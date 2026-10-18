from __future__ import annotations

import unittest
import asyncio
import json
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from services.stt.admission import UploadGate
from services.stt.domain import FailureCode, Segment, SpeechFailure, TranscriptionResult

from scripts.stt_cuda_http_profile import validate_http_cuda_profile
from scripts.stt_cuda_http_smoke import (
    MeasurementSettings,
    _close_and_record,
    _audio_duration_seconds,
    _form,
    _request_measurement,
    _validate_response,
)


class CUDAHTTPProfileTests(unittest.TestCase):
    @staticmethod
    def configs(*, mode="cuda", compute_type="float16", index=0, minimum=12 * 1024**3):
        app = SimpleNamespace(
            device_mode=mode,
            backend_id="faster-whisper",
            audio_limits=object(),
            backend_options=(("compute_type_cuda", compute_type),),
            models=(
                SimpleNamespace(
                    identity=SimpleNamespace(upstream_revision="b" * 40),
                    manifest_sha256="a" * 64,
                ),
            ),
        )
        deployment = SimpleNamespace(
            cuda_device_index=index,
            minimum_free_gpu_bytes_before_load=minimum,
            artifact_roots={
                "tiny": SimpleNamespace(
                    directory=Path("/models/tiny"),
                    manifest=Path("/models/manifests/tiny.yaml"),
                )
            },
        )
        return app, deployment

    def test_configured_cuda_profile_is_accepted(self):
        profile = validate_http_cuda_profile(*self.configs(), "b" * 40, "a" * 64)
        self.assertEqual(profile["cuda_device_index"], 0)
        self.assertEqual(profile["compute_type"], "float16")

    def test_cpu_or_auto_mode_cannot_override_explicit_cuda(self):
        for mode in ("cpu", "auto"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_http_cuda_profile(*self.configs(mode=mode), "b" * 40, "a" * 64)

    def test_device_and_memory_overrides_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "device index"):
            validate_http_cuda_profile(*self.configs(index=1), "b" * 40, "a" * 64)
        with self.assertRaisesRegex(ValueError, "memory gate"):
            validate_http_cuda_profile(
                *self.configs(minimum=8 * 1024**3), "b" * 40, "a" * 64
            )

    def test_compute_type_override_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "float16"):
            validate_http_cuda_profile(
                *self.configs(compute_type="float32"), "b" * 40, "a" * 64
            )

    def test_model_identity_override_fails_closed(self):
        app, deployment = self.configs()
        with self.assertRaisesRegex(ValueError, "revision"):
            validate_http_cuda_profile(app, deployment, "c" * 40, "a" * 64)
        with self.assertRaisesRegex(ValueError, "manifest"):
            validate_http_cuda_profile(app, deployment, "b" * 40, "d" * 64)

    def test_artifact_path_override_outside_readonly_mount_fails_closed(self):
        app, deployment = self.configs()
        deployment.artifact_roots["tiny"].directory = Path("/other/tiny")
        with self.assertRaisesRegex(ValueError, "under the model mount"):
            validate_http_cuda_profile(app, deployment, "b" * 40, "a" * 64)

    def test_response_validation_returns_metadata_without_transcript(self):
        response = {
            "text": "private transcript",
            "language": "ru",
            "segments": [{"start": 0.0, "end": 1.0, "text": "private transcript"}],
        }
        safe = _validate_response(response, 2.0)
        self.assertEqual(safe["language"], "ru")
        self.assertEqual(safe["segment_count"], 1)
        self.assertNotIn("text", safe)

    def test_response_validation_rejects_nonfinite_timestamps(self):
        response = {
            "text": "private transcript",
            "language": "en",
            "segments": [{"start": float("nan"), "end": 1.0, "text": "private"}],
        }
        with self.assertRaisesRegex(ValueError, "timestamps"):
            _validate_response(response, 2.0)

    def test_extensionless_audio_path_uses_explicit_media_type_and_matching_name(self):
        form = _form(b"fixture", Path("/input/smoke-audio"), "tiny", "audio/mp4")
        disposition, headers, _value = form._fields[0]
        self.assertEqual(disposition["filename"], "smoke-audio.m4a")
        self.assertEqual(headers["Content-Type"], "audio/mp4")

    def test_unsupported_or_inconsistent_audio_media_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            _form(
                b"fixture",
                Path("/input/smoke-audio"),
                "tiny",
                "application/octet-stream",
            )
        with self.assertRaisesRegex(ValueError, "does not match"):
            _form(b"fixture", Path("/input/smoke-audio.wav"), "tiny", "audio/mp4")

    def test_http_harness_uses_test_server_and_production_route_with_fake_application(
        self,
    ):
        from scripts.stt_cuda_http_smoke import build_operations

        class FakeApplication:
            last_media_type = None

            def __init__(self, config, _deployment):
                self.config = config
                self._delegate = SimpleNamespace(
                    runner=SimpleNamespace(child_alive=False)
                )
                self._ready = False
                self._readiness_checks = 0
                self.uploads = UploadGate(1, 1024, 1024, 1024)
                self.lifecycle = SimpleNamespace(
                    ready=self._is_ready,
                    cleanup_unconfirmed=lambda: False,
                )

            def _is_ready(self):
                self._readiness_checks += 1
                return self._ready and self._readiness_checks >= 3

            def start(self):
                self._ready = True

            def close(self):
                self.uploads.close()
                self._ready = False

            def acquire_upload(self):
                return self.uploads.acquire()

            def transcribe_uploaded(self, lease, media_type, *_args, **_kwargs):
                lease.finish()
                FakeApplication.last_media_type = media_type
                return TranscriptionResult(
                    "private transcript", "en", (Segment(0, 1, "private segment"),)
                )

        config = SimpleNamespace(
            default_model="tiny",
            lifecycle=SimpleNamespace(
                model_load_timeout_seconds=2,
                shutdown_drain_timeout_seconds=1,
                process_exit_timeout_seconds=1,
            ),
            admission=SimpleNamespace(
                max_request_bytes=1024,
                max_upload_bytes=1024,
                max_retained_audio_bytes=1024,
                max_uploads=1,
                request_timeout_seconds=2,
            ),
            audio_limits=SimpleNamespace(max_duration_seconds=10),
        )
        state = {
            "app": config,
            "deployment": object(),
            "worker": {"poll_interval_seconds": 0.01},
            "audio_path": None,
            "model_config": SimpleNamespace(
                alias="tiny",
                manifest_sha256="a" * 64,
                identity=SimpleNamespace(upstream_revision="b" * 40),
            ),
            "audio_sha256": "c" * 64,
            "audio_duration_seconds": 1.0,
            "compute_type": "float16",
        }
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "smoke-audio"
            audio.write_bytes(b"fake wav payload")
            state["audio_path"] = audio
            args = SimpleNamespace(
                report=Path(directory) / "report.json", audio_media_type="audio/mp4"
            )
            loop = asyncio.new_event_loop()
            self.addCleanup(loop.close)
            with patch(
                "scripts.stt_cuda_http_smoke.DeferredSTTApplication", FakeApplication
            ):
                operations = build_operations(args, loop, state)
                result = operations["http_worker_integration"]({})
                output = operations["output_validation"](
                    {
                        "dependency_check": {
                            "dependency_versions": {"faster-whisper": "1.2.1"},
                            "lock_sha256": "d" * 64,
                        }
                    }
                )
                shutdown = operations["shutdown_validation"]({})
            shutdown_report = json.loads(
                (Path(directory) / "shutdown-report.json").read_text()
            )
        self.assertEqual(result["request_status"], 200)
        self.assertEqual(FakeApplication.last_media_type, "audio/mp4")
        self.assertEqual(state["http_metadata"]["initial_ready_status"], 503)
        self.assertEqual(state["http_metadata"]["ready_status"], 200)
        self.assertEqual(output["segment_count"], 1)
        self.assertEqual(output["request_count"], 1)
        self.assertEqual(
            output["model_load_seconds"], output["process_cold_model_load_seconds"]
        )
        self.assertEqual(
            output["legacy_transcription_seconds_semantics"],
            "first_request_http_duration",
        )
        self.assertEqual(output["request_measurements"][0]["phase"], "first_request")
        self.assertIsNone(
            output["request_measurements"][0]["transcription_duration_seconds"]
        )
        self.assertNotIn("text", output)
        self.assertEqual(
            shutdown,
            {
                "shutdown_status": "completed_and_confirmed",
                "child_exit_confirmed": True,
                "worker_not_ready": True,
            },
        )
        self.assertEqual(shutdown_report["status"], "completed_and_confirmed")

    def test_sampler_start_failure_still_closes_client_and_persists_safe_reports(self):
        from scripts.stt_cuda_diagnostic import DiagnosticFailure, DiagnosticRunner
        from scripts.stt_cuda_http_smoke import build_operations

        events = []

        class Application:
            def __init__(self, _config, _deployment):
                self._delegate = SimpleNamespace(
                    runner=SimpleNamespace(child_alive=False)
                )
                self.lifecycle = SimpleNamespace(
                    ready=lambda: False,
                    shutdown_drain_timeout_seconds=0.01,
                    process_exit_timeout_seconds=0.01,
                )

        class BrokenSampler:
            def __init__(self, *_args, **_kwargs):
                pass

            def start(self):
                events.append("sampler_start")
                raise RuntimeError("sensitive startup detail")

            def stop(self, _timeout):
                events.append("sampler_stop")
                return {
                    "status": "start_failed",
                    "device_index": 0,
                    "sampling_interval_seconds": 1.0,
                    "sample_count": 0,
                    "sampled_peak_label": "sampled_peak",
                    "sample_counts_by_metric": {},
                    "sampled_peaks": {},
                    "nvml_status": "pending",
                    "process_rss_status": "pending",
                    "cgroup_memory": {"status": "not_sampled", "peak_bytes": None},
                    "missing_data": {},
                    "limitations": [],
                }

        class Client:
            async def start_server(self):
                events.append("server_start")

            async def close(self):
                events.append("client_close")

        config = SimpleNamespace(
            default_model="large-turbo",
            lifecycle=SimpleNamespace(
                model_load_timeout_seconds=2,
                shutdown_drain_timeout_seconds=0.01,
                process_exit_timeout_seconds=0.01,
            ),
            admission=SimpleNamespace(request_timeout_seconds=1),
        )
        state = {
            "app": config,
            "deployment": SimpleNamespace(cuda_device_index=0),
            "worker": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                report=Path(directory) / "harness-report.json",
                request_count=1,
                maximum_request_count=1,
                overall_deadline_seconds=2,
                resource_sample_interval_seconds=1,
            )
            loop = asyncio.new_event_loop()
            self.addCleanup(loop.close)
            with (
                patch(
                    "scripts.stt_cuda_http_smoke.DeferredSTTApplication", Application
                ),
                patch("scripts.stt_cuda_http_smoke.create_http_app", lambda app: app),
                patch("scripts.stt_cuda_http_smoke.TestServer", lambda app: app),
                patch(
                    "scripts.stt_cuda_http_smoke.TestClient", lambda _server: Client()
                ),
                patch("scripts.stt_cuda_http_smoke.ResourceSampler", BrokenSampler),
            ):
                operations = build_operations(args, loop, state)
                with self.assertRaises(DiagnosticFailure) as raised:
                    DiagnosticRunner(
                        args.report, stages=("http_worker_integration",)
                    ).run(
                        {
                            "http_worker_integration": operations[
                                "http_worker_integration"
                            ]
                        }
                    )
            report_text = args.report.read_text()
            report = json.loads(report_text)
            shutdown_report = json.loads(
                (Path(directory) / "shutdown-report.json").read_text()
            )
        self.assertEqual(events, ["sampler_start", "client_close", "sampler_stop"])
        self.assertEqual(shutdown_report["status"], "completed_and_confirmed")
        self.assertEqual(
            report["stages"][0]["exception"]["resource_observations"]["status"],
            "start_failed",
        )
        self.assertNotIn("sensitive startup detail", report_text)
        self.assertEqual(raised.exception.stage, "http_worker_integration")

    def test_aggregate_deadline_prevents_a_later_sequential_request(self):
        from scripts.stt_cuda_diagnostic import DiagnosticFailure, DiagnosticRunner
        from scripts.stt_cuda_http_smoke import build_operations

        class Clock:
            value = 0.0

            def __call__(self):
                return self.value

        clock = Clock()
        events = []

        class Response:
            status = 200

            async def json(self):
                return {
                    "text": "private transcript",
                    "language": "ru",
                    "segments": [{"start": 0.0, "end": 1.0, "text": "private"}],
                }

        class Client:
            async def start_server(self):
                pass

            async def get(self, path):
                return SimpleNamespace(
                    status=200,
                    json=lambda: asyncio.sleep(
                        0,
                        result={"status": "alive"}
                        if path == "/healthz"
                        else {"status": "ready"},
                    ),
                )

            async def post(self, *_args, **_kwargs):
                events.append("request")
                clock.value += 1.1
                return Response()

            async def close(self):
                pass

        class Application:
            def __init__(self, _config, _deployment):
                self._delegate = SimpleNamespace(
                    runner=SimpleNamespace(child_alive=False)
                )
                self.lifecycle = SimpleNamespace(
                    ready=lambda: False,
                    shutdown_drain_timeout_seconds=1,
                    process_exit_timeout_seconds=1,
                )

        config = SimpleNamespace(
            default_model="large-turbo",
            lifecycle=SimpleNamespace(
                model_load_timeout_seconds=2,
                shutdown_drain_timeout_seconds=1,
                process_exit_timeout_seconds=1,
            ),
            admission=SimpleNamespace(
                max_request_bytes=1024,
                request_timeout_seconds=5,
            ),
            audio_limits=SimpleNamespace(max_duration_seconds=10),
        )
        state = {
            "app": config,
            "deployment": SimpleNamespace(cuda_device_index=0),
            "worker": {"poll_interval_seconds": 0.01},
            "audio_duration_seconds": 1.0,
            "audio_sha256": "c" * 64,
            "model_config": SimpleNamespace(
                alias="large-turbo",
                manifest_sha256="a" * 64,
                identity=SimpleNamespace(upstream_revision="b" * 40),
            ),
            "compute_type": "float16",
        }
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "smoke-audio.m4a"
            audio.write_bytes(b"fixture")
            state["audio_path"] = audio
            args = SimpleNamespace(
                report=Path(directory) / "harness-report.json",
                audio_media_type="audio/mp4",
                request_count=3,
                maximum_request_count=3,
                overall_deadline_seconds=10,
                resource_sample_interval_seconds=None,
            )
            loop = asyncio.new_event_loop()
            self.addCleanup(loop.close)
            with (
                patch(
                    "scripts.stt_cuda_http_smoke.DeferredSTTApplication", Application
                ),
                patch("scripts.stt_cuda_http_smoke.create_http_app", lambda app: app),
                patch("scripts.stt_cuda_http_smoke.TestServer", lambda app: app),
                patch(
                    "scripts.stt_cuda_http_smoke.TestClient", lambda _server: Client()
                ),
            ):
                operations = build_operations(args, loop, state, clock=clock)
                with self.assertRaises(DiagnosticFailure) as raised:
                    DiagnosticRunner(
                        args.report, stages=("http_worker_integration",)
                    ).run(
                        {
                            "http_worker_integration": operations[
                                "http_worker_integration"
                            ]
                        }
                    )
            report_text = args.report.read_text()
            shutdown_report = json.loads(
                (Path(directory) / "shutdown-report.json").read_text()
            )
        self.assertEqual(events, ["request", "request"])
        self.assertEqual(raised.exception.stage, "http_worker_integration")
        self.assertNotIn("private transcript", report_text)
        self.assertEqual(shutdown_report["status"], "completed_and_confirmed")

    def test_measurement_configuration_defaults_to_one_and_enforces_bounds(self):
        self.assertEqual(
            MeasurementSettings.from_args(SimpleNamespace()).request_count, 1
        )
        for args in (
            SimpleNamespace(request_count=0),
            SimpleNamespace(request_count=2),
            SimpleNamespace(request_count=1, maximum_request_count=0),
            SimpleNamespace(
                request_count=3, maximum_request_count=2, overall_deadline_seconds=10
            ),
            SimpleNamespace(
                request_count=1,
                maximum_request_count=1001,
                overall_deadline_seconds=10,
            ),
            SimpleNamespace(
                request_count=1,
                maximum_request_count=1,
                overall_deadline_seconds=10,
                resource_sample_interval_seconds=0.01,
            ),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                MeasurementSettings.from_args(args)
        valid = MeasurementSettings.from_args(
            SimpleNamespace(
                request_count=3,
                maximum_request_count=5,
                overall_deadline_seconds=10,
                resource_sample_interval_seconds=0.5,
            )
        )
        self.assertEqual(valid.request_count, 3)

    def test_request_timing_and_rtf_are_derived_without_transcript_data(self):
        measured = _request_measurement(
            2,
            0.5,
            2.0,
            {
                "language": "ru",
                "segment_count": 4,
                "timestamp_bounds_valid": True,
            },
        )
        self.assertEqual(measured["phase"], "subsequent_warm_request")
        self.assertEqual(measured["request_real_time_factor"], 0.25)
        self.assertIsNone(measured["transcription_duration_seconds"])
        self.assertNotIn("text", measured)

    def test_audio_duration_uses_container_metadata_without_retaining_payload(self):
        class Stream:
            type = "audio"
            duration = 42
            time_base = 0.5

        class Container:
            streams = [Stream()]
            duration = None

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class AudioLibrary:
            @staticmethod
            def open(path, mode):
                self.assertEqual(path, "/private/fixture.m4a")
                self.assertEqual(mode, "r")
                return Container()

        duration = _audio_duration_seconds(
            Path("/private/fixture.m4a"), av_module=AudioLibrary
        )
        self.assertEqual(duration, 21.0)

    def test_sequential_requests_are_validated_before_the_next_request(self):
        from scripts.stt_cuda_http_smoke import build_operations

        events = []

        class SequentialApplication:
            def __init__(self, config, _deployment):
                self.config = config
                self._delegate = SimpleNamespace(
                    runner=SimpleNamespace(child_alive=False)
                )
                self._ready = False
                self.uploads = UploadGate(1, 1024, 1024, 1024)
                self.lifecycle = SimpleNamespace(
                    ready=lambda: self._ready,
                    cleanup_unconfirmed=lambda: False,
                )

            def start(self):
                self._ready = True

            def close(self):
                self.uploads.close()
                self._ready = False

            def acquire_upload(self):
                return self.uploads.acquire()

            def transcribe_uploaded(self, lease, *_args, **_kwargs):
                lease.finish()
                events.append("request")
                return TranscriptionResult(
                    "sensitive transcript", "ru", (Segment(0, 1, "sensitive"),)
                )

        config = SimpleNamespace(
            default_model="large-turbo",
            lifecycle=SimpleNamespace(
                model_load_timeout_seconds=2,
                shutdown_drain_timeout_seconds=1,
                process_exit_timeout_seconds=1,
            ),
            admission=SimpleNamespace(
                max_request_bytes=1024,
                max_upload_bytes=1024,
                max_retained_audio_bytes=1024,
                max_uploads=1,
                request_timeout_seconds=2,
            ),
            audio_limits=SimpleNamespace(max_duration_seconds=10),
        )
        state = {
            "app": config,
            "deployment": SimpleNamespace(cuda_device_index=0),
            "worker": {"poll_interval_seconds": 0.001},
            "audio_duration_seconds": 2.0,
            "model_config": SimpleNamespace(
                alias="large-turbo",
                manifest_sha256="a" * 64,
                identity=SimpleNamespace(upstream_revision="b" * 40),
            ),
            "audio_sha256": "c" * 64,
            "compute_type": "float16",
        }
        original_validate = _validate_response

        def record_validation(*args):
            events.append("validate")
            return original_validate(*args)

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "input.m4a"
            audio.write_bytes(b"small fixture")
            state["audio_path"] = audio
            args = SimpleNamespace(
                report=Path(directory) / "report.json",
                audio_media_type="audio/mp4",
                request_count=3,
                maximum_request_count=3,
                overall_deadline_seconds=10,
                resource_sample_interval_seconds=None,
            )
            loop = asyncio.new_event_loop()
            self.addCleanup(loop.close)
            with (
                patch(
                    "scripts.stt_cuda_http_smoke.DeferredSTTApplication",
                    SequentialApplication,
                ),
                patch(
                    "scripts.stt_cuda_http_smoke._validate_response", record_validation
                ),
            ):
                operations = build_operations(args, loop, state)
                operations["http_worker_integration"]({})
                result = operations["output_validation"](
                    {
                        "dependency_check": {
                            "dependency_versions": {},
                            "lock_sha256": "d" * 64,
                        }
                    }
                )
        self.assertEqual(events, ["request", "validate"] * 3)
        self.assertEqual(
            [item["request_index"] for item in result["request_measurements"]],
            [1, 2, 3],
        )
        self.assertEqual(
            [item["phase"] for item in result["request_measurements"]],
            ["first_request", "subsequent_warm_request", "subsequent_warm_request"],
        )
        self.assertNotIn("sensitive transcript", repr(result))

    def test_non_200_http_failure_persists_only_safe_response_metadata(self):
        import json

        from scripts.stt_cuda_diagnostic import DiagnosticFailure, DiagnosticRunner
        from scripts.stt_cuda_http_smoke import build_operations

        class FailingApplication:
            def __init__(self, config, _deployment):
                self.config = config
                self._delegate = SimpleNamespace(
                    runner=SimpleNamespace(child_alive=False)
                )
                self._ready = False
                self.uploads = UploadGate(1, 1024, 1024, 1024)
                self.lifecycle = SimpleNamespace(
                    ready=lambda: self._ready,
                    cleanup_unconfirmed=lambda: False,
                )

            def start(self):
                self._ready = True

            def close(self):
                self.uploads.close()
                self._ready = False

            def acquire_upload(self):
                return self.uploads.acquire()

            def transcribe_uploaded(self, lease, *_args, **_kwargs):
                lease.finish()
                raise SpeechFailure(
                    FailureCode.DECODE_FAILED,
                    "sensitive path /private/audio.wav and transcript do not persist",
                )

        config = SimpleNamespace(
            default_model="tiny",
            lifecycle=SimpleNamespace(
                model_load_timeout_seconds=2,
                shutdown_drain_timeout_seconds=1,
                process_exit_timeout_seconds=1,
            ),
            admission=SimpleNamespace(
                max_request_bytes=1024,
                max_upload_bytes=1024,
                max_retained_audio_bytes=1024,
                max_uploads=1,
                request_timeout_seconds=2,
            ),
            audio_limits=SimpleNamespace(max_duration_seconds=10),
        )
        state = {
            "app": config,
            "deployment": object(),
            "worker": {"poll_interval_seconds": 0.01},
            "audio_path": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "smoke-audio"
            audio.write_bytes(b"fake wav payload")
            state["audio_path"] = audio
            args = SimpleNamespace(
                report=Path(directory) / "report.json", audio_media_type="audio/mp4"
            )
            loop = asyncio.new_event_loop()
            self.addCleanup(loop.close)
            with patch(
                "scripts.stt_cuda_http_smoke.DeferredSTTApplication",
                FailingApplication,
            ):
                operations = build_operations(args, loop, state)
                runner = DiagnosticRunner(
                    args.report,
                    stages=("http_worker_integration",),
                )
                with self.assertRaises(DiagnosticFailure):
                    runner.run(
                        {
                            "http_worker_integration": operations[
                                "http_worker_integration"
                            ]
                        }
                    )
            report_text = args.report.read_text()
            report = json.loads(report_text)
            shutdown_report = json.loads(
                (Path(directory) / "shutdown-report.json").read_text()
            )
        exception = report["stages"][0]["exception"]
        self.assertEqual(exception["http_status"], 422)
        self.assertEqual(exception["public_error_code"], "decode_failed")
        self.assertEqual(exception["request_stage"], "transcription_response")
        self.assertEqual(exception["failure_category"], "application_error_response")
        self.assertNotIn("sensitive path", report_text)
        self.assertNotIn("private/audio.wav", report_text)
        self.assertNotIn("private segment", report_text)
        self.assertEqual(shutdown_report["status"], "completed_and_confirmed")

    def test_http_error_metadata_rejects_unrecognized_code_and_message(self):
        import json

        from scripts.stt_cuda_diagnostic import DiagnosticFailure, DiagnosticRunner
        from scripts.stt_cuda_http_smoke import HTTPIntegrationFailure

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            failure = HTTPIntegrationFailure(
                500,
                {
                    "code": "credential=do-not-store",
                    "message": "secret /home/private/transcript",
                },
            )
            runner = DiagnosticRunner(path, stages=("http_worker_integration",))
            with self.assertRaises(DiagnosticFailure):
                runner.run(
                    {
                        "http_worker_integration": lambda _state: (_ for _ in ()).throw(
                            failure
                        )
                    }
                )
            contents = path.read_text()
            report = json.loads(contents)
        exception = report["stages"][0]["exception"]
        self.assertEqual(exception["http_status"], 500)
        self.assertNotIn("public_error_code", exception)
        self.assertEqual(exception["failure_category"], "unrecognized_error_code")
        self.assertNotIn("credential", contents)
        self.assertNotIn("secret", contents)
        self.assertNotIn("private transcript", contents)

    def test_partial_measurements_are_sanitized_in_failure_report(self):
        from scripts.stt_cuda_diagnostic import DiagnosticFailure, DiagnosticRunner
        from scripts.stt_cuda_http_smoke import HTTPIntegrationFailure

        measurement = {
            "request_index": 1,
            "phase": "first_request",
            "http_status": 200,
            "request_duration_seconds": 0.5,
            "transcription_duration_seconds": None,
            "transcription_duration_status": "not_exposed_by_worker_contract",
            "audio_duration_seconds": 2.0,
            "request_real_time_factor": 0.25,
            "language": "ru",
            "segment_count": 2,
            "timestamp_bounds_valid": True,
            "text": "sensitive transcript must be discarded",
            "private_path": "/home/private/audio.m4a",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            runner = DiagnosticRunner(path, stages=("http_worker_integration",))
            failure = HTTPIntegrationFailure(
                503,
                {"code": "not_ready", "message": "private diagnostic"},
                [measurement],
            )
            with self.assertRaises(DiagnosticFailure):
                runner.run(
                    {
                        "http_worker_integration": lambda _state: (_ for _ in ()).throw(
                            failure
                        )
                    }
                )
            report_text = path.read_text()
            report = json.loads(report_text)
        exception = report["stages"][0]["exception"]
        self.assertEqual(len(exception["request_measurements"]), 1)
        self.assertEqual(
            exception["request_measurements"][0]["request_real_time_factor"], 0.25
        )
        self.assertNotIn("sensitive transcript", report_text)
        self.assertNotIn("private_path", report_text)
        self.assertNotIn("/home/private", report_text)

    def test_shutdown_report_distinguishes_unconfirmed_and_failed_or_timed_out(self):
        class Client:
            async def close(self):
                return None

        async def failed_close():
            raise RuntimeError("credential=do-not-record")

        async def timed_out_close():
            raise asyncio.TimeoutError

        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        with tempfile.TemporaryDirectory() as directory:
            unconfirmed_path = Path(directory) / "unconfirmed.json"
            application = SimpleNamespace(
                _delegate=SimpleNamespace(runner=SimpleNamespace(child_alive=True)),
                lifecycle=SimpleNamespace(ready=lambda: True),
            )
            unconfirmed = loop.run_until_complete(
                _close_and_record(
                    Client(), application, {}, unconfirmed_path, timeout_seconds=1
                )
            )
            self.assertEqual(unconfirmed["status"], "attempted_but_unconfirmed")
            self.assertFalse(unconfirmed["child_exit_confirmed"])
            self.assertFalse(unconfirmed["worker_not_ready"])

            for close, category in (
                (failed_close, "client_close_failed"),
                (timed_out_close, "deadline_exceeded"),
            ):
                with self.subTest(category=category):
                    path = Path(directory) / f"{category}.json"
                    report = loop.run_until_complete(
                        _close_and_record(
                            SimpleNamespace(close=close),
                            application,
                            {},
                            path,
                            timeout_seconds=1,
                        )
                    )
                    self.assertEqual(report["status"], "failed_or_timed_out")
                    self.assertEqual(report["failure_category"], category)
                    self.assertNotIn("credential", path.read_text())


if __name__ == "__main__":
    unittest.main()
