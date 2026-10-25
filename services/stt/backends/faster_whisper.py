"""faster-whisper adapter. Native packages are imported only in this module."""

from __future__ import annotations

import io
from dataclasses import dataclass

from services.stt.domain import (
    BackendCapabilities,
    DeviceRequirements,
    FailureCode,
    FatalBackendFailure,
    ModelIdentity,
    ModelMetadata,
    OperationContext,
    Segment,
    SpeechFailure,
    TranscriptionRequest,
    TranscriptionResult,
    VerifiedArtifact,
)


@dataclass(frozen=True)
class Options:
    cpu_threads: int
    compute_type_cpu: str
    compute_type_cuda: str
    beam_size: int
    sample_rate_hz: int
    max_duration_seconds: float
    max_decoded_audio_bytes: int
    max_result_bytes: int
    cuda_device_index: int
    minimum_free_gpu_bytes_before_load: int | None


class Backend:
    def __init__(self, options: Options, *, modules=None):
        self.options = options
        self._modules = modules

    def capabilities(self):
        return BackendCapabilities(
            frozenset({"cpu", "cuda"}),
            automatic_language_detection=True,
            segment_timestamps=True,
        )

    def requirements(self, _model: ModelIdentity):
        return DeviceRequirements(
            frozenset({"cpu", "cuda"}),
            estimated_peak_memory_bytes=self.options.minimum_free_gpu_bytes_before_load,
            required_features_by_kind=(
                ("cpu", frozenset({f"compute_type:{self.options.compute_type_cpu}"})),
                ("cuda", frozenset({f"compute_type:{self.options.compute_type_cuda}"})),
            ),
        )

    def load(self, _selection, artifact: VerifiedArtifact, device, context):
        context.check()
        modules = self._load_modules()
        index = self.options.cuda_device_index if device.kind == "cuda" else 0
        compute_type = (
            self.options.compute_type_cuda
            if device.kind == "cuda"
            else self.options.compute_type_cpu
        )
        try:
            if (
                device.kind == "cuda"
                and modules.ctranslate2.get_cuda_device_count() <= index
            ):
                raise SpeechFailure(FailureCode.DEVICE_UNAVAILABLE)
            supported = modules.ctranslate2.get_supported_compute_types(
                device.kind, index
            )
            if compute_type not in supported:
                raise SpeechFailure(FailureCode.DEVICE_UNAVAILABLE)
            if not (artifact.root / "tokenizer.json").is_file():
                raise SpeechFailure(FailureCode.MODEL_LOAD_FAILED)
            model = modules.faster_whisper.WhisperModel(
                str(artifact.root),
                device=device.kind,
                device_index=index,
                compute_type=compute_type,
                cpu_threads=self.options.cpu_threads,
                num_workers=1,
                local_files_only=True,
            )
        except SpeechFailure:
            raise
        except Exception as exc:
            raise SpeechFailure(FailureCode.MODEL_LOAD_FAILED, str(exc)) from exc
        multilingual = bool(
            getattr(getattr(model, "model", None), "is_multilingual", True)
        )
        try:
            from faster_whisper.tokenizer import _LANGUAGE_CODES

            languages = (
                frozenset(_LANGUAGE_CODES) if multilingual else frozenset({"en"})
            )
        except ImportError:
            languages = frozenset()
        metadata = ModelMetadata(
            _selection.identity,
            languages,
            automatic_language_detection=multilingual,
            segment_timestamps=True,
        )
        return LoadedModel(model, metadata, self.options, modules)

    def _load_modules(self):
        if self._modules is not None:
            return self._modules
        try:
            import av
            import ctranslate2
            import numpy
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise SpeechFailure(
                FailureCode.MODEL_LOAD_FAILED,
                "faster-whisper runtime dependency is unavailable",
            ) from exc

        class Modules:
            pass

        modules = Modules()
        modules.av = av
        modules.ctranslate2 = ctranslate2
        modules.numpy = numpy
        modules.faster_whisper = type(
            "FasterWhisperModule", (), {"WhisperModel": WhisperModel}
        )
        return modules


