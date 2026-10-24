"""Small Git + Compose operator interface for the canonical product stack."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import URLError
from urllib.request import Request, urlopen

import yaml

if __package__:
    from . import ollama_network
else:
    import ollama_network

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DIGEST = "86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6"
TTS_DIGEST = "04d6e05b69b22568030ac21f494e406ffdf2d06efeeab43cfdb4c21ba8c9bd41"
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SOURCE_REVISION_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
GATEWAY_RUNTIME_VARIANT = "foundation"
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(ROOT / ".env"),
    "-f",
    str(ROOT / "compose.yaml"),
]
ALLOWED_ENV = {
    "COMPOSE_PROJECT_NAME",
    "SPEECH_BIND_IP",
    "SPEECH_PORT",
    "SPEECH_API_TOKEN",
    "MODEL_STORE",
    "MODEL_MANIFEST_SHA256",
    "TTS_MODEL_MANIFEST_SHA256",
    "TTS_MODEL_STORE",
    "TTS_MODEL_READ_GID",
    "MODEL_READ_GID",
    "STT_GPU_DEVICE",
    "TTS_GPU_DEVICE",
    "STT_GPU_MEMORY_LIMIT",
    "STT_CPU_LIMIT",
    "STT_PIDS_LIMIT",
    "STT_STOP_GRACE_PERIOD",
    "GATEWAY_MEMORY_LIMIT",
    "GATEWAY_CPU_LIMIT",
    "TTS_GPU_MEMORY_LIMIT",
    "TTS_CPU_LIMIT",
    "TTS_PIDS_LIMIT",
    "TTS_STOP_GRACE_PERIOD",
    "SPEECH_API_URL",
    "GATEWAY_CONFIG",
    "GATEWAY_EXPECTED_IMAGE_ID",
    "GATEWAY_EXPECTED_SOURCE_REVISION",
    "OLLAMA_CONTAINER_NAME",
    "OLLAMA_NETWORK_NAME",
    "GATEWAY_SECRETS_FILE",
    "INSTALL_MIN_FREE_GIB",
}


class OperatorError(Exception):
    pass


def run(args: list[str], *, check=True, capture=False, cwd=None, timeout=60):
    try:
        result = subprocess.run(
            args, cwd=cwd or ROOT, text=True, capture_output=capture, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        raise OperatorError(f"{args[0]} exceeded its bounded command deadline") from exc
    if check and result.returncode:
        details = (result.stderr or result.stdout or "").strip()
        raise OperatorError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{details}"
        )
    return result


def load_env() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.is_file():
        raise OperatorError(".env is missing; run: cp .env.example .env")
    if path.stat().st_mode & 0o077:
        raise OperatorError(".env must be private (mode 0600); run: chmod 600 .env")
    values = {}
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise OperatorError(f".env line {number} must be KEY=value")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise OperatorError(f".env line {number} has an invalid or duplicate key")
        values[key] = value
    unknown = values.keys() - ALLOWED_ENV
    if unknown:
        raise OperatorError(".env contains unknown keys: " + ", ".join(sorted(unknown)))
    return values


def set_compose_env(
    values: dict[str, str], source_revision: str, gateway_image: str | None = None
) -> None:
    for key in ALLOWED_ENV | {
        "COMPOSE_FILE",
        "COMPOSE_PROFILES",
        "COMPOSE_PATH_SEPARATOR",
        "GATEWAY_IMAGE",
        "SOURCE_REVISION",
    }:
        os.environ.pop(key, None)
    os.environ.update(values)
    os.environ["COMPOSE_PROJECT_NAME"] = values.get(
        "COMPOSE_PROJECT_NAME", "speech-platform"
    )
    os.environ["SOURCE_REVISION"] = source_revision
    os.environ["GATEWAY_CONFIG"] = str(gateway_config_path(values))
    os.environ["GATEWAY_SECRETS_FILE"] = str(gateway_secrets_path(values))
    document = yaml.safe_load(gateway_config_path(values).read_text()) or {}
    transform = document.get("text_transform") or {}
    if (
        transform.get("enabled") is not True
        or transform.get("selection", {}).get("allow_cloud") is not True
    ):
        os.environ["GATEWAY_SECRETS_FILE"] = "/dev/null"
    os.environ.pop("GATEWAY_IMAGE", None)
    if gateway_image is not None:
        os.environ["GATEWAY_IMAGE"] = gateway_image


def compose(values, revision, *args, capture=False, gateway_image=None):
    set_compose_env(values, revision, gateway_image=gateway_image)
    command = list(COMPOSE)
    if gateway_uses_local_ollama(gateway_config_path(values)):
        command.extend(["-f", str(ROOT / "deployments/compose/compose.ollama.yaml")])
    return run(
        [*command, *args],
        capture=capture,
        timeout=1800
        if args and args[0] == "build"
        else 300
        if args and args[0] in {"up", "run", "stop", "down"}
        else 60,
    )


def validate_no_build_options(
    command: str,
    service: str | None,
    no_build: bool,
    expected_image_id: str | None,
    configured_image_id: str | None,
    expected_source_revision: str | None,
    configured_source_revision: str | None,
) -> tuple[str, str] | None:
    if (
        expected_image_id is not None or expected_source_revision is not None
    ) and not no_build:
        raise OperatorError("expected image/source identity requires --no-build")
    if not no_build:
        return None
    if command not in {"plan", "install"}:
        raise OperatorError("--no-build is supported only for plan/install")
    if service != "gateway":
        raise OperatorError("--no-build is supported only with --service gateway")
    for cli_value, configured_value, flag, setting in (
        (
            expected_image_id,
            configured_image_id,
            "--expected-image-id",
            "GATEWAY_EXPECTED_IMAGE_ID",
        ),
        (
            expected_source_revision,
            configured_source_revision,
            "--expected-source-revision",
            "GATEWAY_EXPECTED_SOURCE_REVISION",
        ),
    ):
        if (
            cli_value is not None
            and configured_value is not None
            and cli_value != configured_value
        ):
            raise OperatorError(f"{flag} conflicts with {setting}")
    image_id = expected_image_id or configured_image_id
    if image_id is None:
        raise OperatorError(
            "--no-build requires GATEWAY_EXPECTED_IMAGE_ID or --expected-image-id"
        )
    if not IMAGE_ID_PATTERN.fullmatch(image_id):
        raise OperatorError("--expected-image-id must be a full sha256 image ID")
    source_revision = expected_source_revision or configured_source_revision
    if source_revision is None:
        raise OperatorError(
            "--no-build requires GATEWAY_EXPECTED_SOURCE_REVISION or --expected-source-revision"
        )
    if not SOURCE_REVISION_PATTERN.fullmatch(source_revision):
        raise OperatorError("expected source revision must be a full Git revision")
    return image_id, source_revision


def verify_gateway_image(
    values: dict,
    revision: str,
    expected_image_id: str,
    expected_source_revision: str,
) -> dict:
    """Validate the configured local Gateway tag without pulling or building."""
    if not SOURCE_REVISION_PATTERN.fullmatch(expected_source_revision):
        raise OperatorError("expected source revision must be a full Git revision")
    clean = run(["git", "status", "--porcelain"], check=False, capture=True)
    if clean.returncode or clean.stdout.strip():
        raise OperatorError("no-build mode requires a clean Git checkout")
    ancestor = run(
        ["git", "merge-base", "--is-ancestor", expected_source_revision, revision],
        check=False,
        capture=True,
    )
    if ancestor.returncode:
        raise OperatorError("expected image source revision is not an ancestor of HEAD")
    build_inputs = (
        ".dockerignore",
        "go.mod",
        "go.sum",
        "cmd",
        "internal",
        "deployments/compose/gateway.Dockerfile",
    )
    source_diff = run(
        [
            "git",
            "diff",
            "--quiet",
            expected_source_revision,
            revision,
            "--",
            *build_inputs,
        ],
        check=False,
        capture=True,
    )
    if source_diff.returncode:
        raise OperatorError(
            "Gateway build inputs differ from the image source revision"
        )

    expected_reference = f"speech-platform-gateway:{expected_source_revision}"
    rendered = compose(
        values,
        revision,
        "config",
        "--format",
        "json",
        capture=True,
        gateway_image=expected_reference,
    )
    try:
        config = json.loads(rendered.stdout)
        image_reference = config["services"]["gateway"]["image"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise OperatorError("could not resolve the configured Gateway image") from exc
    if not isinstance(image_reference, str) or not image_reference:
        raise OperatorError("configured Gateway image reference is missing")
    if image_reference != expected_reference:
        raise OperatorError(
            "configured Gateway image tag does not match source revision"
        )

    result = run(
        ["docker", "image", "inspect", image_reference],
        check=False,
        capture=True,
    )
    if result.returncode:
        raise OperatorError(
            f"configured Gateway image is not available locally: {image_reference}"
        )
    try:
        images = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise OperatorError("Gateway image inspection returned invalid JSON") from exc
    if (
        not isinstance(images, list)
        or len(images) != 1
        or not isinstance(images[0], dict)
    ):
        raise OperatorError("Gateway image reference is missing or ambiguous")
    image = images[0]
    if image.get("Id") != expected_image_id:
        raise OperatorError("Gateway image ID does not match --expected-image-id")

    labels = (image.get("Config") or {}).get("Labels")
    expected_labels = {
        "org.opencontainers.image.revision": expected_source_revision,
        "com.speech-platform.service": "gateway",
        "com.speech-platform.service-role": "gateway",
        "com.speech-platform.runtime-variant": GATEWAY_RUNTIME_VARIANT,
    }
    if not isinstance(labels, dict):
        raise OperatorError("Gateway image is missing required OCI labels")
    for name, value in expected_labels.items():
        if labels.get(name) != value:
            raise OperatorError(f"Gateway image label mismatch: {name}")
    if image.get("Os") != "linux" or image.get("Architecture") != "amd64":
        raise OperatorError("Gateway image platform must be linux/amd64")
    return {
        "reference": image_reference,
        "image_id": image["Id"],
        "revision": expected_source_revision,
        "runtime_variant": GATEWAY_RUNTIME_VARIANT,
    }


def gateway_config_path(values: dict[str, str]) -> Path:
    """Resolve a tracked or private Gateway config without following symlinks."""
    configured = Path(values.get("GATEWAY_CONFIG", "configs/gateway.yaml"))
    source = configured if configured.is_absolute() else ROOT / configured
    root = ROOT.resolve()
    try:
        resolved = source.resolve(strict=True)
    except OSError as exc:
        raise OperatorError("configured Gateway config file was not found") from exc
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise OperatorError("GATEWAY_CONFIG must identify a file inside the repository")

    current = root
    try:
        relative = source.absolute().relative_to(root)
    except ValueError as exc:
        raise OperatorError("GATEWAY_CONFIG must be inside the repository") from exc
    if ".." in relative.parts:
        raise OperatorError("GATEWAY_CONFIG must not use parent-directory traversal")
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise OperatorError("GATEWAY_CONFIG must not traverse symlinks")
    return resolved


def gateway_secrets_path(values):
    configured = Path(values.get("GATEWAY_SECRETS_FILE", "private/cloud.env"))
    path = configured if configured.is_absolute() else ROOT / configured
    root = ROOT.resolve()
    try:
        relative = path.absolute().relative_to(root)
    except ValueError as exc:
        raise OperatorError("GATEWAY_SECRETS_FILE must be inside private/") from exc
    if ".." in relative.parts or not path.resolve().is_relative_to(root / "private"):
        raise OperatorError(
            "GATEWAY_SECRETS_FILE must be inside private/, without traversal"
        )
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise OperatorError("GATEWAY_SECRETS_FILE must not traverse symlinks")
    return path.absolute()


def gateway_uses_local_ollama(config_path: Path | None = None) -> bool:
    """Select the optional Ollama network only for an enabled local model."""
    path = config_path or gateway_config_path({})
    try:
        document = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise OperatorError(f"could not read Gateway config {path}") from exc
    if not isinstance(document, dict):
        raise OperatorError("Gateway config must contain a YAML mapping")
    transform = document.get("text_transform")
    if transform is None:
        return False
    if not isinstance(transform, dict):
        raise OperatorError("text_transform config must be a mapping")
    if transform.get("enabled") is not True:
        return False
    providers = transform.get("providers") or []
    models = transform.get("models") or []
    if not isinstance(providers, list) or not isinstance(models, list):
        raise OperatorError("text_transform providers and models must be lists")
    provider_by_id = {
        item.get("id"): item for item in providers if isinstance(item, dict)
    }
    active = False
    for model in models:
        if not isinstance(model, dict) or model.get("enabled") is not True:
            continue
        provider = provider_by_id.get(model.get("provider"))
        if (
            not provider
            or provider.get("type") != "ollama"
            or provider.get("locality") != "local"
        ):
            continue
        try:
            endpoint = urlparse(str(provider.get("endpoint", "")))
            port = endpoint.port
        except ValueError as exc:
            raise OperatorError(
                "enabled local Ollama provider endpoint is invalid"
            ) from exc
        if (
            endpoint.scheme != "http"
            or endpoint.hostname != "ollama"
            or port != 11434
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
        ):
            raise OperatorError(
                "enabled local Ollama providers must use http://ollama:11434"
            )
        active = True
    return active


def prepare_local_ollama(values: dict[str, str]) -> dict[str, str]:
    """Reuse external infrastructure; never attach, stop, or recreate shared Ollama."""
    network = values.get("OLLAMA_NETWORK_NAME", ollama_network.DEFAULT_NETWORK)
    container = values.get("OLLAMA_CONTAINER_NAME", ollama_network.DEFAULT_CONTAINER)
    info = json.loads(run(["docker", "inspect", container], capture=True).stdout)[0]
    attachment = info.get("NetworkSettings", {}).get("Networks", {}).get(network)
    if (
        not info.get("State", {}).get("Running")
        or not attachment
        or "ollama" not in (attachment.get("Aliases") or [])
    ):
        raise OperatorError(
            "shared Ollama must already be attached to its configured private network with alias ollama; ask its owner to prepare it"
        )
    return {
        "network": "reused",
        "network_name": network,
        "attachment": "reused",
        "container_name": container,
    }


def require_local_docker():
    # Docker gives DOCKER_CONTEXT precedence over DOCKER_HOST.
    context = os.environ.get("DOCKER_CONTEXT")
    endpoint = None if context else os.environ.get("DOCKER_HOST")
    if not endpoint:
        args = ["docker", "context", "inspect", *([context] if context else [])]
        try:
            data = json.loads(run(args, capture=True).stdout)
            endpoint = data[0].get("Endpoints", {}).get("docker", {}).get("Host", "")
        except (ValueError, IndexError, KeyError, TypeError) as exc:
            raise OperatorError(
                "could not inspect the active Docker context; explicitly select a local Unix context"
            ) from exc
    if not isinstance(endpoint, str) or not endpoint.startswith("unix://"):
        raise OperatorError(
            "this installer requires the local Unix Docker endpoint; explicitly select a local Docker context/unset remote DOCKER_HOST"
        )


def verify_project_ownership(values):
    project = values.get("COMPOSE_PROJECT_NAME", "speech-platform")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
        raise OperatorError("COMPOSE_PROJECT_NAME contains invalid characters")
    result = run(["docker", "compose", "ls", "--format", "json"], capture=True)
    try:
        entries = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise OperatorError(
            "Docker Compose project listing was not valid JSON"
        ) from exc
    owned = False
    for entry in entries:
        if entry.get("Name") != project:
            continue
        config_files = [
            str(Path(path).resolve())
            for path in entry.get("ConfigFiles", "").split(",")
        ]
        canonical = str((ROOT / "compose.yaml").resolve())
        if canonical not in config_files:
            raise OperatorError(
                f"Compose project name {project!r} is already owned by another deployment"
            )
        owned = True
    return owned


def check_gateway_port(ip: str, port: int, values, owns_project: bool) -> None:
    """Reserve a free port, or accept its existing canonical Gateway owner."""
    port_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        port_probe.bind((ip, port))
        return
    except OSError as exc:
        if exc.errno not in {98, 10048}:
            raise OperatorError(f"Gateway port {ip}:{port} cannot be reserved") from exc
    finally:
        port_probe.close()

    if owns_project:
        project = values.get("COMPOSE_PROJECT_NAME", "speech-platform")
        canonical = str((ROOT / "compose.yaml").resolve())
        containers = run(
            ["docker", "ps", "--filter", f"publish={port}", "--format", "{{.ID}}"],
            capture=True,
        ).stdout.splitlines()
        if len(containers) == 1:
            inspected = run(["docker", "inspect", containers[0]], capture=True)
            try:
                data = json.loads(inspected.stdout)
            except json.JSONDecodeError as exc:
                raise OperatorError(
                    "Docker container inspection was not valid JSON"
                ) from exc
            if len(data) == 1:
                container = data[0]
                labels = (container.get("Config") or {}).get("Labels") or {}
                config_files = {
                    str(Path(path).resolve())
                    for path in labels.get(
                        "com.docker.compose.project.config_files", ""
                    ).split(",")
                    if path
                }
                bindings = (
                    (container.get("NetworkSettings") or {}).get("Ports") or {}
                ).get("8080/tcp") or []
                matching_bindings = [
                    binding
                    for binding in bindings
                    if binding.get("HostIp") == ip
                    and binding.get("HostPort") == str(port)
                ]
                if (
                    container.get("State", {}).get("Running") is True
                    and labels.get("com.docker.compose.project") == project
                    and labels.get("com.docker.compose.service") == "gateway"
                    and str(ROOT.resolve())
                    == labels.get("com.docker.compose.project.working_dir")
                    and canonical in config_files
                    and len(matching_bindings) == 1
                    and len(bindings) == 1
                ):
                    return
    raise OperatorError(f"Gateway port {ip}:{port} is already in use")


def parse_compose_readiness(output: str, expected=None) -> list[dict]:
    expected = expected or {"gateway", "stt", "tts"}
    try:
        services = json.loads(output or "[]")
    except json.JSONDecodeError:
        try:
            services = [
                json.loads(line) for line in output.splitlines() if line.strip()
            ]
        except json.JSONDecodeError as exc:
            raise OperatorError(
                "Compose readiness response was not valid JSON"
            ) from exc
    if isinstance(services, dict):
        services = [services]
    if not isinstance(services, list) or any(
        not isinstance(item, dict) for item in services
    ):
        raise OperatorError("Compose readiness response was not valid JSON")
    names = [item.get("Service") for item in services]
    if any(not isinstance(name, str) for name in names):
        raise OperatorError("Compose readiness response had an unexpected service set")
    if len(names) != len(set(names)) or set(names) != expected:
        raise OperatorError("Compose readiness response had an unexpected service set")
    return services


def require_existing_workers_healthy(values, revision) -> None:
    set_compose_env(values, revision)
    result = run([*COMPOSE, "ps", "--format", "json", "stt", "tts"], capture=True)
    services = parse_compose_readiness(result.stdout, expected={"stt", "tts"})
    healthy = {
        item.get("Service")
        for item in services
        if item.get("State") == "running" and item.get("Health") == "healthy"
    }
    if healthy != {"stt", "tts"}:
        raise OperatorError(
            "Gateway-only install requires the existing STT and TTS services to be healthy"
        )


def validate_environment(values):
    required = {
        "MODEL_STORE",
        "MODEL_MANIFEST_SHA256",
        "TTS_MODEL_MANIFEST_SHA256",
        "SPEECH_BIND_IP",
        "SPEECH_PORT",
        "STT_GPU_DEVICE",
        "TTS_GPU_DEVICE",
    }
    missing = required - values.keys()
    if missing:
        raise OperatorError(
            ".env is missing required keys: " + ", ".join(sorted(missing))
        )
    if values["MODEL_MANIFEST_SHA256"] != DIGEST:
        raise OperatorError("MODEL_MANIFEST_SHA256 must match the pinned v0.1.2 model")
    if values["TTS_MODEL_MANIFEST_SHA256"] != TTS_DIGEST:
        raise OperatorError(
            "TTS_MODEL_MANIFEST_SHA256 must match the pinned VoxCPM2 artifact"
        )
    if not Path(values["MODEL_STORE"]).is_absolute():
        raise OperatorError("MODEL_STORE must be an absolute host path")
    if (
        values.get("TTS_MODEL_STORE")
        and not Path(values["TTS_MODEL_STORE"]).is_absolute()
    ):
        raise OperatorError("TTS_MODEL_STORE must be an absolute host path")
    try:
        port = int(values["SPEECH_PORT"])
        gpu = int(values["STT_GPU_DEVICE"])
        tts_gpu = int(values["TTS_GPU_DEVICE"])
        ip = str(ipaddress.IPv4Address(values["SPEECH_BIND_IP"]))
    except ValueError as exc:
        raise OperatorError(
            "SPEECH_PORT, STT_GPU_DEVICE, TTS_GPU_DEVICE or SPEECH_BIND_IP is invalid"
        ) from exc
    if not 1 <= port <= 65535 or gpu < 0 or tts_gpu < 0:
        raise OperatorError(
            "SPEECH_PORT or a GPU device index is outside its valid range"
        )
    if not socket.inet_aton(ip):
        raise OperatorError("SPEECH_BIND_IP must resolve to an IPv4 address")
    if not ipaddress.ip_address(ip).is_loopback:
        if len(values.get("SPEECH_API_TOKEN", "")) < 32:
            raise OperatorError(
                "non-loopback SPEECH_BIND_IP requires a 32-character SPEECH_API_TOKEN"
            )
        parsed_api = urlparse(values.get("SPEECH_API_URL", ""))
        if parsed_api.scheme != "https" or not parsed_api.hostname:
            raise OperatorError(
                "non-loopback API use requires a TLS reverse proxy; set SPEECH_API_URL to its https endpoint"
            )
    if (
        values.get("MODEL_READ_GID", "988").isdecimal() is False
        or not 1 <= int(values.get("MODEL_READ_GID", "988")) <= 2147483647
    ):
        raise OperatorError("MODEL_READ_GID must be in 1..2147483647")
    if (
        values.get(
            "TTS_MODEL_READ_GID", values.get("MODEL_READ_GID", "988")
        ).isdecimal()
        is False
        or not 1
        <= int(values.get("TTS_MODEL_READ_GID", values.get("MODEL_READ_GID", "988")))
        <= 2147483647
    ):
        raise OperatorError("TTS_MODEL_READ_GID must be in 1..2147483647")
    try:
        ollama_network.validate_names(
            values.get("OLLAMA_NETWORK_NAME", ollama_network.DEFAULT_NETWORK),
            values.get("OLLAMA_CONTAINER_NAME", ollama_network.DEFAULT_CONTAINER),
        )
    except ollama_network.NetworkError as exc:
        raise OperatorError(str(exc)) from exc
    if "SPEECH_API_URL" in values:
        parsed_api = urlparse(values["SPEECH_API_URL"])
        if (
            parsed_api.username
            or parsed_api.password
            or parsed_api.query
            or parsed_api.fragment
            or parsed_api.path not in ("", "/")
        ):
            raise OperatorError(
                "SPEECH_API_URL must be an origin without credentials, query or path"
            )
        if parsed_api.scheme == "http" and parsed_api.hostname not in {
            "127.0.0.1",
            "localhost",
        }:
            raise OperatorError("HTTP SPEECH_API_URL is allowed only for loopback")
        if parsed_api.scheme not in {"http", "https"} or not parsed_api.hostname:
            raise OperatorError("SPEECH_API_URL must be an HTTP(S) origin")

    gateway_secrets_path(values)
    try:
        minimum_disk = int(values.get("INSTALL_MIN_FREE_GIB", "20"))
        if not 1 <= minimum_disk <= 1024:
            raise ValueError
    except ValueError as exc:
        raise OperatorError("INSTALL_MIN_FREE_GIB must be in 1..1024") from exc
    return ip, port, gpu, tts_gpu


def checks(
    *,
    model=True,
    compose_config=True,
    require_clean=False,
    hardware=True,
    release=True,
    require_idle_gpu=False,
    check_port=True,
    service=None,
):
    if __package__:
        from .installation_preflight import collect
    else:
        from installation_preflight import collect
    report = collect(
        sys.modules[__name__],
        service=service,
        model=model,
        compose_config=compose_config,
        require_clean=require_clean,
        hardware=hardware,
        check_port=check_port,
    )
    report.display()
    if report.failed:
        raise OperatorError(
            "preflight found blocking failures; resolve FAIL entries and retry"
        )
    return report.values, report.revision, report.compose_version, report.gpu, 0


def verify_service_images(values, revision, services):
    rendered = json.loads(
        compose(values, revision, "config", "--format", "json", capture=True).stdout
    )
    identities = {}
    for service in services:
        reference = rendered["services"][service]["image"]
        image = json.loads(
            run(["docker", "image", "inspect", reference], capture=True).stdout
        )[0]
        labels = image.get("Config", {}).get("Labels") or {}
        expected = {
            "org.opencontainers.image.revision": revision,
            "com.speech-platform.service": service,
            "com.speech-platform.service-role": "gateway"
            if service == "gateway"
            else service + "-worker",
            "com.speech-platform.runtime-variant": "foundation"
            if service == "gateway"
            else "cuda",
        }
        if (
            image.get("Os") != "linux"
            or image.get("Architecture") != "amd64"
            or any(labels.get(k) != v for k, v in expected.items())
        ):
            raise OperatorError(
                f"{service} image platform/source/role validation failed"
            )
        identities[service] = {"reference": reference, "image_id": image["Id"]}
    return identities


def verify_running_images(values, revision, identities):
    for service, identity in identities.items():
        cid = compose(
            values, revision, "ps", "-q", service, capture=True
        ).stdout.strip()
        if not cid or "\n" in cid:
            raise OperatorError(f"{service} has no unique running container")
        reference = identity["reference"]
        image = json.loads(
            run(["docker", "image", "inspect", reference], capture=True).stdout
        )[0]
        if image["Id"] != identity["image_id"]:
            raise OperatorError(f"{service} image tag changed after verification")
        container = json.loads(run(["docker", "inspect", cid], capture=True).stdout)[0]
        descriptor = image.get("Descriptor") or {}
        if "index" in descriptor.get(
            "mediaType", ""
        ) or "manifest.list" in descriptor.get("mediaType", ""):
            # Containerd stores index/attestation identity separately from executable platform content.
            platform = json.loads(
                run(
                    [
                        "docker",
                        "image",
                        "inspect",
                        "--platform",
                        "linux/amd64",
                        reference,
                    ],
                    capture=True,
                ).stdout
            )[0]
            expected = platform["Id"]
            actual = (container.get("ImageManifestDescriptor") or {}).get("digest")
        else:
            expected = image["Id"]
            actual = container.get("Image")
        if actual != expected:
            raise OperatorError(
                f"{service} running platform image differs from the verified build"
            )


def gpu_check(values, revision, services):
    rendered = json.loads(
        compose(values, revision, "config", "--format", "json", capture=True).stdout
    )
    for service in services:
        if service not in {"stt", "tts"}:
            continue
        image = rendered["services"][service]["image"]
        device = values.get(service.upper() + "_GPU_DEVICE", "0")
        # Explicit qualification action, not part of read-only preflight. No model import/load.
        probe = "import ctypes; c=ctypes.CDLL('libcuda.so.1'); assert c.cuInit(0)==0; n=ctypes.c_int(); assert c.cuDeviceGetCount(ctypes.byref(n))==0 and n.value>0; print('PASS: container CUDA driver device access')"
        probe_name = "speech-platform-gpu-check-" + uuid.uuid4().hex
        try:
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    probe_name,
                    "--pull",
                    "never",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--gpus",
                    f"device={device}",
                    "--entrypoint",
                    "python",
                    image,
                    "-c",
                    probe,
                ],
                timeout=60,
            )
        except (OperatorError, OSError) as error:
            try:
                cleanup = run(
                    ["docker", "rm", "-f", probe_name],
                    check=False,
                    capture=True,
                    timeout=15,
                )
                absent = "No such container" in (
                    getattr(cleanup, "stderr", "") or ""
                ) or "No such object" in (getattr(cleanup, "stderr", "") or "")
                if cleanup.returncode and not absent:
                    raise OperatorError("cleanup unconfirmed")
            except (OperatorError, OSError) as cleanup_error:
                raise OperatorError(
                    f"CUDA probe failed; cleanup unconfirmed for {probe_name}; inspect that probe before retrying"
                ) from cleanup_error
            raise OperatorError(
                "CUDA probe failed; selected services were not started"
            ) from error


def wait_ready(port: int, bind_address: str, services=None, timeout=240):
    selected = set(services or ("gateway", "stt", "tts"))
    values = load_env()
    revision = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    address = "127.0.0.1" if bind_address == "0.0.0.0" else bind_address
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = compose(
                values,
                revision,
                "ps",
                "--format",
                "json",
                *sorted(selected),
                capture=True,
            )
            entries = parse_compose_readiness(result.stdout, expected=selected)
            healthy = {
                s["Service"]
                for s in entries
                if s.get("State") == "running" and s.get("Health") == "healthy"
            }
            if healthy == selected:
                if "gateway" not in selected:
                    return
                with urlopen(f"http://{address}:{port}/readyz", timeout=2) as response:
                    if response.status == 200:
                        return
        except (OSError, URLError, OperatorError):
            pass
        time.sleep(2)
    raise OperatorError(
        f"selected services did not become ready within {timeout}s; inspect make logs"
    )


def operational_values():
    values = load_env()
    validate_environment(values)
    require_local_docker()
    verify_project_ownership(values)
    revision = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    return values, revision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "preflight",
            "plan",
            "install",
            "status",
            "logs",
            "test-stt",
            "gpu-check",
            "stop",
            "remove",
        ),
    )
    parser.add_argument(
        "--service",
        choices=("gateway", "stt", "tts"),
        help="operate only on the selected service",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="use an already local, identity-verified Gateway image (Gateway only)",
    )
    parser.add_argument(
        "--expected-image-id",
        help="required full sha256 image ID for --no-build",
    )
    parser.add_argument(
        "--expected-source-revision",
        help="full Git source revision for the approved image in --no-build mode",
    )
    parser.add_argument("--audio", type=Path)
    parser.add_argument(
        "--source-language", choices=("auto", "ru", "en", "sv"), default="auto"
    )
    parser.add_argument(
        "--output-language", choices=("auto", "ru", "en", "sv"), default="auto"
    )
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            if args.no_build or args.expected_image_id or args.expected_source_revision:
                parser.error(
                    "preflight is read-only; use plan/install for Gateway --no-build identity options"
                )
            if __package__:
                from .installation_preflight import collect
            else:
                from installation_preflight import collect
            report = collect(sys.modules[__name__], service=args.service)
            report.display()
            return 2 if report.failed else 0
        values = load_env()
        no_build_identity = validate_no_build_options(
            args.command,
            args.service,
            args.no_build,
            args.expected_image_id,
            values.get("GATEWAY_EXPECTED_IMAGE_ID"),
            args.expected_source_revision,
            values.get("GATEWAY_EXPECTED_SOURCE_REVISION"),
        )
        expected_image_id, expected_source_revision = (
            no_build_identity if no_build_identity is not None else (None, None)
        )
        if args.command in {"preflight", "plan"}:
            values, revision, compose_version, gpu, active_gpu_processes = checks(
                service=args.service
            )
            if args.command == "preflight":
                return 0
            verified_image = (
                verify_gateway_image(
                    values, revision, expected_image_id, expected_source_revision
                )
                if args.no_build
                else None
            )
            print(
                f"PASS: Docker Compose {compose_version}; source {revision}; GPU {gpu}; pinned model manifests; STT {DIGEST}"
            )
            endpoint = values.get(
                "SPEECH_API_URL",
                f"http://{values['SPEECH_BIND_IP']}:{values['SPEECH_PORT']}",
            )
            print(
                f"Plan: project={values.get('COMPOSE_PROJECT_NAME', 'speech-platform')} API={endpoint} model={values['MODEL_STORE']}/{DIGEST}"
            )
            print(f"Selected GPU compute processes: {active_gpu_processes}")
            if verified_image:
                print(
                    "No-build mode: enabled; local Gateway image "
                    f"{verified_image['reference']} ID {verified_image['image_id']} "
                    f"revision {verified_image['revision']} variant "
                    f"{verified_image['runtime_variant']}"
                )
            else:
                print(
                    "No-build mode: disabled; selected service image builds remain enabled."
                )
            if gateway_uses_local_ollama(gateway_config_path(values)):
                print(
                    "Local Ollama: enabled; requires existing private network "
                    f"{values.get('OLLAMA_NETWORK_NAME', ollama_network.DEFAULT_NETWORK)} "
                    "and attached shared container "
                    f"{values.get('OLLAMA_CONTAINER_NAME', ollama_network.DEFAULT_CONTAINER)}."
                )
            else:
                print("Local Ollama: disabled; no Ollama network changes are needed.")
            print("No containers were started or changed.")
        elif args.command == "install":
            values, revision, _version, _gpu, _processes = checks(
                require_clean=True, service=args.service
            )
            if args.no_build:
                verified_image = verify_gateway_image(
                    values,
                    revision,
                    expected_image_id,
                    expected_source_revision,
                )
                print(
                    "No-build mode: enabled; validated local Gateway image "
                    f"{verified_image['reference']} ID {verified_image['image_id']}"
                )
            if args.service == "gateway":
                require_existing_workers_healthy(values, revision)
            if (args.service in (None, "gateway")) and gateway_uses_local_ollama(
                gateway_config_path(values)
            ):
                network_result = prepare_local_ollama(values)
                print(
                    "Ollama network: "
                    f"{network_result['network']} {network_result['network_name']}; "
                    f"container {network_result['attachment']} "
                    f"{network_result['container_name']}"
                )
            services = (args.service,) if args.service else ("gateway", "stt", "tts")
            config_hash = hashlib.sha256(
                gateway_config_path(values).read_bytes()
            ).digest()
            identities = (
                {
                    "gateway": {
                        "reference": verified_image["reference"],
                        "image_id": expected_image_id,
                    }
                }
                if args.no_build
                else {}
            )
            if not args.no_build:
                compose(values, revision, "build", *services)
                identities = verify_service_images(values, revision, services)
                gpu_check(values, revision, services)
            current_values, current_revision, *_ = checks(
                require_clean=True, service=args.service
            )
            if (
                current_values != values
                or current_revision != revision
                or hashlib.sha256(gateway_config_path(values).read_bytes()).digest()
                != config_hash
            ):
                raise OperatorError(
                    "source or deployment configuration changed during build; review and retry before service creation"
                )
            if args.service == "gateway":
                if args.no_build:
                    # Recheck after all preflight/network work and directly before
                    # Compose can recreate the container.
                    verified_image = verify_gateway_image(
                        values,
                        revision,
                        expected_image_id,
                        expected_source_revision,
                    )
                    compose(
                        values,
                        revision,
                        "up",
                        "--no-build",
                        "--pull",
                        "never",
                        "-d",
                        "--no-deps",
                        "gateway",
                        gateway_image=verified_image["reference"],
                    )
                else:
                    compose(
                        values,
                        revision,
                        "up",
                        "-d",
                        "--no-build",
                        "--pull",
                        "never",
                        "--no-deps",
                        "gateway",
                    )
            elif args.service:
                compose(
                    values,
                    revision,
                    "up",
                    "-d",
                    "--no-build",
                    "--pull",
                    "never",
                    "--no-deps",
                    args.service,
                )
            else:
                compose(values, revision, "up", "-d", "--no-build", "--pull", "never")
            wait_ready(int(values["SPEECH_PORT"]), values["SPEECH_BIND_IP"], services)
            verify_running_images(values, revision, identities)
            if (args.service in (None, "gateway")) and gateway_uses_local_ollama(
                gateway_config_path(values)
            ):
                compose(
                    values,
                    revision,
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    *(["--pull", "never"] if args.no_build else []),
                    "gateway",
                    "--config",
                    "/config/gateway.yaml",
                    "--check-ollama",
                    gateway_image=(
                        verified_image["reference"] if args.no_build else None
                    ),
                )
            endpoint = values.get(
                "SPEECH_API_URL",
                f"http://{values['SPEECH_BIND_IP']}:{values['SPEECH_PORT']}",
            )
            print(f"Ready: {endpoint}")
        elif args.command in {"gpu-check", "stop", "remove"}:
            revision = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
            validate_environment(values)
            require_local_docker()
            verify_project_ownership(values)
            services = (args.service,) if args.service else ("gateway", "stt", "tts")
            if args.command == "gpu-check":
                verify_service_images(values, revision, services)
                gpu_check(values, revision, services)
            elif args.command == "stop":
                compose(values, revision, "stop", *services)
            elif args.service:
                compose(values, revision, "stop", args.service)
                compose(values, revision, "rm", "-f", args.service)
            else:
                compose(
                    values, revision, "down"
                )  # no volumes/images or external networks removed
        elif args.command == "status":
            values, revision = operational_values()
            compose(values, revision, "ps", *((args.service,) if args.service else ()))
        elif args.command == "logs":
            values, revision = operational_values()
            compose(
                values,
                revision,
                "logs",
                "--tail",
                "100",
                *((args.service,) if args.service else ()),
            )
        elif args.command == "test-stt":
            values, _revision = operational_values()
            if args.audio is None or not args.audio.is_file():
                raise OperatorError(
                    "provide an existing local --audio file; audio remains on this machine"
                )
            if args.audio.stat().st_size > 25 * 1024 * 1024 - 1024:
                raise OperatorError(
                    "audio file must fit within the 25 MiB request limit"
                )
            import mimetypes
            import uuid
            import urllib.error

            boundary = "----speech-platform-" + uuid.uuid4().hex
            filename = args.audio.name
            media = {
                ".wav": "audio/wav",
                ".flac": "audio/flac",
                ".mp3": "audio/mpeg",
                ".ogg": "audio/ogg",
                ".opus": "audio/ogg",
                ".m4a": "audio/mp4",
                ".mp4": "audio/mp4",
            }.get(
                args.audio.suffix.lower(),
                mimetypes.guess_type(filename)[0] or "application/octet-stream",
            )
            body = bytearray()

            def field(name, value):
                body.extend(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
                )

            body.extend(
                f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="{filename}"\r\nContent-Type: {media}\r\n\r\n'.encode()
            )
            body.extend(args.audio.read_bytes())
            body.extend(b"\r\n")
            field("source_language", args.source_language)
            field("output_language", args.output_language)
            body.extend(f"--{boundary}--\r\n".encode())
            base_url = values.get(
                "SPEECH_API_URL", f"http://127.0.0.1:{values['SPEECH_PORT']}"
            ).rstrip("/")
            request = Request(
                f"{base_url}/v1/stt/transcriptions",
                data=bytes(body),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            token = values.get("SPEECH_API_TOKEN", "")
            if token:
                request.add_header("Authorization", "Bearer " + token)
            try:
                with urlopen(request, timeout=195) as response:
                    result = json.loads(response.read())
            except urllib.error.HTTPError as exc:
                raise OperatorError(
                    f"STT request failed ({exc.code}): {exc.read(2048).decode(errors='replace')}"
                ) from exc
            print(
                json.dumps(
                    {
                        key: result.get(key)
                        for key in (
                            "detected_language",
                            "source_language",
                            "output_language",
                            "translated",
                            "language_probability",
                        )
                        if key in result
                    },
                    ensure_ascii=False,
                )
            )
            print(result.get("text", ""))
        return 0
    except (OperatorError, OSError, ValueError) as exc:
        print(f"speech-platform: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
