from __future__ import annotations

import json
import io
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.stt.domain import OperationContext
from scripts.stt_cuda_diagnostic import (
    DiagnosticFailure,
    DiagnosticPolicyFailure,
    DiagnosticRunner,
    STARTUP_STAGES,
    STAGES,
    assert_explicit_cuda,
    atomic_write_report,
    build_startup_operations,
    locked_versions,
    load_configurations,
    main,
    validate_cuda_profile,
    transcribe_with_production_decoder,
)


class DiagnosticRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.report = Path(self.temporary.name) / "diagnostic.json"
        self.clock_value = 0.0

    def test_harness_uses_production_decoder_and_passes_pcm_to_model(self):
        audio_path = Path(self.temporary.name) / "audio.bin"
        audio_path.write_bytes(b"private fixture bytes")
        decoded_audio = object()
        loaded_model = SimpleNamespace(_options=object(), _modules=object())

        class RecordingModel:
            def transcribe(self, audio, **kwargs):
                self.audio = audio
                self.kwargs = kwargs
                return iter(()), SimpleNamespace(language="ru")

        model = RecordingModel()
        with patch(
            "services.stt.backends.faster_whisper._decode_audio",
            return_value=decoded_audio,
        ) as decode:
            transcribe_with_production_decoder(model, loaded_model, audio_path, 1)

        decoded_bytes, options, context, modules = decode.call_args.args
        self.assertEqual(decoded_bytes, b"private fixture bytes")
        self.assertIs(options, loaded_model._options)
        self.assertIs(modules, loaded_model._modules)
        self.assertIsInstance(context, OperationContext)
        self.assertIs(model.audio, decoded_audio)
        self.assertEqual(
            model.kwargs,
            {
                "language": None,
                "task": "transcribe",
                "beam_size": 1,
                "vad_filter": False,
            },
        )

    def clock(self):
        self.clock_value += 0.125
        return self.clock_value

    def operations(self, *, failure_stage=None, exception=None):
        calls = []
        model = FakeModel(calls, failure_stage, exception)
        self.fake_model = model

        def report_mount(_state):
            calls.append(("report_mount_validation", None))
            return {"write": "pass", "atomic_replace": "pass"}

        def dependency(_state):
            calls.append(("dependency_check", None))
            return {"faster-whisper": "1.2.1"}

        def parse_configuration(_state):
            calls.append(("configuration_parsing", None))
            return {"application_device_mode": "cuda"}

        def cuda_profile(_state):
            calls.append(("cuda_profile_validation", None))
            return {"cuda_device_index": 0}

        def artifacts(_state):
            calls.append(("artifact_validation", None))
            if failure_stage == "artifact_validation":
                raise exception or ValueError("artifact failed")
            return {
                "model_alias": "tiny-test",
                "model_revision": "d" * 40,
                "manifest_sha256": "a" * 64,
                "audio_sha256": "b" * 64,
            }

        def load(_state):
            calls.append(("model_load", None))
            if failure_stage == "model_load":
                if exception is not None:
                    raise exception
                try:
                    raise TypeError("takes 2 positional arguments but 3 were given")
                except TypeError as cause:
                    raise RuntimeError("model construction failed") from cause
            return model

        def transcribe(_state):
            calls.append(("transcribe_call", None))
            if failure_stage == "transcribe_call":
                raise exception or TypeError("transcribe call failed")
            segments, info = model.transcribe(
                "fixture", language=None, task="transcribe"
            )
            _state.update(segments_iterator=segments, info=info)
            return True

        def iterate(_state):
            calls.append(("segment_iteration", None))
            _state["segments"] = list(_state["segments_iterator"])
            return _state["segments"]

        def validate(_state):
            calls.append(("output_validation", None))
            if failure_stage == "output_validation":
                raise exception or ValueError("output failed")
            return {
                "language": "ru",
                "segment_count": 1,
                "timestamp_bounds_valid": True,
                "text": "private transcript must not be serialized",
                "device": "cuda",
                "compute_type": "float16",
            }

        return {
            "report_mount_validation": report_mount,
            "dependency_check": dependency,
            "configuration_parsing": parse_configuration,
            "cuda_profile_validation": cuda_profile,
            "artifact_validation": artifacts,
            "model_load": load,
            "transcribe_call": transcribe,
            "segment_iteration": iterate,
            "output_validation": validate,
        }, calls

    def test_success_calls_and_consumes_lazy_generator_and_writes_safe_report(self):
        operations, calls = self.operations()
        report = DiagnosticRunner(self.report, clock=self.clock).run(operations)
        self.assertEqual(report["outcome"], "pass")
        self.assertEqual([item["name"] for item in report["stages"]], list(STAGES))
        self.assertTrue(
            all(item["duration_seconds"] == 0.125 for item in report["stages"])
        )
        self.assertEqual([name for name, _ in calls], list(STAGES))
        self.assertEqual(self.fake_model.last_call, ("fixture", None, "transcribe"))
        saved = self.report.read_text()
        self.assertNotIn("private transcript", saved)
        self.assertEqual(json.loads(saved)["result"]["segment_count"], 1)

    def test_failure_is_attributed_to_model_construction(self):
        operations, _ = self.operations(
            failure_stage="model_load",
        )
        with self.assertRaises(DiagnosticFailure) as caught:
            DiagnosticRunner(self.report, clock=self.clock).run(operations)
        self.assertEqual(caught.exception.stage, "model_load")
        data = json.loads(self.report.read_text())
        model_stage = next(
            item for item in data["stages"] if item["name"] == "model_load"
        )
        self.assertEqual(model_stage["outcome"], "fail")
        self.assertEqual(model_stage["exception"]["type"], "RuntimeError")
        self.assertEqual(model_stage["exception"]["causes"][0]["type"], "TypeError")
        self.assertIn(
            "takes 2 positional arguments",
            model_stage["exception"]["causes"][0]["message"],
        )

    def test_failure_is_attributed_to_transcribe_call(self):
        operations, _ = self.operations(
            failure_stage="transcribe_call",
            exception=TypeError("got an unexpected keyword argument 'made_up'"),
        )
        with self.assertRaises(DiagnosticFailure) as caught:
            DiagnosticRunner(self.report, clock=self.clock).run(operations)
        self.assertEqual(caught.exception.stage, "transcribe_call")

    def test_lazy_generator_failure_is_attributed_to_iteration(self):
        operations, _ = self.operations(
            failure_stage="segment_iteration",
            exception=TypeError("segment conversion failed"),
        )
        with self.assertRaises(DiagnosticFailure) as caught:
            DiagnosticRunner(self.report, clock=self.clock).run(operations)
        self.assertEqual(caught.exception.stage, "segment_iteration")
        self.assertEqual(
            json.loads(self.report.read_text())["failed_stage"], "segment_iteration"
        )

    def test_output_validation_failure_is_attributed(self):
        operations, _ = self.operations(failure_stage="output_validation")
        with self.assertRaises(DiagnosticFailure) as caught:
            DiagnosticRunner(self.report, clock=self.clock).run(operations)
        self.assertEqual(caught.exception.stage, "output_validation")

    def test_artifact_and_transcribe_call_failures_have_individual_stages(self):
        for stage in ("artifact_validation", "transcribe_call"):
            with self.subTest(stage=stage):
                operations, _ = self.operations(
                    failure_stage=stage,
                    exception=(
                        TypeError("got an unexpected keyword argument 'made_up'")
                        if stage == "transcribe_call"
                        else ValueError("validation failed")
                    ),
                )
                with self.assertRaises(DiagnosticFailure) as caught:
                    DiagnosticRunner(self.report, clock=self.clock).run(operations)
                self.assertEqual(caught.exception.stage, stage)

    def test_diagnostics_redact_paths_secrets_transcripts_and_absolute_frame_paths(
        self,
    ):
        sensitive = TypeError(
            "unexpected input /home/person/private/audio.wav api_key=abc123 transcript words here"
        )
        operations, _ = self.operations(
            failure_stage="transcribe_call", exception=sensitive
        )
        with self.assertRaises(DiagnosticFailure):
            DiagnosticRunner(self.report, clock=self.clock).run(operations)
        serialized = self.report.read_text()
        for value in ("/home/person", "audio.wav", "abc123", "transcript words"):
            self.assertNotIn(value, serialized)
        transcribe_stage = next(
            item
            for item in json.loads(serialized)["stages"]
            if item["name"] == "transcribe_call"
        )
        diagnostic = transcribe_stage["exception"]
        self.assertTrue(diagnostic["frames"])
        self.assertTrue(all("/" not in frame["file"] for frame in diagnostic["frames"]))
        self.assertEqual(diagnostic["message"], "<message-redacted>")

    def test_atomic_report_is_private_and_replaces_without_temporary_residue(self):
        atomic_write_report(self.report, {"outcome": "running"})
        self.assertEqual(stat.S_IMODE(self.report.stat().st_mode), 0o640)
        atomic_write_report(self.report, {"outcome": "pass"})
        self.assertEqual(json.loads(self.report.read_text()), {"outcome": "pass"})
        self.assertEqual(list(Path(self.temporary.name).glob(".stt-diagnostic-*")), [])

    def test_no_cpu_fallback_is_accepted(self):
        assert_explicit_cuda("cuda", "cuda", "cuda", True)
        for values in (
            ("auto", "cuda", "cuda", True),
            ("cuda", "cpu", "cpu", True),
            ("cuda", "cuda", "cpu", True),
            ("cuda", "cuda", "cuda", False),
        ):
            with self.subTest(values=values), self.assertRaises(RuntimeError):
                assert_explicit_cuda(*values)

    def test_lock_versions_parser_reads_pinned_entries(self):
        lock = Path(self.temporary.name) / "lock.txt"
        lock.write_text(
            "# lock\n"
            "aiohttp==3.14.5\n"
            "    --hash=sha256:abc\n"
            "CTranslate2==4.8.3\n"
            "    --hash=sha256:def\n"
        )
        parsed = locked_versions(lock)
        self.assertEqual(parsed, {"aiohttp": "3.14.5", "ctranslate2": "4.8.3"})

    def write_configs(
        self, *, mode="cpu", device_index=0, memory_bytes=None, malformed=False
    ):
        root = Path(__file__).resolve().parents[1]
        application = (root / "configs/stt-application-cpu.example.yaml").read_text()
        application = application.replace(
            "REPLACE_WITH_40_OR_64_HEX_SOURCE_REVISION", "a" * 40
        ).replace("REPLACE_WITH_CANONICAL_MANIFEST_SHA256", "b" * 64)
        if mode == "cuda":
            application = application.replace("mode: cpu", "mode: cuda").replace(
                "preference: [cpu]", "preference: [cuda]"
            )
        if malformed:
            application = application.replace("schema_version: 3", "schema_version: 99")
        app_path = Path(self.temporary.name) / f"application-{mode}.yaml"
        app_path.write_text(application)

        if memory_bytes is None:
            deployment = (root / "configs/stt-deployment-cpu.example.yaml").read_text()
        else:
            deployment = (root / "configs/stt-deployment-cuda.example.yaml").read_text()
            deployment = deployment.replace(
                "REPLACE_WITH_REVIEWED_MEMORY_REQUIREMENT", str(memory_bytes)
            ).replace("cuda_device_index: 0", f"cuda_device_index: {device_index}")
        deployment_path = Path(self.temporary.name) / f"deployment-{mode}.yaml"
        deployment_path.write_text(deployment)
        return app_path, deployment_path

    def test_generic_configuration_parsing_accepts_cpu_and_cuda_profiles(self):
        for mode, memory in (("cpu", None), ("cuda", 12 * 1024**3)):
            with self.subTest(mode=mode):
                app_path, deployment_path = self.write_configs(
                    mode=mode, memory_bytes=memory
                )
                app, deployment = load_configurations(app_path, deployment_path)
                self.assertEqual(app.device_mode, mode)
                self.assertEqual(deployment.cuda_device_index, 0)

    def test_malformed_config_fails_configuration_parsing_with_safe_code(self):
        app_path, deployment_path = self.write_configs(malformed=True)
        args = SimpleNamespace(
            application_config=str(app_path),
            deployment_config=str(deployment_path),
            report=str(self.report),
        )
        runner = DiagnosticRunner(
            self.report, clock=self.clock, stages=STARTUP_STAGES, cuda_requested=False
        )
        with self.assertRaises(DiagnosticFailure) as caught:
            runner.run(build_startup_operations(args))
        self.assertEqual(caught.exception.stage, "configuration_parsing")
        report = json.loads(self.report.read_text())
        stage = next(
            item for item in report["stages"] if item["name"] == "configuration_parsing"
        )
        self.assertEqual(stage["diagnostic_code"], "configuration_invalid")
        self.assertEqual(stage["exception"]["message"], "<message-suppressed>")

    def test_cpu_config_fails_only_explicit_cuda_profile_validation(self):
        app_path, deployment_path = self.write_configs()
        app, deployment = load_configurations(app_path, deployment_path)
        with self.assertRaises(DiagnosticPolicyFailure) as caught:
            validate_cuda_profile(app, deployment)
        self.assertEqual(
            caught.exception.diagnostic_code, "cuda_profile_explicit_cuda_required"
        )

        runner = DiagnosticRunner(
            self.report, clock=self.clock, stages=("cuda_profile_validation",)
        )
        with self.assertRaises(DiagnosticFailure) as stage_failure:
            runner.run(
                {
                    "cuda_profile_validation": lambda _state: validate_cuda_profile(
                        app, deployment
                    )
                }
            )
        report = json.loads(self.report.read_text())
        self.assertEqual(stage_failure.exception.stage, "cuda_profile_validation")
        self.assertEqual(
            report["stages"][0]["diagnostic_code"],
            "cuda_profile_explicit_cuda_required",
        )

    def test_cuda_profile_requires_approved_device_and_memory_gate(self):
        app_path, deployment_path = self.write_configs(
            mode="cuda", memory_bytes=12 * 1024**3
        )
        app, deployment = load_configurations(app_path, deployment_path)
        self.assertEqual(validate_cuda_profile(app, deployment)["cuda_device_index"], 0)

        _, wrong_device_path = self.write_configs(
            mode="cuda", device_index=1, memory_bytes=12 * 1024**3
        )
        _, wrong_device = load_configurations(app_path, wrong_device_path)
        with self.assertRaises(DiagnosticPolicyFailure) as wrong_device_error:
            validate_cuda_profile(app, wrong_device)
        self.assertEqual(
            wrong_device_error.exception.diagnostic_code,
            "cuda_profile_device_index_mismatch",
        )

        _, low_memory_path = self.write_configs(
            mode="cuda", memory_bytes=12 * 1024**3 - 1
        )
        _, low_memory = load_configurations(app_path, low_memory_path)
        with self.assertRaises(DiagnosticPolicyFailure) as memory_error:
            validate_cuda_profile(app, low_memory)
        self.assertEqual(
            memory_error.exception.diagnostic_code,
            "cuda_profile_memory_gate_insufficient",
        )

    def test_startup_only_mode_never_runs_cuda_profile_validation(self):
        app_path, deployment_path = self.write_configs()
        with patch(
            "scripts.stt_cuda_diagnostic.validate_cuda_profile",
            side_effect=AssertionError("must not run in startup-only mode"),
        ) as validate:
            result = main(
                [
                    "--startup-only",
                    "--application-config",
                    str(app_path),
                    "--deployment-config",
                    str(deployment_path),
                    "--report",
                    str(self.report),
                ]
            )
        self.assertEqual(result, 0)
        validate.assert_not_called()
        report = json.loads(self.report.read_text())
        self.assertFalse(report["cuda_requested"])
        self.assertEqual(report["metadata"]["mode"], "startup_only")
        self.assertEqual(
            [item["name"] for item in report["stages"]], list(STARTUP_STAGES)
        )

    def test_report_mount_failure_stops_before_configuration_or_model_work(self):
        app_path, deployment_path = self.write_configs(
            mode="cuda", memory_bytes=12 * 1024**3
        )
        missing_report = Path(self.temporary.name) / "missing" / "report.json"
        with (
            patch(
                "scripts.stt_cuda_diagnostic.build_operations",
                side_effect=AssertionError("model operations must not be built"),
            ) as build,
            patch(
                "scripts.stt_cuda_diagnostic.load_configurations",
                side_effect=AssertionError("configuration must not be parsed"),
            ) as load,
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            result = main(
                [
                    "--application-config",
                    str(app_path),
                    "--deployment-config",
                    str(deployment_path),
                    "--audio",
                    "fixture",
                    "--audio-checksum-file",
                    "checksum",
                    "--report",
                    str(missing_report),
                ]
            )
        self.assertEqual(result, 20)
        self.assertFalse(missing_report.exists())
        build.assert_not_called()
        load.assert_not_called()
        safe = json.loads(output.getvalue())
        self.assertEqual(safe["failed_stage"], "report_mount_validation")
        self.assertEqual(
            safe["diagnostic_code"], "report_mount_directory_missing_or_unsafe"
        )


class FakeModel:
    def __init__(self, calls, failure_stage, exception):
        self.calls = calls
        self.failure_stage = failure_stage
        self.exception = exception
        self.last_call = None

    def transcribe(self, audio, *, language, task):
        self.last_call = (audio, language, task)
        if self.failure_stage == "transcribe_call":
            raise self.exception or TypeError("transcribe call failed")
        return self.segments, SimpleNamespace(language="ru")

    @property
    def segments(self):
        if self.failure_stage == "segment_iteration":

            def broken():
                yield SimpleNamespace(start=0.0, end=0.2, text="hidden")
                raise self.exception or TypeError("generator failed")

            return broken()
        return iter([SimpleNamespace(start=0.0, end=0.2, text="hidden")])


if __name__ == "__main__":
    unittest.main()
