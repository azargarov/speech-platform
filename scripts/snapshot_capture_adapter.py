"""Bounded production boundary for capturing one retained VoiceService snapshot.

This module selects the existing private deployment inputs and wires the
production evidence providers into the snapshot writer. Evidence providers are
explicit dependencies so callers cannot accidentally replace observations with
expected configuration values.
"""

from __future__ import annotations

import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Callable, Mapping

import yaml

from scripts.release_manifest import DEFAULT_RELEASE, REPOSITORY_ROOT, load_release
from scripts.collect_baseline_adoption import collect_baseline_adoption
from scripts.model_artifacts import check_models
from scripts.restore_snapshot import (
    CAPTURE_SOURCE_FILES,
    SnapshotCaptureError,
    capture_snapshot,
    host_bindings_sha256,
)
from scripts.service_selection import resolve_services
from scripts.stt_deployment import (
    _inspect_service_image,
    _run,
    _require_release_match,
    verify_registry_image,
)
from scripts.stt_deployment_profile import load_and_validate
from scripts.tracked_source_integrity import (
    TRACKED_SOURCE_PATHS,
    TrackedSourceError,
    validate_tracked_sources,
)
from services.stt.config import StrictLoader


PROJECT = "speech-platform-m01e-fresh-v012"
# Approved deployment-source revision. The release descriptor's own
# git_source_revision remains the separate image provenance identity.
APPROVED_SOURCE_REVISION = "6e99eaf4516afd0fa54e8a1fe6c7576b03bc529b"
PRIVATE = REPOSITORY_ROOT / "private/deployment/m01e-fresh-v012"
SNAPSHOT_ROOT = PRIVATE / "restoration"
LOCK_ROOT = Path(
    os.environ.get(
        "SPEECH_PLATFORM_LOCK_ROOT", "/srv/speech-platform/deployment-state/locks"
    )
)
SOURCE_PATHS = {
    "enabled-services.yaml": PRIVATE / "enabled-services.yaml",
    "services.yaml": PRIVATE / "services.yaml",
    "gateway.yaml": PRIVATE / "gateway.yaml",
    "tts.yaml": PRIVATE / "tts.yaml",
    "compose.env": PRIVATE / "compose.env",
    "profile.yaml": PRIVATE / "profile.yaml",
    "stt-application.yaml": PRIVATE / "stt-application.yaml",
    "stt-deployment.yaml": PRIVATE / "stt-deployment.yaml",
    "stt.yaml": PRIVATE / "stt.yaml",
    "compose.yaml": REPOSITORY_ROOT / "deployments/compose/compose.yaml",
    "compose.stt-cuda.yaml": REPOSITORY_ROOT
    / "deployments/compose/compose.stt-cuda.yaml",
    "release.yaml": DEFAULT_RELEASE,
}


