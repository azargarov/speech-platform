"""Exercise the production STT HTTP application with bounded CUDA requests."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from scripts.stt_cuda_diagnostic import (
    DiagnosticFailure,
    DiagnosticRunner,
    _report_mount_operation,
    atomic_write_report,
    check_installed_dependencies,
    load_configurations,
)

try:
    from stt_cuda_http_profile import validate_http_cuda_profile
except ModuleNotFoundError:
    from scripts.stt_cuda_http_profile import validate_http_cuda_profile
from scripts.stt_cuda_preflight import verify_approved_audio
from services.stt.artifacts import verify_artifact
from services.stt.domain import FailureCode
from services.stt.http_server import create_app
from services.stt.service import DeferredApplication
from services.worker.server import load_config as load_worker_config
from scripts.stt_resource_sampling import ResourceSampler

MAXIMUM_MEASUREMENT_REQUESTS = 1000


STAGES = (
    "report_mount_validation",
    "dependency_check",
    "configuration_parsing",
    "cuda_profile_validation",
    "artifact_validation",
    "http_worker_integration",
    "output_validation",
    "shutdown_validation",
)

_PUBLIC_ERROR_CODES = frozenset(code.value for code in FailureCode)
_AUDIO_FORMATS = {
    "audio/wav": (".wav", (".wav",)),
    "audio/flac": (".flac", (".flac",)),
    "audio/mpeg": (".mp3", (".mp3",)),
    "audio/ogg": (".ogg", (".ogg", ".opus")),
    "audio/mp4": (".m4a", (".m4a", ".mp4")),
}


@dataclass(frozen=True)
class MeasurementSettings:
    request_count: int
    maximum_request_count: int
    overall_deadline_seconds: float
    resource_sample_interval_seconds: float | None

    @classmethod
    def from_args(cls, args):
        request_count = getattr(args, "request_count", 1)
        maximum = getattr(args, "maximum_request_count", 1)
        deadline = getattr(args, "overall_deadline_seconds", 180.0)
        interval = getattr(args, "resource_sample_interval_seconds", None)
        if type(request_count) is not int or request_count < 1:
            raise ValueError("request count must be a positive integer")
        if type(maximum) is not int or maximum < 1:
            raise ValueError("maximum request count must be a positive integer")
        if request_count > maximum:
            raise ValueError("request count exceeds configured maximum")
        if maximum > MAXIMUM_MEASUREMENT_REQUESTS:
            raise ValueError("maximum request count exceeds report safety bound")
        if (
            type(deadline) not in (int, float)
            or not math.isfinite(deadline)
            or deadline <= 0
        ):
            raise ValueError("overall deadline must be a positive finite number")
        if interval is not None and (
            type(interval) not in (int, float)
            or not math.isfinite(interval)
            or interval < 0.1
            or interval > deadline
        ):
            raise ValueError("resource sample interval is outside configured bounds")
        return cls(request_count, maximum, float(deadline), interval)


class HTTPIntegrationFailure(RuntimeError):
    """Safe metadata for a non-success response from the test HTTP request."""

    def __init__(self, status: int, error_body: object, measurements=None):
        super().__init__("transcription HTTP request failed")
        self.http_status = (
            status if type(status) is int and 100 <= status <= 599 else None
        )
        self.request_stage = "transcription_response"
        self.public_error_code = None
        self.failure_category = "malformed_error_response"
        if isinstance(error_body, dict) and set(error_body) == {"code", "message"}:
            code = error_body.get("code")
            message = error_body.get("message")
            if (
                isinstance(code, str)
                and code in _PUBLIC_ERROR_CODES
                and isinstance(message, str)
            ):
                self.public_error_code = code
                self.failure_category = "application_error_response"
            elif isinstance(code, str) and code not in _PUBLIC_ERROR_CODES:
                self.failure_category = "unrecognized_error_code"
        self.safe_http_metadata = {
            "http_status": self.http_status,
            "public_error_code": self.public_error_code,
            "request_stage": self.request_stage,
            "failure_category": self.failure_category,
            "request_measurements": list(measurements or []),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _form(
    audio: bytes, audio_path: Path, alias: str, audio_media_type: str
) -> FormData:
    filename = _multipart_filename(audio_path, audio_media_type)
    form = FormData()
    form.add_field("audio", audio, filename=filename, content_type=audio_media_type)
    form.add_field("language", "auto")
    form.add_field("model", alias)
    form.add_field("timestamps", "true")
    form.add_field("stream", "false")
    return form


def _multipart_filename(audio_path: Path, audio_media_type: str) -> str:
    if audio_media_type not in _AUDIO_FORMATS:
        raise ValueError("configured audio media type is unsupported")
    canonical_suffix, accepted_suffixes = _AUDIO_FORMATS[audio_media_type]
    suffix = audio_path.suffix.lower()
    if suffix and suffix not in accepted_suffixes:
        raise ValueError("audio filename does not match configured media type")
    return audio_path.name if suffix else f"{audio_path.name}{canonical_suffix}"


def _shutdown_timeout_seconds(app) -> float:
    lifecycle = app.lifecycle
    # STT close drains admission, then allows bounded child exit, terminate and
    # kill/reap waits. This bounds TestClient cleanup from existing settings.
    return lifecycle.shutdown_drain_timeout_seconds + (
        3 * lifecycle.process_exit_timeout_seconds
    )


def _remaining_seconds(deadline: float, clock=time.monotonic) -> float:
    return max(0.0, deadline - clock())


async def _await_with_deadline(awaitable, deadline: float, clock=time.monotonic):
    remaining = _remaining_seconds(deadline, clock)
    if remaining <= 0:
        raise asyncio.TimeoutError
    return await asyncio.wait_for(awaitable, timeout=remaining)


async def _close_and_record(client, application, state, report_path, timeout_seconds):
    started = time.monotonic()
    status = "failed_or_timed_out"
    failure_category = "client_close_failed"
    close_completed = False
    child_exit_confirmed = None
    worker_not_ready = None
    try:
        await asyncio.wait_for(client.close(), timeout=timeout_seconds)
        close_completed = True
    except asyncio.TimeoutError:
        failure_category = "deadline_exceeded"
    except Exception:
        failure_category = "client_close_failed"
    else:
        try:
            delegate = application._delegate
            child_exit_confirmed = (
                delegate is not None and not delegate.runner.child_alive
            )
            worker_not_ready = not application.lifecycle.ready()
            status = (
                "completed_and_confirmed"
                if child_exit_confirmed and worker_not_ready
                else "attempted_but_unconfirmed"
            )
            failure_category = (
                None if status == "completed_and_confirmed" else "state_unconfirmed"
            )
        except Exception:
            status = "attempted_but_unconfirmed"
            failure_category = "state_unavailable"
    report = {
        "schema_version": 1,
        "status": status,
        "close_attempted": True,
        "close_completed": close_completed,
        "child_exit_confirmed": child_exit_confirmed,
        "worker_not_ready": worker_not_ready,
        "failure_category": failure_category,
        "duration_seconds": round(max(0.0, time.monotonic() - started), 6),
    }
    atomic_write_report(report_path, report)
    state["shutdown_evidence"] = report
    return report


def _validate_response(body: object, maximum_duration: float) -> dict:
    required = {"text", "language", "segments"}
    optional = {
        "transcription",
        "detected_language",
        "source_language",
        "output_language",
        "translated",
        "language_probability",
    }
    if (
        not isinstance(body, dict)
        or not required <= body.keys()
        or body.keys() - required - optional
    ):
        raise ValueError("transcription response schema is invalid")
    if not isinstance(body["text"], str) or not body["text"].strip():
        raise ValueError("transcription response text is invalid")
    language = body["language"]
    if not isinstance(language, str) or not re.fullmatch(r"[A-Za-z-]{2,16}", language):
        raise ValueError("transcription language metadata is invalid")
    for field in ("transcription",):
        if field in body and not isinstance(body[field], str):
            raise ValueError("transcription response text is invalid")
    for field in ("detected_language", "source_language", "output_language"):
        if field in body and (
            not isinstance(body[field], str)
            or not re.fullmatch(r"[a-z]{2}", body[field])
        ):
            raise ValueError("transcription language metadata is invalid")
    if "translated" in body and type(body["translated"]) is not bool:
        raise ValueError("translation status metadata is invalid")
    probability = body.get("language_probability")
    if probability is not None and (
        type(probability) not in (int, float)
        or not math.isfinite(probability)
        or not 0 <= probability <= 1
    ):
        raise ValueError("transcription language probability is invalid")
    segments = body["segments"]
    if not isinstance(segments, list) or not segments:
        raise ValueError("transcription segments are invalid")
    previous_end = 0.0
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) != {"start", "end", "text"}:
            raise ValueError("transcription segment schema is invalid")
        start, end = segment["start"], segment["end"]
        if (
            type(start) not in (int, float)
            or type(end) not in (int, float)
            or not math.isfinite(start)
            or not math.isfinite(end)
            or start < previous_end
            or end < start
            or end > maximum_duration
            or not isinstance(segment["text"], str)
        ):
            raise ValueError("transcription timestamps are invalid")
        previous_end = end
    return {
        "language": language,
        "segment_count": len(segments),
        "timestamp_bounds_valid": True,
    }


def _audio_duration_seconds(path: Path, av_module=None) -> float:
    """Read duration metadata only; audio bytes and decoder objects are not retained."""
    if av_module is None:
        import av as av_module
    with av_module.open(str(path), mode="r") as container:
        streams = [stream for stream in container.streams if stream.type == "audio"]
        if (
            streams
            and streams[0].duration is not None
            and streams[0].time_base is not None
        ):
            duration = float(streams[0].duration * streams[0].time_base)
        elif container.duration is not None:
            duration = float(container.duration / av_module.time_base)
        else:
            raise ValueError("audio duration metadata is unavailable")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("audio duration metadata is invalid")
    return duration


def _request_measurement(index, elapsed, audio_duration, response_metadata):
    duration = round(max(0.0, float(elapsed)), 6)
    audio_seconds = round(float(audio_duration), 6)
    return {
        "request_index": index,
        "phase": "first_request" if index == 1 else "subsequent_warm_request",
        "http_status": 200,
        "request_duration_seconds": duration,
        "transcription_duration_seconds": None,
        "transcription_duration_status": "not_exposed_by_worker_contract",
        "audio_duration_seconds": audio_seconds,
        "request_real_time_factor": round(duration / audio_seconds, 6),
        **response_metadata,
    }


def build_operations(args, loop, state, *, clock=time.monotonic):
    def dependency_check(_):
        lock = Path(args.lock)
        lock_sha256 = _sha256(lock)
        if lock_sha256 != args.approved_lock_sha256:
            raise ValueError("CUDA dependency lock differs from approved digest")
        return {
            "dependency_versions": check_installed_dependencies(lock),
            "lock_sha256": lock_sha256,
        }

    def parse_configuration(_):
        measurement = MeasurementSettings.from_args(args)
        app, deployment = load_configurations(
            args.application_config, args.deployment_config
        )
        worker = load_worker_config(args.worker_config, "stt")
        state.update(
            app=app,
            deployment=deployment,
            worker=worker,
            measurement=measurement,
        )
        return {
            "application_device_mode": app.device_mode,
            "model_alias": app.default_model,
            "cuda_device_index": deployment.cuda_device_index,
            "minimum_free_gpu_bytes_before_load": deployment.minimum_free_gpu_bytes_before_load,
        }

    def cuda_profile(_):
        app = state["app"]
        profile = validate_http_cuda_profile(
            app,
            state["deployment"],
            args.model_revision,
            args.model_manifest_sha256,
        )
        compute_type = profile["compute_type"]
        state["compute_type"] = compute_type
        return {**profile, "compute_type": compute_type}

    def artifact_validation(_):
        app = state["app"]
        model = next(item for item in app.models if item.alias == app.default_model)
        location = state["deployment"].artifact_roots[model.artifact_ref]
        artifact = verify_artifact(model, location)
        audio_path = Path(args.audio)
        # Validate the explicit fixture format before starting the HTTP worker
        # or touching the inference child. Mount paths can be extensionless.
        _multipart_filename(audio_path, args.audio_media_type)
        audio_digest = verify_approved_audio(audio_path, args.audio_checksum_file)
        if audio_path.stat().st_size > app.admission.max_request_bytes:
            raise ValueError("audio exceeds configured request limit")
        state.update(
            model_config=model,
            artifact=artifact,
            audio_path=audio_path,
            audio_sha256=audio_digest,
            audio_duration_seconds=_audio_duration_seconds(audio_path),
        )
        return {
            "model_alias": model.alias,
            "model_revision": model.identity.upstream_revision,
            "manifest_sha256": model.manifest_sha256,
            "audio_sha256": audio_digest,
            "audio_duration_seconds": state["audio_duration_seconds"],
        }

    async def exercise_http():
        app = state["app"]
        measurement = state["measurement"]
        application = DeferredApplication(app, state["deployment"])
        client = TestClient(TestServer(create_app(application)))
        overall_deadline = state["experiment_deadline"]
        shutdown_budget = _shutdown_timeout_seconds(app)
        work_deadline = overall_deadline - (2 * shutdown_budget)
        result = None
        sampler = None
        if measurement.resource_sample_interval_seconds is not None:
            sampler = ResourceSampler(
                measurement.resource_sample_interval_seconds,
                state["deployment"].cuda_device_index,
                maximum_samples=math.ceil(
                    measurement.overall_deadline_seconds
                    / measurement.resource_sample_interval_seconds
                )
                + 1,
            )
        request_measurements = []
        try:
            if sampler is not None:
                sampler.start()
            worker_started = clock()
            await _await_with_deadline(client.start_server(), work_deadline, clock)
            health = await _await_with_deadline(
                client.get("/healthz"), work_deadline, clock
            )
            if health.status != 200 or (await health.json()).get("status") != "alive":
                raise RuntimeError("worker health check failed")
            initial_ready = await _await_with_deadline(
                client.get("/readyz"), work_deadline, clock
            )
            initial_ready_status = initial_ready.status
            if initial_ready_status not in {200, 503}:
                raise RuntimeError("worker readiness response is invalid")
            model_load_deadline = min(
                worker_started + app.lifecycle.model_load_timeout_seconds,
                work_deadline,
            )
            while True:
                ready = await _await_with_deadline(
                    client.get("/readyz"), model_load_deadline, clock
                )
                if ready.status == 200:
                    break
                if ready.status != 503 or clock() >= model_load_deadline:
                    raise RuntimeError(
                        "worker did not become ready within configured limit"
                    )
                await _await_with_deadline(
                    asyncio.sleep(state["worker"]["poll_interval_seconds"]),
                    model_load_deadline,
                    clock,
                )
            load_seconds = clock() - worker_started

            audio_bytes = state["audio_path"].read_bytes()
            if len(audio_bytes) > app.admission.max_request_bytes:
                raise ValueError("audio exceeds configured request limit")
            for request_index in range(1, measurement.request_count + 1):
                request_deadline = min(
                    work_deadline,
                    clock() + app.admission.request_timeout_seconds,
                )
                request_started = clock()
                response = await _await_with_deadline(
                    client.post(
                        "/internal/v1/transcriptions",
                        data=_form(
                            audio_bytes,
                            state["audio_path"],
                            app.default_model,
                            args.audio_media_type,
                        ),
                        headers={
                            "X-Request-Timeout-Ms": str(
                                int(app.admission.request_timeout_seconds * 1000)
                            )
                        },
                    ),
                    request_deadline,
                    clock,
                )
                elapsed = clock() - request_started
                if clock() >= work_deadline:
                    raise asyncio.TimeoutError("overall diagnostic deadline exceeded")
                state["response_status"] = response.status
                if response.status != 200:
                    try:
                        error = await _await_with_deadline(
                            response.json(), work_deadline, clock
                        )
                    except asyncio.TimeoutError:
                        raise
                    except Exception:
                        error = None
                    raise HTTPIntegrationFailure(
                        response.status, error, request_measurements
                    )
                try:
                    body = await _await_with_deadline(
                        response.json(), work_deadline, clock
                    )
                    if clock() >= work_deadline:
                        raise asyncio.TimeoutError(
                            "overall diagnostic deadline exceeded"
                        )
                    response_metadata = _validate_response(
                        body, app.audio_limits.max_duration_seconds
                    )
                except asyncio.TimeoutError:
                    raise
                except Exception:
                    raise HTTPIntegrationFailure(
                        response.status, None, request_measurements
                    ) from None
                # The full response was consumed and validated before the next
                # request. Do not retain transcript or segment text.
                request_measurements.append(
                    _request_measurement(
                        request_index,
                        elapsed,
                        state["audio_duration_seconds"],
                        response_metadata,
                    )
                )
                del body
            state["request_measurements"] = request_measurements
            state["http_metadata"] = {
                "health_status": health.status,
                "initial_ready_status": initial_ready_status,
                "ready_status": ready.status,
                "process_cold_model_load_seconds": round(load_seconds, 6),
                "model_load_seconds": round(load_seconds, 6),
                "request_count": len(request_measurements),
                "transcription_seconds": request_measurements[0][
                    "request_duration_seconds"
                ],
                "legacy_transcription_seconds_semantics": "first_request_http_duration",
            }
            result = {"request_status": 200}
        finally:
            active_error = sys.exc_info()[1]
            try:
                await _close_and_record(
                    client,
                    application,
                    state,
                    Path(args.report).with_name("shutdown-report.json"),
                    _remaining_seconds(overall_deadline, clock),
                )
            finally:
                if sampler is not None:
                    state["resource_observations"] = sampler.stop(
                        _remaining_seconds(overall_deadline, clock)
                    )
                if active_error is not None and sampler is not None:
                    try:
                        active_error.safe_resource_observations = state.get(
                            "resource_observations"
                        )
                    except Exception:
                        pass
        if state.get("request_measurements"):
            state["request_measurements"][0]["process_cold_model_load_seconds"] = round(
                load_seconds, 6
            )
        state["measurement_settings"] = measurement
        if result is None:
            raise RuntimeError("HTTP integration ended without a result")
        return result

    def http_integration(_):
        return loop.run_until_complete(exercise_http())

    def output_validation(_):
        if clock() >= state["experiment_deadline"]:
            raise asyncio.TimeoutError("overall diagnostic deadline exceeded")
        measurements = state.get("request_measurements", [])
        if len(measurements) != state["measurement"].request_count:
            raise ValueError("experiment did not complete the configured request count")
        first = measurements[0]
        return {
            "language": first["language"],
            "segment_count": first["segment_count"],
            "timestamp_bounds_valid": all(
                item["timestamp_bounds_valid"] for item in measurements
            ),
            "audio_duration_seconds": state["audio_duration_seconds"],
            "request_measurements": measurements,
            "resource_observations": state.get("resource_observations"),
            **state["http_metadata"],
            "device": "cuda",
            "compute_type": state["compute_type"],
            "dependency_versions": _["dependency_check"]["dependency_versions"],
            "lock_sha256": _["dependency_check"]["lock_sha256"],
            "manifest_sha256": state["model_config"].manifest_sha256,
            "model_alias": state["model_config"].alias,
            "model_revision": state["model_config"].identity.upstream_revision,
            "audio_sha256": state["audio_sha256"],
        }

    def shutdown_validation(_):
        if clock() >= state["experiment_deadline"]:
            raise asyncio.TimeoutError("overall diagnostic deadline exceeded")
        shutdown = state.get("shutdown_evidence", {})
        if shutdown.get("status") != "completed_and_confirmed":
            raise RuntimeError("worker shutdown was not confirmed")
        return {
            "shutdown_status": shutdown["status"],
            "child_exit_confirmed": shutdown["child_exit_confirmed"],
            "worker_not_ready": shutdown["worker_not_ready"],
        }

    state["experiment_started_at"] = clock()
    try:
        state["measurement"] = MeasurementSettings.from_args(args)
    except ValueError:
        # Preserve diagnostic-stage attribution when command settings are invalid.
        state["measurement"] = None
    raw_deadline = getattr(args, "overall_deadline_seconds", 180.0)
    if (
        type(raw_deadline) not in (int, float)
        or not math.isfinite(raw_deadline)
        or raw_deadline <= 0
    ):
        raw_deadline = 180.0
    state["experiment_deadline"] = state["experiment_started_at"] + float(raw_deadline)
    return {
        "report_mount_validation": _report_mount_operation(args.report),
        "dependency_check": dependency_check,
        "configuration_parsing": parse_configuration,
        "cuda_profile_validation": cuda_profile,
        "artifact_validation": artifact_validation,
        "http_worker_integration": http_integration,
        "output_validation": output_validation,
        "shutdown_validation": shutdown_validation,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-config", required=True)
    parser.add_argument("--deployment-config", required=True)
    parser.add_argument("--worker-config", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument(
        "--audio-media-type", required=True, choices=tuple(_AUDIO_FORMATS)
    )
    parser.add_argument("--audio-checksum-file", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--model-manifest-sha256", required=True)
    parser.add_argument("--lock", required=True)
    parser.add_argument("--approved-lock-sha256", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--request-count", type=int, default=1)
    parser.add_argument("--maximum-request-count", type=int, default=1)
    parser.add_argument("--overall-deadline-seconds", type=float, default=180.0)
    parser.add_argument(
        "--resource-sample-interval-seconds",
        type=lambda value: None if value == "disabled" else float(value),
    )
    args = parser.parse_args(argv)

    loop = asyncio.new_event_loop()
    state = {}
    runner = DiagnosticRunner(args.report, stages=STAGES, cuda_requested=True)
    try:
        runner.run(build_operations(args, loop, state), metadata={"mode": "cuda_http"})
    except DiagnosticFailure as exc:
        print(
            json.dumps({"outcome": "fail", "failed_stage": exc.stage}, sort_keys=True)
        )
        return 1
    finally:
        loop.close()
    print(json.dumps({"outcome": "pass", "report_written": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
