"""Plan or install the isolated, release-pinned CUDA STT Compose project."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import yaml

from scripts.model_artifacts import check_models
from scripts.release_manifest import REPOSITORY_ROOT, load_release
from scripts.service_selection import resolve_services
from scripts.stt_deployment_profile import (
    compose_environment,
    load_and_validate,
    require_private_config_paths,
    validate_rendered_compose,
)
from services.stt.config import StrictLoader


COMPOSE_BASE = "deployments/compose/compose.yaml"
COMPOSE_CUDA = "deployments/compose/compose.stt-cuda.yaml"
PROJECT_LABEL = "com.docker.compose.project"
PROTECTED_OPERATIONAL_PROJECT = "speech-platform-stt-runtime-smoke-20261018"
CONTAINER_UID = 65532
CONTAINER_GID = 65532
CONTAINER_SUPPLEMENTARY_GIDS = (988,)
READINESS_POLL_SECONDS = 2
MAX_READINESS_WAIT_SECONDS = 900


def _run(
    command: list[str],
    *,
    input_text: str | None = None,
    environment: dict[str, str] | None = None,
) -> str:
    result = subprocess.run(
        command,
        input=input_text,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )
    return result.stdout


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
    supplementary_gids: tuple[int, ...] = CONTAINER_SUPPLEMENTARY_GIDS,
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
                    "STT configuration source path is unavailable"
                ) from error
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(
                    "STT configuration source path contains an unsafe component"
                )
        try:
            info = path.lstat()
        except OSError as error:
            raise ValueError(
                "required STT configuration source is unavailable"
            ) from error
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError("required STT configuration is not a regular file")
        if not _identity_can_access(path, uid=uid, gids=gids, mode=0b100):
            raise ValueError(
                "container UID 65532 and configured supplementary groups "
                "cannot read a required STT configuration file"
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


def run_deployment(
    action: str,
    *,
    service: str | None = "stt",
    enabled_services: list[str] | None = None,
    profile_path: str,
    application_config: str,
    deployment_config: str,
    worker_config: str,
    release_path: str,
    env_file: str,
    run=_run,
    gpu_probe=None,
) -> int:
    labeled_inputs = [
        ("profile.yaml", profile_path),
        ("stt-application.yaml", application_config),
        ("stt-deployment.yaml", deployment_config),
        ("stt.yaml", worker_config),
    ]
    release = load_release(release_path, REPOSITORY_ROOT)
    if enabled_services is None:
        enabled_services = ["stt"]
    selected = resolve_services(release["services"], enabled_services, service)
    print(f"PLAN: services={','.join(selected)}")
    unsupported = [name for name in selected if name != "stt"]
    if unsupported:
        print(
            "BLOCKED: NOT IMPLEMENTED for selected service(s): "
            + ", ".join(unsupported)
        )
        return 2
    for label, path in labeled_inputs:
        if not Path(path).is_file():
            raise ValueError(
                f"required private configuration {label} is missing "
                "or not a regular file"
            )
    require_private_config_paths([profile_path])
    # Configuration parsing without filesystem artifact checks lets planning
    # report GPU admission even when a later prerequisite is blocked. The
    # strict validation call below remains mandatory before READY or install.
    validated = load_and_validate(
        profile_path,
        application_config,
        deployment_config,
        worker_config,
        verify_files=False,
    )
    require_private_config_paths(
        [application_config, deployment_config, worker_config],
        group_read_gid=validated["artifact_access"]["supplementary_read_gid"],
    )
    require_container_config_access(
        [application_config, deployment_config, worker_config],
        supplementary_gids=(validated["artifact_access"]["supplementary_read_gid"],),
    )
    release = _require_release_match(validated, release_path)
    blockers = []
    image_verified = False
    try:
        verify_registry_image(validated, run)
        image_verified = True
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        blockers.append(_deployment_error(exc))
    compose_values = compose_environment(
        validated, application_config, deployment_config, worker_config
    )
    environment = os.environ.copy()
    environment.update(compose_values)
    project_checked = False
    gpu_status = {
        "free_mib": None,
        "threshold_bytes": validated["deployment"].minimum_free_gpu_bytes_before_load,
    }
    if gpu_probe is None:
        from scripts.stt_deployment_profile import observe_host_gpu

        gpu_probe = observe_host_gpu
    try:
        gpu_status.update(gpu_probe(validated))
        if gpu_status.get("identity_matches") is not True:
            blockers.append("configured GPU UUID does not match the selected device")
        if (
            gpu_status.get("free_bytes") is None
            or gpu_status["free_bytes"] < gpu_status["threshold_bytes"]
        ):
            blockers.append(
                "current GPU free memory is below the configured admission threshold"
            )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        blockers.append(_deployment_error(exc))

    try:
        rendered = _render(validated, compose_values, run)
        existing = _check_project_conflicts(
            validated["profile"]["project_name"], rendered, run
        )
        project_checked = True
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        blockers.append(_deployment_error(exc))
        rendered = None
        existing = False
    try:
        validated = load_and_validate(
            profile_path, application_config, deployment_config, worker_config
        )
        strict_release = _require_release_match(validated, release_path)
        model_results = check_models(
            strict_release, validated["release_root"].parent, REPOSITORY_ROOT
        )
        if (
            len(model_results) != 1
            or model_results[0].directory.resolve()
            != validated["release_root"].resolve()
        ):
            raise ValueError(
                "verified model artifact is not the profile's release directory"
            )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        blockers.append(_deployment_error(exc))
    if action == "install" and blockers:
        raise ValueError("deployment prerequisites blocked: " + "; ".join(blockers))
    if action == "plan":
        print(f"PLAN: release={release['release_version']} service=stt")
        print(f"PLAN: image={validated['image']}")
        print(f"PLAN: image_provenance={'verified' if image_verified else 'BLOCKED'}")
        print(
            f"PLAN: model={validated['model']['alias']}@"
            f"{validated['model']['revision']} location={validated['release_root']}"
        )
        print(
            f"PLAN: compose_project={validated['profile']['project_name']} "
            "bindings=stt:internal-only; "
            f"gateway-profile:127.0.0.1:{validated['profile']['gateway']['host_port']}"
            f"->{validated['profile']['gateway']['listen_port']}"
        )
        conflict_state = (
            ("matching project reusable" if existing else "none observed")
            if project_checked
            else "not safely checked"
        )
        print(f"PLAN: conflicts={conflict_state}")
        print(
            f"PLAN: gpu_free_mib={gpu_status.get('free_mib')} "
            f"admission_threshold_bytes={gpu_status.get('threshold_bytes')} "
            f"admission={'READY' if not blockers else 'BLOCKED'}"
        )
        for reason in blockers:
            print(f"BLOCKER: {reason}")
        return 0 if not blockers else 2
    # Re-read current headroom after all read-only checks, immediately before
    # the only operation that may create or start a container.
    latest = gpu_probe(validated)
    if (
        not latest.get("identity_matches")
        or latest.get("free_bytes") is None
        or latest["free_bytes"] < latest["threshold_bytes"]
    ):
        raise ValueError("GPU admission blocked immediately before startup")
    run(
        _install_command(validated["profile"]["project_name"]),
        environment=environment,
    )
    wait_for_container_readiness(
        validated["profile"]["project_name"],
        validated["image"],
        timeout_seconds=_readiness_timeout(validated),
        run=run,
    )
    print("INSTALL: isolated CUDA STT Compose project is healthy and ready")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "install"))
    parser.add_argument(
        "--service", default="", help="service to select; empty selects all enabled"
    )
    parser.add_argument("--enabled-services", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--application-config", required=True)
    parser.add_argument("--deployment-config", required=True)
    parser.add_argument("--worker-config", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    try:
        enabled_path = Path(args.enabled_services)
        require_private_config_paths([enabled_path])
        try:
            with enabled_path.open(encoding="utf-8") as stream:
                enabled_config = yaml.load(stream, Loader=StrictLoader)
        except (OSError, yaml.YAMLError) as error:
            raise ValueError(
                "enabled-services configuration is unavailable or invalid"
            ) from error
        if (
            not isinstance(enabled_config, dict)
            or set(enabled_config) != {"schema_version", "enabled_services"}
            or type(enabled_config.get("schema_version")) is not int
            or enabled_config["schema_version"] != 1
            or not isinstance(enabled_config.get("enabled_services"), list)
        ):
            raise ValueError(
                "enabled-services configuration fields do not match schema version 1"
            )
        return run_deployment(
            args.action,
            service=args.service or None,
            enabled_services=enabled_config["enabled_services"],
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
        print(
            f"FAIL: deployment {args.action} rejected: {error}",
            file=sys.stderr,
        )
        return 2
    except subprocess.CalledProcessError as error:
        print(
            f"FAIL: deployment {args.action} rejected: {_subprocess_failure(error)}",
            file=sys.stderr,
        )
        return 2
    except (
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        print(
            f"FAIL: deployment {args.action} rejected; verify private "
            "configuration, model access, local image, and host GPU "
            f"requirements ({type(error).__name__})",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
