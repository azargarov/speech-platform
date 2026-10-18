import threading
import tempfile
import time
import unittest
import http.client
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path

from services.stt.application import create_application
from services.stt.config import ArtifactRoot, DeploymentConfig, load_application_config
from services.stt.domain import (
    ArtifactIdentity,
    DeviceCapabilities,
    FailureCode,
    ModelIdentity,
    ModelSelection,
    OperationContext,
    SpeechFailure,
    TranscriptionRequest,
    VerifiedArtifact,
)
from services.stt.lifecycle import Lifecycle, ModelState, WorkerState
from services.stt.supervisor import InferenceSupervisor
from services.stt.testing import FakeBackendFactory
from services.worker.server import handler, load_config

from services.stt.tests.test_config_artifacts import application_data


class FakeDeviceProbe:
    def __init__(self, devices=None):
        self.devices = devices or (DeviceCapabilities("cpu", "cpu-test"),)

    def discover(self, _context):
        return self.devices


class FakeArtifactStore:
    def verify(self, model, root):
        return VerifiedArtifact(
            ArtifactIdentity(model.manifest_sha256, model.artifact_format),
            root.directory,
        )


def supervisor(
    behavior="success",
    duration=0.0,
    grace=0.05,
    load_timeout=1,
    *,
    process_control=None,
    response_reader=None,
    response_poller=None,
    exit_timeout=0.5,
):
    identity = ModelIdentity("whisper", "revision-1")
    selection = ModelSelection(
        "general", identity, "primary", ArtifactIdentity("a" * 64, "fake-v1")
    )
    backend = FakeBackendFactory(behavior, duration)
    return InferenceSupervisor(
        backend,
        selection,
        VerifiedArtifact(selection.artifact_identity, Path("fake-artifact-unused")),
        DeviceCapabilities("cpu", "cpu-test"),
        backend().capabilities(),
        grace,
        exit_timeout,
        65536,
        load_timeout,
        process_control=process_control,
        response_reader=response_reader,
        response_poller=response_poller,
    )


class ControlledProcess:
    def __init__(self):
        self.hold_exit_confirmation = False

    def is_alive(self, process):
        return self.hold_exit_confirmation or process.is_alive()

    @staticmethod
    def terminate(process):
        process.terminate()

    @staticmethod
    def kill(process):
        process.kill()

    @staticmethod
    def join(process, timeout):
        process.join(timeout)


class InjectedResponseReader:
    def __init__(self, mode):
        self.mode = mode
        self.calls = 0

    def __call__(self, pipe, maximum):
        self.calls += 1
        payload = pipe.recv_bytes(maximum)
        if self.calls == 1:
            return payload
        if self.mode == "malformed":
            return b"not-json"
        if self.mode == "oversized":
            return b"x" * (maximum + 1)
        if self.mode == "read-error":
            raise OSError("injected pipe read failure")
        return payload


class GatedResponseReader:
    def __init__(self, response_seen, release):
        self.calls = 0
        self.response_seen = response_seen
        self.release = release

    def __call__(self, pipe, maximum):
        self.calls += 1
        payload = pipe.recv_bytes(maximum)
        if self.calls == 2:
            self.response_seen.set()
            if not self.release.wait(2):
                raise OSError("test response gate timed out")
        return payload


class InjectedResponsePoller:
    def __init__(self):
        self.calls = 0

    def __call__(self, pipe, timeout):
        self.calls += 1
        if self.calls == 2:
            raise OSError("injected pipe poll failure")
        return pipe.poll(timeout)


def load_app_config(
    directory,
    *,
    backend="fake",
    max_queued=2,
    queue_wait=1,
    load_timeout=2,
    cancel_grace=0.1,
    exit_timeout=0.5,
):
    data = application_data()
    data["backend"]["id"] = backend
    data["admission"]["max_queued"] = max_queued
    data["admission"]["queue_wait_timeout_seconds"] = queue_wait
    data["lifecycle"]["model_load_timeout_seconds"] = load_timeout
    data["lifecycle"]["cooperative_cancel_grace_seconds"] = cancel_grace
    data["lifecycle"]["process_exit_timeout_seconds"] = exit_timeout
    path = Path(directory) / "app.yaml"
    import yaml

    path.write_text(yaml.safe_dump(data))
    return load_application_config(path)


