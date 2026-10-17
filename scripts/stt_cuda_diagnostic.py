"""Offline-testable, privacy-filtered CUDA STT diagnostic runner.

The CLI is intended for a separately authorized, isolated validation container.
It performs no model provisioning and requires explicit CUDA configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import stat
import tempfile
import time
import traceback
from pathlib import Path

from scripts.stt_cuda_preflight import verify_approved_audio
from scripts.stt_cuda_mount import (
    ReportMountPreflightError,
    validate_container_report_mount,
)

STAGES = (
    "report_mount_validation",
    "dependency_check",
    "configuration_parsing",
    "cuda_profile_validation",
    "artifact_validation",
    "model_load",
    "transcribe_call",
    "segment_iteration",
    "output_validation",
)

_SAFE_ATOM = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:\\[^\s'\"]+|/(?:[^\s'\"]+))")
_SECRET = re.compile(
    r"(?i)\b(?:bearer\s+|token|password|passwd|secret|api[_-]?key|credential)"
    r"\s*[:=]?\s*[^\s,;]+"
)
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_+/=-]{32,}\b")
_SAFE_MESSAGE = re.compile(
    r"^(?:"
    r"got an unexpected keyword argument ['\"][A-Za-z0-9_]{1,80}['\"]|"
    r"takes \d+ positional arguments? but \d+ were given|"
    r"missing \d+ required positional arguments?: (?:['\"][A-Za-z0-9_]+['\"])(?:, ['\"][A-Za-z0-9_]+['\"])*|"
    r"expected (?:at least|exactly) \d+ arguments?, got \d+|"
    r"['\"][A-Za-z0-9_.]+['\"] object has no attribute ['\"][A-Za-z0-9_]+['\"]|"
    r"CUDA (?:device|compute type) (?:is unavailable|is unsupported)"
    r")$"
)


class DiagnosticFailure(Exception):
    def __init__(self, stage: str, diagnostic: dict):
        super().__init__(f"diagnostic stage failed: {stage}")
        self.stage = stage
        self.diagnostic = diagnostic


class DiagnosticPolicyFailure(ValueError):
    """A parsed configuration failed a fixed diagnostic-only policy."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.diagnostic_code = code


CUDA_DIAGNOSTIC_DEVICE_INDEX = 0
CUDA_DIAGNOSTIC_MINIMUM_FREE_GPU_BYTES = 12 * 1024**3
SAFE_DIAGNOSTIC_CODES = {
    "configuration_invalid",
    "cuda_profile_backend_unsupported",
    "cuda_profile_compute_configuration_missing",
    "cuda_profile_device_index_mismatch",
    "cuda_profile_explicit_cuda_required",
    "cuda_profile_memory_gate_insufficient",
    "cuda_profile_version_unsupported",
    "report_mount_directory_missing_or_unsafe",
    "report_mount_acl_unreadable",
    "report_mount_acl_present",
    "report_mount_write_verification_failed",
    "report_mount_group_not_effective",
    "report_mount_report_mode_invalid",
    "report_mount_write_failed",
    "report_mount_owner_mismatch",
    "report_mount_group_mismatch",
    "report_mount_mode_mismatch",
    "report_mount_host_group_unavailable",
    "report_mount_parent_traversal_unavailable",
    "report_mount_container_identity_mismatch",
    "report_mount_supplementary_group_mismatch",
    "report_mount_root_filesystem_not_readonly",
    "report_mount_bind_configuration_invalid",
}


def _safe_message(exc: BaseException) -> str:
    raw = str(exc).replace("\n", " ").replace("\r", " ")[:512]
    scrubbed = _PATH.sub("<path>", raw)
    scrubbed = _SECRET.sub("<secret-redacted>", scrubbed)
    scrubbed = _LONG_TOKEN.sub("<value-redacted>", scrubbed)
    scrubbed = " ".join(scrubbed.split())
    if "<path>" in scrubbed or "<secret-redacted>" in scrubbed:
        return "<message-redacted>"
    if _SAFE_MESSAGE.fullmatch(scrubbed):
        return scrubbed
    return "<message-suppressed>"


def _safe_traceback(exc: BaseException) -> list[dict]:
    frames = []
    for frame in traceback.extract_tb(exc.__traceback__)[-12:]:
        filename = Path(frame.filename).name
        function = frame.name
        safe_filename = (
            filename
            if filename.endswith(".py") and _SAFE_ATOM.fullmatch(filename)
            else "<file>"
        )
        frames.append(
            {
                "file": safe_filename,
                "line": frame.lineno if frame.lineno > 0 else None,
                "function": function
                if _SAFE_ATOM.fullmatch(function)
                else "<function>",
            }
        )
    return frames


