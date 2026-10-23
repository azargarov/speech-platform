"""Serialized lazy model lifecycle; native inference is never cancelled mid-call."""

from __future__ import annotations

import gc
import hashlib
import json
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


class ModelLifecycle:
    def __init__(self, config: dict, model_factory: Callable[[], object]):
        self.config = config
        self.model_factory = model_factory
        self._condition = threading.Condition()
        self._model = None
        self._state = "unloaded"
        self._active = False
        self._stopping = False
        self._last_used = time.monotonic()
        self._load_error = False
        self._unloader = threading.Thread(
            target=self._idle_loop, name="tts-idle-unloader", daemon=True
        )
        self._unloader.start()

    def state(self) -> dict:
        with self._condition:
            return {"model_state": self._state, "inference_active": self._active}

    def ready(self) -> bool:
        with self._condition:
            return not self._stopping

    def warmup(self) -> None:
        self._with_model(lambda model: None)

    def synthesize(
        self,
        text: str,
        language: str,
        mode: str,
        input_format: str = "text",
        audio_processing: str = "none",
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
        steps = mode_timesteps(mode)
        if input_format == "text":
            result = self._with_model(
                lambda model: self._generate(model, text, language, steps)
            )
        elif input_format == "ssml":
            try:
                segments = parse_ssml(text, self.config)
            except SSMLValidationError as error:
                raise TTSFailure("invalid_ssml", str(error), 400) from error
            result = self._with_model(
                lambda model: self._generate_ssml(model, segments, steps)
            )
        else:
            raise TTSFailure(
                "invalid_input_format", "input_format must be text or ssml", 400
            )
        if audio_processing == "gentle":
            try:
                return process_gently(result[0], self.config), result[1]
            except AudioProcessingError as error:
                raise TTSFailure(error.code, error.message, error.status) from error
        return result

    def _generate_ssml(self, model, segments, steps: int) -> tuple[bytes, str]:
        pieces = []
        composed_frame_bytes = 0
        for segment in segments:
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
            audio, content_type = self._generate(
                model, segment.text, segment.language, steps
            )
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

    def _generate(
        self, model, text: str, language: str, steps: int
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
                audio = model.generate(
                    text=prompt,
                    retry_badcase=False,
                    normalize=False,
                    inference_timesteps=steps,
                )
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

    def _with_model(self, operation):
        with self._condition:
            while self._active and not self._stopping:
                self._condition.wait()
            if self._stopping:
                raise TTSFailure("worker_draining", "worker is shutting down", 503)
            self._active = True
            self._state = "loading" if self._model is None else "loaded"
        try:
            if self._model is None:
                try:
                    self._model = self.model_factory()
                except Exception as error:
                    with self._condition:
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
                    self._load_error = False
            result = operation(self._model)
            return result
        except TTSFailure as error:
            if error.code == "resource_exhausted":
                self._unload_locked()
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


def vox_model_factory(config: dict):
    def load():
        path = Path(config["model_path"])
        manifest_path = path.parent / "manifest.yaml"
        if (
            path.is_symlink()
            or not path.is_dir()
            or manifest_path.is_symlink()
            or not manifest_path.is_file()
        ):
            raise RuntimeError("model artifact is unavailable")
        import yaml

        from services.worker.server import StrictLoader

        manifest = yaml.load(manifest_path.read_text(), Loader=StrictLoader)
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if (
            digest != config["model_manifest_sha256"]
            or manifest.get("model", {}).get("revision") != config["model_revision"]
        ):
            raise RuntimeError("model artifact identity mismatch")
        expected = {
            entry["path"]: entry["size_bytes"] for entry in manifest.get("files", [])
        }
        actual = {}
        for child in path.iterdir():
            if child.is_symlink() or not child.is_file():
                raise RuntimeError("model artifact contains an unsupported entry")
            actual[child.name] = child.stat().st_size
        if not expected or actual != expected or "model.safetensors" not in expected:
            raise RuntimeError("model artifact files do not match the manifest")
        import torch
        from voxcpm import VoxCPM

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for the configured TTS worker")
        free_mib, _total_mib = torch.cuda.mem_get_info()
        if free_mib < config["min_free_vram_mib"] * 1024 * 1024:
            raise RuntimeError(
                "GPU out of memory: insufficient free VRAM before model load"
            )
        torch.cuda.set_per_process_memory_fraction(config["cuda_memory_fraction"])
        torch.set_num_threads(4)
        return VoxCPM.from_pretrained(
            str(path),
            load_denoiser=False,
            local_files_only=True,
            optimize=False,
            device="cuda",
        )

    return load
