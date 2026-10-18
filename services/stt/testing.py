"""Deterministic fake backend for tests; never registered by the worker runtime."""

import os
import time

from services.stt.domain import (
    BackendCapabilities,
    DeviceRequirements,
    FailureCode,
    ModelMetadata,
    Segment,
    SpeechFailure,
    TranscriptionResult,
)


class FakeBackendFactory:
    def __init__(
        self, behavior="success", duration_seconds=0.0, auto=True, timestamps=True
    ):
        self.behavior = behavior
        self.duration_seconds = duration_seconds
        self.auto = auto
        self.timestamps = timestamps

    def __call__(self):
        return FakeBackend(
            self.behavior, self.duration_seconds, self.auto, self.timestamps
        )


class FakeBackend:
    def __init__(self, behavior, duration_seconds, auto, timestamps):
        self.behavior = behavior
        self.duration_seconds = duration_seconds
        self.auto = auto
        self.timestamps = timestamps

    def capabilities(self):
        return BackendCapabilities(
            frozenset({"cpu", "cuda"}), self.auto, self.timestamps, False
        )

    def requirements(self, _model):
        return DeviceRequirements(frozenset({"cpu", "cuda"}))

    def load(self, selection, _artifact, _device, _context):
        if self.behavior == "load_unresponsive":
            time.sleep(30)
        if self.behavior == "load_failure":
            raise SpeechFailure(FailureCode.MODEL_LOAD_FAILED, "fake load failure")
        identity = selection.identity
        if self.behavior == "wrong_identity":
            from services.stt.domain import ModelIdentity

            identity = ModelIdentity(identity.family, "wrong-model")
        return FakeLoadedModel(
            identity,
            self.behavior,
            self.duration_seconds,
            self.auto,
            self.timestamps,
        )


class FakeLoadedModel:
    def __init__(self, identity, behavior, duration_seconds, auto, timestamps):
        self.metadata = ModelMetadata(
            identity, frozenset({"en", "ru"}), auto, timestamps
        )
        self.behavior = behavior
        self.duration_seconds = duration_seconds
        self._failed_once = False

    def transcribe(self, request, context):
        if self.behavior == "crash":
            os._exit(17)
        if self.behavior == "resource_failure_once" and not self._failed_once:
            self._failed_once = True
            raise SpeechFailure(
                FailureCode.RESOURCE_EXHAUSTED, "injected allocation failure"
            )
        deadline = time.monotonic() + self.duration_seconds
        while time.monotonic() < deadline:
            if self.behavior != "unresponsive":
                context.check()
            time.sleep(0.005)
        if self.behavior == "failure":
            raise SpeechFailure(FailureCode.BACKEND_FAILED, "fake request failure")
        return TranscriptionResult(
            f"fake transcription ({len(request.audio)} bytes)",
            request.language or "en",
            (Segment(0.0, 0.5, "fake"),) if request.timestamps else None,
        )

    def unload(self, _context):
        return None
