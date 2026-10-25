"""Run the supported SpeechPlatform Compose commands with fixed ownership."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from scripts import preflight  # noqa: E402
from services.worker.server import StrictLoader  # noqa: E402

COMMANDS = {"build", "exec", "logs", "ps", "stop", "up"}
SERVICES = {"gateway", "stt", "tts"}


def validate_args(args):
    action, rest = args[0], args[1:]
    if action == "build" and rest == ["gateway", "stt", "tts"]:
        return
    if action == "up" and rest == [
        "-d",
        "--no-build",
        "--pull",
        "never",
        "--wait",
        "--wait-timeout",
        "240",
    ]:
        return
    if action == "stop" and (not rest or (len(rest) == 1 and rest[0] in SERVICES)):
        return
    if action == "ps" and rest in (
        ["--all"],
        ["--all", "--format", "json"],
        ["--all", "--format", "json", "gateway"],
        ["--all", "--format", "json", "stt"],
        ["--all", "--format", "json", "tts"],
        ["--all", "gateway"],
        ["--all", "stt"],
        ["--all", "tts"],
        ["--quiet", "gateway"],
        ["--quiet", "stt"],
        ["--quiet", "tts"],
    ):
        return
    if action == "logs" and (
        rest == ["--tail", "100"]
        or rest
        in (
            ["--tail", "100", "gateway"],
            ["--tail", "100", "stt"],
            ["--tail", "100", "tts"],
        )
    ):
        return
    ready = {
        ("exec", "-T", "gateway", "/healthcheck", "http://127.0.0.1:8080/readyz"),
        (
            "exec",
            "-T",
            "stt",
            "python",
            "-c",
            'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8081/readyz", timeout=3)',
        ),
        (
            "exec",
            "-T",
            "tts",
            "python",
            "-c",
            'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8082/readyz", timeout=3)',
        ),
    }
    if tuple(args) in ready:
        return
    raise ValueError("unsupported or unsafe Compose invocation")


def setup(root=ROOT):
    values = preflight.load_env(root)
    revision = preflight.run_command(["git", "rev-parse", "HEAD"], root=root)
    config = preflight.gateway_config_path(root, values)
    env = preflight._compose_environment(values, revision, config, root)
    env.pop("DOCKER_CONTEXT", None)
    env.pop("DOCKER_HOST", None)
    env["COMPOSE_PROJECT_NAME"] = "speech-platform"

    command = [
        "docker",
        "--context",
        "default",
        "compose",
        "--project-name",
        "speech-platform",
        "--env-file",
        str(root / ".env"),
        "-f",
        str(root / "compose.yaml"),
    ]
    document = yaml.load(config.read_text(), Loader=StrictLoader)
    if preflight.uses_local_ollama(document or {}):
        command.extend(["-f", str(root / "deployments/compose/compose.ollama.yaml")])
    return command, env


def verify_project(root=ROOT):
    _command, env = setup(root)
    result = subprocess.run(
        ["docker", "--context", "default", "compose", "ls", "--format", "json"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("could not verify Compose project ownership")
    try:
        projects = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Docker returned invalid Compose project metadata") from exc
    canonical = str((root / "compose.yaml").resolve())
    overlay = str((root / "deployments/compose/compose.ollama.yaml").resolve())
    for project in projects:
        if project.get("Name") != "speech-platform":
            continue
        files = {
            str(Path(item).resolve())
            for item in project.get("ConfigFiles", "").split(",")
            if item
        }
        if canonical not in files or not files <= {canonical, overlay}:
            raise RuntimeError(
                "Compose project speech-platform belongs to another configuration"
            )


def run(args, *, root=ROOT, timeout=300, capture=False):
    if not args or args[0] not in COMMANDS:
        raise ValueError("unsupported Compose command")
    validate_args(args)
    command, env = setup(root)
    if args[0] in {"exec", "logs", "ps", "stop", "up"}:
        verify_project(root)
    return subprocess.run(
        [*command, *args],
        cwd=root,
        env=env,
        timeout=timeout,
        text=True,
        capture_output=capture,
        check=False,
    )


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        result = run(args, timeout=1800 if args and args[0] == "build" else 300)
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        preflight.PreflightError,
    ) as exc:
        print(f"Compose command failed safely: {exc}", file=sys.stderr)
        return 2
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
