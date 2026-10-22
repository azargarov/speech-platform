"""Composition helpers for bounded mono PCM16 48 kHz WAV responses."""

from __future__ import annotations

import io
import wave


class InvalidAudio(ValueError):
    """Generated segment does not match the composition format."""


def pcm16_frames(payload: bytes) -> bytes:
    try:
        with wave.open(io.BytesIO(payload), "rb") as wav:
            if (
                wav.getnchannels() != 1
                or wav.getsampwidth() != 2
                or wav.getframerate() != 48000
                or wav.getcomptype() != "NONE"
            ):
                raise InvalidAudio("generated audio format is unsupported")
            frames = wav.readframes(wav.getnframes())
            if len(frames) != wav.getnframes() * 2:
                raise InvalidAudio("generated WAV frame data is incomplete")
            return frames
    except (wave.Error, EOFError, OSError) as error:
        raise InvalidAudio("generated WAV is malformed") from error


def compose_wav(pieces: list[bytes], max_bytes: int) -> bytes:
    frame_count = sum(len(piece) // 2 for piece in pieces)
    if any(len(piece) % 2 for piece in pieces):
        raise InvalidAudio("PCM16 data has an incomplete frame")
    if frame_count * 2 + 44 > max_bytes:
        raise InvalidAudio("composed audio exceeds the configured size limit")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b"".join(pieces))
    result = output.getvalue()
    if len(result) > max_bytes:
        raise InvalidAudio("composed audio exceeds the configured size limit")
    return result