def make_application(
    directory,
    behavior="success",
    duration=0,
    max_queued=2,
    queue_wait=1,
    load_timeout=2,
    auto=True,
    timestamps=True,
    cancel_grace=0.1,
    exit_timeout=0.5,
    process_control=None,
):
    config = load_app_config(
        directory,
        max_queued=max_queued,
        queue_wait=queue_wait,
        load_timeout=load_timeout,
        cancel_grace=cancel_grace,
        exit_timeout=exit_timeout,
    )
    factory = FakeBackendFactory(behavior, duration, auto, timestamps)
    deployment = DeploymentConfig(
        {
            "primary": ArtifactRoot(
                Path(directory) / "unused", Path(directory) / "manifest"
            )
        }
    )
    if process_control is None:
        app = create_application(
            config,
            deployment,
            {"fake": factory},
            FakeDeviceProbe(),
            FakeArtifactStore(),
        )
    else:

        def create_test_runner(*args, **kwargs):
            return InferenceSupervisor(*args, **kwargs, process_control=process_control)

        with patch(
            "services.stt.application.InferenceSupervisor",
            side_effect=create_test_runner,
        ):
            app = create_application(
                config,
                deployment,
                {"fake": factory},
                FakeDeviceProbe(),
                FakeArtifactStore(),
            )
    self_backend = factory()
    app.start(self_backend.capabilities())
    return app


class LifecycleTests(unittest.TestCase):
    def test_worker_and_model_states_are_independent(self):
        lifecycle = Lifecycle()
        lifecycle.set_worker(WorkerState.SERVING)
        lifecycle.set_model(ModelState.FAULTED)
        self.assertTrue(lifecycle.live())
        self.assertFalse(lifecycle.ready())
        lifecycle.set_model(ModelState.READY)
        self.assertTrue(lifecycle.ready())
        lifecycle.set_model(ModelState.CLEANUP_UNCONFIRMED)
        self.assertFalse(lifecycle.ready())
        self.assertTrue(lifecycle.cleanup_unconfirmed())
        lifecycle.set_worker(WorkerState.DRAINING)
        self.assertTrue(lifecycle.live())
        self.assertFalse(lifecycle.ready())

    def test_http_health_readiness_and_metrics_follow_lifecycle(self):
        lifecycle = Lifecycle()
        lifecycle.set_worker(WorkerState.SERVING)
        lifecycle.set_model(ModelState.LOADING)
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler(load_config("configs/stt.yaml", "stt"), lifecycle)
        )
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            self.assertEqual(self._get(server, "/healthz")[0], 200)
            self.assertEqual(self._get(server, "/readyz")[0], 503)
            self.assertIn(b"speech_ready 0", self._get(server, "/metrics")[1])
            lifecycle.set_model(ModelState.READY)
            self.assertEqual(self._get(server, "/readyz")[0], 200)
            self.assertIn(b"speech_ready 1", self._get(server, "/metrics")[1])
            lifecycle.set_model(ModelState.FAULTED)
            self.assertEqual(self._get(server, "/healthz")[0], 200)
            self.assertEqual(self._get(server, "/readyz")[0], 503)
            lifecycle.set_model(ModelState.CLEANUP_UNCONFIRMED)
            status, body = self._get(server, "/readyz")
            self.assertEqual(status, 503)
            self.assertIn(b"cleanup_unconfirmed", body)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    @staticmethod
    def _get(server, path):
        connection = http.client.HTTPConnection(*server.server_address, timeout=2)
        connection.request("GET", path)
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result


