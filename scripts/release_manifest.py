"""Strict validation for the platform release descriptor and referenced artifacts."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from services.stt.artifacts import load_artifact_manifest
from services.stt.config import (
    APPLICATION_SCHEMA_VERSIONS,
    DEPLOYMENT_SCHEMA_VERSIONS,
    StrictLoader,
)

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE = REPOSITORY_ROOT / "releases/voiceservice-v0.1.2.yaml"
VERSION_PATTERN = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
REVISION_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMAGE_PATTERN = re.compile(
    r"^ghcr\.io/azargarov/[a-z0-9]+(?:[._/-][a-z0-9]+)*@sha256:[0-9a-f]{64}$"
)
MODEL_REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$"
)
PLATFORMS = frozenset({"linux/amd64"})
VARIANTS_BY_SERVICE = {
    "gateway": frozenset({"foundation"}),
    "stt": frozenset({"cpu", "cuda"}),
    "tts": frozenset({"health-only"}),
}
MODEL_SOURCES = frozenset({"huggingface_hub"})
MODEL_FIELDS = {
    "id",
    "source",
    "family",
    "repository",
    "revision",
    "artifact_format",
    "manifest_path",
    "manifest_sha256",
}
SERVICE_FIELDS = {
    "image",
    "platform",
    "runtime_variant",
    "capabilities",
    "dependencies",
    "required_model_artifacts",
    "configuration_compatibility",
}


class ReleaseManifestError(ValueError):
    """The platform release descriptor is incomplete or inconsistent."""


def _read_yaml(path: Path):
    try:
        with path.open(encoding="utf-8") as stream:
            value = yaml.load(stream, Loader=StrictLoader)
    except (OSError, yaml.YAMLError, ValueError, TypeError) as error:
        raise ReleaseManifestError(f"cannot read release YAML: {path}") from error
    if not isinstance(value, dict):
        raise ReleaseManifestError("release YAML root must be a mapping")
    return value


def _text(value, label: str, pattern: re.Pattern | None = None) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ReleaseManifestError(f"{label} must be a non-empty string")
    if pattern is not None and not pattern.fullmatch(value):
        raise ReleaseManifestError(f"{label} has an invalid value")
    return value


def _unique_strings(value, label: str, *, nonempty: bool = True) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ReleaseManifestError(
            f"{label} must be a {'non-empty ' if nonempty else ''}list"
        )
    if any(
        not isinstance(item, str) or not item or item.strip() != item for item in value
    ):
        raise ReleaseManifestError(f"{label} entries must be non-empty strings")
    if len(value) != len(set(value)):
        raise ReleaseManifestError(f"{label} entries must be unique")
    return value


def _repository_services(repository_root: Path) -> set[str]:
    compose_path = repository_root / "deployments/compose/compose.yaml"
    compose = _read_yaml(compose_path)
    services = compose.get("services")
    if not isinstance(services, dict) or not services:
        raise ReleaseManifestError("tracked Compose file has no service mapping")
    return set(services)


def _safe_repository_path(value: str, repository_root: Path) -> Path:
    if "\\" in value:
        raise ReleaseManifestError("artifact manifest path must use POSIX separators")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
    ):
        raise ReleaseManifestError("artifact manifest path must be repository-relative")
    root = repository_root.resolve()
    path = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ReleaseManifestError(
                "artifact manifest path cannot traverse symlinks"
            )
    try:
        path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as error:
        raise ReleaseManifestError(
            "artifact manifest path escapes or is missing"
        ) from error
    if path.is_symlink() or not path.is_file():
        raise ReleaseManifestError(
            "artifact manifest must be a regular repository file"
        )
    return path


def _validate_configuration_compatibility(value, service: str) -> None:
    expected = {"source_revision_bound", "schema_versions"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ReleaseManifestError(
            f"{service} configuration_compatibility fields are invalid"
        )
    if type(value["source_revision_bound"]) is not bool:
        raise ReleaseManifestError("source_revision_bound must be a boolean")
    schemas = value["schema_versions"]
    if not isinstance(schemas, dict):
        raise ReleaseManifestError("schema_versions must be a mapping")
    for name, versions in schemas.items():
        _text(name, "configuration schema name")
        supported = {
            "application": APPLICATION_SCHEMA_VERSIONS,
            "deployment": DEPLOYMENT_SCHEMA_VERSIONS,
        }.get(name)
        if supported is None:
            raise ReleaseManifestError(f"unsupported configuration schema: {name}")
        if not isinstance(versions, list) or not versions:
            raise ReleaseManifestError("schema version compatibility must be non-empty")
        if any(type(version) is not int or version < 1 for version in versions):
            raise ReleaseManifestError(
                "configuration schema versions must be positive integers"
            )
        if len(versions) != len(set(versions)):
            raise ReleaseManifestError("configuration schema versions must be unique")
        if set(versions) - supported:
            raise ReleaseManifestError(
                f"{name} compatibility declares an unsupported version"
            )


def _validate_model_reference(model, repository_root: Path) -> None:
    if not isinstance(model, dict) or set(model) != MODEL_FIELDS:
        raise ReleaseManifestError("required model artifact fields do not match schema")
    _text(model["id"], "model artifact id", re.compile(r"^[a-z0-9][a-z0-9-]*$"))
    source = _text(model["source"], "model source")
    if source not in MODEL_SOURCES:
        raise ReleaseManifestError("unsupported immutable model artifact source")
    _text(model["family"], "model family", re.compile(r"^[a-z0-9][a-z0-9-]*$"))
    _text(model["repository"], "model repository", MODEL_REPOSITORY_PATTERN)
    _text(model["revision"], "model revision", REVISION_PATTERN)
    _text(
        model["artifact_format"],
        "model artifact format",
        re.compile(r"^[a-z0-9][a-z0-9-]*$"),
    )
    _text(model["manifest_sha256"], "model manifest SHA-256", SHA256_PATTERN)
    manifest_path_value = _text(model["manifest_path"], "model manifest path")
    manifest_path = _safe_repository_path(manifest_path_value, repository_root)
    try:
        artifact_manifest = load_artifact_manifest(
            manifest_path, model["manifest_sha256"]
        )
    except (OSError, ValueError) as error:
        raise ReleaseManifestError(
            "referenced model artifact manifest is invalid"
        ) from error
    if (
        artifact_manifest["model"]["family"] != model["family"]
        or artifact_manifest["model"]["repository"] != model["repository"]
        or artifact_manifest["model"]["revision"] != model["revision"]
        or artifact_manifest["artifact"]["format"] != model["artifact_format"]
    ):
        raise ReleaseManifestError(
            "model identity differs from referenced artifact manifest"
        )


def validate_release(data, repository_root: Path = REPOSITORY_ROOT) -> dict:
    if not isinstance(data, dict) or set(data) != {
        "schema_version",
        "release_version",
        "git_source_revision",
        "supported_platforms",
        "services",
    }:
        raise ReleaseManifestError("release fields do not match schema version 1")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ReleaseManifestError("unsupported release schema version")
    version = data["release_version"]
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise ReleaseManifestError(
            "release_version must be an explicit vMAJOR.MINOR.PATCH tag"
        )
    _text(data["git_source_revision"], "git_source_revision", REVISION_PATTERN)
    platforms = _unique_strings(data["supported_platforms"], "supported_platforms")
    if set(platforms) - PLATFORMS:
        raise ReleaseManifestError("release declares an unsupported platform")

    services = data["services"]
    if not isinstance(services, dict) or not services:
        raise ReleaseManifestError("services must be a non-empty mapping")
    if any(not isinstance(service, str) or not service for service in services):
        raise ReleaseManifestError("service names must be non-empty strings")
    known_services = _repository_services(repository_root)
    unknown = set(services) - known_services
    if unknown:
        raise ReleaseManifestError(
            f"unknown Compose service(s): {', '.join(sorted(unknown))}"
        )

    dependency_graph = {}
    for service, entry in services.items():
        if service not in known_services:
            raise ReleaseManifestError(f"unknown service: {service}")
        if not isinstance(entry, dict) or set(entry) != SERVICE_FIELDS:
            raise ReleaseManifestError(f"{service} fields do not match release schema")
        image = _text(entry["image"], f"{service} image", IMAGE_PATTERN)
        repository = image.split("@", 1)[0]
        platform = _text(entry["platform"], f"{service} platform")
        if platform not in platforms:
            raise ReleaseManifestError(
                f"{service} platform is not in supported_platforms"
            )
        variant = _text(entry["runtime_variant"], f"{service} runtime_variant")
        if (
            service in VARIANTS_BY_SERVICE
            and variant not in VARIANTS_BY_SERVICE[service]
        ):
            raise ReleaseManifestError(
                f"unsupported {service} runtime variant: {variant}"
            )
        expected_repository_suffix = {
            "gateway": "voiceservice-gateway",
            "stt": f"voiceservice-stt-{variant}",
            "tts": "voiceservice-tts-health-only",
        }.get(service)
        if expected_repository_suffix and not repository.endswith(
            "/" + expected_repository_suffix
        ):
            raise ReleaseManifestError(
                f"{service} image repository disagrees with service variant"
            )
        capabilities = _unique_strings(entry["capabilities"], f"{service} capabilities")
        if any(
            not re.fullmatch(r"[a-z][a-z0-9-]*", capability)
            for capability in capabilities
        ):
            raise ReleaseManifestError(f"{service} capability name is invalid")
        if service == "tts" and set(capabilities) != {"health"}:
            raise ReleaseManifestError("the current TTS release is health-only")
        dependencies = _unique_strings(
            entry["dependencies"], f"{service} dependencies", nonempty=False
        )
        if service in dependencies:
            raise ReleaseManifestError(f"{service} cannot depend on itself")
        dependency_graph[service] = dependencies
        if not isinstance(entry["required_model_artifacts"], list):
            raise ReleaseManifestError(
                f"{service} required_model_artifacts must be a list"
            )
        model_ids = set()
        for model in entry["required_model_artifacts"]:
            _validate_model_reference(model, repository_root)
            if model["id"] in model_ids:
                raise ReleaseManifestError(
                    f"{service} model artifact ids must be unique"
                )
            model_ids.add(model["id"])
        _validate_configuration_compatibility(
            entry["configuration_compatibility"], service
        )

    for service, dependencies in dependency_graph.items():
        missing = set(dependencies) - set(services)
        if missing:
            raise ReleaseManifestError(
                f"{service} dependencies are absent from this release: {', '.join(sorted(missing))}"
            )
    visiting = set()
    visited = set()

    def visit(service: str) -> None:
        if service in visiting:
            raise ReleaseManifestError("service dependencies contain a cycle")
        if service in visited:
            return
        visiting.add(service)
        for dependency in dependency_graph[service]:
            visit(dependency)
        visiting.remove(service)
        visited.add(service)

    for service in dependency_graph:
        visit(service)
    return data


def load_release(
    path: str | Path = DEFAULT_RELEASE,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict:
    release_path = Path(path)
    return validate_release(_read_yaml(release_path), repository_root)
