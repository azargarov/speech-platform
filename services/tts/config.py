"""Strict configuration for the VoxCPM2 worker."""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from services.worker.server import StrictLoader, valid_host


def load_config(path: str | Path) -> dict:
    data = yaml.load(Path(path).read_text(), Loader=StrictLoader)
    fields = {
        "kind",
        "listen_host",
        "listen_port",
        "socket_timeout_seconds",
        "poll_interval_seconds",
        "model_path",
        "model_revision",
        "model_manifest_sha256",
        "idle_unload_seconds",
        "max_text_characters",
        "max_request_bytes",
        "min_free_vram_mib",
        "shutdown_timeout_seconds",
        "cuda_memory_fraction",
        "fast_mode_enabled",
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
        ("max_text_characters", 1, 10000),
        ("max_request_bytes", 1, 26214400),
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
    if type(data["fast_mode_enabled"]) is not bool:
        raise ValueError("fast_mode_enabled must be boolean")
    fraction = data["cuda_memory_fraction"]
    if (
        type(fraction) not in (int, float)
        or not math.isfinite(fraction)
        or not 0.1 <= fraction <= 0.9
    ):
        raise ValueError("cuda_memory_fraction must be in 0.1..0.9")
    return data
