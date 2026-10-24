"""Ordinary synthesis budgets use fake models and controlled checkpoints only."""

import http.client
import contextlib
from types import SimpleNamespace
from unittest.mock import Mock
import json
import threading
import time
import tempfile
from pathlib import Path
import yaml
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from services.tts.audio_processing import process_gently
from services.tts.config import load_config
from services.tts.lifecycle import ModelLifecycle, SynthesisContext, TTSFailure
from services.tts.server import handler
from services.tts.tests.test_tts import test_config, wav_segment

SSML = '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" xml:lang="en">First.<break time="3s"/><lang xml:lang="sv">Andra.</lang></speak>'


class SynthesisDeadlineTests(unittest.TestCase):
    def test_request_timeout_is_validated_with_legacy_default(self):
        config = test_config()
        config.pop("request_timeout_seconds")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tts.yaml"
            path.write_text(yaml.safe_dump(config))
            self.assertEqual(load_config(path)["request_timeout_seconds"], 600)
            for value in (0, -1, True, 1.5, "600", 86401):
                config["request_timeout_seconds"] = value
                path.write_text(yaml.safe_dump(config))
                with self.assertRaisesRegex(ValueError, "request_timeout_seconds"):
                    load_config(path)

    def test_mastering_does_not_start_second_pass_after_cancellation(self):
        cancelled, calls = [False], []

        def check():
            if cancelled[0]:
                raise TTSFailure(
                    "request_cancelled", "speech request was cancelled", 504
                )

        def analyze(_args, remaining, **_kwargs):
            calls.append(remaining)
            cancelled[0] = True
            return json.dumps(
                dict(
                    input_i=-20,
                    input_tp=-6,
                    input_lra=2,
                    input_thresh=-30,
                    target_offset=0,
                )
            ).encode()

        with (
            patch(
                "services.tts.audio_processing.shutil.which",
                return_value="/fake/ffmpeg",
            ),
            patch("services.tts.audio_processing._run", side_effect=analyze),
        ):
            with self.assertRaises(TTSFailure):
                process_gently(
                    wav_segment(b"\xe0\x2e" * 480),
                    test_config(),
                    deadline=time.monotonic() + 1,
                    check=check,
                )
        self.assertEqual(len(calls), 1)
        self.assertTrue(0 < calls[0] <= 1)

    def test_expiration_at_native_entry_prevents_model_generate(self):
        now = [0]

        @contextlib.contextmanager
        def inference_mode():
            now[0] = 10
            yield

        model = SimpleNamespace(generate=Mock())
        lifecycle = ModelLifecycle(test_config(), object)
        try:
            with patch.dict(
                "sys.modules",
                {
                    "torch": SimpleNamespace(inference_mode=inference_mode),
                    "soundfile": SimpleNamespace(),
                },
            ):
                with self.assertRaises(TTSFailure) as caught:
                    lifecycle._generate(
                        model,
                        "Hello",
                        "en",
                        10,
                        context=SynthesisContext(10, clock=lambda: now[0]),
                    )
                self.assertEqual(caught.exception.code, "deadline_exceeded")
                model.generate.assert_not_called()
        finally:
            lifecycle.stop(1)

    def test_expired_budget_does_not_load(self):
        calls = []
        lifecycle = ModelLifecycle(test_config(), lambda: calls.append("load"))
        try:
            with self.assertRaises(TTSFailure) as caught:
                lifecycle.synthesize(
                    "Hello",
                    "en",
                    "quality",
                    context=SynthesisContext(0, clock=lambda: 1),
                )
            self.assertEqual(caught.exception.status, 504)
            self.assertEqual(calls, [])
        finally:
            lifecycle.stop(1)

    def test_load_completion_after_deadline_does_not_start_inference(self):
        now, calls = [0], []

        def load():
            now[0] = 11
            return object()

        lifecycle = ModelLifecycle(test_config(), load)
        lifecycle._generate = lambda *args, **_kwargs: calls.append("inference")
        try:
            with self.assertRaises(TTSFailure) as caught:
                lifecycle.synthesize(
                    "Hello",
                    "en",
                    "quality",
                    context=SynthesisContext(10, clock=lambda: now[0]),
                )
            self.assertEqual(caught.exception.code, "deadline_exceeded")
            self.assertEqual(calls, [])
            self.assertFalse(lifecycle.state()["inference_active"])
        finally:
            lifecycle.stop(1)

    def test_load_failure_after_deadline_is_timeout_not_unavailable(self):
        now = [0]

        def load():
            now[0] = 11
            raise RuntimeError("synthetic private diagnostic")

        lifecycle = ModelLifecycle(test_config(), load)
        try:
            with self.assertRaises(TTSFailure) as caught:
                lifecycle.synthesize(
                    "Hello",
                    "en",
                    "quality",
                    context=SynthesisContext(10, clock=lambda: now[0]),
                )
            self.assertEqual(caught.exception.code, "deadline_exceeded")
            self.assertEqual(caught.exception.status, 504)
            self.assertNotIn("private", caught.exception.message)
        finally:
            lifecycle.stop(1)

    def test_no_later_ssml_segment_or_mastering_after_expiration_or_disconnect(self):
        for reason in ("deadline", "disconnect"):
            with self.subTest(reason=reason):
                now, disconnected, calls = [0], [False], []
                lifecycle = ModelLifecycle(test_config(), object)

                def generate(_model, text, _language, _steps, *, context=None):
                    calls.append(text)
                    if reason == "deadline":
                        now[0] = 10
                    else:
                        disconnected[0] = True
                    return wav_segment(b"\x01\x00" * 480), "audio/wav"

                lifecycle._generate = generate
                context = SynthesisContext(
                    10, lambda: disconnected[0], clock=lambda: now[0]
                )
                try:
                    with patch("services.tts.lifecycle.process_gently") as processing:
                        with self.assertRaises(TTSFailure) as caught:
                            lifecycle.synthesize(
                                SSML,
                                "auto",
                                "quality",
                                "ssml",
                                "gentle",
                                context=context,
                            )
                        self.assertEqual(caught.exception.status, 504)
                        processing.assert_not_called()
                    self.assertEqual(calls, ["First."])
                    self.assertFalse(lifecycle.state()["inference_active"])
                    # Expiration does not poison a resident model or initiate retries.
                    lifecycle._generate = lambda *_, **_kwargs: (
                        wav_segment(b"\x01\x00" * 480),
                        "audio/wav",
                    )
                    self.assertTrue(lifecycle.synthesize("Next", "en", "quality")[0])
                finally:
                    lifecycle.stop(1)

    def test_mastering_receives_same_absolute_deadline(self):
        lifecycle = ModelLifecycle(test_config(), object)
        audio = wav_segment(b"\x01\x00" * 480)
        lifecycle._generate = lambda *_, **_kwargs: (audio, "audio/wav")
        context = SynthesisContext(10, clock=lambda: 0)
        try:
            with patch(
                "services.tts.lifecycle.process_gently", return_value=audio
            ) as processing:
                self.assertEqual(
                    lifecycle.synthesize(
                        "Hello",
                        "en",
                        "quality",
                        audio_processing="gentle",
                        context=context,
                    )[0],
                    audio,
                )
                self.assertEqual(processing.call_args.kwargs["deadline"], 10)
                self.assertEqual(processing.call_args.kwargs["check"], context.check)
        finally:
            lifecycle.stop(1)


