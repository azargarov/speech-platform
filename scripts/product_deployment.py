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

ROOT = Path(__file__).resolve().parents[1]
DIGEST = "86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6"
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
    "MODEL_READ_GID",
    "STT_GPU_DEVICE",
    "STT_GPU_MEMORY_LIMIT",
    "STT_CPU_LIMIT",
    "STT_PIDS_LIMIT",
    "STT_STOP_GRACE_PERIOD",
    "GATEWAY_MEMORY_LIMIT",
    "GATEWAY_CPU_LIMIT",
    "TTS_MEMORY_LIMIT",
    "TTS_CPU_LIMIT",
    "SPEECH_API_URL",
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


def set_compose_env(values: dict[str, str], source_revision: str) -> None:
    os.environ.update(values)
    os.environ["SOURCE_REVISION"] = source_revision


def compose(values, revision, *args, capture=False):
    set_compose_env(values, revision)
    return run([*COMPOSE, *args], capture=capture)


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


def parse_compose_readiness(output: str) -> list[dict]:
    expected = {"gateway", "stt", "tts"}
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
        "SPEECH_BIND_IP",
        "SPEECH_PORT",
        "STT_GPU_DEVICE",
    }
    missing = required - values.keys()
    if missing:
        raise OperatorError(
            ".env is missing required keys: " + ", ".join(sorted(missing))
        )
    if values["MODEL_MANIFEST_SHA256"] != DIGEST:
        raise OperatorError("MODEL_MANIFEST_SHA256 must match the pinned v0.1.2 model")
    if not Path(values["MODEL_STORE"]).is_absolute():
        raise OperatorError("MODEL_STORE must be an absolute host path")
    try:
        port = int(values["SPEECH_PORT"])
        gpu = int(values["STT_GPU_DEVICE"])
        ip = str(ipaddress.IPv4Address(values["SPEECH_BIND_IP"]))
    except ValueError as exc:
        raise OperatorError(
            "SPEECH_PORT, STT_GPU_DEVICE or SPEECH_BIND_IP is invalid"
        ) from exc
    if not 1 <= port <= 65535 or gpu < 0:
        raise OperatorError("SPEECH_PORT or STT_GPU_DEVICE is outside its valid range")
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
        if gpu >= len(rows):
            raise OperatorError(
                f"STT_GPU_DEVICE={gpu} is unavailable; detected {len(rows)} GPU(s)"
            )
        try:
            free_mib = int(rows[gpu].split(",")[2].strip().split()[0])
        except (IndexError, ValueError) as exc:
            raise OperatorError("could not parse selected GPU free memory") from exc
        if free_mib < 6144:
            raise OperatorError(
                f"selected GPU has {free_mib} MiB free; at least 6144 MiB is required by the STT model profile"
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
        selected_uuid = rows[gpu].split(",")[1].strip()
        active_gpu_processes = sum(
            line.split(",")[0].strip() == selected_uuid
            for line in processes.stdout.splitlines()
            if "," in line
        )
        allowed_processes = 1 if owns_project else 0
        if require_idle_gpu and active_gpu_processes > allowed_processes:
            raise OperatorError(
                f"safe installation requires an idle selected GPU (or only the existing canonical STT worker); found {active_gpu_processes} active compute process(es). Existing workloads were left untouched."
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
            "configs/gateway.yaml",
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
    parser.add_argument("--audio", type=Path)
    parser.add_argument(
        "--source-language", choices=("auto", "ru", "en", "sv"), default="auto"
    )
    parser.add_argument(
        "--output-language", choices=("auto", "ru", "en", "sv"), default="auto"
    )
    args = parser.parse_args()
    try:
        if args.command == "plan":
            values, revision, compose_version, gpu, active_gpu_processes = checks()
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
            print("No containers were started or changed.")
        elif args.command == "install":
            values, revision, _version, _gpu, _processes = checks(
                require_clean=True, require_idle_gpu=True
            )
            compose(values, revision, "build", "gateway", "stt", "tts")
            checks(require_clean=True, require_idle_gpu=True)
            compose(values, revision, "up", "-d")
            wait_ready(int(values["SPEECH_PORT"]), values["SPEECH_BIND_IP"])
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
