"""Strict host-level settings shared by selected Compose services."""

from __future__ import annotations

import math
import re
from urllib.parse import urlparse
from pathlib import Path

import yaml

from services.stt.config import StrictLoader


PROFILE_FIELDS = {
    "schema_version",
    "project_name",
    "config_reader_gid",
    "gateway",
    "tts",
    "readiness",
}
RESOURCE_FIELDS = {"memory_limit", "cpu_limit", "pids_limit"}
MEMORY_PATTERN = re.compile(r"^[1-9][0-9]*(?:[kmgt](?:i)?b?)?$", re.IGNORECASE)
PROJECT_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
GO_DURATION_PATTERN = re.compile(r"^(?:[0-9]+(?:\.[0-9]+)?(?:ns|us|µs|ms|s|m|h))+$")
GATEWAY_FIELDS = {
    "listen_host",
    "listen_port",
    "max_header_bytes",
    "max_request_bytes",
    "read_timeout",
    "write_timeout",
    "idle_timeout",
    "shutdown_timeout",
}
GATEWAY_OPTIONAL_FIELDS = {
    "stt_url",
    "stt_timeout",
    "tts_url",
    "tts_timeout",
    "warmup_timeout",
    "groq_stt",
}
GROQ_STT_FIELDS = {"enabled", "capacity", "model", "api_key_env"}


