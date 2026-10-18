"""Fail-closed validation and Compose environment generation for CUDA STT."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from services.stt.artifacts import verify_artifact
from services.stt.config import (
    ArtifactRoot,
    StrictLoader,
    load_application_config,
    load_deployment_config,
)
from services.stt.domain import SpeechFailure
from services.worker.server import load_config

PROFILE_FIELDS = {
    "schema_version",
    "project_name",
    "runtime",
    "model",
    "device",
    "artifact_access",
    "resources",
    "lifecycle",
    "healthcheck",
}

# Local Docker image IDs in Compose were create-tested only on this exact pair.
LOCAL_IMAGE_ID_ENGINE_VERSIONS = frozenset({"29.7.2-ce"})
LOCAL_IMAGE_ID_COMPOSE_VERSIONS = frozenset({"5.6.0"})


def _fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"{label} fields do not match the deployment schema")


def _read_yaml(path):
    try:
        value = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=StrictLoader)
    except (OSError, yaml.YAMLError, ValueError, TypeError) as exc:
        raise ValueError("deployment input is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("deployment input root must be a mapping")
    return value


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest_reference(value, label):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:/-]+@sha256:[0-9a-f]{64}", value
    ):
        raise ValueError(f"{label} must be an immutable sha256 image reference")
    return value


def _image_id(value, label="runtime.image_id"):
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError(f"{label} must be an exact Docker sha256 image ID")
    return value


def validate_local_image_build_evidence(runtime, evidence, evidence_path):
    """Bind the private build record to the local-image identity in the profile."""
    if _sha256(evidence_path) != runtime["build_evidence_sha256"]:
        raise ValueError("production image build evidence digest does not match")
    if not isinstance(evidence, dict) or evidence.get("status") != (
        "BUILD_SUCCEEDED_IMAGE_NOT_RUN"
    ):
        raise ValueError("production image build evidence is incomplete")
    image = evidence.get("image")
    base = evidence.get("base")
    labels = image.get("labels") if isinstance(image, dict) else None
    if not isinstance(labels, dict) or not isinstance(base, dict):
        raise ValueError("production image build evidence is incomplete")
    base_digest = runtime["base_image"].rsplit("@", 1)[-1]
    expected = (
        evidence.get("source_commit") == runtime["source_revision"],
        evidence.get("dependency_lock_sha256") == runtime["cuda_lock_sha256"],
        image.get("id") == runtime["image_id"],
        image.get("platform") == runtime["platform"],
        base.get("platform") == runtime["base_image_platform"],
        base.get("platform_manifest_digest") == base_digest,
        labels.get("org.opencontainers.image.revision") == runtime["source_revision"],
        labels.get("com.speech-platform.source-revision") == runtime["source_revision"],
        labels.get("com.speech-platform.image-role") == "stt-worker",
        labels.get("com.speech-platform.base-image") == runtime["base_image"],
        labels.get("com.speech-platform.cuda-lock-sha256")
        == runtime["cuda_lock_sha256"],
    )
    if not all(expected):
        raise ValueError("production image build evidence conflicts with profile")


def validate_local_image_inspection(runtime, inspection):
    """Compare read-only Docker inspection output to validated build identity."""
    if not isinstance(inspection, list) or len(inspection) != 1:
        raise ValueError("Docker image inspection did not return exactly one image")
    image = inspection[0]
    config = image.get("Config") if isinstance(image, dict) else None
    if not isinstance(config, dict):
        raise ValueError("Docker image configuration is unavailable")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict):
        raise ValueError("Docker image provenance labels are unavailable")
    expected = (
        image.get("Id") == runtime["image_id"],
        image.get("Os") == "linux",
        image.get("Architecture") == "amd64",
        config.get("User") == "65532:65532",
        config.get("Entrypoint") == ["python", "-m"],
        labels.get("org.opencontainers.image.revision") == runtime["source_revision"],
        labels.get("com.speech-platform.source-revision") == runtime["source_revision"],
        labels.get("com.speech-platform.image-role") == "stt-worker",
        labels.get("com.speech-platform.base-image") == runtime["base_image"],
        labels.get("com.speech-platform.cuda-lock-sha256")
        == runtime["cuda_lock_sha256"],
    )
    if not all(expected):
        raise ValueError("local Docker image identity or provenance mismatch")


def validate_created_container_inspection(expected_image_id, inspection):
    """Require the exact image ID on a stopped, newly created container."""
    _image_id(expected_image_id, "expected image ID")
    if not isinstance(inspection, list) or len(inspection) != 1:
        raise ValueError("Docker container inspection did not return exactly one item")
    container = inspection[0]
    if not isinstance(container, dict):
        raise ValueError("Docker container inspection is invalid")
    state = container.get("State") if isinstance(container, dict) else None
    if (
        container.get("Image") != expected_image_id
        or not isinstance(state, dict)
        or state.get("Status") != "created"
        or state.get("Running") is not False
    ):
        raise ValueError("created container image identity or state mismatch")


def validate_local_image_runtime_versions(engine_version, compose_version):
    if engine_version not in LOCAL_IMAGE_ID_ENGINE_VERSIONS:
        raise ValueError("unsupported Docker Engine version for local image ID mode")
    if compose_version not in LOCAL_IMAGE_ID_COMPOSE_VERSIONS:
        raise ValueError("unsupported Docker Compose version for local image ID mode")


def _docker_read(args):
    try:
        result = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("read-only Docker inspection could not be started") from exc
    if result.returncode != 0:
        raise ValueError("read-only Docker inspection failed")
    return result.stdout.strip()


def verify_local_image_runtime_with_docker():
    validate_local_image_runtime_versions(
        _docker_read(["docker", "info", "--format", "{{.ServerVersion}}"]),
        _docker_read(["docker", "compose", "version", "--short"]),
    )


def verify_local_image_with_docker(runtime):
    verify_local_image_runtime_with_docker()
    try:
        inspection = json.loads(
            _docker_read(["docker", "image", "inspect", runtime["image_id"]])
        )
    except json.JSONDecodeError as exc:
        raise ValueError("Docker image inspection returned invalid data") from exc
    validate_local_image_inspection(runtime, inspection)


def verify_created_container_with_docker(container_id, expected_image_id):
    if not isinstance(container_id, str) or not re.fullmatch(
        r"[0-9a-f]{64}", container_id
    ):
        raise ValueError("container ID must be a full hexadecimal Docker ID")
    try:
        inspection = json.loads(
            _docker_read(["docker", "container", "inspect", container_id])
        )
    except json.JSONDecodeError as exc:
        raise ValueError("Docker container inspection returned invalid data") from exc
    validate_created_container_inspection(expected_image_id, inspection)


def _positive_number(value, label, maximum):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if value <= 0 or value > maximum:
        raise ValueError(f"{label} is outside the supported range")
    return value


def _reject_placeholders(value):
    if isinstance(value, dict):
        for nested in value.values():
            _reject_placeholders(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_placeholders(nested)
    elif isinstance(value, str) and "REPLACE_WITH_" in value:
        raise ValueError("deployment profile still contains replacement values")


def _assert_no_acl(path: Path, *, directory: bool):
    if not hasattr(os, "getxattr"):
        raise ValueError("POSIX ACL inspection is unavailable")
    attributes = ["system.posix_acl_access"]
    if directory:
        attributes.append("system.posix_acl_default")
    for attribute in attributes:
        try:
            os.getxattr(path, attribute, follow_symlinks=False)
        except OSError as exc:
            if exc.errno in {errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP}:
                continue
            raise ValueError("ACL policy cannot be verified") from exc
        else:
            raise ValueError("path must not use POSIX ACLs")


def _mode_for_identity(info, service_uid: int, service_gids: set[int]):
    mode = stat.S_IMODE(info.st_mode)
    if info.st_uid == service_uid:
        return (mode >> 6) & 0o7
    if info.st_gid in service_gids:
        return (mode >> 3) & 0o7
    return mode & 0o7


def _group_access(path: Path, expected_gid: int, expected_uid: int, *, directory: bool):
    info = path.lstat()
    if (
        stat.S_ISLNK(info.st_mode)
        or info.st_gid != expected_gid
        or info.st_uid != expected_uid
    ):
        raise ValueError("model release ownership or symlink policy is invalid")
    _assert_no_acl(path, directory=directory)
    mode = stat.S_IMODE(info.st_mode)
    group_required = 0o050 if directory else 0o040
    owner_required = 0o700 if directory else 0o600
    if (
        (mode & owner_required) != owner_required
        or (mode & group_required) != group_required
        or mode & 0o027
        or mode & 0o007
        or (directory and not mode & stat.S_ISGID)
        or mode & stat.S_ISUID
        or (not directory and mode & (stat.S_ISGID | stat.S_ISVTX))
        or (directory and mode & stat.S_ISVTX)
    ):
        raise ValueError("model release group access is insufficient or too broad")
    if directory and not stat.S_ISDIR(info.st_mode):
        raise ValueError("model release contains a non-directory path")
    if not directory and not stat.S_ISREG(info.st_mode):
        raise ValueError("model release contains a non-regular file")


def validate_model_permissions(
    release_root,
    manifest_file,
    expected_gid: int,
    expected_owner_uid: int,
    service_uid: int = 65532,
    service_gid: int = 65532,
):
    root = Path(release_root)
    try:
        normalized_root = root.resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            "model release root must be an existing absolute directory"
        ) from exc
    if (
        not root.is_absolute()
        or root != normalized_root
        or root.is_symlink()
        or not root.is_dir()
    ):
        raise ValueError("model release root must be an existing absolute directory")
    _group_access(root, expected_gid, expected_owner_uid, directory=True)

    # The container must be able to traverse each host-side parent to reach
    # the read-only bind mount. Evaluate DAC permissions for the configured
    # service identity and supplementary artifact group without impersonation.
    service_gids = {service_gid, expected_gid}
    for parent in root.parents:
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("model release parent path contains an unsafe entry")
        _assert_no_acl(parent, directory=True)
        permissions = _mode_for_identity(info, service_uid, service_gids)
        mode = stat.S_IMODE(info.st_mode)
        sticky_tmp = (
            info.st_uid == 0 and bool(mode & stat.S_ISVTX) and bool(mode & 0o002)
        )
        if (
            not permissions & 0o1
            or (permissions & 0o2 and not sticky_tmp)
            or (mode & 0o002 and not sticky_tmp)
        ):
            raise ValueError("model release parent is not traversable by worker")

    manifest = Path(manifest_file)
    if manifest.parent != root or not manifest.is_file():
        raise ValueError("model manifest must be a regular file in the release root")
    _group_access(manifest, expected_gid, expected_owner_uid, directory=False)

    def fail_walk(error):
        raise ValueError("model release tree cannot be completely inspected") from error

    for current, directories, files in os.walk(
        root, followlinks=False, onerror=fail_walk
    ):
        current_path = Path(current)
        for name in directories:
            _group_access(
                current_path / name,
                expected_gid,
                expected_owner_uid,
                directory=True,
            )
        for name in files:
            _group_access(
                current_path / name,
                expected_gid,
                expected_owner_uid,
                directory=False,
            )


def configuration_set_sha256(
    profile_path,
    application_path,
    deployment_path,
    worker_path,
    compose_base_path="deployments/compose/compose.yaml",
    compose_cuda_path="deployments/compose/compose.stt-cuda.yaml",
    build_evidence_path=None,
):
    inputs = {
        "application": application_path,
        "compose_base": compose_base_path,
        "compose_cuda": compose_cuda_path,
        "deployment": deployment_path,
        "profile": profile_path,
        "worker": worker_path,
    }
    identities = {
        role: {"path": str(Path(path).resolve()), "sha256": _sha256(path)}
        for role, path in inputs.items()
    }
    if build_evidence_path is not None:
        identities["image_build_evidence"] = {
            "path": str(Path(build_evidence_path).resolve()),
            "sha256": _sha256(build_evidence_path),
        }
    canonical = json.dumps(identities, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def require_private_config_paths(paths, repository_root="."):
    root = Path(repository_root).resolve()
    private_root = root / "private"
    if private_root.is_symlink() or not private_root.is_dir():
        raise ValueError("private configuration directory is unavailable")
    _assert_no_acl(private_root, directory=True)
    if private_root.stat().st_mode & 0o077:
        raise ValueError("private configuration directory permissions are too broad")
    resolved_private = private_root.resolve()
    for value in paths:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(resolved_private)
        except ValueError as exc:
            raise ValueError("deployment configuration must be under private/") from exc
        if candidate.name.endswith(".example.yaml") or not resolved.is_file():
            raise ValueError(
                "deployment configuration must be an explicit private file"
            )
        if candidate.is_symlink():
            raise ValueError("private configuration inputs must not be symlinks")
        _assert_no_acl(resolved, directory=False)
        if resolved.stat().st_mode & 0o077:
            raise ValueError("private configuration file permissions are too broad")
        parent = candidate.parent
        while parent.resolve() != resolved_private:
            if (
                parent.is_symlink()
                or not parent.is_dir()
                or parent.stat().st_mode & 0o077
            ):
                raise ValueError(
                    "private configuration directory permissions are too broad"
                )
            _assert_no_acl(parent, directory=True)
            try:
                parent.resolve().relative_to(resolved_private)
            except ValueError as exc:
                raise ValueError(
                    "deployment configuration must be under private/"
                ) from exc
            if parent == parent.parent:
                raise ValueError("deployment configuration must be under private/")
            parent = parent.parent


def _container_model_path(value, label):
    if not isinstance(value, str) or not value.startswith("/models/"):
        raise ValueError(f"{label} must be inside the read-only /models mount")
    path = Path(value)
    if ".." in path.parts or path.as_posix() != value:
        raise ValueError(f"{label} must be a normalized container path")
    return path


def load_and_validate(
    profile_path,
    application_config_path,
    deployment_config_path,
    worker_config_path,
    *,
    lock_path="services/requirements-stt-cuda.lock",
    dockerfile_path="deployments/compose/worker-stt-cuda.Dockerfile",
    build_evidence_path=None,
    verify_files=True,
):
    profile_path = Path(profile_path)
    profile = _read_yaml(profile_path)
    _fields(profile, PROFILE_FIELDS, "deployment profile")
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ValueError("unsupported deployment profile schema")
    _reject_placeholders(profile)
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", profile["project_name"]):
        raise ValueError("Compose project name is invalid")

    runtime = profile["runtime"]
    if not isinstance(runtime, dict):
        raise ValueError("runtime must be a mapping")
    # Validate the base reference before local evidence comparison, which
    # derives its digest from this value. Malformed input must fail through the
    # deployment validator rather than leaking an incidental attribute error.
    base_image = _digest_reference(runtime.get("base_image"), "runtime.base_image")
    identity_mode = runtime.get("identity_mode")
    common_runtime_fields = {
        "identity_mode",
        "image_role",
        "platform",
        "base_image",
        "base_image_platform",
        "base_image_platform_verified",
        "cuda_lock_sha256",
        "source_revision",
        "source_revision_verified",
    }
    if identity_mode == "registry_digest":
        _fields(
            runtime,
            common_runtime_fields | {"image", "image_id", "image_reference_verified"},
            "runtime",
        )
        image = _digest_reference(runtime["image"], "runtime.image")
        if any(token in image.lower() for token in ("validation", "probe")):
            raise ValueError(
                "validation-only image references cannot be production workers"
            )
        image_id = _image_id(runtime["image_id"])
        if runtime["image_reference_verified"] is not True:
            raise ValueError(
                "built image reference must be verified against its image ID"
            )
    elif identity_mode == "local_image_id":
        _fields(
            runtime,
            common_runtime_fields | {"image_id", "build_evidence_sha256"},
            "runtime",
        )
        image_id = _image_id(runtime["image_id"])
        image = image_id
        evidence_digest = runtime["build_evidence_sha256"]
        if not isinstance(evidence_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", evidence_digest
        ):
            raise ValueError("local image mode requires a build evidence SHA-256")
        if build_evidence_path is None:
            raise ValueError("local image mode requires private build evidence")
        try:
            evidence = json.loads(Path(build_evidence_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                "local image build evidence is unavailable or invalid"
            ) from exc
        validate_local_image_build_evidence(runtime, evidence, build_evidence_path)
    else:
        raise ValueError(
            "runtime.identity_mode must be registry_digest or local_image_id"
        )
    if runtime["image_role"] != "stt-worker":
        raise ValueError(
            "runtime image must be identified as the production STT worker"
        )
    if image_id == (
        "sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540"
    ):
        raise ValueError(
            "CUDA validation image cannot be used as the production worker"
        )
    if runtime["platform"] != "linux/amd64":
        raise ValueError("deployment platform must be linux/amd64")
    if (
        runtime["base_image_platform"] != runtime["platform"]
        or runtime["base_image_platform_verified"] is not True
    ):
        raise ValueError(
            "base image linux/amd64 manifest identity requires operator verification"
        )
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", runtime["source_revision"]):
        raise ValueError("production application source revision must be immutable")
    if runtime["source_revision_verified"] is not True:
        raise ValueError("production application source revision must be verified")
    if not base_image.startswith("python:3.13.9-slim@sha256:"):
        raise ValueError("CUDA base image must retain the approved Python version")
    if not re.fullmatch(r"[0-9a-f]{64}", runtime["cuda_lock_sha256"]):
        raise ValueError("CUDA lock identity must be a SHA-256 digest")
    lock_digest = _sha256(lock_path)
    if lock_digest != runtime["cuda_lock_sha256"]:
        raise ValueError("CUDA dependency lock identity does not match")
    dockerfile = Path(dockerfile_path).read_text(encoding="utf-8")
    stt_entrypoint = Path("services/stt/main.py")
    if not stt_entrypoint.is_file() or any(
        fragment not in stt_entrypoint.read_text(encoding="utf-8")
        for fragment in (
            "from services.worker.server import main",
            'main("stt")',
        )
    ):
        raise ValueError("production STT module entrypoint is unavailable")
    required_dockerfile_fragments = (
        "ARG STT_CUDA_BASE_IMAGE",
        "FROM ${STT_CUDA_BASE_IMAGE}",
        "COPY services/requirements-stt-cuda.lock ./requirements.lock",
        "--require-hashes -r requirements.lock",
        "ENV LD_LIBRARY_PATH=/usr/local/lib/python3.13/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.13/site-packages/nvidia/cuda_nvrtc/lib:/usr/local/lib/python3.13/site-packages/nvidia/cudnn/lib",
        'ENTRYPOINT ["python", "-m"]',
        "USER 65532:65532",
        "org.opencontainers.image.revision=${STT_SOURCE_REVISION}",
        'com.speech-platform.image-role="stt-worker"',
        "com.speech-platform.base-image=${STT_CUDA_BASE_IMAGE}",
        "com.speech-platform.source-revision=${STT_SOURCE_REVISION}",
        "com.speech-platform.cuda-lock-sha256=${STT_CUDA_LOCK_SHA256}",
    )
    if any(fragment not in dockerfile for fragment in required_dockerfile_fragments):
        raise ValueError("CUDA Dockerfile does not define the production STT image")
    copy_instructions = [
        line.strip()
        for line in dockerfile.splitlines()
        if line.strip().upper().startswith(("COPY ", "ADD "))
    ]
    if copy_instructions != [
        "COPY services/requirements-stt-cuda.lock ./requirements.lock",
        "COPY services/stt ./services/stt",
        "COPY services/worker ./services/worker",
    ]:
        raise ValueError("CUDA image may copy only the lock and production source")
    lowered_dockerfile = dockerfile.lower()
    if any(
        marker in lowered_dockerfile
        for marker in (
            "huggingface-cli download",
            "hf download",
            "snapshot_download",
            "from_pretrained(",
            "curl ",
            "wget ",
        )
    ):
        raise ValueError("CUDA image must not download models or runtime artifacts")
    if (
        "/opt/validation/probe.py" in dockerfile
        or "COPY private" in dockerfile
        or "COPY models" in dockerfile
        or "huggingface-cli download" in dockerfile
        or "hf download" in dockerfile
    ):
        raise ValueError(
            "CUDA production image contains validation or private artifacts"
        )
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8")
    if any(
        pattern not in dockerignore
        for pattern in ("/private", "/secrets", "/credentials", "*.bin", "*.m4a")
    ):
        raise ValueError("Docker build context must exclude private/model/audio data")

    model = profile["model"]
    _fields(
        model,
        {
            "alias",
            "revision",
            "manifest_sha256",
            "host_release_root",
            "container_artifact_directory",
            "container_manifest_path",
        },
        "model",
    )
    if not isinstance(model["alias"], str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*", model["alias"]
    ):
        raise ValueError("model alias is invalid")
    if not isinstance(model["revision"], str) or not re.fullmatch(
        r"(?:[0-9a-f]{40}|[0-9a-f]{64})", model["revision"]
    ):
        raise ValueError("model revision must be immutable")
    if not isinstance(model["manifest_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", model["manifest_sha256"]
    ):
        raise ValueError("model manifest identity must be a SHA-256 digest")
    if not isinstance(model["host_release_root"], str):
        raise ValueError("model release root must be an explicit host path")
    host_release_root = Path(model["host_release_root"])
    artifact_directory = _container_model_path(
        model["container_artifact_directory"], "artifact directory"
    )
    manifest_path = _container_model_path(
        model["container_manifest_path"], "manifest path"
    )

    device = profile["device"]
    _fields(
        device,
        {"host_physical_index", "expected_host_uuid", "container_cuda_index"},
        "device",
    )
    if (
        type(device["host_physical_index"]) is not int
        or device["host_physical_index"] != 0
    ):
        raise ValueError("deployment must select host physical GPU 0")
    if (
        type(device["container_cuda_index"]) is not int
        or device["container_cuda_index"] != 0
    ):
        raise ValueError("single-device CUDA container index must be 0")
    if not isinstance(device["expected_host_uuid"], str) or not re.fullmatch(
        r"GPU-[0-9a-fA-F-]{16,}", device["expected_host_uuid"]
    ):
        raise ValueError("expected host GPU UUID must be verified before deployment")

    access = profile["artifact_access"]
    _fields(
        access,
        {
            "service_uid",
            "service_gid",
            "supplementary_read_gid",
            "artifact_owner_uid",
        },
        "artifact_access",
    )
    if access["service_uid"] != 65532 or access["service_gid"] != 65532:
        raise ValueError("CUDA worker identity must match the non-root image user")
    read_gid = access["supplementary_read_gid"]
    if type(read_gid) is not int or not 1 <= read_gid < 2**32 - 1 or read_gid == 65532:
        raise ValueError("artifact read group must be an explicit non-root group")
    owner_uid = access["artifact_owner_uid"]
    if (
        type(owner_uid) is not int
        or not 0 <= owner_uid < 2**32 - 1
        or owner_uid == 65532
    ):
        raise ValueError("artifact owner UID must be explicit and distinct from worker")
    if host_release_root.name != model["manifest_sha256"]:
        raise ValueError("model release directory must be named by its manifest digest")

    app = load_application_config(application_config_path)
    deployment = load_deployment_config(deployment_config_path)
    worker = load_config(worker_config_path, "stt")
    if app.device_mode != "cuda" or app.device_preference != ("cuda",):
        raise ValueError(
            "CUDA deployment requires an explicit CUDA-only application policy"
        )
    if (
        app.backend_id != "faster-whisper"
        or dict(app.backend_options).get("compute_type_cuda") != "float16"
    ):
        raise ValueError(
            "deployment must use the approved faster-whisper CUDA float16 profile"
        )
    if app.default_model != model["alias"]:
        raise ValueError("deployment model alias must match the application default")
    selected = [entry for entry in app.models if entry.alias == model["alias"]]
    if len(selected) != 1:
        raise ValueError("deployment model alias is not uniquely configured")
    selected = selected[0]
    if (
        selected.identity.upstream_revision != model["revision"]
        or selected.manifest_sha256 != model["manifest_sha256"]
    ):
        raise ValueError(
            "deployment model identity does not match the application config"
        )
    if deployment.cuda_device_index != device["container_cuda_index"]:
        raise ValueError(
            "worker CUDA index does not match the exposed container device"
        )
    artifact = deployment.artifact_roots.get(selected.artifact_ref)
    if (
        artifact is None
        or artifact.directory != artifact_directory
        or artifact.manifest != manifest_path
    ):
        raise ValueError(
            "deployment artifact paths do not match the read-only mount profile"
        )
    if worker["listen_host"] not in {"0.0.0.0", "::"}:
        raise ValueError(
            "private container worker must listen on its container interface"
        )

    resources = profile["resources"]
    _fields(
        resources,
        {"cpu_limit", "memory_limit_bytes", "pids_limit", "limits_reviewed"},
        "resources",
    )
    _positive_number(resources["cpu_limit"], "cpu_limit", 32)
    if (
        type(resources["memory_limit_bytes"]) is not int
        or not 1024**3 <= resources["memory_limit_bytes"] <= 64 * 1024**3
    ):
        raise ValueError("memory limit must be an explicit 1..64 GiB byte value")
    if (
        type(resources["pids_limit"]) is not int
        or not 16 <= resources["pids_limit"] <= 4096
    ):
        raise ValueError("PID limit must be an explicit 16..4096 value")
    if resources["limits_reviewed"] is not True:
        raise ValueError(
            "host memory headroom and deployment limits require operator review"
        )

    lifecycle = profile["lifecycle"]
    _fields(
        lifecycle,
        {"stop_grace_period_seconds", "termination_margin_seconds"},
        "lifecycle",
    )
    stop_grace = lifecycle["stop_grace_period_seconds"]
    margin = lifecycle["termination_margin_seconds"]
    _positive_number(stop_grace, "stop_grace_period_seconds", 3600)
    _positive_number(margin, "termination_margin_seconds", 60)
    if app.admission.request_timeout_seconds > worker["socket_timeout_seconds"]:
        raise ValueError(
            "worker shutdown timeout must cover the maximum request timeout"
        )
    required_grace = (
        max(
            app.lifecycle.model_load_timeout_seconds
            + app.lifecycle.process_exit_timeout_seconds,
            worker["socket_timeout_seconds"]
            + app.lifecycle.shutdown_drain_timeout_seconds
            + app.lifecycle.process_exit_timeout_seconds,
        )
        + margin
    )
    if stop_grace < required_grace:
        raise ValueError("Compose stop grace must cover drain, process exit and margin")

    health = profile["healthcheck"]
    _fields(
        health,
        {
            "interval_seconds",
            "timeout_seconds",
            "probe_timeout_seconds",
            "retries",
            "start_period_seconds",
        },
        "healthcheck",
    )
    _positive_number(health["interval_seconds"], "health interval", 300)
    timeout = _positive_number(health["timeout_seconds"], "health timeout", 60)
    probe_timeout = _positive_number(
        health["probe_timeout_seconds"], "probe timeout", 60
    )
    if probe_timeout > timeout:
        raise ValueError("health probe timeout must fit inside the Compose timeout")
    retries = health["retries"]
    if type(retries) is not int or not 1 <= retries <= 10:
        raise ValueError("health retries must be in 1..10")
    start_period = _positive_number(
        health["start_period_seconds"], "health start period", 86400
    )
    if start_period < app.lifecycle.model_load_timeout_seconds:
        raise ValueError(
            "health start period must cover the configured model-load timeout"
        )

    if verify_files:
        validate_model_permissions(
            host_release_root,
            host_release_root / manifest_path.relative_to("/models"),
            read_gid,
            owner_uid,
            access["service_uid"],
            access["service_gid"],
        )
        host_artifact = ArtifactRoot(
            host_release_root / artifact_directory.relative_to("/models"),
            host_release_root / manifest_path.relative_to("/models"),
        )
        verified = verify_artifact(selected, host_artifact)
        if verified.identity.manifest_sha256 != model["manifest_sha256"]:
            raise ValueError(
                "verified artifact identity does not match deployment profile"
            )

    return {
        "profile": profile,
        "profile_sha256": _sha256(profile_path),
        "image": image,
        "image_id": image_id,
        "platform": runtime["platform"],
        "model": model,
        "device": device,
        "artifact_access": access,
        "configuration_set_sha256": configuration_set_sha256(
            profile_path,
            application_config_path,
            deployment_config_path,
            worker_config_path,
            build_evidence_path=build_evidence_path,
        ),
        "identity_mode": identity_mode,
        "resources": resources,
        "lifecycle": lifecycle,
        "healthcheck": health,
        "application": app,
        "deployment": deployment,
        "worker": worker,
        "release_root": host_release_root,
        "application_config_path": Path(application_config_path).resolve(),
        "deployment_config_path": Path(deployment_config_path).resolve(),
        "worker_config_path": Path(worker_config_path).resolve(),
    }


def compose_environment(validated, application_path, deployment_path, worker_path):
    profile = validated["profile"]
    resources = validated["resources"]
    health = validated["healthcheck"]
    lifecycle = validated["lifecycle"]
    device = validated["device"]
    access = validated["artifact_access"]
    model = validated["model"]
    values = {
        "STT_COMPOSE_PROJECT_NAME": profile["project_name"],
        "STT_CUDA_IMAGE": validated["image"],
        "STT_IMAGE_IDENTITY_MODE": validated["identity_mode"],
        "STT_IMAGE_ID": validated["image_id"],
        "STT_SOURCE_REVISION": validated["profile"]["runtime"]["source_revision"],
        "STT_CUDA_LOCK_SHA256": validated["profile"]["runtime"]["cuda_lock_sha256"],
        "STT_PLATFORM": validated["platform"],
        "STT_MODEL_HOST_ROOT": str(validated["release_root"]),
        "STT_APPLICATION_CONFIG": str(Path(application_path).resolve()),
        "STT_DEPLOYMENT_CONFIG": str(Path(deployment_path).resolve()),
        "STT_WORKER_CONFIG": str(Path(worker_path).resolve()),
        "STT_ARTIFACT_GID": str(access["supplementary_read_gid"]),
        "STT_HOST_GPU_DEVICE_ID": str(device["host_physical_index"]),
        "STT_MEMORY_LIMIT_BYTES": str(resources["memory_limit_bytes"]),
        "STT_CPU_LIMIT": str(resources["cpu_limit"]),
        "STT_PIDS_LIMIT": str(resources["pids_limit"]),
        "STT_STOP_GRACE_PERIOD_SECONDS": str(lifecycle["stop_grace_period_seconds"]),
        "STT_HEALTHCHECK_INTERVAL_SECONDS": str(health["interval_seconds"]),
        "STT_HEALTHCHECK_TIMEOUT_SECONDS": str(health["timeout_seconds"]),
        "STT_HEALTHCHECK_PROBE_TIMEOUT_SECONDS": str(health["probe_timeout_seconds"]),
        "STT_HEALTHCHECK_RETRIES": str(health["retries"]),
        "STT_HEALTHCHECK_START_PERIOD_SECONDS": str(health["start_period_seconds"]),
        "STT_LISTEN_PORT": str(validated["worker"]["listen_port"]),
        "STT_DEPLOYMENT_PROFILE_SHA256": validated["profile_sha256"],
        "STT_MODEL_MANIFEST_SHA256": model["manifest_sha256"],
        "STT_MODEL_REVISION": model["revision"],
        "STT_APPLICATION_CONFIG_SHA256": _sha256(validated["application_config_path"]),
        "STT_DEPLOYMENT_CONFIG_SHA256": _sha256(validated["deployment_config_path"]),
        "STT_WORKER_CONFIG_SHA256": _sha256(validated["worker_config_path"]),
        "STT_CONFIGURATION_SET_SHA256": validated["configuration_set_sha256"],
    }
    return values


def write_env_file(path, values, repository_root="."):
    root = Path(repository_root).resolve()
    private_root = root / "private"
    if private_root.is_symlink() or not private_root.is_dir():
        raise ValueError("private deployment directory is unavailable")
    _assert_no_acl(private_root, directory=True)
    if private_root.stat().st_mode & 0o077:
        raise ValueError("private deployment directory permissions are too broad")
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(private_root)
    except ValueError as exc:
        raise ValueError(
            "generated deployment environment must remain under private/"
        ) from exc
    if not relative.parts or candidate.name in {".", ".."}:
        raise ValueError("generated deployment environment path is invalid")
    current = private_root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("private deployment directories must not be symlinks")
        if current.exists():
            if not current.is_dir() or current.stat().st_mode & 0o077:
                raise ValueError(
                    "private deployment directory permissions are too broad"
                )
            _assert_no_acl(current, directory=True)
        else:
            current.mkdir(mode=0o700)
    path = candidate
    if path.is_symlink():
        raise ValueError("generated deployment environment must not be a symlink")
    if path.exists() and not path.is_file():
        raise ValueError("generated deployment environment must be a regular file")
    content_lines = []
    for key, value in sorted(values.items()):
        text = str(value)
        if "\n" in text or "\r" in text:
            raise ValueError("deployment environment values cannot contain newlines")
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        content_lines.append(f'{key}="{escaped}"\n')
    content = "".join(content_lines)
    descriptor, temporary = tempfile.mkstemp(prefix=".stt-compose-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_rendered_compose(config, validated):
    services = config.get("services", {})
    stt = services.get("stt", {})
    if set(services) != {"gateway", "stt", "tts"}:
        raise ValueError("rendered Compose services are not the approved set")
    if set(services["gateway"].get("networks", {})) != {
        "stt_private",
        "tts_private",
    }:
        raise ValueError("Gateway must retain both private worker networks")
    if set(services["tts"].get("networks", {})) != {"tts_private"}:
        raise ValueError("TTS must remain isolated on its own private network")
    if services["tts"].get("ports") or services["gateway"].get("ports") is None:
        raise ValueError("worker and Gateway host-port configuration is invalid")
    if config.get("name") != validated["profile"]["project_name"]:
        raise ValueError("rendered Compose project identity does not match profile")
    if stt.get("gpus"):
        raise ValueError("rendered CUDA worker must not use broad GPU allocation")
    if stt.get("image") != validated["image"] or stt.get("build") is not None:
        raise ValueError("rendered CUDA service must use only its immutable image")
    expected_command = [
        "services.stt.main",
        "--config",
        "/config/stt.yaml",
        "--application-config",
        "/config/stt-application.yaml",
        "--deployment-config",
        "/config/stt-deployment.yaml",
    ]
    if stt.get("command") != expected_command:
        raise ValueError("rendered CUDA service must launch the production STT app")
    labels = stt.get("labels", {})
    runtime = validated["profile"]["runtime"]
    if (
        labels.get("com.speech-platform.image-role") != "stt-worker"
        or labels.get("com.speech-platform.image-identity-mode")
        != validated["identity_mode"]
        or labels.get("com.speech-platform.image-id") != validated["image_id"]
        or labels.get("com.speech-platform.source-revision")
        != runtime["source_revision"]
        or labels.get("com.speech-platform.cuda-lock-sha256")
        != runtime["cuda_lock_sha256"]
    ):
        raise ValueError(
            "rendered image role or provenance labels do not match profile"
        )
    if stt.get("pull_policy") != "never" or stt.get("platform") != "linux/amd64":
        raise ValueError("rendered CUDA service image policy is unsafe")
    if stt.get("profiles") != ["cuda"]:
        raise ValueError("rendered CUDA service must require the cuda profile")
    if (
        stt.get("restart") != "no"
        or stt.get("stop_grace_period")
        != f"{validated['lifecycle']['stop_grace_period_seconds']}s"
    ):
        raise ValueError("rendered restart or stop policy does not match profile")
    if stt.get("user") != "65532:65532" or stt.get("read_only") is not True:
        raise ValueError("rendered CUDA service must remain non-root and read-only")
    if stt.get("privileged", False) or stt.get("cap_drop") != ["ALL"]:
        raise ValueError("rendered CUDA service has an unsafe privilege policy")
    if "no-new-privileges:true" not in stt.get("security_opt", []):
        raise ValueError("rendered CUDA service must retain no-new-privileges")
    if stt.get("ports") or stt.get("networks") != {"stt_private": None}:
        raise ValueError("rendered STT service must remain private without host ports")
    networks = config.get("networks", {})
    if set(networks) != {"stt_private", "tts_private"} or any(
        not value.get("internal", False) for value in networks.values()
    ):
        raise ValueError("rendered worker networks must remain separate and internal")
    devices = (
        stt.get("deploy", {})
        .get("resources", {})
        .get("reservations", {})
        .get("devices", [])
    )
    if len(devices) != 1 or devices[0].get("device_ids") != [
        str(validated["device"]["host_physical_index"])
    ]:
        raise ValueError(
            "rendered CUDA allocation must select only configured physical GPU"
        )
    if devices[0].get("driver") != "nvidia" or "gpu" not in devices[0].get(
        "capabilities", []
    ):
        raise ValueError("rendered CUDA device reservation is invalid")
    if int(stt.get("mem_limit", 0)) != validated["resources"]["memory_limit_bytes"]:
        raise ValueError("rendered memory limit does not match profile")
    if float(stt.get("cpus", 0)) != float(validated["resources"]["cpu_limit"]):
        raise ValueError("rendered CPU limit does not match profile")
    if int(stt.get("pids_limit", 0)) != validated["resources"]["pids_limit"]:
        raise ValueError("rendered PID limit does not match profile")
    health = stt.get("healthcheck", {})
    test = health.get("test", [])
    if (
        not test
        or "/healthz" not in " ".join(map(str, test))
        or "/readyz" in " ".join(map(str, test))
    ):
        raise ValueError("Compose liveness check must call healthz, not readiness")
    if health.get("interval") != f"{validated['healthcheck']['interval_seconds']}s":
        raise ValueError("rendered health interval does not match profile")
    for key, profile_key in (
        ("timeout", "timeout_seconds"),
        ("start_period", "start_period_seconds"),
    ):
        if health.get(key) != f"{validated['healthcheck'][profile_key]}s":
            raise ValueError(f"rendered health {key} does not match profile")
    if health.get("retries") != validated["healthcheck"]["retries"]:
        raise ValueError("rendered health retries do not match profile")
    environment = stt.get("environment", {})
    if "python" not in test or not environment.get(
        "STT_HEALTHCHECK_PROBE_TIMEOUT_SECONDS"
    ):
        raise ValueError("liveness probe must use the runtime Python standard library")
    volumes = stt.get("volumes", [])
    if any(volume.get("read_only") is not True for volume in volumes):
        raise ValueError("all CUDA worker bind mounts must be read-only")
    if len(volumes) != 4:
        raise ValueError("rendered CUDA worker must have only the approved mounts")
    model_mounts = [volume for volume in volumes if volume.get("target") == "/models"]
    if len(model_mounts) != 1 or model_mounts[0].get("read_only") is not True:
        raise ValueError("model release must have one explicit read-only mount")
    if (
        Path(model_mounts[0].get("source", "")).resolve()
        != Path(validated["release_root"]).resolve()
    ):
        raise ValueError("rendered model mount source does not match the release")
    if environment.get("STT_LISTEN_PORT") != str(validated["worker"]["listen_port"]):
        raise ValueError("rendered liveness port does not match worker configuration")
    expected_config_mounts = {
        str(validated["worker_config_path"]): "/config/stt.yaml",
        str(validated["application_config_path"]): "/config/stt-application.yaml",
        str(validated["deployment_config_path"]): "/config/stt-deployment.yaml",
    }
    actual_mounts = {
        str(volume.get("source")): str(volume.get("target")) for volume in volumes
    }
    if any(
        actual_mounts.get(source) != target
        for source, target in expected_config_mounts.items()
    ):
        raise ValueError("rendered config mounts do not match validated config inputs")
    expected_gids = [str(validated["artifact_access"]["supplementary_read_gid"])]
    if stt.get("group_add") != expected_gids:
        raise ValueError("rendered model access group does not match profile")
    if (
        labels.get("com.speech-platform.deployment-profile-sha256")
        != validated["profile_sha256"]
    ):
        raise ValueError("rendered deployment profile label does not match")
    if (
        labels.get("com.speech-platform.configuration-set-sha256")
        != validated["configuration_set_sha256"]
    ):
        raise ValueError("rendered configuration-set identity label does not match")
    if (
        labels.get("com.speech-platform.model-manifest-sha256")
        != validated["model"]["manifest_sha256"]
    ):
        raise ValueError("rendered model manifest label does not match profile")
    if (
        labels.get("com.speech-platform.model-revision")
        != validated["model"]["revision"]
    ):
        raise ValueError("rendered model revision label does not match profile")
    for label, environment_key in (
        (
            "com.speech-platform.application-config-sha256",
            "STT_APPLICATION_CONFIG_SHA256",
        ),
        (
            "com.speech-platform.deployment-config-sha256",
            "STT_DEPLOYMENT_CONFIG_SHA256",
        ),
        ("com.speech-platform.worker-config-sha256", "STT_WORKER_CONFIG_SHA256"),
    ):
        if labels.get(label) != _sha256(
            {
                "STT_APPLICATION_CONFIG_SHA256": validated["application_config_path"],
                "STT_DEPLOYMENT_CONFIG_SHA256": validated["deployment_config_path"],
                "STT_WORKER_CONFIG_SHA256": validated["worker_config_path"],
            }[environment_key]
        ):
            raise ValueError("rendered configuration identity label does not match")


def _main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "check-rendered", "verify-image", "verify-container"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--profile", required=True)
        sub.add_argument("--application-config", required=True)
        sub.add_argument("--deployment-config", required=True)
        sub.add_argument("--worker-config", required=True)
        sub.add_argument("--lock", default="services/requirements-stt-cuda.lock")
        sub.add_argument(
            "--dockerfile", default="deployments/compose/worker-stt-cuda.Dockerfile"
        )
        sub.add_argument("--build-evidence")
        if name == "prepare":
            sub.add_argument("--output-env", required=True)
        if name == "verify-container":
            sub.add_argument("--container-id", required=True)
    args = parser.parse_args()
    try:
        private_inputs = [
            args.profile,
            args.application_config,
            args.deployment_config,
            args.worker_config,
        ]
        if args.build_evidence:
            private_inputs.append(args.build_evidence)
        require_private_config_paths(private_inputs)
        validated = load_and_validate(
            args.profile,
            args.application_config,
            args.deployment_config,
            args.worker_config,
            lock_path=args.lock,
            dockerfile_path=args.dockerfile,
            build_evidence_path=args.build_evidence,
        )
        if args.command == "prepare":
            write_env_file(
                args.output_env,
                compose_environment(
                    validated,
                    args.application_config,
                    args.deployment_config,
                    args.worker_config,
                ),
            )
            print(
                "PASS: deployment profile and artifacts verified; private Compose environment written"
            )
        elif args.command == "check-rendered":
            rendered = json.load(sys.stdin)
            validate_rendered_compose(rendered, validated)
            print(
                "PASS: rendered Compose matches the validated CUDA deployment profile"
            )
        elif args.command == "verify-image":
            if validated["identity_mode"] != "local_image_id":
                raise ValueError("verify-image is for local_image_id mode only")
            verify_local_image_with_docker(validated["profile"]["runtime"])
            print("PASS: exact local image ID, platform, user and provenance match")
        else:
            if validated["identity_mode"] == "local_image_id":
                verify_local_image_runtime_with_docker()
            verify_created_container_with_docker(
                args.container_id, validated["image_id"]
            )
            print("PASS: created, stopped container uses the approved image ID")
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        SpeechFailure,
        yaml.YAMLError,
    ) as exc:
        print(
            f"FAIL: CUDA deployment profile rejected ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