def _exception_record(exc: BaseException) -> dict:
    name = type(exc).__name__
    if not _SAFE_ATOM.fullmatch(name):
        name = "Exception"
    record = {
        "type": name,
        "message": _safe_message(exc),
        "frames": _safe_traceback(exc),
    }
    code = getattr(exc, "diagnostic_code", None)
    if code in SAFE_DIAGNOSTIC_CODES:
        record["diagnostic_code"] = code
    causes = []
    cause = exc.__cause__ or exc.__context__
    while cause is not None and len(causes) < 3:
        cause_name = type(cause).__name__
        causes.append(
            {
                "type": cause_name if _SAFE_ATOM.fullmatch(cause_name) else "Exception",
                "message": _safe_message(cause),
                "frames": _safe_traceback(cause),
            }
        )
        cause = cause.__cause__ or cause.__context__
    if causes:
        record["causes"] = causes
    return record


def atomic_write_report(path: str | Path, report: dict) -> None:
    """Atomically persist a JSON report with owner-only permissions."""
    target = Path(path)
    parent = target.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("report directory must already exist and cannot be a symlink")
    if target.is_symlink():
        raise ValueError("report target cannot be a symlink")
    fd, temporary = tempfile.mkstemp(prefix=".stt-diagnostic-", dir=parent)
    try:
        # The report directory is operator-group-only; group read allows the
        # host operator to retrieve the result from a non-root container UID.
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class DiagnosticRunner:
    """Runs injected stage operations and persists progress after every stage."""

    def __init__(
        self,
        report_path: str | Path,
        *,
        clock=time.monotonic,
        stages: tuple[str, ...] = STAGES,
        cuda_requested: bool = True,
    ):
        self.report_path = Path(report_path)
        self.clock = clock
        self.stages = stages
        self.cuda_requested = cuda_requested

    def run(self, operations: dict[str, object], metadata: dict | None = None) -> dict:
        if tuple(operations) != self.stages:
            raise ValueError(
                "diagnostic operations must provide the configured stages in order"
            )
        report = {
            "schema_version": 1,
            "outcome": "running",
            "cuda_requested": self.cuda_requested,
            "cpu_fallback": False,
            "metadata": _safe_result(metadata or {}),
            "stages": [
                {"name": stage, "outcome": "pending", "duration_seconds": None}
                for stage in self.stages
            ],
        }
        atomic_write_report(self.report_path, report)
        state = {}
        for index, stage in enumerate(self.stages):
            entry = report["stages"][index]
            entry["outcome"] = "running"
            atomic_write_report(self.report_path, report)
            started = self.clock()
            try:
                state[stage] = operations[stage](state)
            except BaseException as exc:
                entry["duration_seconds"] = round(max(0.0, self.clock() - started), 6)
                entry["outcome"] = "fail"
                entry["exception"] = _exception_record(exc)
                entry["diagnostic_code"] = entry["exception"].get(
                    "diagnostic_code",
                    "configuration_invalid"
                    if stage == "configuration_parsing"
                    else "diagnostic_stage_failed",
                )
                report["outcome"] = "fail"
                report["failed_stage"] = stage
                atomic_write_report(self.report_path, report)
                raise DiagnosticFailure(stage, report) from exc
            entry["duration_seconds"] = round(max(0.0, self.clock() - started), 6)
            entry["outcome"] = "pass"
            if stage == "output_validation":
                report["result"] = _safe_result(state[stage])
            atomic_write_report(self.report_path, report)
        report["outcome"] = "pass"
        atomic_write_report(self.report_path, report)
        return report


