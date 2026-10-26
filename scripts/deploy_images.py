"""Focused image identity, retention and container CUDA checks for make install."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import compose, preflight  # noqa: E402

SERVICES = {
    "gateway": ("speech-platform-gateway", "gateway", "foundation"),
    "stt": ("speech-platform-stt-cuda", "stt-worker", "cuda"),
    "tts": ("speech-platform-tts", "tts-worker", "cuda"),
}
CUDA_PROBE = (
    "import ctypes; c=ctypes.CDLL('libcuda.so.1'); "
    "assert c.cuInit(0)==0; n=ctypes.c_int(); "
    "assert c.cuDeviceGetCount(ctypes.byref(n))==0 and n.value>0; "
    "print('PASS: container CUDA driver/device access')"
)


class DeployError(RuntimeError):
    pass


def docker(args, *, capture=True, timeout=60, check=True):
    _compose, env = compose.setup(ROOT)
    try:
        result = subprocess.run(
            ["docker", "--context", "default", *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=capture,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeployError("Docker command did not complete") from exc
    if check and result.returncode:
        raise DeployError("Docker command failed; inspect Docker status and logs")
    return result


def compose_run(args, *, capture=True, timeout=60, check=True):
    try:
        result = compose.run(args, root=ROOT, timeout=timeout, capture=capture)
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        preflight.PreflightError,
    ) as exc:
        raise DeployError("Compose command did not complete") from exc
    if check and result.returncode:
        raise DeployError("Compose command failed; inspect Docker status and logs")
    return result


def revision():
    try:
        value = preflight.run_command(["git", "rev-parse", "HEAD"], root=ROOT)
    except (OSError, preflight.PreflightError):
        value = ""
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise DeployError("a full committed Git revision is required")
    return value


def source_check():
    rev = revision()
    try:
        dirty = preflight.run_command(
            ["git", "status", "--porcelain", "--untracked-files=all"], root=ROOT
        )
    except (OSError, preflight.PreflightError) as exc:
        raise DeployError("could not verify source worktree state") from exc
    if dirty:
        raise DeployError("make install requires a clean Git worktree")
    print(f"Verified clean committed source {rev}")


def parse_json_lines(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else [value]
    except json.JSONDecodeError:
        try:
            return [json.loads(line) for line in raw.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise DeployError("Docker returned invalid container metadata") from exc


def inspect_container(container_id):
    data = parse_json_lines(docker(["inspect", container_id]).stdout)
    if len(data) != 1:
        raise DeployError("container identity was missing or ambiguous")
    return data[0]


def check_owner(container, service):
    labels = (container.get("Config") or {}).get("Labels") or {}
    expected = {
        "com.docker.compose.project": "speech-platform",
        "com.docker.compose.service": service,
        "com.docker.compose.project.working_dir": str(ROOT.resolve()),
    }
    if any(labels.get(name) != value for name, value in expected.items()):
        raise DeployError(f"{service} container is not owned by this Compose project")
    configs = {
        str(Path(path).resolve())
        for path in labels.get("com.docker.compose.project.config_files", "").split(",")
        if path
    }
    allowed = {
        str((ROOT / "compose.yaml").resolve()),
        str((ROOT / "deployments/compose/compose.ollama.yaml").resolve()),
    }
    if (
        not configs
        or not configs <= allowed
        or str((ROOT / "compose.yaml").resolve()) not in configs
    ):
        raise DeployError(f"{service} container uses an unexpected Compose file")


def parse_components(raw):
    parts = raw.split(",")
    if any(not part.strip() for part in parts):
        raise DeployError(
            "components must be a unique comma-separated selection including gateway"
        )
    components = tuple(part.strip() for part in parts)
    if (
        not components
        or components[0] != "gateway"
        or len(components) != len(set(components))
        or not set(components) <= set(SERVICES)
    ):
        raise DeployError(
            "components must be a unique comma-separated selection including gateway"
        )
    return components


def project_containers(components=None):
    selected = set(components or SERVICES)
    rows = parse_json_lines(
        compose_run(["ps", "--all", "--format", "json"]).stdout.strip()
    )
    seen = set()
    containers = []
    for row in rows:
        if not row:
            continue
        service = row.get("Service")
        container_id = row.get("ID") or row.get("Id")
        if service not in SERVICES or not container_id or service in seen:
            raise DeployError(
                "Compose project has unknown or ambiguous service containers"
            )
        seen.add(service)
        container = inspect_container(container_id)
        check_owner(container, service)
        if service in selected:
            containers.append((service, container))
    return containers


def retain(components=None):
    containers = project_containers(components)
    for service, container in containers:
        image_id = container.get("Image")
        if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
            raise DeployError(f"{service} running image ID is unavailable")
        tag = f"speech-platform-rollback-{service}:{image_id[7:]}"
        result = docker(["image", "inspect", tag], check=False)
        if result.returncode:
            docker(["image", "tag", image_id, tag], capture=False)
        else:
            images = parse_json_lines(result.stdout)
            if len(images) != 1 or images[0].get("Id") != image_id:
                raise DeployError(
                    f"rollback tag for {service} conflicts with another image"
                )
        print(f"Retained {service} image {image_id} as {tag}")
    if not containers:
        print("No existing SpeechPlatform containers to retain")


def built_images(components=None):
    rev = revision()
    identities = {}
    selected = components or tuple(SERVICES)
    for service in selected:
        name, role, variant = SERVICES[service]
        reference = f"{name}:{rev}"
        images = parse_json_lines(docker(["image", "inspect", reference]).stdout)
        if len(images) != 1:
            raise DeployError(f"{service} image is missing or ambiguous")
        image = images[0]
        labels = (image.get("Config") or {}).get("Labels") or {}
        required = {
            "org.opencontainers.image.revision": rev,
            "com.speech-platform.service": service,
            "com.speech-platform.service-role": role,
            "com.speech-platform.runtime-variant": variant,
        }
        if (
            image.get("Os") != "linux"
            or image.get("Architecture") != "amd64"
            or any(labels.get(k) != v for k, v in required.items())
        ):
            raise DeployError(
                f"{service} image source, role or platform validation failed"
            )
        identities[service] = (reference, image["Id"])
    return identities


def verify(components=None):
    for service, (reference, image_id) in built_images(components).items():
        print(f"Verified {service}: {reference} {image_id}")


def cuda_probe(components=None):
    selected = components or tuple(SERVICES)
    values = preflight.load_env(ROOT)
    preflight.validate_environment(values, ROOT, components=selected)
    identities = built_images(selected)
    for service in ("stt", "tts"):
        if service not in selected:
            continue
        reference, _ = identities[service]
        device = values[service.upper() + "_GPU_DEVICE"]
        name = f"speech-platform-cuda-probe-{service}-{uuid.uuid4().hex[:12]}"
        args = [
            "run",
            "--rm",
            "--name",
            name,
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--user",
            "65532:65532",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--pids-limit",
            "32",
            "--gpus",
            f"device={device}",
            "--entrypoint",
            "python",
            reference,
            "-c",
            CUDA_PROBE,
        ]
        failure = None
        try:
            result = docker(args, capture=False, timeout=60, check=False)
            if result.returncode:
                failure = f"{service} CUDA probe failed; services were not replaced"
        except DeployError:
            failure = (
                f"{service} CUDA probe did not complete; services were not replaced"
            )
        cleanup = docker(["rm", "-f", name], check=False, timeout=15)
        absent = "No such container" in (cleanup.stderr or "") or "No such object" in (
            cleanup.stderr or ""
        )
        if cleanup.returncode and not absent:
            raise DeployError(f"{service} CUDA probe cleanup is unconfirmed for {name}")
        if failure:
            raise DeployError(failure)


def running(components=None):
    selected = components or tuple(SERVICES)
    identities = built_images(selected)
    for service, (reference, image_id) in identities.items():
        raw = compose_run(["ps", "--quiet", service]).stdout.strip()
        ids = [line for line in raw.splitlines() if line]
        if len(ids) != 1:
            raise DeployError(f"{service} does not have one running container")
        container = inspect_container(ids[0])
        check_owner(container, service)
        if container.get("Image") != image_id:
            raise DeployError(
                f"{service} running image differs from the verified build"
            )
        state = (container.get("State") or {}).get("Status")
        if state != "running":
            raise DeployError(f"{service} container is not running")
        print(f"Running {service}: {reference} {image_id}")


def status(service=None):
    rows = parse_json_lines(
        compose_run(
            ["ps", "--all", "--format", "json", *([service] if service else [])]
        ).stdout.strip()
    )
    for row in rows:
        if not row:
            continue
        container_id = row.get("ID") or row.get("Id")
        container = inspect_container(container_id)
        service = row.get("Service")
        if service not in SERVICES:
            raise DeployError("Compose project contains an unsupported service")
        check_owner(container, service)
        image_id = container.get("Image", "unknown")
        image_data = parse_json_lines(docker(["image", "inspect", image_id]).stdout)
        labels = (image_data[0].get("Config") or {}).get("Labels") or {}
        source = labels.get("org.opencontainers.image.revision", "unknown")
        print(
            f"{service}: state={row.get('State', 'unknown')} "
            f"health={row.get('Health', 'unknown')} image={image_id} source={source}"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("source", "retain", "verify", "cuda", "running", "status")
    )
    parser.add_argument("service", nargs="?", choices=tuple(SERVICES))
    parser.add_argument("--components", default=",".join(SERVICES))
    args = parser.parse_args(argv)
    try:
        components = parse_components(args.components)
        if args.action == "source":
            source_check()
        elif args.action == "status":
            status(args.service)
        elif args.service:
            raise DeployError("service selection is supported only for status")
        else:
            {
                "retain": lambda: retain(components),
                "verify": lambda: verify(components),
                "cuda": lambda: cuda_probe(components),
                "running": lambda: running(components),
            }[args.action]()
    except (
        DeployError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        preflight.PreflightError,
    ) as exc:
        print(f"Installation check failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
