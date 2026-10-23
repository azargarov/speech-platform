"""Small Git + Compose operator interface for the canonical product stack."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
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
}


class OperatorError(Exception):
    pass


def run(args: list[str], *, check=True, capture=False, cwd=ROOT):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=capture)
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
    os.environ.update(values)
    os.environ["SOURCE_REVISION"] = source_revision
    os.environ["GATEWAY_CONFIG"] = str(gateway_config_path(values))
    os.environ.pop("GATEWAY_IMAGE", None)
    if gateway_image is not None:
        os.environ["GATEWAY_IMAGE"] = gateway_image


def compose(values, revision, *args, capture=False, gateway_image=None):
    set_compose_env(values, revision, gateway_image=gateway_image)
    command = list(COMPOSE)
    if gateway_uses_local_ollama(gateway_config_path(values)):
        command.extend(["-f", str(ROOT / "deployments/compose/compose.ollama.yaml")])
    return run([*command, *args], capture=capture)


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
    try:
        return ollama_network.prepare_network(
            values.get("OLLAMA_NETWORK_NAME", ollama_network.DEFAULT_NETWORK),
            values.get("OLLAMA_CONTAINER_NAME", ollama_network.DEFAULT_CONTAINER),
        )
    except ollama_network.NetworkError as exc:
        raise OperatorError(str(exc)) from exc


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


def checks(
    *,
    model=True,
    compose_config=True,
    require_clean=False,
    hardware=True,
    release=True,
    require_idle_gpu=False,
    check_port=True,
):
    values = load_env()
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

    if shutil.which("docker") is None:
        raise OperatorError("Docker CLI is not installed")
    run(["docker", "info"], capture=True)
    compose_version = run(["docker", "compose", "version"], capture=True).stdout.strip()
    owns_project = verify_project_ownership(values)
    if check_port:
        check_gateway_port(ip, port, values, owns_project)
    rows = []
    active_gpu_processes = 0
    if hardware:
        if shutil.which("nvidia-smi") is None:
            raise OperatorError("nvidia-smi is required for CUDA STT")
        gpu_query = run(
            [
                "nvidia-smi",
                "--query-gpu=index,uuid,memory.free,memory.total",
                "--format=csv,noheader",
            ],
            capture=True,
        )
        rows = [line.strip() for line in gpu_query.stdout.splitlines() if line.strip()]
        if gpu >= len(rows) or tts_gpu >= len(rows):
            raise OperatorError(
                f"configured STT/TTS GPU device is unavailable; detected {len(rows)} GPU(s)"
            )
        try:
            free_mib = int(rows[gpu].split(",")[2].strip().split()[0])
            tts_free_mib = int(rows[tts_gpu].split(",")[2].strip().split()[0])
        except (IndexError, ValueError) as exc:
            raise OperatorError("could not parse selected GPU free memory") from exc
        if free_mib < 6144:
            raise OperatorError(
                f"selected GPU has {free_mib} MiB free; at least 6144 MiB is required by the STT model profile"
            )
        if tts_free_mib < 8192:
            raise OperatorError(
                f"selected TTS GPU has {tts_free_mib} MiB free; at least 8192 MiB is required at model load"
            )
        runtime = run(
            ["docker", "info", "--format", "{{json .Runtimes}}"], capture=True
        ).stdout.strip()
        if not runtime or "nvidia" not in runtime.lower():
            raise OperatorError("Docker does not report the NVIDIA container runtime")
        processes = run(
            [
                "nvidia-smi",
                "--query-compute-apps=gpu_uuid,pid",
                "--format=csv,noheader",
            ],
            capture=True,
        )
        selected_uuids = {rows[index].split(",")[1].strip() for index in {gpu, tts_gpu}}
        active_gpu_processes = {
            line.split(",")[0].strip()
            for line in processes.stdout.splitlines()
            if "," in line and line.split(",")[0].strip() in selected_uuids
        }
        allowed_processes = 1 if owns_project and gpu == tts_gpu else 0
        if require_idle_gpu and len(active_gpu_processes) > allowed_processes:
            raise OperatorError(
                f"safe installation requires selected GPU(s) idle (or only the existing canonical STT worker); found {len(active_gpu_processes)} active compute process(es). Existing workloads were left untouched."
            )

    revision = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    if (
        require_clean
        and run(["git", "status", "--porcelain"], capture=True).stdout.strip()
    ):
        raise OperatorError(
            "install requires a clean Git checkout; commit or discard local changes first"
        )
    run(
        [
            "go",
            "run",
            "./cmd/gateway",
            "--config",
            str(gateway_config_path(values)),
            "--check-config",
        ]
    )
    run(
        [
            sys.executable,
            "-m",
            "services.stt.main",
            "--config",
            "configs/stt.yaml",
            "--application-config",
            "configs/stt-product-application.yaml",
            "--deployment-config",
            "configs/stt-product-deployment.yaml",
            "--check-config",
        ]
    )
    run(
        [
            sys.executable,
            "-m",
            "services.tts.main",
            "--config",
            "configs/tts.yaml",
            "--check-config",
        ]
    )
    if release:
        run(
            [
                sys.executable,
                "-m",
                "scripts.check_release",
                "--release",
                "releases/voiceservice-v0.1.2.yaml",
            ]
        )
    if model:
        model_command = [
            sys.executable,
            "-m",
            "scripts.provision_models",
            "check",
            "--release",
            "releases/voiceservice-v0.1.2.yaml",
            "--store",
            values["MODEL_STORE"],
        ]
        check = run(model_command, check=False, capture=True)
        if (
            check.returncode
            and "Permission denied" in (check.stderr or "")
            and shutil.which("sudo")
        ):
            privileged = run(["sudo", "-n", *model_command], check=False, capture=True)
            if privileged.returncode == 0:
                check = privileged
            else:
                raise OperatorError(
                    "model store is root-owned; run `sudo -v` to authorize the read-only integrity check, then retry make plan. No artifact changes are performed."
                )
        if check.returncode:
            message = (check.stderr or check.stdout).strip()
            raise OperatorError(
                "persistent model verification failed; preserve the current artifact and correct MODEL_STORE permissions/configuration. "
                + message
            )
        tts_model_command = [
            sys.executable,
            "-m",
            "scripts.tts_model",
            "check",
            "--store",
            values.get("TTS_MODEL_STORE") or values["MODEL_STORE"],
        ]
        tts_check = run(tts_model_command, check=False, capture=True)
        if (
            tts_check.returncode
            and "Permission denied" in (tts_check.stderr or "")
            and shutil.which("sudo")
        ):
            privileged = run(
                ["sudo", "-n", *tts_model_command], check=False, capture=True
            )
            if privileged.returncode == 0:
                tts_check = privileged
            else:
                raise OperatorError(
                    "TTS model store is root-owned; run `sudo -v` to authorize the read-only integrity check"
                )
        if tts_check.returncode:
            message = (tts_check.stderr or tts_check.stdout).strip()
            raise OperatorError(
                "pinned VoxCPM2 artifact is not available or failed verification; run `make tts-model-fetch` after reviewing the artifact terms. "
                + message
            )
        if DIGEST not in check.stdout:
            raise OperatorError(
                "model checker did not verify the pinned large-v3-turbo manifest"
            )
        print(check.stdout.strip())
    if compose_config:
        compose(values, revision, "config", "--quiet")
    return (
        values,
        revision,
        compose_version,
        rows[gpu] if rows else "not checked",
        active_gpu_processes,
    )


def wait_ready(port: int, bind_address: str, timeout=240):
    address = "127.0.0.1" if bind_address == "0.0.0.0" else bind_address
    endpoint = f"http://{address}:{port}/readyz"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        api_ready = False
        try:
            with urlopen(endpoint, timeout=2) as response:
                api_ready = response.status == 200
        except (OSError, URLError):
            pass
        project = run(
            [
                "docker",
                "compose",
                "--env-file",
                str(ROOT / ".env"),
                "-f",
                str(ROOT / "compose.yaml"),
                "ps",
                "--format",
                "json",
            ],
            capture=True,
        )
        services = parse_compose_readiness(project.stdout)
        healthy = {
            item.get("Service")
            for item in services
            if item.get("State") == "running" and item.get("Health") == "healthy"
        }
        if api_ready and healthy >= {"gateway", "stt", "tts"}:
            return
        time.sleep(2)
    raise OperatorError(
        f"Gateway did not become ready within {timeout}s; inspect: make logs"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("plan", "install", "status", "logs", "test-stt")
    )
    parser.add_argument(
        "--service", choices=("gateway",), help="limit install to Gateway"
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
        if args.command == "plan":
            values, revision, compose_version, gpu, active_gpu_processes = checks()
            verified_image = (
                verify_gateway_image(
                    values, revision, expected_image_id, expected_source_revision
                )
                if args.no_build
                else None
            )
            print(
                f"PASS: Docker Compose {compose_version}; source {revision}; GPU {gpu}; model release v0.1.2; manifest {DIGEST}"
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
                print("No-build mode: disabled; Gateway image build remains selected.")
            if gateway_uses_local_ollama(gateway_config_path(values)):
                print(
                    "Local Ollama: enabled; install will prepare network "
                    f"{values.get('OLLAMA_NETWORK_NAME', ollama_network.DEFAULT_NETWORK)} "
                    "and attach container "
                    f"{values.get('OLLAMA_CONTAINER_NAME', ollama_network.DEFAULT_CONTAINER)}."
                )
            else:
                print("Local Ollama: disabled; no Ollama network changes are needed.")
            print("No containers were started or changed.")
        elif args.command == "install":
            values, revision, _version, _gpu, _processes = checks(
                require_clean=True, require_idle_gpu=True
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
            if gateway_uses_local_ollama(gateway_config_path(values)):
                network_result = prepare_local_ollama(values)
                print(
                    "Ollama network: "
                    f"{network_result['network']} {network_result['network_name']}; "
                    f"container {network_result['attachment']} "
                    f"{network_result['container_name']}"
                )
            services = (args.service,) if args.service else ("gateway", "stt", "tts")
            if not args.no_build:
                compose(values, revision, "build", *services)
            checks(require_clean=True, require_idle_gpu=True)
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
                    compose(values, revision, "up", "-d", "--no-deps", "gateway")
            else:
                compose(values, revision, "up", "-d")
            wait_ready(int(values["SPEECH_PORT"]), values["SPEECH_BIND_IP"])
            if gateway_uses_local_ollama(gateway_config_path(values)):
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
        elif args.command == "status":
            values, revision, *_ = checks(
                model=False,
                compose_config=False,
                hardware=False,
                release=False,
                check_port=False,
            )
            compose(values, revision, "ps")
        elif args.command == "logs":
            values, revision, *_ = checks(
                model=False,
                compose_config=False,
                hardware=False,
                release=False,
                check_port=False,
            )
            compose(values, revision, "logs", "--tail", "100", "-f")
        elif args.command == "test-stt":
            values, _revision, *_ = checks(
                model=False,
                compose_config=False,
                hardware=False,
                release=False,
                check_port=False,
            )
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
