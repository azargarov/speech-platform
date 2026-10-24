"""Serialized lazy model lifecycle; native inference is never cancelled mid-call."""

from __future__ import annotations

import gc
import hashlib
import json
import stat
import threading
import time
from pathlib import Path
from typing import Callable

from services.tts.audio import InvalidAudio, compose_wav, pcm16_frames
from services.tts.audio_processing import AudioProcessingError, process_gently
from services.tts.ssml import (
    SSMLValidationError,
    SilenceSegment,
    parse_ssml,
)


class TTSFailure(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class PermanentModelError(Exception):
    """A validated, non-resource failure in the configured model artifacts."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


class SynthesisContext:
    """One ordinary synthesis budget; checkpoints never interrupt native calls."""

    def __init__(self, deadline, disconnected=lambda: False, clock=None):
        self.deadline = deadline
        self.disconnected = disconnected
        self.clock = clock or time.monotonic

    def check(self):
        if self.clock() >= self.deadline:
            raise TTSFailure(
                "deadline_exceeded", "speech request deadline exceeded", 504
            )
        if self.disconnected():
            raise TTSFailure("request_cancelled", "speech request was cancelled", 504)


class ModelLifecycle:
    def __init__(
        self,
        config: dict,
        model_factory: Callable[[SynthesisContext | None], object],
    ):
        self.config = config
        self.model_factory = model_factory
        self._condition = threading.Condition()
        self._model = None
        self._state = "unloaded"
        self._active = False
        self._stopping = False
        self._last_used = time.monotonic()
        self._permanent_failure: tuple[str, str] | None = None
        self._unloader = threading.Thread(
            target=self._idle_loop, name="tts-idle-unloader", daemon=True
        )
        self._unloader.start()

    def state(self) -> dict:
        with self._condition:
            state = {"model_state": self._state, "inference_active": self._active}
            if self._permanent_failure is not None:
                state["failure_category"] = self._permanent_failure[0]
            return state

    def ready(self) -> bool:
        with self._condition:
            return not self._stopping and self._permanent_failure is None

    def readiness(self) -> dict:
        """Return sanitized readiness details without initializing the model."""
        with self._condition:
            if self._stopping:
                return {
                    "ready": False,
                    "code": "worker_draining",
                    "message": "TTS worker is shutting down",
                }
            if self._permanent_failure is not None:
                code, message = self._permanent_failure
                return {"ready": False, "code": code, "message": message}
            return {"ready": True}

    def warmup(self) -> None:
        self._with_model(lambda model: None)

    def synthesize(
        self,
        text: str,
        language: str,
        mode: str,
        input_format: str = "text",
        audio_processing: str = "none",
        *,
        context: SynthesisContext | None = None,
    ) -> tuple[bytes, str]:
        if audio_processing not in {"none", "gentle"}:
            raise TTSFailure(
                "invalid_audio_processing",
                "audio_processing must be none or gentle",
                400,
            )
        if mode not in {
            "quality",
            "fast",
            "auto",
            "high_quality",
            "extra_high_quality",
        }:
            raise TTSFailure(
                "invalid_mode",
                "mode must be quality, fast, auto, high_quality, or extra_high_quality",
                400,
            )
        if context is not None:
            context.check()
        steps = mode_timesteps(mode)
        if input_format == "text":
            result = self._with_model(
                lambda model: self._generate_segment(
                    model, text, language, steps, context
                ),
                context,
            )
        elif input_format == "ssml":
            try:
                segments = parse_ssml(text, self.config)
            except SSMLValidationError as error:
                raise TTSFailure("invalid_ssml", str(error), 400) from error
            result = self._with_model(
                lambda model: self._generate_ssml(model, segments, steps, context),
                context,
            )
        else:
            raise TTSFailure(
                "invalid_input_format", "input_format must be text or ssml", 400
            )
        if audio_processing == "gentle":
            try:
                if context is not None:
                    context.check()
                    processed = process_gently(
                        result[0],
                        self.config,
                        deadline=context.deadline,
                        check=context.check,
                    )
                    context.check()
                else:
                    processed = process_gently(result[0], self.config)
                return processed, result[1]
            except AudioProcessingError as error:
                if context is not None:
                    context.check()
                raise TTSFailure(error.code, error.message, error.status) from error
        return result

    def _generate_ssml(
        self, model, segments, steps: int, context=None
    ) -> tuple[bytes, str]:
        pieces = []
        composed_frame_bytes = 0
        for segment in segments:
            if context is not None:
                context.check()
            if isinstance(segment, SilenceSegment):
                silence_bytes = segment.duration_ms * 48 * 2
                if (
                    composed_frame_bytes + silence_bytes + 44
                    > self.config["max_output_audio_bytes"]
                ):
                    raise TTSFailure(
                        "output_too_large",
                        "composed audio exceeds the configured size limit",
                        500,
                    )
                pieces.append(b"\x00" * silence_bytes)
                composed_frame_bytes += silence_bytes
                continue
            audio, content_type = self._generate_segment(
                model, segment.text, segment.language, steps, context
            )
            if context is not None:
                context.check()
            if (
                content_type != "audio/wav"
                or len(audio) > self.config["max_output_audio_bytes"]
            ):
                raise TTSFailure("inference_failed", "generated audio is invalid", 500)
            if (
                composed_frame_bytes + len(audio)
                > self.config["max_output_audio_bytes"]
            ):
                raise TTSFailure(
                    "output_too_large",
                    "composed audio exceeds the configured size limit",
                    500,
                )
            try:
                frames = pcm16_frames(audio)
                pieces.append(frames)
                composed_frame_bytes += len(frames)
                if composed_frame_bytes + 44 > self.config["max_output_audio_bytes"]:
                    raise InvalidAudio("composed audio exceeds configured size")
            except InvalidAudio as error:
                raise TTSFailure(
                    "inference_failed", "generated audio is invalid", 500
                ) from error
        try:
            return compose_wav(
                pieces, self.config["max_output_audio_bytes"]
            ), "audio/wav"
        except InvalidAudio as error:
            raise TTSFailure(
                "inference_failed", "generated audio is invalid", 500
            ) from error

    def _generate_segment(self, model, text, language, steps, context):
        if context is None:
            return self._generate(model, text, language, steps)
        return self._generate(model, text, language, steps, context=context)

    def _generate(
        self, model, text: str, language: str, steps: int, *, context=None
    ) -> tuple[bytes, str]:
        hints = {
            "en": "Speak in English with clear, neutral pronunciation.",
            "ru": "Speak in Russian with clear, neutral pronunciation.",
            "sv": "Speak in Swedish with clear, neutral pronunciation.",
        }
        prompt = language_instruction(text, language, hints)
        try:
            import io
            import soundfile as sf
            import numpy as np

            import torch

            with torch.inference_mode():
                if context is not None:
                    context.check()
                audio = model.generate(
                    text=prompt,
                    retry_badcase=False,
                    normalize=False,
                    inference_timesteps=steps,
                )
            if context is not None:
                context.check()
            if audio.size == 0 or not np.isfinite(audio).all():
                raise TTSFailure("inference_failed", "generated audio is invalid", 500)
            output = io.BytesIO()
            sf.write(
                output,
                audio,
                int(model.tts_model.sample_rate),
                format="WAV",
                subtype="PCM_16",
            )
            generated = output.getvalue()
            if len(generated) > self.config["max_output_audio_bytes"]:
                raise TTSFailure(
                    "output_too_large",
                    "generated audio exceeds the configured size limit",
                    500,
                )
            return generated, "audio/wav"
        except TTSFailure:
            raise
        except Exception as error:
            if _is_oom(error):
                raise TTSFailure(
                    "resource_exhausted",
                    "GPU resources are temporarily unavailable",
                    503,
                ) from error
            raise TTSFailure(
                "inference_failed", "speech generation failed", 500
            ) from error

    def _with_model(self, operation, context=None):
        with self._condition:
            while self._active and not self._stopping:
                if context is not None:
                    context.check()
                self._condition.wait(
                    min(0.05, max(0, context.deadline - context.clock()))
                    if context is not None
                    else 0.05
                )
            if context is not None:
                context.check()
            if self._stopping:
                raise TTSFailure("worker_draining", "worker is shutting down", 503)
            self._active = True
            self._state = "loading" if self._model is None else "loaded"
        try:
            if self._model is None:
                if context is not None:
                    context.check()
                try:
                    self._model = self.model_factory(context)
                except TTSFailure:
                    with self._condition:
                        self._state = "unloaded"
                    raise
                except PermanentModelError as error:
                    with self._condition:
                        self._permanent_failure = (error.category, error.message)
                        self._state = "unloaded"
                    raise TTSFailure(error.category, error.message, 503) from error
                except Exception as error:
                    with self._condition:
                        # A retry that reaches a transient failure proves the
                        # previous permanent condition is no longer established.
                        self._permanent_failure = None
                        self._state = "unloaded"
                    if _is_oom(error):
                        raise TTSFailure(
                            "resource_exhausted",
                            "GPU resources are temporarily unavailable",
                            503,
                        ) from error
                    raise TTSFailure(
                        "model_load_failed", "TTS model could not be loaded", 503
                    ) from error
                with self._condition:
                    self._state = "loaded"
                    self._permanent_failure = None
            if context is not None:
                context.check()
            result = operation(self._model)
            if context is not None:
                context.check()
            return result
        except TTSFailure as error:
            if error.code == "resource_exhausted":
                self._unload_locked()
            if context is not None:
                context.check()
            raise
        finally:
            with self._condition:
                self._active = False
                self._last_used = time.monotonic()
                if self._model is not None:
                    self._state = "loaded"
                elif not self._stopping:
                    self._state = "unloaded"
                self._condition.notify_all()

    def _unload_locked(self) -> None:
        model, self._model = self._model, None
        del model
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        self._state = "unloaded"

    def unload(self) -> bool:
        with self._condition:
            if self._active or self._model is None:
                return False
            self._unload_locked()
            return True

    def stop(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            self._stopping = True
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            self._unload_locked()
        self._unloader.join(timeout=max(0, deadline - time.monotonic()))
        return not self._unloader.is_alive()

    def _idle_loop(self) -> None:
        interval = self.config["idle_unload_seconds"]
        if interval <= 0:
            return
        while True:
            time.sleep(min(interval, 1.0))
            with self._condition:
                if self._stopping:
                    return
                if (
                    self._model is not None
                    and not self._active
                    and time.monotonic() - self._last_used >= interval
                ):
                    self._unload_locked()


def _is_oom(error: Exception) -> bool:
    return (
        "out of memory" in str(error).lower()
        or "cuda error: out of memory" in str(error).lower()
    )


def mode_timesteps(mode: str) -> int:
    if mode == "fast":
        return 8
    if mode == "high_quality":
        return 16
    if mode == "extra_high_quality":
        return 32
    if mode in {"quality", "auto"}:
        return 10
    raise TTSFailure(
        "invalid_mode",
        "mode must be quality, fast, auto, high_quality, or extra_high_quality",
        400,
    )


def language_instruction(text: str, language: str, instructions: dict[str, str]) -> str:
    if language == "auto":
        return text
    return f"({instructions[language]}){text}"


def _file_sha256(path: Path, context: SynthesisContext | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            if context is not None:
                context.check()
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    if context is not None:
        context.check()
    return digest.hexdigest()


def _file_metadata(path: Path) -> tuple[int, int, int, int, int]:
    metadata = path.lstat()
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def vox_model_factory(config: dict):
    verified_metadata = None

    def load(context: SynthesisContext | None = None):
        nonlocal verified_metadata
        path = Path(config["model_path"])
        manifest_path = path.parent / "manifest.yaml"
        try:
            model_stat = path.lstat()
            manifest_stat = manifest_path.lstat()
        except (FileNotFoundError, NotADirectoryError) as error:
            raise PermanentModelError(
                "model_artifact_unavailable",
                "configured TTS model artifacts are unavailable; verify the model mount and files",
            ) from error
        if (
            stat.S_ISLNK(model_stat.st_mode)
            or not stat.S_ISDIR(model_stat.st_mode)
            or stat.S_ISLNK(manifest_stat.st_mode)
            or not stat.S_ISREG(manifest_stat.st_mode)
        ):
            raise PermanentModelError(
                "model_artifact_unavailable",
                "configured TTS model artifacts are unavailable; verify the model mount and files",
            )
        import yaml

        from services.worker.server import StrictLoader

        try:
            if context is not None:
                context.check()
            manifest = yaml.load(manifest_path.read_text(), Loader=StrictLoader)
            digest = hashlib.sha256(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if not isinstance(manifest, dict) or (
                digest != config["model_manifest_sha256"]
                or manifest.get("model", {}).get("revision") != config["model_revision"]
            ):
                raise ValueError("manifest identity mismatch")
            entries = manifest.get("files", [])
            if not isinstance(entries, list) or not entries:
                raise ValueError("manifest file list is invalid")
            expected = {}
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {
                    "path",
                    "size_bytes",
                    "sha256",
                }:
                    raise ValueError("manifest file entry is invalid")
                name = entry["path"]
                if (
                    not isinstance(name, str)
                    or not name
                    or Path(name).name != name
                    or "\\" in name
                    or name in expected
                ):
                    raise ValueError("manifest file path is invalid")
                expected[name] = entry
            actual = {}
            for child in path.iterdir():
                child_stat = child.lstat()
                if stat.S_ISLNK(child_stat.st_mode) or not stat.S_ISREG(
                    child_stat.st_mode
                ):
                    raise ValueError("unsupported artifact entry")
                actual[child.name] = (
                    child,
                    (
                        child_stat.st_dev,
                        child_stat.st_ino,
                        child_stat.st_size,
                        child_stat.st_mtime_ns,
                        child_stat.st_ctime_ns,
                    ),
                )
            if (
                not expected
                or set(actual) != set(expected)
                or "model.safetensors" not in expected
            ):
                raise ValueError("artifact files do not match the manifest")
            manifest_metadata = _file_metadata(manifest_path)
            metadata = (
                manifest_metadata,
                tuple((name, actual[name][1]) for name in sorted(actual)),
            )
            sizes_match = all(
                type(expected[name]["size_bytes"]) is int
                and actual[name][1][2] == expected[name]["size_bytes"]
                for name in actual
            )
            if verified_metadata != metadata:
                hashes = {}
                for name in sorted(actual):
                    child, _file_stat = actual[name]
                    hashes[name] = _file_sha256(child, context)

                after_metadata = (
                    _file_metadata(manifest_path),
                    tuple(
                        (name, _file_metadata(actual[name][0]))
                        for name in sorted(actual)
                    ),
                )
                if after_metadata != metadata:
                    raise ValueError("artifact metadata changed during verification")

                for name in actual:
                    entry = expected[name]
                    if (
                        type(entry["size_bytes"]) is not int
                        or actual[name][1][2] != entry["size_bytes"]
                    ):
                        raise ValueError("artifact file size mismatch")
                    if hashes[name] != entry["sha256"]:
                        raise ValueError("artifact file digest mismatch")
                if context is not None:
                    context.check()
                verified_metadata = metadata
            elif not sizes_match:
                # Keep the size check explicit on every load, even on a cache hit.
                raise ValueError("artifact file size mismatch")
        except TTSFailure:
            raise
        except OSError:
            # Filesystem I/O may recover; do not latch it as artifact corruption.
            raise
        except Exception as error:
            raise PermanentModelError(
                "model_artifact_invalid",
                "configured TTS model artifacts are invalid; restore the pinned model files and manifest",
            ) from error
        import torch
        from voxcpm import VoxCPM

        if context is not None:
            context.check()
        if not torch.cuda.is_available():
            raise PermanentModelError(
                "cuda_unavailable",
                "TTS CUDA is unavailable; verify container GPU access and driver configuration",
            )
        free_mib, _total_mib = torch.cuda.mem_get_info()
        if free_mib < config["min_free_vram_mib"] * 1024 * 1024:
            raise RuntimeError(
                "GPU out of memory: insufficient free VRAM before model load"
            )
        torch.cuda.set_per_process_memory_fraction(config["cuda_memory_fraction"])
        torch.set_num_threads(4)
        if context is not None:
            context.check()
        return VoxCPM.from_pretrained(
            str(path),
            load_denoiser=False,
            local_files_only=True,
            optimize=False,
            device="cuda",
        )

    return load
