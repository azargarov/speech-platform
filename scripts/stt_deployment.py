"""Plan or install a service-scoped, release-pinned Compose project."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from scripts.model_artifacts import (
    ModelProvisionError,
    check_models,
    download_from_huggingface,
    model_directory,
    provision_models,
)
from scripts.project_lock import ProjectLock
from scripts.release_manifest import REPOSITORY_ROOT, load_release
from scripts.service_deployment_profile import (
    load_gateway_config,
    load_service_profile,
)
from scripts.service_selection import resolve_services
from scripts.stt_deployment_profile import (
    compose_environment,
    load_and_validate,
    require_private_config_paths,
    validate_rendered_compose,
)
from services.stt.config import StrictLoader
from services.worker.server import load_config as load_worker_config


COMPOSE_BASE = "deployments/compose/compose.yaml"
COMPOSE_CUDA = "deployments/compose/compose.stt-cuda.yaml"
PROJECT_LABEL = "com.docker.compose.project"
PROTECTED_OPERATIONAL_PROJECT = "speech-platform-stt-runtime-smoke-20261018"
CONTAINER_UID = 65532
CONTAINER_GID = 65532
READINESS_POLL_SECONDS = 2
MAX_READINESS_WAIT_SECONDS = 900
SUPPORTED_SERVICES = frozenset({"gateway", "stt", "tts"})
SERVICE_NETWORKS = {
    "gateway": {"gateway_publish", "stt_private", "tts_private"},
    "stt": {"stt_private"},
    "tts": {"tts_private"},
}


def _run(
    command: list[str],
    *,
    input_text: str | None = None,
    environment: dict[str, str] | None = None,
    lock_fd: int | None = None,
    timeout: float = 60,
) -> str:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        start_new_session=True,
        pass_fds=(() if lock_fd is None else (lock_fd,)),
    )
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        # The process group owns the inherited lock descriptor, so a coordinator
        # interruption cannot release it while a Compose client is alive.
        for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                break
            try:
                process.communicate(timeout=grace)
                break
            except subprocess.TimeoutExpired:
                continue
        else:
            raise UncertainSubprocessError(
                "deployment subprocess termination could not be confirmed"
            ) from None
        if error.__class__ is subprocess.TimeoutExpired:
            if lock_fd is not None:
                raise UncertainSubprocessError(
                    "deployment subprocess timed out; operation outcome is uncertain"
                ) from None
            raise subprocess.TimeoutExpired(command, timeout) from None
        raise
    if _process_group_exists(process.pid):
        for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                break
            deadline = time.monotonic() + grace
            while _process_group_exists(process.pid) and time.monotonic() < deadline:
                time.sleep(0.02)
            if not _process_group_exists(process.pid):
                break
        raise UncertainSubprocessError(
            "deployment subprocess exited with descendants; runtime outcome is uncertain"
        )
    if process.returncode:
        raise subprocess.CalledProcessError(
            process.returncode, command, output=stdout, stderr=stderr
        )
    return stdout


def _process_group_exists(process_group: int) -> bool:
    """Report whether the subprocess process group still has live members."""
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class UncertainSubprocessError(subprocess.SubprocessError):
    """A child process could not be confirmed stopped after cancellation."""


def _subprocess_failure(exc: subprocess.CalledProcessError) -> str:
    """Describe a failed operation without echoing args, environment or stderr."""
    command = exc.cmd if isinstance(exc.cmd, (list, tuple)) else [exc.cmd]
    safe_command = [str(part) for part in command[:2]]
    operations = {
        ("docker", "compose"): "docker compose operation",
        ("docker", "image"): "docker image operation",
        ("docker", "network"): "docker network operation",
        ("docker", "ps"): "docker container discovery",
        ("docker", "inspect"): "docker inspect",
    }
    operation = operations.get(tuple(safe_command), "deployment subprocess")
    if safe_command == ["docker", "compose"] and len(command) > 2:
        compose_operation = str(command[2])
        if compose_operation in {"config", "up", "ps", "down"}:
            operation = f"docker compose {compose_operation}"
    return f"{operation} failed with exit code {exc.returncode}"


def _deployment_error(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return _subprocess_failure(exc)
    return str(exc)


def _require_release_match(validated: dict, release_path: str | Path) -> dict:
    if validated["identity_mode"] != "registry_digest":
        raise ValueError("Make deployment requires an immutable GHCR image reference")
    release = load_release(release_path, REPOSITORY_ROOT)
    service = release["services"].get("stt")
    if service is None or service["runtime_variant"] != "cuda":
        raise ValueError("release does not define a CUDA STT service")
    if validated["image"] != service["image"]:
        raise ValueError("profile image does not match the selected release digest")
    if validated["platform"] != service["platform"]:
        raise ValueError("profile platform does not match the selected release")
    models = service["required_model_artifacts"]
    if len(models) != 1:
        raise ValueError(
            "selected CUDA release must require exactly one model artifact"
        )
    release_model = models[0]
    profile_model = validated["profile"]["model"]
    if any(
        profile_model[key] != release_model[release_key]
        for key, release_key in (
            ("alias", "id"),
            ("revision", "revision"),
            ("manifest_sha256", "manifest_sha256"),
        )
    ):
        raise ValueError("profile model identity does not match the selected release")
    return release


def _render(validated: dict, environment: dict[str, str], run=_run) -> dict:
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-f",
        COMPOSE_BASE,
        "-f",
        COMPOSE_CUDA,
        "--profile",
        "cuda",
        "config",
        "--format",
        "json",
    ]
    rendered = json.loads(run(command, environment=environment))
    validate_rendered_compose(rendered, validated)
    return rendered


def verify_registry_image(validated: dict, run=_run) -> None:
    """Require the exact immutable registry reference to be present locally."""
    raw = run(["docker", "image", "inspect", validated["image"]])
    images = json.loads(raw)
    if not isinstance(images, list) or len(images) != 1:
        raise ValueError("Docker image inspection did not return exactly one image")
    image = images[0]
    runtime = validated["profile"]["runtime"]
    config = image.get("Config") or {}
    labels = config.get("Labels") or {}
    expected_repo_digest = validated["image"]
    platform_parts = validated["platform"].split("/", maxsplit=1)
    if len(platform_parts) != 2:
        raise ValueError("validated image platform is malformed")
    if (
        image.get("Id") != validated["image_id"]
        or expected_repo_digest not in (image.get("RepoDigests") or [])
        or image.get("Os") != platform_parts[0]
        or image.get("Architecture") != platform_parts[1]
        or config.get("User") != "65532:65532"
        or config.get("Entrypoint") != ["python", "-m"]
        or labels.get("org.opencontainers.image.revision") != runtime["source_revision"]
        or labels.get("com.speech-platform.source-revision")
        != runtime["source_revision"]
        or labels.get("com.speech-platform.image-role") != "stt-worker"
        or labels.get("com.speech-platform.base-image") != runtime["base_image"]
        or labels.get("com.speech-platform.cuda-lock-sha256")
        != runtime["cuda_lock_sha256"]
    ):
        raise ValueError("local registry image digest, platform or provenance mismatch")


def _existing_project_containers(project_name: str, run=_run) -> list[dict]:
    ids = run(
        [
            "docker",
            "ps",
            "--all",
            "--filter",
            f"label={PROJECT_LABEL}={project_name}",
            "--format",
            "{{.ID}}",
        ]
    ).split()
    containers = []
    for container_id in ids:
        raw = run(["docker", "inspect", container_id])
        records = json.loads(raw)
        if len(records) != 1:
            raise ValueError("Docker returned an ambiguous project container")
        containers.append(records[0])
    return containers


def _check_project_networks(
    project_name: str, containers: list[dict], run=_run
) -> None:
    network_ids = run(
        [
            "docker",
            "network",
            "ls",
            "--filter",
            f"label={PROJECT_LABEL}={project_name}",
            "--format",
            "{{.ID}}",
        ]
    ).split()
    if not network_ids:
        if containers:
            raise ValueError("existing project is missing its isolated STT network")
        return
    if len(network_ids) != 1 or len(containers) != 1:
        raise ValueError("Compose project has conflicting network resources")
    network_records = json.loads(run(["docker", "network", "inspect", network_ids[0]]))
    if len(network_records) != 1:
        raise ValueError("Docker returned an ambiguous project network")
    network = network_records[0]
    labels = network.get("Labels") or {}
    endpoints = set((network.get("Containers") or {}).keys())
    container_id = containers[0].get("Id")
    if (
        network.get("Name") != f"{project_name}_stt_private"
        or labels.get(PROJECT_LABEL) != project_name
        or labels.get("com.docker.compose.network") != "stt_private"
        or network.get("Internal") is not True
        or not container_id
        or not endpoints.issubset({container_id})
    ):
        raise ValueError("existing project network is not isolated to its STT service")


def _check_project_conflicts(project_name: str, rendered: dict, run=_run) -> bool:
    """Reject foreign resources in the selected namespace; return exact-match state."""
    if project_name == PROTECTED_OPERATIONAL_PROJECT:
        raise ValueError("configured project is the protected operational STT project")
    containers = _existing_project_containers(project_name, run)
    if not containers:
        _check_project_networks(project_name, containers, run)
        return False
    if len(containers) != 1:
        raise ValueError("Compose project has an unexpected number of containers")
    service = rendered["services"]["stt"]
    expected_labels = service.get("labels", {})
    for container in containers:
        config = container.get("Config", {})
        labels = config.get("Labels") or {}
        if (
            labels.get(PROJECT_LABEL) != project_name
            or labels.get("com.docker.compose.service") != "stt"
            or config.get("Image") != service["image"]
        ):
            raise ValueError(
                "Compose project name conflicts with an existing container"
            )
        if any(labels.get(key) != value for key, value in expected_labels.items()):
            raise ValueError(
                "existing project container has a different deployment identity"
            )
    _check_project_networks(project_name, containers, run)
    return True


def _install_command(project_name: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        project_name,
        "--env-file",
        "/dev/null",
        "-f",
        COMPOSE_BASE,
        "-f",
        COMPOSE_CUDA,
        "--profile",
        "cuda",
        "up",
        "-d",
        "--no-build",
        "--pull",
        "never",
        "--no-deps",
        "stt",
    ]


def _identity_can_access(
    path: Path, *, uid: int, gids: tuple[int, ...], mode: int
) -> bool:
    """Check POSIX owner/group/other access without opening or printing a file."""
    info = path.stat()
    if uid == info.st_uid:
        permission_bits = (info.st_mode >> 6) & 0b111
    elif info.st_gid in gids:
        permission_bits = (info.st_mode >> 3) & 0b111
    else:
        permission_bits = info.st_mode & 0b111
    return permission_bits & mode == mode


def require_container_config_access(
    config_paths: list[str | Path],
    *,
    uid: int = CONTAINER_UID,
    gid: int = CONTAINER_GID,
    supplementary_gids: tuple[int, ...] = (),
    service: str = "required",
) -> None:
    """Check individually bind-mounted config files against the container identity.

    Docker exposes each source file at its mount target, so the container does
    not traverse the host-side directories containing that source.
    """
    gids = (gid, *supplementary_gids)
    for config_path in config_paths:
        path = Path(os.path.abspath(config_path))
        # Check every host-side component without following symlinks. Parents
        # must exist as directories, but their host permission bits are not
        # container permissions for an individual file bind mount.
        current = Path(path.anchor)
        for component in path.parts[1:-1]:
            current /= component
            try:
                info = current.lstat()
            except OSError as error:
                raise ValueError(
                    f"{service} configuration source path is unavailable"
                ) from error
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(
                    f"{service} configuration source path contains an unsafe component"
                )
        try:
            info = path.lstat()
        except OSError as error:
            raise ValueError(
                f"required {service} configuration source is unavailable"
            ) from error
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError(f"required {service} configuration is not a regular file")
        if not _identity_can_access(path, uid=uid, gids=gids, mode=0b100):
            raise ValueError(
                f"container UID 65532 and configured supplementary groups "
                f"cannot read the required {service} configuration file"
            )


def _readiness_timeout(validated: dict) -> float:
    health = validated["healthcheck"]
    # Compose's start period and retry schedule bound normal model initialization.
    budget = (
        health["start_period_seconds"]
        + health["interval_seconds"] * health["retries"]
        + health["timeout_seconds"]
    )
    if budget <= 0:
        raise ValueError("configured readiness timeout must be positive")
    return min(float(budget), float(MAX_READINESS_WAIT_SECONDS))


def wait_for_container_readiness(
    project_name: str,
    expected_image: str,
    *,
    timeout_seconds: float,
    run=_run,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> None:
    """Wait for the exact project's STT container to become Docker healthy."""
    deadline = monotonic() + timeout_seconds
    while True:
        ids = run(
            [
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label={PROJECT_LABEL}={project_name}",
                "--filter",
                "label=com.docker.compose.service=stt",
            ]
        ).split()
        if len(ids) != 1:
            raise ValueError("STT container was not created or is ambiguous")
        records = json.loads(run(["docker", "inspect", ids[0]]))
        if len(records) != 1:
            raise ValueError("Docker returned an ambiguous STT container state")
        container = records[0]
        labels = (container.get("Config") or {}).get("Labels") or {}
        if (
            labels.get(PROJECT_LABEL) != project_name
            or labels.get("com.docker.compose.service") != "stt"
        ):
            raise ValueError(
                "inspected container does not match the STT project identity"
            )
        if (container.get("Config") or {}).get("Image") != expected_image:
            raise ValueError("STT container image does not match the validated image")
        state = container.get("State") or {}
        status = state.get("Status")
        health = (state.get("Health") or {}).get("Status")
        if status in {"exited", "dead", "removing"}:
            raise ValueError(
                f"STT container exited before readiness (exit {state.get('ExitCode')})"
            )
        if health == "unhealthy":
            raise ValueError("STT container became unhealthy before readiness")
        if status == "running" and health == "healthy":
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ValueError("STT container did not become ready before the deadline")
        sleep(min(READINESS_POLL_SECONDS, remaining))


