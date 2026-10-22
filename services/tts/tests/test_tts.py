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
from services.tts.audio import InvalidAudio, compose_wav, pcm16_frames
from services.tts.ssml import (
    SSMLValidationError,
    SilenceSegment,
    SpeechSegment,
    parse_ssml,
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
            "too_many_segments": source.replace(
                "max_ssml_segments: 64", "max_ssml_segments: 0"
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


def ssml_config(**overrides):
    config = test_config()
    config.update(overrides)
    return config


class SSMLParserTests(unittest.TestCase):
    def test_ordered_languages_breaks_and_consecutive_breaks(self):
        document = (
            '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" '
            'xml:lang="en-US">hello <break time="250ms"/>'
            '<break time="0.5s"/><lang xml:lang="sv-SE">hej '
            '<lang xml:lang="ru-RU">мир</lang> igen</lang></speak>'
        )
        self.assertEqual(
            parse_ssml(document, ssml_config()),
            [
                SpeechSegment("hello ", "en"),
                SilenceSegment(250),
                SilenceSegment(500),
                SpeechSegment("hej ", "sv"),
                SpeechSegment("мир", "ru"),
                SpeechSegment(" igen", "sv"),
            ],
        )

    def test_ignores_formatting_whitespace_but_preserves_inline_space(self):
        document = """<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" xml:lang="en">
  hello <lang xml:lang="sv">hej</lang> there
</speak>"""
        self.assertEqual(
            parse_ssml(document, ssml_config()),
            [
                SpeechSegment("hello ", "en"),
                SpeechSegment("hej", "sv"),
                SpeechSegment(" there", "en"),
            ],
        )

    def test_rejects_malformed_unsupported_and_unsafe_markup(self):
        prefix = '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" xml:lang="en">'
        cases = (
            "<speak",
            prefix + "hello</wrong>",
            '<speak xmlns="urn:wrong" version="1.1" xml:lang="en">hello</speak>',
            '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1">hello</speak>',
            prefix.replace('xml:lang="en"', 'xml:lang="en" extra="x"')
            + "hello</speak>",
            prefix.replace('version="1.1"', 'version="1.0"') + "hello</speak>",
            prefix + '<prosody rate="slow">hello</prosody></speak>',
            prefix + '<break strength="weak"/></speak>',
            prefix + '<lang xml:lang="de">hello</lang></speak>',
            prefix + '<break time="1.0001s"/></speak>',
            '<!DOCTYPE speak [<!ENTITY x "hello">]>' + prefix + "&x;</speak>",
            '<!DOCTYPE speak SYSTEM "file:///etc/passwd">' + prefix + "hello</speak>",
        )
        for document in cases:
            with (
                self.subTest(document=document[:80]),
                self.assertRaises(SSMLValidationError),
            ):
                parse_ssml(document, ssml_config())

    def test_rejects_each_configured_limit_and_no_speech(self):
        def document(body):
            return (
                '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" xml:lang="en">'
                + body
                + "</speak>"
            )

        checks = (
            (document("hello"), {"max_ssml_bytes": 10}),
            (document("hello"), {"max_text_characters": 4}),
            (
                document('<lang xml:lang="sv">a</lang><lang xml:lang="ru">b</lang>'),
                {"max_ssml_segments": 1},
            ),
            (
                document('<break time="0ms"/><break time="0ms"/>hello'),
                {"max_ssml_elements": 2},
            ),
            (
                document('<lang xml:lang="sv"><lang xml:lang="ru">hello</lang></lang>'),
                {"max_ssml_nesting_depth": 1},
            ),
            (document('<break time="1001ms"/>hello'), {"max_ssml_break_ms": 1000}),
            (
                document('<break time="600ms"/><break time="600ms"/>hello'),
                {"max_ssml_total_silence_ms": 1000},
            ),
            (
                document("hello"),
                {
                    "max_output_audio_bytes": 1024,
                    "ssml_estimated_characters_per_second": 0.01,
                },
            ),
        )
        for source, overrides in checks:
            with (
                self.subTest(overrides=overrides),
                self.assertRaises(SSMLValidationError),
            ):
                parse_ssml(source, ssml_config(**overrides))
        with self.assertRaises(SSMLValidationError):
            parse_ssml(document(" \n  "), ssml_config())


def wav_segment(frames: bytes) -> bytes:
    import io
    import wave

    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(frames)
    return output.getvalue()


class AudioCompositionTests(unittest.TestCase):
    def test_composes_exact_silence_and_one_mono_pcm16_48khz_wav(self):
        first = b"\x01\x00" * 100
        silence = b"\x00\x00" * (250 * 48)
        second = b"\x02\x00" * 50
        composed = compose_wav([first, silence, second], 100000)
        frames = pcm16_frames(composed)
        self.assertEqual(len(frames), (100 + 250 * 48 + 50) * 2)
        self.assertEqual(frames[: len(first)], first)
        self.assertEqual(frames[len(first) : len(first) + len(silence)], silence)
        self.assertEqual(frames[-len(second) :], second)
        import io
        import wave

        with wave.open(io.BytesIO(composed), "rb") as wav:
            self.assertEqual(
                (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()),
                (1, 2, 48000),
            )
            self.assertEqual(wav.getcomptype(), "NONE")

    def test_rejects_bad_input_format_and_output_limit(self):
        with self.assertRaises(InvalidAudio):
            pcm16_frames(b"not a wav")
        with self.assertRaises(InvalidAudio):
            compose_wav([b"\x00\x00" * 100], 100)


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

    def test_ssml_synthesis_uses_language_context_and_composes_all_segments(self):
        lifecycle = ModelLifecycle(ssml_config(idle_unload_seconds=0), object)
        observed = []

        def generate(_model, text, language, steps):
            observed.append((text, language, steps))
            marker = {"en": b"\x01\x00", "sv": b"\x02\x00", "ru": b"\x03\x00"}[language]
            return wav_segment(marker * 480), "audio/wav"

        lifecycle._generate = generate
        document = (
            '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" '
            'xml:lang="en-US">one<break time="10ms"/>'
            '<lang xml:lang="sv-SE">två<lang xml:lang="ru-RU">три</lang></lang>'
            "</speak>"
        )
        try:
            result, content_type = lifecycle.synthesize(
                document, "auto", "high_quality", "ssml"
            )
            self.assertEqual(content_type, "audio/wav")
            self.assertEqual(
                observed,
                [("one", "en", 16), ("två", "sv", 16), ("три", "ru", 16)],
            )
            frames = pcm16_frames(result)
            self.assertEqual(len(frames) // 2, 480 * 3 + 480)
            self.assertEqual(frames[480 * 2 : 480 * 2 + 480 * 2], b"\x00\x00" * 480)
        finally:
            lifecycle.stop(1)

    def test_ssml_segment_failure_never_returns_composed_audio(self):
        lifecycle = ModelLifecycle(ssml_config(idle_unload_seconds=0), object)
        calls = []

        def generate(_model, text, language, steps):
            calls.append(text)
            if text == "second":
                raise TTSFailure("inference_failed", "synthetic failure", 500)
            return wav_segment(b"\x00\x00" * 480), "audio/wav"

        lifecycle._generate = generate
        document = (
            '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" '
            'xml:lang="en">first<lang xml:lang="sv">second</lang></speak>'
        )
        try:
            with self.assertRaises(TTSFailure):
                lifecycle.synthesize(document, "auto", "quality", "ssml")
            self.assertEqual(calls, ["first", "second"])
            self.assertEqual(lifecycle.state()["model_state"], "loaded")
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

            def synthesize(self, text, language, mode, input_format="text"):
                self.requests.append((text, language, mode, input_format))
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
        self.assertEqual(
            self.lifecycle.requests[-1], ("hello", "auto", "quality", "text")
        )
        for payload, status, code in (
            (b'{"text":"hi","language":"zh"}', 400, "invalid_language"),
            (b'{"text":"hi","extra":1}', 400, "invalid_request"),
            (b'{"text":"hi","mode":"turbo"}', 400, "invalid_mode"),
            (b'{"text":"hi","input_format":"guess"}', 400, "invalid_input_format"),
            (
                b'{"text":"hi","input_format":"ssml","language":"en"}',
                400,
                "invalid_language",
            ),
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

    def test_explicit_ssml_input_format_is_forwarded(self):
        self.lifecycle.release.set()
        response = self._request(
            json.dumps(
                {
                    "text": '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" xml:lang="en">hello</speak>',
                    "input_format": "ssml",
                }
            ).encode()
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(self.lifecycle.requests[-1][3], "ssml")

    def test_explicit_text_input_format_preserves_plain_text_path(self):
        self.lifecycle.release.set()
        response = self._request(b'{"text":"hello","input_format":"text"}')
        self.assertEqual(response.status, 200)
        self.assertEqual(
            self.lifecycle.requests[-1], ("hello", "auto", "quality", "text")
        )

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
        payload = json.dumps(
            {
                "text": '<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" xml:lang="sv">hello</speak>',
                "input_format": "ssml",
            }
        ).encode()
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
        self.assertEqual(self.lifecycle.requests[-1][2:], ("quality", "ssml"))


if __name__ == "__main__":
    unittest.main()
