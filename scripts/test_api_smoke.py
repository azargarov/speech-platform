from __future__ import annotations

import contextlib
import io
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import api_smoke


class APISmokeTests(unittest.TestCase):
    def test_make_targets_execute_the_module_cli(self):
        root = Path(__file__).resolve().parents[1]
        for target, expected in (
            (
                "test-stt",
                f'{sys.executable} -m scripts.api_smoke stt --audio "private/audio/test.wav"',
            ),
            (
                "test-tts",
                f'{sys.executable} -m scripts.api_smoke tts --output "private/audio/test.wav"',
            ),
        ):
            with self.subTest(target=target):
                result = subprocess.run(
                    [
                        "make",
                        "--no-print-directory",
                        "-n",
                        target,
                        f"PYTHON={sys.executable}",
                        "AUDIO=private/audio/test.wav",
                        "OUTPUT=private/audio/test.wav",
                    ],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertIn(expected, result.stdout)

    def test_module_cli_entrypoint_runs_from_repository_root(self):
        root = Path(__file__).resolve().parents[1]
        for service in ("stt", "tts"):
            with self.subTest(service=service):
                result = subprocess.run(
                    [sys.executable, "-m", "scripts.api_smoke", service, "--help"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertIn("usage:", result.stdout)
                self.assertIn(service, result.stdout)

    def test_gateway_origin_requires_token_without_disclosing_it(self):
        with self.assertRaisesRegex(api_smoke.SmokeError, "TOKEN"):
            api_smoke._gateway_origin({"SPEECH_PORT": "8080"})
        token = "synthetic-token-value-that-is-not-printed"
        self.assertEqual(
            api_smoke._gateway_origin(
                {"SPEECH_PORT": "8080", "SPEECH_API_TOKEN": token}
            ),
            ("http://127.0.0.1:8080", token),
        )

    def test_stt_request_is_authenticated_and_prints_only_response(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                return json.dumps(
                    {"text": "synthetic transcript", "translated": False}
                ).encode()

        with tempfile.TemporaryDirectory() as temp:
            audio = Path(temp) / "sample.wav"
            audio.write_bytes(b"synthetic audio")
            args = SimpleNamespace(
                audio=audio, source_language="en", output_language="auto"
            )
            output = io.StringIO()
            with (
                patch.object(api_smoke, "urlopen", return_value=Response()) as open_url,
                contextlib.redirect_stdout(output),
            ):
                api_smoke.run_stt(
                    args,
                    {
                        "SPEECH_PORT": "8080",
                        "SPEECH_API_TOKEN": "synthetic-token-value-that-is-not-printed",
                    },
                )
            request = open_url.call_args.args[0]
            self.assertEqual(
                request.full_url, "http://127.0.0.1:8080/v1/stt/transcriptions"
            )
            self.assertEqual(
                request.get_header("Authorization"),
                "Bearer synthetic-token-value-that-is-not-printed",
            )
            self.assertIn(b'name="source_language"', request.data)
            self.assertIn("synthetic transcript", output.getvalue())

    def test_tts_writes_private_wav_exclusively_with_private_permissions(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                return b"RIFF" + b"\0" * 4 + b"WAVE" + b"data"

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private/audio").mkdir(parents=True)
            output_file = root / "private/audio/smoke.wav"
            args = SimpleNamespace(output=output_file, text="synthetic speech")
            output = io.StringIO()
            with (
                patch.object(api_smoke, "ROOT", root),
                patch.object(api_smoke, "urlopen", return_value=Response()) as open_url,
                contextlib.redirect_stdout(output),
            ):
                api_smoke.run_tts(
                    args,
                    {
                        "SPEECH_PORT": "8080",
                        "SPEECH_API_TOKEN": "synthetic-token-value-that-is-not-printed",
                    },
                )
            self.assertEqual(stat.S_IMODE(output_file.stat().st_mode), 0o600)
            self.assertEqual(output_file.read_bytes()[:4], b"RIFF")
            self.assertEqual(
                open_url.call_args.args[0].full_url,
                "http://127.0.0.1:8080/v1/tts/speech",
            )
            self.assertNotIn("synthetic speech", output.getvalue())

    def test_tts_rejects_paths_outside_private(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private").mkdir()
            args = SimpleNamespace(output=root / "outside.wav", text="synthetic")
            with (
                patch.object(api_smoke, "ROOT", root),
                self.assertRaisesRegex(api_smoke.SmokeError, "under private"),
            ):
                api_smoke.run_tts(
                    args,
                    {
                        "SPEECH_PORT": "8080",
                        "SPEECH_API_TOKEN": "synthetic-token-value-that-is-not-printed",
                    },
                )

    def test_tts_does_not_infer_or_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "private/audio"
            directory.mkdir(parents=True)
            output = directory / "existing.wav"
            output.write_bytes(b"keep")
            args = SimpleNamespace(output=output, text="synthetic")
            with (
                patch.object(api_smoke, "ROOT", root),
                patch.object(api_smoke, "urlopen") as open_url,
                self.assertRaisesRegex(api_smoke.SmokeError, "already exists"),
            ):
                api_smoke.run_tts(
                    args,
                    {
                        "SPEECH_PORT": "8080",
                        "SPEECH_API_TOKEN": "synthetic-token-value-that-is-not-printed",
                    },
                )
            open_url.assert_not_called()
            self.assertEqual(output.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