def _fields(value, expected: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if extra:
            details.append("unsupported " + ", ".join(sorted(extra)))
        raise ValueError(f"{label} fields are invalid: {'; '.join(details)}")


def _duration_seconds(value: str) -> float:
    components = re.findall(r"([0-9]+(?:\.[0-9]+)?)(ns|us|µs|ms|s|m|h)", value)
    multiplier = {
        "ns": 1e-9,
        "us": 1e-6,
        "µs": 1e-6,
        "ms": 1e-3,
        "s": 1,
        "m": 60,
        "h": 3600,
    }
    return sum(float(number) * multiplier[unit] for number, unit in components)


def _resource_settings(value: dict, label: str) -> dict:
    _fields(value, RESOURCE_FIELDS, f"{label} resources")
    memory = value["memory_limit"]
    if not isinstance(memory, str) or not MEMORY_PATTERN.fullmatch(memory):
        raise ValueError(f"{label} memory_limit must be a positive Compose size")
    cpu = value["cpu_limit"]
    if type(cpu) not in (int, float) or not math.isfinite(cpu) or not 0 < cpu <= 64:
        raise ValueError(f"{label} cpu_limit must be in (0, 64]")
    pids = value["pids_limit"]
    if type(pids) is not int or not 1 <= pids <= 32768:
        raise ValueError(f"{label} pids_limit must be in 1..32768")
    return {**value, "cpu_limit": float(cpu)}


def load_service_profile(path: str | Path) -> dict:
    try:
        with Path(path).open(encoding="utf-8") as stream:
            profile = yaml.load(stream, Loader=StrictLoader)
    except (OSError, yaml.YAMLError, ValueError) as error:
        raise ValueError(
            "service deployment profile is unavailable or invalid"
        ) from error
    _fields(profile, PROFILE_FIELDS, "service deployment profile")
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ValueError("unsupported service deployment profile schema")
    if not isinstance(profile["project_name"], str) or not PROJECT_PATTERN.fullmatch(
        profile["project_name"]
    ):
        raise ValueError("service deployment project_name is invalid")
    reader_gid = profile["config_reader_gid"]
    if type(reader_gid) is not int or not 1 <= reader_gid <= 2147483647:
        raise ValueError("config_reader_gid must be in 1..2147483647")
    _fields(profile["gateway"], {"host_port", *RESOURCE_FIELDS}, "Gateway")
    host_port = profile["gateway"]["host_port"]
    if type(host_port) is not int or not 1024 <= host_port <= 65535:
        raise ValueError("Gateway loopback host_port must be in 1024..65535")
    profile["gateway"] = {
        **_resource_settings(
            {key: profile["gateway"][key] for key in RESOURCE_FIELDS}, "Gateway"
        ),
        "host_port": host_port,
    }
    profile["tts"] = _resource_settings(profile["tts"], "TTS")
    _fields(
        profile["readiness"],
        {"timeout_seconds", "poll_interval_seconds", "probe_timeout_seconds"},
        "readiness",
    )
    readiness = profile["readiness"]
    for key, low, high in (
        ("timeout_seconds", 1, 1800),
        ("poll_interval_seconds", 1, 60),
        ("probe_timeout_seconds", 1, 60),
    ):
        value = readiness[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"readiness {key} must be in {low}..{high}")
    if readiness["probe_timeout_seconds"] > readiness["poll_interval_seconds"]:
        raise ValueError("readiness probe timeout cannot exceed its poll interval")
    return profile


def load_gateway_config(path: str | Path) -> dict:
    try:
        with Path(path).open(encoding="utf-8") as stream:
            config = yaml.load(stream, Loader=StrictLoader)
    except (OSError, yaml.YAMLError, ValueError) as error:
        raise ValueError("Gateway configuration is unavailable or invalid") from error
    if not isinstance(config, dict):
        raise ValueError("Gateway configuration must be a mapping")
    missing = GATEWAY_FIELDS - set(config)
    extra = set(config) - GATEWAY_FIELDS - GATEWAY_OPTIONAL_FIELDS
    if missing or extra:
        parts = []
        if missing:
            parts.append("missing " + ", ".join(sorted(missing)))
        if extra:
            parts.append("unsupported " + ", ".join(sorted(extra)))
        raise ValueError(
            "Gateway configuration fields are invalid: " + "; ".join(parts)
        )
    if config["listen_host"] != "0.0.0.0":
        raise ValueError("Gateway listen_host must accept the isolated container port")
    port = config["listen_port"]
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Gateway listen_port must be in 1..65535")
    if type(config["max_header_bytes"]) is not int or config["max_header_bytes"] < 1:
        raise ValueError("Gateway max_header_bytes must be positive")
    request_limit = config["max_request_bytes"]
    if type(request_limit) is not int or not 1 <= request_limit <= 25 * 1024 * 1024:
        raise ValueError("Gateway max_request_bytes must be in 1..26214400")
    for key in ("read_timeout", "write_timeout", "idle_timeout", "shutdown_timeout"):
        value = config[key]
        if not isinstance(value, str) or not GO_DURATION_PATTERN.fullmatch(value):
            raise ValueError(f"Gateway {key} must be a positive Go duration")
        if _duration_seconds(value) <= 0:
            raise ValueError(f"Gateway {key} must be a positive Go duration")
    if "warmup_timeout" in config:
        value = config["warmup_timeout"]
        if (
            not isinstance(value, str)
            or not GO_DURATION_PATTERN.fullmatch(value)
            or not 1 <= _duration_seconds(value) <= 600
            or _duration_seconds(value) + 5 > _duration_seconds(config["write_timeout"])
        ):
            raise ValueError(
                "Gateway warmup_timeout must be from 1s to 10m and fit write_timeout"
            )
    if "stt_url" in config:
        worker = urlparse(
            config["stt_url"] if isinstance(config["stt_url"], str) else ""
        )
        if worker.scheme != "http" or not worker.netloc or worker.path not in ("", "/"):
            raise ValueError("Gateway stt_url must be an internal HTTP origin")
    if "stt_timeout" in config:
        value = config["stt_timeout"]
        if not isinstance(value, str) or not GO_DURATION_PATTERN.fullmatch(value):
            raise ValueError("Gateway stt_timeout must be a positive Go duration")
        if _duration_seconds(value) <= 0:
            raise ValueError("Gateway stt_timeout must be a positive Go duration")
    if "tts_url" in config:
        worker = urlparse(
            config["tts_url"] if isinstance(config["tts_url"], str) else ""
        )
        if worker.scheme != "http" or not worker.netloc or worker.path not in ("", "/"):
            raise ValueError("Gateway tts_url must be an internal HTTP origin")
    if "tts_timeout" in config:
        value = config["tts_timeout"]
        if (
            not isinstance(value, str)
            or not GO_DURATION_PATTERN.fullmatch(value)
            or not 0 < _duration_seconds(value) <= 600
        ):
            raise ValueError(
                "Gateway tts_timeout must be a positive Go duration no greater than 10m"
            )
    if "groq_stt" in config:
        groq = config["groq_stt"]
        if not isinstance(groq, dict) or set(groq) - GROQ_STT_FIELDS:
            raise ValueError("Gateway groq_stt configuration fields are invalid")
        if "enabled" in groq and type(groq["enabled"]) is not bool:
            raise ValueError("Gateway groq_stt.enabled must be boolean")
        capacity = groq.get("capacity", 2)
        if type(capacity) is not int or not 1 <= capacity <= 2:
            raise ValueError("Gateway groq_stt.capacity must be 1 or 2")
        model = groq.get("model", "whisper-large-v3-turbo")
        if model not in {"whisper-large-v3", "whisper-large-v3-turbo"}:
            raise ValueError("Gateway groq_stt.model is unsupported")
        api_key_env = groq.get("api_key_env", "GROQ_STT_API_KEY")
        if not isinstance(api_key_env, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]{0,127}", api_key_env
        ):
            raise ValueError("Gateway groq_stt.api_key_env is invalid")
    return config
