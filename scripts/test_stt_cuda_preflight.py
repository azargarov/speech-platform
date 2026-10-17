from __future__ import annotations

import contextlib
import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.stt_cuda_preflight import (
    parse_free_gpu_memory_mib,
    validate_free_gpu_memory,
    verify_approved_audio,
)


class AudioPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.audio = self.root / "approved.m4a"
        self.audio.write_bytes(b"approved fixture bytes")
        self.checksum = self.root / "approved.sha256"
        self.digest = hashlib.sha256(self.audio.read_bytes()).hexdigest()
        self.checksum.write_text(f"{self.digest}  approved.m4a\n")

    def test_approved_audio_passes(self):
        self.assertEqual(verify_approved_audio(self.audio, self.checksum), self.digest)

    def test_modified_audio_fails_closed(self):
        self.audio.write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "does not match"):
            verify_approved_audio(self.audio, self.checksum)

    def test_missing_or_invalid_expected_digest_fails_closed(self):
        self.checksum.write_text("\n")
        with self.assertRaisesRegex(ValueError, "missing a valid digest"):
            verify_approved_audio(self.audio, self.checksum)
        self.checksum.unlink()
        with self.assertRaisesRegex(ValueError, "regular file"):
            verify_approved_audio(self.audio, self.checksum)

    def test_local_and_host_use_same_checksum_verifier_and_digest(self):
        local_digest = verify_approved_audio(self.audio, self.checksum)
        host_digest = verify_approved_audio(self.audio, self.checksum)
        self.assertEqual(local_digest, host_digest)

    def test_repository_approved_record_matches_private_audio(self):
        repository = Path(__file__).resolve().parents[1]
        audio = repository / "private/audio/russian.m4a"
        checksum = repository / "private/results/audio-before-offline.sha256"
        if audio.is_file() and checksum.is_file():
            self.assertEqual(
                verify_approved_audio(audio, checksum), self.digest_for(audio)
            )

    @staticmethod
    def digest_for(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_host_launcher_rejects_audio_before_any_runner_call(self):
        from scripts import launch_stt_cuda_diagnostic as launcher

        self.audio.write_bytes(b"changed after approval")
        argv = [
            "launch_stt_cuda_diagnostic.py",
            "--attempt-root",
            str(self.root / "attempts"),
            "--shared-gid",
            str(os.getgid()),
            "--attempt-id",
            "test-attempt",
            "--container-name",
            "test-attempt",
            "--image-id",
            "sha256:" + "a" * 64,
            "--audio-file",
            str(self.audio),
            "--audio-checksum-file",
            str(self.checksum),
            "--platform",
            "linux/amd64",
            "--timeout-seconds",
            "180",
            "--grace-seconds",
            "5",
            "--",
            "docker",
            "run",
            "--network",
            "none",
            "--user",
            "65532:65532",
        ]
        output = io.StringIO()
        with (
            patch("sys.argv", argv),
            patch.object(launcher, "DiagnosticLauncher") as diagnostic_launcher,
            contextlib.redirect_stderr(output),
        ):
            with self.assertRaises(SystemExit):
                launcher.main()
        diagnostic_launcher.assert_not_called()
        self.assertIn("audio failed approved checksum preflight", output.getvalue())
        self.assertFalse((self.root / "attempts").exists())

    def test_gpu_memory_gate_uses_configured_threshold_at_boundary(self):
        gate = 12 * 1024**3
        validate_free_gpu_memory(12 * 1024, gate)
        with self.assertRaisesRegex(ValueError, "below"):
            validate_free_gpu_memory(12 * 1024 - 1, gate)

    def test_gpu_memory_probe_rejects_unparseable_output(self):
        self.assertEqual(parse_free_gpu_memory_mib("12288\n"), 12288)
        for output in ("", "12288 MiB", "12,288", "unknown"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                parse_free_gpu_memory_mib(output)


if __name__ == "__main__":
    unittest.main()