class LoadedModel:
    def __init__(self, model, metadata, options, modules):
        self.metadata = metadata
        self._model = model
        self._options = options
        self._modules = modules

    def transcribe(self, request: TranscriptionRequest, context: OperationContext):
        audio = _decode_audio(request.audio, self._options, context, self._modules)
        context.check()
        try:
            segments, info = self._model.transcribe(
                audio,
                language=request.language,
                task="transcribe",
                beam_size=self._options.beam_size,
                word_timestamps=False,
                vad_filter=False,
            )
            transcription, result_segments = _collect_segments(
                segments, request, context, self._options.max_result_bytes
            )
            context.check()
            language = getattr(info, "language", None)
            if not isinstance(language, str) or not language:
                raise SpeechFailure(FailureCode.LANGUAGE_UNDETECTED)
            language = language.lower()
            output_language = request.output_language
            target = language if output_language == "auto" else output_language
            text = transcription
            translated = False
            if target != language:
                if language not in {"ru", "en", "sv"}:
                    raise SpeechFailure(FailureCode.UNSUPPORTED_DETECTED_LANGUAGE)
                if target != "en":
                    raise SpeechFailure(FailureCode.UNSUPPORTED_TRANSLATION)
                translated_segments, _ = self._model.transcribe(
                    audio,
                    language=language,
                    task="translate",
                    beam_size=self._options.beam_size,
                    word_timestamps=False,
                    vad_filter=False,
                )
                text, _ = _collect_segments(
                    translated_segments,
                    request,
                    context,
                    self._options.max_result_bytes,
                )
                translated = True
            probability = getattr(info, "language_probability", None)
            if request.language is not None or type(probability) not in (int, float):
                probability = None
            return TranscriptionResult(
                text,
                language,
                tuple(result_segments) if request.timestamps else None,
                transcription,
                float(probability) if probability is not None else None,
                target,
                translated,
            )
        except SpeechFailure:
            raise
        except Exception as exc:
            # Native runtime failures may leave CUDA state uncertain. Fault-latch the
            # child instead of trying another precision, device or model.
            raise FatalBackendFailure(FailureCode.BACKEND_FAILED, str(exc)) from exc

    def unload(self, context: OperationContext):
        context.check()
        self._model = None


def _collect_segments(segments, request, context, maximum):
    parts = []
    timestamps = []
    size = 0
    for segment in segments:
        context.check()
        text = str(segment.text)
        size += len(text.encode("utf-8")) + (64 if request.timestamps else 0)
        if size > maximum:
            raise SpeechFailure(FailureCode.RESOURCE_EXHAUSTED)
        parts.append(text)
        if request.timestamps:
            timestamps.append(Segment(float(segment.start), float(segment.end), text))
    context.check()
    return "".join(parts), timestamps


def _decode_audio(audio_bytes, options, context, modules):
    maximum_samples = min(
        options.max_decoded_audio_bytes // 4,
        int(options.max_duration_seconds * options.sample_rate_hz),
    )
    if maximum_samples < 1:
        raise SpeechFailure(FailureCode.RESOURCE_EXHAUSTED)
    try:
        output = modules.numpy.empty(maximum_samples, dtype="float32")
    except MemoryError as exc:
        raise SpeechFailure(
            FailureCode.RESOURCE_EXHAUSTED, "decoded audio allocation failed"
        ) from exc
    written = 0
    try:
        with modules.av.open(io.BytesIO(audio_bytes), mode="r") as container:
            if not container.streams.audio:
                raise SpeechFailure(FailureCode.DECODE_FAILED)
            resampler = modules.av.AudioResampler(
                format="fltp", layout="mono", rate=options.sample_rate_hz
            )
            for frame in container.decode(audio=0):
                context.check()
                for converted in resampler.resample(frame):
                    samples = converted.to_ndarray().reshape(-1)
                    count = len(samples)
                    if written + count > maximum_samples:
                        raise SpeechFailure(FailureCode.INPUT_LIMIT)
                    output[written : written + count] = samples
                    written += count
            for converted in resampler.resample(None):
                samples = converted.to_ndarray().reshape(-1)
                count = len(samples)
                if written + count > maximum_samples:
                    raise SpeechFailure(FailureCode.INPUT_LIMIT)
                output[written : written + count] = samples
                written += count
    except SpeechFailure:
        raise
    except Exception as exc:
        raise SpeechFailure(FailureCode.DECODE_FAILED, str(exc)) from exc
    if written == 0:
        raise SpeechFailure(FailureCode.DECODE_FAILED)
    context.check()
    return output[:written]
