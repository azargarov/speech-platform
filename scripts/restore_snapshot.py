"""Read-only verification for private, project-level restoration snapshots."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import stat
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Sequence

from scripts.deployment_state import (
    SUPPORTED_FILESYSTEMS,
    _filesystem_type,
    _reject_symlink_components,
    canonical_json,
)
from scripts.durable_files import fsync_directory, mkdir_private, publish_immutable_file
from scripts.project_lock import ProjectLock

SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMMUTABLE_ARTIFACT_REF = re.compile(
    r"^(?:oci|model)://[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$|"
    r"^sha256:[0-9a-f]{64}$"
)
PROJECT_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
TOOL_VERSION = re.compile(r"^v?[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?$")
REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
IMAGE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]+@sha256:[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
NUMBER = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
MEMORY = re.compile(r"^[0-9]+(?:[bkmg]|[KMGT]iB)?$")
FORBIDDEN_CONTENT = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?i:\b(?:password|passwd|secret|api[_-]?(?:key|token)|token|access[_-]?token|authorization|credential|private[_-]?key)\b\s*[:=])"
)

COMMON_FILES = {
    "enabled-services.yaml",
    "services.yaml",
    "gateway.yaml",
    "tts.yaml",
    "compose.env",
    "compose.yaml",
    "release.yaml",
}
PROJECT_FILES = COMMON_FILES | {
    "profile.yaml",
    "stt-application.yaml",
    "stt-deployment.yaml",
    "stt.yaml",
    "compose.stt-cuda.yaml",
    "render-environment.json",
    "rendered-compose.json",
}
OPTIONAL_ARTIFACT_EVIDENCE_FILES = frozenset(
    {"image-build-evidence.json", "image-store-evidence.json"}
)
GENERATED_FILES = frozenset({"render-environment.json", "rendered-compose.json"})
CAPTURE_SOURCE_FILES = PROJECT_FILES - GENERATED_FILES
TRACKED_SOURCE_FILES = frozenset(
    {"compose.yaml", "compose.stt-cuda.yaml", "release.yaml"}
)
SERVICES = ("gateway", "stt", "tts")
MANIFEST_FIELDS = {
    "schema_version",
    "project_name",
    "source_revision",
    "source_git_blob_ids",
    "selected_services",
    "files",
    "optional_file_roles",
    "artifacts_by_service",
    "secret_versions_by_service",
    "rendered_compose_sha256",
    "compose_service_hashes",
    "configuration_sha256_by_service",
    "runtime_identity_sha256_by_service",
    "host_bindings_sha256",
    "docker_engine_version",
    "compose_version",
}
FILE_IDENTITY_FIELDS = {"sha256", "size_bytes", "classification"}

# This is the allowlist emitted by stt_deployment_profile.write_env_file for
# the retained compose.env. Any extra key, including a secret-looking key,
# blocks snapshot validation.
PERSISTED_ENV_KEYS = frozenset(
    {
        "SPEECH_BIND_IP",
        "SPEECH_LISTEN_PORT",
        "SPEECH_PORT",
        "STT_APPLICATION_CONFIG",
        "STT_APPLICATION_CONFIG_SHA256",
        "STT_ARTIFACT_GID",
        "STT_COMPOSE_PROJECT_NAME",
        "STT_CONFIGURATION_SET_SHA256",
        "STT_CPU_LIMIT",
        "STT_CUDA_IMAGE",
        "STT_CUDA_LOCK_SHA256",
        "STT_DEPLOYMENT_CONFIG",
        "STT_DEPLOYMENT_CONFIG_SHA256",
        "STT_DEPLOYMENT_PROFILE_SHA256",
        "STT_HEALTHCHECK_INTERVAL_SECONDS",
        "STT_HEALTHCHECK_PROBE_TIMEOUT_SECONDS",
        "STT_HEALTHCHECK_RETRIES",
        "STT_HEALTHCHECK_START_PERIOD_SECONDS",
        "STT_HEALTHCHECK_TIMEOUT_SECONDS",
        "STT_HOST_GPU_DEVICE_ID",
        "STT_IMAGE_ID",
        "STT_IMAGE_IDENTITY_MODE",
        "STT_LISTEN_PORT",
        "STT_MEMORY_LIMIT_BYTES",
        "STT_MODEL_HOST_ROOT",
        "STT_MODEL_MANIFEST_SHA256",
        "STT_MODEL_REVISION",
        "STT_PIDS_LIMIT",
        "STT_PLATFORM",
        "STT_SOURCE_REVISION",
        "STT_STOP_GRACE_PERIOD_SECONDS",
        "STT_WORKER_CONFIG",
        "STT_WORKER_CONFIG_SHA256",
    }
)
RENDER_ENV_KEYS = PERSISTED_ENV_KEYS | frozenset(
    {
        "SERVICE_PROJECT_NAME",
        "SERVICE_CONFIG_READER_GID",
        "GATEWAY_IMAGE",
        "TTS_IMAGE",
        "GATEWAY_CONFIG",
        "TTS_CONFIG",
        "GATEWAY_CONFIG_SHA256",
        "TTS_CONFIG_SHA256",
        "GATEWAY_MEMORY",
        "GATEWAY_CPUS",
        "GATEWAY_PIDS",
        "TTS_MEMORY",
        "TTS_CPUS",
        "TTS_PIDS",
        "GATEWAY_DEPLOYMENT_IDENTITY_SHA256",
        "TTS_DEPLOYMENT_IDENTITY_SHA256",
    }
)
PATH_ENV_KEYS = frozenset(
    {
        "GATEWAY_CONFIG",
        "TTS_CONFIG",
        "STT_APPLICATION_CONFIG",
        "STT_DEPLOYMENT_CONFIG",
        "STT_WORKER_CONFIG",
        "STT_MODEL_HOST_ROOT",
    }
)
PATH_ENV_BASENAMES = {
    "GATEWAY_CONFIG": "gateway.yaml",
    "TTS_CONFIG": "tts.yaml",
    "STT_APPLICATION_CONFIG": "stt-application.yaml",
    "STT_DEPLOYMENT_CONFIG": "stt-deployment.yaml",
    "STT_WORKER_CONFIG": "stt.yaml",
}
IMAGE_ENV_KEYS = frozenset({"GATEWAY_IMAGE", "TTS_IMAGE", "STT_CUDA_IMAGE"})
IMAGE_ID_KEYS = frozenset({"STT_IMAGE_ID"})
DIGEST_ENV_KEYS = frozenset(
    key for key in RENDER_ENV_KEYS if key.endswith("_SHA256") or key.endswith("_SHA")
)
REVISION_ENV_KEYS = frozenset({"STT_MODEL_REVISION", "STT_SOURCE_REVISION"})
INTEGER_ENV_KEYS = frozenset(
    {
        "SPEECH_LISTEN_PORT",
        "SPEECH_PORT",
        "SERVICE_CONFIG_READER_GID",
        "STT_ARTIFACT_GID",
        "STT_HOST_GPU_DEVICE_ID",
        "STT_LISTEN_PORT",
        "STT_MEMORY_LIMIT_BYTES",
        "STT_PIDS_LIMIT",
        "STT_STOP_GRACE_PERIOD_SECONDS",
        "STT_HEALTHCHECK_INTERVAL_SECONDS",
        "STT_HEALTHCHECK_PROBE_TIMEOUT_SECONDS",
        "STT_HEALTHCHECK_RETRIES",
        "STT_HEALTHCHECK_START_PERIOD_SECONDS",
        "STT_HEALTHCHECK_TIMEOUT_SECONDS",
    }
)
NUMBER_ENV_KEYS = frozenset({"STT_CPU_LIMIT", "GATEWAY_CPUS", "TTS_CPUS"})
MEMORY_ENV_KEYS = frozenset({"GATEWAY_MEMORY", "TTS_MEMORY"})
PROJECT_ENV_KEYS = frozenset({"SERVICE_PROJECT_NAME", "STT_COMPOSE_PROJECT_NAME"})


class SnapshotCaptureError(ValueError):
    """Snapshot capture refused input or failed before/while publishing."""


def _capture_fail(message: str, error: BaseException | None = None):
    failure = SnapshotCaptureError(message)
    if error is None:
        raise failure
    raise failure from None


def _source_bytes(
    path: Path,
    *,
    private: bool,
    allow_group_read: bool = False,
    maximum: int = 16 * 1024 * 1024,
) -> tuple[bytes, tuple]:
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        _capture_fail("snapshot source path is invalid")
    try:
        _reject_symlink_components(path)
        fd = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except (OSError, ValueError):
        _capture_fail("snapshot source is unavailable or unsafe")
    try:
        before = os.fstat(fd)
        current = path.lstat()
        try:
            attributes = os.listxattr(fd)
        except OSError:
            _capture_fail("snapshot source ACL state is unavailable")
        source_mode = stat.S_IMODE(before.st_mode)
        accepted_modes = (
            ({0o400, 0o600, 0o640} if allow_group_read else {0o400, 0o600})
            if private
            else {0o400, 0o444, 0o600, 0o644, 0o664}
        )
        if (
            not stat.S_ISREG(before.st_mode)
            or (private and before.st_uid != os.getuid())
            or (not private and before.st_uid not in {0, os.getuid()})
            or source_mode not in accepted_modes
            or before.st_nlink != 1
            or any(name.startswith("system.posix_acl_") for name in attributes)
            or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)
            or before.st_size > maximum
        ):
            _capture_fail(
                "snapshot source ownership, mode, type or link count is invalid"
            )
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                _capture_fail("snapshot source exceeds the configured size limit")
        after = os.fstat(fd)
        current = path.lstat()
        identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
        )
        if (
            identity
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
                after.st_mode,
                after.st_uid,
                after.st_gid,
                after.st_nlink,
            )
            or identity
            != (
                current.st_dev,
                current.st_ino,
                current.st_size,
                current.st_mtime_ns,
                current.st_ctime_ns,
                current.st_mode,
                current.st_uid,
                current.st_gid,
                current.st_nlink,
            )
            or total != before.st_size
        ):
            _capture_fail("snapshot source changed while being read")
        return b"".join(chunks), identity
    finally:
        os.close(fd)


def _validate_private_source_parents(path: Path) -> None:
    current = path.parent
    chain = []
    while current != current.parent:
        chain.append(current)
        if current.name == "private":
            break
        current = current.parent
    if not chain or chain[-1].name != "private":
        _capture_fail("private configuration input is outside private storage")
    for directory in chain:
        if directory.is_symlink():
            _capture_fail("private configuration input has a symlink parent")
        try:
            _secure_dir(directory)
        except ValueError:
            _capture_fail("private configuration input parent is unsafe")


def _validate_tracked_source_parents(
    path: Path, approved_roots: Sequence[Path]
) -> None:
    resolved = path.resolve(strict=True)
    roots = [root.resolve(strict=True) for root in approved_roots]
    selected_root = next(
        (root for root in roots if resolved != root and root in resolved.parents), None
    )
    if selected_root is None:
        _capture_fail("tracked source is outside approved repository roots")
    current = path.parent
    while True:
        try:
            info = current.lstat()
            fd = os.open(current, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                opened = os.fstat(fd)
                attributes = os.listxattr(fd)
            finally:
                os.close(fd)
        except OSError:
            _capture_fail("tracked source parent is unavailable or unsafe")
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in {0, os.getuid()}
            or stat.S_IMODE(info.st_mode) & 0o002
            or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino)
            or any(name.startswith("system.posix_acl_") for name in attributes)
        ):
            _capture_fail("tracked source parent permissions are unsafe")
        if current == selected_root:
            break
        if current == current.parent:
            _capture_fail("tracked source parent escapes its approved root")
        current = current.parent


def _ensure_private_dir(path: Path, *, create: bool) -> None:
    try:
        if create and not path.exists() and not path.is_symlink():
            mkdir_private(path)
        path.lstat()
    except (OSError, FileNotFoundError):
        _capture_fail("snapshot storage directory is unavailable")
    try:
        _secure_dir(path)
    except ValueError:
        _capture_fail("snapshot storage directory ownership or mode is unsafe")


def _write_staged_file(directory: Path, name: str, data: bytes) -> None:
    if (
        name not in PROJECT_FILES | OPTIONAL_ARTIFACT_EVIDENCE_FILES
        or Path(name).name != name
    ):
        _capture_fail("snapshot staging file role is invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(directory / name, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    _capture_fail("snapshot staging write was incomplete")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
    except FileExistsError:
        _capture_fail("snapshot staging file already exists")
    except OSError:
        _capture_fail("snapshot staging write failed")


def _runtime_projection(
    evidence: object, project_name: str, maximum_age_seconds: int
) -> dict:
    fields = {
        "container_id",
        "compose_project_name",
        "compose_service_name",
        "image_id",
        "image_reference",
        "platform",
        "compose_config_hash",
        "configuration_sha256",
        "runtime_identity_sha256",
        "compatible",
        "state",
        "health",
        "readiness",
    }
    if (
        not isinstance(evidence, dict)
        or evidence.get("project_name") != project_name
        or not isinstance(evidence.get("docker_engine_version"), str)
        or not TOOL_VERSION.fullmatch(evidence["docker_engine_version"])
        or not isinstance(evidence.get("compose_version"), str)
        or not TOOL_VERSION.fullmatch(evidence["compose_version"])
        or not isinstance(evidence.get("observed_at_epoch"), (int, float))
        or time.time() - evidence["observed_at_epoch"] > maximum_age_seconds
        or evidence["observed_at_epoch"] > time.time() + 1
        or not isinstance(evidence.get("services"), dict)
        or set(evidence["services"]) != set(SERVICES)
    ):
        _capture_fail("runtime evidence is missing, stale or for another project")
    result = {
        "docker_engine_version": evidence["docker_engine_version"],
        "compose_version": evidence["compose_version"],
        "services": {},
    }
    for service, observed in evidence["services"].items():
        if not isinstance(observed, dict) or not fields.issubset(observed):
            _capture_fail("runtime service evidence is incomplete")
        readiness = observed["readiness"]
        if (
            observed["state"] != "running"
            or observed["compose_project_name"] != project_name
            or observed["compose_service_name"] != service
            or observed["health"] != "healthy"
            or observed["compatible"] is not True
            or not isinstance(readiness, dict)
            or readiness.get("status") != "READY"
            or not isinstance(readiness.get("observed_at_epoch"), (int, float))
            or time.time() - readiness["observed_at_epoch"] > maximum_age_seconds
            or readiness["observed_at_epoch"] > time.time() + 1
            or not isinstance(observed["container_id"], str)
            or not observed["container_id"]
            or not isinstance(observed["image_id"], str)
            or not IMAGE_ID.fullmatch(observed["image_id"])
            or not isinstance(observed["image_reference"], str)
            or not IMAGE_REF.fullmatch(observed["image_reference"])
            or observed["platform"] != "linux/amd64"
        ):
            _capture_fail("runtime service is unhealthy, unready or malformed")
        for key in (
            "compose_config_hash",
            "configuration_sha256",
            "runtime_identity_sha256",
        ):
            if not _sha256(observed[key]):
                _capture_fail("runtime service identity is invalid")
        result["services"][service] = {
            key: observed[key]
            for key in sorted(fields - {"health", "readiness", "state"})
        }
    return result


def _validate_rendered_mounts(
    rendered: dict, render_environment: dict[str, str]
) -> None:
    expected = {
        "gateway": {"/config/gateway.yaml": render_environment["GATEWAY_CONFIG"]},
        "tts": {"/config/tts.yaml": render_environment["TTS_CONFIG"]},
        "stt": {
            "/config/stt-application.yaml": render_environment[
                "STT_APPLICATION_CONFIG"
            ],
            "/config/stt-deployment.yaml": render_environment["STT_DEPLOYMENT_CONFIG"],
            "/config/stt.yaml": render_environment["STT_WORKER_CONFIG"],
            "/models": render_environment["STT_MODEL_HOST_ROOT"],
        },
    }
    services = rendered["services"]
    for service, targets in expected.items():
        volumes = services[service].get("volumes", [])
        if not isinstance(volumes, list):
            _capture_fail("rendered Compose mounts are invalid")
        observed = {}
        for volume in volumes:
            if (
                not isinstance(volume, dict)
                or volume.get("type") != "bind"
                or volume.get("read_only") is not True
                or not isinstance(volume.get("source"), str)
                or not isinstance(volume.get("target"), str)
            ):
                _capture_fail("rendered Compose contains an unapproved mount")
            observed[volume["target"]] = volume["source"]
        if len(observed) != len(volumes) or observed != targets:
            _capture_fail("rendered Compose mount set does not match captured inputs")


def capture_snapshot(
    root: Path,
    project_name: str,
    source_paths: Mapping[str, Path],
    *,
    allowed_source_roots: Sequence[Path],
    validate_configuration: Callable[[Mapping[str, bytes]], dict],
    render_captured: Callable[[Mapping[str, bytes]], dict],
    collect_runtime: Callable[[], dict],
    verify_artifacts: Callable[[dict[str, list[str]]], None],
    lock_root: Path,
    expected_uid: int | None = None,
    maximum_runtime_age_seconds: int = 30,
    before_publish: Callable[[str, str], None] | None = None,
    filesystem_type: Callable[[Path], str] = _filesystem_type,
    tracked_source_validator: Callable[
        [Mapping[str, Path], Mapping[str, bytes] | None], object
    ]
    | None = None,
    tracked_source_revision: str | None = None,
) -> dict:
    """Capture a verified project snapshot; all external evidence is injected.

    The callbacks are trusted adapters around existing strict config, artifact,
    Compose-render and Docker-evidence helpers. This function never invokes
    Docker itself and never changes running services.
    """
    if not isinstance(project_name, str) or not PROJECT_NAME.fullmatch(project_name):
        _capture_fail("Compose project identity is invalid")
    if (
        type(maximum_runtime_age_seconds) is not int
        or not 1 <= maximum_runtime_age_seconds <= 300
    ):
        _capture_fail("runtime evidence freshness bound is invalid")
    if (
        not isinstance(source_paths, Mapping)
        or not CAPTURE_SOURCE_FILES.issubset(source_paths)
        or set(source_paths) - CAPTURE_SOURCE_FILES - OPTIONAL_ARTIFACT_EVIDENCE_FILES
    ):
        _capture_fail(
            "snapshot configuration input set is incomplete or contains unknown roles"
        )
    if TRACKED_SOURCE_FILES.intersection(source_paths):
        if not isinstance(tracked_source_revision, str) or not REVISION.fullmatch(
            tracked_source_revision
        ):
            _capture_fail("approved tracked source commit identity is required")
    if (
        not isinstance(allowed_source_roots, Sequence)
        or isinstance(allowed_source_roots, (str, bytes))
        or not allowed_source_roots
    ):
        _capture_fail("approved configuration source roots are required")
    root = Path(root)
    if root.is_symlink() or not root.is_absolute() or ".." in root.parts:
        _capture_fail("snapshot root path is invalid")
    uid = os.getuid() if expected_uid is None else expected_uid
    if uid != os.getuid():
        _capture_fail("snapshot owner must be the current operator")
    try:
        _require_private_ancestry(root)
        if filesystem_type(root) not in SUPPORTED_FILESYSTEMS:
            _capture_fail("snapshot storage filesystem is unsupported")
    except (OSError, ValueError):
        _capture_fail("snapshot storage boundary failed validation")

    def read_sources() -> tuple[dict[str, bytes], dict[str, tuple], dict[str, str]]:
        contents, identities = {}, {}
        tracked_paths = {
            name: Path(path)
            for name, path in source_paths.items()
            if name in TRACKED_SOURCE_FILES
        }
        if tracked_paths:
            if not callable(tracked_source_validator):
                _capture_fail("approved tracked source revision is required")
            try:
                tracked_ids = tracked_source_validator(tracked_paths, None)
            except Exception:
                _capture_fail("tracked source integrity validation failed")
            if (
                not isinstance(tracked_ids, dict)
                or set(tracked_ids) != set(TRACKED_SOURCE_FILES)
                or any(
                    not isinstance(value, str) or not REVISION.fullmatch(value)
                    for value in tracked_ids.values()
                )
            ):
                _capture_fail("tracked source Git blob identities are incomplete")
        else:
            tracked_ids = {}
        try:
            approved_roots = [
                Path(item).resolve(strict=True) for item in allowed_source_roots
            ]
        except (OSError, TypeError, ValueError):
            _capture_fail("approved configuration source root is unavailable")
        for role in sorted(set(source_paths) - GENERATED_FILES):
            try:
                source_path = Path(source_paths[role])
                resolved_source = source_path.resolve(strict=True)
            except (OSError, TypeError, ValueError):
                _capture_fail("snapshot source is unavailable or unsafe")
            if not any(
                resolved_source != approved and approved in resolved_source.parents
                for approved in approved_roots
            ):
                _capture_fail("snapshot source is outside approved configuration roots")
            is_private = role not in TRACKED_SOURCE_FILES
            if is_private:
                _validate_private_source_parents(source_path)
            else:
                _validate_tracked_source_parents(source_path, approved_roots)
            content, identity = _source_bytes(
                source_path,
                private=is_private,
                allow_group_read=role
                in {
                    "gateway.yaml",
                    "tts.yaml",
                    "stt-application.yaml",
                    "stt-deployment.yaml",
                    "stt.yaml",
                },
            )
            contents[role] = content
            identities[role] = identity
            try:
                _validate_config_blob(role, content)
            except ValueError as error:
                raise SnapshotCaptureError(str(error)) from None
        if tracked_paths:
            try:
                captured_ids = tracked_source_validator(
                    tracked_paths,
                    {role: contents[role] for role in tracked_paths},
                )
            except Exception:
                _capture_fail("captured tracked source integrity validation failed")
            if captured_ids != tracked_ids:
                _capture_fail("tracked source identities changed during capture")
        persisted_env = _decode_env_file(contents["compose.env"])
        for key, role in {
            "STT_APPLICATION_CONFIG": "stt-application.yaml",
            "STT_DEPLOYMENT_CONFIG": "stt-deployment.yaml",
            "STT_WORKER_CONFIG": "stt.yaml",
        }.items():
            if persisted_env[key] != str(Path(source_paths[role]).resolve()):
                _capture_fail("persisted Compose path is not the captured input")
        if persisted_env["STT_COMPOSE_PROJECT_NAME"] != project_name:
            _capture_fail("persisted Compose project identity does not match")
        return contents, identities, tracked_ids

    initial, initial_identities, initial_tracked_ids = read_sources()
    try:
        initial_contract = validate_configuration(initial)
    except Exception:
        _capture_fail("captured configuration failed strict validation")
    if (
        not isinstance(initial_contract, dict)
        or initial_contract.get("project_name") != project_name
    ):
        _capture_fail("validated configuration project identity does not match")
    optional_roles = initial_contract.get("required_optional_file_roles")
    if (
        not isinstance(optional_roles, list)
        or not all(isinstance(role, str) for role in optional_roles)
        or optional_roles != sorted(set(optional_roles))
        or set(optional_roles) - OPTIONAL_ARTIFACT_EVIDENCE_FILES
        or set(source_paths) != CAPTURE_SOURCE_FILES | set(optional_roles)
    ):
        _capture_fail(
            "snapshot dependency closure is incomplete or contains unknown roles"
        )

    lock = ProjectLock(project_name, lock_root, expected_uid=uid)
    try:
        lock.acquire()
    except Exception:
        _capture_fail("shared project lock could not be acquired")
    try:
        lock.assert_current()
        locked_sources, locked_identities, locked_tracked_ids = read_sources()
        if (
            initial_identities != locked_identities
            or initial_tracked_ids != locked_tracked_ids
            or initial != locked_sources
        ):
            _capture_fail("configuration changed before capture lock acquisition")
        try:
            contract = validate_configuration(locked_sources)
            runtime_before = collect_runtime()
        except Exception:
            _capture_fail("configuration or runtime evidence revalidation failed")
        if contract != initial_contract:
            _capture_fail("validated configuration changed during capture")
        runtime_before_projection = _runtime_projection(
            runtime_before, project_name, maximum_runtime_age_seconds
        )

        staging_root = root / "staging"
        snapshots_root = root / "snapshots"
        objects_root = root / "objects"
        for directory in (staging_root, snapshots_root, objects_root):
            _ensure_private_dir(directory, create=True)
        snapshots_hash = snapshots_root / "sha256"
        objects_hash = objects_root / "sha256"
        _ensure_private_dir(snapshots_hash, create=True)
        _ensure_private_dir(objects_hash, create=True)
        stage = staging_root / uuid.uuid4().hex
        try:
            mkdir_private(stage)
        except OSError:
            _capture_fail("private snapshot staging directory could not be created")

        staged = dict(locked_sources)
        try:
            render_result = render_captured(staged)
        except Exception:
            _capture_fail(
                "captured configuration could not reproduce Compose rendering"
            )
        if not isinstance(render_result, dict) or set(render_result) != {
            "render_environment",
            "rendered_compose",
            "compose_service_hashes",
        }:
            _capture_fail("captured Compose render evidence is incomplete")
        try:
            render_env = _validate_environment(
                render_result["render_environment"], persisted=False
            )
            persisted_env = _decode_env_file(locked_sources["compose.env"])
            if any(render_env[key] != persisted_env[key] for key in PERSISTED_ENV_KEYS):
                _capture_fail(
                    "rendered environment differs from persisted configuration"
                )
            rendered = render_result["rendered_compose"]
            compose_hashes = render_result["compose_service_hashes"]
            generated = {
                "render-environment.json": canonical_json(render_env),
                "rendered-compose.json": canonical_json(rendered),
            }
            for name, raw in generated.items():
                _validate_config_blob(name, raw)
            if (
                not isinstance(rendered, dict)
                or rendered.get("name") != project_name
                or not isinstance(rendered.get("services"), dict)
                or set(rendered["services"]) != set(SERVICES)
            ):
                _capture_fail("rendered Compose service identity set is incomplete")
            expected_config_paths = {
                "GATEWAY_CONFIG": "gateway.yaml",
                "TTS_CONFIG": "tts.yaml",
                "STT_APPLICATION_CONFIG": "stt-application.yaml",
                "STT_DEPLOYMENT_CONFIG": "stt-deployment.yaml",
                "STT_WORKER_CONFIG": "stt.yaml",
            }
            for key, role in expected_config_paths.items():
                if render_env[key] != str(Path(source_paths[role]).resolve()):
                    _capture_fail(
                        "rendered Compose configuration path is not the captured input"
                    )
            if render_env["SERVICE_PROJECT_NAME"] != project_name:
                _capture_fail("rendered Compose project identity does not match")
            _validate_rendered_mounts(rendered, render_env)
            if not isinstance(compose_hashes, dict) or set(compose_hashes) != set(
                SERVICES
            ):
                _capture_fail("rendered Compose service hashes are incomplete")
            if any(not _sha256(digest) for digest in compose_hashes.values()):
                _capture_fail("rendered Compose service hash is invalid")
            if not isinstance(contract, dict):
                _capture_fail("validated configuration contract is invalid")
            artifacts = contract.get("artifacts_by_service")
            if not isinstance(artifacts, dict) or set(artifacts) != set(SERVICES):
                _capture_fail("immutable artifact reference set is incomplete")
            for service, references in artifacts.items():
                if (
                    not isinstance(references, list)
                    or not references
                    or len(references) != len(set(references))
                    or any(
                        not isinstance(reference, str)
                        or not IMMUTABLE_ARTIFACT_REF.fullmatch(reference)
                        for reference in references
                    )
                ):
                    _capture_fail("snapshot artifact reference is mutable or invalid")
                observed_image = runtime_before["services"][service]["image_reference"]
                if "oci://" + observed_image not in references:
                    _capture_fail(
                        "observed runtime image does not match immutable artifact reference"
                    )
            verify_artifacts(artifacts)
        except SnapshotCaptureError:
            raise
        except Exception:
            _capture_fail("captured configuration or artifacts failed verification")

        expected_config = contract.get("configuration_sha256_by_service")
        expected_runtime = contract.get("runtime_identity_sha256_by_service")
        if (
            not isinstance(expected_config, dict)
            or set(expected_config) != set(SERVICES)
            or not isinstance(expected_runtime, dict)
            or set(expected_runtime) != set(SERVICES)
            or contract.get("secret_versions_by_service")
            != {name: [] for name in SERVICES}
            or contract.get("required_optional_file_roles") != optional_roles
            or contract.get("selected_services") != list(SERVICES)
        ):
            _capture_fail(
                "configuration identity or secret-reference contract is invalid"
            )
        if any(not _sha256(value) for value in expected_config.values()) or any(
            not _sha256(value) for value in expected_runtime.values()
        ):
            _capture_fail("expected configuration identities are invalid")
        expected_images = contract.get("image_id_by_service")
        expected_platforms = contract.get("platform_by_service")
        if (
            not isinstance(expected_images, dict)
            or set(expected_images) != set(SERVICES)
            or not isinstance(expected_platforms, dict)
            or set(expected_platforms) != set(SERVICES)
            or any(
                not isinstance(value, str) or not IMAGE_ID.fullmatch(value)
                for value in expected_images.values()
            )
            or expected_platforms != {service: "linux/amd64" for service in SERVICES}
        ):
            _capture_fail("expected runtime image identities are invalid")
        observed_services = runtime_before["services"]
        for service in SERVICES:
            if (
                observed_services[service]["configuration_sha256"]
                != expected_config[service]
                or observed_services[service]["runtime_identity_sha256"]
                != expected_runtime[service]
                or observed_services[service]["image_id"] != expected_images[service]
                or compose_hashes[service]
                != observed_services[service]["compose_config_hash"]
            ):
                _capture_fail(
                    "captured configuration does not match fresh runtime identity"
                )
        if host_bindings_sha256(rendered) != contract.get("host_bindings_sha256"):
            _capture_fail(
                "captured Compose host bindings do not match validated configuration"
            )

        complete = {**locked_sources, **generated}
        snapshot_file_set = PROJECT_FILES | set(optional_roles)
        if set(complete) != snapshot_file_set:
            _capture_fail("captured snapshot file set is incomplete")
        files = {}
        for name in sorted(snapshot_file_set):
            content = complete[name]
            _validate_config_blob(name, content)
            digest = hashlib.sha256(content).hexdigest()
            files[name] = {
                "sha256": digest,
                "size_bytes": len(content),
                "classification": "non_secret_configuration",
            }
            _write_staged_file(stage, name, content)
            staged_content, _ = _source_bytes(stage / name, private=True)
            if (
                staged_content != content
                or hashlib.sha256(staged_content).hexdigest() != digest
            ):
                _capture_fail("staged configuration content failed digest verification")
        try:
            fsync_directory(stage)
        except OSError:
            _capture_fail("snapshot staging directory could not be synchronized")

        # Re-read every original source after staging; this detects manual edits
        # that do not honor the shared Compose project lock.
        final_sources, final_identities, final_tracked_ids = read_sources()
        if (
            final_sources != locked_sources
            or final_identities != locked_identities
            or final_tracked_ids != locked_tracked_ids
        ):
            _capture_fail("configuration changed during snapshot capture")
        try:
            runtime_after = collect_runtime()
        except Exception:
            _capture_fail("runtime freshness could not be revalidated")
        runtime_after_projection = _runtime_projection(
            runtime_after, project_name, maximum_runtime_age_seconds
        )
        if runtime_before_projection != runtime_after_projection:
            _capture_fail("runtime identity changed during snapshot capture")
        lock.assert_current()

        manifest = {
            "schema_version": 3,
            "project_name": project_name,
            "source_revision": tracked_source_revision,
            "source_git_blob_ids": locked_tracked_ids,
            "selected_services": list(SERVICES),
            "optional_file_roles": optional_roles,
            "files": files,
            "artifacts_by_service": {
                service: sorted(references) for service, references in artifacts.items()
            },
            "secret_versions_by_service": {service: [] for service in SERVICES},
            "rendered_compose_sha256": files["rendered-compose.json"]["sha256"],
            "compose_service_hashes": {
                service: observed_services[service]["compose_config_hash"]
                for service in SERVICES
            },
            "configuration_sha256_by_service": expected_config,
            "runtime_identity_sha256_by_service": {
                service: observed_services[service]["runtime_identity_sha256"]
                for service in SERVICES
            },
            "host_bindings_sha256": host_bindings_sha256(rendered),
            "docker_engine_version": runtime_before["docker_engine_version"],
            "compose_version": runtime_before["compose_version"],
        }
        raw_manifest = canonical_json(manifest)
        manifest_digest = hashlib.sha256(raw_manifest).hexdigest()

        # Immutable objects are published first. A failure can leave verified
        # orphan blobs or staging, but never an eligible manifest.
        for name, content in sorted(complete.items()):
            digest = files[name]["sha256"]
            blob_path = objects_hash / digest
            if blob_path.exists() or blob_path.is_symlink():
                existing = _secure_file(blob_path)
                if existing != content:
                    _capture_fail("existing content-addressed blob is corrupt")
                continue
            if before_publish is not None:
                before_publish("before_blob", name)
            try:
                publish_immutable_file(objects_hash, digest, content)
            except FileExistsError:
                if _secure_file(blob_path) != content:
                    _capture_fail("concurrent content-addressed blob conflicts")
            except OSError:
                _capture_fail("content-addressed blob publication failed")
            if before_publish is not None:
                before_publish("blob_published", name)

        snapshot_dir = snapshots_hash / manifest_digest
        if not snapshot_dir.exists():
            try:
                mkdir_private(snapshot_dir)
            except FileExistsError:
                pass
            except OSError:
                _capture_fail("snapshot manifest directory could not be created")
        _ensure_private_dir(snapshot_dir, create=False)
        manifest_path = snapshot_dir / "manifest.json"
        if manifest_path.exists() or manifest_path.is_symlink():
            if {item.name for item in snapshot_dir.iterdir()} != {"manifest.json"}:
                _capture_fail("snapshot directory contains unexpected entries")
            existing = _secure_file(manifest_path)
            if existing != raw_manifest:
                _capture_fail("existing immutable snapshot identity is corrupt")
            verify_retained_snapshot(
                root,
                "stt",
                manifest_digest,
                project_name=project_name,
                expected_artifacts_by_service={
                    service: set(refs) for service, refs in artifacts.items()
                },
            )
        else:
            if list(snapshot_dir.iterdir()):
                _capture_fail("snapshot publication directory is not empty")
            if before_publish is not None:
                before_publish("before_manifest", "manifest.json")
            try:
                publish_immutable_file(snapshot_dir, "manifest.json", raw_manifest)
            except FileExistsError:
                if _secure_file(manifest_path) != raw_manifest:
                    _capture_fail("concurrent snapshot identity conflicts")
            except OSError:
                _capture_fail("snapshot manifest activation failed")
            verify_retained_snapshot(
                root,
                "stt",
                manifest_digest,
                project_name=project_name,
                expected_artifacts_by_service={
                    service: set(refs) for service, refs in artifacts.items()
                },
            )
            if {item.name for item in snapshot_dir.iterdir()} != {"manifest.json"}:
                _capture_fail("snapshot directory contains unexpected entries")
        return {
            "project_name": project_name,
            "schema_version": 3,
            "snapshot_sha256": manifest_digest,
            "snapshot_reference": f"private://snapshots/sha256/{manifest_digest}",
            "staging_retained": True,
        }
    except SnapshotCaptureError:
        raise
    except Exception:
        _capture_fail("snapshot capture failed safely")
    finally:
        lock.release()


def _secure_file(
    path: Path, *, mode: int = 0o600, maximum: int = 16 * 1024 * 1024
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise ValueError("snapshot file is unavailable or unsafe") from error
    try:
        info = os.fstat(fd)
        current = path.lstat()
        try:
            attributes = os.listxattr(fd)
        except OSError as error:
            raise ValueError("snapshot file ACL state is unavailable") from error
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != mode
            or info.st_nlink != 1
            or any(name.startswith("system.posix_acl_") for name in attributes)
            or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)
            or info.st_size > maximum
        ):
            raise ValueError("snapshot file type, owner, link count or mode is invalid")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read(maximum + 1)
    finally:
        os.close(fd)


def _secure_dir(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError("snapshot directory is unavailable") from error
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("snapshot directory type, owner or mode is invalid")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            current = os.fstat(fd)
            attributes = os.listxattr(fd)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError("snapshot directory changed while opening")
            if any(name.startswith("system.posix_acl_") for name in attributes):
                raise ValueError("snapshot directory ACL is not allowed")
        finally:
            os.close(fd)
    except OSError as error:
        raise ValueError("snapshot directory ACL state is unavailable") from error


def _sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _require_private_ancestry(root: Path) -> None:
    parts = (root, *root.parents)
    private_index = next(
        (index for index, path in enumerate(parts) if path.name == "private"), None
    )
    if private_index is None or private_index < 3:
        raise ValueError("snapshot storage is not under a private deployment root")
    for path in parts[: private_index + 1]:
        if path.is_symlink():
            raise ValueError("snapshot storage contains a symlink component")
        _secure_dir(path)


def _validate_environment(values: object, *, persisted: bool) -> dict[str, str]:
    allowed = PERSISTED_ENV_KEYS if persisted else RENDER_ENV_KEYS
    if not isinstance(values, dict) or set(values) != set(allowed):
        raise ValueError("deployment environment keys do not match the allowlist")
    result: dict[str, str] = {}
    for key, value in values.items():
        if (
            not isinstance(value, str)
            or not value
            or any(c in value for c in "\x00\r\n$` ")
        ):
            raise ValueError("deployment environment value is invalid")
        if key in PATH_ENV_KEYS:
            path = PurePosixPath(value)
            if not path.is_absolute() or ".." in path.parts or str(path) != value:
                raise ValueError("deployment path binding is invalid")
            if key in PATH_ENV_BASENAMES and path.name != PATH_ENV_BASENAMES[key]:
                raise ValueError("deployment path does not match its logical role")
            if key == "STT_MODEL_HOST_ROOT" and not SHA256.fullmatch(path.name):
                raise ValueError("model host binding is not manifest-addressed")
        elif key in IMAGE_ENV_KEYS:
            if not (
                IMAGE_REF.fullmatch(value)
                or (key == "STT_CUDA_IMAGE" and IMAGE_ID.fullmatch(value))
            ):
                raise ValueError("deployment image reference is not immutable")
        elif key in IMAGE_ID_KEYS:
            if not IMAGE_ID.fullmatch(value):
                raise ValueError("deployment image identity is invalid")
        elif key in DIGEST_ENV_KEYS:
            if not SHA256.fullmatch(value):
                raise ValueError("deployment digest reference is invalid")
        elif key in REVISION_ENV_KEYS:
            if not REVISION.fullmatch(value):
                raise ValueError("deployment revision reference is invalid")
        elif key in INTEGER_ENV_KEYS:
            if not re.fullmatch(r"[0-9]+", value):
                raise ValueError("deployment integer value is invalid")
        elif key in NUMBER_ENV_KEYS:
            if not NUMBER.fullmatch(value):
                raise ValueError("deployment numeric value is invalid")
        elif key in MEMORY_ENV_KEYS:
            if not MEMORY.fullmatch(value):
                raise ValueError("deployment memory value is invalid")
        elif key in PROJECT_ENV_KEYS:
            if not PROJECT_NAME.fullmatch(value):
                raise ValueError("deployment project identity is invalid")
        elif key == "SPEECH_BIND_IP":
            try:
                address = ipaddress.ip_address(value)
            except ValueError as error:
                raise ValueError("deployment bind address is invalid") from error
            if not address.is_loopback:
                raise ValueError("deployment bind address is not loopback")
        elif key == "STT_IMAGE_IDENTITY_MODE":
            if value not in {"registry_digest", "local_image_id"}:
                raise ValueError("deployment image identity mode is invalid")
        elif key == "STT_PLATFORM":
            if value != "linux/amd64":
                raise ValueError("deployment image platform is unsupported")
        elif key in {"GATEWAY_PIDS", "TTS_PIDS"}:
            if not re.fullmatch(r"[0-9]+", value):
                raise ValueError("deployment process limit is invalid")
        elif key == "STT_CUDA_IMAGE":
            raise ValueError("deployment image reference is invalid")
        result[key] = value
    return result


def _decode_env_file(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("deployment environment file is not UTF-8") from error
    values: dict[str, str] = {}
    keys = []
    if not text.endswith("\n"):
        raise ValueError("deployment environment file is not newline terminated")
    for line in text.splitlines():
        if not line:
            raise ValueError("deployment environment file contains a blank line")
        key, separator, encoded_value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise ValueError("deployment environment file syntax is invalid")
        try:
            value = json.loads(encoded_value)
        except json.JSONDecodeError as error:
            raise ValueError(
                "deployment environment file quoting is invalid"
            ) from error
        if not isinstance(value, str):
            raise ValueError("deployment environment value is invalid")
        if encoded_value != json.dumps(value):
            raise ValueError("deployment environment value encoding is not canonical")
        values[key] = value
        keys.append(key)
    if keys != sorted(keys):
        raise ValueError("deployment environment keys are not canonically ordered")
    return values


def _check_forbidden_content(name: str, raw: bytes) -> None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("configuration snapshot contains non-text content") from error
    if FORBIDDEN_CONTENT.search(text):
        raise ValueError(f"forbidden sensitive content in configuration role: {name}")


def _validate_config_blob(name: str, raw: bytes) -> None:
    _check_forbidden_content(name, raw)
    if name == "compose.env":
        _validate_environment(_decode_env_file(raw), persisted=True)
    elif name == "render-environment.json":
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("render environment JSON is invalid") from error
        if canonical_json(value) != raw:
            raise ValueError("render environment JSON is not canonical")
        _validate_environment(value, persisted=False)
    elif name == "rendered-compose.json":
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("rendered Compose JSON is invalid") from error
        if canonical_json(value) != raw:
            raise ValueError("rendered Compose JSON is not canonical")
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("services"), dict)
            or set(value["services"]) != set(SERVICES)
        ):
            raise ValueError("rendered Compose service set is incomplete")


def host_bindings_sha256(rendered_compose: dict) -> str:
    """Hash normalized bind sources and targets without exposing their paths."""
    services = rendered_compose.get("services")
    if not isinstance(services, dict) or set(services) != set(SERVICES):
        raise ValueError("rendered Compose service set is incomplete")
    bindings = {}
    for service in SERVICES:
        definition = services[service]
        if not isinstance(definition, dict):
            raise ValueError("rendered Compose service definition is invalid")
        volumes = definition.get("volumes", [])
        if not isinstance(volumes, list):
            raise ValueError("rendered Compose mounts are invalid")
        service_bindings = []
        for volume in volumes:
            if not isinstance(volume, dict) or volume.get("type") != "bind":
                raise ValueError("snapshot may contain only approved bind mounts")
            source = volume.get("source")
            target = volume.get("target")
            if (
                not isinstance(source, str)
                or not source.startswith("/")
                or ".." in PurePosixPath(source).parts
                or not isinstance(target, str)
                or not target.startswith("/")
                or ".." in PurePosixPath(target).parts
                or volume.get("read_only") is not True
            ):
                raise ValueError("snapshot bind source or target is invalid")
            service_bindings.append(
                {"source": source, "target": target, "read_only": True}
            )
        bindings[service] = sorted(service_bindings, key=lambda item: item["target"])
    return hashlib.sha256(canonical_json(bindings)).hexdigest()


def verify_retained_snapshot(
    root: Path,
    service: str,
    digest: str,
    *,
    project_name: str,
    expected_artifacts_by_service: dict[str, set[str]] | None = None,
) -> dict:
    """Verify the full project snapshot and every content-addressed config blob."""
    if (
        service not in SERVICES
        or not PROJECT_NAME.fullmatch(project_name)
        or not SHA256.fullmatch(digest)
    ):
        raise ValueError("snapshot identity is invalid")
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("snapshot root type is invalid")
    _require_private_ancestry(root)
    snapshots_hash = root / "snapshots" / "sha256"
    objects_hash = root / "objects" / "sha256"
    for path in (root / "snapshots", snapshots_hash, root / "objects", objects_hash):
        _secure_dir(path)
    directory = snapshots_hash / digest
    _secure_dir(directory)
    raw = _secure_file(directory / "manifest.json")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("snapshot manifest digest does not match its reference")
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("snapshot manifest is invalid") from error
    if canonical_json(manifest) != raw:
        raise ValueError("snapshot manifest is not canonical JSON")
    if (
        not isinstance(manifest, dict)
        or set(manifest) != MANIFEST_FIELDS
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 3
        or manifest["project_name"] != project_name
        or not isinstance(manifest["source_revision"], str)
        or not REVISION.fullmatch(manifest["source_revision"])
        or not isinstance(manifest["source_git_blob_ids"], dict)
        or set(manifest["source_git_blob_ids"]) != set(TRACKED_SOURCE_FILES)
        or any(
            not isinstance(value, str) or not REVISION.fullmatch(value)
            for value in manifest["source_git_blob_ids"].values()
        )
        or manifest["selected_services"] != list(SERVICES)
        or not isinstance(manifest["files"], dict)
        or not isinstance(manifest["optional_file_roles"], list)
        or not all(isinstance(role, str) for role in manifest["optional_file_roles"])
        or manifest["optional_file_roles"]
        != sorted(set(manifest["optional_file_roles"]))
        or set(manifest["optional_file_roles"]) - OPTIONAL_ARTIFACT_EVIDENCE_FILES
        or set(manifest["files"])
        != PROJECT_FILES | set(manifest["optional_file_roles"])
        or not isinstance(manifest["artifacts_by_service"], dict)
        or set(manifest["artifacts_by_service"]) != set(SERVICES)
        or not isinstance(manifest["secret_versions_by_service"], dict)
        or set(manifest["secret_versions_by_service"]) != set(SERVICES)
        or not isinstance(manifest["compose_service_hashes"], dict)
        or set(manifest["compose_service_hashes"]) != set(SERVICES)
        or not isinstance(manifest["configuration_sha256_by_service"], dict)
        or set(manifest["configuration_sha256_by_service"]) != set(SERVICES)
        or not isinstance(manifest["runtime_identity_sha256_by_service"], dict)
        or set(manifest["runtime_identity_sha256_by_service"]) != set(SERVICES)
        or not _sha256(manifest["rendered_compose_sha256"])
        or not _sha256(manifest["host_bindings_sha256"])
        or not isinstance(manifest["docker_engine_version"], str)
        or not TOOL_VERSION.fullmatch(manifest["docker_engine_version"])
        or not isinstance(manifest["compose_version"], str)
        or not TOOL_VERSION.fullmatch(manifest["compose_version"])
    ):
        raise ValueError("snapshot manifest schema or project inputs are incomplete")
    if any(not _sha256(value) for value in manifest["compose_service_hashes"].values()):
        raise ValueError("snapshot Compose service identity is invalid")
    if any(
        not _sha256(value)
        for value in manifest["configuration_sha256_by_service"].values()
    ):
        raise ValueError("snapshot configuration identity is invalid")
    if any(
        not _sha256(value)
        for value in manifest["runtime_identity_sha256_by_service"].values()
    ):
        raise ValueError("snapshot runtime identity is invalid")
    for name, refs in manifest["secret_versions_by_service"].items():
        if not isinstance(refs, list) or refs:
            raise ValueError(
                "secret restoration references require an approved resolver"
            )
    for name, refs in manifest["artifacts_by_service"].items():
        if (
            not isinstance(refs, list)
            or not refs
            or any(
                not isinstance(ref, str) or not IMMUTABLE_ARTIFACT_REF.fullmatch(ref)
                for ref in refs
            )
            or len(refs) != len(set(refs))
        ):
            raise ValueError("snapshot artifact references are not immutable")
    if expected_artifacts_by_service is not None and manifest[
        "artifacts_by_service"
    ] != {name: sorted(refs) for name, refs in expected_artifacts_by_service.items()}:
        raise ValueError("snapshot artifacts do not match the pinned release")
    verified_blobs: dict[str, bytes] = {}
    for name, identity in manifest["files"].items():
        if not isinstance(identity, dict) or set(identity) != FILE_IDENTITY_FIELDS:
            raise ValueError("snapshot file identity schema is invalid")
        if identity["classification"] != "non_secret_configuration":
            raise ValueError("snapshot file classification is not allowed")
        blob_digest = identity["sha256"]
        if (
            not isinstance(blob_digest, str)
            or not SHA256.fullmatch(blob_digest)
            or type(identity["size_bytes"]) is not int
            or identity["size_bytes"] < 0
        ):
            raise ValueError("snapshot file identity is invalid")
        blob = _secure_file(objects_hash / blob_digest)
        if (
            len(blob) != identity["size_bytes"]
            or hashlib.sha256(blob).hexdigest() != blob_digest
        ):
            raise ValueError(f"snapshot file content verification failed: {name}")
        _validate_config_blob(name, blob)
        verified_blobs[name] = blob
    if (
        hashlib.sha256(verified_blobs["rendered-compose.json"]).hexdigest()
        != manifest["rendered_compose_sha256"]
    ):
        raise ValueError("snapshot rendered Compose digest does not match")
    rendered = json.loads(verified_blobs["rendered-compose.json"])
    render_environment = json.loads(verified_blobs["render-environment.json"])
    persisted_environment = _decode_env_file(verified_blobs["compose.env"])
    if any(
        render_environment[key] != persisted_environment[key]
        for key in PERSISTED_ENV_KEYS
    ):
        raise ValueError(
            "snapshot rendered environment does not match persisted config"
        )
    _validate_rendered_mounts(rendered, render_environment)
    if host_bindings_sha256(rendered) != manifest["host_bindings_sha256"]:
        raise ValueError(
            "snapshot host binding digest does not match the rendered Compose"
        )
    if (
        expected_artifacts_by_service is not None
        and service not in expected_artifacts_by_service
    ):
        raise ValueError("snapshot service is not selected")
    return manifest
