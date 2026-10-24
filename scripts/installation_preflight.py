"""Read-only prerequisite report for the existing Git + Compose installer."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

import yaml

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.worker.server import StrictLoader

GROUPS = ("Host", "GPU", "Models", "Networking", "External Providers", "Deployment")
STATUSES = ("PASS", "WARN", "FAIL", "SKIP")


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


def cloud_credentials(root: Path, values: dict, transform: dict):
    """Validate the optional, private runtime env file without displaying secrets."""
    if (
        transform.get("enabled") is not True
        or transform.get("selection", {}).get("allow_cloud") is not True
    ):
        return False
    enabled = {
        m.get("provider")
        for m in transform.get("models", [])
        if m.get("enabled") is True
    }
    providers = [
        p
        for p in transform.get("providers", [])
        if p.get("locality") == "cloud" and p.get("id") in enabled
    ]
    if not providers:
        return False
    names = {p.get("api_key_env") for p in providers}
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


def collect(
    product,
    *,
    service=None,
    model=True,
    compose_config=True,
    require_clean=False,
    hardware=True,
    check_port=True,
):
    """Collect independent read-only checks; commands never run/pull/create containers."""
    r = Report()
    selected = {service} if service else {"gateway", "stt", "tts"}
    if not selected <= {"gateway", "stt", "tts"}:
        raise ValueError("unknown service")

    def command(args, timeout=60):
        result = product.run(args, capture=True, check=False, timeout=timeout)
        if result.returncode:
            raise ValueError("command rejected")
        return result.stdout.strip()

    def check(group, name, action, remedy, *, warning=False):
        try:
            value = action()
            r.add(group, "PASS", name)
            return value
        except Exception:
            r.add(group, "WARN" if warning else "FAIL", name, remedy)
            return None

    supported = platform.system() == "Linux" and platform.machine() in {
        "x86_64",
        "amd64",
    }
    r.add(
        "Host",
        "PASS" if supported else "FAIL",
        "Linux amd64",
        "Use a Linux amd64 host (Ubuntu 24.04 qualified)." if not supported else "",
    )
    loaded = check(
        "Host",
        "Private .env and validated settings",
        lambda: product.load_env(),
        "Copy .env.example to .env, chmod 600, and correct unknown or duplicate keys.",
    )
    r.values = loaded or {}
    if loaded is not None:
        valid = check(
            "Deployment",
            "Deployment values",
            lambda: product.validate_environment(r.values),
            "Review .env IP/port, pinned digests, absolute model paths, GPU indices and limits.",
        )
    else:
        valid = None
    check(
        "Host",
        "Docker daemon and permissions",
        lambda: command(["docker", "info"]),
        "Install/start Docker Engine and grant this account Docker access; retry docker info.",
    )
    check(
        "Host",
        "Local Unix Docker endpoint",
        product.require_local_docker,
        "Select a local Unix Docker context and unset remote DOCKER_HOST; this host-GPU installer does not target remote daemons.",
    )
    version = check(
        "Host",
        "Compose plugin >= 2.24",
        lambda: command(["docker", "compose", "version", "--short"]),
        "Install Docker Compose plugin >=2.24 (optional env_file support).",
    )
    if version:
        numbers = re.search(r"(\d+)\.(\d+)", version)
        if not numbers or tuple(map(int, numbers.groups())) < (2, 24):
            r.add(
                "Host",
                "FAIL",
                "Compose compatibility",
                "Upgrade the Compose plugin to >=2.24.",
            )
        r.compose_version = version
    python_ok = sys.version_info >= (3, 12)
    r.add(
        "Host",
        "PASS" if python_ok else "FAIL",
        "Python >=3.12",
        "Create the virtualenv with Python 3.12 or newer." if not python_ok else "",
    )

    def go_compatible():
        actual = re.search(r"go(\d+)\.(\d+)(?:\.(\d+))?", command(["go", "version"]))
        minimum = re.search(
            r"^go (\d+)\.(\d+)(?:\.(\d+))?",
            (product.ROOT / "go.mod").read_text(),
            re.MULTILINE,
        )
        if (
            not actual
            or not minimum
            or tuple(int(x or 0) for x in actual.groups())
            < tuple(int(x or 0) for x in minimum.groups())
        ):
            raise ValueError("Go toolchain is older than go.mod")

    check(
        "Host",
        "Go toolchain compatible with go.mod",
        go_compatible,
        "Install the Go version required by go.mod; container builds use their separately pinned compiler.",
    )
    for tool in ("git", "ffmpeg"):
        # FFmpeg is a host smoke-test convenience; worker includes its own copy.
        found = shutil.which(tool)
        r.add(
            "Host",
            "PASS" if found else ("WARN" if tool == "ffmpeg" else "FAIL"),
            tool,
            "Install " + tool + " for configuration/build or smoke tests."
            if not found
            else "",
        )
    minimum = int(r.values.get("INSTALL_MIN_FREE_GIB", "20")) if valid else 20
    free = shutil.disk_usage(product.ROOT).free / 1024**3
    r.add(
        "Host",
        "PASS" if free >= minimum else "FAIL",
        f"Storage ({free:.1f} GiB free)",
        f"Free at least {minimum} GiB on the checkout/build filesystem."
        if free < minimum
        else "",
    )
    try:
        docker_root = command(["docker", "info", "--format", "{{.DockerRootDir}}"])
        if not Path(docker_root).is_absolute():
            raise ValueError("Docker storage path unavailable")
        docker_free = shutil.disk_usage(docker_root).free / 1024**3
        r.add(
            "Host",
            "PASS" if docker_free >= minimum else "FAIL",
            f"Docker storage ({docker_free:.1f} GiB free)",
            f"Free at least {minimum} GiB on Docker's storage filesystem before builds."
            if docker_free < minimum
            else "",
        )
    except (OSError, ValueError):
        r.add(
            "Host",
            "WARN",
            "Docker storage visibility",
            "Check free disk space on the Docker daemon's storage filesystem before uncached builds; it may be separate from the checkout.",
        )
    if not valid:
        for group in ("GPU", "Models", "Networking", "External Providers"):
            r.add(group, "SKIP", "Dependent checks", "Correct configuration first.")
        return r

    values = r.values
    revision = check(
        "Deployment",
        "Git revision",
        lambda: command(["git", "rev-parse", "HEAD"]),
        "Use a Git checkout with an existing commit.",
    )
    r.revision = revision or ""
    dirty = (
        check(
            "Deployment",
            "Git tree inspection",
            lambda: command(["git", "status", "--porcelain"]),
            "Restore readable Git metadata before installation.",
        )
        if revision
        else "unknown"
    )
    r.add(
        "Deployment",
        "FAIL" if dirty and require_clean else "WARN" if dirty else "PASS",
        "Committed source",
        "Commit reviewed changes before installation; preflight itself is safe on a dirty tree."
        if dirty
        else "",
    )
    owns = check(
        "Deployment",
        "Compose project ownership",
        lambda: product.verify_project_ownership(values),
        "Choose an unused COMPOSE_PROJECT_NAME or use the checkout owning this project.",
    )
    if "gateway" in selected and check_port:
        check(
            "Networking",
            "Gateway bind port",
            lambda: product.check_gateway_port(valid[0], valid[1], values, owns),
            "Choose an unused SPEECH_PORT or restore the existing canonical Gateway port binding.",
        )
    else:
        r.add(
            "Networking",
            "SKIP",
            "Gateway bind port",
            "Gateway not selected or status-only check.",
        )

    config_path = check(
        "Deployment",
        "Gateway config path",
        lambda: product.gateway_config_path(values),
        "Set GATEWAY_CONFIG to an existing regular file inside this checkout, without symlinks.",
    )
    if config_path is None:
        for group in ("GPU", "Models", "External Providers"):
            r.add(group, "SKIP", "Dependent checks", "Correct the config path first.")
        return r
    checks = []
    if "gateway" in selected:
        checks.append(
            (
                "Gateway schema",
                [
                    "go",
                    "run",
                    "./cmd/gateway",
                    "--config",
                    str(product.gateway_config_path(values)),
                    "--check-config",
                ],
            )
        )
    if "stt" in selected:
        checks.append(
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
        checks.append(
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
    check(
        "Deployment",
        "Compose environment",
        lambda: product.set_compose_env(values, r.revision),
        "Correct the Gateway YAML document and private configuration paths.",
    )
    for name, args in checks:
        check(
            "Deployment",
            name,
            lambda args=args: command(args, 120),
            "Run the service --check-config command; correct its schema before installation.",
        )
    if compose_config:
        check(
            "Deployment",
            "Canonical Compose rendering",
            lambda: product.compose(
                values, r.revision, "config", "--quiet", capture=True
            ),
            "Correct .env and config paths; use make preflight again.",
        )
    if selected == {"gateway"}:
        check(
            "Deployment",
            "Existing worker readiness",
            lambda: product.require_existing_workers_healthy(values, r.revision),
            "Install STT and TTS first, or select the full stack.",
        )
    r.add(
        "Networking",
        "WARN",
        "Fresh internal DNS/connectivity",
        "Verified after deployment health checks; a read-only preflight cannot create missing networks or containers.",
    )

    gpu_selected = selected & {"stt", "tts"}
    if not hardware or not gpu_selected:
        r.add("GPU", "SKIP", "CUDA workers", "No GPU worker selected.")
    else:
        rows = check(
            "GPU",
            "Host NVIDIA driver and memory",
            lambda: command(
                [
                    "nvidia-smi",
                    "--query-gpu=index,driver_version,memory.free,memory.total",
                    "--format=csv,noheader",
                ]
            ),
            "Install a supported NVIDIA driver; verify nvidia-smi and configured GPU indices.",
        )
        runtimes = check(
            "GPU",
            "NVIDIA Container Toolkit",
            lambda: command(["docker", "info", "--format", "{{json .Runtimes}}"]),
            "Install/configure NVIDIA Container Toolkit for Docker.",
        )
        if runtimes and "nvidia" not in runtimes.lower():
            r.add(
                "GPU",
                "FAIL",
                "NVIDIA runtime registered",
                "Configure NVIDIA Container Toolkit with Docker and have the administrator restart Docker separately.",
            )
        if rows:
            r.gpu = rows
            indices = {line.split(",")[0].strip(): line for line in rows.splitlines()}
            for worker in sorted(gpu_selected):
                index = values.get(worker.upper() + "_GPU_DEVICE", "0")
                if index not in indices:
                    r.add(
                        "GPU",
                        "FAIL",
                        worker + " GPU index",
                        "Choose an available GPU index in .env.",
                    )
                else:
                    try:
                        free_mib = int(indices[index].split(",")[2].strip().split()[0])
                    except (ValueError, IndexError):
                        r.add(
                            "GPU",
                            "FAIL",
                            worker + " memory metadata",
                            "Check nvidia-smi output and the configured device index; memory visibility is required.",
                        )
                        continue
                    try:
                        config_file = product.ROOT / (
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
                    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
                        r.add(
                            "GPU",
                            "SKIP",
                            worker + " load headroom",
                            "Correct worker configuration first.",
                        )
                        continue
                    r.add(
                        "GPU",
                        "WARN" if free_mib < floor else "PASS",
                        f"{worker} load headroom ({free_mib} MiB)",
                        "Wait for active workloads to finish; this observation does not reserve VRAM."
                        if free_mib < floor
                        else "",
                    )
        r.add(
            "GPU",
            "WARN",
            "Container CUDA execution",
            "Host nvidia-smi/runtime registration is not a CUDA test. After image build, run make gpu-check SERVICE=stt (or tts); installation runs this bounded disposable check before service creation.",
        )

    for worker in ("stt", "tts"):
        if not model or worker not in selected:
            r.add("Models", "SKIP", worker + " artifact", "Worker not selected.")
            continue
        store = (
            values.get("TTS_MODEL_STORE", values["MODEL_STORE"])
            if worker == "tts"
            else values["MODEL_STORE"]
        )
        module = "scripts.tts_model" if worker == "tts" else "scripts.provision_models"
        args = [sys.executable, "-m", module, "check", "--store", store]
        if worker == "stt":
            args += ["--release", "releases/voiceservice-v0.1.2.yaml"]
        check(
            "Models",
            worker + " pinned artifact/checksums",
            lambda args=args: command(args, 300),
            f"Provision explicitly with make {'tts-model-fetch' if worker == 'tts' else 'model-fetch'}, or use the configured model-reader group (sg stt-model-reader) to check existing artifacts. Preflight never downloads models.",
        )
        if not os.access(store, os.W_OK):
            r.add(
                "Models",
                "WARN",
                worker + " provisioning permission",
                "Runtime mounts are read-only; ask the model-store owner to provision missing artifacts explicitly.",
            )

    if "gateway" not in selected:
        r.add("External Providers", "SKIP", "Text providers", "Gateway not selected.")
        return r
    document = check(
        "External Providers",
        "Provider configuration",
        lambda: yaml.load(
            product.gateway_config_path(values).read_text(), Loader=StrictLoader
        ),
        "Correct the Gateway YAML schema (including duplicate fields).",
    )
    if not isinstance(document, dict):
        if document is not None:
            r.add(
                "External Providers",
                "FAIL",
                "Provider configuration mapping",
                "Use a Gateway YAML mapping.",
            )
        return r
    transform = document.get("text_transform") or {}
    if (
        not isinstance(transform, dict)
        or not isinstance(transform.get("selection", {}), dict)
        or any(
            not isinstance(transform.get(name, []), list)
            or any(not isinstance(item, dict) for item in transform.get(name, []))
            for name in ("models", "providers")
        )
    ):
        r.add(
            "External Providers",
            "FAIL",
            "Provider/model structure",
            "Use mapping entries in provider/model lists and a selection mapping; run Gateway --check-config.",
        )
        return r
    if transform.get("enabled") is not True:
        r.add(
            "External Providers",
            "SKIP",
            "Ollama and cloud",
            "Text transformation disabled; credentials and models not required.",
        )
        return r
    cloud = check(
        "External Providers",
        "Cloud configuration (no inference)",
        lambda: cloud_credentials(product.ROOT, values, transform),
        "For enabled cloud processing, set HTTPS endpoints/api_key_env and supply matching nonempty credentials in private/cloud.env (0600). No token values are printed.",
    )
    if cloud is True:
        r.add(
            "External Providers",
            "WARN",
            "Cloud account/network qualification",
            "Configuration is valid; qualify account authorization and network with a separately authorized provider test. Preflight never makes paid inference calls.",
        )
    if cloud is False:
        # Replace a misleading PASS for an intentionally disabled capability.
        r.entries[-1] = (
            "External Providers",
            "SKIP",
            "Cloud inference",
            "Disabled or no enabled cloud model; credentials not required.",
        )
    local = check(
        "External Providers",
        "Local endpoint eligibility",
        lambda: product.gateway_uses_local_ollama(config_path),
        "Use the configured private Ollama alias http://ollama:11434/api/generate for eligible local models.",
    )
    if local is None:
        return r
    if not local:
        r.add(
            "External Providers",
            "SKIP",
            "Local Ollama",
            "No enabled local Ollama model.",
        )
        return r
    enabled = {
        p["id"]
        for p in transform.get("providers", [])
        if p.get("type") == "ollama" and p.get("locality") == "local"
    }
    models = [
        m["model"]
        for m in transform.get("models", [])
        if m.get("enabled") is True and m.get("provider") in enabled
    ]
    network = values.get("OLLAMA_NETWORK_NAME", "speech-platform_ollama_private")
    container = values.get("OLLAMA_CONTAINER_NAME", "ollama")

    def inspect_external():
        obj = json.loads(command(["docker", "inspect", container]))[0]
        net = obj.get("NetworkSettings", {}).get("Networks", {}).get(network)
        info = json.loads(command(["docker", "network", "inspect", network]))[0]
        if (
            not obj.get("State", {}).get("Running")
            or not net
            or "ollama" not in (net.get("Aliases") or [])
            or not info.get("Internal")
        ):
            raise ValueError("external Ollama not prepared")
        return net["IPAddress"]

    address = check(
        "External Providers",
        "Shared Ollama network/alias",
        inspect_external,
        "Have the Ollama owner attach its running container to the configured private internal network with alias ollama. SpeechPlatform does not recreate or modify shared Ollama.",
    )
    if address:
        check(
            "External Providers",
            "Ollama version and configured models",
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
            "Check Ollama API/network and run an explicit ollama pull for missing configured models; metadata checks never load models.",
        )
        gateway = values.get("COMPOSE_PROJECT_NAME", "speech-platform") + "-gateway-1"
        check(
            "Networking",
            "Gateway-to-Ollama DNS/TCP/HTTP",
            lambda: command(
                [
                    "docker",
                    "exec",
                    gateway,
                    "/healthcheck",
                    "http://ollama:11434/api/version",
                ]
            ),
            "Before first installation this is unestablished; install then use the Gateway --check-ollama probe. For an existing Gateway, inspect its external-network attachment.",
            warning=True,
        )
    return r


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
        raise SystemExit(2)
