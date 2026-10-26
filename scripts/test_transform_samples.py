from __future__ import annotations

import contextlib
import io
import json
import stat
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from scripts import qualify, transform_samples as batch


def make_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 160)


class TransformSamplesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.audio_dir = self.root / "samples" / "audio"
        self.audio_dir.mkdir(parents=True)
        for case in ("en-rude", "ru-polite", "sv-informal"):
            make_wav(self.audio_dir / f"{case}.wav")
        self.env = {
            "SPEECH_API_URL": "http://127.0.0.1:8080",
            "SPEECH_API_TOKEN": "synthetic-token-never-print-this-123456",
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_discovery_is_sorted_and_maps_languages(self):
        fixtures = batch.discover_audio(self.audio_dir)
        self.assertEqual(
            [(item["case_id"], item["language"]) for item in fixtures],
            [("en-rude", "en"), ("ru-polite", "ru"), ("sv-informal", "sv")],
        )

    def test_output_names_are_ten_files_per_case(self):
        names = batch.output_names("en")
        self.assertEqual(len(names), 10)
        self.assertEqual(names[0]["name"], "raw.txt")
        self.assertEqual(
            [item["name"] for item in names[1:4]],
            ["written.txt", "written-ru.txt", "written-sv.txt"],
        )
        self.assertEqual(names[-1]["name"], "diplomatic-sv.txt")

    def test_batch_transcribes_once_and_reuses_raw_text_for_nine_local_requests(self):
        calls = []
        transformations = []
        source = "Source includes 15,000 SEK and uncertainty."

        def request(url, token, body, content_type, timeout, max_bytes, headers=None):
            calls.append((url, token, body, content_type, headers))
            if url.endswith("/v1/stt/transcriptions"):
                self.assertEqual(headers["X-STT-Provider"], "local")
                self.assertEqual(headers["X-Allow-Cloud-Audio"], "false")
                return (
                    200,
                    {"X-Speech-Provider": "local"},
                    json.dumps({"text": source, "language": "en"}).encode(),
                )
            payload = json.loads(body)
            transformations.append((payload["mode"], payload["target_language"]))
            self.assertEqual(
                set(payload),
                {"text", "mode", "format", "target_language", "local_only"},
            )
            self.assertEqual(payload["text"], source)
            self.assertTrue(payload["local_only"])
            self.assertEqual(payload["format"], "normal")
            self.assertNotIn("model", payload)
            return (
                200,
                {"X-Speech-Prompt-SHA256": "a" * 64},
                json.dumps(
                    {
                        "original_text": source,
                        "transformed_text": f"{payload['mode']} {payload['target_language']}",
                        "options": {
                            "mode": payload["mode"],
                            "format": "normal",
                            "target_language": payload["target_language"],
                            "model": None,
                            "local_only": True,
                        },
                        "provider": "host-ollama",
                        "model": "local-qwen",
                        "fallback_occurred": False,
                        "generated": True,
                    }
                ).encode(),
            )

        args = batch._parser().parse_args(["--case", "en-rude"])
        stderr = io.StringIO()
        with (
            patch.object(batch, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "_request", side_effect=request),
            contextlib.redirect_stderr(stderr),
        ):
            report = batch.run(args)

        self.assertEqual(report["outcome"], "pass")
        self.assertEqual(len(calls), 10)
        self.assertTrue(calls[0][0].endswith("/v1/stt/transcriptions"))
        self.assertTrue(
            all(call[0].endswith("/v1/text/transformations") for call in calls[1:])
        )
        self.assertEqual(
            transformations,
            [(mode, target) for mode in batch.MODES for target in ("none", "ru", "sv")],
        )
        self.assertEqual(report["operations_attempted"], 10)
        self.assertEqual(report["operations_succeeded"], 10)
        self.assertFalse(report["routing"]["cloud_audio_consent"])
        self.assertTrue(report["routing"]["text_local_only"])
        self.assertFalse(report["routing"]["text_cloud_authorized"])
        case_dir = self.root / "samples" / "transformed" / "en-rude"
        self.assertEqual(len(list(case_dir.glob("*.txt"))), 10)
        self.assertEqual((case_dir / "raw.txt").read_text(), source)
        self.assertEqual(report["cases"][0]["operations"][1]["model"], "local-qwen")
        self.assertEqual(report["cases"][0]["operations"][1]["prompt_sha256"], "a" * 64)
        diagnostic = report["cases"][0]["operations"][1]["diagnostics"]
        self.assertTrue(diagnostic["client_request_id"])
        self.assertEqual(diagnostic["gateway_logs"], "not_available_via_public_api")
        self.assertIn("local_only=true", stderr.getvalue())
        self.assertNotIn(source, stderr.getvalue())
        self.assertNotIn(self.env["SPEECH_API_TOKEN"], stderr.getvalue())

    def test_existing_outputs_rejected_before_any_request(self):
        out = self.root / "samples" / "transformed" / "en-rude"
        out.mkdir(parents=True)
        (out / "raw.txt").write_text("keep")
        args = batch._parser().parse_args(["--case", "en-rude"])
        with (
            patch.object(batch, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "_request") as request,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            report = batch.run(args)
        request.assert_not_called()
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual((out / "raw.txt").read_text(), "keep")

    def test_regeneration_write_uses_atomic_replacement_and_private_mode(self):
        target = self.root / "result.txt"
        batch._write_text(target, "first", regenerate=True)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        target.write_text("old")
        with patch.object(batch, "ROOT", self.root):
            batch._write_text(target, "new", regenerate=True)
        self.assertEqual(target.read_text(), "new")
        self.assertEqual(list(self.root.glob(".result.txt.*.tmp")), [])

    def test_failed_atomic_regeneration_keeps_existing_output(self):
        target = self.root / "result.txt"
        target.write_text("previous result")
        with (
            patch.object(batch.os, "replace", side_effect=OSError),
            self.assertRaises(batch.BatchError),
        ):
            batch._write_text(target, "new result", regenerate=True)
        self.assertEqual(target.read_text(), "previous result")
        self.assertEqual(list(self.root.glob(".result.txt.*.tmp")), [])

    def test_invalid_fixture_language_is_rejected_before_requests(self):
        make_wav(self.audio_dir / "fr-sample.wav")
        with self.assertRaises(batch.BatchError):
            batch.discover_audio(self.audio_dir)

    def test_transformation_failure_is_reported_and_not_written(self):
        calls = 0

        def request(url, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            if url.endswith("/v1/stt/transcriptions"):
                return (
                    200,
                    {"X-Speech-Provider": "local"},
                    json.dumps(
                        {"text": "synthetic transcript", "language": "en"}
                    ).encode(),
                )
            return 200, {}, b"not-json"

        args = batch._parser().parse_args(["--case", "en-rude"])
        with (
            patch.object(batch, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "_request", side_effect=request),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            report = batch.run(args)
        self.assertEqual(calls, 10)
        self.assertEqual(report["operations_succeeded"], 1)
        self.assertEqual(report["operations_failed"], 9)
        failed = report["cases"][0]["operations"][1]
        self.assertEqual(failed["error_classification"], "invalid_response")
        self.assertEqual(failed["http_status"], 200)
        self.assertFalse(
            (self.root / "samples/transformed/en-rude/written.txt").exists()
        )
        self.assertEqual(failed["diagnostics"]["failure_stage"], "response_validation")

    def test_failed_stt_skips_transformations_and_reports_missing_outputs(self):
        def request(*_args, **_kwargs):
            raise qualify.QualificationError(
                "connection", "Gateway request could not connect"
            )

        args = batch._parser().parse_args(["--case", "en-rude"])
        with (
            patch.object(batch, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "_request", side_effect=request),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            report = batch.run(args)
        self.assertEqual(report["operations_attempted"], 1)
        self.assertEqual(report["operations_failed"], 1)
        self.assertEqual(len(report["missing_outputs"]), 10)
        self.assertEqual(report["error"]["classification"], "connection")

    def test_malformed_stt_response_retains_http_status(self):
        args = batch._parser().parse_args(["--case", "en-rude"])
        with (
            patch.object(batch, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(
                qualify,
                "_request",
                return_value=(200, {"X-Speech-Provider": "local"}, b"not-json"),
            ),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            report = batch.run(args)
        operation = report["cases"][0]["operations"][0]
        self.assertEqual(operation["status"], "fail")
        self.assertEqual(operation["http_status"], 200)
        self.assertEqual(operation["error_classification"], "invalid_response")


if __name__ == "__main__":
    unittest.main()
