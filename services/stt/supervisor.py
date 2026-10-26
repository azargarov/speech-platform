"""Small persistent child-process runner for one loaded model."""

from __future__ import annotations

import base64
import json
import math
import multiprocessing
import threading
import time
import uuid

from services.stt.domain import (
    FailureCode,
    FatalBackendFailure,
    ModelIdentity,
    ModelMetadata,
    ModelSelection,
    OperationContext,
    Segment,
    SpeechFailure,
    TranscriptionRequest,
    TranscriptionResult,
)


class ProcessControl:
    """Narrow OS process seam used for bounded termination and deterministic tests."""

    @staticmethod
    def is_alive(process):
        return process.is_alive()

    @staticmethod
    def terminate(process):
        process.terminate()

    @staticmethod
    def kill(process):
        process.kill()

    @staticmethod
    def join(process, timeout):
        process.join(timeout)


class IPCProtocolError(Exception):
    pass


class InferenceSupervisor:
    def __init__(
        self,
        backend_factory,
        selection: ModelSelection,
        artifact,
        device,
        capabilities,
        cooperative_grace_seconds: float,
        process_exit_timeout_seconds: float,
        max_message_bytes: int,
        model_load_timeout_seconds: float,
        *,
        process_control=None,
        response_reader=None,
        response_poller=None,
        cleanup_event=None,
    ):
        self._factory = backend_factory
        self._selection = selection
        self._artifact = artifact
        self._device = device
        self._capabilities = capabilities
        # Retained in the constructor/config contract for compatibility. Active
        # inference is never terminated by this setting; its response must be
        # consumed before the serialized IPC channel can serve another request.
        self._exit_timeout = process_exit_timeout_seconds
        self._max_message_bytes = max_message_bytes
        self._load_timeout = model_load_timeout_seconds
        self._process_control = process_control or ProcessControl()
        self._response_reader = response_reader or _read_pipe
        self._response_poller = response_poller or _poll_pipe
        self._lock = threading.RLock()
        self._ctx = multiprocessing.get_context("spawn")
        self._process = None
        self._exit_logged = False
        self._request_pipe = None
        self._response_pipe = None
        self._cancel_event = None
        self._started = False
        self._closed = False
        self._faulted = False
        self._cleanup_unconfirmed = False
        self._monitor_started = False
        self.cleanup_event = cleanup_event or threading.Event()
        self.cleanup_event.set()
        self.metadata: ModelMetadata | None = None

    @property
    def faulted(self):
        return self._faulted

    @property
    def cleanup_unconfirmed(self):
        return self._cleanup_unconfirmed

    @property
    def child_alive(self):
        return self._process is not None and self._is_alive(self._process)

    def start(self) -> ModelMetadata:
        with self._lock:
            if self._started or self._closed:
                raise RuntimeError(
                    "inference supervisor cannot be started in this state"
                )
            response_receive, child_response_send = self._ctx.Pipe(duplex=False)
            child_request_receive, request_send = self._ctx.Pipe(duplex=False)
            cancel_event = self._ctx.Event()
            startup_deadline = time.monotonic() + self._load_timeout
            process = self._ctx.Process(
                target=_child_main,
                args=(
                    self._factory,
                    self._selection,
                    self._artifact,
                    self._device,
                    self._capabilities,
                    child_request_receive,
                    child_response_send,
                    cancel_event,
                    startup_deadline,
                    self._max_message_bytes,
                ),
                daemon=False,
            )
            self._process = process
            self._request_pipe = request_send
            self._response_pipe = response_receive
            self._cancel_event = cancel_event
            self.cleanup_event.clear()
            try:
                process.start()
            except Exception as exc:
                self._faulted = True
                self._closed = True
                self._process = None
                self._close_pipes()
                self.cleanup_event.set()
                raise SpeechFailure(FailureCode.MODEL_LOAD_FAILED, str(exc)) from exc
            self._started = True
            child_response_send.close()
            child_request_receive.close()

        try:
            startup_response_available = self._poll_response(self._load_timeout)
        except IPCProtocolError as exc:
            confirmed = self._fatal_child_fault(exc)
            raise SpeechFailure(
                FailureCode.MODEL_LOAD_FAILED,
                "inference worker communication failed",
                retain_resources=not confirmed,
            ) from exc
        if not startup_response_available:
            confirmed = self._force_reap()
            self._faulted = True
            raise SpeechFailure(
                FailureCode.MODEL_LOAD_FAILED,
                "model load timed out",
                retain_resources=not confirmed,
            )
        try:
            response = self._read_response()
            self._validate_ready(response)
        except (IPCProtocolError, OSError, EOFError) as exc:
            confirmed = self._fatal_child_fault(exc)
            raise SpeechFailure(
                FailureCode.MODEL_LOAD_FAILED,
                "invalid model worker response",
                retain_resources=not confirmed,
            ) from exc
        if response["type"] != "ready":
            confirmed = self._force_reap()
            self._faulted = True
            raise SpeechFailure(
                FailureCode.MODEL_LOAD_FAILED,
                "model load failed",
                retain_resources=not confirmed,
            )
        identity_data = response["model_identity"]
        self.metadata = ModelMetadata(
            ModelIdentity(identity_data["family"], identity_data["upstream_revision"]),
            frozenset(response["languages"]),
            response["automatic_language_detection"],
            response["segment_timestamps"],
        )
        return self.metadata

    def transcribe(self, request: TranscriptionRequest, context: OperationContext):
        with self._lock:
            if not self._started or self._closed or self._faulted:
                raise SpeechFailure(
                    FailureCode.NOT_READY, "inference worker is unavailable"
                )
            if not self._is_alive(self._process):
                self._faulted = True
                self._confirm_exit()
                raise SpeechFailure(FailureCode.NOT_READY, "inference worker failed")
            encoded_audio = base64.b64encode(request.audio).decode("ascii")
            message = {
                "type": "transcribe",
                "id": uuid.uuid4().hex,
                "audio": encoded_audio,
                "media_type": request.media_type,
                "language": request.language,
                "output_language": request.output_language,
                "timestamps": request.timestamps,
                "deadline": context.deadline,
            }
            if context.request_id:
                message["request_id"] = context.request_id
            payload = _encode(message, self._max_message_bytes)
            self._cancel_event.clear()
            try:
                self._request_pipe.send_bytes(payload)
            except (BrokenPipeError, EOFError, OSError) as exc:
                confirmed = self._fatal_child_fault(exc)
                raise SpeechFailure(
                    FailureCode.NOT_READY,
                    "inference worker communication failed",
                    retain_resources=not confirmed,
                ) from exc

            while True:
                try:
                    response_available = self._poll_response(0.02)
                    if response_available:
                        response = self._read_response()
                        self._validate_response(response)
                except IPCProtocolError as exc:
                    confirmed = self._fatal_child_fault(exc)
                    raise SpeechFailure(
                        FailureCode.NOT_READY,
                        "inference worker communication failed",
                        retain_resources=not confirmed,
                    ) from exc
                if response_available:
                    break
                if not self._is_alive(self._process):
                    self._faulted = True
                    self._confirm_exit()
                    raise SpeechFailure(
                        FailureCode.NOT_READY, "inference worker failed"
                    )
                if context.cancelled():
                    # Signal cooperative checkpoints, but keep the healthy child
                    # alive until its response is consumed. Native inference may
                    # not observe this event until the native call has returned.
                    self._cancel_event.set()

            if response["type"] == "failure":
                code = FailureCode(response["code"])
                if response.get("fatal", False):
                    confirmed = self._fatal_child_fault("fatal backend failure")
                    if context.cancelled():
                        raise self._cancel_failure(
                            context, retain_resources=not confirmed
                        )
                    raise SpeechFailure(
                        code,
                        response.get("diagnostic"),
                        retain_resources=not confirmed,
                    )
                if context.cancelled():
                    raise self._cancel_failure(context)
                raise SpeechFailure(code, response.get("diagnostic"))
            if context.cancelled():
                raise self._cancel_failure(context)
            return TranscriptionResult(
                response["text"],
                response["language"],
                tuple(
                    Segment(item["start_seconds"], item["end_seconds"], item["text"])
                    for item in response["segments"]
                )
                if response["segments"] is not None
                else None,
                response["transcription"],
                response["language_probability"],
                response["output_language"],
                response["translated"],
            )

    def shutdown(self, timeout_seconds: float):
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        acquired = self._lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
        if not acquired:
            # The inference owner still holds the IPC channel. Do not race it;
            # retain the child and surface that its cleanup is unconfirmed.
            self._faulted = True
            self._cleanup_unconfirmed = True
            self.cleanup_event.clear()
            return False
        try:
            if self._closed and not self._cleanup_unconfirmed:
                return True
            was_closed = self._closed
            self._closed = True
            if not self._started:
                self.cleanup_event.set()
                return True
            if not was_closed and self._is_alive(self._process) and not self._faulted:
                try:
                    self._request_pipe.send_bytes(
                        _encode({"type": "shutdown"}, self._max_message_bytes)
                    )
                except (BrokenPipeError, EOFError, OSError):
                    self._faulted = True
            process = self._process
        finally:
            self._lock.release()
        stopped_confirmed = False
        if self._is_alive(process) and not self._faulted:
            wait = min(max(0.0, deadline - time.monotonic()), self._exit_timeout)
            try:
                if self._poll_response(wait):
                    response = self._read_response()
                    if response != {"type": "stopped"}:
                        self._faulted = True
                    else:
                        stopped_confirmed = True
            except IPCProtocolError:
                self._faulted = True
        if stopped_confirmed and self._is_alive(process):
            self._join_bounded(process, max(0.0, deadline - time.monotonic()))
        if self._is_alive(process):
            self._faulted = True
            self._force_reap(deadline=deadline)
        else:
            self._confirm_exit()
        return not self._is_alive(process) and not self._cleanup_unconfirmed

    def _cancel_failure(self, context, *, retain_resources=False):
        if context.deadline is not None and time.monotonic() >= context.deadline:
            return SpeechFailure(
                FailureCode.DEADLINE_EXCEEDED,
                "request deadline exceeded",
                retain_resources=retain_resources,
            )
        return SpeechFailure(
            FailureCode.CANCELLED,
            "request was cancelled",
            retain_resources=retain_resources,
        )

    def _read_response(self):
        try:
            payload = self._response_reader(
                self._response_pipe, self._max_message_bytes
            )
            if not isinstance(payload, bytes) or len(payload) > self._max_message_bytes:
                raise IPCProtocolError("child response exceeds the frame limit")
            response = json.loads(payload)
        except IPCProtocolError:
            raise
        except (EOFError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise IPCProtocolError("child response frame is unreadable") from exc
        if not isinstance(response, dict):
            raise IPCProtocolError("child response must be an object")
        return response

    def _poll_response(self, timeout):
        try:
            return self._response_poller(self._response_pipe, timeout)
        except (EOFError, OSError) as exc:
            raise IPCProtocolError("child response channel cannot be polled") from exc

    def _validate_ready(self, response):
        if response.get("type") != "ready":
            return
        required = {
            "type",
            "model_identity",
            "languages",
            "automatic_language_detection",
            "segment_timestamps",
        }
        if (
            set(response) != required
            or not self._valid_identity(response["model_identity"])
            or not isinstance(response["languages"], list)
            or any(
                not isinstance(item, str) or not item for item in response["languages"]
            )
            or type(response["automatic_language_detection"]) is not bool
            or type(response["segment_timestamps"]) is not bool
        ):
            raise IPCProtocolError("invalid ready response")

    def _validate_response(self, response):
        kind = response.get("type")
        if kind == "failure":
            if (
                set(response) - {"type", "code", "diagnostic", "fatal"}
                or not isinstance(response.get("code"), str)
                or response["code"] not in FailureCode._value2member_map_
                or (
                    "diagnostic" in response
                    and not isinstance(response["diagnostic"], str)
                )
                or ("fatal" in response and type(response["fatal"]) is not bool)
            ):
                raise IPCProtocolError("invalid failure response")
            return
        if kind != "result" or set(response) != {
            "type",
            "text",
            "language",
            "segments",
            "transcription",
            "language_probability",
            "output_language",
            "translated",
        }:
            raise IPCProtocolError("invalid result response")
        if (
            not isinstance(response["text"], str)
            or not isinstance(response["language"], str)
            or not response["language"]
            or not isinstance(response["transcription"], str)
            or (
                response["language_probability"] is not None
                and (
                    type(response["language_probability"]) not in (int, float)
                    or not _finite_number(response["language_probability"])
                    or not 0 <= response["language_probability"] <= 1
                )
            )
            or not isinstance(response["output_language"], str)
            or type(response["translated"]) is not bool
        ):
            raise IPCProtocolError("invalid result fields")
        segments = response["segments"]
        if segments is not None:
            if not isinstance(segments, list):
                raise IPCProtocolError("invalid result segments")
            for segment in segments:
                if (
                    not isinstance(segment, dict)
                    or set(segment) != {"start_seconds", "end_seconds", "text"}
                    or type(segment["start_seconds"]) not in (int, float)
                    or type(segment["end_seconds"]) not in (int, float)
                    or not _finite_number(segment["start_seconds"])
                    or not _finite_number(segment["end_seconds"])
                    or segment["start_seconds"] < 0
                    or segment["end_seconds"] < segment["start_seconds"]
                    or not isinstance(segment["text"], str)
                ):
                    raise IPCProtocolError("invalid result segment")

    @staticmethod
    def _valid_identity(value):
        return (
            isinstance(value, dict)
            and set(value) == {"family", "upstream_revision"}
            and all(isinstance(item, str) and item for item in value.values())
        )

    def _fatal_child_fault(self, _diagnostic):
        self._faulted = True
        return self._force_reap()

    def _force_reap(self, deadline=None):
        with self._lock:
            process = self._process
            if process is None:
                self.cleanup_event.set()
                self._cleanup_unconfirmed = False
                return True
            if not self._is_alive(process):
                self._confirm_exit()
                return True
            try:
                self._process_control.terminate(process)
            except (OSError, ProcessLookupError):
                pass
            first_wait = self._exit_timeout
            if deadline is not None:
                first_wait = min(first_wait, max(0.0, deadline - time.monotonic()))
            self._join_bounded(process, first_wait)
            if self._is_alive(process):
                try:
                    self._process_control.kill(process)
                except (OSError, ProcessLookupError):
                    pass
                second_wait = self._exit_timeout
                if deadline is not None:
                    second_wait = min(
                        second_wait, max(0.0, deadline - time.monotonic())
                    )
                self._join_bounded(process, second_wait)
            if self._is_alive(process):
                self._cleanup_unconfirmed = True
                self.cleanup_event.clear()
                self._start_cleanup_monitor()
                return False
            self._confirm_exit()
            return True

    def _is_alive(self, process):
        try:
            return self._process_control.is_alive(process)
        except (OSError, AssertionError):
            # An OS/process-control error is uncertainty, never proof of exit.
            return True

    def _join_bounded(self, process, timeout):
        try:
            self._process_control.join(process, timeout)
        except (OSError, AssertionError):
            pass

    def _start_cleanup_monitor(self):
        if self._monitor_started:
            return
        self._monitor_started = True

        def monitor():
            process = self._process
            while self._is_alive(process):
                self._join_bounded(process, 0.1)
            with self._lock:
                self._confirm_exit()

        thread = threading.Thread(target=monitor, name="stt-child-reaper", daemon=True)
        thread.start()

    def _confirm_exit(self):
        process = self._process
        if process is not None:
            self._join_bounded(process, 0)
            if process.exitcode is not None:
                if not self._exit_logged:
                    _emit_child_exit(process)
                    self._exit_logged = True
        self._cleanup_unconfirmed = False
        self._close_pipes()
        self.cleanup_event.set()

    def _close_pipes(self):
        for pipe in (self._request_pipe, self._response_pipe):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass


def _read_pipe(pipe, maximum):
    return pipe.recv_bytes(maximum)


def _poll_pipe(pipe, timeout):
    return pipe.poll(timeout)


def _finite_number(value):
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _encode(message, maximum):
    payload = json.dumps(message, separators=(",", ":")).encode()
    if len(payload) > maximum:
        raise SpeechFailure(
            FailureCode.INPUT_LIMIT, "request exceeds IPC message limit"
        )
    return payload


def _child_main(
    factory,
    selection,
    artifact,
    device,
    capabilities,
    receive,
    send,
    cancel_event,
    startup_deadline,
    max_bytes,
):
    model = None
    try:
        backend = factory()
        context = OperationContext(startup_deadline)
        model = backend.load(selection, artifact, device, context)
        metadata = model.metadata
        send.send_bytes(
            _encode(
                {
                    "type": "ready",
                    "model_identity": {
                        "family": metadata.identity.family,
                        "upstream_revision": metadata.identity.upstream_revision,
                    },
                    "languages": sorted(metadata.languages),
                    "automatic_language_detection": metadata.automatic_language_detection
                    and capabilities.automatic_language_detection,
                    "segment_timestamps": metadata.segment_timestamps
                    and capabilities.segment_timestamps,
                },
                max_bytes,
            )
        )
        while True:
            try:
                message = json.loads(receive.recv_bytes(max_bytes))
            except EOFError:
                break
            if message.get("type") == "shutdown":
                model.unload(OperationContext())
                send.send_bytes(_encode({"type": "stopped"}, max_bytes))
                break
            if message.get("type") != "transcribe":
                send.send_bytes(
                    _encode(
                        {
                            "type": "failure",
                            "code": "backend_failed",
                            "diagnostic": "invalid worker message",
                        },
                        max_bytes,
                    )
                )
                continue
            try:
                request = TranscriptionRequest(
                    base64.b64decode(message["audio"], validate=True),
                    message["media_type"],
                    selection.alias,
                    message["language"],
                    message["timestamps"],
                    message["output_language"],
                )
                result = model.transcribe(
                    request,
                    OperationContext(
                        message["deadline"],
                        cancel_event,
                        message.get("request_id"),
                    ),
                )
                response = {
                    "type": "result",
                    "text": result.text,
                    "language": result.language,
                    "transcription": result.transcription
                    if result.transcription is not None
                    else result.text,
                    "language_probability": result.language_probability,
                    "output_language": result.output_language or result.language,
                    "translated": result.translated,
                    "segments": [
                        {
                            "start_seconds": segment.start_seconds,
                            "end_seconds": segment.end_seconds,
                            "text": segment.text,
                        }
                        for segment in result.segments
                    ]
                    if result.segments is not None
                    else None,
                }
            except SpeechFailure as exc:
                _emit_event(
                    "inference_failure",
                    code=exc.code.value,
                    fatal=isinstance(exc, FatalBackendFailure),
                    **(
                        {"request_id": message["request_id"]}
                        if message.get("request_id")
                        else {}
                    ),
                )
                response = {
                    "type": "failure",
                    "code": exc.code.value,
                    "diagnostic": exc.diagnostic,
                    "fatal": isinstance(exc, FatalBackendFailure),
                }
            except Exception as exc:
                _emit_event(
                    "inference_failure",
                    code="backend_failed",
                    fatal=False,
                    exception_type=type(exc).__name__,
                    **(
                        {"request_id": message["request_id"]}
                        if message.get("request_id")
                        else {}
                    ),
                )
                response = {
                    "type": "failure",
                    "code": "backend_failed",
                    "diagnostic": str(exc),
                }
            send.send_bytes(_encode(response, max_bytes))
    except Exception as exc:
        _emit_event(
            "inference_worker_startup_failure",
            exception_type=type(exc).__name__,
        )
        try:
            send.send_bytes(
                _encode(
                    {
                        "type": "failure",
                        "code": "model_load_failed",
                        "diagnostic": "model load failed",
                    },
                    max_bytes,
                )
            )
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        receive.close()
        send.close()


def _emit_child_exit(process):
    _emit_event("inference_worker_exited", exitcode=process.exitcode)


def _emit_event(event, **fields):
    # Diagnostics are fixed classifications and metadata; never emit exception text,
    # audio, transcripts, paths or credentials.
    print(json.dumps({"event": event, **fields}, separators=(",", ":")), flush=True)