def _identity_sha256(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _service_identity(
    service: str,
    release_entry: dict,
    config_path: Path,
    service_profile: dict,
    config: dict,
) -> str:
    values = {
        "service": service,
        "image": release_entry["image"],
        "platform": release_entry["platform"],
        "configuration_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "resources": service_profile[service],
        "config_reader_gid": service_profile["config_reader_gid"],
        "compose_sha256": hashlib.sha256(Path(COMPOSE_BASE).read_bytes()).hexdigest(),
    }
    if service == "gateway":
        values["host_port"] = service_profile["gateway"]["host_port"]
        values["listen_port"] = config["listen_port"]
    return _identity_sha256(values)


def _load_enabled_services(path: str | Path) -> list[str]:
    require_private_config_paths([path])
    try:
        with Path(path).open(encoding="utf-8") as stream:
            value = yaml.load(stream, Loader=StrictLoader)
    except (OSError, yaml.YAMLError, ValueError) as error:
        raise ValueError(
            "enabled-services configuration is unavailable or invalid"
        ) from error
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "enabled_services"}
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or not isinstance(value.get("enabled_services"), list)
    ):
        raise ValueError(
            "enabled-services configuration fields do not match schema version 1"
        )
    return value["enabled_services"]


def _load_selected_configs(
    selected: list[str],
    *,
    service_profile_path: str,
    gateway_config_path: str,
    tts_config_path: str,
) -> tuple[dict, dict | None, dict | None, Path, Path]:
    require_private_config_paths([service_profile_path])
    service_profile = load_service_profile(service_profile_path)
    config_reader_gid = service_profile["config_reader_gid"]
    root = REPOSITORY_ROOT.resolve()
    if "gateway" in selected:
        require_private_config_paths(
            [gateway_config_path], group_read_gid=config_reader_gid
        )
        gateway_path = Path(gateway_config_path).resolve(strict=True)
        gateway_config = load_gateway_config(gateway_path)
        require_container_config_access(
            [gateway_path], supplementary_gids=(config_reader_gid,), service="Gateway"
        )
    else:
        gateway_path = root / "configs/gateway.yaml"
        gateway_config = load_gateway_config(gateway_path)
    if "tts" in selected:
        require_private_config_paths(
            [tts_config_path], group_read_gid=config_reader_gid
        )
        tts_path = Path(tts_config_path).resolve(strict=True)
        tts_config = load_worker_config(tts_path, "tts")
        require_container_config_access(
            [tts_path], supplementary_gids=(config_reader_gid,), service="TTS"
        )
    else:
        tts_path = root / "configs/tts.yaml"
        tts_config = load_worker_config(tts_path, "tts")
    return service_profile, gateway_config, tts_config, gateway_path, tts_path


