from __future__ import annotations

import contextlib
import io
import json
import os
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
    headers = {
        "X-Speech-Provider": "local",
        "X-Speech-Prompt-SHA256": "a" * 64,
        "Content-Type": "application/json",
    }

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

    def test_transform_omits_default_model_and_keeps_report_content_free(self):
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
        self.assertNotIn("model", payload)
        self.assertTrue(payload["local_only"])
        self.assertEqual(payload["target_language"], "none")
        self.assertNotIn("private synthetic words", str(seen))

    def test_explicit_local_model_is_sent_unchanged(self):
        alias = "synthetic-local-alias"
        body = {
            "original_text": "source",
            "transformed_text": "output",
            "options": {
                "mode": "written",
                "format": "normal",
                "target_language": "none",
                "model": alias,
                "local_only": True,
            },
            "model": alias,
            "provider": "host-ollama",
            "fallback_occurred": False,
            "generated": True,
        }
        status, seen = self.invoke(
            ["transform", "--text", "source", "--model", alias],
            json.dumps(body).encode(),
        )
        payload = json.loads(seen["request"].data)
        self.assertEqual(status, 0)
        self.assertEqual(payload["model"], alias)
        self.assertTrue(payload["local_only"])

    def test_explicit_cloud_model_requires_cli_consent_and_gateway_policy(self):
        alias = "synthetic-cloud-alias"
        body = {
            "original_text": "source",
            "transformed_text": "output",
            "options": {
                "mode": "written",
                "format": "normal",
                "target_language": "none",
                "model": alias,
                "local_only": False,
            },
            "model": alias,
            "provider": "synthetic-cloud-provider",
            "fallback_occurred": False,
            "generated": True,
        }
        status, seen = self.invoke(
            [
                "transform",
                "--text",
                "source",
                "--model",
                alias,
                "--allow-cloud",
            ],
            json.dumps(body).encode(),
        )
        payload = json.loads(seen["request"].data)
        self.assertEqual(status, 0)
        self.assertEqual(payload["model"], alias)
        self.assertFalse(payload["local_only"])

    def test_gateway_authorization_and_alias_errors_are_preserved(self):
        cases = (
            ("synthetic-cloud-alias", (), 403, "cloud_not_allowed", True),
            (
                "synthetic-cloud-alias",
                ("--allow-cloud",),
                403,
                "cloud_disabled",
                False,
            ),
            ("unavailable-alias", (), 400, "unknown_model", True),
        )
        for index, (alias, options, status_code, api_code, local_only) in enumerate(
            cases
        ):
            with self.subTest(alias=alias, options=options):
                report_path = self.root / "private" / f"{alias}-{index}-failure.json"
                captured = {}

                def reject(request, timeout):
                    captured["request"] = request
                    raise HTTPError(
                        request.full_url,
                        status_code,
                        "Gateway error",
                        {},
                        io.BytesIO(
                            json.dumps(
                                {
                                    "code": api_code,
                                    "message": "synthetic private provider detail",
                                }
                            ).encode()
                        ),
                    )

                stdout = io.StringIO()
                with (
                    patch.object(qualify, "ROOT", self.root),
                    patch.object(qualify, "load_env", return_value=self.env),
                    patch.object(qualify, "urlopen", side_effect=reject),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = qualify.main(
                        [
                            "transform",
                            "--text",
                            "source",
                            "--model",
                            alias,
                            *options,
                            "--report",
                            str(report_path),
                        ]
                    )

                payload = json.loads(captured["request"].data)
                report = json.loads(report_path.read_text())
                self.assertEqual(result, qualify.EXIT_REQUEST)
                self.assertEqual(payload["model"], alias)
                self.assertEqual(payload["local_only"], local_only)
                self.assertEqual(report["http"]["status"], status_code)
                self.assertEqual(report["error"]["api_code"], api_code)
                self.assertNotIn(
                    "synthetic private provider detail", report_path.read_text()
                )
                self.assertNotIn("synthetic private provider detail", stdout.getvalue())

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

    def test_tts_writes_relative_absolute_and_non_private_paths(self):
        (self.root / "samples" / "audio").mkdir(parents=True)
        (self.root / "outside").mkdir()
        paths = (
            Path("relative.wav"),
            self.root / "absolute.wav",
            Path("samples/audio/en-polite.wav"),
            self.root / "outside" / "speech.wav",
        )
        original_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            for output in paths:
                with self.subTest(output=str(output)):
                    status, _ = self.invoke(
                        ["tts", "--text", "synthetic", "--output", str(output)],
                        wav_bytes(),
                    )
                    self.assertEqual(status, 0)
                    resolved = output.expanduser().absolute()
                    self.assertTrue(resolved.is_file())
                    self.assertEqual(stat.S_IMODE(resolved.stat().st_mode), 0o600)
        finally:
            os.chdir(original_cwd)

    def test_tts_expands_home_directory_output(self):
        home = self.root / "home"
        (home / "recordings").mkdir(parents=True)
        with patch.dict(os.environ, {"HOME": str(home)}):
            status, _ = self.invoke(
                ["tts", "--text", "synthetic", "--output", "~/recordings/speech.wav"],
                wav_bytes(),
            )
        output = home / "recordings" / "speech.wav"
        self.assertEqual(status, 0)
        self.assertTrue(output.is_file())
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_tts_existing_output_collision_fails_before_request_with_safe_message(self):
        output = self.root / "existing.wav"
        output.write_bytes(b"keep")
        stdout = io.StringIO()
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen") as opened,
            contextlib.redirect_stdout(stdout),
        ):
            status = qualify.main(
                ["tts", "--text", "private words", "--output", str(output)]
            )
        self.assertEqual(status, qualify.EXIT_INPUT)
        self.assertIn("HTTP N/A; elapsed=N/A", stdout.getvalue())
        self.assertIn("output file already exists", stdout.getvalue())
        self.assertNotIn("private words", stdout.getvalue())
        self.assertNotIn(TOKEN, stdout.getvalue())
        opened.assert_not_called()
        self.assertEqual(output.read_bytes(), b"keep")

    def test_tts_missing_output_parent_fails_before_request(self):
        output = self.root / "missing" / "speech.wav"
        stdout = io.StringIO()
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen") as opened,
            contextlib.redirect_stdout(stdout),
        ):
            status = qualify.main(
                ["tts", "--text", "synthetic", "--output", str(output)]
            )
        self.assertEqual(status, qualify.EXIT_INPUT)
        self.assertIn("output directory does not exist:", stdout.getvalue())
        self.assertIn("HTTP N/A; elapsed=N/A", stdout.getvalue())
        opened.assert_not_called()

    def test_tts_permission_failure_has_safe_actionable_error_and_output_exit(self):
        output = self.root / "forbidden.wav"
        stdout = io.StringIO()
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", return_value=Response(wav_bytes())),
            patch.object(qualify.os, "open", side_effect=PermissionError),
            contextlib.redirect_stdout(stdout),
        ):
            status = qualify.main(
                ["tts", "--text", "private words", "--output", str(output)]
            )
        self.assertEqual(status, qualify.EXIT_OUTPUT)
        self.assertIn("HTTP 200", stdout.getvalue())
        self.assertIn("permission denied creating output file", stdout.getvalue())
        self.assertNotIn("private words", stdout.getvalue())
        self.assertNotIn(TOKEN, stdout.getvalue())

    def test_report_and_evidence_remain_restricted_to_private(self):
        for option in ("--report", "--evidence"):
            with self.subTest(option=option):
                stdout = io.StringIO()
                with (
                    patch.object(qualify, "ROOT", self.root),
                    patch.object(qualify, "load_env", return_value=self.env),
                    patch.object(qualify, "urlopen") as opened,
                    contextlib.redirect_stdout(stdout),
                ):
                    status = qualify.main(
                        [
                            "tts",
                            "--text",
                            "synthetic",
                            option,
                            str(self.root / "outside.json"),
                        ]
                    )
                self.assertEqual(status, qualify.EXIT_INPUT)
                self.assertIn("under private/", stdout.getvalue())
                self.assertIn("HTTP N/A; elapsed=N/A", stdout.getvalue())
                opened.assert_not_called()

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
        actual_write = qualify._write_output

        def fail_audio(path, data, **kwargs):
            if path == output:
                raise qualify.QualificationError("output_error", "write failed")
            return actual_write(path, data, **kwargs)

        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", return_value=Response(wav_bytes())),
            patch.object(
                qualify,
                "_write_output",
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
        actual_write = qualify._write_output

        def fail_report(path, data, **kwargs):
            if path == report:
                raise qualify.QualificationError("output_error", "write failed")
            return actual_write(path, data, **kwargs)

        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", return_value=Response(wav_bytes())),
            patch.object(qualify, "_write_output", side_effect=fail_report),
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
        self.assertEqual(report["response"]["metadata"]["prompt_sha256"], "a" * 64)
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
