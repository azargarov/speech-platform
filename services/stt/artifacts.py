"""Offline validation for immutable, path-independent model manifests."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Protocol

from services.stt.config import ArtifactRoot, ModelConfig, _read_yaml
from services.stt.domain import (
    ArtifactIdentity,
    FailureCode,
    SpeechFailure,
    VerifiedArtifact,
)


class ArtifactStore(Protocol):
    def verify(
        self, model: ModelConfig, location: ArtifactRoot
    ) -> VerifiedArtifact: ...


def canonical_manifest_digest(manifest: dict) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_artifact_manifest(
    path: str | Path, expected_sha256: str | None = None
) -> dict:
    """Load and validate the shared model artifact manifest contract."""
    manifest_path = Path(path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("manifest must be a regular file")
    manifest = _read_yaml(manifest_path)
    _validate_manifest_shape(manifest)
    if expected_sha256 and canonical_manifest_digest(manifest) != expected_sha256:
        raise ValueError("manifest digest mismatch")
    return manifest


def verify_artifact(model: ModelConfig, location: ArtifactRoot) -> VerifiedArtifact:
    root = location.directory
    manifest_path = location.manifest
    try:
        manifest = load_artifact_manifest(manifest_path, model.manifest_sha256)
        if manifest["model"]["family"] != model.identity.family:
            raise ValueError("manifest model family mismatch")
        if manifest["model"]["revision"] != model.identity.upstream_revision:
            raise ValueError("manifest model revision mismatch")
        if manifest["artifact"]["format"] != model.artifact_format:
            raise ValueError("manifest artifact format mismatch")
        if root.is_symlink() or not root.is_dir():
            raise ValueError("artifact directory is unavailable")
        expected = {}
        for entry in manifest["files"]:
            relative = _relative_file(entry["path"])
            if relative in expected:
                raise ValueError("manifest contains duplicate paths")
            expected[relative] = entry
        actual = _regular_files(root)
        if set(actual) != set(expected):
            raise ValueError("artifact file set does not match manifest")
        for relative, entry in expected.items():
            file_path = actual[relative]
            if file_path.stat().st_size != entry["size_bytes"]:
                raise ValueError("artifact file size mismatch")
            digest = _file_digest(file_path)
            if digest != entry["sha256"]:
                raise ValueError(
                    "artifact file digest mismatch for "
                    f"{relative}: expected SHA-256 {entry['sha256']}, "
                    f"got {digest}"
                )
        return VerifiedArtifact(
            ArtifactIdentity(model.manifest_sha256, model.artifact_format),
            root.resolve(),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SpeechFailure(
            FailureCode.MODEL_LOAD_FAILED, "model artifact validation failed"
        ) from exc


def _validate_manifest_shape(manifest):
    if set(manifest) != {"manifest_version", "model", "artifact", "files"}:
        raise ValueError("invalid manifest fields")
    if (
        type(manifest["manifest_version"]) is not int
        or manifest["manifest_version"] != 1
    ):
        raise ValueError("unsupported manifest version")
    if set(manifest["model"]) != {"family", "repository", "revision"}:
        raise ValueError("invalid manifest model fields")
    if set(manifest["artifact"]) != {"format", "tool", "tool_version"}:
        raise ValueError("invalid manifest artifact fields")
    for section in (manifest["model"], manifest["artifact"]):
        if any(not isinstance(value, str) or not value for value in section.values()):
            raise ValueError("manifest metadata values must be non-empty strings")
    if not isinstance(manifest["files"], list) or not manifest["files"]:
        raise ValueError("manifest files must be a non-empty list")
    for entry in manifest["files"]:
        if set(entry) != {"path", "size_bytes", "sha256"}:
            raise ValueError("invalid manifest file entry")
        _relative_file(entry["path"])
        if type(entry["size_bytes"]) is not int or entry["size_bytes"] < 0:
            raise ValueError("manifest file size must be a non-negative integer")
        if not isinstance(entry["sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", entry["sha256"]
        ):
            raise ValueError("manifest file digest must be lowercase SHA-256")


def _relative_file(value):
    if not isinstance(value, str) or "\\" in value:
        raise ValueError("manifest paths must be normalized relative POSIX paths")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("manifest paths must remain inside artifact root")
    if path.as_posix() != value:
        raise ValueError("manifest path is not normalized")
    return path.as_posix()


def _regular_files(root: Path):
    found = {}
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories:
            if (current_path / name).is_symlink():
                raise ValueError("artifact directories cannot be symlinks")
        for name in filenames:
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("artifact entries must be regular files")
            found[path.relative_to(root).as_posix()] = path
    return found


def _file_digest(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