def _compose_environment(
    selected: list[str],
    release: dict,
    service_profile: dict,
    gateway_config: dict,
    tts_config: dict,
    gateway_path: Path,
    tts_path: Path,
    *,
    stt_validated: dict | None,
    application_config: str,
    deployment_config: str,
    worker_config: str,
) -> dict[str, str]:
    project = service_profile["project_name"]
    values = {
        "SERVICE_PROJECT_NAME": project,
        "SERVICE_CONFIG_READER_GID": str(service_profile["config_reader_gid"]),
        "STT_COMPOSE_PROJECT_NAME": project,
        "GATEWAY_IMAGE": release["services"]["gateway"]["image"],
        "TTS_IMAGE": release["services"]["tts"]["image"],
        "GATEWAY_CONFIG": str(gateway_path),
        "TTS_CONFIG": str(tts_path),
        "GATEWAY_CONFIG_SHA256": hashlib.sha256(gateway_path.read_bytes()).hexdigest(),
        "TTS_CONFIG_SHA256": hashlib.sha256(tts_path.read_bytes()).hexdigest(),
        "SPEECH_BIND_IP": "127.0.0.1",
        "SPEECH_PORT": str(service_profile["gateway"]["host_port"]),
        "SPEECH_LISTEN_PORT": str(gateway_config["listen_port"]),
        "GATEWAY_MEMORY": service_profile["gateway"]["memory_limit"],
        "GATEWAY_CPUS": str(service_profile["gateway"]["cpu_limit"]),
        "GATEWAY_PIDS": str(service_profile["gateway"]["pids_limit"]),
        "TTS_MEMORY": service_profile["tts"]["memory_limit"],
        "TTS_CPUS": str(service_profile["tts"]["cpu_limit"]),
        "TTS_PIDS": str(service_profile["tts"]["pids_limit"]),
        "GATEWAY_DEPLOYMENT_IDENTITY_SHA256": _service_identity(
            "gateway",
            release["services"]["gateway"],
            gateway_path,
            service_profile,
            gateway_config,
        ),
        "TTS_DEPLOYMENT_IDENTITY_SHA256": _service_identity(
            "tts", release["services"]["tts"], tts_path, service_profile, tts_config
        ),
    }
    if "stt" in selected:
        if stt_validated is None:
            raise ValueError("selected STT service has no validated CUDA profile")
        stt_values = compose_environment(
            stt_validated, application_config, deployment_config, worker_config
        )
        if (
            stt_validated["profile"]["project_name"] != project
            or stt_validated["profile"]["gateway"]["host_port"]
            != service_profile["gateway"]["host_port"]
            or stt_validated["profile"]["gateway"]["listen_port"]
            != gateway_config["listen_port"]
        ):
            raise ValueError(
                "STT profile project and Gateway binding must match the service profile"
            )
        if (
            stt_validated["artifact_access"]["supplementary_read_gid"]
            != service_profile["config_reader_gid"]
        ):
            raise ValueError(
                "STT and service profiles must use the same config-reader group"
            )
        values.update(stt_values)
        values["SERVICE_PROJECT_NAME"] = project
    return values


