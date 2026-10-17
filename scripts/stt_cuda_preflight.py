"""Small, shared artifact checks for the CUDA diagnostic host and container."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def approved_audio_sha256(checksum_file: str | Path) -> str:
    """Read the single approved digest from a sha256sum-format metadata file."""
    path = Path(checksum_file)
    if path.is_symlink() or not path.is_file():
        raise ValueError("audio checksum metadata must be a regular file")
    fields = path.read_text(encoding="ascii").strip().split()
    if not fields or not re.fullmatch(r"[0-9a-f]{64}", fields[0]):
        raise ValueError("audio checksum metadata is missing a valid digest")
    if len(fields) > 2:
        raise ValueError("audio checksum metadata must identify one artifact")
    return fields[0]


def verify_approved_audio(audio_file: str | Path, checksum_file: str | Path) -> str:
    """Fail closed unless audio matches the approved checksum metadata."""
    expected = approved_audio_sha256(checksum_file)
    audio = Path(audio_file)
    if audio.is_symlink() or not audio.is_file():
        raise ValueError("audio input must be a regular local file")
    digest = hashlib.sha256()
    with audio.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError("audio does not match approved checksum")
    return expected
