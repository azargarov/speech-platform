import threading
import tempfile
import time
import unittest
import http.client
import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path

from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from services.stt.application import _RunnerFactoryHandoff, create_application
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
    TranscriptionResult,
    VerifiedArtifact,
)
from services.stt.lifecycle import Lifecycle, ModelState, WorkerState
from services.stt.supervisor import InferenceSupervisor
from services.stt.testing import FakeBackendFactory
from services.stt.http_server import STARTUP_TASK_KEY, create_app
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
    translation_supported=True,
    idle_timeout=60,
    shutdown_drain_timeout=1,
    max_request_bytes=None,
    max_upload_bytes=None,
    max_retained_audio_bytes=None,
):
    data = application_data()
    data["backend"]["id"] = backend
    data["admission"]["max_queued"] = max_queued
    if max_request_bytes is not None:
        data["admission"]["max_request_bytes"] = max_request_bytes
    if max_upload_bytes is not None:
        data["admission"]["max_upload_bytes"] = max_upload_bytes
    if max_retained_audio_bytes is not None:
        data["admission"]["max_retained_audio_bytes"] = max_retained_audio_bytes
    data["admission"]["queue_wait_timeout_seconds"] = queue_wait
    data["lifecycle"]["model_load_timeout_seconds"] = load_timeout
    data["lifecycle"]["model_idle_unload_seconds"] = idle_timeout
    data["lifecycle"]["cooperative_cancel_grace_seconds"] = cancel_grace
    data["lifecycle"]["process_exit_timeout_seconds"] = exit_timeout
    data["lifecycle"]["shutdown_drain_timeout_seconds"] = shutdown_drain_timeout
    data["models"][0]["translation_supported"] = translation_supported
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
    translation_supported=True,
    idle_timeout=60,
    shutdown_drain_timeout=1,
):
    config = load_app_config(
        directory,
        max_queued=max_queued,
        queue_wait=queue_wait,
        load_timeout=load_timeout,
        cancel_grace=cancel_grace,
        exit_timeout=exit_timeout,
        translation_supported=translation_supported,
        idle_timeout=idle_timeout,
        shutdown_drain_timeout=shutdown_drain_timeout,
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
        lifecycle.set_model(ModelState.UNLOADED)
        self.assertTrue(lifecycle.ready())
        lifecycle.set_model(ModelState.LOADING)
        self.assertTrue(lifecycle.ready())
        lifecycle.set_model(ModelState.UNLOADING)
        self.assertTrue(lifecycle.ready())
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
            self.assertEqual(self._get(server, "/readyz")[0], 200)
            self.assertIn(b"speech_ready 1", self._get(server, "/metrics")[1])
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
        runner = supervisor("unresponsive", duration=0.25, grace=0.01)
        runner.start()
        started = time.monotonic()
        with self.assertRaises(SpeechFailure) as caught:
            runner.transcribe(
                TranscriptionRequest(b"cancelled", "audio/wav"),
                OperationContext(time.monotonic() + 0.04),
            )
        self.assertEqual(caught.exception.code, FailureCode.DEADLINE_EXCEEDED)
        self.assertGreaterEqual(time.monotonic() - started, 0.2)
        self.assertFalse(runner.faulted)
        self.assertTrue(runner.child_alive)
        result = runner.transcribe(
            TranscriptionRequest(b"next", "audio/wav"), OperationContext()
        )
        self.assertEqual(result.text, "fake transcription (4 bytes)")
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

    def test_explicit_shutdown_cleanup_is_bounded_when_exit_is_unconfirmed(self):
        process_control = ControlledProcess()
        runner = supervisor(process_control=process_control, exit_timeout=0.03)
        runner.start()
        process_control.hold_exit_confirmation = True
        started = time.monotonic()
        runner.shutdown(0.03)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(runner.cleanup_unconfirmed)
        self.assertFalse(runner.cleanup_event.is_set())
        process_control.hold_exit_confirmation = False
        self.assertTrue(runner.cleanup_event.wait(2))
        runner.shutdown(0.1)

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

    def test_fatal_response_is_latched_when_request_is_cancelled(self):
        class FatalResponseReader:
            def __init__(self):
                self.calls = 0

            def __call__(self, pipe, maximum):
                self.calls += 1
                payload = pipe.recv_bytes(maximum)
                if self.calls == 2:
                    return b'{"type":"failure","code":"backend_failed","fatal":true}'
                return payload

        runner = supervisor(response_reader=FatalResponseReader())
        runner.start()
        context = OperationContext()
        context.cancel()
        with self.assertRaises(SpeechFailure) as caught:
            runner.transcribe(
                TranscriptionRequest(b"x", "audio/wav"),
                context,
            )
        self.assertEqual(caught.exception.code, FailureCode.CANCELLED)
        self.assertTrue(runner.faulted)
        self.assertFalse(runner.child_alive)
        runner.shutdown(0.1)

    def test_child_crash_and_load_failure_are_latched(self):
        crashed = supervisor("crash")
        crashed.start()
        events = io.StringIO()
        with redirect_stdout(events), self.assertRaises(SpeechFailure):
            crashed.transcribe(
                TranscriptionRequest(b"x", "audio/wav"), OperationContext()
            )
        parsed = [json.loads(line) for line in events.getvalue().splitlines()]
        self.assertTrue(
            any(
                event.get("event") == "inference_worker_exited"
                and event.get("exitcode") not in (None, 0)
                for event in parsed
            )
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
    def test_start_is_lazy_warmup_loads_once_and_inference_reuses_model(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory)
            self.assertTrue(app.lifecycle.ready())
            self.assertEqual(app.lifecycle.snapshot()[1], ModelState.UNLOADED)
            self.assertIsNone(app.runner)
            self.assertEqual(app.warmup(), {"model_state": "ready"})
            runner = app.runner
            self.assertTrue(runner.child_alive)
            app.transcribe(TranscriptionRequest(b"audio", "audio/wav"))
            self.assertIs(app.runner, runner)
            app.close()

    def test_first_inference_loads_without_prior_warmup(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory)
            self.assertEqual(app.lifecycle.snapshot()[1], ModelState.UNLOADED)
            result = app.transcribe(TranscriptionRequest(b"cold audio", "audio/wav"))
            self.assertIn("fake transcription", result.text)
            runner = app.runner
            self.assertIsNotNone(runner)
            self.assertTrue(runner.child_alive)
            app.transcribe(TranscriptionRequest(b"second audio", "audio/wav"))
            self.assertIs(app.runner, runner)
            app.close()

    def test_idle_unload_and_subsequent_inference_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, idle_timeout=0.05)
            previous = None
            for _ in range(3):
                app.warmup()
                current = app.runner
                self._wait_for(
                    lambda: app.lifecycle.snapshot()[1] == ModelState.UNLOADED
                )
                self.assertFalse(current.child_alive)
                if previous is not None:
                    self.assertIsNot(current, previous)
                previous = current
            app.transcribe(TranscriptionRequest(b"again", "audio/wav"))
            self.assertIsNot(app.runner, previous)
            app.close()

    def test_zero_timeout_waits_for_active_and_admitted_queued_work(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, duration=0.15, idle_timeout=0)
            failures = []

            def invoke(audio):
                _capture(
                    failures,
                    lambda: app.transcribe(TranscriptionRequest(audio, "audio/wav")),
                )

            first = threading.Thread(target=invoke, args=(b"active",))
            first.start()
            self._wait_for(lambda: app._admission.snapshot()["active"])
            self._wait_for(lambda: app.lifecycle.snapshot()[1] == ModelState.READY)
            second = threading.Thread(target=invoke, args=(b"queued",))
            second.start()
            self._wait_for(lambda: app._admission.snapshot()["queued"] == 1)
            self.assertEqual(app.lifecycle.snapshot()[1], ModelState.READY)
            self.assertTrue(app.runner.child_alive)
            first.join(2)
            second.join(2)
            self.assertFalse(first.is_alive() or second.is_alive())
            self.assertEqual(failures, [])
            self._wait_for(lambda: app.lifecycle.snapshot()[1] == ModelState.UNLOADED)
            app.close()

    def test_zero_timeout_unload_after_completion_does_not_dereference_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, idle_timeout=0)
            validation_entered = threading.Event()
            release_validation = threading.Event()
            original_validate = app._validate_result

            def gated_validate(result):
                validation_entered.set()
                self.assertTrue(release_validation.wait(2))
                return original_validate(result)

            app._validate_result = gated_validate
            outcome = []
            request = threading.Thread(
                target=lambda: _capture(
                    outcome,
                    lambda: app.transcribe(TranscriptionRequest(b"audio", "audio/wav")),
                )
            )
            request.start()
            self.assertTrue(validation_entered.wait(2))
            self._wait_for(lambda: app.lifecycle.snapshot()[1] == ModelState.UNLOADED)
            release_validation.set()
            request.join(2)
            self.assertFalse(request.is_alive())
            self.assertEqual(outcome, [])
            app.close()

    def test_shared_load_failure_fails_all_admitted_jobs_once(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, behavior="load_failure", max_queued=2)
            factory_calls = []
            original_factory = app._runner_factory

            def counted_factory():
                factory_calls.append(True)
                return original_factory()

            app._runner_factory = counted_factory
            failure_entered = threading.Event()
            release_failure = threading.Event()
            original_fail_admitted = app._admission.fail_admitted

            def gated_fail_admitted(failure, finish_generation):
                failure_entered.set()
                self.assertTrue(release_failure.wait(2))
                return original_fail_admitted(failure, finish_generation)

            app._admission.fail_admitted = gated_fail_admitted
            outcomes = []
            first = threading.Thread(
                target=lambda: _capture(
                    outcomes,
                    lambda: app.transcribe(TranscriptionRequest(b"first", "audio/wav")),
                )
            )
            first.start()
            self.assertTrue(failure_entered.wait(2))
            second = threading.Thread(
                target=lambda: _capture(
                    outcomes,
                    lambda: app.transcribe(
                        TranscriptionRequest(b"second", "audio/wav")
                    ),
                )
            )
            second.start()
            self._wait_for(lambda: app._admission.snapshot()["queued"] == 1)
            release_failure.set()
            first.join(3)
            second.join(3)
            self.assertFalse(first.is_alive() or second.is_alive())
            self.assertEqual(len(outcomes), 2)
            self.assertTrue(all(isinstance(item, SpeechFailure) for item in outcomes))
            self.assertEqual(len(factory_calls), 1)
            snapshot = app._admission.snapshot()
            self.assertFalse(snapshot["active"])
            self.assertEqual(snapshot["queued"], 0)
            self.assertEqual(snapshot["retained_bytes"], 0)
            app.close()

    def test_blocked_device_preflight_times_out_and_late_factory_cannot_start_child(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, load_timeout=0.05, exit_timeout=0.05)
            original_factory = app._runner_factory
            entered = threading.Event()
            release = threading.Event()
            created = []

            def blocked_factory():
                entered.set()
                release.wait(2)
                runner = original_factory()
                created.append(runner)
                return runner

            app._runner_factory = blocked_factory
            with self.assertRaises(SpeechFailure) as caught:
                app.warmup(OperationContext(time.monotonic() + 1))
            self.assertEqual(caught.exception.code, FailureCode.MODEL_LOAD_FAILED)
            self.assertTrue(entered.is_set())
            self.assertTrue(app.lifecycle.cleanup_unconfirmed())
            closer = threading.Thread(target=app.close)
            closer.start()
            release.set()
            closer.join(2)
            self.assertFalse(closer.is_alive())
            self.assertTrue(created)
            self.assertFalse(created[0].child_alive)

    def test_preflight_handoff_timeout_and_completion_have_one_owner(self):
        late = _RunnerFactoryHandoff()
        self.assertEqual(late.claim(0), (None, None, True))
        late_runner = object()
        self.assertTrue(late.publish(late_runner, None))
        late.cleanup_finished()

        completed = _RunnerFactoryHandoff()
        completed_runner = object()
        self.assertFalse(completed.publish(completed_runner, None))
        self.assertEqual(completed.claim(0), (completed_runner, None, False))

        for _ in range(25):
            handoff = _RunnerFactoryHandoff()
            runner = object()
            start = threading.Barrier(3)
            publish_result = []
            claim_result = []

            publisher = threading.Thread(
                target=lambda: (
                    start.wait(),
                    publish_result.append(handoff.publish(runner, None)),
                )
            )
            claimant = threading.Thread(
                target=lambda: (start.wait(), claim_result.append(handoff.claim(0.002)))
            )
            publisher.start()
            claimant.start()
            start.wait()
            publisher.join(1)
            claimant.join(1)
            self.assertFalse(publisher.is_alive() or claimant.is_alive())
            claimed_runner, _error, abandoned = claim_result[0]
            if abandoned:
                self.assertIsNone(claimed_runner)
                self.assertEqual(publish_result, [True])
                handoff.cleanup_finished()
            else:
                self.assertIs(claimed_runner, runner)
                self.assertEqual(publish_result, [False])

    def test_shutdown_during_non_cooperative_inference_is_bounded_and_latched(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(
                directory,
                load_timeout=2,
                exit_timeout=0.05,
                shutdown_drain_timeout=0.12,
            )
            app.warmup()
            runner = app.runner
            inference_entered = threading.Event()
            release_inference = threading.Event()
            shutdown_calls = []

            def blocked_inference(_request, _context):
                inference_entered.set()
                release_inference.wait(3)
                return TranscriptionResult("test", "en")

            original_shutdown = runner.shutdown

            def tracked_shutdown(timeout):
                shutdown_calls.append(timeout)
                return original_shutdown(timeout)

            runner.transcribe = blocked_inference
            runner.shutdown = tracked_shutdown
            outcomes = []
            request = threading.Thread(
                target=lambda: _capture(
                    outcomes,
                    lambda: app.transcribe(
                        TranscriptionRequest(b"audio", "audio/wav"),
                        OperationContext(time.monotonic() + 5),
                    ),
                )
            )
            request.start()
            self.assertTrue(inference_entered.wait(2))

            started = time.monotonic()
            app.close()
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 0.35)
            self.assertTrue(app.lifecycle.cleanup_unconfirmed())
            self.assertFalse(app.lifecycle.ready())
            self.assertEqual(shutdown_calls, [])

            release_inference.set()
            request.join(2)
            self.assertFalse(request.is_alive())
            self.assertEqual(
                app.lifecycle.snapshot()[1], ModelState.CLEANUP_UNCONFIRMED
            )
            self.assertEqual(shutdown_calls, [])

            # Release the test child only after its fake active owner has exited.
            original_shutdown(0.5)

    def test_active_caller_cancellation_returns_without_releasing_admission_ownership(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory)
            app.warmup()
            entered, release = threading.Event(), threading.Event()

            def blocked(_request, _context):
                entered.set()
                release.wait(3)
                return TranscriptionResult("test", "en")

            app.runner.transcribe = blocked
            context = OperationContext(time.monotonic() + 5)
            outcomes = []
            caller = threading.Thread(
                target=lambda: _capture(
                    outcomes,
                    lambda: app.transcribe(
                        TranscriptionRequest(b"audio", "audio/wav"), context
                    ),
                )
            )
            try:
                caller.start()
                self.assertTrue(entered.wait(1))
                context.cancel()
                caller.join(1)
                self.assertFalse(caller.is_alive())
                self.assertEqual(outcomes[0].code, FailureCode.CANCELLED)
                snapshot = app._admission.snapshot()
                self.assertTrue(snapshot["active"])
                self.assertEqual(snapshot["retained_bytes"], len(b"audio"))
                self.assertFalse(
                    app._admission.run_if_idle(
                        lambda: True, lambda: self.fail("active inference unloaded")
                    )
                )
                release.set()
                self._wait_for(lambda: not app._admission.snapshot()["active"])
                self.assertEqual(app._admission.snapshot()["retained_bytes"], 0)
            finally:
                release.set()
                caller.join(2)
                app.close()

    def test_supervisor_shutdown_lock_wait_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory)
            app.warmup()
            runner = app.runner
            lock_held = threading.Event()
            release_lock = threading.Event()

            def hold_lock():
                with runner._lock:
                    lock_held.set()
                    release_lock.wait(2)

            holder = threading.Thread(target=hold_lock)
            holder.start()
            self.assertTrue(lock_held.wait(1))
            started = time.monotonic()
            self.assertFalse(runner.shutdown(0.05))
            self.assertLess(time.monotonic() - started, 0.15)
            self.assertTrue(runner.cleanup_unconfirmed)
            self.assertTrue(runner.child_alive)
            release_lock.set()
            holder.join(1)
            self.assertFalse(holder.is_alive())
            runner.shutdown(0.5)
            app.close()

    def test_shutdown_reports_blocked_preflight_as_cleanup_unconfirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, load_timeout=0.05, exit_timeout=0.05)
            entered = threading.Event()
            release = threading.Event()
            original_factory = app._runner_factory

            def blocked_factory():
                entered.set()
                release.wait(2)
                return original_factory()

            app._runner_factory = blocked_factory
            with self.assertRaises(SpeechFailure):
                app.warmup(OperationContext(time.monotonic() + 1))
            self.assertTrue(entered.is_set())
            app.close()
            self.assertTrue(app.lifecycle.cleanup_unconfirmed())
            self.assertFalse(app.lifecycle.ready())
            release.set()
            app._preflight_thread.join(2)
            self.assertFalse(app._preflight_thread.is_alive())

    def test_concurrent_warmups_share_recoverable_load_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, behavior="load_failure")
            original_factory = app._runner_factory
            calls = []
            entered = threading.Event()
            release = threading.Event()

            def gated_factory():
                calls.append(True)
                runner = original_factory()
                start = runner.start

                def blocked_start():
                    entered.set()
                    release.wait(2)
                    return start()

                runner.start = blocked_start
                return runner

            app._runner_factory = gated_factory
            outcomes = []
            first = threading.Thread(target=lambda: _capture(outcomes, app.warmup))
            second = threading.Thread(target=lambda: _capture(outcomes, app.warmup))
            first.start()
            self.assertTrue(entered.wait(2))
            second.start()
            release.set()
            first.join(3)
            second.join(3)
            self.assertFalse(first.is_alive() or second.is_alive())
            self.assertEqual(len(outcomes), 2)
            self.assertTrue(all(isinstance(item, SpeechFailure) for item in outcomes))
            self.assertEqual(len(calls), 1)
            self.assertFalse(app._load_thread.is_alive())
            app.close()

    def test_upload_acquired_before_unload_reservation_prevents_unload(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, idle_timeout=0)
            with app.acquire_upload():
                app.warmup()
                self.assertEqual(app.lifecycle.snapshot()[1], ModelState.READY)
                self.assertTrue(app.runner.child_alive)
            self._wait_for(lambda: app.lifecycle.snapshot()[1] == ModelState.UNLOADED)
            app.close()

    def test_new_request_waits_boundedly_while_child_shutdown_is_reserved(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, idle_timeout=10)
            app.warmup()
            runner = app.runner
            original_shutdown = runner.shutdown
            entered = threading.Event()
            release = threading.Event()

            def blocked_shutdown(timeout):
                entered.set()
                release.wait(2)
                return original_shutdown(timeout)

            runner.shutdown = blocked_shutdown
            with app._condition:
                app._last_use = 0
                app._condition.notify_all()
            self.assertTrue(entered.wait(2))
            result = []
            request = threading.Thread(
                target=lambda: _capture(
                    result,
                    lambda: app.transcribe(
                        TranscriptionRequest(b"audio", "audio/wav"),
                        OperationContext(time.monotonic() + 0.05),
                    ),
                )
            )
            request.start()
            request.join(1)
            self.assertFalse(request.is_alive())
            self.assertEqual(result[0].code, FailureCode.DEADLINE_EXCEEDED)
            release.set()
            self._wait_for(lambda: app.lifecycle.snapshot()[1] == ModelState.UNLOADED)
            app.close()

    def test_completed_inference_resets_idle_unload_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, duration=0.15, idle_timeout=1.0)
            app.warmup()
            threading.Event().wait(0.7)
            done = threading.Event()

            def invoke():
                app.transcribe(TranscriptionRequest(b"audio", "audio/wav"))
                done.set()

            worker = threading.Thread(target=invoke)
            worker.start()
            self.assertTrue(done.wait(2))
            worker.join(1)
            threading.Event().wait(0.4)
            self.assertEqual(app.lifecycle.snapshot()[1], ModelState.READY)
            self._wait_for(lambda: app.lifecycle.snapshot()[1] == ModelState.UNLOADED)
            app.close()

    def test_concurrent_warmup_and_inference_share_one_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory)
            original_factory = app._runner_factory
            factory_calls = []
            start_entered = threading.Event()
            release_start = threading.Event()

            def gated_factory():
                runner = original_factory()
                factory_calls.append(runner)
                original_start = runner.start

                def gated_start():
                    start_entered.set()
                    if not release_start.wait(2):
                        raise RuntimeError("test gate timed out")
                    return original_start()

                runner.start = gated_start
                return runner

            app._runner_factory = gated_factory
            failures = []
            warmup = threading.Thread(target=lambda: _capture(failures, app.warmup))
            inference = threading.Thread(
                target=lambda: _capture(
                    failures,
                    lambda: app.transcribe(TranscriptionRequest(b"audio", "audio/wav")),
                )
            )
            warmup.start()
            self.assertTrue(start_entered.wait(2))
            self.assertTrue(app.lifecycle.ready())
            inference.start()
            release_start.set()
            warmup.join(3)
            inference.join(3)
            self.assertFalse(warmup.is_alive() or inference.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(len(factory_calls), 1)
            app.close()

    def test_warmup_wait_timeout_does_not_cancel_shared_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory)
            original_factory = app._runner_factory
            start_entered = threading.Event()
            release_start = threading.Event()

            def gated_factory():
                runner = original_factory()
                original_start = runner.start

                def gated_start():
                    start_entered.set()
                    if not release_start.wait(2):
                        raise RuntimeError("test gate timed out")
                    return original_start()

                runner.start = gated_start
                return runner

            app._runner_factory = gated_factory
            failures = []
            waiter = threading.Thread(
                target=lambda: _capture(
                    failures,
                    lambda: app.warmup(OperationContext(time.monotonic() + 0.05)),
                )
            )
            waiter.start()
            self.assertTrue(start_entered.wait(2))
            waiter.join(1)
            self.assertFalse(waiter.is_alive())
            self.assertEqual(len(failures), 1)
            self.assertIsInstance(failures[0], SpeechFailure)
            self.assertEqual(failures[0].code, FailureCode.DEADLINE_EXCEEDED)
            self.assertEqual(app.lifecycle.snapshot()[1], ModelState.LOADING)
            release_start.set()
            self._wait_for(lambda: app.lifecycle.snapshot()[1] == ModelState.READY)
            self.assertTrue(app.runner.child_alive)
            app.close()

    def test_shutdown_during_loading_waits_for_supervised_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory)
            original_factory = app._runner_factory
            start_entered = threading.Event()
            release_start = threading.Event()
            runners = []

            def gated_factory():
                runner = original_factory()
                runners.append(runner)
                original_start = runner.start

                def gated_start():
                    start_entered.set()
                    if not release_start.wait(2):
                        raise RuntimeError("test gate timed out")
                    return original_start()

                runner.start = gated_start
                return runner

            app._runner_factory = gated_factory
            warmup_errors = []
            warmup = threading.Thread(
                target=lambda: _capture(warmup_errors, app.warmup)
            )
            warmup.start()
            self.assertTrue(start_entered.wait(2))
            closer = threading.Thread(target=app.close)
            closer.start()
            self.assertTrue(app._stopping.wait(1))
            release_start.set()
            warmup.join(3)
            closer.join(3)
            self.assertFalse(warmup.is_alive() or closer.is_alive())
            self.assertEqual(len(warmup_errors), 1)
            self.assertFalse(app._load_thread.is_alive())
            self.assertFalse(runners[0].child_alive)
            self.assertEqual(app.lifecycle.snapshot()[0], WorkerState.STOPPED)

    def test_translation_capability_is_model_configured(self):
        for detected_language in ("ru", "sv"):
            with (
                self.subTest(language=detected_language),
                tempfile.TemporaryDirectory() as directory,
            ):
                app = make_application(directory, translation_supported=False)
                app.warmup()
                requests = []

                def transcribe(request, _context):
                    requests.append(request)
                    return TranscriptionResult("raw transcript", detected_language)

                app.runner.transcribe = transcribe
                with self.assertRaises(SpeechFailure) as caught:
                    app.transcribe(
                        TranscriptionRequest(
                            b"audio", "audio/wav", output_language="en"
                        )
                    )
                self.assertEqual(
                    caught.exception.code, FailureCode.UNSUPPORTED_TRANSLATION
                )
                self.assertEqual(requests[0].output_language, "auto")
                app.close()

        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, translation_supported=False)
            app.warmup()
            app.runner.transcribe = lambda _request, _context: TranscriptionResult(
                "raw transcript", "ru"
            )
            same_language = app.transcribe(
                TranscriptionRequest(b"audio", "audio/wav", output_language="ru")
            )
            automatic = app.transcribe(TranscriptionRequest(b"audio", "audio/wav"))
            self.assertEqual(same_language.text, "raw transcript")
            self.assertFalse(same_language.translated)
            self.assertEqual(automatic.text, "raw transcript")
            self.assertFalse(automatic.translated)
            app.close()

        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, translation_supported=False)
            app.warmup()
            app.runner.transcribe = lambda _request, _context: TranscriptionResult(
                "unexpected translated text", "ru", translated=True
            )
            with self.assertRaises(SpeechFailure) as caught:
                app.transcribe(TranscriptionRequest(b"audio", "audio/wav"))
            self.assertEqual(caught.exception.code, FailureCode.BACKEND_FAILED)
            app.close()

    def test_v1_language_validation_and_unsupported_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory)
            app.warmup()
            with self.assertRaises(SpeechFailure) as invalid:
                app.transcribe(
                    TranscriptionRequest(b"x", "audio/wav", output_language="de")
                )
            self.assertEqual(invalid.exception.code, FailureCode.INVALID_INPUT)
            app.runner.transcribe = lambda _request, _context: TranscriptionResult(
                "text", "de"
            )
            with self.assertRaises(SpeechFailure) as unsupported:
                app.transcribe(TranscriptionRequest(b"x", "audio/wav"))
            self.assertEqual(
                unsupported.exception.code, FailureCode.UNSUPPORTED_DETECTED_LANGUAGE
            )
            app.close()

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
            for request, expected in (
                (
                    TranscriptionRequest(b"x", "audio/wav"),
                    FailureCode.UNSUPPORTED_OPTION,
                ),
                (
                    TranscriptionRequest(b"x", "audio/wav", language="fr"),
                    FailureCode.INVALID_INPUT,
                ),
                (
                    TranscriptionRequest(b"x", "audio/wav", timestamps=True),
                    FailureCode.UNSUPPORTED_OPTION,
                ),
            ):
                with self.assertRaises(SpeechFailure) as caught:
                    app.transcribe(request)
                self.assertEqual(caught.exception.code, expected)
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

    def test_cold_load_failure_is_bounded_and_worker_remains_operational(self):
        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, behavior="load_failure")
            self.assertTrue(app.lifecycle.ready())
            self.assertTrue(app.lifecycle.live())
            with self.assertRaises(SpeechFailure) as caught:
                app.transcribe(TranscriptionRequest(b"x", "audio/wav"))
            self.assertEqual(caught.exception.code, FailureCode.MODEL_LOAD_FAILED)
            app.close()

        with tempfile.TemporaryDirectory() as directory:
            app = make_application(directory, behavior="wrong_identity")
            with self.assertRaises(SpeechFailure) as caught:
                app.transcribe(TranscriptionRequest(b"x", "audio/wav"))
            self.assertEqual(caught.exception.code, FailureCode.MODEL_LOAD_FAILED)
            self.assertTrue(app.lifecycle.ready())
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
            runners = []
            original_factory = app._runner_factory

            def capture_runner():
                runner = original_factory()
                runners.append(runner)
                return runner

            app._runner_factory = capture_runner
            with self.assertRaises(SpeechFailure) as load_error:
                app.warmup()
            self.assertEqual(load_error.exception.code, FailureCode.MODEL_LOAD_FAILED)
            runner = runners[0]
            self.assertTrue(app.lifecycle.live())
            self.assertFalse(app.lifecycle.ready())
            self.assertTrue(app.lifecycle.cleanup_unconfirmed())
            self.assertTrue(runner.cleanup_unconfirmed)
            with self.assertRaises(SpeechFailure) as caught:
                app.transcribe(TranscriptionRequest(b"audio", "audio/wav"))
            self.assertEqual(caught.exception.code, FailureCode.NOT_READY)

            process_control.hold_exit_confirmation = False
            self.assertTrue(runner.cleanup_event.wait(1))
            self.assertFalse(runner.cleanup_unconfirmed)
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
            self._wait_for(lambda: app.lifecycle.snapshot()[1] == ModelState.READY)
            queued = threading.Thread(target=invoke, args=(b"q",))
            queued.start()
            self._wait_for(lambda: app._admission.snapshot()["queued"] == 1)
            app.close()
            active.join(1)
            queued.join(1)
            self.assertFalse(active.is_alive() or queued.is_alive())
            self.assertEqual(len(captured), 2)
            self.assertGreaterEqual(captured.count(FailureCode.NOT_READY), 1)
            self.assertTrue(
                all(
                    code
                    in {
                        FailureCode.NOT_READY,
                        FailureCode.CANCELLED,
                        FailureCode.DEADLINE_EXCEEDED,
                    }
                    for code in captured
                )
            )
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


