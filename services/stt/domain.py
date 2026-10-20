"""Provider-neutral STT domain types and ports."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class FailureCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_OPTION = "unsupported_option"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    UNKNOWN_MODEL = "unknown_model"
    INPUT_LIMIT = "input_limit"
    DECODE_FAILED = "decode_failed"
    LANGUAGE_UNDETECTED = "language_undetected"
    UNSUPPORTED_DETECTED_LANGUAGE = "unsupported_detected_language"
    UNSUPPORTED_TRANSLATION = "unsupported_translation"
    OVERLOADED = "overloaded"
    NOT_READY = "not_ready"
    CANCELLED = "cancelled"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    DEVICE_UNAVAILABLE = "device_unavailable"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    MODEL_LOAD_FAILED = "model_load_failed"
    BACKEND_FAILED = "backend_failed"


class SpeechFailure(Exception):
    def __init__(
        self,
        code: FailureCode,
        diagnostic: str | None = None,
        *,
        retain_resources=False,
    ):
        super().__init__(public_message(code))
        self.code = code
        self.safe_message = public_message(code)
        self.diagnostic = diagnostic
        self.retain_resources = retain_resources


class FatalBackendFailure(SpeechFailure):
    """Backend failure requiring the supervised child to be fault-latched."""


_PUBLIC_MESSAGES = {
    FailureCode.INVALID_INPUT: "request is invalid",
    FailureCode.UNSUPPORTED_OPTION: "requested option is unsupported",
    FailureCode.UNSUPPORTED_MEDIA_TYPE: "unsupported audio media type",
    FailureCode.UNKNOWN_MODEL: "unknown model alias",
    FailureCode.INPUT_LIMIT: "request exceeds the configured limit",
    FailureCode.DECODE_FAILED: "audio could not be decoded",
    FailureCode.LANGUAGE_UNDETECTED: "language could not be detected",
    FailureCode.UNSUPPORTED_DETECTED_LANGUAGE: "detected language is not supported",
    FailureCode.UNSUPPORTED_TRANSLATION: "requested translation is unavailable",
    FailureCode.OVERLOADED: "service capacity is full",
    FailureCode.NOT_READY: "service is not ready",
    FailureCode.CANCELLED: "request was cancelled",
    FailureCode.DEADLINE_EXCEEDED: "request deadline was exceeded",
    FailureCode.DEVICE_UNAVAILABLE: "configured device is unavailable",
    FailureCode.RESOURCE_EXHAUSTED: "service resource limit was exceeded",
    FailureCode.MODEL_LOAD_FAILED: "model could not be loaded",
    FailureCode.BACKEND_FAILED: "inference failed",
}


def public_message(code: FailureCode) -> str:
    return _PUBLIC_MESSAGES[code]


@dataclass(frozen=True)
class ErrorResponse:
    code: str
    message: str


def safe_error(failure: SpeechFailure) -> tuple[int, ErrorResponse]:
    status = {
        FailureCode.INVALID_INPUT: 400,
        FailureCode.UNSUPPORTED_OPTION: 400,
        FailureCode.UNSUPPORTED_MEDIA_TYPE: 415,
        FailureCode.UNKNOWN_MODEL: 404,
        FailureCode.INPUT_LIMIT: 413,
        FailureCode.DECODE_FAILED: 422,
        FailureCode.LANGUAGE_UNDETECTED: 422,
        FailureCode.UNSUPPORTED_DETECTED_LANGUAGE: 422,
        FailureCode.UNSUPPORTED_TRANSLATION: 400,
        FailureCode.OVERLOADED: 429,
        FailureCode.NOT_READY: 503,
        FailureCode.CANCELLED: 504,
        FailureCode.DEADLINE_EXCEEDED: 504,
        FailureCode.DEVICE_UNAVAILABLE: 503,
        FailureCode.RESOURCE_EXHAUSTED: 503,
        FailureCode.MODEL_LOAD_FAILED: 503,
        FailureCode.BACKEND_FAILED: 500,
    }[failure.code]
    return status, ErrorResponse(failure.code.value, public_message(failure.code))


@dataclass(frozen=True)
class TranscriptionRequest:
    audio: bytes | bytearray
    media_type: str
    model_alias: str | None = None
    language: str | None = None
    timestamps: bool = False
    output_language: str = "auto"


@dataclass(frozen=True)
class Segment:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str
    segments: tuple[Segment, ...] | None = None
    transcription: str | None = None
    language_probability: float | None = None
    output_language: str | None = None
    translated: bool = False


@dataclass(frozen=True)
class ModelIdentity:
    family: str
    upstream_revision: str


@dataclass(frozen=True)
class ArtifactIdentity:
    manifest_sha256: str
    format: str


@dataclass(frozen=True)
class VerifiedArtifact:
    identity: ArtifactIdentity
    root: Path


@dataclass(frozen=True)
class ModelSelection:
    alias: str
    identity: ModelIdentity
    artifact_ref: str
    artifact_identity: ArtifactIdentity


@dataclass(frozen=True)
class ModelMetadata:
    identity: ModelIdentity
    languages: frozenset[str]
    automatic_language_detection: bool
    segment_timestamps: bool


@dataclass(frozen=True)
class BackendCapabilities:
    device_kinds: frozenset[str]
    automatic_language_detection: bool
    segment_timestamps: bool
    streaming: bool = False


@dataclass(frozen=True)
class DeviceCapabilities:
    kind: str
    handle: str
    features: frozenset[str] = frozenset()
    total_memory_bytes: int | None = None
    free_memory_bytes: int | None = None


@dataclass(frozen=True)
class DeviceRequirements:
    allowed_kinds: frozenset[str]
    required_features: frozenset[str] = frozenset()
    estimated_peak_memory_bytes: int | None = None
    required_features_by_kind: tuple[tuple[str, frozenset[str]], ...] = ()


class OperationContext:
    """Monotonic deadline and cancellation signal passed across application ports."""

    def __init__(self, deadline: float | None = None, cancel_event=None):
        self.deadline = deadline
        self._cancelled = (
            cancel_event if cancel_event is not None else threading.Event()
        )

    def cancel(self) -> None:
        self._cancelled.set()

    def cancelled(self) -> bool:
        return self._cancelled.is_set() or (
            self.deadline is not None and time.monotonic() >= self.deadline
        )

    def check(self) -> None:
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise SpeechFailure(
                FailureCode.DEADLINE_EXCEEDED, "request deadline exceeded"
            )
        if self._cancelled.is_set():
            raise SpeechFailure(FailureCode.CANCELLED, "request was cancelled")


class LoadedModel(Protocol):
    metadata: ModelMetadata

    def transcribe(
        self, request: TranscriptionRequest, context: OperationContext
    ) -> TranscriptionResult: ...

    def unload(self, context: OperationContext) -> None: ...


class Backend(Protocol):
    def capabilities(self) -> BackendCapabilities: ...

    def requirements(self, model: ModelIdentity) -> DeviceRequirements: ...

    def load(
        self,
        model: ModelSelection,
        artifact: VerifiedArtifact,
        device: DeviceCapabilities,
        context: OperationContext,
    ) -> LoadedModel: ...


class DeviceProbe(Protocol):
    def discover(self, context: OperationContext) -> tuple[DeviceCapabilities, ...]: ...
