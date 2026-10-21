"""STT use case orchestration and composition root."""

from __future__ import annotations

import json
import math
import time

from services.stt.admission import AdmissionController
from services.stt.artifacts import verify_artifact
from services.stt.config import (
    ApplicationConfig,
    DeploymentConfig,
    ModelConfig,
    resolve_backend,
)
from services.stt.devices import select_device
from services.stt.domain import (
    DeviceRequirements,
    FailureCode,
    OperationContext,
    SpeechFailure,
    TranscriptionRequest,
    TranscriptionResult,
    Segment,
)
from services.stt.lifecycle import Lifecycle, ModelState, WorkerState
from services.stt.supervisor import InferenceSupervisor


SUPPORTED_MEDIA_TYPES = frozenset(
    {"audio/wav", "audio/flac", "audio/mpeg", "audio/ogg", "audio/mp4"}
)
STT_V1_LANGUAGES = frozenset({"ru", "en", "sv"})


class ModelCatalog:
    def __init__(self, entries: tuple[ModelConfig, ...], default_alias: str):
        self._entries = {entry.alias: entry for entry in entries}
        self._default = default_alias

    def resolve(self, alias: str | None) -> ModelConfig:
        if alias is not None and (
            not isinstance(alias, str) or not alias or len(alias) > 128
        ):
            raise SpeechFailure(FailureCode.INVALID_INPUT, "model alias is invalid")
        requested = alias or self._default
        try:
            return self._entries[requested]
        except KeyError as exc:
            raise SpeechFailure(
                FailureCode.UNKNOWN_MODEL, "unknown model alias"
            ) from exc