def _render_selected(
    project_name: str,
    selected: list[str],
    environment: dict[str, str],
    gateway_config: dict,
    stt_validated: dict | None,
    run=_run,
) -> dict:
    command = [
        "docker",
        "compose",
        "--project-name",
        project_name,
        "--env-file",
        "/dev/null",
        "-f",
        COMPOSE_BASE,
    ]
    if "stt" in selected:
        command.extend(["-f", COMPOSE_CUDA, "--profile", "cuda"])
    command.extend(["config", "--format", "json"])
    rendered = json.loads(run(command, environment=environment))
    from scripts.check_compose import validate as validate_compose

    validate_compose(
        rendered,
        gateway_config["listen_port"],
        "127.0.0.1",
        environment.get("SERVICE_CONFIG_READER_GID", "65532"),
    )
    if "stt" in selected:
        validate_rendered_compose(rendered, stt_validated)
    return rendered


def _inspect_service_image(
    service: str, entry: dict, source_revision: str, run=_run
) -> dict:
    raw = run(["docker", "image", "inspect", entry["image"]])
    records = json.loads(raw)
    if not isinstance(records, list) or len(records) != 1:
        raise ValueError(f"{service} image inspection was ambiguous")
    image = records[0]
    expected_os, expected_arch = entry["platform"].split("/", maxsplit=1)
    config = image.get("Config") or {}
    labels = config.get("Labels") or {}
    role_by_service = {
        "gateway": ("gateway", "foundation"),
        "tts": ("tts-health-only", "health-only"),
    }
    if service == "stt":
        return image
    role, variant = role_by_service[service]
    expected_image_user = {
        # Distroless nonroot records the numeric UID and leaves the image's
        # primary GID unspecified. Compose supplies the effective GID.
        "gateway": "65532",
        "tts": "65532:65532",
    }[service]
    if config.get("User") != expected_image_user:
        raise ValueError(
            f"{service} image runtime identity mismatch: expected "
            f"Config.User={expected_image_user!r}, got {config.get('User')!r}"
        )
    if (
        entry["image"] not in (image.get("RepoDigests") or [])
        or image.get("Os") != expected_os
        or image.get("Architecture") != expected_arch
        or labels.get("org.opencontainers.image.revision") != source_revision
        or labels.get("com.speech-platform.service") != service
        or labels.get("com.speech-platform.runtime-variant") != variant
        or labels.get("com.speech-platform.service-role") != role
    ):
        raise ValueError(f"{service} image digest, platform or provenance mismatch")
    return image


def _ensure_service_image(
    service: str,
    entry: dict,
    *,
    action: str,
    stt_validated: dict | None,
    source_revision: str,
    before_mutation=None,
    run=_run,
) -> str:
    try:
        image = _inspect_service_image(service, entry, source_revision, run)
    except subprocess.CalledProcessError:
        if action == "plan":
            raise ValueError(
                f"{service} immutable image is missing locally; install will stage it"
            )
        if before_mutation is not None:
            before_mutation()
        run(
            [
                "docker",
                "image",
                "pull",
                "--platform",
                entry["platform"],
                entry["image"],
            ]
        )
        image = _inspect_service_image(service, entry, source_revision, run)
    if service == "stt":
        if stt_validated is None:
            raise ValueError("STT image cannot be verified without its private profile")
        verify_registry_image(stt_validated, run)
    else:
        # _inspect_service_image has checked immutable digest, platform and role.
        del image
    return "verified"


def _selected_release(release: dict, selected: list[str]) -> dict:
    return {
        **release,
        "services": {name: release["services"][name] for name in selected},
    }


def _ensure_selected_models(
    selected_release: dict,
    validated: dict,
    *,
    action: str,
    before_mutation=None,
) -> list[str]:
    models = [
        model
        for service in selected_release["services"].values()
        for model in service["required_model_artifacts"]
    ]
    if not models:
        return []
    store = validated["release_root"].parent
    missing_by_service = {}
    existing_by_service = {}
    for name, service in selected_release["services"].items():
        missing_by_service[name] = [
            model
            for model in service["required_model_artifacts"]
            if not model_directory(store, model).exists()
        ]
        existing_by_service[name] = [
            model
            for model in service["required_model_artifacts"]
            if model not in missing_by_service[name]
        ]
    missing = [model for models in missing_by_service.values() for model in models]
    existing = [model for models in existing_by_service.values() for model in models]
    staged = []
    if missing:
        if action == "plan":
            raise ModelProvisionError(
                "required model artifacts are missing; install will stage pinned files"
            )

        existing_release = {
            **selected_release,
            "services": {
                name: {
                    **selected_release["services"][name],
                    "required_model_artifacts": artifacts,
                }
                for name, artifacts in existing_by_service.items()
                if artifacts
            },
        }
        if existing:
            check_models(existing_release, store, REPOSITORY_ROOT)

        if before_mutation is not None:
            before_mutation()

        missing_release = {
            **selected_release,
            "services": {
                name: {
                    **selected_release["services"][name],
                    "required_model_artifacts": artifacts,
                }
                for name, artifacts in missing_by_service.items()
                if artifacts
            },
        }

        def download(model, relative_path, destination, maximum_bytes):
            if model["source"] != "huggingface_hub":
                raise ModelProvisionError("model source has no configured downloader")
            download_from_huggingface(model, relative_path, destination, maximum_bytes)

        access = validated["artifact_access"]
        provisioned = provision_models(
            missing_release,
            store,
            REPOSITORY_ROOT,
            download,
            directory_mode=0o2750,
            file_mode=0o640,
            expected_owner_uid=access["artifact_owner_uid"],
            expected_group_gid=access["supplementary_read_gid"],
        )
        staged.extend(
            result.artifact_id for result in provisioned if result.status == "installed"
        )
    checked = check_models(selected_release, store, REPOSITORY_ROOT)
    if len(checked) != len(models):
        raise ModelProvisionError("selected model artifact verification was incomplete")
    return staged


