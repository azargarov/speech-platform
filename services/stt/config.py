"""Strict, versioned STT application and deployment configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from services.stt.domain import (
    ArtifactIdentity,
    ModelIdentity,
    ModelSelection,
    SpeechFailure,
    FailureCode,
)

APPLICATION_SCHEMA_VERSIONS = frozenset({2, 3})
DEPLOYMENT_SCHEMA_VERSIONS = frozenset({1, 2})


class StrictLoader(yaml.SafeLoader):
    pass


def _mapping(loader: StrictLoader, node: yaml.MappingNode, deep: bool = False):
    values = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in values:
            raise ValueError("duplicate configuration field")
        values[key] = loader.construct_object(value_node, deep=deep)
    return values


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


@dataclass(frozen=True)
class ModelConfig:
    alias: str
    identity: ModelIdentity
    artifact_ref: str
    manifest_sha256: str
    artifact_format: str


@dataclass(frozen=True)
class AdmissionConfig:
    max_queued: int
    max_queued_audio_bytes: int
    max_retained_audio_bytes: int
    max_uploads: int
    max_upload_bytes: int
    max_request_bytes: int
    max_result_bytes: int
    max_ipc_message_bytes: int
    queue_wait_timeout_seconds: float
    request_timeout_seconds: float


@dataclass(frozen=True)
class LifecycleConfig:
    model_load_timeout_seconds: float
    cooperative_cancel_grace_seconds: float
    process_exit_timeout_seconds: float
    shutdown_drain_timeout_seconds: float


@dataclass(frozen=True)
class AudioLimits:
    sample_rate_hz: int
    max_duration_seconds: float
    max_decoded_audio_bytes: int


@dataclass(frozen=True)
class ApplicationConfig:
    backend_id: str
    default_model: str
    models: tuple[ModelConfig, ...]
    device_mode: str
    device_preference: tuple[str, ...]
    admission: AdmissionConfig
    lifecycle: LifecycleConfig
    backend_options: tuple[tuple[str, object], ...] = ()
    audio_limits: AudioLimits | None = None

    def catalog(self) -> dict[str, ModelSelection]:
        return {
            model.alias: ModelSelection(
                model.alias,
                model.identity,
                model.artifact_ref,
                _artifact_identity(model),
            )
            for model in self.models
        }


@dataclass(frozen=True)
class ArtifactRoot:
    directory: Path
    manifest: Path


@dataclass(frozen=True)
class DeploymentConfig:
    artifact_roots: dict[str, ArtifactRoot]
    cuda_device_index: int = 0
    minimum_free_gpu_bytes_before_load: int | None = None


def _artifact_identity(model: ModelConfig):
    return ArtifactIdentity(model.manifest_sha256, model.artifact_format)


def _read_yaml(path: str | Path):
    try:
        with Path(path).open(encoding="utf-8") as stream:
            value = yaml.load(stream, Loader=StrictLoader)
    except (OSError, yaml.YAMLError, ValueError, TypeError) as exc:
        raise ValueError("invalid YAML configuration") from exc
    if not isinstance(value, dict):
        raise ValueError("configuration root must be a mapping")
    return value


def _fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"{label} fields must match the versioned schema")


def _integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def _number(value, name, minimum, maximum):
    if type(value) not in (int, float) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be a number in {minimum}..{maximum}")
    return float(value)


def _text(value, name, maximum=256):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(
            f"{name} must be a non-empty string of at most {maximum} characters"
        )
    return value


def load_application_config(path: str | Path) -> ApplicationConfig:
    data = _read_yaml(path)
    version = data.get("schema_version")
    if type(version) is not int or version not in APPLICATION_SCHEMA_VERSIONS:
        raise ValueError("application schema_version must be 2 or 3")
    fields = {
        "schema_version",
        "default_model",
        "backend",
        "models",
        "device_policy",
        "admission",
        "lifecycle",
        "recovery",
    }
    if version == 3:
        fields.add("audio_limits")
    _fields(data, fields, "application configuration")
    backend = data["backend"]
    _fields(backend, {"id", "options"}, "backend")
    backend_id = _text(backend["id"], "backend.id", 64)
    raw_backend_options = backend["options"]
    if version == 2 and raw_backend_options != {}:
        raise ValueError("backend options are not implemented in schema version 2")
    backend_options = ()
    if version == 3:
        if backend_id != "faster-whisper":
            raise ValueError("schema version 3 currently supports faster-whisper only")
        _fields(
            raw_backend_options,
            {"cpu_threads", "compute_type_cpu", "compute_type_cuda", "beam_size"},
            "faster-whisper options",
        )
        compute_types = {"float32", "float16", "int8", "int8_float16", "int8_float32"}
        _integer(raw_backend_options["cpu_threads"], "cpu_threads", 1, 256)
        cpu_type = _text(
            raw_backend_options["compute_type_cpu"], "compute_type_cpu", 32
        )
        cuda_type = _text(
            raw_backend_options["compute_type_cuda"], "compute_type_cuda", 32
        )
        if cpu_type not in compute_types or cuda_type not in compute_types:
            raise ValueError("unsupported compute type")
        if cpu_type in {"float16", "int8_float16"}:
            raise ValueError("CPU compute type is incompatible with CPU policy")
        if (
            _integer(raw_backend_options["beam_size"], "beam_size", 1, 10)
            != raw_backend_options["beam_size"]
        ):
            raise ValueError("invalid beam_size")
        backend_options = tuple(sorted(raw_backend_options.items()))
        audio = data["audio_limits"]
        _fields(
            audio,
            {"sample_rate_hz", "max_duration_seconds", "max_decoded_audio_bytes"},
            "audio_limits",
        )
        audio_limits = AudioLimits(
            _integer(audio["sample_rate_hz"], "sample_rate_hz", 8000, 48000),
            _number(audio["max_duration_seconds"], "max_duration_seconds", 0.1, 3600),
            _integer(
                audio["max_decoded_audio_bytes"],
                "max_decoded_audio_bytes",
                4096,
                2**31 - 1,
            ),
        )
    else:
        audio_limits = None

    raw_models = data["models"]
    if not isinstance(raw_models, list) or not raw_models:
        raise ValueError("models must be a non-empty list")
    if len(raw_models) != 1:
        raise ValueError("M02-A supports exactly one resident model")
    models = []
    aliases = set()
    for entry in raw_models:
        _fields(
            entry,
            {"alias", "family", "immutable_revision", "artifacts"},
            "model",
        )
        alias = _text(entry["alias"], "model.alias", 128)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", alias) or alias in aliases:
            raise ValueError("model aliases must be unique stable identifiers")
        aliases.add(alias)
        family = _text(entry["family"], "model.family", 128)
        revision = _text(entry["immutable_revision"], "model.immutable_revision", 256)
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision):
            raise ValueError("model revision must be an immutable hexadecimal digest")
        artifacts = entry["artifacts"]
        if not isinstance(artifacts, dict) or set(artifacts) != {backend_id}:
            raise ValueError(
                "each model must define exactly the configured backend artifact"
            )
        artifact = artifacts[backend_id]
        _fields(
            artifact,
            {"ref", "manifest_sha256", "format"},
            "model backend artifact",
        )
        digest = _text(artifact["manifest_sha256"], "model.manifest_sha256", 64)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("model.manifest_sha256 must be lowercase SHA-256")
        models.append(
            ModelConfig(
                alias,
                ModelIdentity(family, revision),
                _text(artifact["ref"], "model artifact reference", 128),
                digest,
                _text(artifact["format"], "model artifact format", 128),
            )
        )
    default_model = _text(data["default_model"], "default_model", 128)
    if default_model not in aliases:
        raise ValueError("default_model must reference a configured alias")

    policy = data["device_policy"]
    _fields(policy, {"mode", "preference"}, "device_policy")
    mode = policy["mode"]
    preference = policy["preference"]
    if not isinstance(mode, str) or mode not in {"cpu", "cuda", "auto"}:
        raise ValueError("device_policy.mode must be cpu, cuda or auto")
    if (
        not isinstance(preference, list)
        or not preference
        or any(
            not isinstance(item, str) or item not in {"cpu", "cuda"}
            for item in preference
        )
        or len(set(preference)) != len(preference)
    ):
        raise ValueError("device preference must be a unique non-empty CPU/CUDA list")
    if mode != "auto" and preference != [mode]:
        raise ValueError("explicit device policy must have exactly its selected device")

    admission = data["admission"]
    _fields(
        admission,
        {
            "max_active",
            "max_queued",
            "max_queued_audio_bytes",
            "max_retained_audio_bytes",
            "max_uploads",
            "max_upload_bytes",
            "max_request_bytes",
            "max_result_bytes",
            "max_ipc_message_bytes",
            "queue_wait_timeout_seconds",
            "request_timeout_seconds",
        },
        "admission",
    )
    if _integer(admission["max_active"], "max_active", 1, 1024) != 1:
        raise ValueError("M02-A supports exactly one active job")
    admission_config = AdmissionConfig(
        _integer(admission["max_queued"], "max_queued", 0, 1024),
        _integer(
            admission["max_queued_audio_bytes"], "max_queued_audio_bytes", 1, 2**40
        ),
        _integer(
            admission["max_retained_audio_bytes"], "max_retained_audio_bytes", 1, 2**40
        ),
        _integer(admission["max_uploads"], "max_uploads", 1, 1024),
        _integer(admission["max_upload_bytes"], "max_upload_bytes", 1, 2**40),
        _integer(admission["max_request_bytes"], "max_request_bytes", 1, 2**31 - 1),
        _integer(admission["max_result_bytes"], "max_result_bytes", 1, 2**31 - 1),
        _integer(
            admission["max_ipc_message_bytes"],
            "max_ipc_message_bytes",
            65536,
            2**31 - 1,
        ),
        _number(
            admission["queue_wait_timeout_seconds"],
            "queue_wait_timeout_seconds",
            0.001,
            86400,
        ),
        _number(
            admission["request_timeout_seconds"],
            "request_timeout_seconds",
            0.001,
            86400,
        ),
    )
    if (
        admission_config.max_queued_audio_bytes
        > admission_config.max_retained_audio_bytes
    ):
        raise ValueError("queued audio budget cannot exceed retained audio budget")
    if admission_config.max_request_bytes > admission_config.max_retained_audio_bytes:
        raise ValueError("max_request_bytes cannot exceed retained audio budget")
    if admission_config.max_request_bytes > admission_config.max_upload_bytes:
        raise ValueError("max_request_bytes cannot exceed upload byte budget")
    encoded_limit = admission_config.max_request_bytes * 4 // 3 + 4096
    if admission_config.max_ipc_message_bytes < encoded_limit:
        raise ValueError(
            "max_ipc_message_bytes is too small for a maximum audio request"
        )
    if admission_config.max_result_bytes > admission_config.max_ipc_message_bytes:
        raise ValueError("max_result_bytes cannot exceed the IPC message limit")

    lifecycle = data["lifecycle"]
    _fields(
        lifecycle,
        {
            "model_load_timeout_seconds",
            "cooperative_cancel_grace_seconds",
            "process_exit_timeout_seconds",
            "shutdown_drain_timeout_seconds",
        },
        "lifecycle",
    )
    lifecycle_config = LifecycleConfig(
        _number(
            lifecycle["model_load_timeout_seconds"],
            "model_load_timeout_seconds",
            0.001,
            86400,
        ),
        _number(
            lifecycle["cooperative_cancel_grace_seconds"],
            "cooperative_cancel_grace_seconds",
            0.001,
            3600,
        ),
        _number(
            lifecycle["process_exit_timeout_seconds"],
            "process_exit_timeout_seconds",
            0.001,
            3600,
        ),
        _number(
            lifecycle["shutdown_drain_timeout_seconds"],
            "shutdown_drain_timeout_seconds",
            0.001,
            86400,
        ),
    )
    recovery = data["recovery"]
    _fields(recovery, {"policy"}, "recovery")
    if recovery["policy"] != "manual":
        raise ValueError("only manual recovery is implemented")
    return ApplicationConfig(
        backend_id,
        default_model,
        tuple(models),
        mode,
        tuple(preference),
        admission_config,
        lifecycle_config,
        backend_options,
        audio_limits,
    )


def load_deployment_config(path: str | Path) -> DeploymentConfig:
    data = _read_yaml(path)
    version = data.get("schema_version")
    if type(version) is not int or version not in DEPLOYMENT_SCHEMA_VERSIONS:
        raise ValueError("deployment schema_version must be 1 or 2")
    expected_fields = {"schema_version", "artifacts"}
    if version == 2:
        expected_fields.add("device_access")
    _fields(data, expected_fields, "deployment configuration")
    raw_artifacts = data["artifacts"]
    if not isinstance(raw_artifacts, dict):
        raise ValueError("artifacts must be a mapping")
    artifacts = {}
    for key, item in raw_artifacts.items():
        _fields(item, {"directory", "manifest"}, "artifact root")
        directory = Path(_text(item["directory"], "artifact directory", 4096))
        manifest = Path(_text(item["manifest"], "artifact manifest path", 4096))
        artifacts[_text(key, "artifact reference", 128)] = ArtifactRoot(
            directory, manifest
        )
    if version == 1:
        return DeploymentConfig(artifacts)
    access = data["device_access"]
    _fields(
        access,
        {"cuda_device_index", "minimum_free_gpu_bytes_before_load"},
        "device_access",
    )
    return DeploymentConfig(
        artifacts,
        _integer(access["cuda_device_index"], "cuda_device_index", 0, 1024),
        _integer(
            access["minimum_free_gpu_bytes_before_load"],
            "minimum_free_gpu_bytes_before_load",
            1,
            2**50,
        ),
    )


def resolve_backend(backend_id: str, registry: dict[str, object]):
    try:
        return registry[backend_id]
    except KeyError as exc:
        raise SpeechFailure(
            FailureCode.MODEL_LOAD_FAILED,
            "configured inference backend is not available",
        ) from exc