class STTApplication:
    def __init__(self, config: ApplicationConfig, catalog: ModelCatalog, runner):
        self.config = config
        self.catalog = catalog
        self.runner = runner
        self.lifecycle = Lifecycle()
        self._capabilities = None
        self._admission = None
        self.startup_failure: SpeechFailure | None = None

    def start(self, backend_capabilities):
        self._capabilities = backend_capabilities
        self.lifecycle.set_model(ModelState.VALIDATING)
        self.lifecycle.set_worker(WorkerState.SERVING)
        try:
            self.lifecycle.set_model(ModelState.LOADING)
            metadata = self.runner.start()
            expected_model = self.catalog.resolve(None).identity
            self._check_capabilities(backend_capabilities, metadata, expected_model)
            settings = self.config.admission
            self._admission = AdmissionController(
                self._execute_job,
                settings.max_queued,
                settings.max_queued_audio_bytes,
                settings.max_retained_audio_bytes,
                settings.max_request_bytes,
                settings.queue_wait_timeout_seconds,
                settings.max_uploads,
                settings.max_upload_bytes,
                cleanup_event=self.runner.cleanup_event,
            )
            self._admission.start()
            self.lifecycle.set_model(ModelState.READY)
            return True
        except SpeechFailure as exc:
            self.startup_failure = exc
            self.lifecycle.set_model(ModelState.FAULTED)
            self.runner.shutdown(self.config.lifecycle.process_exit_timeout_seconds)
            if self.runner.cleanup_unconfirmed:
                self.lifecycle.set_model(ModelState.CLEANUP_UNCONFIRMED)
            return False
        except Exception:
            self.lifecycle.set_model(ModelState.FAULTED)
            self.runner.shutdown(self.config.lifecycle.process_exit_timeout_seconds)
            if self.runner.cleanup_unconfirmed:
                self.lifecycle.set_model(ModelState.CLEANUP_UNCONFIRMED)
            raise

    def acquire_upload(self):
        if not self.lifecycle.ready() or self._admission is None:
            raise SpeechFailure(FailureCode.NOT_READY, "model is unavailable")
        return self._admission.uploads.acquire()

    def transcribe(
        self,
        request: TranscriptionRequest,
        context: OperationContext | None = None,
        *,
        _upload_lease=None,
    ):
        if not self.lifecycle.ready() or self._admission is None:
            raise SpeechFailure(FailureCode.NOT_READY, "model is unavailable")
        if not isinstance(request, TranscriptionRequest):
            raise SpeechFailure(
                FailureCode.INVALID_INPUT, "transcription request is invalid"
            )
        if context is None:
            context = OperationContext(
                time.monotonic() + self.config.admission.request_timeout_seconds
            )
        context.check()
        if not isinstance(request.audio, (bytes, bytearray)) or not isinstance(
            request.media_type, str
        ):
            raise SpeechFailure(FailureCode.INVALID_INPUT, "audio request is invalid")
        if type(request.timestamps) is not bool:
            raise SpeechFailure(FailureCode.INVALID_INPUT, "timestamps must be boolean")
        media_type = request.media_type.split(";", 1)[0].strip().lower()
        if media_type not in SUPPORTED_MEDIA_TYPES:
            raise SpeechFailure(
                FailureCode.UNSUPPORTED_MEDIA_TYPE, "unsupported audio media type"
            )
        if not request.audio:
            raise SpeechFailure(FailureCode.INVALID_INPUT, "audio must not be empty")
        if len(request.audio) > self.config.admission.max_request_bytes:
            raise SpeechFailure(
                FailureCode.INPUT_LIMIT, "audio exceeds configured request limit"
            )
        model = self.catalog.resolve(request.model_alias)
        metadata = self.runner.metadata
        if request.language is not None and not isinstance(request.language, str):
            raise SpeechFailure(
                FailureCode.INVALID_INPUT, "language must be a BCP-47 tag"
            )
        if request.language is None or request.language.lower() == "auto":
            if not metadata.automatic_language_detection:
                raise SpeechFailure(
                    FailureCode.UNSUPPORTED_OPTION,
                    "automatic language detection is unavailable",
                )
            language = None
        else:
            language_code = request.language.lower()
            if language_code not in STT_V1_LANGUAGES:
                raise SpeechFailure(
                    FailureCode.INVALID_INPUT,
                    "source_language must be auto, ru, en, or sv",
                )
            language = language_code
        output_language = request.output_language
        if not isinstance(
            output_language, str
        ) or output_language.lower() not in STT_V1_LANGUAGES | {"auto"}:
            raise SpeechFailure(
                FailureCode.INVALID_INPUT, "output_language must be auto, ru, en, or sv"
            )
        output_language = output_language.lower()
        if request.timestamps and not metadata.segment_timestamps:
            raise SpeechFailure(
                FailureCode.UNSUPPORTED_OPTION, "segment timestamps are unavailable"
            )
        requested_output_language = output_language
        backend_output_language = (
            "auto" if not model.translation_supported else output_language
        )
        normalized = TranscriptionRequest(
            request.audio,
            media_type,
            model.alias,
            language,
            request.timestamps,
            backend_output_language,
        )
        try:
            result = self._admission.submit(normalized, context, _upload_lease)
        except SpeechFailure:
            if self.runner.faulted:
                self._latch_fault()
            raise
        self._validate_result(result)
        if result.language.lower() not in STT_V1_LANGUAGES:
            raise SpeechFailure(FailureCode.UNSUPPORTED_DETECTED_LANGUAGE)
        if not model.translation_supported:
            if result.translated:
                raise SpeechFailure(
                    FailureCode.BACKEND_FAILED,
                    "model returned translated output without translation capability",
                )
            if (
                requested_output_language != "auto"
                and requested_output_language != result.language.lower()
            ):
                raise SpeechFailure(FailureCode.UNSUPPORTED_TRANSLATION)
        result_size = len(
            json.dumps(
                {
                    "text": result.text,
                    "language": result.language,
                    "transcription": result.transcription,
                    "language_probability": result.language_probability,
                    "output_language": result.output_language,
                    "translated": result.translated,
                    "segments": [segment.__dict__ for segment in result.segments]
                    if result.segments is not None
                    else None,
                },
                separators=(",", ":"),
            ).encode()
        )
        if result_size > self.config.admission.max_result_bytes:
            raise SpeechFailure(
                FailureCode.RESOURCE_EXHAUSTED,
                "transcription result exceeds configured limit",
            )
        if self.runner.faulted:
            self._latch_fault()
        return result

    def transcribe_uploaded(
        self,
        upload_lease,
        media_type: str,
        model_alias: str | None = None,
        language: str | None = None,
        timestamps: bool = False,
        context: OperationContext | None = None,
        output_language: str = "auto",
    ):
        audio = upload_lease.finish()
        return self.transcribe(
            TranscriptionRequest(
                audio, media_type, model_alias, language, timestamps, output_language
            ),
            context,
            _upload_lease=upload_lease,
        )

    def close(self):
        if self.lifecycle.snapshot()[1] == ModelState.READY:
            self.lifecycle.set_model(ModelState.UNLOADING)
        self.lifecycle.set_worker(WorkerState.DRAINING)
        if self._admission is not None:
            self._admission.close(self.config.lifecycle.shutdown_drain_timeout_seconds)
        self.runner.shutdown(self.config.lifecycle.process_exit_timeout_seconds)
        if self.runner.cleanup_unconfirmed:
            self.lifecycle.set_model(ModelState.CLEANUP_UNCONFIRMED)
            self.lifecycle.set_worker(WorkerState.DRAINING)
        elif self.runner.faulted:
            self.lifecycle.set_model(ModelState.FAULTED)
            self.lifecycle.set_worker(WorkerState.STOPPED)
        else:
            self.lifecycle.set_model(ModelState.UNLOADED)
            self.lifecycle.set_worker(WorkerState.STOPPED)

    def _latch_fault(self):
        state = (
            ModelState.CLEANUP_UNCONFIRMED
            if self.runner.cleanup_unconfirmed
            else ModelState.FAULTED
        )
        self.lifecycle.set_model(state)
        if self._admission is not None:
            self._admission.latch_fault()

    def _execute_job(self, request, context):
        try:
            return self.runner.transcribe(request, context)
        except SpeechFailure:
            if self.runner.faulted:
                self._latch_fault()
            raise

    @staticmethod
    def _validate_result(result):
        if (
            not isinstance(result, TranscriptionResult)
            or not isinstance(result.text, str)
            or not isinstance(result.language, str)
            or not result.language
        ):
            raise SpeechFailure(
                FailureCode.BACKEND_FAILED, "inference returned an invalid result"
            )
        if result.transcription is not None and not isinstance(
            result.transcription, str
        ):
            raise SpeechFailure(
                FailureCode.BACKEND_FAILED, "inference returned invalid transcription"
            )
        if result.language_probability is not None and (
            type(result.language_probability) not in (float, int)
            or not math.isfinite(result.language_probability)
            or not 0 <= result.language_probability <= 1
        ):
            raise SpeechFailure(
                FailureCode.BACKEND_FAILED,
                "inference returned invalid language probability",
            )
        if type(result.translated) is not bool:
            raise SpeechFailure(
                FailureCode.BACKEND_FAILED,
                "inference returned invalid translation status",
            )
        if result.segments is None:
            return
        if not isinstance(result.segments, tuple):
            raise SpeechFailure(
                FailureCode.BACKEND_FAILED, "inference returned invalid timestamps"
            )
        for segment in result.segments:
            if (
                not isinstance(segment, Segment)
                or type(segment.start_seconds) not in (int, float)
                or type(segment.end_seconds) not in (int, float)
                or not math.isfinite(segment.start_seconds)
                or not math.isfinite(segment.end_seconds)
                or segment.start_seconds < 0
                or segment.end_seconds < segment.start_seconds
                or not isinstance(segment.text, str)
            ):
                raise SpeechFailure(
                    FailureCode.BACKEND_FAILED,
                    "inference returned invalid timestamps",
                )

    @staticmethod
    def _check_capabilities(capabilities, metadata, expected_model):
        if metadata.identity != expected_model:
            raise SpeechFailure(
                FailureCode.MODEL_LOAD_FAILED,
                "loaded model identity does not match configuration",
            )
        if (
            metadata.automatic_language_detection
            and not capabilities.automatic_language_detection
        ):
            raise SpeechFailure(
                FailureCode.MODEL_LOAD_FAILED,
                "backend capability report is inconsistent",
            )
        if metadata.segment_timestamps and not capabilities.segment_timestamps:
            raise SpeechFailure(
                FailureCode.MODEL_LOAD_FAILED,
                "backend capability report is inconsistent",
            )