class SupervisorTests(unittest.TestCase):
    def test_persistent_child_success_and_graceful_shutdown(self):
        runner = supervisor()
        metadata = runner.start()
        self.assertTrue(metadata.automatic_language_detection)
        self.assertTrue(runner.child_alive)
        result = runner.transcribe(
            TranscriptionRequest(b"audio", "audio/wav", "general", timestamps=True),
            OperationContext(time.monotonic() + 2),
        )
        self.assertEqual(result.text, "fake transcription (5 bytes)")
        self.assertEqual(len(result.segments), 1)
        runner.shutdown(1)
        self.assertFalse(runner.child_alive)

    def test_request_failure_does_not_restart_persistent_child(self):
        runner = supervisor("failure")
        runner.start()
        pid = runner._process.pid
        for _ in range(2):
            with self.assertRaises(SpeechFailure) as caught:
                runner.transcribe(
                    TranscriptionRequest(b"x", "audio/wav"),
                    OperationContext(time.monotonic() + 1),
                )
            self.assertEqual(caught.exception.code, FailureCode.BACKEND_FAILED)
            self.assertEqual(runner._process.pid, pid)
            self.assertTrue(runner.child_alive)
        runner.shutdown(1)

    def test_cooperative_cancellation_keeps_child_healthy(self):
        runner = supervisor("success", duration=1, grace=0.2)
        runner.start()
        with self.assertRaises(SpeechFailure) as caught:
            runner.transcribe(
                TranscriptionRequest(b"x", "audio/wav"),
                OperationContext(time.monotonic() + 0.06),
            )
        self.assertEqual(caught.exception.code, FailureCode.DEADLINE_EXCEEDED)
        self.assertFalse(runner.faulted)
        self.assertTrue(runner.child_alive)
        runner.shutdown(1)

    def test_explicit_client_cancellation_is_cooperative(self):
        runner = supervisor("success", duration=1, grace=0.2)
        runner.start()
        context = OperationContext(time.monotonic() + 2)
        result = []

        def transcribe():
            try:
                runner.transcribe(TranscriptionRequest(b"x", "audio/wav"), context)
            except SpeechFailure as exc:
                result.append(exc.code)

        thread = threading.Thread(target=transcribe)
        thread.start()
        time.sleep(0.06)
        context.cancel()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [FailureCode.CANCELLED])
        self.assertTrue(runner.child_alive)
        self.assertFalse(runner.faulted)
        runner.shutdown(1)

    def test_ipc_message_size_is_enforced_before_send(self):
        runner = supervisor()
        runner.start()
        with self.assertRaises(SpeechFailure) as caught:
            runner.transcribe(
                TranscriptionRequest(b"x" * 50_000, "audio/wav"),
                OperationContext(time.monotonic() + 1),
            )
        self.assertEqual(caught.exception.code, FailureCode.INPUT_LIMIT)
        self.assertTrue(runner.child_alive)
        runner.shutdown(1)

    def test_malformed_oversized_and_read_failure_reap_live_child(self):
        for mode in ("malformed", "oversized", "read-error"):
            with self.subTest(mode=mode):
                runner = supervisor(response_reader=InjectedResponseReader(mode))
                runner.start()
                with self.assertRaises(SpeechFailure) as caught:
                    runner.transcribe(
                        TranscriptionRequest(b"x", "audio/wav"), OperationContext()
                    )
                self.assertEqual(caught.exception.code, FailureCode.NOT_READY)
                self.assertTrue(runner.faulted)
                self.assertFalse(runner.cleanup_unconfirmed)
                self.assertFalse(runner.child_alive)
                with self.assertRaises(RuntimeError):
                    runner.start()
                runner.shutdown(0.1)

    def test_response_poll_failure_reaps_live_child(self):
        runner = supervisor(response_poller=InjectedResponsePoller())
        runner.start()
        with self.assertRaises(SpeechFailure) as caught:
            runner.transcribe(
                TranscriptionRequest(b"x", "audio/wav"), OperationContext()
            )
        self.assertEqual(caught.exception.code, FailureCode.NOT_READY)
        self.assertTrue(runner.faulted)
        self.assertFalse(runner.child_alive)
        runner.shutdown(0.1)

    def test_cleanup_unconfirmed_is_bounded_and_blocks_replacement(self):
        process_control = ControlledProcess()
        process_control.hold_exit_confirmation = True
        runner = supervisor(
            "unresponsive",
            duration=10,
            grace=0.02,
            process_control=process_control,
            exit_timeout=0.03,
        )
        runner.start()
        context = OperationContext(time.monotonic() + 0.06)
        started = time.monotonic()
        with self.assertRaises(SpeechFailure) as caught:
            runner.transcribe(TranscriptionRequest(b"x", "audio/wav"), context)
        self.assertEqual(caught.exception.code, FailureCode.DEADLINE_EXCEEDED)
        self.assertTrue(caught.exception.retain_resources)
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(runner.cleanup_unconfirmed)
        self.assertFalse(runner.cleanup_event.is_set())
        with self.assertRaises(RuntimeError):
            runner.start()
        process_control.hold_exit_confirmation = False
        self.assertTrue(runner.cleanup_event.wait(2))
        self.assertFalse(runner.cleanup_unconfirmed)
        runner.shutdown(0.1)
        runner.shutdown(0.1)
        self.assertFalse(runner.child_alive)

    def test_unconfirmed_cleanup_keeps_admission_bytes_and_readiness_latched(self):
        process_control = ControlledProcess()
        process_control.hold_exit_confirmation = True
        original = InferenceSupervisor

        def controlled_supervisor(*args, **kwargs):
            return original(*args, process_control=process_control, **kwargs)

        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "services.stt.application.InferenceSupervisor", controlled_supervisor
            ),
        ):
            app = make_application(
                directory,
                behavior="unresponsive",
                duration=10,
                cancel_grace=0.02,
                exit_timeout=0.03,
            )
            with self.assertRaises(SpeechFailure) as caught:
                app.transcribe(
                    TranscriptionRequest(b"retained", "audio/wav"),
                    OperationContext(time.monotonic() + 0.06),
                )
            self.assertEqual(caught.exception.code, FailureCode.DEADLINE_EXCEEDED)
            self.assertTrue(app.runner.cleanup_unconfirmed)
            self.assertEqual(
                app.lifecycle.snapshot()[1], ModelState.CLEANUP_UNCONFIRMED
            )
            self.assertFalse(app.lifecycle.ready())
            snapshot = app._admission.snapshot()
            self.assertTrue(snapshot["active"])
            self.assertEqual(snapshot["retained_bytes"], len(b"retained"))
            self.assertGreaterEqual(snapshot["retained_bytes"], 0)
            process_control.hold_exit_confirmation = False
            self.assertTrue(app.runner.cleanup_event.wait(2))
            deadline = time.monotonic() + 1
            while (
                app._admission.snapshot()["retained_bytes"] != 0
                and time.monotonic() < deadline
            ):
                time.sleep(0.005)
            self.assertEqual(app._admission.snapshot()["retained_bytes"], 0)
            self.assertFalse(app._admission.snapshot()["active"])
            app.close()

    def test_child_crash_during_cancellation_faults_and_reaps(self):
        runner = supervisor("crash", exit_timeout=0.2)
        runner.start()
        context = OperationContext(time.monotonic() + 1)
        context.cancel()
        with self.assertRaises(SpeechFailure):
            runner.transcribe(TranscriptionRequest(b"x", "audio/wav"), context)
        self.assertTrue(runner.faulted)
        self.assertFalse(runner.child_alive)
        runner.shutdown(0.1)

    def test_simultaneous_completed_response_and_cancellation_returns_cancelled(self):
        response_seen = threading.Event()
        release = threading.Event()
        reader = GatedResponseReader(response_seen, release)
        runner = supervisor(response_reader=reader)
        runner.start()
        context = OperationContext(time.monotonic() + 2)
        failures = []

        def invoke():
            try:
                runner.transcribe(TranscriptionRequest(b"audio", "audio/wav"), context)
            except SpeechFailure as exc:
                failures.append(exc.code)

        caller = threading.Thread(target=invoke)
        caller.start()
        self.assertTrue(response_seen.wait(2))
        context.cancel()
        release.set()
        caller.join(1)
        self.assertFalse(caller.is_alive())
        self.assertEqual(failures, [FailureCode.CANCELLED])
        self.assertTrue(runner.child_alive)
        runner.shutdown(0.5)

    def test_unresponsive_child_is_terminated_reaped_and_fault_latched(self):
        runner = supervisor("unresponsive", duration=10, grace=0.03)
        runner.start()
        with self.assertRaises(SpeechFailure):
            runner.transcribe(
                TranscriptionRequest(b"x", "audio/wav"),
                OperationContext(time.monotonic() + 0.08),
            )
        self.assertTrue(runner.faulted)
        self.assertFalse(runner.child_alive)
        with self.assertRaises(SpeechFailure) as caught:
            runner.transcribe(
                TranscriptionRequest(b"x", "audio/wav"), OperationContext()
            )
        self.assertEqual(caught.exception.code, FailureCode.NOT_READY)
        runner.shutdown(0.1)

    def test_child_crash_and_load_failure_are_latched(self):
        crashed = supervisor("crash")
        crashed.start()
        with self.assertRaises(SpeechFailure):
            crashed.transcribe(
                TranscriptionRequest(b"x", "audio/wav"), OperationContext()
            )
        self.assertTrue(crashed.faulted)
        self.assertFalse(crashed.child_alive)
        crashed.shutdown(0.1)

        failed = supervisor("load_failure")
        with self.assertRaises(SpeechFailure):
            failed.start()
        self.assertTrue(failed.faulted)
        self.assertFalse(failed.child_alive)
        failed.shutdown(0.1)

        timed_out = supervisor("load_unresponsive", load_timeout=0.1)
        with self.assertRaises(SpeechFailure) as caught:
            timed_out.start()
        self.assertEqual(caught.exception.code, FailureCode.MODEL_LOAD_FAILED)
        self.assertTrue(timed_out.faulted)
        self.assertFalse(timed_out.child_alive)
        timed_out.shutdown(0.1)


