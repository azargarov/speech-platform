"""Bounded, fixed-policy FFmpeg mastering for complete TTS WAV programs."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from services.tts.audio import InvalidAudio, compose_wav, pcm16_frames


_COMPRESSOR = (
    "acompressor=threshold=0.125:ratio=1.5:attack=20:release=250:makeup=1.25:knee=2.828"
)
_LOUDNORM_ANALYZE = f"{_COMPRESSOR},loudnorm=I=-18:TP=-2.5:LRA=11:print_format=json"
_LOUDNORM_OUTPUT = (
    f"{_COMPRESSOR},loudnorm=I=-18:TP=-2.5:LRA=11:"
    "measured_I={input_i:.3f}:measured_TP={input_tp:.3f}:"
    "measured_LRA={input_lra:.3f}:measured_thresh={input_thresh:.3f}:"
    "offset={target_offset:.3f}:linear=true:print_format=none,"
    "alimiter=limit=0.75:level=false:attack=5:release=50:latency=true"
)
_JSON_BLOCK = re.compile(r"\{\s*\"input_i\".*?\}", re.DOTALL)
_NEAR_SILENT_PEAK = 64  # 16-bit PCM peak below approximately -54 dBFS.
_NEAR_SILENT_LUFS = -45.0
_MAX_DURATION_DELTA_FRAMES = 480  # 10 ms at the worker's fixed 48 kHz format.


class AudioProcessingError(Exception):
    def __init__(self, code: str, message: str, status: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _measurements(stderr: bytes) -> dict[str, float] | None:
    matches = list(_JSON_BLOCK.finditer(stderr.decode("utf-8", errors="replace")))
    if not matches:
        return None
    try:
        values = json.loads(matches[-1].group())
        names = (
            "input_i",
            "input_tp",
            "input_lra",
            "input_thresh",
            "target_offset",
        )
        parsed = {name: float(values[name]) for name in names}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not all(math.isfinite(value) for value in parsed.values()):
        return None
    if not -100 <= parsed["input_i"] <= 0:
        return None
    if not -100 <= parsed["input_tp"] <= 20:
        return None
    if not 0 <= parsed["input_lra"] <= 100:
        return None
    if not -100 <= parsed["input_thresh"] <= 20:
        return None
    if not -100 <= parsed["target_offset"] <= 100:
        return None
    return parsed


def _run(args: list[str], remaining: float, *, capture_stderr: bool) -> bytes:
    try:
        result = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture_stderr else subprocess.DEVNULL,
            check=False,
            timeout=remaining,
        )
    except subprocess.TimeoutExpired as error:
        raise AudioProcessingError(
            "audio_processing_timeout",
            "audio processing exceeded its time limit",
            504,
        ) from error
    except OSError as error:
        raise AudioProcessingError(
            "audio_processing_unavailable",
            "audio processing is unavailable",
            503,
        ) from error
    if result.returncode != 0:
        raise AudioProcessingError(
            "audio_processing_failed", "audio processing failed", 500
        )
    return result.stderr or b""


def process_gently(payload: bytes, config: dict, *, deadline=None, check=None) -> bytes:
    """Master a complete PCM16 WAV, retaining bounded duration and silence."""
    max_bytes = config["max_output_audio_bytes"]
    if len(payload) > max_bytes:
        raise AudioProcessingError(
            "output_too_large", "audio exceeds the configured size limit", 500
        )
    try:
        frames = pcm16_frames(payload)
    except InvalidAudio as error:
        raise AudioProcessingError(
            "audio_processing_failed", "generated audio is invalid", 500
        ) from error
    samples = np.frombuffer(frames, dtype="<i2")
    if (
        samples.size == 0
        or max(int(samples.max()), abs(int(samples.min()))) < _NEAR_SILENT_PEAK
    ):
        return payload

    executable = shutil.which("ffmpeg")
    if executable is None:
        raise AudioProcessingError(
            "audio_processing_unavailable",
            "audio processing is unavailable",
            503,
        )

    timeout = config["audio_processing_timeout_seconds"]
    processing_deadline = time.monotonic() + timeout
    if deadline is not None:
        processing_deadline = min(processing_deadline, deadline)

    def remaining():
        if check is not None:
            check()
        budget = processing_deadline - time.monotonic()
        if budget <= 0:
            raise AudioProcessingError(
                "audio_processing_timeout",
                "audio processing exceeded its time limit",
                504,
            )
        return budget

    with tempfile.TemporaryDirectory(prefix="speech-tts-audio-") as temp_dir:
        source = Path(temp_dir) / "source.wav"
        output = Path(temp_dir) / "processed.wav"
        try:
            source.write_bytes(payload)
        except OSError as error:
            raise AudioProcessingError(
                "audio_processing_failed", "audio processing failed", 500
            ) from error

        analyze_args = [
            executable,
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-v",
            "info",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-af",
            _LOUDNORM_ANALYZE,
            "-f",
            "null",
            "-",
        ]
        analysis = _run(analyze_args, remaining(), capture_stderr=True)
        measured = _measurements(analysis)
        if measured is None:
            raise AudioProcessingError(
                "audio_processing_failed", "audio analysis failed", 500
            )
        if measured["input_i"] <= _NEAR_SILENT_LUFS:
            return payload

        filter_graph = _LOUDNORM_OUTPUT.format(**measured)
        output_args = [
            executable,
            "-nostdin",
            "-hide_banner",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-af",
            filter_graph,
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            "-fs",
            str(max_bytes),
            "-f",
            "wav",
            str(output),
        ]
        _run(output_args, remaining(), capture_stderr=False)
        try:
            result = output.read_bytes()
            output_frames = pcm16_frames(result)
        except (OSError, ValueError) as error:
            raise AudioProcessingError(
                "audio_processing_failed", "processed audio is invalid", 500
            ) from error
        if output.stat().st_size >= max_bytes:
            raise AudioProcessingError(
                "output_too_large",
                "processed audio exceeds the configured size limit",
                500,
            )
        if abs(len(output_frames) - len(frames)) > _MAX_DURATION_DELTA_FRAMES:
            raise AudioProcessingError(
                "audio_processing_failed",
                "processed audio duration changed unexpectedly",
                500,
            )
        processed_samples = np.frombuffer(output_frames, dtype="<i2").copy()
        original_samples = np.frombuffer(frames, dtype="<i2")
        processed_samples[original_samples == 0] = 0
        try:
            restored = compose_wav(
                [processed_samples.astype("<i2", copy=False).tobytes()], max_bytes
            )
        except InvalidAudio as error:
            raise AudioProcessingError(
                "audio_processing_failed", "processed audio is invalid", 500
            ) from error
        return restored
