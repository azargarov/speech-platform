"""Read-only prerequisite report for the existing Git + Compose installer."""

from __future__ import annotations

import json
import ipaddress
import argparse
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from urllib.parse import urlparse
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

import yaml

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.worker.server import StrictLoader
from scripts.release_manifest import load_release
from services.stt.artifacts import load_artifact_manifest
from scripts import ollama_network

GROUPS = ("Host", "GPU", "Models", "Networking", "External Providers", "Deployment")
STATUSES = ("PASS", "WARN", "FAIL", "SKIP")
ROOT = Path(__file__).resolve().parents[1]
STT_MANIFEST_SHA256 = "86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6"
TTS_MANIFEST_SHA256 = "04d6e05b69b22568030ac21f494e406ffdf2d06efeeab43cfdb4c21ba8c9bd41"
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


class PreflightError(ValueError):
    """A safe configuration or prerequisite validation error."""


def run_command(args, *, root=ROOT, timeout=60, env=None):
    """Run a bounded inspection/configuration command without shell expansion."""
    result = subprocess.run(
        args, cwd=root, text=True, capture_output=True, timeout=timeout, env=env
    )
    if result.returncode:
        raise PreflightError("command rejected")
    return result.stdout.strip()


def load_env(root=ROOT):
    path = root / ".env"
    if not path.is_file():
        raise PreflightError(".env is missing; run make init")
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise PreflightError(".env must be a regular private file (mode 0600)")
    values = {}
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise PreflightError(f".env line {number} must be KEY=value")
        key, value = (part.strip() for part in line.split("=", 1))
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise PreflightError(f".env line {number} has an invalid or duplicate key")
        values[key] = value
    unknown = values.keys() - ALLOWED_ENV
    if unknown:
        raise PreflightError(
            ".env contains unknown keys: " + ", ".join(sorted(unknown))
        )
    return values


def gateway_config_path(root, values):
    configured = Path(values.get("GATEWAY_CONFIG", "configs/gateway.yaml"))
    source = configured if configured.is_absolute() else root / configured
    repository = root.resolve()
    try:
        relative = source.absolute().relative_to(repository)
    except ValueError as exc:
        raise PreflightError("GATEWAY_CONFIG must be inside the repository") from exc
    if ".." in relative.parts:
        raise PreflightError("GATEWAY_CONFIG must not use parent-directory traversal")
    try:
        resolved = source.resolve(strict=True)
    except OSError as exc:
        raise PreflightError("configured Gateway config file was not found") from exc
    if not resolved.is_relative_to(repository) or not resolved.is_file():
        raise PreflightError(
            "GATEWAY_CONFIG must identify a file inside the repository"
        )
    current = repository
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise PreflightError("GATEWAY_CONFIG must not traverse symlinks")
    return resolved


def gateway_secrets_path(root, values):
    configured = Path(values.get("GATEWAY_SECRETS_FILE", "private/cloud.env"))
    source = configured if configured.is_absolute() else root / configured
    repository = root.resolve()
    try:
        relative = source.absolute().relative_to(repository)
        resolved = source.resolve(strict=False)
    except ValueError as exc:
        raise PreflightError("GATEWAY_SECRETS_FILE must be inside private/") from exc
    if ".." in relative.parts or not resolved.is_relative_to(repository / "private"):
        raise PreflightError(
            "GATEWAY_SECRETS_FILE must be inside private/, without traversal"
        )
    current = repository
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise PreflightError("GATEWAY_SECRETS_FILE must not traverse symlinks")
    return source.absolute()


def credential_env_names(document):
    names = set()
    groq = document.get("groq_stt") or {}
    if groq.get("enabled") is True:
        names.add(groq.get("api_key_env", "GROQ_STT_API_KEY"))
    transform = document.get("text_transform") or {}
    selection = transform.get("selection") or {}
    if transform.get("enabled") is True and selection.get("allow_cloud") is True:
        enabled = {
            model.get("provider")
            for model in transform.get("models", [])
            if model.get("enabled") is True
        }
        names.update(
            provider.get("api_key_env")
            for provider in transform.get("providers", [])
            if provider.get("locality") == "cloud" and provider.get("id") in enabled
        )
    return names