def validate_project_inputs(
    source_paths: Mapping[str, Path],
    *,
    project_name: str = PROJECT,
    approved_source_revision: str = APPROVED_SOURCE_REVISION,
    git_runner=None,
) -> dict:
    """Validate release and service selection before the writer acquires a lock."""
    if set(source_paths) != CAPTURE_SOURCE_FILES:
        raise SnapshotCaptureError("production snapshot source set is incomplete")
    tracked_paths = {role: Path(source_paths[role]) for role in TRACKED_SOURCE_PATHS}
    try:
        validate_tracked_sources(
            tracked_paths,
            None,
            approved_revision=approved_source_revision,
            repository_root=REPOSITORY_ROOT,
            **({} if git_runner is None else {"runner": git_runner}),
        )
    except TrackedSourceError:
        raise SnapshotCaptureError(
            "tracked Compose or release source integrity failed"
        ) from None
    for name, path in source_paths.items():
        try:
            info = Path(path).lstat()
        except OSError:
            raise SnapshotCaptureError(
                "production snapshot input is unavailable"
            ) from None
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SnapshotCaptureError("production snapshot input is unsafe")
        tracked = name in {"compose.yaml", "compose.stt-cuda.yaml", "release.yaml"}
        permitted_modes = (
            {0o400, 0o444, 0o600, 0o644, 0o664} if tracked else {0o400, 0o600, 0o640}
        )
        trusted_owner = info.st_uid == os.getuid() or (tracked and info.st_uid == 0)
        if not trusted_owner or stat.S_IMODE(info.st_mode) not in permitted_modes:
            raise SnapshotCaptureError("deployment input permissions are unsafe")
    try:
        service_profile = yaml.load(
            source_paths["services.yaml"].read_bytes(), Loader=StrictLoader
        )
        reader_gid = service_profile.get("config_reader_gid")
        if type(reader_gid) is not int or reader_gid <= 0:
            raise ValueError("invalid config reader group")
        for name in (
            "gateway.yaml",
            "tts.yaml",
            "stt-application.yaml",
            "stt-deployment.yaml",
            "stt.yaml",
        ):
            info = source_paths[name].stat()
            if stat.S_IMODE(info.st_mode) == 0o640 and info.st_gid != reader_gid:
                raise ValueError("configuration group does not match reader group")
        release = load_release(source_paths["release.yaml"], REPOSITORY_ROOT)
        enabled = yaml.load(
            source_paths["enabled-services.yaml"].read_bytes(), Loader=StrictLoader
        )
        if (
            not isinstance(enabled, dict)
            or set(enabled) != {"schema_version", "enabled_services"}
            or type(enabled["schema_version"]) is not int
            or enabled["schema_version"] != 1
        ):
            raise ValueError("invalid service selection")
        selected = resolve_services(release["services"], enabled["enabled_services"])
        if selected != ["gateway", "stt", "tts"]:
            raise ValueError(
                "snapshot capture requires the complete release service set"
            )
        if project_name != PROJECT:
            raise ValueError("project identity differs from the approved host project")
    except Exception:
        raise SnapshotCaptureError(
            "release or enabled-service inputs failed validation"
        ) from None
    return {
        "project_name": project_name,
        "release_version": release["release_version"],
        "selected_services": selected,
    }


def capture_project_snapshot(
    *,
    validate_configuration: Callable[[Mapping[str, bytes]], dict] | None = None,
    render_captured: Callable[[Mapping[str, bytes]], dict] | None = None,
    collect_runtime: Callable[[], dict] | None = None,
    verify_artifacts: Callable[[dict[str, list[str]]], None] | None = None,
    source_paths: Mapping[str, Path] = SOURCE_PATHS,
    root: Path = SNAPSHOT_ROOT,
    lock_root: Path = LOCK_ROOT,
    retained_model_store: Path | None = None,
    run_preflight: Callable[[Mapping[str, Path]], dict] = validate_project_inputs,
    approved_source_revision: str = APPROVED_SOURCE_REVISION,
    writer: Callable = capture_snapshot,
    run: Callable = _run,
) -> dict:
    """Run a production capture through the writer's lock and revalidation gates.

    The callbacks must use the repository's strict deployment validators,
    captured-byte Compose renderer, read-only Docker observation helpers, and
    immutable image/model verification. They are mandatory by design: absence
    of observed evidence cannot be synthesized from this module's preflight.
    """
    paths = {name: Path(path) for name, path in source_paths.items()}
    preflight = run_preflight(
        paths,
        project_name=PROJECT,
        approved_source_revision=approved_source_revision,
    )
    if (
        not isinstance(preflight, dict)
        or preflight.get("project_name") != PROJECT
        or preflight.get("selected_services") != ["gateway", "stt", "tts"]
    ):
        raise SnapshotCaptureError("production snapshot preflight is incomplete")
    callbacks = (
        validate_configuration,
        render_captured,
        collect_runtime,
        verify_artifacts,
    )
    if all(callback is None for callback in callbacks):
        if retained_model_store is None:
            raise SnapshotCaptureError(
                "persistent retained model store path must be supplied"
            )
        adapters = production_callbacks(
            retained_model_store=retained_model_store, run=run
        )
        callbacks = tuple(
            adapters[key]
            for key in (
                "validate_configuration",
                "render_captured",
                "collect_runtime",
                "verify_artifacts",
            )
        )
    if any(not callable(callback) for callback in callbacks):
        raise SnapshotCaptureError(
            "production snapshot evidence adapters are incomplete"
        )
    validate_configuration, render_captured, collect_runtime, verify_artifacts = (
        callbacks
    )
    return writer(
        root,
        PROJECT,
        paths,
        allowed_source_roots=[PRIVATE, REPOSITORY_ROOT],
        validate_configuration=validate_configuration,
        render_captured=render_captured,
        collect_runtime=collect_runtime,
        verify_artifacts=verify_artifacts,
        lock_root=lock_root,
        tracked_source_revision=approved_source_revision,
        tracked_source_validator=lambda tracked, content: validate_tracked_sources(
            tracked,
            content,
            approved_revision=approved_source_revision,
            repository_root=REPOSITORY_ROOT,
        ),
    )


