"""STT use case orchestration and composition root."""

from __future__ import annotations

import json
import math
import threading
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


class _RunnerFactoryHandoff:
    """Give a preflight runner exclusively to the loader or late cleanup."""

    def __init__(self):
        self._condition = threading.Condition()
        self._state = "running"
        self._runner = None
        self._error = None

    def publish(self, runner, error):
        with self._condition:
            if self._state == "running":
                self._runner = runner
                self._error = error
                self._state = "ready"
                self._condition.notify_all()
                return False
            if self._state == "abandoned":
                self._state = "cleaning" if runner is not None else "cleaned"
                self._condition.notify_all()
                return runner is not None
            raise RuntimeError("preflight runner ownership is inconsistent")

    def claim(self, timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while self._state == "running":
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._state = "abandoned"
                    self._condition.notify_all()
                    return None, None, True
                self._condition.wait(remaining)
            if self._state != "ready":
                return None, None, True
            self._state = "claimed"
            return self._runner, self._error, False

    def cleanup_finished(self):
        with self._condition:
            if self._state != "cleaning":
                raise RuntimeError("preflight cleanup ownership is inconsistent")
            self._state = "cleaned"
            self._condition.notify_all()


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
    def __init__(
        self,
        config: ApplicationConfig,
        catalog: ModelCatalog,
        runner_factory,
        cleanup_event=None,
    ):
        self.config = config
        self.catalog = catalog
        self._runner_factory = runner_factory
        self.runner = None
        self.lifecycle = Lifecycle()
        self._capabilities = None
        self._admission = None
        self._condition = threading.Condition()
        self._state = ModelState.UNLOADED
        self._loading_failure = None
        self._load_generation = 0
        self._failed_generation = None
        self._load_thread = None
        self._preflight_thread = None
        self._cleanup_event = cleanup_event or threading.Event()
        self._cleanup_event.set()
        self._stopping = threading.Event()
        self._idle_thread = None
        self._last_use = time.monotonic()
        self._warmups = 0
        self.startup_failure: SpeechFailure | None = None
        self._preflight_handoff = None

    def start(self, backend_capabilities):
        self._capabilities = backend_capabilities
        self.lifecycle.set_model(ModelState.VALIDATING)
        self.lifecycle.set_worker(WorkerState.SERVING)
        try:
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
                cleanup_event=self._cleanup_event,
            )
            self._admission.start()
            self.lifecycle.set_model(ModelState.UNLOADED)
            self._idle_thread = threading.Thread(
                target=self._idle_loop, name="stt-model-idle", daemon=True
            )
            self._idle_thread.start()
            return True
        except SpeechFailure as exc:
            self.startup_failure = exc
            self.lifecycle.set_model(ModelState.FAULTED)
            return False
        except Exception:
            self.lifecycle.set_model(ModelState.FAULTED)
            raise

    def warmup(self, context: OperationContext | None = None):
        if not self.lifecycle.ready() or self._admission is None:
            raise SpeechFailure(FailureCode.NOT_READY, "worker is unavailable")
        if context is None:
            context = OperationContext(
                time.monotonic() + self.config.admission.request_timeout_seconds
            )
        context.check()
        with self._condition:
            self._warmups += 1
        try:
            self._ensure_model(context)
            return {"model_state": "ready"}
        finally:
            with self._condition:
                self._warmups -= 1
                if self._state == ModelState.READY:
                    self._last_use = time.monotonic()
                self._condition.notify_all()

    def acquire_upload(self):
        if not self.lifecycle.ready() or self._admission is None:
            raise SpeechFailure(FailureCode.NOT_READY, "model is unavailable")
        return self._admission.acquire_upload()

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
        if request.language is not None and not isinstance(request.language, str):
            raise SpeechFailure(
                FailureCode.INVALID_INPUT, "language must be a BCP-47 tag"
            )
        if request.language is None or request.language.lower() == "auto":
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
            self._latch_runner_fault_if_needed()
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
        self._latch_runner_fault_if_needed()
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
        shutdown_deadline = time.monotonic() + (
            self.config.lifecycle.shutdown_drain_timeout_seconds
            + self.config.lifecycle.model_load_timeout_seconds
            + 2 * self.config.lifecycle.process_exit_timeout_seconds
        )
        self.lifecycle.set_worker(WorkerState.DRAINING)
        self._stopping.set()
        with self._condition:
            self._condition.notify_all()
        admission_stopped = True
        if self._admission is not None:
            admission_stopped = self._admission.close(
                min(
                    self.config.lifecycle.shutdown_drain_timeout_seconds,
                    max(0.0, shutdown_deadline - time.monotonic()),
                )
            )
        cleanup_uncertain = not admission_stopped
        with self._condition:
            while (
                self._state in {ModelState.LOADING, ModelState.UNLOADING}
                or self._warmups
            ):
                remaining = shutdown_deadline - time.monotonic()
                if remaining <= 0:
                    cleanup_uncertain = True
                    self._state = ModelState.CLEANUP_UNCONFIRMED
                    self.lifecycle.set_model(ModelState.CLEANUP_UNCONFIRMED)
                    break
                self._condition.wait(min(remaining, 0.05))
        if self._idle_thread is not None:
            self._idle_thread.join(
                timeout=max(0.0, shutdown_deadline - time.monotonic())
            )
            if self._idle_thread.is_alive():
                cleanup_uncertain = True
        loader = self._load_thread
        if loader is not None and loader is not threading.current_thread():
            loader.join(timeout=max(0.0, shutdown_deadline - time.monotonic()))
            if loader.is_alive():
                cleanup_uncertain = True
        preflight = self._preflight_thread
        if preflight is not None and preflight is not threading.current_thread():
            preflight.join(timeout=max(0.0, shutdown_deadline - time.monotonic()))
            if preflight.is_alive():
                cleanup_uncertain = True
        with self._condition:
            runner = self.runner
        if runner is not None and not cleanup_uncertain:
            if not self._shutdown_runner(
                runner, max(0.0, shutdown_deadline - time.monotonic())
            ):
                cleanup_uncertain = True
        if cleanup_uncertain or (runner is not None and runner.cleanup_unconfirmed):
            self.lifecycle.set_model(ModelState.CLEANUP_UNCONFIRMED)
            self.lifecycle.set_worker(WorkerState.DRAINING)
        elif runner is not None and runner.faulted:
            self.lifecycle.set_model(ModelState.FAULTED)
            self.lifecycle.set_worker(WorkerState.STOPPED)
        else:
            self.lifecycle.set_model(ModelState.UNLOADED)
            self.lifecycle.set_worker(WorkerState.STOPPED)

    def _latch_fault(self):
        runner = self.runner
        state = (
            ModelState.CLEANUP_UNCONFIRMED
            if runner is not None and runner.cleanup_unconfirmed
            else ModelState.FAULTED
        )
        with self._condition:
            self._state = state
            self._condition.notify_all()
        self.lifecycle.set_model(state)
        if self._admission is not None:
            self._admission.latch_fault()

    def _latch_runner_fault_if_needed(self):
        with self._condition:
            if self._state == ModelState.CLEANUP_UNCONFIRMED:
                return
            runner = self.runner
            if runner is None or not runner.faulted:
                return
            state = (
                ModelState.CLEANUP_UNCONFIRMED
                if runner.cleanup_unconfirmed
                else ModelState.FAULTED
            )
            self._state = state
            self.lifecycle.set_model(state)
            self._condition.notify_all()
        if self._admission is not None:
            self._admission.latch_fault()

    def _shutdown_runner(self, runner, timeout_seconds=None):
        try:
            timeout = (
                self.config.lifecycle.process_exit_timeout_seconds
                if timeout_seconds is None
                else timeout_seconds
            )
            result = runner.shutdown(timeout)
        except Exception:
            return False
        return result is not False and not runner.cleanup_unconfirmed

    def _execute_job(self, request, context):
        try:
            runner = self._ensure_model(context)
            metadata = runner.metadata
            if request.language is None and not metadata.automatic_language_detection:
                raise SpeechFailure(
                    FailureCode.UNSUPPORTED_OPTION,
                    "automatic language detection is unavailable",
                )
            if request.timestamps and not metadata.segment_timestamps:
                raise SpeechFailure(
                    FailureCode.UNSUPPORTED_OPTION,
                    "segment timestamps are unavailable",
                )
            return runner.transcribe(request, context)
        except SpeechFailure:
            self._latch_runner_fault_if_needed()
            raise
        finally:
            self._mark_model_used()

    def _ensure_model(self, context):
        while True:
            context.check()
            with self._condition:
                if self._stopping.is_set():
                    raise SpeechFailure(FailureCode.NOT_READY, "worker is draining")
                if self._state == ModelState.READY:
                    return self.runner
                if self._state in {
                    ModelState.FAULTED,
                    ModelState.CLEANUP_UNCONFIRMED,
                }:
                    raise SpeechFailure(FailureCode.NOT_READY, "model is unavailable")
                if self._state == ModelState.LOADING:
                    generation = self._load_generation
                    remaining = (
                        context.deadline - time.monotonic() if context.deadline else 0.1
                    )
                    if remaining <= 0:
                        raise SpeechFailure(FailureCode.DEADLINE_EXCEEDED)
                    self._condition.wait(min(remaining, 0.05))
                    if (
                        self._state != ModelState.LOADING
                        and self._failed_generation == generation
                    ):
                        raise self._loading_failure
                    continue
                if self._state == ModelState.UNLOADING:
                    remaining = (
                        context.deadline - time.monotonic() if context.deadline else 0.1
                    )
                    if remaining <= 0:
                        raise SpeechFailure(FailureCode.DEADLINE_EXCEEDED)
                    self._condition.wait(min(remaining, 0.05))
                    continue
                self._state = ModelState.LOADING
                self._loading_failure = None
                self._failed_generation = None
                self._load_generation += 1
                generation = self._load_generation
                self.lifecycle.set_model(ModelState.LOADING)
                loader = threading.Thread(
                    target=self._load_model,
                    args=(generation,),
                    name="stt-model-loader",
                    daemon=True,
                )
                self._load_thread = loader
                loader.start()

    def _load_model(self, generation):
        runner = None
        try:
            runner = self._runner_factory_bounded()
            with self._condition:
                if self._stopping.is_set() or self._state != ModelState.LOADING:
                    raise SpeechFailure(FailureCode.NOT_READY, "worker is draining")
                self.runner = runner
            metadata = runner.start()
            self._check_capabilities(
                self._capabilities, metadata, self.catalog.resolve(None).identity
            )
            if self._stopping.is_set():
                raise SpeechFailure(FailureCode.NOT_READY, "worker is draining")
            with self._condition:
                self._state = ModelState.READY
                self._last_use = time.monotonic()
                self.lifecycle.set_model(ModelState.READY)
                self._condition.notify_all()
            return
        except SpeechFailure as exc:
            shutdown_confirmed = runner is None or self._shutdown_runner(runner)
            cleanup_unconfirmed = exc.retain_resources or not shutdown_confirmed
            with self._condition:
                self._loading_failure = exc
                self._failed_generation = generation
                if cleanup_unconfirmed:
                    self.runner = runner
                    self._state = ModelState.CLEANUP_UNCONFIRMED
                    self.lifecycle.set_model(ModelState.CLEANUP_UNCONFIRMED)
                elif self._stopping.is_set():
                    self.runner = None
                    if self._state != ModelState.CLEANUP_UNCONFIRMED:
                        self._state = ModelState.UNLOADED
                else:
                    self.runner = None
                if cleanup_unconfirmed or self._stopping.is_set():
                    self._condition.notify_all()
            if (
                self._admission is not None
                and not cleanup_unconfirmed
                and not self._stopping.is_set()
            ):
                failure = exc
                self._admission.fail_admitted(
                    failure, lambda: self._publish_failed_generation(failure)
                )
            elif self._admission is not None:
                if cleanup_unconfirmed:
                    self._admission.latch_fault()
            if (
                self._admission is None
                and not cleanup_unconfirmed
                and not self._stopping.is_set()
            ):
                self._publish_failed_generation(exc)
        except Exception:
            shutdown_confirmed = runner is None or self._shutdown_runner(runner)
            failure = SpeechFailure(FailureCode.MODEL_LOAD_FAILED)
            cleanup_unconfirmed = not shutdown_confirmed
            with self._condition:
                self._loading_failure = failure
                self._failed_generation = generation
                if cleanup_unconfirmed:
                    self.runner = runner
                    self._state = ModelState.CLEANUP_UNCONFIRMED
                    self.lifecycle.set_model(self._state)
                else:
                    self.runner = None
                    if (
                        self._stopping.is_set()
                        and self._state != ModelState.CLEANUP_UNCONFIRMED
                    ):
                        self._state = ModelState.UNLOADED
                if cleanup_unconfirmed or self._stopping.is_set():
                    self._condition.notify_all()
            if (
                self._admission is not None
                and not cleanup_unconfirmed
                and not self._stopping.is_set()
            ):
                self._admission.fail_admitted(
                    failure, lambda: self._publish_failed_generation(failure)
                )
            elif self._admission is not None:
                if cleanup_unconfirmed:
                    self._admission.latch_fault()
            if (
                self._admission is None
                and not cleanup_unconfirmed
                and not self._stopping.is_set()
            ):
                self._publish_failed_generation(failure)

    def _publish_failed_generation(self, failure):
        with self._condition:
            self._loading_failure = failure
            self._state = ModelState.UNLOADED
            self.lifecycle.set_model(ModelState.UNLOADED)
            self._condition.notify_all()

    def _runner_factory_bounded(self):
        """Bound preflight even when a native device probe ignores cancellation.

        A late factory result is never allowed to start a child. It is shut down
        by the factory thread, while cleanup remains latched uncertain.
        """
        handoff = _RunnerFactoryHandoff()
        self._preflight_handoff = handoff

        def create():
            runner = None
            error = None
            try:
                runner = self._runner_factory()
            except BaseException as exc:
                error = exc
            cleanup = handoff.publish(runner, error)
            if cleanup and runner is not None:
                self._shutdown_runner(runner)
                handoff.cleanup_finished()

        thread = threading.Thread(
            target=create, name="stt-device-preflight", daemon=True
        )
        self._preflight_thread = thread
        thread.start()
        runner, error, abandoned = handoff.claim(
            self.config.lifecycle.model_load_timeout_seconds
        )
        if abandoned:
            raise SpeechFailure(
                FailureCode.MODEL_LOAD_FAILED,
                "device preflight exceeded initialization deadline",
                retain_resources=True,
            )
        if error is not None:
            if isinstance(error, SpeechFailure):
                raise error
            raise SpeechFailure(FailureCode.MODEL_LOAD_FAILED) from error
        return runner

    def _mark_model_used(self):
        with self._condition:
            if self._state == ModelState.READY:
                self._last_use = time.monotonic()
                self._condition.notify_all()

    def _idle_loop(self):
        timeout = self.config.lifecycle.model_idle_unload_seconds
        while not self._stopping.is_set():
            with self._condition:
                if self._state != ModelState.READY:
                    self._condition.wait(0.1)
                    continue
                deadline = self._last_use + timeout
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
            if self._admission is not None:
                if not self._admission.run_if_idle(
                    self._reserve_unload, self._unload_if_idle
                ):
                    with self._condition:
                        self._condition.wait(0.02)
                else:
                    with self._condition:
                        if self._state == ModelState.READY:
                            self._condition.wait(0.02)

    def _reserve_unload(self):
        with self._condition:
            if self._state != ModelState.READY or self._stopping.is_set():
                return
            if self._warmups:
                return
            if (
                time.monotonic()
                < self._last_use + self.config.lifecycle.model_idle_unload_seconds
            ):
                return
            runner = self.runner
            if runner is None:
                return
            self._state = ModelState.UNLOADING
            self.lifecycle.set_model(ModelState.UNLOADING)
            return True

    def _unload_if_idle(self):
        with self._condition:
            runner = self.runner
        if runner is None:
            with self._condition:
                self._state = ModelState.CLEANUP_UNCONFIRMED
                self.lifecycle.set_model(ModelState.CLEANUP_UNCONFIRMED)
                self._condition.notify_all()
            return
        cleanup_confirmed = self._shutdown_runner(runner)
        latch_admission = False
        with self._condition:
            if self._state == ModelState.CLEANUP_UNCONFIRMED:
                self._condition.notify_all()
                return
            if not cleanup_confirmed:
                self._state = ModelState.CLEANUP_UNCONFIRMED
                self.lifecycle.set_model(ModelState.CLEANUP_UNCONFIRMED)
                latch_admission = True
            elif runner.faulted:
                self._state = ModelState.FAULTED
                self.lifecycle.set_model(ModelState.FAULTED)
                latch_admission = True
            else:
                self.runner = None
                self._state = ModelState.UNLOADED
                self.lifecycle.set_model(ModelState.UNLOADED)
            self._condition.notify_all()
        if latch_admission and self._admission is not None:
            self._admission.latch_fault()

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
    cleanup_event = threading.Event()
    cleanup_event.set()
    supervisor_type = InferenceSupervisor

    def runner_factory():
        available = device_probe.discover(OperationContext())
        device = select_device(
            config.device_mode, config.device_preference, requirements, available
        )
        if device.kind not in backend_capabilities.device_kinds:
            raise SpeechFailure(
                FailureCode.DEVICE_UNAVAILABLE,
                "backend does not support selected device",
            )
        return supervisor_type(
            factory,
            selection,
            artifact,
            device,
            backend_capabilities,
            config.lifecycle.cooperative_cancel_grace_seconds,
            config.lifecycle.process_exit_timeout_seconds,
            config.admission.max_ipc_message_bytes,
            config.lifecycle.model_load_timeout_seconds,
            cleanup_event=cleanup_event,
        )

    return STTApplication(
        config,
        ModelCatalog(config.models, config.default_model),
        runner_factory,
        cleanup_event,
    )