class M06HTTPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_warmup_then_transcription_uses_same_model_child(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_app_config(
                directory,
                idle_timeout=60,
                max_request_bytes=1024,
                max_upload_bytes=1024,
                max_retained_audio_bytes=1024,
            )
            factory = FakeBackendFactory()
            deployment = DeploymentConfig(
                {
                    "primary": ArtifactRoot(
                        Path(directory) / "unused", Path(directory) / "manifest"
                    )
                }
            )
            application = create_application(
                config,
                deployment,
                {"fake": factory},
                FakeDeviceProbe(),
                FakeArtifactStore(),
            )

            class HTTPFacade:
                config = application.config
                lifecycle = application.lifecycle

                @staticmethod
                def start():
                    application.start(factory().capabilities())

                def __getattr__(self, name):
                    return getattr(application, name)

            client = TestClient(TestServer(create_app(HTTPFacade())))
            await client.start_server()
            try:
                await client.app[STARTUP_TASK_KEY]
                readiness = await client.get("/readyz")
                self.assertEqual(readiness.status, 200)
                self.assertEqual(
                    application.lifecycle.snapshot()[1], ModelState.UNLOADED
                )
                self.assertIsNone(application.runner)

                warmed = await client.post(
                    "/internal/v1/warmup",
                    headers={"X-Request-Timeout-Ms": "5000"},
                )
                self.assertEqual(warmed.status, 200)
                self.assertEqual(await warmed.json(), {"model_state": "ready"})
                runner = application.runner
                self.assertIsNotNone(runner)

                form = FormData()
                form.add_field(
                    "audio",
                    b"synthetic audio fixture",
                    filename="synthetic.wav",
                    content_type="audio/wav",
                )
                form.add_field("timestamps", "false")
                transcription = await client.post(
                    "/internal/v1/transcriptions",
                    data=form,
                    headers={"X-Request-Timeout-Ms": "5000"},
                )
                self.assertEqual(transcription.status, 200)
                self.assertEqual(
                    (await transcription.json())["text"],
                    "fake transcription (23 bytes)",
                )
                repeated = await client.post(
                    "/internal/v1/transcriptions",
                    data=form,
                    headers={"X-Request-Timeout-Ms": "5000"},
                )
                self.assertEqual(repeated.status, 200)
                self.assertIs(application.runner, runner)
                ready_after = await client.get("/readyz")
                self.assertEqual(ready_after.status, 200)
            finally:
                await client.close()


def _capture(failures, callback):
    try:
        callback()
    except Exception as exc:
        failures.append(exc)


if __name__ == "__main__":
    unittest.main()