def _captured_compose_paths(files: Mapping[str, bytes]):
    """Stage only captured Compose source bytes for config rendering."""
    temporary = tempfile.TemporaryDirectory(prefix="voiceservice-compose-capture-")
    root = Path(temporary.name)
    os.chmod(root, 0o700)
    paths = {}
    for role in ("compose.yaml", "compose.stt-cuda.yaml"):
        if role not in files:
            temporary.cleanup()
            raise SnapshotCaptureError("captured Compose dependency is missing")
        path = root / role
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(files[role])
            stream.flush()
            os.fsync(stream.fileno())
        paths[role] = path
    return temporary, paths


def production_callbacks(
    *, retained_model_store: Path, run: Callable = _run
) -> dict[str, Callable]:
    """Build adapters from the existing strict config, Docker and artifact helpers."""
    retained_model_store = Path(retained_model_store)
    if not retained_model_store.is_absolute():
        raise SnapshotCaptureError("persistent retained model store path is invalid")

    def collect(evidence_sink, *, compose_paths=None):
        plan = collect_baseline_adoption(
            run=run, evidence_sink=evidence_sink, compose_paths=compose_paths
        )
        unacceptable = [
            blocker
            for blocker in plan["blockers"]
            if not blocker.endswith(":restore_inputs_missing")
            and blocker not in {"restore_inputs_missing_or_invalid"}
        ]
        if unacceptable:
            raise SnapshotCaptureError("fresh production evidence failed validation")
        return plan

    def validate_configuration(files: Mapping[str, bytes]) -> dict:
        if set(files) != CAPTURE_SOURCE_FILES:
            raise SnapshotCaptureError("captured production input set is incomplete")
        for role, path in SOURCE_PATHS.items():
            try:
                if Path(path).read_bytes() != files[role]:
                    raise SnapshotCaptureError("captured input differs from its source")
            except OSError:
                raise SnapshotCaptureError(
                    "captured production input is unavailable"
                ) from None
        evidence = {}
        collect(evidence)
        release = evidence["release"]
        expected = evidence["expected_runtime_contract"]
        observations = {item["service"]: item for item in evidence["observations"]}
        artifacts = {
            service: sorted(
                ["oci://" + release["services"][service]["image"]]
                + [
                    "model://" + model["id"] + "@sha256:" + model["manifest_sha256"]
                    for model in release["services"][service][
                        "required_model_artifacts"
                    ]
                ]
            )
            for service in ("gateway", "stt", "tts")
        }
        return {
            "project_name": PROJECT,
            "selected_services": ["gateway", "stt", "tts"],
            "required_optional_file_roles": [],
            "configuration_sha256_by_service": {
                service: expected[service]["configuration_sha256"]
                for service in ("gateway", "stt", "tts")
            },
            "runtime_identity_sha256_by_service": {
                service: expected[service]["runtime_identity_sha256"]
                for service in ("gateway", "stt", "tts")
            },
            "image_id_by_service": {
                service: observations[service]["image_id"]
                for service in ("gateway", "stt", "tts")
            },
            "platform_by_service": {
                service: release["services"][service]["platform"]
                for service in ("gateway", "stt", "tts")
            },
            "artifacts_by_service": artifacts,
            "secret_versions_by_service": {
                service: [] for service in ("gateway", "stt", "tts")
            },
            "host_bindings_sha256": host_bindings_sha256(evidence["rendered_compose"]),
        }

    def render_captured(files: Mapping[str, bytes]) -> dict:
        temporary, compose_paths = _captured_compose_paths(files)
        try:
            evidence = {}
            collect(evidence, compose_paths=compose_paths)
            return {
                "render_environment": evidence["render_environment"],
                "rendered_compose": evidence["rendered_compose"],
                "compose_service_hashes": evidence["compose_service_hashes"],
            }
        finally:
            temporary.cleanup()

    def collect_runtime() -> dict:
        evidence = {}
        collect(evidence)
        observations = {item["service"]: item for item in evidence["observations"]}
        readiness_times = [
            item["readiness"]["observed_at_epoch"] for item in observations.values()
        ]
        try:
            docker_version = run(
                ["docker", "version", "--format", "{{.Server.Version}}"]
            )
            compose_version = run(["docker", "compose", "version", "--short"])
        except Exception:
            raise SnapshotCaptureError(
                "Docker version evidence is unavailable"
            ) from None
        return {
            "project_name": PROJECT,
            "docker_engine_version": docker_version.strip().split()[-1],
            "compose_version": compose_version.strip().split()[-1],
            "observed_at_epoch": max(readiness_times, default=time.time()),
            "services": {
                service: {
                    "container_id": item["container_id"],
                    "compose_project_name": item["project_name"],
                    "compose_service_name": service,
                    "image_id": item["image_id"],
                    "image_reference": item["image_reference"],
                    "platform": item["platform"],
                    "compose_config_hash": item["compose_config_hash"],
                    "configuration_sha256": item["configuration_sha256"],
                    "runtime_identity_sha256": item["runtime_identity_sha256"],
                    "compatible": item["compatible"],
                    "state": item["state"],
                    "health": item["health"],
                    "readiness": item["readiness"],
                }
                for service, item in observations.items()
            },
        }

    def verify_artifacts(artifacts: dict[str, list[str]]) -> None:
        try:
            release = load_release(DEFAULT_RELEASE, REPOSITORY_ROOT)
            validated = load_and_validate(
                PRIVATE / "profile.yaml",
                PRIVATE / "stt-application.yaml",
                PRIVATE / "stt-deployment.yaml",
                PRIVATE / "stt.yaml",
                verify_files=False,
            )
            _require_release_match(validated, DEFAULT_RELEASE)
            verify_registry_image(validated, run=run)
            for service in ("gateway", "stt", "tts"):
                _inspect_service_image(
                    service,
                    release["services"][service],
                    release["git_source_revision"],
                    run,
                )
            check_models(release, retained_model_store, REPOSITORY_ROOT)
            expected = {
                service: sorted(
                    ["oci://" + release["services"][service]["image"]]
                    + [
                        "model://" + model["id"] + "@sha256:" + model["manifest_sha256"]
                        for model in release["services"][service][
                            "required_model_artifacts"
                        ]
                    ]
                )
                for service in ("gateway", "stt", "tts")
            }
            if artifacts != expected:
                raise ValueError("artifact reference set mismatch")
        except Exception:
            raise SnapshotCaptureError(
                "immutable image or model verification failed"
            ) from None

    return {
        "validate_configuration": validate_configuration,
        "render_captured": render_captured,
        "collect_runtime": collect_runtime,
        "verify_artifacts": verify_artifacts,
    }
