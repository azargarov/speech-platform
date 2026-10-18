"""Publish the Compose-built VoiceService images to GHCR."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SERVICES = {
    "gateway": ("voiceservice-gateway", "gateway", "foundation", None),
    "tts": ("voiceservice-tts-health-only", "tts-health-only", "health-only", None),
}
SERVICE_NAMES = frozenset({"gateway", "stt", "tts"})
STT_VARIANTS = {
    "cpu": ("voiceservice-stt-cpu", "stt-worker", "cpu", "cpu-lock-sha256"),
    "cuda": (
        "voiceservice-stt-cuda",
        "stt-worker",
        "cuda",
        "cuda-lock-sha256",
    ),
}
VARIANTS = frozenset(STT_VARIANTS)
REGISTRY = "ghcr.io/azargarov"
VERSION_PATTERN = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
LABEL_REVISION = "org.opencontainers.image.revision"
LABEL_ROLE = "com.speech-platform.service-role"
LABEL_SERVICE = "com.speech-platform.service"
LABEL_VARIANT = "com.speech-platform.runtime-variant"


class PublishError(RuntimeError):
    """An input, local Docker, or registry publication error."""


def validate_version(version: str) -> None:
    if not VERSION_PATTERN.fullmatch(version):
        raise PublishError("VERSION must be a semantic version tag such as v0.1.0")


def validate_services(value: str) -> list[str]:
    services = value.split()
    if not services:
        raise PublishError("at least one service must be selected")
    unknown = sorted(set(services) - SERVICE_NAMES)
    if unknown:
        raise PublishError(f"unknown service(s): {', '.join(unknown)}")
    return list(dict.fromkeys(services))


def validate_variant(value: str) -> str:
    if value not in VARIANTS:
        raise PublishError("VARIANT must be cpu or cuda")
    return value


def image_identity(service: str, variant: str) -> tuple[str, str, str, str | None]:
    if service == "stt":
        try:
            return STT_VARIANTS[variant]
        except KeyError as error:
            raise PublishError("VARIANT must be cpu or cuda") from error
    try:
        return SERVICES[service]
    except KeyError as error:
        raise PublishError(f"unknown service: {service}") from error


def docker_auth_is_configured() -> bool:
    docker_config = Path(os.environ.get("DOCKER_CONFIG", Path.home() / ".docker"))
    config_path = docker_config / "config.json"
    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    registry_keys = {"ghcr.io", "https://ghcr.io", "https://ghcr.io/v1/"}
    auths = config.get("auths", {})
    helpers = config.get("credHelpers", {})
    return bool(
        registry_keys.intersection(auths)
        or "ghcr.io" in helpers
        or config.get("credsStore")
    )


def command(
    args: list[str], *, capture: bool = False, env: dict[str, str] | None = None
) -> str:
    try:
        result = subprocess.run(
            args,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            env=env,
        )
    except FileNotFoundError as error:
        raise PublishError(f"required command not found: {args[0]}") from error
    except subprocess.CalledProcessError as error:
        raise PublishError(
            f"command failed with exit status {error.returncode}: {' '.join(args)}"
        ) from error
    return result.stdout.strip() if capture else ""


def current_revision() -> str:
    changes = command(["git", "status", "--porcelain"], capture=True)
    if changes:
        raise PublishError("publication requires a clean Git working tree")
    revision = command(["git", "rev-parse", "HEAD"], capture=True)
    if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise PublishError("could not determine a full Git source revision")
    return revision


def workflow_identity() -> str:
    workflow = os.environ.get("GITHUB_WORKFLOW")
    if workflow:
        return (
            f"{workflow}#{os.environ.get('GITHUB_RUN_ID', 'unknown')}"
            f".{os.environ.get('GITHUB_RUN_ATTEMPT', 'unknown')}"
        )
    return "local:make-publish"


def local_image_details(image_id: str) -> tuple[str, dict[str, str]]:
    raw = command(["docker", "image", "inspect", image_id], capture=True)
    try:
        image = json.loads(raw)[0]
        platform = f"{image['Os']}/{image['Architecture']}"
        labels = image["Config"].get("Labels") or {}
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as error:
        raise PublishError(f"could not inspect local image {image_id}") from error
    return platform, labels


def published_image_details(repository: str, digest: str) -> tuple[str, dict[str, str]]:
    reference = f"{repository}@{digest}"
    command(["docker", "pull", reference])
    raw = command(["docker", "image", "inspect", reference], capture=True)
    try:
        image = json.loads(raw)[0]
        platform = f"{image['Os']}/{image['Architecture']}"
        labels = image["Config"].get("Labels") or {}
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as error:
        raise PublishError(f"could not inspect published image {reference}") from error
    return platform, labels


def registry_digest(repository: str, version: str) -> str:
    output = command(
        ["docker", "buildx", "imagetools", "inspect", f"{repository}:{version}"],
        capture=True,
    )
    match = re.search(r"^Digest:\s+(sha256:[0-9a-f]{64})$", output, re.MULTILINE)
    if not match:
        raise PublishError(
            f"registry did not return a manifest digest for {repository}:{version}"
        )
    return match.group(1)


def publish(
    version: str, services: list[str], variant: str, metadata_dir: Path
) -> None:
    validate_version(version)
    validate_variant(variant)
    services = validate_services(" ".join(services))
    if not docker_auth_is_configured():
        raise PublishError(
            "GHCR authentication is not configured; log in with `docker login ghcr.io` first"
        )
    revision = current_revision()
    identity = workflow_identity()
    metadata_dir.mkdir(parents=True, exist_ok=True)

    # Each image is built through the existing Make/Compose definition. The
    # variant applies only to STT; CUDA build failures are never retried as CPU.
    for service in services:
        build_args = ["make", "image", f"SERVICE={service}"]
        if service == "stt":
            build_args.append(f"VARIANT={variant}")
        command(build_args)

    for service in services:
        package, expected_role, runtime_variant, lock_label = image_identity(
            service, variant
        )
        image_id = compose_image_id(service, revision, variant)
        platform, labels = local_image_details(image_id)
        expected_labels = {
            LABEL_SERVICE: service,
            LABEL_VARIANT: runtime_variant,
        }
        if lock_label:
            lock_variant = "cpu" if runtime_variant == "cpu" else "cuda"
            lock_path = Path(f"services/requirements-stt-{lock_variant}.lock")
            expected_labels[f"com.speech-platform.{lock_label}"] = hashlib.sha256(
                lock_path.read_bytes()
            ).hexdigest()
        if labels.get(LABEL_REVISION) != revision:
            raise PublishError(
                f"local {service} image source revision label does not match {revision}"
            )
        if labels.get(LABEL_ROLE) != expected_role:
            raise PublishError(
                f"local {service} image role label does not match {expected_role}"
            )
        for label, expected in expected_labels.items():
            if labels.get(label) != expected:
                raise PublishError(
                    f"local {service} image label {label} does not match {expected}"
                )
        if platform != "linux/amd64":
            raise PublishError(
                f"local {service} image platform {platform!r} is not linux/amd64"
            )

        repository = f"{REGISTRY}/{package}"
        tagged = f"{repository}:{version}"
        command(["docker", "image", "tag", image_id, tagged])
        command(["docker", "push", tagged])
        digest = registry_digest(repository, version)
        published_platform, published_labels = published_image_details(
            repository, digest
        )
        if published_platform != platform:
            raise PublishError(
                f"published {service} platform {published_platform} differs from local {platform}"
            )
        if published_labels.get(LABEL_REVISION) != revision:
            raise PublishError(
                f"published {service} source revision label does not match {revision}"
            )
        if published_labels.get(LABEL_ROLE) != expected_role:
            raise PublishError(
                f"published {service} image role label does not match {expected_role}"
            )
        for label, expected in expected_labels.items():
            if published_labels.get(label) != expected:
                raise PublishError(
                    f"published {service} image label {label} does not match {expected}"
                )

        metadata = {
            "service": service,
            "runtime_variant": runtime_variant,
            "git_source_revision": revision,
            "release_version": version,
            "image_repository": repository,
            "oci_digest": digest,
            "platform": published_platform,
            "architecture": published_platform.split("/", 1)[1],
            "build_workflow_identity": identity,
        }
        if lock_label:
            metadata["dependency_lock_sha256"] = expected_labels[
                f"com.speech-platform.{lock_label}"
            ]
        path = metadata_dir / f"{package}-{version}.json"
        path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        print(f"published {repository}@{digest}; metadata: {path}")


def compose_image_id(service: str, revision: str, variant: str) -> str:
    compose_files = ["deployments/compose/compose.yaml"]
    if service == "stt":
        overlay = (
            "compose.stt-cuda-build.yaml"
            if variant == "cuda"
            else "compose.stt-cpu.yaml"
        )
        compose_files.append(f"deployments/compose/{overlay}")
    env = os.environ.copy()
    env.update(
        {
            "SOURCE_REVISION": revision,
            "STT_CPU_LOCK_SHA256": dependency_lock_digest("cpu"),
            "STT_CUDA_LOCK_SHA256": dependency_lock_digest("cuda"),
            "STT_APPLICATION_CONFIG": str(
                Path.cwd() / "configs/stt-application-cpu.example.yaml"
            ),
            "STT_DEPLOYMENT_CONFIG": str(
                Path.cwd() / "configs/stt-deployment-cpu.example.yaml"
            ),
            "STT_MODEL_ROOT": "/models",
        }
    )
    args = ["docker", "compose"]
    for compose_file in compose_files:
        args.extend(["-f", compose_file])
    args.extend(["images", "-q", service])
    output = command(
        args,
        env=env,
        capture=True,
    )
    image_ids = output.splitlines()
    if len(image_ids) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_ids[0]):
        raise PublishError(
            f"expected one Compose image ID for {service}, got {output!r}"
        )
    return image_ids[0]


def dependency_lock_digest(variant: str) -> str:
    return hashlib.sha256(
        Path(f"services/requirements-stt-{variant}.lock").read_bytes()
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--services", required=True)
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="cuda")
    parser.add_argument(
        "--metadata-dir", type=Path, default=Path("dist/release-metadata")
    )
    args = parser.parse_args()
    try:
        validate_version(args.version)
        services = validate_services(args.services)
        publish(args.version, services, args.variant, args.metadata_dir)
    except PublishError as error:
        print(f"publish failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