def _safe_result(value: dict) -> dict:
    """Keep only non-sensitive, bounded output metadata."""
    allowed = {
        "model_alias",
        "model_revision",
        "manifest_sha256",
        "audio_sha256",
        "language",
        "segment_count",
        "timestamp_bounds_valid",
        "device",
        "compute_type",
        "dependency_versions",
        "lock_sha256",
        "application_device_mode",
        "cuda_device_index",
        "minimum_free_gpu_bytes_before_load",
        "mode",
    }
    result = {}
    for key in allowed:
        if key not in value:
            continue
        item = value[key]
        if key == "dependency_versions" and isinstance(item, dict):
            result[key] = {
                str(name): str(version)
                for name, version in item.items()
                if _SAFE_ATOM.fullmatch(str(name))
                and _SAFE_ATOM.fullmatch(str(version))
            }
        elif (
            key == "model_alias"
            and isinstance(item, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", item)
        ):
            result[key] = item
        elif (
            key
            in {
                "model_revision",
                "manifest_sha256",
                "audio_sha256",
                "lock_sha256",
            }
            and isinstance(item, str)
            and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", item)
        ):
            result[key] = item
        elif (
            key == "language"
            and isinstance(item, str)
            and re.fullmatch(r"[A-Za-z-]{2,16}", item)
        ):
            result[key] = item
        elif key == "device" and item in {"cuda", "cpu"}:
            result[key] = item
        elif key == "application_device_mode" and item in {"cpu", "cuda", "auto"}:
            result[key] = item
        elif key == "mode" and item in {"startup_only", "cuda_diagnostic"}:
            result[key] = item
        elif key in {"cuda_device_index", "minimum_free_gpu_bytes_before_load"} and (
            type(item) is int and item >= 0
        ):
            result[key] = item
        elif (
            key == "compute_type"
            and isinstance(item, str)
            and re.fullmatch(r"[a-z0-9_]{1,32}", item)
        ):
            result[key] = item
        elif key in {"segment_count", "timestamp_bounds_valid"} and isinstance(
            item, (int, bool)
        ):
            result[key] = item
    return result


def assert_explicit_cuda(requested: str, selected: str, actual: str, supported: bool):
    if requested != "cuda" or selected != "cuda" or actual not in {"cuda", "gpu"}:
        raise RuntimeError("explicit CUDA execution could not be confirmed")
    if not supported:
        raise RuntimeError("configured CUDA compute type is unsupported")


def locked_versions(lock_path: str | Path) -> dict[str, str]:
    entries = {}
    for line in Path(lock_path).read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line or line[0].isspace():
            continue
        entry = line.strip().removesuffix("\\").strip()
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^ ]+)$", entry)
        if match:
            entries[re.sub(r"[-_.]+", "-", match.group(1)).lower()] = match.group(2)
    if not entries:
        raise ValueError("CUDA dependency lock contains no pinned packages")
    return entries


def check_installed_dependencies(lock_path: str | Path) -> dict[str, str]:
    locked = locked_versions(lock_path)
    installed = {}
    for name, expected in locked.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(f"locked dependency is not installed: {name}") from exc
        if actual != expected:
            raise RuntimeError(
                f"installed dependency version mismatch: {name} {actual}"
            )
        installed[name] = actual
    return installed


def load_configurations(application_path: str | Path, deployment_path: str | Path):
    """Parse strict app/deployment schemas without applying a device profile."""
    from services.stt.config import load_application_config, load_deployment_config

    return (
        load_application_config(application_path),
        load_deployment_config(deployment_path),
    )


def validate_cuda_profile(app, deployment) -> dict:
    """Apply the approved CUDA diagnostic gate after generic parsing succeeds."""
    if app.device_mode != "cuda":
        raise DiagnosticPolicyFailure(
            "cuda_profile_explicit_cuda_required",
            "CUDA diagnostic requires explicit CUDA selection",
        )
    if app.backend_id != "faster-whisper":
        raise DiagnosticPolicyFailure(
            "cuda_profile_backend_unsupported",
            "CUDA diagnostic backend is unsupported",
        )
    if app.audio_limits is None:
        raise DiagnosticPolicyFailure(
            "cuda_profile_version_unsupported",
            "CUDA diagnostic requires application schema version 3",
        )
    if deployment.cuda_device_index != CUDA_DIAGNOSTIC_DEVICE_INDEX:
        raise DiagnosticPolicyFailure(
            "cuda_profile_device_index_mismatch",
            "CUDA diagnostic requires the approved device index",
        )
    minimum = deployment.minimum_free_gpu_bytes_before_load
    if minimum is None or minimum < CUDA_DIAGNOSTIC_MINIMUM_FREE_GPU_BYTES:
        raise DiagnosticPolicyFailure(
            "cuda_profile_memory_gate_insufficient",
            "CUDA diagnostic free-memory gate is below the approved minimum",
        )
    return {
        "application_device_mode": app.device_mode,
        "cuda_device_index": deployment.cuda_device_index,
        "minimum_free_gpu_bytes_before_load": minimum,
    }


STARTUP_STAGES = ("report_mount_validation", "configuration_parsing")


def _report_mount_operation(report_path, *, cuda_requested=True):
    return lambda _state: validate_container_report_mount(
        report_path, atomic_write_report, cuda_requested=cuda_requested
    )


