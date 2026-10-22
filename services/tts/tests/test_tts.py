from __future__ import annotations

import json
import socket
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from services.tts.config import load_config
from services.tts.lifecycle import (
    ModelLifecycle,
    TTSFailure,
    language_instruction,
    mode_timesteps,
)
from services.tts.server import handler


ROOT = Path(__file__).resolve().parents[3]


def test_config():
    return load_config(ROOT / "configs/tts.yaml")


class ConfigTests(unittest.TestCase):
    def test_strict_config(self):
        source = (ROOT / "configs/tts.yaml").read_text()
        for name, content in {
            "valid": source,
            "unknown": source + "unexpected: true\n",
            "bad_digest": source.replace(
                "04d6e05b69b22568030ac21f494e406ffdf2d06efeeab43cfdb4c21ba8c9bd41",
                "x" * 64,
            ),
            "negative_idle": source.replace(
                "idle_unload_seconds: 60", "idle_unload_seconds: -1"
            ),
        }.items():
            with self.subTest(name=name):
                import tempfile

                with tempfile.TemporaryDirectory() as temp:
                    config_path = Path(temp) / "tts.yaml"
                    config_path.write_text(content)
                    if name == "valid":
                        self.assertEqual(load_config(config_path)["listen_port"], 8082)
                    else:
                        with self.assertRaises(ValueError):
                            load_config(config_path)


class ModeAndLanguageTests(unittest.TestCase):
    def test_mode_selection(self):
        self.assertEqual(mode_timesteps("quality"), 10)
        self.assertEqual(mode_timesteps("auto"), 10)
        self.assertEqual(mode_timesteps("fast"), 8)
        self.assertEqual(mode_timesteps("high_quality"), 16)
        with self.assertRaises(TTSFailure):
            mode_timesteps("turbo")

    def test_language_is_a_hint_and_auto_preserves_text(self):
        text = "Hello, мир."
        hints = {
            "en": "Speak in English.",
            "ru": "Speak in Russian.",
            "sv": "Speak in Swedish.",
        }
        self.assertEqual(language_instruction(text, "auto", hints), text)
        self.assertEqual(
            language_instruction(text, "ru", hints), "(Speak in Russian.)Hello, мир."
        )


class LifecycleTests(unittest.TestCase):
    def test_synthesis_selects_steps_for_each_mode(self):
        lifecycle = ModelLifecycle({"idle_unload_seconds": 0}, object)
        observed = []
        lifecycle._generate = lambda _model, _text, _language, steps: (
            observed.append(steps) or b"wav",
            "audio/wav",
        )
        try:
            for mode in ("quality", "fast", "auto", "high_quality"):
                lifecycle.synthesize("hello", "auto", mode)
            self.assertEqual(observed, [10, 8, 10, 16])
        finally:
            lifecycle.stop(1)

    def test_warmup_loads_and_idle_unload_reloads(self):
        calls = []
        lifecycle = ModelLifecycle(
            {"idle_unload_seconds": 0.2},
            lambda: calls.append(object()) or calls[-1],
        )
        try:
            self.assertEqual(lifecycle.state()["model_state"], "unloaded")
            lifecycle.warmup()
            self.assertEqual(lifecycle.state()["model_state"], "loaded")
            deadline = time.monotonic() + 2
            while (
                lifecycle.state()["model_state"] != "unloaded"
                and time.monotonic() < deadline
            ):
                time.sleep(0.02)
            self.assertEqual(lifecycle.state()["model_state"], "unloaded")
            lifecycle.warmup()
            self.assertEqual(len(calls), 2)
        finally:
            lifecycle.stop(1)

    def test_active_inference_prevents_unload(self):
        entered = threading.Event()
        release = threading.Event()
        lifecycle = ModelLifecycle({"idle_unload_seconds": 0.1}, object)
        worker = threading.Thread(
            target=lambda: lifecycle._with_model(
                lambda _model: (entered.set(), release.wait(2))
            )
        )
        try:
            worker.start()
            self.assertTrue(entered.wait(1))
            time.sleep(1.2)
            self.assertEqual(
                lifecycle.state(), {"model_state": "loaded", "inference_active": True}
            )
        finally:
            release.set()
            worker.join(1)
            lifecycle.stop(1)

    def test_failed_load_recovers_on_next_request(self):
        attempts = []

        def factory():
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError("temporary load failure")
            return object()

        lifecycle = ModelLifecycle({"idle_unload_seconds": 0}, factory)
        try:
            with self.assertRaises(TTSFailure) as caught:
                lifecycle.warmup()
            self.assertEqual(caught.exception.code, "model_load_failed")
            self.assertEqual(lifecycle.state()["model_state"], "unloaded")
            lifecycle.warmup()
            self.assertEqual(lifecycle.state()["model_state"], "loaded")
            self.assertEqual(len(attempts), 2)
        finally:
            lifecycle.stop(1)

    def test_inference_failure_does_not_latch_worker(self):
        lifecycle = ModelLifecycle({"idle_unload_seconds": 0}, object)
        attempts = []
        original = lifecycle._generate

        def sometimes_fail(*args):
            attempts.append(True)
            if len(attempts) == 1:
                raise TTSFailure("inference_failed", "synthetic failure", 500)
            return b"wav", "audio/wav"

        lifecycle._generate = sometimes_fail
        try:
            with self.assertRaises(TTSFailure):
                lifecycle.synthesize("hello", "auto", "quality")
            self.assertEqual(lifecycle.state()["model_state"], "loaded")
            self.assertEqual(
                lifecycle.synthesize("hello", "auto", "quality"), (b"wav", "audio/wav")
            )
            self.assertEqual(len(attempts), 2)
        finally:
            lifecycle._generate = original
            lifecycle.stop(1)