def create_application(
    config: ApplicationConfig,
    deployment: DeploymentConfig,
    backend_registry: dict[str, object],
    device_probe,
    artifact_store=None,
) -> STTApplication:
    factory = resolve_backend(config.backend_id, backend_registry)
    backend = factory()
    expected_artifacts = {model.artifact_ref for model in config.models}
    if set(deployment.artifact_roots) != expected_artifacts:
        raise SpeechFailure(
            FailureCode.MODEL_LOAD_FAILED,
            "deployment artifact roots do not match application configuration",
        )
    model_config = ModelCatalog(config.models, config.default_model).resolve(None)
    selection = config.catalog()[config.default_model]
    try:
        root = deployment.artifact_roots[model_config.artifact_ref]
    except KeyError as exc:
        raise SpeechFailure(
            FailureCode.MODEL_LOAD_FAILED, "model artifact is not configured"
        ) from exc
    if artifact_store is None:
        artifact = verify_artifact(model_config, root)
    else:
        artifact = artifact_store.verify(model_config, root)
    operation = OperationContext()
    available = device_probe.discover(operation)
    requirements = backend.requirements(model_config.identity)
    backend_capabilities = backend.capabilities()
    if (
        config.device_mode != "auto"
        and config.device_mode not in backend_capabilities.device_kinds
    ):
        raise SpeechFailure(
            FailureCode.DEVICE_UNAVAILABLE, "backend does not support configured device"
        )
    requirements = DeviceRequirements(
        requirements.allowed_kinds & backend_capabilities.device_kinds,
        requirements.required_features,
        requirements.estimated_peak_memory_bytes,
        requirements.required_features_by_kind,
    )
    device = select_device(
        config.device_mode, config.device_preference, requirements, available
    )
    if device.kind not in backend_capabilities.device_kinds:
        raise SpeechFailure(
            FailureCode.DEVICE_UNAVAILABLE, "backend does not support selected device"
        )
    runner = InferenceSupervisor(
        factory,
        selection,
        artifact,
        device,
        backend_capabilities,
        config.lifecycle.cooperative_cancel_grace_seconds,
        config.lifecycle.process_exit_timeout_seconds,
        config.admission.max_ipc_message_bytes,
        config.lifecycle.model_load_timeout_seconds,
    )
    return STTApplication(
        config, ModelCatalog(config.models, config.default_model), runner
    )
