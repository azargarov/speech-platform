"""Structural guard for the hash-pinned TTS dependency lock."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "services/requirements-tts.lock"
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s]+)\s+\\$")
HASH = re.compile(r"^\s+--hash=sha256:[0-9a-f]{64}\s*(?:\\)?$")


def validate(text: str) -> list[str]:
    errors = []
    seen = set()
    pending_hashes = 0
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw or raw.startswith("#"):
            continue
        if raw[0].isspace():
            if not HASH.fullmatch(raw):
                errors.append(f"line {number}: invalid or unpinned hash")
            elif pending_hashes:
                pending_hashes -= 1
            continue
        match = PIN.fullmatch(raw)
        if not match:
            errors.append(f"line {number}: requirement must be exactly pinned")
            continue
        package = match.group(1).lower().replace("_", "-").replace(".", "-")
        if package in seen:
            errors.append(f"line {number}: duplicate package")
        seen.add(package)
        if pending_hashes:
            errors.append(f"line {number}: package has no hash")
        pending_hashes = 1
    if pending_hashes:
        errors.append("last package has no hash")
    if not seen:
        errors.append("lock is empty")
    return errors


def main() -> int:
    errors = validate(LOCK.read_text())
    if errors:
        print("TTS dependency lock invalid: " + "; ".join(errors), file=sys.stderr)
        return 2
    print(
        f"TTS dependency lock valid: {len([line for line in LOCK.read_text().splitlines() if PIN.fullmatch(line)])} exact hashed package pins"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
