"""Host-local, append-only deployment state records (no runtime control)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from scripts.durable_files import mkdir_private, publish_immutable_file

from scripts.service_deployment_profile import PROJECT_PATTERN

DEFAULT_STATE_ROOT = Path("/srv/speech-platform/deployment-state")
SCHEMA_VERSION = 1
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_FILESYSTEMS = frozenset({"ext4", "xfs", "btrfs"})
IMAGE_REFERENCE_PATTERN = re.compile(
    r"^[A-Za-z0-9.-]+(?::[0-9]+)?/[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$"
)
OUTCOMES = frozenset(
    {
        "REJECTED",
        "FAILED",
        "PARTIAL",
        "UNKNOWN",
        "SUCCEEDED",
        "ROLLBACK_FAILED",
        "ROLLED_BACK",
    }
)
ELIGIBILITY = frozenset({"ROLLBACK_READY", "NOT_ELIGIBLE", "UNKNOWN"})
OPERATION_TYPES = frozenset({"UPDATE", "ROLLBACK", "ADOPT_BASELINE", "RECONCILIATION"})
OPERATION_STATES = frozenset(
    {
        "PLANNED",
        "READY",
        "APPLYING",
        "VERIFYING",
        "RESTORING",
        "REJECTED",
        "FAILED",
        "PARTIAL",
        "UNKNOWN",
        "SUCCEEDED",
        "ROLLBACK_FAILED",
        "ROLLED_BACK",
    }
)
TERMINAL_STATES = OUTCOMES
TRANSITIONS = {
    "UPDATE": {
        "PLANNED": {"READY", "REJECTED"},
        "READY": {"APPLYING", "REJECTED"},
        "APPLYING": {"VERIFYING", "FAILED", "PARTIAL", "UNKNOWN"},
        "VERIFYING": {"SUCCEEDED", "FAILED", "PARTIAL", "UNKNOWN"},
    },
    "ROLLBACK": {
        "PLANNED": {"READY", "REJECTED"},
        "READY": {"RESTORING", "REJECTED"},
        "RESTORING": {"VERIFYING", "ROLLBACK_FAILED", "PARTIAL", "UNKNOWN"},
        "VERIFYING": {"ROLLED_BACK", "ROLLBACK_FAILED", "PARTIAL", "UNKNOWN"},
    },
    "ADOPT_BASELINE": {
        "PLANNED": {"READY", "REJECTED"},
        "READY": {"APPLYING", "REJECTED"},
        "APPLYING": {"VERIFYING", "FAILED", "PARTIAL", "UNKNOWN"},
        "VERIFYING": {"SUCCEEDED", "FAILED", "PARTIAL", "UNKNOWN"},
    },
    "RECONCILIATION": {
        "PLANNED": {"READY", "REJECTED"},
        "READY": {"APPLYING", "REJECTED"},
        "APPLYING": {"VERIFYING", "FAILED", "PARTIAL", "UNKNOWN"},
        "VERIFYING": {"SUCCEEDED", "FAILED", "PARTIAL", "UNKNOWN"},
    },
}
OPERATION_FIELDS = frozenset(
    {
        "schema_version",
        "operation_id",
        "operation_type",
        "created_at",
        "state",
        "outcome",
        "metadata",
        "rollback_eligibility",
        "revision",
        "previous_revision_sha256",
        "sha256",
    }
)
METADATA_FIELDS = frozenset(
    {
        "actor",
        "approval_reference",
        "source_operation_id",
        "source_generation_id",
        "target_generation_id",
    }
)
GENERATION_FIELDS = frozenset(
    {
        "schema_version",
        "generation_id",
        "created_at",
        "project_name",
        "parent_generation_id",
        "operation_id",
        "services",
        "sha256",
    }
)
POINTER_FIELDS = frozenset({"schema_version", "generation_id", "sha256"})
SERVICE_IDENTITY_FIELDS = frozenset(
    {
        "release_id",
        "release_descriptor_sha256",
        "image_reference",
        "image_manifest_sha256",
        "platform",
        "runtime_variant",
        "configuration_sha256",
        "model_identities",
        "compatible",
        "runtime_identity_sha256",
        "health_status",
        "health_evidence_sha256",
    }
)
MODEL_IDENTITY_FIELDS = frozenset({"model_id", "revision", "manifest_sha256"})


class StateError(ValueError):
    """State is invalid, inaccessible, corrupt, or conflicts with an existing record."""


def canonical_json(value: dict) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise StateError("record cannot be represented as canonical JSON") from error


def record_digest(record: dict) -> str:
    body = {key: value for key, value in record.items() if key != "sha256"}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def _text(value: object, label: str, pattern: re.Pattern = ID_PATTERN) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise StateError(f"{label} is invalid")
    return value


def _strict(value: object, fields: frozenset[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise StateError(f"{label} fields are missing or unknown")
    return value


def _utc_timestamp(value: object, label: str) -> None:
    if not isinstance(value, str):
        raise StateError(f"{label} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise StateError(f"{label} must be a UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise StateError(f"{label} must be a UTC timestamp")


def validate_generation(value: dict) -> dict:
    _strict(value, GENERATION_FIELDS, "generation")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise StateError("unknown generation schema version")
    _text(value["generation_id"], "generation_id")
    _text(value["operation_id"], "operation_id")
    _text(value["project_name"], "project_name", PROJECT_PATTERN)
    if value["parent_generation_id"] is not None:
        _text(value["parent_generation_id"], "parent_generation_id")
    _utc_timestamp(value["created_at"], "created_at")
    services = value["services"]
    if not isinstance(services, dict) or not services:
        raise StateError("generation services must be a non-empty mapping")
    for name, identity in services.items():
        _text(name, "service name")
        _strict(identity, SERVICE_IDENTITY_FIELDS, f"identity for {name}")
        for field in (
            "release_id",
            "image_reference",
            "platform",
            "runtime_variant",
        ):
            if not isinstance(identity[field], str) or not identity[field]:
                raise StateError(f"identity for {name} has invalid {field}")
        if not IMAGE_REFERENCE_PATTERN.fullmatch(identity["image_reference"]):
            raise StateError(f"identity for {name} image reference is not immutable")
        for field in (
            "release_descriptor_sha256",
            "image_manifest_sha256",
            "configuration_sha256",
            "runtime_identity_sha256",
            "health_evidence_sha256",
        ):
            if not isinstance(identity[field], str) or not SHA256_PATTERN.fullmatch(
                identity[field]
            ):
                raise StateError(f"identity for {name} has invalid {field}")
        if type(identity["compatible"]) is not bool:
            raise StateError(f"identity for {name} has invalid compatibility result")
        if not isinstance(identity["health_status"], str) or identity[
            "health_status"
        ] not in {"HEALTHY", "UNHEALTHY", "UNKNOWN"}:
            raise StateError(f"identity for {name} has invalid health status")
        if not isinstance(identity["model_identities"], list):
            raise StateError(f"identity for {name} model_identities must be a list")
        for model in identity["model_identities"]:
            _strict(model, MODEL_IDENTITY_FIELDS, f"{name} model identity")
            for field in MODEL_IDENTITY_FIELDS:
                if not isinstance(model[field], str) or not model[field]:
                    raise StateError(f"identity for {name} has invalid model {field}")
            if not SHA256_PATTERN.fullmatch(model["manifest_sha256"]):
                raise StateError(
                    f"identity for {name} has invalid model manifest digest"
                )
    if not isinstance(value["sha256"], str) or not SHA256_PATTERN.fullmatch(
        value["sha256"]
    ):
        raise StateError("generation digest is invalid")
    if record_digest(value) != value["sha256"]:
        raise StateError("generation checksum mismatch")
    return value


def validate_operation(value: dict) -> dict:
    _strict(value, OPERATION_FIELDS, "operation revision")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise StateError("unknown operation schema version")
    _text(value["operation_id"], "operation_id")
    if (
        not isinstance(value["operation_type"], str)
        or value["operation_type"] not in OPERATION_TYPES
    ):
        raise StateError("operation_type is invalid")
    _utc_timestamp(value["created_at"], "created_at")
    if not isinstance(value["state"], str) or value["state"] not in OPERATION_STATES:
        raise StateError("operation state is invalid")
    allowed_states = set(TRANSITIONS[value["operation_type"]]) | {
        "REJECTED",
        "FAILED",
        "PARTIAL",
        "UNKNOWN",
    }
    if value["operation_type"] == "ROLLBACK":
        allowed_states |= {"ROLLBACK_FAILED", "ROLLED_BACK"}
    elif value["operation_type"] != "ROLLBACK":
        allowed_states.add("SUCCEEDED")
    if value["state"] not in allowed_states:
        raise StateError("operation state is invalid for operation type")
    if value["outcome"] is not None and (
        not isinstance(value["outcome"], str) or value["outcome"] not in OUTCOMES
    ):
        raise StateError("operation outcome is invalid")
    if (value["outcome"] is None and value["state"] in TERMINAL_STATES) or (
        value["outcome"] is not None and value["state"] != value["outcome"]
    ):
        raise StateError("terminal state and operation outcome must agree")
    if value["outcome"] is not None and value["state"] not in TRANSITIONS[
        value["operation_type"]
    ].get("VERIFYING", set()) | {"REJECTED"}:
        raise StateError("outcome is inconsistent with operation type")
    if value["outcome"] == "REJECTED" and value["state"] != "REJECTED":
        raise StateError("rejected outcome must use REJECTED state")
    if value["outcome"] == "SUCCEEDED" and value["operation_type"] == "ROLLBACK":
        raise StateError("rollback success must use ROLLED_BACK")
    if value["outcome"] == "ROLLED_BACK" and value["operation_type"] != "ROLLBACK":
        raise StateError("ROLLED_BACK is only valid for rollback operations")
    if value["outcome"] == "ROLLBACK_FAILED" and value["operation_type"] != "ROLLBACK":
        raise StateError("ROLLBACK_FAILED is only valid for rollback operations")
    if value["operation_type"] == "ROLLBACK" and value["outcome"] in {
        "FAILED",
        "SUCCEEDED",
    }:
        raise StateError("rollback outcome is inconsistent with rollback state machine")
    if (
        not isinstance(value["metadata"], dict)
        or set(value["metadata"]) - METADATA_FIELDS
    ):
        raise StateError("operation metadata has missing or unknown fields")
    if any(
        not isinstance(item, str)
        or not item
        or any(
            term in item.lower()
            for term in (
                "password=",
                "token=",
                "secret=",
                "credential=",
                "audio",
                "transcript",
            )
        )
        for item in value["metadata"].values()
    ):
        raise StateError("operation metadata contains an invalid or prohibited value")
    if value["rollback_eligibility"] is not None and (
        not isinstance(value["rollback_eligibility"], str)
        or value["rollback_eligibility"] not in ELIGIBILITY
    ):
        raise StateError("rollback eligibility assessment is invalid")
    if type(value["revision"]) is not int or value["revision"] < 1:
        raise StateError("revision must be a positive integer")
    previous = value["previous_revision_sha256"]
    if (value["revision"] == 1 and previous is not None) or (
        value["revision"] > 1
        and (not isinstance(previous, str) or not SHA256_PATTERN.fullmatch(previous))
    ):
        raise StateError("previous revision digest is invalid")
    if not isinstance(value["sha256"], str) or not SHA256_PATTERN.fullmatch(
        value["sha256"]
    ):
        raise StateError("operation digest is invalid")
    if record_digest(value) != value["sha256"]:
        raise StateError("operation checksum mismatch")
    return value


def _reject_symlink_components(path: Path) -> None:
    if ".." in path.parts:
        raise StateError("state path cannot contain parent traversal")
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise StateError(f"state path contains a symlink: {current}")


def _safe_dir(path: Path, expected_uid: int) -> None:
    _reject_symlink_components(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise StateError(f"state path is not a directory: {path}")
    if info.st_uid != expected_uid:
        raise StateError(f"state directory has unexpected owner: {path}")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise StateError(f"state directory mode must be 0700: {path}")


def _filesystem_type(path: Path) -> str:
    """Return the mounted filesystem type from Linux mountinfo, failing closed."""
    try:
        resolved = path.resolve(strict=True)
        mounts = []
        for line in (
            Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
        ):
            fields = line.split()
            separator = fields.index("-")
            mountpoint = Path(
                fields[4]
                .replace("\\040", " ")
                .replace("\\011", "\t")
                .replace("\\134", "\\")
            )
            if resolved == mountpoint or mountpoint in resolved.parents:
                mounts.append((len(mountpoint.parts), fields[separator + 1]))
        if not mounts:
            raise StateError("state root filesystem cannot be identified")
        return max(mounts)[1]
    except (OSError, ValueError, IndexError) as error:
        raise StateError("state root filesystem cannot be identified") from error


def _mkdir_private(path: Path, fsync: Callable[[int], None]) -> None:
    try:
        mkdir_private(path, fsync)
    except OSError as error:
        raise StateError(
            f"cannot durably create private state directory: {path}"
        ) from error


class StateStore:
    """Project-scoped store. Construction validates existing paths; it never initializes host state."""

    def __init__(
        self,
        root: str | Path = DEFAULT_STATE_ROOT,
        project_name: str = "speech-platform",
        *,
        expected_uid: int | None = None,
        fsync: Callable[[int], None] = os.fsync,
        before_publish: Callable[[Path, Path], None] | None = None,
        filesystem_type: Callable[[Path], str] = _filesystem_type,
    ):
        self.root = Path(root)
        if not self.root.is_absolute():
            raise StateError("state root must be an absolute path")
        self.project_name = _text(project_name, "project_name", PROJECT_PATTERN)
        self.expected_uid = os.getuid() if expected_uid is None else expected_uid
        _safe_dir(self.root, self.expected_uid)
        fs_type = filesystem_type(self.root)
        if fs_type not in SUPPORTED_FILESYSTEMS:
            raise StateError(f"unsupported state filesystem: {fs_type}")
        self.project = self.root / self.project_name
        _safe_dir(self.project, self.expected_uid)
        self.generations = self.project / "generations"
        self.operations = self.project / "operations"
        _safe_dir(self.generations, self.expected_uid)
        _safe_dir(self.operations, self.expected_uid)
        self._fsync = fsync
        self._before_publish = before_publish
        self._filesystem_type = filesystem_type

    @classmethod
    def initialize(
        cls,
        root: str | Path,
        project_name: str,
        *,
        expected_uid: int | None = None,
        fsync: Callable[[int], None] = os.fsync,
        before_publish: Callable[[Path, Path], None] | None = None,
        filesystem_type: Callable[[Path], str] = _filesystem_type,
    ) -> "StateStore":
        """Explicitly initialize a store; intended for separately authorized setup and tests."""
        base = Path(root)
        if not base.is_absolute():
            raise StateError("state root must be an absolute path")
        uid = os.getuid() if expected_uid is None else expected_uid
        _reject_symlink_components(base)
        filesystem_probe = base if base.exists() else base.parent
        filesystem = filesystem_type(filesystem_probe)
        if filesystem not in SUPPORTED_FILESYSTEMS:
            raise StateError(f"unsupported state filesystem: {filesystem}")
        if not base.exists():
            if not base.parent.is_dir():
                raise StateError("state root parent must already exist")
            _mkdir_private(base, fsync)
        _safe_dir(base, uid)
        project = base / _text(project_name, "project_name", PROJECT_PATTERN)
        if not project.exists():
            _mkdir_private(project, fsync)
        else:
            _safe_dir(project, uid)
        for name in ("generations", "operations"):
            child = project / name
            if not child.exists():
                _mkdir_private(child, fsync)
            else:
                _safe_dir(child, uid)
        return cls(
            base,
            project_name,
            expected_uid=uid,
            fsync=fsync,
            before_publish=before_publish,
            filesystem_type=filesystem_type,
        )

    def _publish(self, path: Path, data: bytes, *, replace: bool = False) -> None:
        filesystem = self._filesystem_type(path.parent)
        if filesystem not in SUPPORTED_FILESYSTEMS:
            raise StateError(f"unsupported state filesystem: {filesystem}")
        try:
            publish_immutable_file(
                path.parent,
                path.name,
                data,
                fsync=self._fsync,
                before_publish=(
                    None
                    if self._before_publish is None
                    else lambda temporary, _target: self._before_publish(
                        temporary, path
                    )
                ),
                replace=replace,
            )
        except FileExistsError as error:
            raise StateError(f"immutable record already exists: {path.name}") from error
        except StateError:
            raise
        except OSError as error:
            raise StateError(f"durable publication failed for {path.name}") from error

    def _read(self, path: Path) -> dict:
        _reject_symlink_components(path)
        try:
            parent_fd = os.open(
                path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.expected_uid:
                raise StateError(f"record type or owner is invalid: {path.name}")
            if info.st_nlink != 1:
                raise StateError(f"record has unexpected hard links: {path.name}")
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise StateError(f"record mode must be 0600: {path.name}")
            with os.fdopen(fd, "rb") as stream:
                fd = -1
                raw = stream.read()
            value = json.loads(raw)
        except StateError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise StateError(f"record is missing or unreadable: {path.name}") from error
        finally:
            if "fd" in locals() and fd >= 0:
                os.close(fd)
            if "parent_fd" in locals():
                os.close(parent_fd)
        if not isinstance(value, dict) or canonical_json(value) != raw:
            raise StateError(f"record is malformed or noncanonical: {path.name}")
        return value

    def put_generation(self, record: dict) -> str:
        value = dict(record)
        value.pop("sha256", None)
        value["sha256"] = record_digest(value)
        validate_generation(value)
        self._publish(
            self.generations / f"{value['generation_id']}.json", canonical_json(value)
        )
        return value["sha256"]

    def put_operation_revision(self, record: dict) -> str:
        value = dict(record)
        operation_id = _text(value.get("operation_id"), "operation_id")
        directory = self.operations / operation_id
        _reject_symlink_components(directory)
        if directory.exists():
            _safe_dir(directory, self.expected_uid)
        existing = self._operation_paths(operation_id)
        prior_digest = None
        for sequence, path in enumerate(existing, start=1):
            prior = validate_operation(self._read(path))
            if (
                path.name != f"r{sequence}.json"
                or prior["revision"] != sequence
                or prior["operation_id"] != operation_id
                or prior["previous_revision_sha256"] != prior_digest
            ):
                raise StateError(
                    "existing operation revision sequence or chain is corrupt"
                )
            prior_digest = prior["sha256"]
        expected = len(existing) + 1
        if value.get("revision") != expected:
            raise StateError(f"revision must be contiguous; expected {expected}")
        if expected == 1 and value.get("state") != "PLANNED":
            raise StateError("first operation revision must be PLANNED")
        previous = validate_operation(self._read(existing[-1])) if existing else None
        if previous and previous["outcome"] is not None:
            raise StateError("terminal operation revisions cannot be extended")
        if previous:
            immutable = ("operation_id", "operation_type", "created_at", "metadata")
            if any(value.get(field) != previous[field] for field in immutable):
                raise StateError("immutable operation identity or metadata changed")
            if value.get("state") not in TRANSITIONS[previous["operation_type"]].get(
                previous["state"], set()
            ):
                raise StateError("illegal operation state transition")
        value["previous_revision_sha256"] = previous["sha256"] if previous else None
        value.pop("sha256", None)
        value["sha256"] = record_digest(value)
        validate_operation(value)
        if not directory.exists():
            directory.mkdir(mode=0o700)
            parent_fd = os.open(
                self.operations, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            try:
                self._fsync(parent_fd)
            finally:
                os.close(parent_fd)
        _safe_dir(directory, self.expected_uid)
        self._publish(directory / f"r{expected}.json", canonical_json(value))
        return value["sha256"]

    def _operation_paths(self, operation_id: str) -> list[Path]:
        directory = self.operations / operation_id
        if not directory.exists():
            return []
        try:
            return sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError as error:
            raise StateError("operation directory cannot be read") from error

    def _validate_generation_promotion(
        self, generation: dict, current_id: str | None
    ) -> None:
        if generation["parent_generation_id"] != current_id:
            raise StateError("generation parent does not match installed generation")
        if any(
            identity["compatible"] is not True or identity["health_status"] != "HEALTHY"
            for identity in generation["services"].values()
        ):
            raise StateError("generation lacks compatible healthy service evidence")
        operation_id = generation["operation_id"]
        paths = self._operation_paths(operation_id)
        if not paths:
            raise StateError("generation producer has no operation evidence")
        revisions = []
        previous_digest = None
        for index, path in enumerate(paths, 1):
            if path.name != f"r{index}.json":
                raise StateError("generation producer revision sequence is malformed")
            item = validate_operation(self._read(path))
            if (
                item["operation_id"] != operation_id
                or item["revision"] != index
                or item["previous_revision_sha256"] != previous_digest
            ):
                raise StateError("generation producer operation chain is inconsistent")
            if revisions:
                prior = revisions[-1]
                if (
                    prior["outcome"] is not None
                    or item["operation_type"] != prior["operation_type"]
                    or item["created_at"] != prior["created_at"]
                    or item["metadata"] != prior["metadata"]
                    or item["state"]
                    not in TRANSITIONS[prior["operation_type"]].get(
                        prior["state"], set()
                    )
                ):
                    raise StateError(
                        "generation producer operation transitions are inconsistent"
                    )
            revisions.append(item)
            previous_digest = item["sha256"]
        last = revisions[-1]
        if last["state"] not in {"VERIFYING", "SUCCEEDED", "ROLLED_BACK"}:
            raise StateError(
                "generation producer has not reached verified promotion state"
            )

    def set_installed_generation(self, generation_id: str) -> None:
        _text(generation_id, "generation_id")
        generation = validate_generation(
            self._read(self.generations / f"{generation_id}.json")
        )
        if generation["project_name"] != self.project_name:
            raise StateError("generation belongs to another project")
        pointer_path = self.project / "installed.json"
        current_generation_id = None
        if pointer_path.exists() or pointer_path.is_symlink():
            current = _strict(
                self._read(pointer_path), POINTER_FIELDS, "installed pointer"
            )
            current_generation_id = _text(current["generation_id"], "generation_id")
            if (
                type(current["schema_version"]) is not int
                or current["schema_version"] != SCHEMA_VERSION
            ):
                raise StateError("unknown installed pointer schema version")
            _text(current["sha256"], "installed pointer digest", SHA256_PATTERN)
            current_generation = validate_generation(
                self._read(self.generations / f"{current_generation_id}.json")
            )
            if (
                current_generation["generation_id"] != current_generation_id
                or current_generation["project_name"] != self.project_name
                or current_generation["sha256"] != current["sha256"]
            ):
                raise StateError(
                    "installed pointer is inconsistent; refusing replacement"
                )
        self._validate_generation_promotion(generation, current_generation_id)
        pointer = {
            "schema_version": 1,
            "generation_id": generation_id,
            "sha256": generation["sha256"],
        }
        self._publish(
            self.project / "installed.json", canonical_json(pointer), replace=True
        )

    def inspect(self) -> dict:
        """Read-only integrity inspection; never repairs or contacts Docker."""
        issues: list[str] = []
        for path in (self.project, self.generations, self.operations):
            try:
                filesystem = self._filesystem_type(path)
                if filesystem not in SUPPORTED_FILESYSTEMS:
                    issues.append(
                        f"directory {path.name}: unsupported filesystem {filesystem}"
                    )
            except StateError as error:
                issues.append(f"directory {path.name}: {error}")
        generations: dict[str, dict] = {}
        try:
            generation_entries = sorted(self.generations.iterdir())
        except OSError as error:
            generation_entries = []
            issues.append(f"generation directory cannot be read: {error}")
        for path in generation_entries:
            if path.name.startswith(".pending-"):
                issues.append(f"generation temporary publication remains: {path.name}")
                continue
            if path.suffix != ".json":
                issues.append(f"generation entry {path.name}: unsupported filename")
                continue
            try:
                value = validate_generation(self._read(path))
                if (
                    path.name != f"{value['generation_id']}.json"
                    or value["project_name"] != self.project_name
                ):
                    raise StateError("generation identity or project path mismatch")
                generations[value["generation_id"]] = value
            except StateError as error:
                issues.append(f"generation {path.name}: {error}")
        operations: dict[str, list[dict]] = {}
        try:
            operation_entries = sorted(self.operations.iterdir())
        except OSError as error:
            operation_entries = []
            issues.append(f"operation directory cannot be read: {error}")
        for directory in operation_entries:
            if directory.name.startswith(".pending-"):
                issues.append(
                    f"operation temporary publication remains: {directory.name}"
                )
                continue
            if not directory.is_dir() or directory.is_symlink():
                issues.append(f"operation entry {directory.name}: invalid directory")
                continue
            try:
                _safe_dir(directory, self.expected_uid)
            except (StateError, OSError) as error:
                issues.append(f"operation directory {directory.name}: {error}")
                continue
            if not ID_PATTERN.fullmatch(directory.name):
                issues.append(f"operation entry {directory.name}: invalid operation id")
            paths = self._operation_paths(directory.name)
            revisions = []
            if not paths:
                issues.append(f"operation {directory.name}: no committed revisions")
            expected = 1
            previous_digest = None
            for path in paths:
                try:
                    if path.name.startswith(".pending-"):
                        issues.append(
                            f"operation {directory.name}: temporary publication remains: {path.name}"
                        )
                        continue
                    if not path.is_file() or path.suffix != ".json":
                        raise StateError(
                            "operation entry has unsupported type or filename"
                        )
                    value = validate_operation(self._read(path))
                    if (
                        path.name != f"r{expected}.json"
                        or value["revision"] != expected
                    ):
                        raise StateError(
                            "revision sequence has a gap, duplicate, or wrong filename"
                        )
                    if expected == 1 and value["state"] != "PLANNED":
                        raise StateError("first operation revision is not PLANNED")
                    if (
                        value["operation_id"] != directory.name
                        or value["previous_revision_sha256"] != previous_digest
                    ):
                        raise StateError(
                            "operation identity or previous revision link is broken"
                        )
                    if revisions and revisions[-1]["outcome"] is not None:
                        issues.append(
                            f"operation {directory.name}: terminal operation revision was extended"
                        )
                    if revisions:
                        prior = revisions[-1]
                        if (
                            value["operation_type"] != prior["operation_type"]
                            or value["created_at"] != prior["created_at"]
                            or value["metadata"] != prior["metadata"]
                        ):
                            raise StateError(
                                "immutable operation identity or metadata changed"
                            )
                        if value["state"] not in TRANSITIONS[
                            prior["operation_type"]
                        ].get(prior["state"], set()):
                            raise StateError("illegal operation state transition")
                    revisions.append(value)
                    previous_digest = value["sha256"]
                    expected += 1
                except StateError as error:
                    issues.append(f"operation {directory.name}/{path.name}: {error}")
            if revisions:
                operations[directory.name] = revisions
                if revisions[-1]["outcome"] is None:
                    issues.append(f"operation {directory.name}: unfinished")
                outcomes = [r["outcome"] for r in revisions if r["outcome"] is not None]
                if len(outcomes) > 1:
                    issues.append(
                        f"operation {directory.name}: contradictory terminal records"
                    )
        for generation_id, record in generations.items():
            if (
                record["parent_generation_id"] is not None
                and record["parent_generation_id"] not in generations
            ):
                issues.append(
                    f"generation {generation_id}: parent generation is missing"
                )
            if record["parent_generation_id"] == generation_id:
                issues.append(f"generation {generation_id}: cannot be its own parent")
            if record["operation_id"] not in operations:
                issues.append(
                    f"generation {generation_id}: producing operation is missing"
                )
            else:
                try:
                    current = None
                    pointer_record = None
                    pointer_file = self.project / "installed.json"
                    if pointer_file.exists():
                        pointer_record = _strict(
                            self._read(pointer_file),
                            POINTER_FIELDS,
                            "installed pointer",
                        )
                        current = pointer_record.get("generation_id")
                    self._validate_generation_promotion(
                        record,
                        record["parent_generation_id"]
                        if generation_id != current
                        else (record["parent_generation_id"]),
                    )
                except StateError as error:
                    issues.append(
                        f"generation {generation_id}: promotion evidence: {error}"
                    )
        pointer_path = self.project / "installed.json"
        pointer = None
        if pointer_path.exists() or pointer_path.is_symlink():
            try:
                pointer = _strict(
                    self._read(pointer_path), POINTER_FIELDS, "installed pointer"
                )
                if (
                    type(pointer["schema_version"]) is not int
                    or pointer["schema_version"] != 1
                ):
                    raise StateError("unknown installed pointer schema version")
                _text(pointer["generation_id"], "installed pointer generation_id")
                _text(pointer["sha256"], "installed pointer digest", SHA256_PATTERN)
                generation = generations.get(pointer["generation_id"])
                if generation is None or generation["sha256"] != pointer["sha256"]:
                    raise StateError(
                        "installed pointer does not match a valid generation"
                    )
            except (StateError, KeyError, TypeError, OSError, ValueError) as error:
                issues.append(f"installed pointer: {error}")
        return {
            "status": "STATE_INCONSISTENT" if issues else "OK",
            "generation_ids": sorted(generations),
            "operation_ids": sorted(operations),
            "installed_generation_id": pointer.get("generation_id")
            if pointer
            else None,
            "issues": issues,
        }
