"""Tests for the pinned STT dependency compatibility policy."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts import check_stt_locks


class SttLockPolicyTests(unittest.TestCase):
    def _copy_repository_inputs(self, destination: Path) -> None:
        (destination / "services").mkdir()
        for name in (
            "requirements-stt-cpu.in",
            "requirements-stt-cpu.lock",
            "requirements-stt-cuda.in",
            "requirements-stt-cuda.lock",
        ):
            shutil.copy2(
                check_stt_locks.ROOT / "services" / name,
                destination / "services" / name,
            )

    def test_current_locked_runtime_combination_is_supported(self) -> None:
        check_stt_locks.validate()

    def test_changed_ctranslate2_and_cudnn_versions_are_rejected(self) -> None:
        for package, expected, changed in (
            ("ctranslate2", "4.8.3", "4.8.2"),
            ("nvidia-cudnn-cu12", "9.27.0.42", "8.9.7.29"),
        ):
            with self.subTest(package=package), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self._copy_repository_inputs(root)
                source = root / "services" / "requirements-stt-cuda.in"
                lock = root / "services" / "requirements-stt-cuda.lock"
                source.write_text(
                    source.read_text().replace(
                        f"{package}=={expected}", f"{package}=={changed}"
                    )
                )
                lock.write_text(
                    lock.read_text().replace(
                        f"{package}=={expected}", f"{package}=={changed}"
                    )
                )

                with self.assertRaisesRegex(
                    ValueError, "unsupported CUDA runtime combination"
                ):
                    check_stt_locks.validate(root)

    def test_cuda_runtime_package_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._copy_repository_inputs(root)
            cuda_lock = root / "services" / "requirements-stt-cuda.lock"
            cuda_lock.write_text(
                cuda_lock.read_text()
                + "\nnvidia-cuda-runtime-cu12==12.9.79 \\\n    --hash=sha256:"
                + "0" * 64
                + "\n"
            )

            with self.assertRaisesRegex(
                ValueError, "must not add nvidia-cuda-runtime-cu12"
            ):
                check_stt_locks.validate(root)


if __name__ == "__main__":
    unittest.main()
