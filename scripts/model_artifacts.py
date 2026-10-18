"""Content-addressed model artifact checking and explicit staged provisioning."""

from __future__ import annotations

import os
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from services.stt.artifacts import load_artifact_manifest, verify_artifact
from services.stt.config import ArtifactRoot, ModelConfig
from services.stt.domain import ModelIdentity


class ModelProvisionError(RuntimeError):
    """A pinned model is absent, invalid, or could not be staged safely."""


DownloadFile = Callable[[dict, str, Path, int], None]


@dataclass(frozen=True)
class ModelResult:
    artifact_id: str
    directory: Path
    status: str


def _model_config(model: dict) -> ModelConfig:
    return ModelConfig(
        alias=model["id"],
        identity=ModelIdentity(model["family"], model["revision"]),
        artifact_ref=model["id"],
        manifest_sha256=model["manifest_sha256"],
        artifact_format=model["artifact_format"],
    )


def _model_manifest(model: dict, repository_root: Path) -> tuple[Path, dict]:
    path = repository_root / model["manifest_path"]
    try:
        manifest = load_artifact_manifest(path, model["manifest_sha256"])
    except (OSError, ValueError) as error:
        raise ModelProvisionError(
            "release model artifact manifest is no longer valid"
        ) from error
    identity = manifest["model"]
    if (
        identity["family"] != model["family"]
        or identity["repository"] != model["repository"]
        or identity["revision"] != model["revision"]
        or manifest["artifact"]["format"] != model["artifact_format"]
    ):
        raise ModelProvisionError(
            "release model identity disagrees with its artifact manifest"
        )
    return path, manifest


def _store_root(path: str | Path, *, create: bool) -> Path:
    root = Path(path)
    if root.is_symlink():
        raise ModelProvisionError("model store root cannot be a symlink")
    if not root.exists() and not create:
        return root
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as error:
        raise ModelProvisionError("could not create private model store") from error
    if root.is_symlink() or not root.is_dir():
        raise ModelProvisionError("model store root must be a real directory")
    return root


def model_directory(store_root: str | Path, model: dict) -> Path:
    return Path(store_root) / model["manifest_sha256"]


def _verify_directory(model: dict, directory: Path) -> None:
    config = _model_config(model)
    try:
        verify_artifact(
            config,
            ArtifactRoot(directory / "artifact", directory / "manifest.yaml"),
        )
    except Exception as error:
        raise ModelProvisionError(
            f"model artifact {model['id']} failed local verification"
        ) from error


def check_models(
    release: dict, store_root: str | Path, repository_root: Path
) -> list[ModelResult]:
    root = _store_root(store_root, create=False)
    results = []
    for service in release["services"].values():
        for model in service["required_model_artifacts"]:
            _model_manifest(model, repository_root)
            directory = model_directory(root, model)
            if not directory.exists() and not directory.is_symlink():
                raise ModelProvisionError(
                    f"model artifact {model['id']} is not cached at {directory}"
                )
            _verify_directory(model, directory)
            results.append(ModelResult(model["id"], directory, "verified"))
    if not results:
        raise ModelProvisionError("release contains no model artifacts to check")
    return results


def provision_models(
    release: dict,
    store_root: str | Path,
    repository_root: Path,
    download_file: DownloadFile,
) -> list[ModelResult]:
    root = _store_root(store_root, create=True)
    results = []
    for service_name, service in release["services"].items():
        for model in service["required_model_artifacts"]:
            final_directory = model_directory(root, model)
            if final_directory.exists() or final_directory.is_symlink():
                _verify_directory(model, final_directory)
                results.append(ModelResult(model["id"], final_directory, "reused"))
                continue

            manifest_path, artifact_manifest = _model_manifest(model, repository_root)
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".staging-{model['manifest_sha256'][:12]}-", dir=root
                )
            )
            try:
                os.chmod(staging, 0o700)
                staging_manifest = staging / "manifest.yaml"
                shutil.copyfile(manifest_path, staging_manifest)
                os.chmod(staging_manifest, 0o600)
                staged_artifacts = staging / "artifact"
                staged_artifacts.mkdir(mode=0o700)
                for entry in artifact_manifest["files"]:
                    relative_path = PurePosixPath(entry["path"])
                    target = staged_artifacts.joinpath(*relative_path.parts)
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    download_file(model, entry["path"], target, entry["size_bytes"])
                    if target.is_symlink() or not target.is_file():
                        raise ModelProvisionError(
                            f"download did not produce a regular file for {entry['path']}"
                        )
                    os.chmod(target, 0o600)

                _verify_directory(model, staging)
                try:
                    os.rename(staging, final_directory)
                except OSError:
                    if final_directory.exists() or final_directory.is_symlink():
                        _verify_directory(model, final_directory)
                        results.append(
                            ModelResult(model["id"], final_directory, "reused")
                        )
                        if staging.exists() and not staging.is_symlink():
                            shutil.rmtree(staging)
                        continue
                    raise
                results.append(ModelResult(model["id"], final_directory, "installed"))
            except BaseException as error:
                if staging.exists() and not staging.is_symlink():
                    shutil.rmtree(staging)
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise
                if isinstance(error, ModelProvisionError):
                    raise
                raise ModelProvisionError(
                    f"could not stage model artifact {model['id']} for {service_name}"
                ) from error
    if not results:
        raise ModelProvisionError("release contains no model artifacts to provision")
    return results


class _HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if urllib.parse.urlsplit(new_url).scheme != "https":
            raise urllib.error.URLError("refusing non-HTTPS model download redirect")
        return super().redirect_request(
            request, response, code, message, headers, new_url
        )


def download_from_huggingface(
    model: dict,
    relative_path: str,
    destination: Path,
    maximum_bytes: int,
    *,
    timeout_seconds: int = 60,
) -> None:
    """Fetch one file by immutable Hub revision; caller verifies its SHA-256."""
    encoded_repository = "/".join(
        urllib.parse.quote(part, safe="") for part in model["repository"].split("/")
    )
    encoded_path = "/".join(
        urllib.parse.quote(part, safe="") for part in PurePosixPath(relative_path).parts
    )
    url = (
        "https://huggingface.co/"
        f"{encoded_repository}/resolve/{model['revision']}/{encoded_path}"
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "speech-platform-model-provisioner/1"},
    )
    opener = urllib.request.build_opener(_HTTPSRedirectHandler())
    total = 0
    with opener.open(request, timeout=timeout_seconds) as response:
        with destination.open("xb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > maximum_bytes:
                    raise ModelProvisionError(
                        f"download exceeded manifest size for {relative_path}"
                    )
                output.write(block)