def _project_services(
    project_name: str,
    *,
    gateway_host_port: int | None = None,
    gateway_listen_port: int | None = None,
    run=_run,
) -> dict[str, dict]:
    if project_name == PROTECTED_OPERATIONAL_PROJECT:
        raise ValueError("configured project is the protected operational STT project")
    containers = _existing_project_containers(project_name, run)
    services = {}
    container_ids = set()
    for container in containers:
        labels = (container.get("Config") or {}).get("Labels") or {}
        name = labels.get("com.docker.compose.service")
        if labels.get(PROJECT_LABEL) != project_name or name not in SUPPORTED_SERVICES:
            raise ValueError("Compose project contains an unknown or foreign service")
        if name in services:
            raise ValueError(f"Compose project has multiple {name} containers")
        services[name] = container
        container_ids.add(container.get("Id"))
    network_ids = run(
        [
            "docker",
            "network",
            "ls",
            "--filter",
            f"label={PROJECT_LABEL}={project_name}",
            "--format",
            "{{.ID}}",
        ]
    ).split()
    seen_networks = set()
    for network_id in network_ids:
        records = json.loads(run(["docker", "network", "inspect", network_id]))
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError("Docker returned an ambiguous project network")
        network = records[0]
        labels = network.get("Labels") or {}
        network_name = labels.get("com.docker.compose.network")
        endpoints = set((network.get("Containers") or {}).keys())
        network_options = network.get("Options") or {}
        if (
            labels.get(PROJECT_LABEL) != project_name
            or network_name not in {"gateway_publish", "stt_private", "tts_private"}
            or network_name in seen_networks
            or network.get("Internal") is not (network_name != "gateway_publish")
            or (
                network_name == "gateway_publish"
                and network_options.get(
                    "com.docker.network.bridge.enable_ip_masquerade"
                )
                != "false"
            )
            or not endpoints.issubset(container_ids)
        ):
            raise ValueError("Compose project network is not isolated to its services")
        seen_networks.add(network_name)
    for name, container in services.items():
        actual_networks = set(
            ((container.get("NetworkSettings") or {}).get("Networks") or {}).keys()
        )
        expected_networks = {
            f"{project_name}_{network}" for network in SERVICE_NETWORKS[name]
        }
        if actual_networks and actual_networks != expected_networks:
            if name != "gateway" or not actual_networks.issubset(expected_networks):
                raise ValueError(
                    f"existing {name} container uses an unexpected network"
                )
        port_bindings = (container.get("HostConfig") or {}).get("PortBindings") or {}
        actual_bindings = {
            target: values for target, values in port_bindings.items() if values
        }
        if name == "gateway" and gateway_host_port is not None:
            expected_target = f"{gateway_listen_port}/tcp"
            expected_bindings = {
                expected_target: [
                    {"HostIp": "127.0.0.1", "HostPort": str(gateway_host_port)}
                ]
            }
            if actual_bindings != expected_bindings:
                raise ValueError(
                    "existing Gateway does not use the configured loopback port"
                )
        elif name != "gateway" and actual_bindings:
            raise ValueError(f"existing {name} worker has a published host port")
    return services


def _service_probe(
    service: str,
    container: dict,
    *,
    profile: dict,
    gateway_config: dict,
    tts_config: dict,
    run=_run,
    request=urllib.request.urlopen,
) -> bool:
    state = container.get("State") or {}
    if state.get("Status") != "running":
        return False
    if service == "stt":
        return (state.get("Health") or {}).get("Status") == "healthy"
    timeout = profile["readiness"]["probe_timeout_seconds"]
    if service == "gateway":
        url = f"http://127.0.0.1:{profile['gateway']['host_port']}/healthz"
        try:
            with request(url, timeout=timeout) as response:
                return response.status == 200
        except (OSError, urllib.error.URLError, TimeoutError):
            return False
    command = [
        "docker",
        "exec",
        container["Id"],
        "python",
        "-c",
        "import urllib.request; urllib.request.urlopen("
        f"'http://127.0.0.1:{tts_config['listen_port']}/healthz', timeout={timeout}).read()",
    ]
    try:
        run(command)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _gateway_port_publication_error(
    container: dict, *, host_port: int, listen_port: int
) -> str | None:
    """Check Docker's realized host mapping, rather than only create intent."""
    target = f"{listen_port}/tcp"
    published = ((container.get("NetworkSettings") or {}).get("Ports") or {}).get(
        target
    )
    expected = {"HostIp": "127.0.0.1", "HostPort": str(host_port)}
    if published != [expected]:
        return (
            f"Gateway host port {host_port} is configured but not published by Docker "
            f"for {target}"
        )
    return None


def _service_matches(
    container: dict, service: str, rendered: dict, project: str
) -> bool:
    config = container.get("Config") or {}
    labels = config.get("Labels") or {}
    expected = rendered["services"][service]
    expected_networks = {
        f"{project}_{network}" for network in expected.get("networks", {})
    }
    actual_networks = set(
        ((container.get("NetworkSettings") or {}).get("Networks") or {}).keys()
    )
    if actual_networks and actual_networks != expected_networks:
        return False
    expected_labels = expected.get("labels") or {}
    if service in {"gateway", "tts"}:
        # The legacy deployment identity also hashes the entire shared Compose
        # file, so an unrelated service edit must not recreate this service.
        # Config bytes have their own label; actual runtime settings are checked
        # separately by _runtime_configuration_matches.
        expected_labels = {
            key: value
            for key, value in expected_labels.items()
            if key != "com.speech-platform.deployment-identity-sha256"
        }
    # The aggregate STT configuration-set digest includes both Compose source
    # files. Adding Gateway/TTS to the base Compose file changes that digest
    # even when the mounted STT inputs and effective container settings are
    # unchanged. Keep the digest as provenance, while the component hashes and
    # _runtime_configuration_matches establish whether the existing worker can
    # safely be retained.
    if service == "stt":
        expected_labels = {
            key: value
            for key, value in expected_labels.items()
            if key != "com.speech-platform.configuration-set-sha256"
        }
    return (
        labels.get(PROJECT_LABEL) == project
        and labels.get("com.docker.compose.service") == service
        and config.get("Image") == expected.get("image")
        and all(
            labels.get(key) == value
            for key, value in expected_labels.items()
            if not (
                service in {"gateway", "tts"}
                and key == "com.speech-platform.configuration-sha256"
                and key not in labels
            )
        )
    )


