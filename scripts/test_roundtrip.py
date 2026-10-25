from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import qualify, roundtrip

TOKEN = "offline-test-token-value-that-is-longer-than-32-characters"


class Response:
    def __init__(self, body, *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        return self.body


def wav_bytes(rate=16000, frames=800):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\0\0" * frames)
    return output.getvalue()


class RoundtripTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.text = self.root / "samples" / "text"
        self.audio = self.root / "samples" / "audio"
        self.private = self.root / "private"
        self.text.mkdir(parents=True)
        self.audio.mkdir()
        self.private.mkdir()
        self.env = {
            "SPEECH_API_URL": "http://127.0.0.1:8080",
            "SPEECH_API_TOKEN": TOKEN,
        }
        self.reference = "Hello, world!"
        (self.text / "en-polite.txt").write_text(self.reference, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def args(self, *argv):
        return roundtrip._parser().parse_args(argv)

    def patched(self, **extra):
        values = {
            "ROOT": self.root,
            "TEXT_DIR": self.text,
            "AUDIO_DIR": self.audio,
            "q_root": self.root,
        }
        values.update(extra)
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(roundtrip, "ROOT", values["ROOT"]))
        stack.enter_context(patch.object(roundtrip, "TEXT_DIR", values["TEXT_DIR"]))
        stack.enter_context(patch.object(roundtrip, "AUDIO_DIR", values["AUDIO_DIR"]))
        stack.enter_context(patch.object(qualify, "ROOT", values["q_root"]))
        stack.enter_context(patch.object(qualify, "load_env", return_value=self.env))
        if "urlopen" in values:
            stack.enter_context(
                patch.object(qualify, "urlopen", side_effect=values["urlopen"])
            )
        return stack

    def fake_gateway(self, transcript="hello world", *, provider="local"):
        seen = []

        def open_url(request, timeout):
            seen.append(request)
            if request.full_url.endswith("/v1/tts/speech"):
                return Response(wav_bytes(), headers={"Content-Type": "audio/wav"})
            return Response(
                json.dumps({"text": transcript, "language": "en"}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Speech-Provider": provider,
                },
            )

        return seen, open_url

    def test_fixture_discovery_is_sorted_and_extracts_language(self):
        (self.text / "sv-rude.txt").write_text("Hej.", encoding="utf-8")
        (self.text / "ru-polite.txt").write_text("Здравствуйте.", encoding="utf-8")
        fixtures = roundtrip.discover_fixtures(self.text)
        self.assertEqual(
            [(item["case_id"], item["language"]) for item in fixtures],
            [("en-polite", "en"), ("ru-polite", "ru"), ("sv-rude", "sv")],
        )
        self.assertEqual(len(fixtures[0]["reference_sha256"]), 64)

    def test_fixture_discovery_rejects_unsupported_empty_and_bad_names(self):
        for name, content in (
            ("de-case.txt", "Hallo"),
            ("en-empty.txt", " \n\t"),
            ("en-bad_name.txt", "text"),
            ("en-Polite.txt", "text"),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                (folder / name).write_text(content, encoding="utf-8")
                with self.assertRaises(roundtrip.RoundtripError):
                    roundtrip.discover_fixtures(folder)

    def test_normalization_and_levenshtein_metrics(self):
        self.assertEqual(
            roundtrip.normalize("  STRASSE, Cafe\u0301!\n"), "strasse café"
        )
        self.assertEqual(roundtrip.edit_distance("kitten", "sitting"), 3)
        result = roundtrip.metrics("One, two!", "one two")
        self.assertEqual(result["wer"], 0)
        self.assertEqual(result["cer"], 0)
        self.assertEqual(
            result["normalization"]["version"],
            "speechplatform-roundtrip-text-v1",
        )
        self.assertAlmostEqual(
            roundtrip.metrics("one two three", "one four three")["wer"], 1 / 3
        )
        self.assertEqual(roundtrip.metrics("a", "a b c")["wer"], 2.0)
        with self.assertRaises(roundtrip.RoundtripError):
            roundtrip.metrics("!!!", "")

    def test_mocked_roundtrip_auth_local_only_report_and_metrics(self):
        original = (self.text / "en-polite.txt").read_bytes()
        seen, open_url = self.fake_gateway()
        report_path = self.private / "run.json"
        with (
            self.patched(urlopen=open_url),
            patch.object(roundtrip, "_git_state", return_value=("a" * 40, True)),
        ):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = roundtrip.main(
                    ["--case", "en-polite", "--report", str(report_path)]
                )
        self.assertEqual(status, 0)
        self.assertEqual(len(seen), 2)
        tts, stt = seen
        self.assertEqual(tts.full_url, "http://127.0.0.1:8080/v1/tts/speech")
        self.assertEqual(tts.get_header("Authorization"), f"Bearer {TOKEN}")
        tts_payload = json.loads(tts.data)
        self.assertEqual(tts_payload["language"], "en")
        self.assertEqual(tts_payload["mode"], "quality")
        self.assertEqual(tts_payload["audio_processing"], "none")
        self.assertEqual(stt.full_url, "http://127.0.0.1:8080/v1/stt/transcriptions")
        self.assertEqual(stt.get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertEqual(stt.get_header("X-stt-provider"), "local")
        self.assertEqual(stt.get_header("X-allow-cloud-audio"), "false")
        self.assertIn(b'name="source_language"\r\n\r\nen', stt.data)
        self.assertIn(b'name="output_language"\r\n\r\nen', stt.data)
        audio = self.audio / "en-polite.wav"
        self.assertTrue(audio.is_file())
        self.assertEqual(stat.S_IMODE(audio.stat().st_mode), 0o600)
        self.assertEqual((self.text / "en-polite.txt").read_bytes(), original)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        case = report["cases"][0]
        self.assertEqual(
            set(report),
            {
                "schema_version",
                "operation",
                "started_at",
                "git_revision",
                "git_worktree_dirty",
                "public_api_metadata",
                "request",
                "cases",
                "technical_status",
                "quality_status",
                "human_review_status",
                "error",
                "finished_at",
                "output_dir",
            },
        )
        self.assertEqual(report["technical_status"], "PASS")
        self.assertEqual(report["quality_status"], "MEASURED")
        self.assertEqual(report["human_review_status"], "NOT_REVIEWED")
        self.assertRegex(report["git_revision"], r"^[0-9a-f]{40,64}$")
        self.assertTrue(report["git_worktree_dirty"])
        self.assertEqual(
            report["public_api_metadata"]["stt"]["requested_provider"], "local"
        )
        self.assertEqual(case["stt"]["provider"], "local")
        self.assertEqual(case["metrics"]["wer"], 0)
        self.assertEqual(case["metrics"]["cer"], 0)
        self.assertEqual(case["transcription"], "hello world")
        self.assertEqual(stat.S_IMODE(report_path.stat().st_mode), 0o600)
        self.assertNotIn("hello world", stdout.getvalue())
        self.assertNotIn(TOKEN, stdout.getvalue() + report_path.read_text())

    def test_progress_stages_precede_requests_and_summaries_exclude_sensitive_text(
        self,
    ):
        progress = io.StringIO()
        stdout = io.StringIO()
        seen = []

        def open_url(request, timeout):
            del timeout
            seen.append(request)
            current = progress.getvalue()
            if request.full_url.endswith("/v1/tts/speech"):
                self.assertIn("[1/1] en-polite: TTS starting", current)
                return Response(wav_bytes(), headers={"Content-Type": "audio/wav"})
            self.assertIn("[1/1] en-polite: STT starting", current)
            return Response(
                json.dumps({"text": "secret transcript", "language": "en"}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Speech-Provider": "local",
                },
            )

        with self.patched(urlopen=open_url):
            with (
                contextlib.redirect_stderr(progress),
                contextlib.redirect_stdout(stdout),
            ):
                status = roundtrip.main(["--case", "en-polite"])
        self.assertEqual(status, 0)
        self.assertEqual(len(seen), 2)
        self.assertRegex(progress.getvalue(), r"TTS complete \(\d+\.\d{3}s\)")
        self.assertRegex(
            progress.getvalue(), r"STT complete \(\d+\.\d{3}s\); WER=.+ CER=.+"
        )
        self.assertNotIn(TOKEN, progress.getvalue())
        self.assertNotIn("Hello, world!", progress.getvalue())
        self.assertNotIn("secret transcript", progress.getvalue())
        self.assertIn("technical=PASS", stdout.getvalue())
        self.assertNotIn("secret transcript", stdout.getvalue())

    def test_multi_case_progress_numbering_and_final_elapsed_summary(self):
        (self.text / "en-rude.txt").write_text("A second private reference.")
        seen, open_url = self.fake_gateway()
        progress = io.StringIO()
        stdout = io.StringIO()
        with self.patched(urlopen=open_url):
            with (
                contextlib.redirect_stderr(progress),
                contextlib.redirect_stdout(stdout),
            ):
                status = roundtrip.main([])
        self.assertEqual(status, 0)
        self.assertEqual(len(seen), 4)
        self.assertIn(
            "roundtrip: 2 cases; TTS=quality; STT provider=local", progress.getvalue()
        )
        self.assertIn("[1/2] en-polite", progress.getvalue())
        self.assertIn("[2/2] en-rude", progress.getvalue())
        self.assertRegex(
            stdout.getvalue(), r"successes=2; failures=0; .*total_elapsed=\d+\.\d{3}s"
        )

    def test_tts_failure_and_interruption_are_printed_with_elapsed(self):
        progress = io.StringIO()

        def fail_tts(_request, timeout):
            del timeout
            raise HTTPError(
                "http://gateway/v1/tts/speech", 503, "unavailable", {}, None
            )

        with self.patched(urlopen=fail_tts):
            with contextlib.redirect_stderr(progress):
                failed = roundtrip.run(self.args())
        failure_output = progress.getvalue()
        self.assertLess(
            failure_output.index("TTS starting"), failure_output.index("TTS failed")
        )
        self.assertRegex(failure_output, r"TTS failed \(http_error; \d+\.\d{3}s\)")
        self.assertEqual(failed["error"]["classification"], "http_error")

        progress = io.StringIO()

        def interrupt(_request, timeout):
            del timeout
            raise KeyboardInterrupt

        with self.patched(urlopen=interrupt):
            with contextlib.redirect_stderr(progress):
                interrupted = roundtrip.run(self.args())
        self.assertIn("TTS interrupted (", progress.getvalue())
        self.assertEqual(interrupted["error"]["classification"], "interrupted")

    def test_nonlocal_serving_provider_fails_and_stops_further_cases(self):
        (self.text / "en-rude.txt").write_text("Another test.", encoding="utf-8")
        seen, open_url = self.fake_gateway(provider="groq")
        with self.patched(urlopen=open_url):
            report = roundtrip.run(self.args())
        self.assertEqual(len(seen), 2)
        self.assertEqual(report["technical_status"], "FAIL")
        self.assertEqual(
            report["cases"][0]["error_classification"], "provider_mismatch"
        )
        self.assertEqual(len(report["cases"]), 1)

    def test_existing_wav_fails_before_request_and_regenerate_replaces_only_expected(
        self,
    ):
        audio = self.audio / "en-polite.wav"
        audio.write_bytes(b"stale")
        seen, open_url = self.fake_gateway()
        with self.patched(urlopen=open_url):
            failed = roundtrip.run(self.args())
        self.assertEqual(seen, [])
        self.assertEqual(failed["error"]["classification"], "local_validation")
        unrelated = self.audio / "keep.txt"
        unrelated.write_text("keep")
        with self.patched(urlopen=open_url):
            result = roundtrip.run(self.args("--regenerate"))
        self.assertEqual(result["technical_status"], "PASS")
        self.assertTrue(wave.open(str(audio)).getnframes())
        self.assertEqual(unrelated.read_text(), "keep")
        self.assertEqual(list(self.audio.glob("*.tmp")), [])

    def test_invalid_fixture_or_filter_fails_before_http(self):
        (self.text / "xx-invalid.txt").write_text("invalid", encoding="utf-8")
        seen, open_url = self.fake_gateway()
        with self.patched(urlopen=open_url):
            report = roundtrip.run(self.args("--case", "en-polite"))
        self.assertEqual(seen, [])
        self.assertEqual(report["technical_status"], "FAIL")
        self.assertEqual(report["error"]["classification"], "local_validation")

    def test_tts_failure_leaves_no_completed_wav_and_preserves_http_error(self):
        def fail_tts(_request, timeout):
            del timeout
            raise HTTPError(
                "http://gateway/v1/tts/speech",
                503,
                "unavailable",
                {},
                io.BytesIO(b'{"code":"provider_not_ready"}'),
            )

        with self.patched(urlopen=fail_tts):
            report = roundtrip.run(self.args())
        case = report["cases"][0]
        self.assertEqual(case["tts"]["http_status"], 503)
        self.assertEqual(case["tts"]["error"]["api_code"], "provider_not_ready")
        self.assertFalse((self.audio / "en-polite.wav").exists())

    def test_timeout_stops_sequence_without_retry(self):
        calls = []

        def timeout(request, timeout):
            del timeout
            calls.append(request)
            raise TimeoutError

        with self.patched(urlopen=timeout):
            report = roundtrip.run(self.args())
        self.assertEqual(len(calls), 1)
        self.assertEqual(report["error"]["classification"], "timeout")
        self.assertEqual(
            report["cases"][0]["tts"]["error"]["classification"], "timeout"
        )

    def test_audio_output_failure_does_not_call_stt(self):
        seen, open_url = self.fake_gateway()
        with (
            self.patched(urlopen=open_url),
            patch.object(roundtrip.os, "open", side_effect=PermissionError),
        ):
            report = roundtrip.run(self.args())
        self.assertEqual(len(seen), 1)
        case = report["cases"][0]
        self.assertEqual(case["tts"]["error"]["classification"], "output_error")
        self.assertEqual(case["stt"]["status"], "not_run")
        self.assertFalse((self.audio / "en-polite.wav").exists())

    def test_invalid_tts_wav_is_not_published(self):
        def invalid_wav(_request, timeout):
            del timeout
            return Response(b"not a wav", headers={"Content-Type": "audio/wav"})

        with self.patched(urlopen=invalid_wav):
            report = roundtrip.run(self.args())
        case = report["cases"][0]
        self.assertEqual(case["tts"]["http_status"], 200)
        self.assertEqual(case["tts"]["error"]["classification"], "invalid_response")
        self.assertFalse((self.audio / "en-polite.wav").exists())

    def test_regeneration_invalid_tts_response_preserves_existing_wav(self):
        target = self.audio / "en-polite.wav"
        target.write_bytes(b"previous valid artifact")

        def invalid_wav(_request, timeout):
            del timeout
            return Response(b"not a wav", headers={"Content-Type": "audio/wav"})

        with self.patched(urlopen=invalid_wav):
            report = roundtrip.run(self.args("--regenerate"))
        self.assertEqual(report["technical_status"], "FAIL")
        self.assertEqual(target.read_bytes(), b"previous valid artifact")
        self.assertEqual(list(self.audio.glob("*.tmp")), [])

    def test_regeneration_temporary_write_failure_preserves_existing_wav(self):
        target = self.audio / "en-polite.wav"
        target.write_bytes(b"previous valid artifact")
        seen, open_url = self.fake_gateway()
        with (
            self.patched(urlopen=open_url),
            patch.object(roundtrip.os, "fdopen", side_effect=OSError),
        ):
            report = roundtrip.run(self.args("--regenerate"))
        self.assertEqual(len(seen), 1)
        self.assertEqual(report["technical_status"], "FAIL")
        self.assertEqual(
            report["cases"][0]["tts"]["error"]["classification"], "output_error"
        )
        self.assertEqual(target.read_bytes(), b"previous valid artifact")
        self.assertEqual(list(self.audio.glob("*.tmp")), [])

    def test_interruption_is_recorded_on_case_and_overall_report(self):
        def interrupt(_request, timeout):
            del timeout
            raise KeyboardInterrupt

        with self.patched(urlopen=interrupt):
            report = roundtrip.run(self.args())
        self.assertEqual(report["technical_status"], "FAIL")
        self.assertEqual(report["error"]["classification"], "interrupted")
        self.assertEqual(
            report["error"]["message"], "round-trip interrupted during case en-polite"
        )
        case = report["cases"][0]
        self.assertEqual(case["technical_status"], "FAIL")
        self.assertEqual(case["error_classification"], "interrupted")
        self.assertEqual(case["tts"]["error"]["classification"], "interrupted")

    def test_stt_request_limit_is_checked_before_transcription(self):
        seen, open_url = self.fake_gateway()
        with (
            self.patched(urlopen=open_url),
            patch.object(roundtrip, "MAX_STT_BYTES", 1),
        ):
            report = roundtrip.run(self.args())
        case = report["cases"][0]
        self.assertEqual(len(seen), 1)
        self.assertEqual(case["tts"]["status"], "pass")
        self.assertEqual(case["stt"]["error"]["classification"], "local_validation")
        self.assertTrue((self.audio / "en-polite.wav").is_file())

    def test_report_outside_private_is_rejected_before_requests(self):
        seen, open_url = self.fake_gateway()
        with (
            self.patched(urlopen=open_url),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = roundtrip.main(["--report", str(self.root / "outside.json")])
        self.assertEqual(status, roundtrip.EXIT_INPUT)
        self.assertEqual(seen, [])

    def test_report_write_failure_returns_output_exit_code(self):
        seen, open_url = self.fake_gateway()
        with (
            self.patched(urlopen=open_url),
            patch.object(
                qualify,
                "_write_output",
                side_effect=qualify.QualificationError("output_error", "write failed"),
            ),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            status = roundtrip.main(["--report", str(self.private / "report.json")])
        self.assertEqual(status, roundtrip.EXIT_OUTPUT)
        self.assertEqual(len(seen), 2)

    def test_generated_audio_is_ignored_by_git(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["git", "check-ignore", "-q", "samples/audio/en-polite.wav"],
            cwd=root,
            check=False,
        )
        self.assertEqual(result.returncode, 0)

    def test_stt_malformed_json_is_failure_with_http_status_and_no_transcript(self):
        calls = 0

        def malformed(_request, timeout):
            del timeout
            nonlocal calls
            calls += 1
            if calls == 1:
                return Response(wav_bytes(), headers={"Content-Type": "audio/wav"})
            return Response(
                b"{",
                headers={
                    "Content-Type": "application/json",
                    "X-Speech-Provider": "local",
                },
            )

        with self.patched(urlopen=malformed):
            report = roundtrip.run(self.args())
        case = report["cases"][0]
        self.assertEqual(case["stt"]["http_status"], 200)
        self.assertEqual(case["stt"]["error"]["classification"], "invalid_response")
        self.assertIsNone(case["transcription"])

    def test_interrupted_audio_publication_cleans_temporary_file(self):
        target = self.audio / "en-polite.wav"
        with patch.object(roundtrip.os, "fdopen", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                roundtrip._publish_audio(target, wav_bytes(), regenerate=False)
        self.assertEqual(list(self.audio.iterdir()), [])

    def test_make_target_is_explicitly_live_and_not_a_verify_prerequisite(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["make", "-n", "test-roundtrip", f"PYTHON={os.sys.executable}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("-m scripts.roundtrip", result.stdout)
        verify = subprocess.run(
            ["make", "-n", "verify"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertNotIn("scripts.roundtrip", verify.stdout)


if __name__ == "__main__":
    unittest.main()