def uses_local_ollama(document):
    transform = document.get("text_transform") or {}
    if not isinstance(transform, dict):
        raise PreflightError("text_transform config must be a mapping")
    if transform.get("enabled") is not True:
        return False
    providers = transform.get("providers") or []
    models = transform.get("models") or []
    if not isinstance(providers, list) or not isinstance(models, list):
        raise PreflightError("text_transform providers and models must be lists")
    provider_by_id = {
        item.get("id"): item for item in providers if isinstance(item, dict)
    }
    for model in models:
        provider = (
            provider_by_id.get(model.get("provider"))
            if isinstance(model, dict) and model.get("enabled") is True
            else None
        )
        if (
            provider
            and provider.get("type") == "ollama"
            and provider.get("locality") == "local"
        ):
            try:
                endpoint = urlparse(str(provider.get("endpoint", "")))
                port = endpoint.port
            except ValueError as exc:
                raise PreflightError(
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
                raise PreflightError(
                    "enabled local Ollama providers must use http://ollama:11434"
                )
            return True
    return False


def validate_environment(values, root=ROOT):
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
        raise PreflightError(
            ".env is missing required keys: " + ", ".join(sorted(missing))
        )
    if values["MODEL_MANIFEST_SHA256"] != STT_MANIFEST_SHA256:
        raise PreflightError("MODEL_MANIFEST_SHA256 must match the pinned STT model")
    if values["TTS_MODEL_MANIFEST_SHA256"] != TTS_MANIFEST_SHA256:
        raise PreflightError(
            "TTS_MODEL_MANIFEST_SHA256 must match the pinned VoxCPM2 artifact"
        )
    if not Path(values["MODEL_STORE"]).is_absolute() or (
        values.get("TTS_MODEL_STORE")
        and not Path(values["TTS_MODEL_STORE"]).is_absolute()
    ):
        raise PreflightError("model store paths must be absolute host paths")
    try:
        port = int(values["SPEECH_PORT"])
        gpu = int(values["STT_GPU_DEVICE"])
        tts_gpu = int(values["TTS_GPU_DEVICE"])
        ip = str(ipaddress.IPv4Address(values["SPEECH_BIND_IP"]))
    except ValueError as exc:
        raise PreflightError(
            "SPEECH_PORT, GPU indices or SPEECH_BIND_IP are invalid"
        ) from exc
    if not 1 <= port <= 65535 or gpu < 0 or tts_gpu < 0:
        raise PreflightError(
            "SPEECH_PORT or a GPU device index is outside its valid range"
        )
    if len(values.get("SPEECH_API_TOKEN", "")) < 32:
        raise PreflightError(
            "SPEECH_API_TOKEN must contain at least 32 characters for every deployment"
        )
    if not ipaddress.ip_address(ip).is_loopback:
        parsed = urlparse(values.get("SPEECH_API_URL", ""))
        if parsed.scheme != "https" or not parsed.hostname:
            raise PreflightError(
                "non-loopback API use requires an https SPEECH_API_URL"
            )
    for key, fallback in (
        ("MODEL_READ_GID", "988"),
        ("TTS_MODEL_READ_GID", values.get("MODEL_READ_GID", "988")),
    ):
        raw = values.get(key, fallback)
        if not raw.isdecimal() or not 1 <= int(raw) <= 2147483647:
            raise PreflightError(f"{key} must be in 1..2147483647")
    try:
        ollama_network.validate_names(
            values.get("OLLAMA_NETWORK_NAME", ollama_network.DEFAULT_NETWORK),
            values.get("OLLAMA_CONTAINER_NAME", ollama_network.DEFAULT_CONTAINER),
        )
    except ollama_network.NetworkError as exc:
        raise PreflightError(str(exc)) from exc
    api_url = values.get("SPEECH_API_URL")
    if api_url:
        parsed = urlparse(api_url)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise PreflightError(
                "SPEECH_API_URL must be an HTTP(S) origin without credentials, query or path"
            )
        if parsed.scheme == "http" and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
        }:
            raise PreflightError("HTTP SPEECH_API_URL is allowed only for loopback")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise PreflightError("SPEECH_API_URL must be an HTTP(S) origin")
    gateway_secrets_path(root, values)
    try:
        minimum = int(values.get("INSTALL_MIN_FREE_GIB", "20"))
        if not 1 <= minimum <= 1024:
            raise ValueError
    except ValueError as exc:
        raise PreflightError("INSTALL_MIN_FREE_GIB must be in 1..1024") from exc
    return ip, port, gpu, tts_gpu


def _base_environment(values):
    env = os.environ.copy()
    controlled = ALLOWED_ENV | {
        "COMPOSE_FILE",
        "COMPOSE_PROFILES",
        "COMPOSE_PATH_SEPARATOR",
        "SOURCE_REVISION",
        "GATEWAY_IMAGE",
        "GATEWAY_CONFIG",
        "GATEWAY_SECRETS_FILE",
    }
    for key in controlled:
        env.pop(key, None)
    env.update(values)
    env["COMPOSE_PROJECT_NAME"] = values.get("COMPOSE_PROJECT_NAME", "speech-platform")
    return env