def _runtime_configuration_matches(
    container: dict, service: str, rendered: dict
) -> bool:
    config = container.get("Config") or {}
    host = container.get("HostConfig") or {}
    expected = rendered["services"][service]
    expected_mounts = {
        volume["target"]: (volume.get("source"), not volume.get("read_only", False))
        for volume in expected.get("volumes", [])
    }
    actual_mounts = {
        mount.get("Destination"): (mount.get("Source"), mount.get("RW", True))
        for mount in container.get("Mounts", [])
    }
    expected_cpus = int(round(float(expected.get("cpus", 0)) * 1_000_000_000))
    if (
        config.get("User") != expected.get("user")
        or config.get("Cmd") != expected.get("command")
        or host.get("ReadonlyRootfs") is not expected.get("read_only")
        or host.get("Memory") != int(expected.get("mem_limit", 0))
        or host.get("NanoCpus") != expected_cpus
        or host.get("PidsLimit") != expected.get("pids_limit")
        or host.get("GroupAdd", []) != expected.get("group_add", [])
        or host.get("CapDrop") != expected.get("cap_drop")
        or host.get("SecurityOpt") != expected.get("security_opt")
        or actual_mounts != expected_mounts
    ):
        return False
    if service == "stt":
        expected_devices = (
            expected.get("deploy", {})
            .get("resources", {})
            .get("reservations", {})
            .get("devices", [])
        )
        actual_devices = host.get("DeviceRequests") or []
        if len(expected_devices) != 1 or len(actual_devices) != 1:
            return False
        if actual_devices[0].get("DeviceIDs") != expected_devices[0].get("device_ids"):
            return False
    return True


def _service_action(
    service: str,
    container: dict | None,
    rendered: dict,
    project: str,
    *,
    profile: dict,
    gateway_config: dict,
    tts_config: dict,
    run=_run,
    probe=_service_probe,
) -> str:
    if container is None:
        return "install"
    if not _service_matches(container, service, rendered, project) or not (
        _runtime_configuration_matches(container, service, rendered)
    ):
        return "replace"
    if probe(
        service,
        container,
        profile=profile,
        gateway_config=gateway_config,
        tts_config=tts_config,
        run=run,
    ):
        return "unchanged"
    return "replace"


def _install_service_command(
    project: str, service: str, *, replace: bool, include_stt: bool
) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        "/dev/null",
        "-f",
        COMPOSE_BASE,
    ]
    if include_stt:
        command.extend(["-f", COMPOSE_CUDA, "--profile", "cuda"])
    command.extend(["up", "-d", "--no-build", "--pull", "never", "--no-deps"])
    if replace:
        command.append("--force-recreate")
    command.append(service)
    return command


def _wait_service_readiness(
    service: str,
    project: str,
    expected_image: str,
    rendered: dict,
    profile: dict,
    gateway_config: dict,
    tts_config: dict,
    *,
    timeout_seconds: float | None = None,
    run=_run,
    sleep=time.sleep,
    monotonic=time.monotonic,
    probe=_service_probe,
) -> None:
    readiness = profile["readiness"]
    deadline = monotonic() + (
        readiness["timeout_seconds"] if timeout_seconds is None else timeout_seconds
    )
    while True:
        services = _project_services(
            project,
            gateway_host_port=profile["gateway"]["host_port"],
            gateway_listen_port=gateway_config["listen_port"],
            run=run,
        )
        container = services.get(service)
        if container is None:
            raise ValueError(f"{service} container was not created")
        state = container.get("State") or {}
        if state.get("Status") in {"exited", "dead", "removing"}:
            raise ValueError(
                f"{service} container exited before readiness "
                f"(exit {state.get('ExitCode')})"
            )
        config = container.get("Config") or {}
        if config.get("Image") != expected_image:
            raise ValueError(f"{service} container image does not match the release")
        if not _service_matches(container, service, rendered, project) or not (
            _runtime_configuration_matches(container, service, rendered)
        ):
            raise ValueError(f"{service} container configuration differs from the plan")
        if service == "gateway":
            publication_error = _gateway_port_publication_error(
                container,
                host_port=profile["gateway"]["host_port"],
                listen_port=gateway_config["listen_port"],
            )
            if publication_error:
                raise ValueError(publication_error)
        health = (state.get("Health") or {}).get("Status")
        if health == "unhealthy":
            raise ValueError(f"{service} container became unhealthy before readiness")
        if probe(
            service,
            container,
            profile=profile,
            gateway_config=gateway_config,
            tts_config=tts_config,
            run=run,
        ):
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            if service == "gateway" and not (config.get("Healthcheck") or {}).get(
                "Test"
            ):
                raise ValueError(
                    "gateway Docker healthcheck is missing and host HTTP readiness "
                    "did not become healthy before the deadline"
                )
            raise ValueError(f"{service} did not become healthy before the deadline")
        sleep(min(readiness["poll_interval_seconds"], remaining))


