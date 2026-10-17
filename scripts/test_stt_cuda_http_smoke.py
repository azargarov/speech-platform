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
from scripts.stt_cuda_http_smoke import _close_and_record, _form, _validate_response


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
