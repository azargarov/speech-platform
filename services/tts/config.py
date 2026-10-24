"""Strict configuration for the VoxCPM2 worker."""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from services.worker.server import StrictLoader, valid_host


def load_config(path: str | Path) -> dict:
    data = yaml.load(Path(path).read_text(), Loader=StrictLoader)
    if isinstance(data, dict):
        data.setdefault("request_timeout_seconds", 600)
    fields = {
        "kind",
        "listen_host",
        "listen_port",
        "socket_timeout_seconds",
        "request_timeout_seconds",
        "audio_processing_timeout_seconds",
        "poll_interval_seconds",
        "model_path",
        "model_revision",
        "model_manifest_sha256",
        "idle_unload_seconds",
        "max_text_characters",
        "max_request_bytes",
        "max_ssml_bytes",
        "max_ssml_segments",
        "max_ssml_elements",
        "max_ssml_nesting_depth",
        "max_ssml_break_ms",
        "max_ssml_total_silence_ms",
        "ssml_estimated_characters_per_second",
        "ssml_segment_overhead_seconds",
        "max_output_audio_bytes",
        "min_free_vram_mib",
        "shutdown_timeout_seconds",
        "cuda_memory_fraction",
    }
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("configuration fields must match required TTS schema")
    if (
        data["kind"] != "tts"
        or not isinstance(data["listen_host"], str)
        or not valid_host(data["listen_host"])
    ):
        raise ValueError("invalid TTS worker identity or listener")
    for name, low, high in (
        ("listen_port", 1, 65535),
        ("socket_timeout_seconds", 1, 86400),
        ("request_timeout_seconds", 1, 86400),
        ("audio_processing_timeout_seconds", 1, 60),
        ("max_text_characters", 1, 10000),
        ("max_request_bytes", 1, 26214400),
        ("max_ssml_bytes", 1, 49152),
        ("max_ssml_segments", 1, 256),
        ("max_ssml_elements", 1, 1024),
        ("max_ssml_nesting_depth", 1, 32),
        ("max_ssml_break_ms", 1, 60000),
        ("max_ssml_total_silence_ms", 1, 600000),
        ("max_output_audio_bytes", 1024, 67108864),
        ("min_free_vram_mib", 0, 15360),
        ("shutdown_timeout_seconds", 1, 600),
    ):
        value = data[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{name} is outside its allowed range")
    interval = data["poll_interval_seconds"]
    idle = data["idle_unload_seconds"]
    if (
        type(interval) not in (int, float)
        or not math.isfinite(interval)
        or not 0 < interval <= 60
    ):
        raise ValueError("poll_interval_seconds must be greater than 0 and at most 60")
    if (
        type(idle) not in (int, float)
        or not math.isfinite(idle)
        or not 0 <= idle <= 86400
    ):
        raise ValueError("idle_unload_seconds must be in 0..86400")
    for name in (
        "ssml_estimated_characters_per_second",
        "ssml_segment_overhead_seconds",
    ):
        value = data[name]
        high = 30 if name == "ssml_estimated_characters_per_second" else 10
        low = 5 if name == "ssml_estimated_characters_per_second" else 0.1
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError(f"{name} is outside its allowed range")
    if (
        not isinstance(data["model_path"], str)
        or not Path(data["model_path"]).is_absolute()
    ):
        raise ValueError("model_path must be an absolute path")
    if not isinstance(data["model_revision"], str) or not data["model_revision"]:
        raise ValueError("model_revision is required")
    digest = data["model_manifest_sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("model_manifest_sha256 must be lowercase SHA-256")
    fraction = data["cuda_memory_fraction"]
    if (
        type(fraction) not in (int, float)
        or not math.isfinite(fraction)
        or not 0.1 <= fraction <= 0.9
    ):
        raise ValueError("cuda_memory_fraction must be in 0.1..0.9")
    return data