def _compose_environment(values, revision, config_path, root=ROOT):
    """Build isolated Compose interpolation env; ambient deployment values lose."""
    env = _base_environment(values)
    env["SOURCE_REVISION"] = revision
    env["GATEWAY_CONFIG"] = str(config_path)
    secret_path = gateway_secrets_path(root, values)
    env["GATEWAY_SECRETS_FILE"] = str(secret_path)
    try:
        document = yaml.load(config_path.read_text(), Loader=StrictLoader)
    except (OSError, ValueError, yaml.YAMLError):
        document = None
    try:
        credential_names = (
            credential_env_names(document) if isinstance(document, dict) else set()
        )
    except (AttributeError, TypeError):
        credential_names = set()
    if not credential_names:
        env["GATEWAY_SECRETS_FILE"] = "/dev/null"
    return env


def _model_metadata(store: str, worker: str, root: Path):
    """Check pinned manifests, exact file set and sizes without hashing model files."""
    if worker == "stt":
        release = load_release(str(root / "releases/voiceservice-v0.1.2.yaml"))
        models = release["services"]["stt"]["required_model_artifacts"]
        store_root = Path(store)
    else:
        from scripts.tts_model import _model

        models = [_model()]
        store_root = Path(store)
    if store_root.is_symlink() or not store_root.is_dir():
        raise PreflightError(f"{worker.upper()} model store is missing or is a symlink")
    for model in models:
        digest = model["manifest_sha256"]
        model_dir = store_root / digest
        if model_dir.is_symlink() or not model_dir.is_dir():
            raise PreflightError(f"{worker.upper()} pinned model directory is missing")
        artifact_dir = model_dir / "artifact"
        local_manifest = model_dir / "manifest.yaml"
        if artifact_dir.is_symlink() or not artifact_dir.is_dir():
            raise PreflightError(f"{worker.upper()} artifact directory is missing")
        pinned_manifest = root / model["manifest_path"]
        expected_manifest = load_artifact_manifest(pinned_manifest, digest)
        if local_manifest.is_symlink() or not local_manifest.is_file():
            raise PreflightError(f"{worker.upper()} local artifact manifest is missing")
        if load_artifact_manifest(local_manifest, digest) != expected_manifest:
            raise PreflightError(
                f"{worker.upper()} local artifact manifest does not match the pinned manifest"
            )
        expected = {
            entry["path"]: entry["size_bytes"] for entry in expected_manifest["files"]
        }
        actual = {}
        walk_errors = []
        for current, directories, names in os.walk(
            artifact_dir, followlinks=False, onerror=walk_errors.append
        ):
            base = Path(current)
            if any((base / name).is_symlink() for name in directories):
                raise PreflightError(
                    f"{worker.upper()} artifact contains a symlink directory"
                )
            for name in names:
                path = base / name
                if path.is_symlink() or not path.is_file():
                    raise PreflightError(
                        f"{worker.upper()} artifact contains a non-regular file"
                    )
                if not os.access(path, os.R_OK):
                    raise PreflightError(
                        f"{worker.upper()} artifact file is not readable"
                    )
                actual[path.relative_to(artifact_dir).as_posix()] = path.stat().st_size
        if walk_errors:
            raise PreflightError(f"{worker.upper()} artifact directory cannot be read")
        if actual.keys() != expected.keys():
            raise PreflightError(
                f"{worker.upper()} artifact file set does not match the pinned manifest"
            )
        if actual != expected:
            raise PreflightError(
                f"{worker.upper()} artifact file sizes do not match the pinned manifest"
            )
    return True


@dataclass
class Report:
    entries: list[tuple[str, str, str, str]] = field(default_factory=list)
    values: dict = field(default_factory=dict)
    revision: str = ""
    compose_version: str = ""
    gpu: str = "not applicable"

    def add(self, group, status, name, detail=""):
        if group not in GROUPS or status not in STATUSES:
            raise ValueError("invalid prerequisite result")
        if status in {"WARN", "FAIL"} and not detail:
            raise ValueError("warnings and failures need actionable remediation")
        self.entries.append((group, status, name, detail))

    @property
    def failed(self):
        return any(status == "FAIL" for _, status, _, _ in self.entries)

    def display(self):
        for group in GROUPS:
            print(group + ":")
            for category, status, name, detail in self.entries:
                if category == group:
                    print(f"  {status:4} {name}" + (f" — {detail}" if detail else ""))
        counts = Counter(status for _, status, _, _ in self.entries)
        print("Summary: " + " ".join(f"{s}={counts[s]}" for s in STATUSES))
        print("NOT READY TO INSTALL" if self.failed else "READY TO INSTALL")


class NoMetadataRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def probe_ollama(origin: str, models: list[str], *, timeout=5, opener=None):
    """Version/tags only: never load a model, generate content, or send credentials."""
    opener = opener or build_opener(ProxyHandler({}), NoMetadataRedirect()).open
    documents = []
    for path in ("/api/version", "/api/tags"):
        with opener(origin + path, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError("Ollama metadata endpoint failed")
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ValueError("Ollama metadata response exceeded its bound")
            documents.append(json.loads(body))
    if not isinstance(documents[0], dict) or not isinstance(
        documents[0].get("version"), str
    ):
        raise ValueError("Ollama returned invalid version metadata")
    tags = documents[1].get("models") if isinstance(documents[1], dict) else None
    if not isinstance(tags, list) or any(not isinstance(m, dict) for m in tags):
        raise ValueError("Ollama returned invalid model metadata")
    available = {m.get("name") for m in tags} | {m.get("model") for m in tags}
    missing = set(models) - available
    if missing:
        raise ValueError(
            "configured Ollama model is missing; provision it explicitly with ollama pull"
        )
    return documents[0]["version"]


def cloud_credentials(root: Path, values: dict, gateway_config: dict, credential_names):
    """Validate the optional, private runtime env file without displaying secrets."""
    names = credential_names(gateway_config)
    if not names:
        return False
    if any(
        not isinstance(n, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", n) for n in names
    ):
        raise ValueError("set api_key_env for every enabled cloud provider")
    reserved = {
        "PATH",
        "HOME",
        "GODEBUG",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    if any(
        n in reserved
        or n.startswith(
            (
                "SPEECH_",
                "GATEWAY_",
                "STT_",
                "TTS_",
                "OLLAMA_",
                "MODEL_",
                "COMPOSE_",
                "LD_",
                "PYTHON",
            )
        )
        for n in names
    ):
        raise ValueError(
            "use dedicated cloud credential names; process/deployment variables are reserved"
        )
    configured = Path(values.get("GATEWAY_SECRETS_FILE", "private/cloud.env"))
    path = configured if configured.is_absolute() else root / configured
    resolved = path.resolve(strict=True)
    repository = root.resolve()
    try:
        relative = path.absolute().relative_to(repository)
    except ValueError as exc:
        raise ValueError("put credential file inside private/") from exc
    current = repository
    if ".." in relative.parts or not resolved.is_relative_to(repository / "private"):
        raise ValueError(
            "put credential file inside private/, without parent traversal"
        )
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("credential path must not traverse symlinks")
    if resolved.stat().st_mode & 0o077:
        raise ValueError("set cloud credential file permissions to 0600")
    keys = {}
    for line in resolved.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("use KEY=value lines in the cloud credential file")
        key, value = line.split("=", 1)
        if key in keys or key not in names:
            raise ValueError(
                "credential file must contain only configured api_key_env names, once each"
            )
        if (
            len(value) < 8
            or any(c in value for c in "\"'$\\")
            or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value)
        ):
            raise ValueError(
                "set nonempty printable credentials without whitespace or quoting"
            )
        keys[key] = value
    if set(keys) != names:
        raise ValueError("provide a credential for every enabled cloud provider")
    return True


def run_checks(
    *,
    root=ROOT,
    service=None,
    model=True,
    compose_config=True,
    require_clean=False,
    hardware=True,
    check_port=True,
):
    """Read-only checks for host, config, providers and model metadata."""
    root = Path(root).resolve()
    report = Report()
    selected = {service} if service else {"gateway", "stt", "tts"}
    if not selected <= {"gateway", "stt", "tts"}:
        raise ValueError("unknown service")

    def command(args, timeout=60, env=None):
        return run_command(args, root=root, timeout=timeout, env=env)

    def check(group, name, action, remedy, *, warning=False):
        try:
            value = action()
            report.add(group, "PASS", name)
            return value
        except Exception:
            report.add(group, "WARN" if warning else "FAIL", name, remedy)
            return None

    supported = platform.system() == "Linux" and platform.machine().lower() in {
        "x86_64",
        "amd64",
    }
    report.add(
        "Host",
        "PASS" if supported else "FAIL",
        "Linux amd64",
        "Use a Linux amd64 host (Ubuntu 24.04 qualified)." if not supported else "",
    )
    values = check(
        "Host",
        "Private .env and validated settings",
        lambda: load_env(root),
        "Run make init; keep .env mode 0600 and correct unsupported or duplicate keys.",
    )
    report.values = values or {}
    validated = (
        check(
            "Deployment",
            "Deployment values",
            lambda: validate_environment(values, root),
            "Correct required paths, token, ports, GPU indices, manifest pins and limits in .env.",
        )
        if values is not None
        else None
    )
    if values is None or validated is None:
        for group in ("GPU", "Models", "Networking", "External Providers"):
            report.add(
                group, "SKIP", "Dependent checks", "Correct .env settings first."
            )
        return report
    ip, port, _, _ = validated

    check(
        "Host",
        "Docker daemon and permissions",
        lambda: command(["docker", "info"]),
        "Start Docker Engine and grant this account access; verify with docker info.",
    )

    def local_endpoint():
        context = os.environ.get("DOCKER_CONTEXT")
        endpoint = os.environ.get("DOCKER_HOST") if not context else None
        if not endpoint:
            data = json.loads(
                command(
                    ["docker", "context", "inspect", *([context] if context else [])]
                )
            )
            endpoint = data[0].get("Endpoints", {}).get("docker", {}).get("Host", "")
        if not isinstance(endpoint, str) or not endpoint.startswith("unix://"):
            raise PreflightError("remote Docker endpoint")

    check(
        "Host",
        "Local Unix Docker endpoint",
        local_endpoint,
        "Select a local Unix Docker context; this GPU install requires the local host daemon.",
    )
    compose_version = check(
        "Host",
        "Compose plugin >= 2.24",
        lambda: command(["docker", "compose", "version", "--short"]),
        "Install Docker Compose plugin >=2.24.",
    )
    if compose_version:
        match = re.search(r"(\d+)\.(\d+)", compose_version)
        if not match or tuple(map(int, match.groups())) < (2, 24):
            report.add(
                "Host",
                "FAIL",
                "Compose compatibility",
                "Upgrade Docker Compose plugin to >=2.24.",
            )
        report.compose_version = compose_version
    report.add(
        "Host",
        "PASS" if sys.version_info >= (3, 12) else "FAIL",
        "Python >=3.12",
        "Use the project virtualenv with Python 3.12 or newer."
        if sys.version_info < (3, 12)
        else "",
    )
    for tool in ("git", "go"):
        found = shutil.which(tool)
        report.add(
            "Host",
            "PASS" if found else "FAIL",
            tool,
            f"Install {tool}; it is needed for configuration checks."
            if not found
            else "",
        )
    if shutil.which("go"):

        def go_compatible():
            actual = re.search(
                r"go(\d+)\.(\d+)(?:\.(\d+))?", command(["go", "version"])
            )
            minimum = re.search(
                r"^go (\d+)\.(\d+)(?:\.(\d+))?",
                (root / "go.mod").read_text(),
                re.MULTILINE,
            )
            if (
                not actual
                or not minimum
                or tuple(int(x or 0) for x in actual.groups())
                < tuple(int(x or 0) for x in minimum.groups())
            ):
                raise PreflightError("host Go toolchain is older than go.mod")

        check(
            "Host",
            "Go version matches go.mod",
            go_compatible,
            "Install the Go version specified by go.mod; Gateway config validation uses the host toolchain.",
        )
    report.add(
        "Host",
        "PASS" if shutil.which("ffmpeg") else "WARN",
        "ffmpeg",
        "Install FFmpeg for local audio inspection; it is not required to start services."
        if not shutil.which("ffmpeg")
        else "",
    )
    minimum = int(values.get("INSTALL_MIN_FREE_GIB", "20"))
    free = shutil.disk_usage(root).free / 1024**3
    report.add(
        "Host",
        "PASS" if free >= minimum else "FAIL",
        f"Checkout storage ({free:.1f} GiB free)",
        f"Free at least {minimum} GiB before building images."
        if free < minimum
        else "",
    )
    docker_root = check(
        "Host",
        "Docker storage path",
        lambda: command(["docker", "info", "--format", "{{.DockerRootDir}}"]),
        "Check Docker daemon storage access and free space.",
    )
    if docker_root:
        try:
            docker_free = shutil.disk_usage(docker_root).free / 1024**3
            report.add(
                "Host",
                "PASS" if docker_free >= minimum else "FAIL",
                f"Docker storage ({docker_free:.1f} GiB free)",
                f"Free at least {minimum} GiB on Docker storage before uncached builds."
                if docker_free < minimum
                else "",
            )
        except OSError:
            report.add(
                "Host",
                "WARN",
                "Docker storage visibility",
                "Check free space on the Docker daemon storage filesystem before builds.",
            )

    revision = check(
        "Deployment",
        "Git revision",
        lambda: command(["git", "rev-parse", "HEAD"]),
        "Use a checkout with valid Git metadata.",
    )
    report.revision = revision or ""
    if revision:
        dirty = check(
            "Deployment",
            "Git tree inspection",
            lambda: command(["git", "status", "--porcelain"]),
            "Restore readable Git metadata.",
        )
        report.add(
            "Deployment",
            "FAIL" if dirty and require_clean else "WARN" if dirty else "PASS",
            "Committed source",
            "Commit reviewed changes before installation; preflight is read-only."
            if dirty
            else "",
        )

    project = values.get("COMPOSE_PROJECT_NAME", "speech-platform")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
        report.add(
            "Deployment",
            "FAIL",
            "Compose project name",
            "Use lowercase letters, digits, underscores or hyphens; begin with a letter or digit.",
        )
        owned = False
    else:

        def project_ownership():
            args = [
                "docker",
                "compose",
                "--env-file",
                str(root / ".env"),
                "-f",
                str(root / "compose.yaml"),
                "ls",
                "--format",
                "json",
            ]
            entries = json.loads(command(args, env=_base_environment(values)))
            expected = str((root / "compose.yaml").resolve())
            for entry in entries:
                if entry.get("Name") == project:
                    files = [
                        str(Path(item).resolve())
                        for item in entry.get("ConfigFiles", "").split(",")
                        if item
                    ]
                    if expected not in files:
                        raise PreflightError(
                            "project name belongs to another compose file"
                        )
                    return True
            return False

        owned = check(
            "Deployment",
            "Compose project ownership",
            project_ownership,
            "Choose a project name not owned by a different Compose deployment.",
        )

    config_path = check(
        "Deployment",
        "Gateway config path",
        lambda: gateway_config_path(root, values),
        "Set GATEWAY_CONFIG to a regular file inside this checkout without symlinks.",
    )
    gateway_document = None
    if config_path:
        try:
            gateway_document = yaml.load(config_path.read_text(), Loader=StrictLoader)
            if not isinstance(gateway_document, dict):
                raise ValueError("not a mapping")
            report.add("Deployment", "PASS", "Gateway configuration syntax")
        except Exception:
            report.add(
                "Deployment",
                "FAIL",
                "Gateway configuration syntax",
                "Correct the Gateway YAML mapping and rerun Gateway --check-config.",
            )

    local_ollama = False
    if gateway_document is not None and "gateway" in selected:
        cloud = check(
            "External Providers",
            "Enabled provider credentials (no inference)",
            lambda: cloud_credentials(
                root, values, gateway_document, credential_env_names
            ),
            "For enabled cloud providers, set api_key_env and its value in a regular mode-0600 file under private/.",
        )
        if cloud is False:
            report.entries[-1] = (
                "External Providers",
                "SKIP",
                "Cloud inference",
                "No enabled cloud provider; credentials are not required.",
            )
        elif cloud:
            report.add(
                "External Providers",
                "WARN",
                "Cloud provider reachability",
                "Credentials are structurally valid; preflight makes no cloud request.",
            )
        local_ollama = check(
            "External Providers",
            "Local Ollama eligibility",
            lambda: uses_local_ollama(gateway_document),
            "Use the configured local endpoint http://ollama:11434/api/generate.",
        )
        if local_ollama:
            transform = gateway_document.get("text_transform") or {}
            provider_ids = {
                p["id"]
                for p in transform.get("providers", [])
                if p.get("type") == "ollama" and p.get("locality") == "local"
            }
            models = [
                m["model"]
                for m in transform.get("models", [])
                if m.get("enabled") is True and m.get("provider") in provider_ids
            ]
            network = values.get("OLLAMA_NETWORK_NAME", ollama_network.DEFAULT_NETWORK)
            container = values.get(
                "OLLAMA_CONTAINER_NAME", ollama_network.DEFAULT_CONTAINER
            )

            def inspect_ollama():
                info = json.loads(command(["docker", "inspect", container]))[0]
                attachment = (
                    info.get("NetworkSettings", {}).get("Networks", {}).get(network)
                )
                net = json.loads(command(["docker", "network", "inspect", network]))[0]
                if (
                    info.get("State", {}).get("Running") is not True
                    or not attachment
                    or "ollama" not in (attachment.get("Aliases") or [])
                    or not net.get("Internal")
                ):
                    raise PreflightError("external Ollama attachment is unavailable")
                return attachment["IPAddress"]

            address = check(
                "External Providers",
                "Shared Ollama network/alias",
                inspect_ollama,
                "Ask the Ollama owner to keep its running container attached to the configured internal network with alias ollama; preflight will not modify it.",
            )
            if address:
                check(
                    "External Providers",
                    "Ollama version and configured model metadata",
                    lambda: command(
                        [
                            sys.executable,
                            str(Path(__file__).resolve()),
                            "--probe-ollama",
                            f"http://{address}:11434",
                            *models,
                        ],
                        timeout=12,
                    ),
                    "Check the running Ollama API and explicitly provision any missing configured model; metadata requests do not load models.",
                )
        else:
            report.add(
                "External Providers",
                "SKIP",
                "Local Ollama",
                "No enabled local Ollama model.",
            )
    elif "gateway" in selected:
        report.add(
            "External Providers",
            "SKIP",
            "Provider credential and Ollama checks",
            "Correct Gateway configuration first.",
        )
    else:
        report.add(
            "External Providers",
            "SKIP",
            "Provider credential and Ollama checks",
            "Gateway not selected.",
        )

    env = _compose_environment(
        values, revision or "local", config_path or root / "configs/gateway.yaml", root
    )
    compose_files = [
        "docker",
        "compose",
        "--env-file",
        str(root / ".env"),
        "-f",
        str(root / "compose.yaml"),
    ]
    if gateway_document is not None and local_ollama is True:
        compose_files += ["-f", str(root / "deployments/compose/compose.ollama.yaml")]
    if compose_config and gateway_document is not None:
        check(
            "Deployment",
            "Canonical Compose rendering",
            lambda: command([*compose_files, "config", "--quiet"], env=env),
            "Correct Compose interpolation and configuration paths; rendering does not create resources.",
        )

    schema_checks = []
    if "gateway" in selected and config_path:
        schema_checks.append(
            (
                "Gateway schema",
                [
                    "go",
                    "run",
                    "./cmd/gateway",
                    "--config",
                    str(config_path),
                    "--check-config",
                ],
            )
        )
    if "stt" in selected:
        schema_checks.append(
            (
                "STT schema",
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
                ],
            )
        )
    if "tts" in selected:
        schema_checks.append(
            (
                "TTS schema",
                [
                    sys.executable,
                    "-m",
                    "services.tts.main",
                    "--config",
                    "configs/tts.yaml",
                    "--check-config",
                ],
            )
        )
    for name, args in schema_checks:
        check(
            "Deployment",
            name,
            lambda args=args: command(args, timeout=120, env=env),
            "Run the service --check-config command and correct the rejected schema.",
        )

    if "gateway" in selected and check_port:

        def port_available():
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.bind((ip, port))
                return
            except OSError:
                if not owned:
                    raise PreflightError("port is occupied")
            finally:
                probe.close()
            ids = command([*compose_files, "ps", "-q", "gateway"], env=env).splitlines()
            if len(ids) != 1:
                raise PreflightError("occupied port has no unique project Gateway")
            data = json.loads(command(["docker", "inspect", ids[0]]))[0]
            labels = (data.get("Config") or {}).get("Labels") or {}
            config_files = {
                str(Path(item).resolve())
                for item in labels.get(
                    "com.docker.compose.project.config_files", ""
                ).split(",")
                if item
            }
            bindings = ((data.get("NetworkSettings") or {}).get("Ports") or {}).get(
                "8080/tcp"
            ) or []
            matching = [
                binding
                for binding in bindings
                if binding.get("HostIp") == ip and binding.get("HostPort") == str(port)
            ]
            if (
                data.get("State", {}).get("Running") is not True
                or labels.get("com.docker.compose.project") != project
                or labels.get("com.docker.compose.service") != "gateway"
                or labels.get("com.docker.compose.project.working_dir")
                != str(root.resolve())
                or str((root / "compose.yaml").resolve()) not in config_files
                or len(matching) != 1
                or len(bindings) != 1
            ):
                raise PreflightError("occupied port belongs to another service")

        check(
            "Networking",
            "Gateway bind port",
            port_available,
            "Choose an unused SPEECH_PORT or verify the existing Gateway is the owner.",
        )
    else:
        report.add(
            "Networking",
            "SKIP",
            "Gateway bind port",
            "Gateway not selected or port check disabled.",
        )
    report.add(
        "Networking",
        "WARN",
        "Fresh internal service networking",
        "DNS and worker connectivity are verified by post-start health checks; preflight does not create networks or containers.",
    )

    gpu_selected = selected & {"stt", "tts"}
    if not hardware or not gpu_selected:
        report.add(
            "GPU",
            "SKIP",
            "NVIDIA prerequisites",
            "No GPU worker selected or hardware checks disabled.",
        )
    else:
        output = check(
            "GPU",
            "Host NVIDIA driver and memory",
            lambda: command(
                [
                    "nvidia-smi",
                    "--query-gpu=index,driver_version,memory.free,memory.total",
                    "--format=csv,noheader",
                ]
            ),
            "Install a supported NVIDIA driver and verify nvidia-smi and configured GPU indices.",
        )
        runtimes = check(
            "GPU",
            "NVIDIA Container Toolkit",
            lambda: command(["docker", "info", "--format", "{{json .Runtimes}}"]),
            "Install/configure NVIDIA Container Toolkit for Docker.",
        )
        if runtimes and "nvidia" not in runtimes.lower():
            report.add(
                "GPU",
                "FAIL",
                "NVIDIA runtime registration",
                "Configure NVIDIA Container Toolkit with Docker; preflight will not restart Docker.",
            )
        if output:
            report.gpu = output
            available = {
                line.split(",")[0].strip(): line for line in output.splitlines()
            }
            for worker in sorted(gpu_selected):
                index = values.get(worker.upper() + "_GPU_DEVICE", "0")
                if index not in available:
                    report.add(
                        "GPU",
                        "FAIL",
                        f"{worker} GPU index",
                        "Select an index present in nvidia-smi output.",
                    )
                else:
                    try:
                        free_mib = int(
                            available[index].split(",")[2].strip().split()[0]
                        )
                        config_file = root / (
                            "configs/stt-product-deployment.yaml"
                            if worker == "stt"
                            else "configs/tts.yaml"
                        )
                        runtime_config = yaml.load(
                            config_file.read_text(), Loader=StrictLoader
                        )
                        floor = (
                            runtime_config["device_access"][
                                "minimum_free_gpu_bytes_before_load"
                            ]
                            // 1048576
                            if worker == "stt"
                            else runtime_config["min_free_vram_mib"]
                        )
                    except (
                        OSError,
                        ValueError,
                        TypeError,
                        KeyError,
                        IndexError,
                        yaml.YAMLError,
                    ):
                        report.add(
                            "GPU",
                            "FAIL",
                            f"{worker} VRAM configuration",
                            "Correct the worker GPU headroom configuration and rerun its --check-config validation.",
                        )
                        continue
                    report.add(
                        "GPU",
                        "WARN" if free_mib < floor else "PASS",
                        f"{worker} load headroom ({free_mib} MiB / {floor} MiB minimum)",
                        "Wait for active GPU workloads to finish; observed free VRAM is not reserved and does not guarantee coexistence."
                        if free_mib < floor
                        else "Free VRAM is a point-in-time observation, not a reservation or coexistence guarantee.",
                    )
        report.add(
            "GPU",
            "SKIP",
            "Container CUDA probe",
            "Run the disposable CUDA probe during install after image build; preflight remains read-only.",
        )

    for worker in ("stt", "tts"):
        if worker not in selected or not model:
            report.add(
                "Models",
                "SKIP",
                worker + " model metadata",
                "Worker not selected or model checks disabled.",
            )
            continue
        store = (
            values.get("TTS_MODEL_STORE", values["MODEL_STORE"])
            if worker == "tts"
            else values["MODEL_STORE"]
        )
        result = check(
            "Models",
            worker + " pinned manifest/file metadata",
            lambda worker=worker, store=store: _model_metadata(store, worker, root),
            f"Provision the pinned model with make {'tts-model-fetch' if worker == 'tts' else 'model-fetch'}; preflight checks file names and sizes, while worker startup verifies SHA-256.",
        )
        if result and not os.access(store, os.R_OK | os.X_OK):
            report.add(
                "Models",
                "FAIL",
                worker + " model-store access",
                "Grant the configured runtime reader access to this model store.",
            )
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Read-only SpeechPlatform installation preflight"
    )
    parser.add_argument("--service", choices=("gateway", "stt", "tts"))
    args = parser.parse_args()
    report = run_checks(service=args.service)
    report.display()
    return 2 if report.failed else 0


if __name__ == "__main__":
    # Isolated subprocess gives the entire metadata probe a hard parent-enforced
    # deadline, including servers trickling bytes. No model-loading API is called.
    if len(sys.argv) >= 3 and sys.argv[1] == "--probe-ollama":
        try:
            print(probe_ollama(sys.argv[2], sys.argv[3:]))
        except (OSError, ValueError):
            print("Ollama metadata/model verification failed", file=sys.stderr)
            raise SystemExit(2)
    else:
        raise SystemExit(main())
