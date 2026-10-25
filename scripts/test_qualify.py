from __future__ import annotations

import contextlib
import io
import json
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts import qualify


TOKEN = "synthetic-token-that-never-appears-in-reports-123"


class Response:
    status = 200
    headers = {"X-Speech-Provider": "local", "Content-Type": "application/json"}

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        return self.body


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 1600)
    return buffer.getvalue()


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "private").mkdir()
        self.env = {
            "SPEECH_API_URL": "http://127.0.0.1:8080",
            "SPEECH_API_TOKEN": TOKEN,
        }

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, argv, body):
        captured = {}

        def open_url(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return Response(body)

        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", side_effect=open_url),
        ):
            status = qualify.main(argv)
        return status, captured

    def test_transform_builds_public_request_and_default_report_hides_text(self):
        status, seen = self.invoke(
            ["transform", "--text", "private synthetic words"],
            json.dumps(
                {
                    "original_text": "source",
                    "transformed_text": "private output",
                    "options": {
                        "mode": "written",
                        "format": "normal",
                        "target_language": "none",
                        "model": None,
                        "local_only": True,
                    },
                    "provider": "host-ollama",
                    "model": "local-qwen",
                    "generated": True,
                    "fallback_occurred": False,
                }
            ).encode(),
        )
        self.assertEqual(status, 0)
        request = seen["request"]
        self.assertEqual(request.get_header("Authorization"), f"Bearer {TOKEN}")
        payload = json.loads(request.data)
        self.assertTrue(payload["local_only"])
        self.assertEqual(payload["target_language"], "none")
        self.assertNotIn("private synthetic words", str(seen))

    def test_groq_requires_explicit_consent_before_request(self):
        with (
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen") as opened,
        ):
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                qualify.main(
                    [
                        "stt",
                        "--audio",
                        str(self.root / "missing.wav"),
                        "--provider",
                        "groq",
                    ]
                )
        self.assertEqual(raised.exception.code, 2)
        opened.assert_not_called()

    def test_stt_pins_local_and_extracts_provider_metadata(self):
        audio = self.root / "sample.wav"
        audio.write_bytes(b"audio-fixture")
        _, seen = self.invoke(
            ["stt", "--audio", str(audio)],
            json.dumps(
                {"text": "transcript", "language": "en", "detected_language": "en"}
            ).encode(),
        )
        request = seen["request"]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-stt-provider"], "local")
        self.assertEqual(headers["x-allow-cloud-audio"], "false")

    def test_tts_validates_wav_and_writes_private_file_exclusively(self):
        output = self.root / "private" / "output.wav"
        status, seen = self.invoke(
            ["tts", "--text", "sample", "--output", str(output)], wav_bytes()
        )
        self.assertEqual(status, 0)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(
            seen["request"].full_url, "http://127.0.0.1:8080/v1/tts/speech"
        )

    def test_wav_rejects_truncation_and_incomplete_final_frame(self):
        valid = wav_bytes()
        with self.assertRaises(qualify.QualificationError):
            qualify._wav_metadata(valid[:-1])

        partial = bytearray(valid)
        data_header = partial.index(b"data")
        data_size = struct.unpack_from("<I", partial, data_header + 4)[0]
        partial.extend(b"\x7f\x00")  # One extra data byte and its RIFF pad byte.
        struct.pack_into("<I", partial, data_header + 4, data_size + 1)
        struct.pack_into("<I", partial, 4, len(partial) - 8)
        with self.assertRaises(qualify.QualificationError):
            qualify._wav_metadata(bytes(partial))

    def test_stt_rejects_missing_required_fields_and_invalid_types(self):
        audio = self.root / "sample.wav"
        audio.write_bytes(b"audio")
        for body in (
            {"text": "transcript"},
            {"text": 4, "language": "en"},
            {"text": "transcript", "language": None},
            {"text": "transcript", "language": "en", "translated": "false"},
        ):
            with self.subTest(body=body):
                status, _ = self.invoke(
                    ["stt", "--audio", str(audio)], json.dumps(body).encode()
                )
                self.assertEqual(status, qualify.EXIT_REQUEST)

    def test_transform_rejects_incomplete_response_and_invalid_field_types(self):
        good = {
            "original_text": "source",
            "transformed_text": "output",
            "options": {
                "mode": "written",
                "format": "normal",
                "target_language": "none",
                "model": None,
                "local_only": True,
            },
            "model": "local-qwen",
            "provider": "host-ollama",
            "fallback_occurred": False,
            "generated": True,
        }
        cases = []
        missing = good.copy()
        del missing["original_text"]
        cases.append(missing)
        invalid = good.copy()
        invalid["generated"] = "true"
        cases.append(invalid)
        invalid_options = good.copy()
        invalid_options["options"] = {**good["options"], "local_only": "yes"}
        cases.append(invalid_options)
        for body in cases:
            with self.subTest(body=body):
                status, _ = self.invoke(
                    ["transform", "--text", "source"], json.dumps(body).encode()
                )
                self.assertEqual(status, qualify.EXIT_REQUEST)

    def test_malformed_json_is_classified_as_invalid_response(self):
        status, _ = self.invoke(["transform", "--text", "source"], b"{")
        self.assertEqual(status, qualify.EXIT_REQUEST)

    def test_connection_failure_timeout_and_oversized_response_are_classified(self):
        for exception, expected in (
            (URLError(ConnectionRefusedError()), "connection"),
            (TimeoutError(), "timeout"),
            (URLError(TimeoutError()), "timeout"),
        ):
            with (
                self.subTest(expected=expected),
                patch.object(qualify, "urlopen", side_effect=exception),
            ):
                with self.assertRaises(qualify.QualificationError) as raised:
                    qualify._request(
                        "http://localhost", TOKEN, b"x", "text/plain", 1, 5
                    )
                self.assertEqual(raised.exception.classification, expected)
        with patch.object(qualify, "urlopen", return_value=Response(b"123456")):
            with self.assertRaises(qualify.QualificationError) as raised:
                qualify._request("http://localhost", TOKEN, b"x", "text/plain", 1, 5)
        self.assertEqual(raised.exception.classification, "invalid_response")

    def test_duplicate_canonical_output_paths_fail_before_request(self):
        (self.root / "private" / "nested").mkdir()
        first = self.root / "private" / "result.json"
        alias = self.root / "private" / "nested" / ".." / "result.json"
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen") as opened,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            status = qualify.main(
                [
                    "tts",
                    "--text",
                    "sample",
                    "--report",
                    str(first),
                    "--output",
                    str(alias),
                ]
            )
        self.assertEqual(status, qualify.EXIT_INPUT)
        opened.assert_not_called()

    def test_file_output_failure_returns_output_exit_code(self):
        output = self.root / "private" / "out.wav"
        report_path = self.root / "private" / "report.json"
        actual_write = qualify._write_private

        def fail_audio(path, data):
            if path == output:
                raise qualify.QualificationError("output_error", "write failed")
            return actual_write(path, data)

        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", return_value=Response(wav_bytes())),
            patch.object(
                qualify,
                "_write_private",
                side_effect=fail_audio,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = qualify.main(
                [
                    "tts",
                    "--text",
                    "sample",
                    "--output",
                    str(output),
                    "--report",
                    str(report_path),
                ]
            )
        self.assertEqual(status, qualify.EXIT_OUTPUT)
        report = json.loads(report_path.read_text())
        self.assertEqual(report["http"], {"status": 200, "success": True})
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(
            report["technical_checks"], [{"name": "valid_pcm16_wav", "passed": True}]
        )
        self.assertFalse(report["artifact"]["saved"])

    def test_previous_audio_artifact_remains_if_report_write_fails(self):
        output = self.root / "private" / "out.wav"
        report = self.root / "private" / "report.json"
        actual_write = qualify._write_private

        def fail_report(path, data):
            if path == report:
                raise qualify.QualificationError("output_error", "write failed")
            return actual_write(path, data)

        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", return_value=Response(wav_bytes())),
            patch.object(qualify, "_write_private", side_effect=fail_report),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            status = qualify.main(
                [
                    "tts",
                    "--text",
                    "sample",
                    "--output",
                    str(output),
                    "--report",
                    str(report),
                ]
            )
        self.assertEqual(status, qualify.EXIT_OUTPUT)
        self.assertTrue(output.is_file())

    def test_http_error_preserves_api_code_without_message_payload(self):
        error = HTTPError(
            "https://gateway.invalid",
            403,
            "no",
            {},
            io.BytesIO(b'{"code":"cloud_disabled","message":"secret text"}'),
        )
        with patch.object(qualify, "urlopen", side_effect=error):
            with self.assertRaises(qualify.QualificationError) as raised:
                qualify._request(
                    "https://gateway.invalid", TOKEN, b"x", "application/json", 1, 1024
                )
        self.assertEqual(raised.exception.classification, "authorization")
        self.assertEqual(raised.exception.api_code, "cloud_disabled")
        self.assertNotIn("secret text", str(raised.exception))

    def test_json_report_is_private_exclusive_and_content_free(self):
        report_path = self.root / "private" / "report.json"
        body = json.dumps(
            {
                "original_text": "source",
                "transformed_text": "private output",
                "options": {
                    "mode": "written",
                    "format": "normal",
                    "target_language": "none",
                    "model": None,
                    "local_only": True,
                },
                "provider": "host-ollama",
                "model": "local-qwen",
                "generated": True,
                "fallback_occurred": False,
            }
        ).encode()
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", return_value=Response(body)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = qualify.main(
                ["transform", "--text", "secret input", "--report", str(report_path)]
            )
        report_text = report_path.read_text()
        report = json.loads(report_text)
        self.assertEqual(status, 0)
        self.assertEqual(stat.S_IMODE(report_path.stat().st_mode), 0o600)
        self.assertNotIn("secret input", report_text)
        self.assertNotIn("private output", report_text)
        self.assertEqual(report["schema_version"], "1.0")

    def test_preflight_failure_can_be_recorded_without_sensitive_input(self):
        report_path = self.root / "private" / "failed.json"
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value={}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = qualify.main(
                [
                    "transform",
                    "--text",
                    "do not record this",
                    "--report",
                    str(report_path),
                ]
            )
        report_text = report_path.read_text()
        report = json.loads(report_text)
        self.assertEqual(status, qualify.EXIT_INPUT)
        self.assertEqual(report["error"]["classification"], "authentication")
        self.assertNotIn("do not record this", report_text)

    def test_raw_structured_rejected_before_network(self):
        with (
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen") as opened,
            patch.object(qualify, "ROOT", self.root),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            status = qualify.main(
                ["transform", "--text", "x", "--mode", "raw", "--format", "structured"]
            )
        self.assertEqual(status, qualify.EXIT_INPUT)
        opened.assert_not_called()

    def test_make_verification_keeps_original_smoke_cli_module_entrypoint(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "make",
                "-n",
                "test-stt",
                f"PYTHON={sys.executable}",
                "AUDIO=private/a.wav",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("-m scripts.api_smoke stt", result.stdout)


if __name__ == "__main__":
    unittest.main()