def build_startup_operations(args):
    def parse_configs(_state):
        app, deployment = load_configurations(
            args.application_config, args.deployment_config
        )
        return {
            "application_device_mode": app.device_mode,
            "cuda_device_index": deployment.cuda_device_index,
            "minimum_free_gpu_bytes_before_load": deployment.minimum_free_gpu_bytes_before_load,
        }

    return {
        "report_mount_validation": _report_mount_operation(
            args.report, cuda_requested=False
        ),
        "configuration_parsing": parse_configs,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_operations(args):
    state = {}

    def dependencies(_state):
        lock_path = Path(args.lock)
        return {
            "versions": check_installed_dependencies(lock_path),
            "lock_sha256": _sha256(lock_path),
        }

    def artifacts(_state):
        from services.stt.artifacts import verify_artifact

        app = state["app"]
        deployment = state["deployment"]
        selection = app.catalog()[app.default_model]
        model_config = next(
            model for model in app.models if model.alias == app.default_model
        )
        location = deployment.artifact_roots[selection.artifact_ref]
        artifact = verify_artifact(model_config, location)
        audio = Path(args.audio)
        audio_digest = verify_approved_audio(audio, args.audio_checksum_file)
        if audio.stat().st_size > app.admission.max_request_bytes:
            raise ValueError("audio input exceeds configured request limit")
        state.update(
            app=app,
            deployment=deployment,
            selection=selection,
            artifact=artifact,
            audio=audio,
            audio_sha256=audio_digest,
        )
        return {
            "model_alias": selection.alias,
            "model_revision": selection.identity.upstream_revision,
            "manifest_sha256": selection.artifact_identity.manifest_sha256,
            "audio_sha256": state["audio_sha256"],
        }

    def parse_configs(_state):
        app, deployment = load_configurations(
            args.application_config, args.deployment_config
        )
        state.update(app=app, deployment=deployment)
        return {
            "application_device_mode": app.device_mode,
            "cuda_device_index": deployment.cuda_device_index,
            "minimum_free_gpu_bytes_before_load": deployment.minimum_free_gpu_bytes_before_load,
        }

    def enforce_cuda_profile(_state):
        return validate_cuda_profile(state["app"], state["deployment"])

    def load_model(_state):
        from services.stt.devices import select_device
        from services.stt.domain import DeviceRequirements, OperationContext
        from services.stt.runtime import create_runtime

        app = state["app"]
        deployment = state["deployment"]
        factory, probe = create_runtime(app, deployment)
        backend = factory()
        requirements = backend.requirements(state["selection"].identity)
        requirements = DeviceRequirements(
            requirements.allowed_kinds,
            requirements.required_features,
            requirements.estimated_peak_memory_bytes,
            requirements.required_features_by_kind,
        )
        devices = probe.discover(OperationContext())
        device = select_device("cuda", ("cuda",), requirements, devices)
        if device.kind != "cuda" or device.handle != str(deployment.cuda_device_index):
            raise RuntimeError("explicit CUDA device selection failed")
        options = dict(app.backend_options)
        compute_type = options["compute_type_cuda"]
        loaded = backend.load(
            state["selection"],
            state["artifact"],
            device,
            OperationContext(),
        )
        # The diagnostic inspects only the adapter's loaded engine device to
        # distinguish requested CUDA from an unexpected backend fallback.
        model = loaded._model
        engine = getattr(model, "model", None)
        actual_device = getattr(engine, "device", None)
        assert_explicit_cuda("cuda", device.kind, actual_device, True)
        state.update(
            model=model, device=device, compute_type=compute_type, loaded_model=loaded
        )
        return {
            "device": "cuda",
            "compute_type": compute_type,
        }

    def call_transcribe(_state):
        options = dict(state["app"].backend_options)
        # Use the bounded production decoder, then pass PCM to faster-whisper.
        # faster-whisper 1.2.1's path decoder passes metadata_errors to av.open,
        # an argument removed by the locked PyAV 19 runtime.
        segments, info = transcribe_with_production_decoder(
            state["model"],
            state["loaded_model"],
            state["audio"],
            options["beam_size"],
        )
        state.update(segments_iterator=segments, info=info)
        return {"iterator_returned": True}

    def iterate_segments(_state):
        segments = list(state["segments_iterator"])
        state["segments"] = segments
        return {"segment_count": len(segments)}

    def validate_output(_state):
        segments = state["segments"]
        info = state["info"]
        language = getattr(info, "language", None)
        if not isinstance(language, str) or not re.fullmatch(
            r"[A-Za-z-]{2,16}", language
        ):
            raise ValueError("transcription language metadata is invalid")
        if not segments:
            raise ValueError("transcription produced no segments")
        previous_end = 0.0
        for segment in segments:
            start, end = float(segment.start), float(segment.end)
            if (
                start < previous_end
                or end < start
                or end > state["app"].audio_limits.max_duration_seconds
            ):
                raise ValueError("transcription timestamps failed bounds validation")
            if not isinstance(segment.text, str):
                raise ValueError("transcription segment text is invalid")
            previous_end = end
        return {
            **state["artifact_metadata"],
            "audio_sha256": state["audio_sha256"],
            "language": language,
            "segment_count": len(segments),
            "timestamp_bounds_valid": True,
            "device": "cuda",
            "compute_type": state["compute_type"],
            "dependency_versions": _state["dependency_check"]["versions"],
            "lock_sha256": _state["dependency_check"]["lock_sha256"],
        }

    def artifacts_and_save_metadata(_state):
        value = artifacts(_state)
        state["artifact_metadata"] = value
        return value

    def load_and_save_metadata(_state):
        value = load_model(_state)
        state["model_metadata"] = value
        return value

    def output(_state):
        return validate_output(_state)

    # Model load follows artifact validation; config is parsed only in that stage.
    return {
        "report_mount_validation": _report_mount_operation(args.report),
        "dependency_check": dependencies,
        "configuration_parsing": parse_configs,
        "cuda_profile_validation": enforce_cuda_profile,
        "artifact_validation": artifacts_and_save_metadata,
        "model_load": load_and_save_metadata,
        "transcribe_call": call_transcribe,
        "segment_iteration": iterate_segments,
        "output_validation": output,
    }


def transcribe_with_production_decoder(model, loaded_model, audio_path, beam_size):
    """Decode bounded audio with the application adapter before engine invocation."""
    from services.stt.backends.faster_whisper import _decode_audio
    from services.stt.domain import OperationContext

    decoded_audio = _decode_audio(
        audio_path.read_bytes(),
        loaded_model._options,
        OperationContext(),
        loaded_model._modules,
    )
    return model.transcribe(
        decoded_audio,
        language=None,
        task="transcribe",
        beam_size=beam_size,
        vad_filter=False,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-config", required=True)
    parser.add_argument("--deployment-config", required=True)
    parser.add_argument("--audio")
    parser.add_argument("--audio-checksum-file")
    parser.add_argument("--lock", default="services/requirements-stt-cuda.lock")
    parser.add_argument("--report", required=True)
    parser.add_argument(
        "--startup-only",
        action="store_true",
        help="parse configuration only; skip CUDA profile checks and inference",
    )
    args = parser.parse_args(argv)
    try:
        validate_container_report_mount(
            args.report,
            atomic_write_report,
            cuda_requested=not args.startup_only,
        )
    except ReportMountPreflightError as exc:
        print(
            json.dumps(
                {
                    "outcome": "fail",
                    "failed_stage": "report_mount_validation",
                    "diagnostic_code": exc.code,
                },
                sort_keys=True,
            )
        )
        return 20
    if args.startup_only:
        operations = build_startup_operations(args)
        runner = DiagnosticRunner(
            args.report, stages=STARTUP_STAGES, cuda_requested=False
        )
    else:
        if not args.audio:
            parser.error("--audio is required unless --startup-only is selected")
        if not args.audio_checksum_file:
            parser.error("--audio-checksum-file is required for CUDA diagnostics")
        operations = build_operations(args)
        runner = DiagnosticRunner(args.report)
    try:
        report = runner.run(
            operations,
            metadata={
                "mode": "startup_only" if args.startup_only else "cuda_diagnostic"
            },
        )
    except DiagnosticFailure as exc:
        print(
            json.dumps({"outcome": "fail", "failed_stage": exc.stage}, sort_keys=True)
        )
        return 1
    except Exception as exc:
        # Preserve infrastructure/setup errors without exposing arbitrary messages.
        report = {
            "schema_version": 1,
            "outcome": "fail",
            "cuda_requested": True,
            "cpu_fallback": False,
            "failed_stage": "diagnostic_setup",
            "exception": _exception_record(exc),
            "stages": [],
        }
        atomic_write_report(args.report, report)
        print(json.dumps({"outcome": "fail", "failed_stage": "diagnostic_setup"}))
        return 1
    print(json.dumps({"outcome": report["outcome"], "report_written": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