class ApplicationTests(unittest.TestCase):
    def test_success_alias_capabilities_and_release(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory)
            result = app.transcribe(
                TranscriptionRequest(b"audio", "audio/wav", timestamps=True)
            )
            self.assertEqual(result.language, "en")
            self.assertEqual(app._admission.snapshot()["retained_bytes"], 0)
            with self.assertRaises(SpeechFailure) as unknown:
                app.transcribe(
                    TranscriptionRequest(b"x", "audio/wav", model_alias="missing")
                )
            self.assertEqual(unknown.exception.code, FailureCode.UNKNOWN_MODEL)
            app.close()

        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, auto=False, timestamps=False)
            for request in (
                TranscriptionRequest(b"x", "audio/wav"),
                TranscriptionRequest(b"x", "audio/wav", language="fr"),
                TranscriptionRequest(b"x", "audio/wav", timestamps=True),
            ):
                with self.assertRaises(SpeechFailure) as caught:
                    app.transcribe(request)
                self.assertEqual(caught.exception.code, FailureCode.UNSUPPORTED_OPTION)
            app.close()

    def test_recoverable_resource_failure_releases_admission_for_next_request(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, behavior="resource_failure_once")
            with self.assertRaises(SpeechFailure) as caught:
                app.transcribe(TranscriptionRequest(b"audio", "audio/wav"))
            self.assertEqual(caught.exception.code, FailureCode.RESOURCE_EXHAUSTED)
            snapshot = app._admission.snapshot()
            self.assertFalse(snapshot["active"])
            self.assertEqual(snapshot["queued"], 0)
            self.assertEqual(snapshot["retained_bytes"], 0)
            self.assertTrue(app.lifecycle.ready())

            result = app.transcribe(TranscriptionRequest(b"audio", "audio/wav"))
            self.assertIn("fake transcription", result.text)
            self.assertEqual(app._admission.snapshot()["retained_bytes"], 0)
            app.close()

    def test_media_size_deadline_and_upload_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory)
            with self.assertRaises(SpeechFailure):
                app.transcribe(TranscriptionRequest(b"x", "audio/x-private"))
            with self.assertRaises(SpeechFailure) as limited:
                app.transcribe(TranscriptionRequest(b"x" * 17, "audio/wav"))
            self.assertEqual(limited.exception.code, FailureCode.INPUT_LIMIT)
            with self.assertRaises(SpeechFailure) as expired:
                app.transcribe(
                    TranscriptionRequest(b"x", "audio/wav"),
                    OperationContext(time.monotonic() - 1),
                )
            self.assertEqual(expired.exception.code, FailureCode.DEADLINE_EXCEEDED)
            with app.acquire_upload():
                with app.acquire_upload():
                    with self.assertRaises(SpeechFailure):
                        with app.acquire_upload():
                            pass
            app.close()

    def test_streamed_upload_budget_transfers_to_retained_job(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory)
            with app.acquire_upload() as upload:
                upload.write(b"aud")
                upload.write(b"io")
                self.assertEqual(app._admission.uploads.snapshot()["upload_bytes"], 5)
                result = app.transcribe_uploaded(upload, "audio/wav")
                self.assertIn("5 bytes", result.text)
                snapshot = app._admission.uploads.snapshot()
                self.assertEqual(snapshot["upload_bytes"], 0)
                self.assertEqual(snapshot["retained_bytes"], 0)
                self.assertEqual(snapshot["active_uploads"], 0)
            app.close()

    def test_queue_saturation_does_not_flap_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, duration=0.35, max_queued=1)
            failures = []
            first = threading.Thread(
                target=lambda: app.transcribe(TranscriptionRequest(b"1", "audio/wav"))
            )
            first.start()
            self._wait_for(lambda: app._admission.snapshot()["active"])
            second = threading.Thread(
                target=lambda: app.transcribe(TranscriptionRequest(b"2", "audio/wav"))
            )
            second.start()
            self._wait_for(lambda: app._admission.snapshot()["queued"] == 1)
            with self.assertRaises(SpeechFailure) as caught:
                app.transcribe(TranscriptionRequest(b"3", "audio/wav"))
            failures.append(caught.exception.code)
            self.assertEqual(failures, [FailureCode.OVERLOADED])
            self.assertTrue(app.lifecycle.ready())
            first.join(3)
            second.join(3)
            self.assertFalse(first.is_alive() or second.is_alive())
            self.assertEqual(app._admission.snapshot()["retained_bytes"], 0)
            app.close()

    def test_startup_load_failure_keeps_worker_live_but_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, behavior="load_failure")
            self.assertFalse(app.lifecycle.ready())
            self.assertTrue(app.lifecycle.live())
            with self.assertRaises(SpeechFailure) as caught:
                app.transcribe(TranscriptionRequest(b"x", "audio/wav"))
            self.assertEqual(caught.exception.code, FailureCode.NOT_READY)
            app.close()

        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, behavior="wrong_identity")
            self.assertFalse(app.lifecycle.ready())
            self.assertEqual(app.startup_failure.code, FailureCode.MODEL_LOAD_FAILED)
            self.assertFalse(app.runner.child_alive)
            app.close()

    def test_model_load_timeout_with_unconfirmed_exit_reports_cleanup_unconfirmed(self):
        process_control = ControlledProcess()
        process_control.hold_exit_confirmation = True
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(
                directory,
                behavior="load_unresponsive",
                load_timeout=0.05,
                exit_timeout=0.03,
                process_control=process_control,
            )
            self.assertEqual(app.startup_failure.code, FailureCode.MODEL_LOAD_FAILED)
            self.assertTrue(app.lifecycle.live())
            self.assertFalse(app.lifecycle.ready())
            self.assertTrue(app.lifecycle.cleanup_unconfirmed())
            self.assertTrue(app.runner.cleanup_unconfirmed)
            with self.assertRaises(SpeechFailure) as caught:
                app.transcribe(TranscriptionRequest(b"audio", "audio/wav"))
            self.assertEqual(caught.exception.code, FailureCode.NOT_READY)

            process_control.hold_exit_confirmation = False
            self.assertTrue(app.runner.cleanup_event.wait(1))
            self.assertFalse(app.runner.cleanup_unconfirmed)
            self.assertFalse(app.lifecycle.ready())
            app.close()

    def test_fatal_child_fault_latches_model_without_killing_worker_liveness(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, behavior="crash")
            with self.assertRaises(SpeechFailure):
                app.transcribe(TranscriptionRequest(b"x", "audio/wav"))
            self.assertTrue(app.lifecycle.live())
            self.assertFalse(app.lifecycle.ready())
            self.assertTrue(app.runner.faulted)
            with self.assertRaises(SpeechFailure) as caught:
                app.transcribe(TranscriptionRequest(b"x", "audio/wav"))
            self.assertEqual(caught.exception.code, FailureCode.NOT_READY)
            app.close()

    def test_shutdown_during_fault_is_repeatable_and_keeps_accounting_nonnegative(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, behavior="crash")
            with self.assertRaises(SpeechFailure):
                app.transcribe(TranscriptionRequest(b"audio", "audio/wav"))
            self.assertFalse(app.lifecycle.ready())
            app.close()
            app.close()
            snapshot = app._admission.snapshot()
            self.assertEqual(snapshot["retained_bytes"], 0)
            self.assertEqual(snapshot["queued_bytes"], 0)
            self.assertGreaterEqual(snapshot["retained_bytes"], 0)
            self.assertFalse(app.runner.child_alive)

    def test_shutdown_drains_then_cancels_active_child_and_drops_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, duration=3, max_queued=1)
            captured = []

            def invoke(audio):
                try:
                    app.transcribe(TranscriptionRequest(audio, "audio/wav"))
                except SpeechFailure as exc:
                    captured.append(exc.code)

            active = threading.Thread(target=invoke, args=(b"a",))
            active.start()
            self._wait_for(lambda: app._admission.snapshot()["active"])
            queued = threading.Thread(target=invoke, args=(b"q",))
            queued.start()
            self._wait_for(lambda: app._admission.snapshot()["queued"] == 1)
            app.close()
            active.join(1)
            queued.join(1)
            self.assertFalse(active.is_alive() or queued.is_alive())
            self.assertEqual(captured.count(FailureCode.NOT_READY), 1)
            self.assertFalse(app.runner.child_alive)
            self.assertEqual(app._admission.snapshot()["retained_bytes"], 0)
            self.assertFalse(app.lifecycle.live())

    @staticmethod
    def _wait_for(predicate):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        raise AssertionError("condition did not become true")


if __name__ == "__main__":
    unittest.main()
