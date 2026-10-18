"""Host-side, privacy-filtered launcher for one isolated CUDA diagnostic."""

from __future__ import annotations

import json
import math
import os
import re
import selectors
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

try:
    from stt_cuda_mount import ReportMountPreflightError, validate_static_report_mount
except ModuleNotFoundError:
    from scripts.stt_cuda_mount import (
        ReportMountPreflightError,
        validate_static_report_mount,
    )

MAX_CAPTURE_BYTES = 64 * 1024
MAX_ATTEMPTS = 20
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def atomic_write(path: Path, value: dict) -> None:
    """Write private JSON atomically in its already-private parent directory."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def classify_output(data: bytes, truncated: bool) -> dict:
    """Return safe output metadata; never persist arbitrary process text."""
    if len(data) > MAX_CAPTURE_BYTES:
        data = data[:MAX_CAPTURE_BYTES]
        truncated = True
    decoded = data.decode("utf-8", errors="replace").lower()
    classifications = []
    patterns = (
        (
            "report_mount_unwritable",
            (
                '"failed_stage": "report_mount_validation"',
                '"failed_stage":"report_mount_validation"',
            ),
        ),
        (
            "docker_daemon_unavailable",
            ("cannot connect to the docker daemon", "is the docker daemon running"),
        ),
        ("permission_denied", ("permission denied", "operation not permitted")),
        (
            "image_unavailable",
            ("no such image", "pull access denied", "manifest unknown"),
        ),
        (
            "runtime_start_failure",
            (
                "failed to create task",
                "error while creating mount",
                "failed to create shim",
                "oci runtime create failed",
                "error mounting",
            ),
        ),
        (
            "executable_unavailable",
            (
                "executable file not found in $path",
                "executable not found",
                "exec format error",
            ),
        ),
        (
            "mount_setup_failure",
            (
                "invalid mount config",
                "bind source path does not exist",
                "mounts denied",
            ),
        ),
        (
            "python_import_failure",
            ("modulenotfounderror", "no module named", "importerror:"),
        ),
        (
            "python_probe_failure",
            ("traceback (most recent call last)", "assertionerror", "permissionerror"),
        ),
        ("process_terminated", ("terminated", "killed")),
    )
    for label, needles in patterns:
        if any(needle in decoded for needle in needles):
            classifications.append(label)
    if data and not classifications:
        classifications.append("unclassified_output_redacted")
    return {
        "bytes_observed_capped": len(data),
        "truncated": truncated,
        "classifications": classifications,
    }


@dataclass(frozen=True)
class ProcessOutcome:
    started: bool
    exit_code: int | None
    timed_out: bool
    termination_requested: bool
    kill_requested: bool
    exit_confirmed: bool
    start_error_class: str | None
    started_at: str
    ended_at: str
    stdout: dict
    stderr: dict


class Runner(Protocol):
    def run(
        self,
        command: list[str],
        *,
        timeout_seconds: float,
        grace_seconds: float,
        stdout_path: Path,
        stderr_path: Path,
    ) -> ProcessOutcome: ...


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _docker_option(args: list[str], name: str) -> list[str]:
    values = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == name and index + 1 < len(args):
            values.append(args[index + 1])
            index += 2
            continue
        if arg.startswith(name + "="):
            values.append(arg.partition("=")[2])
        index += 1
    return values


def _memory_bytes(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)(b|k|m|g|kb|mb|gb|ki|mi|gi)?", value.lower())
    if not match:
        raise ValueError("CUDA HTTP memory limit is invalid")
    amount = int(match.group(1))
    unit = match.group(2) or "b"
    scale = {
        "b": 1,
        "k": 1000,
        "m": 1000**2,
        "g": 1000**3,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "ki": 1024,
        "mi": 1024**2,
        "gi": 1024**3,
    }[unit]
    return amount * scale


def validate_docker_invocation(
    command: list[str],
    *,
    cuda_http_profile: bool = False,
    expected_gpu_index: int | None = None,
    expected_image_id: str | None = None,
    expected_platform: str | None = None,
    expected_shared_gid: int | None = None,
) -> dict | None:
    """Reject obvious violations of this diagnostic's isolation boundary."""
    if len(command) < 3 or Path(command[0]).name != "docker" or command[1] != "run":
        raise ValueError("launcher requires a docker run argument vector")
    args = command[2:]
    network_none = "--network=none" in args or any(
        args[index] == "--network"
        and index + 1 < len(args)
        and args[index + 1] == "none"
        for index in range(len(args))
    )
    if not network_none:
        raise ValueError("diagnostic container must use network none")
    if any(
        arg in {"-p", "-P", "--publish", "--publish-all"}
        or arg.startswith("--publish=")
        or (arg.startswith("-p") and len(arg) > 2)
        for arg in args
    ):
        raise ValueError("diagnostic container cannot publish ports")
    user_value = None
    mounts = []
    for index, arg in enumerate(args):
        if arg == "--user" and index + 1 < len(args):
            user_value = args[index + 1]
        elif arg.startswith("--user="):
            user_value = arg.partition("=")[2]
        elif arg == "--mount" and index + 1 < len(args):
            mounts.append(args[index + 1])
        elif arg.startswith("--mount="):
            mounts.append(arg.partition("=")[2])
    if user_value is None or user_value.split(":", 1)[0] in {"0", "root"}:
        raise ValueError("diagnostic container must specify a non-root user")

    parsed_mounts = []
    for mount in mounts:
        fields = dict(part.split("=", 1) for part in mount.split(",") if "=" in part)
        flags = set(mount.split(","))
        if fields.get("type") == "bind" and fields.get("src") and fields.get("dst"):
            parsed_mounts.append(
                (Path(fields["src"]), fields["dst"].rstrip("/"), flags)
            )
    if cuda_http_profile and len(parsed_mounts) != len(mounts):
        raise ValueError("CUDA HTTP container permits bind mounts only")
    for source, destination, flags in parsed_mounts:
        if "readonly" not in flags and "ro" not in flags:
            continue
        if not source.is_dir():
            continue
        for _nested_source, nested_destination, _nested_flags in parsed_mounts:
            prefix = destination + "/"
            if not nested_destination.startswith(prefix):
                continue
            relative = nested_destination[len(prefix) :]
            target = source / relative
            if not target.exists():
                raise ValueError(
                    "nested bind target must exist inside its read-only parent source"
                )

    if not cuda_http_profile:
        return None
    if expected_gpu_index is None or expected_gpu_index < 0:
        raise ValueError("CUDA HTTP profile requires a validated configured GPU index")
    if _docker_option(args, "--network") != ["none"]:
        raise ValueError(
            "CUDA HTTP container must use exactly one isolated network mode"
        )
    if expected_image_id is None or args.count(expected_image_id) != 1:
        raise ValueError("Docker image must match the approved immutable image ID")
    if expected_platform is None or _docker_option(args, "--platform") != [
        expected_platform
    ]:
        raise ValueError("Docker platform must match the approved image platform")
    if _docker_option(args, "--pull") != ["never"]:
        raise ValueError("CUDA HTTP container must not pull an image at runtime")
    if "--read-only" not in args:
        raise ValueError("CUDA HTTP container root filesystem must be read-only")
    if any(
        arg in {"--privileged", "--cap-add"} or arg.startswith("--cap-add=")
        for arg in args
    ):
        raise ValueError("CUDA HTTP container cannot request privileged capabilities")
    if any(
        arg in {"-v", "--volume", "--device", "--tmpfs", "--volumes-from"}
        or arg.startswith(("--volume=", "--device=", "--tmpfs=", "--volumes-from="))
        for arg in args
    ):
        raise ValueError(
            "CUDA HTTP container uses an unsupported mount or device option"
        )
    if _docker_option(args, "--entrypoint") != ["python"]:
        raise ValueError("CUDA HTTP container must use the approved Python entrypoint")
    if _docker_option(args, "--user") != ["65532:65532"]:
        raise ValueError(
            "CUDA HTTP container must use the configured non-root identity"
        )
    if expected_shared_gid is None or _docker_option(args, "--group-add") != [
        str(expected_shared_gid)
    ]:
        raise ValueError("CUDA HTTP group must match the report mount group")
    gpu_values = _docker_option(args, "--gpus")
    if gpu_values != [f"device={expected_gpu_index}"]:
        raise ValueError("Docker GPU selection must match deployment configuration")

    memory = _docker_option(args, "--memory")
    cpus = _docker_option(args, "--cpus")
    pids = _docker_option(args, "--pids-limit")
    if len(memory) != 1 or _memory_bytes(memory[0]) <= 0:
        raise ValueError("CUDA HTTP container requires one positive memory limit")
    if len(cpus) != 1:
        raise ValueError("CUDA HTTP container requires one CPU limit")
    try:
        cpu_limit = float(cpus[0])
    except ValueError as exc:
        raise ValueError("CUDA HTTP CPU limit is invalid") from exc
    if not (0 < cpu_limit < float("inf")):
        raise ValueError("CUDA HTTP CPU limit must be finite and positive")
    if len(pids) != 1 or not pids[0].isdecimal() or int(pids[0]) < 1:
        raise ValueError("CUDA HTTP container requires one positive PID limit")

    destinations = {}
    writable = []
    for source, destination, flags in parsed_mounts:
        destinations[destination] = flags
        if "readonly" not in flags and "ro" not in flags:
            writable.append(destination)
    if len(destinations) != len(parsed_mounts):
        raise ValueError("CUDA HTTP bind mount destinations must be unique")
    required = {
        "/input",
        "/models",
        "/opt/validation/configs",
        "/opt/validation/scripts",
        "/opt/validation/services",
        "/results",
    }
    if not required.issubset(destinations):
        raise ValueError(
            "CUDA HTTP input, artifact, code and report mounts are required"
        )
    if writable != ["/results"]:
        raise ValueError("only the attempt-specific results mount may be writable")
    return {
        "gpu_device_index": expected_gpu_index,
        "cpu_limit": cpu_limit,
        "memory_limit_bytes": _memory_bytes(memory[0]),
        "pids_limit": int(pids[0]),
    }