class WorkerDeadlineTests(unittest.TestCase):
    def setUp(self):
        class Fake:
            def __init__(self):
                self.calls = []
                self.entered, self.release, self.completed = (
                    threading.Event(),
                    threading.Event(),
                    threading.Event(),
                )
                self.continued = False
                self.disconnected = lambda: False

            def synthesize(self, *args, context=None):
                context.check()
                self.calls.append(context.deadline - time.monotonic())
                if args[0] == "Block":
                    self.disconnected = context.disconnected
                    self.entered.set()
                    try:
                        self.release.wait(2)
                        context.check()
                        self.continued = True
                    finally:
                        self.completed.set()
                if args[0] == "Expire":
                    context.clock = lambda: context.deadline
                    context.check()
                return wav_segment(b"\x01\x00" * 480), "audio/wav"

        self.fake = Fake()
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler(test_config(), self.fake)
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.fake.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(1)

    def request(self, header=None, text="Hello"):
        client = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=2
        )
        headers = {"Content-Type": "application/json"}
        if header is not None:
            headers["X-Request-Timeout-Ms"] = header
        try:
            client.request(
                "POST", "/internal/v1/speech", json.dumps({"text": text}), headers
            )
            response = client.getresponse()
            return response.status, response.read()
        finally:
            client.close()

    def test_header_validation_default_and_remaining_budget(self):
        for invalid in ("", "0", "-1", "NaN", "99999999999"):
            status, body = self.request(invalid)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["code"], "invalid_request")
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.request()[0], 200)
        self.assertGreater(self.fake.calls[-1], 590)
        self.assertEqual(self.request("5000")[0], 200)
        self.assertTrue(0 < self.fake.calls[-1] <= 5)
        self.assertEqual(self.request("9999999999")[0], 200)
        self.assertTrue(0 < self.fake.calls[-1] <= 600)

    def test_stalled_upload_expires_before_synthesis(self):
        client = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=2
        )
        try:
            client.putrequest("POST", "/internal/v1/speech")
            client.putheader("Content-Type", "application/json")
            client.putheader("Content-Length", "100")
            client.putheader("X-Request-Timeout-Ms", "20")
            client.endheaders()
            client.send(b"{")
            response = client.getresponse()
            self.assertEqual(response.status, 504)
            self.assertEqual(json.loads(response.read())["code"], "deadline_exceeded")
            self.assertEqual(self.fake.calls, [])
        finally:
            client.close()

    def test_disconnection_does_not_interrupt_active_call_but_stops_followup(self):
        client = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=2
        )
        try:
            client.request(
                "POST",
                "/internal/v1/speech",
                json.dumps({"text": "Block"}),
                {"Content-Type": "application/json"},
            )
            self.assertTrue(self.fake.entered.wait(1))
            client.close()
            deadline = time.monotonic() + 1
            while not self.fake.disconnected() and time.monotonic() < deadline:
                self.fake.completed.wait(0.005)
            self.assertTrue(self.fake.disconnected())
            self.assertFalse(self.fake.completed.is_set())
            self.fake.release.set()
            self.assertTrue(self.fake.completed.wait(1))
            self.assertFalse(self.fake.continued)
            self.assertEqual(len(self.fake.calls), 1)
        finally:
            client.close()
            self.fake.release.set()

    def test_expired_inference_returns_504_without_retry(self):
        status, body = self.request("5000", "Expire")
        self.assertEqual(status, 504)
        self.assertEqual(json.loads(body)["code"], "deadline_exceeded")
        self.assertEqual(len(self.fake.calls), 1)
