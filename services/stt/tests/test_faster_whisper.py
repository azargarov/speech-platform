import io
import math
import tempfile
import wave
from types import SimpleNamespace
import unittest
from pathlib import Path

import numpy

from services.stt.backends.faster_whisper import (
    FasterWhisperBackend,
    FasterWhisperLoadedModel,
    FasterWhisperOptions,
    _decode_audio,
)
from services.stt.domain import (
    ArtifactIdentity,
    DeviceCapabilities,
    FailureCode,
    FatalBackendFailure,
    ModelIdentity,
    ModelMetadata,
    ModelSelection,
    OperationContext,
    SpeechFailure,
    TranscriptionRequest,
    VerifiedArtifact,
    safe_error,
)
from services.stt.device_adapters import SystemDeviceProbe


def wav_bytes(seconds=0.2, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        count = int(seconds * rate)
        stream.writeframes(
            b"".join(
                int(1000 * math.sin(2 * math.pi * 440 * index / rate)).to_bytes(
                    2, "little", signed=True
                )
                for index in range(count)
            )
        )
    return output.getvalue()


def options(**overrides):
    values = {
        "cpu_threads": 2,
        "compute_type_cpu": "int8",
        "compute_type_cuda": "float16",
        "beam_size": 1,
        "sample_rate_hz": 16000,
        "max_duration_seconds": 1,
        "max_decoded_audio_bytes": 64000,
        "max_result_bytes": 1024,
        "cuda_device_index": 0,
        "minimum_free_gpu_bytes_before_load": 1024,
    }
    values.update(overrides)
    return FasterWhisperOptions(**values)


class DecodeTests(unittest.TestCase):
    def test_decode_is_mono_float32_and_bounded(self):
        class Resampler:
            def __init__(self, **_kwargs):
                pass

            def resample(self, frame):
                if frame is None:
                    return []
                return [frame]

        class Frame:
            def to_ndarray(self):
                return numpy.zeros((1, 3200), dtype=numpy.float32)

        class Container:
            streams = SimpleNamespace(audio=[object()])

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def decode(self, **_kwargs):
                return [Frame()]

        fake_av = SimpleNamespace(
            open=lambda *_args, **_kwargs: Container(), AudioResampler=Resampler
        )
        modules = SimpleNamespace(av=fake_av, numpy=numpy)
        decoded = _decode_audio(b"fixture", options(), OperationContext(), modules)
        self.assertEqual(decoded.dtype, numpy.float32)
        self.assertEqual(decoded.shape, (3200,))
        with self.assertRaises(SpeechFailure) as caught:
            _decode_audio(
                b"fixture",
                options(max_decoded_audio_bytes=4096),
                OperationContext(),
                modules,
            )
        self.assertEqual(caught.exception.code, FailureCode.INPUT_LIMIT)

    def test_real_pyav_decode_of_synthetic_wav_and_invalid_audio(self):
        import av

        modules = SimpleNamespace(av=av, numpy=numpy)
        decoded = _decode_audio(wav_bytes(), options(), OperationContext(), modules)
        self.assertEqual(decoded.dtype, numpy.float32)
        self.assertGreater(len(decoded), 0)
        with self.assertRaises(SpeechFailure) as caught:
            _decode_audio(b"not audio", options(), OperationContext(), modules)
        self.assertEqual(caught.exception.code, FailureCode.DECODE_FAILED)


class AdapterContractTests(unittest.TestCase):
    def test_translation_to_english_preserves_raw_text_and_rejects_other_targets(self):
        class FakeModel:
            def __init__(self):
                self.tasks = []

            def transcribe(self, _audio, **kwargs):
                self.tasks.append(kwargs["task"])
                text = "Hello there" if kwargs["task"] == "translate" else "Привет"
                return iter(
                    [SimpleNamespace(start=0.0, end=0.2, text=text)]
                ), SimpleNamespace(language="ru", language_probability=0.91)

        class Resampler:
            def __init__(self, **_kwargs):
                pass

            def resample(self, frame):
                return [] if frame is None else [frame]

        class Frame:
            def to_ndarray(self):
                return numpy.zeros((1, 3200), dtype=numpy.float32)

        class Container:
            streams = SimpleNamespace(audio=[object()])

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def decode(self, **_kwargs):
                return [Frame()]

        modules = SimpleNamespace(
            av=SimpleNamespace(
                open=lambda *_args, **_kwargs: Container(), AudioResampler=Resampler
            ),
            numpy=numpy,
        )
        model = FakeModel()
        loaded = FasterWhisperLoadedModel(
            model,
            ModelMetadata(ModelIdentity("whisper", "a" * 40), frozenset(), True, True),
            options(),
            modules,
        )
        translated = loaded.transcribe(
            TranscriptionRequest(wav_bytes(), "audio/wav", output_language="en"),
            OperationContext(),
        )
        self.assertEqual(translated.transcription, "Привет")
        self.assertEqual(translated.text, "Hello there")
        self.assertEqual(translated.output_language, "en")
        self.assertTrue(translated.translated)
        self.assertEqual(translated.language_probability, 0.91)
        self.assertEqual(model.tasks, ["transcribe", "translate"])
        with self.assertRaises(SpeechFailure) as caught:
            loaded.transcribe(
                TranscriptionRequest(wav_bytes(), "audio/wav", output_language="sv"),
                OperationContext(),
            )
        self.assertEqual(caught.exception.code, FailureCode.UNSUPPORTED_TRANSLATION)

    def test_cpu_load_uses_local_artifact_explicit_precision_and_threads(self):
        calls = {}

        class FakeWhisper:
            def __init__(self, path, **kwargs):
                calls["path"] = path
                calls.update(kwargs)
                self.model = SimpleNamespace(is_multilingual=True)

        modules = SimpleNamespace(
            ctranslate2=SimpleNamespace(
                get_supported_compute_types=lambda _device, _index=0: {"int8"},
                get_cuda_device_count=lambda: 0,
            ),
            faster_whisper=SimpleNamespace(WhisperModel=FakeWhisper),
        )
        backend = FasterWhisperBackend(options(), modules=modules)
        identity = ModelIdentity("whisper", "a" * 40)
        selection = ModelSelection(
            "small", identity, "small", ArtifactIdentity("b" * 64, "ct2")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tokenizer.json").write_text("{}")
            artifact = VerifiedArtifact(selection.artifact_identity, root)
            loaded = backend.load(
                selection, artifact, DeviceCapabilities("cpu", "0"), OperationContext()
            )
        self.assertEqual(calls["path"], str(root))
        self.assertEqual(calls["compute_type"], "int8")
        self.assertEqual(calls["cpu_threads"], 2)
        self.assertTrue(calls["local_files_only"])
        self.assertTrue(loaded.metadata.segment_timestamps)
        self.assertIsNotNone(loaded._model)
        loaded.unload(OperationContext())
        self.assertIsNone(loaded._model)

    def test_unsupported_cuda_compute_type_fails_without_cpu_fallback(self):
        modules = SimpleNamespace(
            ctranslate2=SimpleNamespace(
                get_supported_compute_types=lambda device, _index=0: {"int8"}
                if device == "cpu"
                else {"float32"},
                get_cuda_device_count=lambda: 1,
            ),
            faster_whisper=SimpleNamespace(WhisperModel=lambda *_args, **_kwargs: None),
        )
        backend = FasterWhisperBackend(options(), modules=modules)
        identity = ModelIdentity("whisper", "a" * 40)
        selection = ModelSelection(
            "small", identity, "small", ArtifactIdentity("b" * 64, "ct2")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tokenizer.json").write_text("{}")
            artifact = VerifiedArtifact(selection.artifact_identity, root)
            with self.assertRaises(SpeechFailure) as caught:
                backend.load(
                    selection,
                    artifact,
                    DeviceCapabilities("cuda", "0"),
                    OperationContext(),
                )
        self.assertEqual(caught.exception.code, FailureCode.DEVICE_UNAVAILABLE)

    def test_cuda_initialization_failure_is_typed_without_cpu_fallback(self):
        calls = []

        def construct(_path, **kwargs):
            calls.append(kwargs["device"])
            raise RuntimeError("CUDA initialization failed")

        modules = SimpleNamespace(
            ctranslate2=SimpleNamespace(
                get_supported_compute_types=lambda device, _index=0: {"float16"}
                if device == "cuda"
                else {"int8"},
                get_cuda_device_count=lambda: 1,
            ),
            faster_whisper=SimpleNamespace(WhisperModel=construct),
        )
        backend = FasterWhisperBackend(options(), modules=modules)
        identity = ModelIdentity("whisper", "a" * 40)
        selection = ModelSelection(
            "small", identity, "small", ArtifactIdentity("b" * 64, "ct2")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tokenizer.json").write_text("{}")
            with self.assertRaises(SpeechFailure) as caught:
                backend.load(
                    selection,
                    VerifiedArtifact(selection.artifact_identity, root),
                    DeviceCapabilities("cuda", "0"),
                    OperationContext(),
                )
        self.assertEqual(caught.exception.code, FailureCode.MODEL_LOAD_FAILED)
        self.assertEqual(calls, ["cuda"])

    def test_decoded_audio_allocation_failure_is_resource_exhausted(self):
        class FailingNumpy:
            @staticmethod
            def empty(*_args, **_kwargs):
                raise MemoryError("private allocator diagnostic")

        modules = SimpleNamespace(numpy=FailingNumpy())
        with self.assertRaises(SpeechFailure) as caught:
            _decode_audio(b"audio", options(), OperationContext(), modules)
        self.assertEqual(caught.exception.code, FailureCode.RESOURCE_EXHAUSTED)
        self.assertNotIn("private allocator", caught.exception.safe_message)

    def test_transcription_maps_language_timestamps_and_fatal_native_errors(self):
        class FakeModel:
            def __init__(self, *, fail=False):
                self.fail = fail

            def transcribe(self, audio, **kwargs):
                self.assertion = (audio.dtype, kwargs)
                if self.fail:
                    raise RuntimeError("native CUDA and local path diagnostic")
                return iter(
                    [SimpleNamespace(start=0.0, end=0.2, text=" hello")]
                ), SimpleNamespace(language="en")

        class Resampler:
            def __init__(self, **_kwargs):
                pass

            def resample(self, frame):
                return [] if frame is None else [frame]

        class Frame:
            def to_ndarray(self):
                return numpy.zeros((1, 3200), dtype=numpy.float32)

        class Container:
            streams = SimpleNamespace(audio=[object()])

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def decode(self, **_kwargs):
                return [Frame()]

        modules = SimpleNamespace(
            av=SimpleNamespace(
                open=lambda *_args, **_kwargs: Container(), AudioResampler=Resampler
            ),
            numpy=numpy,
        )
        metadata = ModelMetadata(
            ModelIdentity("whisper", "a" * 40), frozenset(), True, True
        )
        loaded = FasterWhisperLoadedModel(FakeModel(), metadata, options(), modules)
        result = loaded.transcribe(
            TranscriptionRequest(b"wav", "audio/wav", language="auto", timestamps=True),
            OperationContext(),
        )
        self.assertEqual(result.language, "en")
        self.assertEqual(result.text, " hello")
        self.assertEqual(result.segments[0].end_seconds, 0.2)
        self.assertTrue(loaded._model.assertion[1]["word_timestamps"] is False)

        failed = FasterWhisperLoadedModel(
            FakeModel(fail=True), metadata, options(), modules
        )
        with self.assertRaises(FatalBackendFailure) as caught:
            failed.transcribe(
                TranscriptionRequest(b"wav", "audio/wav"), OperationContext()
            )
        status, public = safe_error(caught.exception)
        self.assertEqual(status, 500)
        self.assertNotIn("native CUDA", public.message)

    def test_cpu_device_probe_does_not_import_nvidia_packages(self):
        devices = SystemDeviceProbe(cuda_enabled=False).discover(OperationContext())
        self.assertEqual([device.kind for device in devices], ["cpu"])
        self.assertIn("compute_type:int8", devices[0].features)


if __name__ == "__main__":
    unittest.main()