class _BoundedOutput:
    def __init__(self, path: Path):
        self.path = path
        self.data = bytearray()
        self.truncated = False
        self.total = 0

    def accept(self, chunk: bytes) -> None:
        self.total += len(chunk)
        room = MAX_CAPTURE_BYTES - len(self.data)
        if room > 0:
            self.data.extend(chunk[:room])
        if len(chunk) > room:
            self.truncated = True

    def persist(self) -> dict:
        safe = classify_output(bytes(self.data), self.truncated)
        safe["total_bytes_observed"] = self.total
        self.path.write_text(json.dumps(safe, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(self.path, 0o600)
        return safe


class SubprocessRunner:
    """Run a command with bounded capture and bounded terminate/kill waits."""

    def run(
        self,
        command: list[str],
        *,
        timeout_seconds: float,
        grace_seconds: float,
        stdout_path: Path,
        stderr_path: Path,
    ) -> ProcessOutcome:
        started_at = _utc_now()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            ended = _utc_now()
            for path in (stdout_path, stderr_path):
                path.write_text(
                    '{"bytes_observed_capped":0,"truncated":false,"classifications":[]}\n'
                )
                os.chmod(path, 0o600)
            # Store only a class, never exception text which can contain paths.
            return ProcessOutcome(
                False,
                None,
                False,
                False,
                False,
                True,
                type(exc).__name__,
                started_at,
                ended,
                classify_output(b"", False),
                classify_output(b"", False),
            )

        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        termination_requested = False
        kill_requested = False
        streams = {
            process.stdout: _BoundedOutput(stdout_path),
            process.stderr: _BoundedOutput(stderr_path),
        }
        selector = selectors.DefaultSelector()
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        while process.poll() is None and time.monotonic() < deadline:
            for key, _ in selector.select(
                min(0.1, max(0.0, deadline - time.monotonic()))
            ):
                try:
                    chunk = os.read(key.fileobj.fileno(), 8192)
                except BlockingIOError:
                    continue
                if chunk:
                    streams[key.fileobj].accept(chunk)
                else:
                    selector.unregister(key.fileobj)
        if process.poll() is None:
            timed_out = True
            termination_requested = True
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                kill_requested = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=grace_seconds)
                except subprocess.TimeoutExpired:
                    pass
        # Drain remaining bytes for a bounded interval; retain only safe classifications.
        drain_deadline = time.monotonic() + min(2.0, grace_seconds)
        while selector.get_map() and time.monotonic() < drain_deadline:
            for key, _ in selector.select(min(0.1, drain_deadline - time.monotonic())):
                try:
                    chunk = os.read(key.fileobj.fileno(), 8192)
                except BlockingIOError:
                    continue
                if chunk:
                    streams[key.fileobj].accept(chunk)
                else:
                    selector.unregister(key.fileobj)
        selector.close()
        stdout_meta = streams[process.stdout].persist()
        stderr_meta = streams[process.stderr].persist()
        process.stdout.close()
        process.stderr.close()
        try:
            process.wait(timeout=0.01)
            exit_confirmed = True
        except subprocess.TimeoutExpired:
            exit_confirmed = False
        return ProcessOutcome(
            True,
            process.returncode if exit_confirmed else None,
            timed_out,
            termination_requested,
            kill_requested,
            exit_confirmed,
            None,
            started_at,
            _utc_now(),
            stdout_meta,
            stderr_meta,
        )


class DiagnosticLauncher:
    def __init__(
        self,
        root: str | Path,
        runner: Runner,
        *,
        max_attempts: int = MAX_ATTEMPTS,
        shared_gid: int | None = None,
    ):
        self.root = Path(root)
        self.runner = runner
        self.max_attempts = max_attempts
        self.shared_gid = shared_gid

    def run(
        self,
        attempt_id: str,
        command: list[str],
        *,
        image_id: str,
        container_name: str,
        timeout_seconds: float,
        grace_seconds: float,
        harness_report_name: str = "harness-report.json",
        platform: str,
        lock_sha256: str | None = None,
        cuda_http_profile: bool = False,
        expected_gpu_index: int | None = None,
    ) -> dict:
        if not SAFE_ID.fullmatch(attempt_id) or not SAFE_ID.fullmatch(container_name):
            raise ValueError("attempt and container identifiers must be safe tokens")
        if not image_id.startswith("sha256:") or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", image_id
        ):
            raise ValueError("image identity must be a sha256 digest")
        if platform not in {"linux/amd64", "linux/arm64"}:
            raise ValueError("platform must be a supported linux architecture token")
        if lock_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", lock_sha256):
            raise ValueError("lock digest must be SHA-256")
        if not command or not all(isinstance(arg, str) for arg in command):
            raise ValueError("command must be a non-empty argument vector")
        if (
            not math.isfinite(timeout_seconds)
            or not math.isfinite(grace_seconds)
            or timeout_seconds <= 0
            or grace_seconds <= 0
        ):
            raise ValueError("timeouts must be positive")
        if Path(harness_report_name).name != harness_report_name:
            raise ValueError("harness report name must be a basename")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("attempt root cannot be a symlink")
        os.chmod(self.root, 0o700)
        if self.shared_gid is not None and self.shared_gid <= 0:
            raise ValueError("shared group id must be non-root")
        existing = [entry for entry in self.root.iterdir() if entry.is_dir()]
        if len(existing) >= self.max_attempts:
            raise RuntimeError(
                "attempt retention limit reached; operator review and deletion required"
            )
        attempt = self.root / attempt_id
        attempt.mkdir(mode=0o700)
        os.chmod(attempt, 0o700)
        harness_dir = attempt / "harness"
        harness_dir.mkdir(mode=0o700)
        if self.shared_gid is not None:
            os.chown(harness_dir, -1, self.shared_gid)
            os.chmod(harness_dir, 0o2770)
        report_path = attempt / "launcher-report.json"
        report = {
            "schema_version": 1,
            "outcome": "running",
            "attempt_id": attempt_id,
            "container": {
                "name": container_name,
                "image_id": image_id,
                "platform": platform,
                "id": None,
            },
            "dependency_lock_sha256": lock_sha256,
            "launch": {
                "executable": Path(command[0]).name,
                "argument_count": len(command),
                "network_mode": "none",
                "ports_published": False,
                "timeout_seconds": timeout_seconds,
                "started_at": _utc_now(),
            },
            "container_created": None,
            "process": None,
            "harness_report": {
                "present": False,
                "directory": "harness",
                "file": harness_report_name,
            },
            "report_mount_preflight": None,
        }
        atomic_write(report_path, report)
        try:
            actual_command = [
                arg.replace("{attempt_dir}", str(attempt)).replace(
                    "{harness_dir}", str(harness_dir)
                )
                for arg in command
            ]
            report["launch"]["cuda_http_limits"] = validate_docker_invocation(
                actual_command,
                cuda_http_profile=cuda_http_profile,
                expected_gpu_index=expected_gpu_index,
                expected_image_id=image_id,
                expected_platform=platform,
                expected_shared_gid=self.shared_gid,
            )
            if self.shared_gid is not None:
                report["report_mount_preflight"] = validate_static_report_mount(
                    harness_dir,
                    actual_command,
                    expected_group=self.shared_gid,
                )
            outcome = self.runner.run(
                actual_command,
                timeout_seconds=timeout_seconds,
                grace_seconds=grace_seconds,
                stdout_path=attempt / "stdout.json",
                stderr_path=attempt / "stderr.json",
            )
            report["process"] = asdict(outcome)
            cidfile = attempt / "container.id"
            if cidfile.is_file() and not cidfile.is_symlink():
                candidate = cidfile.read_text(encoding="ascii").strip()
                if re.fullmatch(r"[0-9a-f]{64}", candidate):
                    report["container"]["id"] = candidate
                    report["container_created"] = True
            elif outcome.started:
                report["container_created"] = False
            report["exact_container_postflight_required"] = bool(
                outcome.timed_out and report["container_created"] is True
            )
            harness_path = harness_dir / harness_report_name
            if harness_path.is_file() and not harness_path.is_symlink():
                report["harness_report"]["present"] = True
            if not outcome.started:
                report["outcome"] = "launch_failed"
                report["failure_layer"] = "host_process_launch"
            elif "report_mount_unwritable" in outcome.stdout.get("classifications", []):
                report["outcome"] = "container_preflight_failed"
                report["failure_layer"] = "container_report_mount"
                report["diagnostic_code"] = "report_mount_validation_failed"
            elif not outcome.exit_confirmed:
                report["outcome"] = "cleanup_unconfirmed"
                report["failure_layer"] = "host_process_cleanup"
            elif outcome.timed_out:
                report["outcome"] = "timeout"
                report["failure_layer"] = "docker_run_or_container"
            elif outcome.exit_code != 0:
                if outcome.exit_code == 125:
                    report["outcome"] = "docker_run_failed"
                    report["failure_layer"] = "docker_cli_or_daemon"
                elif outcome.exit_code in {126, 127}:
                    report["outcome"] = "container_command_failed"
                    report["failure_layer"] = "container_exec"
                elif report["container_created"]:
                    report["outcome"] = "container_start_or_process_failed"
                    report["failure_layer"] = "container_start_or_process"
                else:
                    report["outcome"] = "docker_run_failed"
                    report["failure_layer"] = "docker_cli_or_daemon"
            elif not report["harness_report"]["present"]:
                report["outcome"] = "harness_report_missing"
                report["failure_layer"] = "container_completed_without_report"
            else:
                report["outcome"] = "completed"
        except BaseException as exc:
            for path in (attempt / "stdout.json", attempt / "stderr.json"):
                if not path.exists():
                    path.write_text(
                        '{"bytes_observed_capped":0,"truncated":false,"classifications":[]}\n',
                        encoding="utf-8",
                    )
                    os.chmod(path, 0o600)
            if isinstance(exc, ReportMountPreflightError):
                report["outcome"] = "preflight_failed"
                report["failure_layer"] = "host_static_report_mount"
                report["diagnostic_code"] = exc.code
            else:
                report["outcome"] = "launcher_failed"
                report["launcher_error_class"] = type(exc).__name__
            report["ended_at"] = _utc_now()
            atomic_write(report_path, report)
            if isinstance(exc, ReportMountPreflightError):
                for path in (attempt / "stdout.json", attempt / "stderr.json"):
                    path.write_text(
                        '{"bytes_observed_capped":0,"truncated":false,"classifications":[]}\n',
                        encoding="utf-8",
                    )
                    os.chmod(path, 0o600)
                return report
            raise
        report["ended_at"] = _utc_now()
        atomic_write(report_path, report)
        return report