def run_deployment(
    action: str,
    *,
    service: str | None = "stt",
    enabled_services: list[str] | None = None,
    services_profile_path: str = "private/deployment/services.yaml",
    gateway_config_path: str = "private/deployment/gateway.yaml",
    tts_config_path: str = "private/deployment/tts.yaml",
    profile_path: str,
    application_config: str,
    deployment_config: str,
    worker_config: str,
    release_path: str,
    env_file: str,
    lock_root: str | Path | None = None,
    run=_run,
    gpu_probe=None,
    service_probe=_service_probe,
) -> int:
    if action not in {"plan", "install"}:
        raise ValueError("deployment action must be plan or install")
    release = load_release(release_path, REPOSITORY_ROOT)
    if enabled_services is None:
        enabled_services = ["stt"]
    selected = resolve_services(release["services"], enabled_services, service)
    unsupported = [name for name in selected if name not in SUPPORTED_SERVICES]
    if unsupported:
        raise ValueError("unsupported selected service(s): " + ", ".join(unsupported))
    print(f"PLAN: services={','.join(selected)}")
    edges = sorted(
        f"{dependency}->{name}"
        for name in selected
        for dependency in release["services"][name]["dependencies"]
        if dependency in selected
    )
    print(f"PLAN: dependencies={','.join(edges) if edges else 'none'}")

    service_profile, gateway_config, tts_config, gateway_path, tts_path = (
        _load_selected_configs(
            selected,
            service_profile_path=services_profile_path,
            gateway_config_path=gateway_config_path,
            tts_config_path=tts_config_path,
        )
    )
    project = service_profile["project_name"]
    if project == PROTECTED_OPERATIONAL_PROJECT:
        raise ValueError("configured project is the protected operational STT project")
    stt_validated = None
    blockers = []
    if "stt" in selected:
        labeled_inputs = [
            ("profile.yaml", profile_path),
            ("stt-application.yaml", application_config),
            ("stt-deployment.yaml", deployment_config),
            ("stt.yaml", worker_config),
        ]
        for label, path in labeled_inputs:
            if not Path(path).is_file():
                raise ValueError(
                    f"required private configuration {label} is missing or not a regular file"
                )
        require_private_config_paths([profile_path])
        stt_validated = load_and_validate(
            profile_path,
            application_config,
            deployment_config,
            worker_config,
            verify_files=False,
        )
        require_private_config_paths(
            [application_config, deployment_config, worker_config],
            group_read_gid=stt_validated["artifact_access"]["supplementary_read_gid"],
        )
        require_container_config_access(
            [application_config, deployment_config, worker_config],
            supplementary_gids=(
                stt_validated["artifact_access"]["supplementary_read_gid"],
            ),
        )
        _require_release_match(stt_validated, release_path)

    compose_values = _compose_environment(
        selected,
        release,
        service_profile,
        gateway_config,
        tts_config,
        gateway_path,
        tts_path,
        stt_validated=stt_validated,
        application_config=application_config,
        deployment_config=deployment_config,
        worker_config=worker_config,
    )
    environment = os.environ.copy()
    environment.update(compose_values)
    rendered = _render_selected(
        project, selected, compose_values, gateway_config, stt_validated, run
    )
    selected_release = _selected_release(release, selected)

    gpu_status = None
    if "stt" in selected:
        if gpu_probe is None:
            from scripts.stt_deployment_profile import observe_host_gpu

            gpu_probe = observe_host_gpu
        try:
            gpu_status = gpu_probe(stt_validated)
            if not gpu_status.get("identity_matches"):
                blockers.append(
                    "configured GPU UUID does not match the selected device"
                )
            if gpu_status.get("free_bytes", 0) < gpu_status.get("threshold_bytes", 1):
                blockers.append(
                    "current GPU free memory is below the configured admission threshold"
                )
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            blockers.append(_deployment_error(error))

    try:
        existing = _project_services(
            project,
            gateway_host_port=service_profile["gateway"]["host_port"],
            gateway_listen_port=gateway_config["listen_port"],
            run=run,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        blockers.append(_deployment_error(error))
        existing = {}

    actions = {}
    for name in selected:
        try:
            actions[name] = _service_action(
                name,
                existing.get(name),
                rendered,
                project,
                profile=service_profile,
                gateway_config=gateway_config,
                tts_config=tts_config,
                run=run,
                probe=service_probe,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            blockers.append(_deployment_error(error))
            actions[name] = "BLOCKED"

    preflight_actions = dict(actions)

    if action == "install" and blockers:
        raise ValueError("deployment prerequisites blocked: " + "; ".join(blockers))

    lock_context = (
        ProjectLock(project, root=lock_root, wait_seconds=0)
        if action == "install"
        else contextlib.nullcontext(None)
    )
    with lock_context as deployment_lock:
        if deployment_lock is not None:
            base_run = run

            def run(command, **kwargs):
                deployment_lock.assert_current()
                if base_run is _run:
                    kwargs["lock_fd"] = deployment_lock.fd
                try:
                    return base_run(command, **kwargs)
                finally:
                    deployment_lock.assert_current()

            # Planning above is deliberately read-only. Re-render and repeat the
            # exact project/GPU admission checks under the shared lock before any
            # pull, model staging, or lifecycle operation can begin.
            locked_release = load_release(release_path, REPOSITORY_ROOT)
            if locked_release != release:
                raise ValueError("release inputs changed after install preflight")
            (
                service_profile,
                gateway_config,
                tts_config,
                gateway_path,
                tts_path,
            ) = _load_selected_configs(
                selected,
                service_profile_path=services_profile_path,
                gateway_config_path=gateway_config_path,
                tts_config_path=tts_config_path,
            )
            if service_profile["project_name"] != project:
                raise ValueError("Compose project identity changed after preflight")
            if "stt" in selected:
                for label, path in (
                    ("profile.yaml", profile_path),
                    ("stt-application.yaml", application_config),
                    ("stt-deployment.yaml", deployment_config),
                    ("stt.yaml", worker_config),
                ):
                    if not Path(path).is_file():
                        raise ValueError(
                            f"required private configuration {label} changed after preflight"
                        )
                require_private_config_paths([profile_path])
                stt_validated = load_and_validate(
                    profile_path,
                    application_config,
                    deployment_config,
                    worker_config,
                    verify_files=False,
                )
                require_private_config_paths(
                    [application_config, deployment_config, worker_config],
                    group_read_gid=stt_validated["artifact_access"][
                        "supplementary_read_gid"
                    ],
                )
                require_container_config_access(
                    [application_config, deployment_config, worker_config],
                    supplementary_gids=(
                        stt_validated["artifact_access"]["supplementary_read_gid"],
                    ),
                )
                _require_release_match(stt_validated, release_path)
            compose_values = _compose_environment(
                selected,
                locked_release,
                service_profile,
                gateway_config,
                tts_config,
                gateway_path,
                tts_path,
                stt_validated=stt_validated,
                application_config=application_config,
                deployment_config=deployment_config,
                worker_config=worker_config,
            )
            environment = os.environ.copy()
            environment.update(compose_values)
            selected_release = _selected_release(locked_release, selected)
            rendered = _render_selected(
                project, selected, compose_values, gateway_config, stt_validated, run
            )
            if "stt" in selected:
                gpu_status = gpu_probe(stt_validated)
                if not gpu_status.get("identity_matches") or gpu_status.get(
                    "free_bytes", 0
                ) < gpu_status.get("threshold_bytes", 1):
                    raise ValueError("GPU admission changed before install staging")
            existing = _project_services(
                project,
                gateway_host_port=service_profile["gateway"]["host_port"],
                gateway_listen_port=gateway_config["listen_port"],
                run=run,
            )
            locked_actions = {
                name: _service_action(
                    name,
                    existing.get(name),
                    rendered,
                    project,
                    profile=service_profile,
                    gateway_config=gateway_config,
                    tts_config=tts_config,
                    run=run,
                    probe=service_probe,
                )
                for name in selected
            }
            if locked_actions != preflight_actions:
                raise ValueError("deployment actions changed after install preflight")
            actions = locked_actions

        # A verified no-op stays read-only even if a local artifact disappears
        # between preflight and this point. In that case the plan-mode validators
        # fail closed instead of pulling an image or downloading a model.
        validation_action = (
            "plan"
            if action == "install"
            and actions
            and all(current == "unchanged" for current in actions.values())
            else action
        )
        image_status = {}
        for name in selected:
            try:
                image_status[name] = _ensure_service_image(
                    name,
                    release["services"][name],
                    action=validation_action,
                    stt_validated=stt_validated,
                    source_revision=release["git_source_revision"],
                    before_mutation=(
                        deployment_lock.mark_mutation_started
                        if deployment_lock is not None
                        else None
                    ),
                    run=run,
                )
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                blockers.append(_deployment_error(error))
                image_status[name] = "BLOCKED"

        staged_models = []
        if stt_validated is not None and not (action == "install" and blockers):
            try:
                if action == "install":
                    # Validate profile, model configuration, and all config identities
                    # before artifact staging or any container operation.
                    staged_models = _ensure_selected_models(
                        selected_release,
                        stt_validated,
                        action=validation_action,
                        before_mutation=(
                            deployment_lock.mark_mutation_started
                            if deployment_lock is not None
                            else None
                        ),
                    )
                    stt_validated = load_and_validate(
                        profile_path,
                        application_config,
                        deployment_config,
                        worker_config,
                    )
                else:
                    _ensure_selected_models(
                        selected_release, stt_validated, action=action
                    )
            except (
                ModelProvisionError,
                OSError,
                ValueError,
                subprocess.SubprocessError,
            ) as error:
                blockers.append(_deployment_error(error))

        if action == "plan":
            print(
                f"PLAN: compose_project={project} gateway=127.0.0.1:{service_profile['gateway']['host_port']}->{gateway_config['listen_port']}"
            )
            for name in selected:
                print(
                    f"PLAN: service={name} image={release['services'][name]['image']} "
                    f"artifact={image_status.get(name, 'BLOCKED')} action={actions[name]}"
                )
            if staged_models:
                print(f"PLAN: staged_models={','.join(staged_models)}")
            if gpu_status is not None:
                print(
                    f"PLAN: gpu_free_mib={gpu_status.get('free_mib')} "
                    f"admission_threshold_bytes={gpu_status.get('threshold_bytes')}"
                )
            print(f"PLAN: admission={'READY' if not blockers else 'BLOCKED'}")
            for reason in blockers:
                print(f"BLOCKER: {reason}")
            return 0 if not blockers else 2

        if blockers:
            raise ValueError("deployment prerequisites blocked: " + "; ".join(blockers))
        for name in selected:
            if actions[name] == "unchanged":
                print(f"INSTALL: {name} unchanged and healthy")
                continue
            current = _project_services(
                project,
                gateway_host_port=service_profile["gateway"]["host_port"],
                gateway_listen_port=gateway_config["listen_port"],
                run=run,
            ).get(name)
            current_action = _service_action(
                name,
                current,
                rendered,
                project,
                profile=service_profile,
                gateway_config=gateway_config,
                tts_config=tts_config,
                run=run,
                probe=service_probe,
            )
            if current_action != actions[name]:
                raise ValueError(
                    f"{name} deployment changed after install freshness check"
                )
            if name == "stt":
                latest = gpu_probe(stt_validated)
                if (
                    not latest.get("identity_matches")
                    or latest.get("free_bytes") is None
                    or latest["free_bytes"] < latest["threshold_bytes"]
                ):
                    raise ValueError(
                        "GPU admission blocked immediately before STT startup"
                    )
            command = _install_service_command(
                project,
                name,
                replace=actions[name] == "replace",
                include_stt="stt" in selected,
            )
            if deployment_lock is not None:
                deployment_lock.mark_mutation_started()
            run(command, environment=environment)
            _wait_service_readiness(
                name,
                project,
                release["services"][name]["image"],
                rendered,
                service_profile,
                gateway_config,
                tts_config,
                timeout_seconds=(
                    _readiness_timeout(stt_validated)
                    if name == "stt"
                    else service_profile["readiness"]["timeout_seconds"]
                ),
                run=run,
                probe=service_probe,
            )
            print(f"INSTALL: {name} healthy and ready")
        if deployment_lock is not None:
            deployment_lock.mark_complete()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "install"))
    parser.add_argument(
        "--service", default="", help="empty selects every enabled service"
    )
    parser.add_argument("--enabled-services", required=True)
    parser.add_argument("--services-profile", required=True)
    parser.add_argument("--gateway-config", default="private/deployment/gateway.yaml")
    parser.add_argument("--tts-config", default="private/deployment/tts.yaml")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--application-config", required=True)
    parser.add_argument("--deployment-config", required=True)
    parser.add_argument("--worker-config", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    try:
        enabled_services = _load_enabled_services(args.enabled_services)
        return run_deployment(
            args.action,
            service=args.service or None,
            enabled_services=enabled_services,
            services_profile_path=args.services_profile,
            gateway_config_path=args.gateway_config,
            tts_config_path=args.tts_config,
            profile_path=args.profile,
            application_config=args.application_config,
            deployment_config=args.deployment_config,
            worker_config=args.worker_config,
            release_path=args.release,
            env_file=args.env_file,
        )
    except PermissionError:
        print(
            f"FAIL: deployment {args.action} rejected: model release "
            "read/traverse access is unavailable to the current account; "
            "use the configured stt-model-reader group context",
            file=sys.stderr,
        )
        return 2
    except ValueError as error:
        print(f"FAIL: deployment {args.action} rejected: {error}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as error:
        print(
            f"FAIL: deployment {args.action} rejected: {_subprocess_failure(error)}",
            file=sys.stderr,
        )
        return 2
    except UncertainSubprocessError as error:
        print(
            f"FAIL: deployment {args.action} outcome is uncertain: {error}",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print(
            f"FAIL: deployment {args.action} was interrupted; if install mutation "
            "started, operator review is required before another install",
            file=sys.stderr,
        )
        return 130
    except (
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        print(
            f"FAIL: deployment {args.action} rejected; verify private configuration, "
            f"model access, local image, and host requirements ({type(error).__name__})",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