class WorkerHTTPTests(unittest.TestCase):
    def setUp(self):
        class FakeLifecycle:
            def __init__(self):
                self.started = threading.Event()
                self.release = threading.Event()
                self.finished = threading.Event()
                self.requests = []

            def ready(self):
                return True

            def state(self):
                return {"model_state": "unloaded", "inference_active": False}

            def warmup(self):
                return None

            def synthesize(self, text, language, mode):
                self.requests.append((text, language, mode))
                self.started.set()
                self.release.wait(2)
                self.finished.set()
                import io
                import wave

                output = io.BytesIO()
                with wave.open(output, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(24000)
                    wav.writeframes(b"\x00\x00" * 8)
                return output.getvalue(), "audio/wav"

        self.lifecycle = FakeLifecycle()
        self.config = test_config()
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler(self.config, self.lifecycle)
        )
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.lifecycle.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(1)

    def _request(self, payload):
        import urllib.error
        import urllib.request

        request = urllib.request.Request(
            self.url + "/internal/v1/speech",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            return urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            return error

    def assert_valid_wav(self, audio):
        import io
        import wave

        with wave.open(io.BytesIO(audio), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 24000)
            self.assertEqual(wav.getnframes(), 8)

    def test_request_defaults_and_validation(self):
        self.lifecycle.release.set()
        response = self._request(b'{"text":"hello"}')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "audio/wav")
        audio = response.read()
        self.assert_valid_wav(audio)
        self.assertEqual(self.lifecycle.requests[-1], ("hello", "auto", "quality"))
        for payload, status, code in (
            (b'{"text":"hi","language":"zh"}', 400, "invalid_language"),
            (b'{"text":"hi","extra":1}', 400, "invalid_request"),
            (b'{"text":"hi","mode":"turbo"}', 400, "invalid_mode"),
            (b'{"text":3}', 400, "invalid_text"),
        ):
            response = self._request(payload)
            self.assertEqual(response.code, status)
            self.assertEqual(json.loads(response.read())["code"], code)

    def test_supported_modes_return_wav_with_audio_metadata(self):
        self.lifecycle.release.set()
        for mode in ("quality", "fast", "auto", "high_quality"):
            with self.subTest(mode=mode):
                response = self._request(
                    json.dumps({"text": "hello", "mode": mode}).encode()
                )
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], "audio/wav")
                audio = response.read()
                self.assert_valid_wav(audio)
                self.assertEqual(self.lifecycle.requests[-1][2], mode)

    def test_worker_admission_is_single_slot(self):
        payload = b'{"text":"first"}'
        body = (
            f"POST /internal/v1/speech HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
            + payload
        )
        client = socket.create_connection(
            ("127.0.0.1", self.server.server_port), timeout=2
        )
        client.sendall(body)
        self.assertTrue(self.lifecycle.started.wait(1))
        rejected = self._request(b'{"text":"second"}')
        self.assertEqual(rejected.code, 429)
        self.lifecycle.release.set()
        client.close()

    def test_cancelled_client_does_not_interrupt_native_call(self):
        payload = b'{"text":"hello","language":"sv"}'
        body = (
            f"POST /internal/v1/speech HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
            + payload
        )
        client = socket.create_connection(
            ("127.0.0.1", self.server.server_port), timeout=2
        )
        client.sendall(body)
        self.assertTrue(self.lifecycle.started.wait(1))
        client.close()
        self.lifecycle.release.set()
        self.assertTrue(self.lifecycle.finished.wait(1))
        self.assertEqual(self.lifecycle.requests[-1], ("hello", "sv", "quality"))


if __name__ == "__main__":
    unittest.main()
