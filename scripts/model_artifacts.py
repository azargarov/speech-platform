"""Content-addressed model artifact checking and explicit staged provisioning."""

from __future__ import annotations

import os
import shutil
import stat
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


def _validate_staging_parent(path: Path, expected_owner_uid: int) -> None:
    """Reject symlink or untrusted-writable components above a staged store."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except OSError as error:
            raise ModelProvisionError(
                "model staging store parent must already exist"
            ) from error
        mode = info.st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ModelProvisionError(
                "model staging store parent path must contain real directories"
            )
        if info.st_uid not in {0, expected_owner_uid}:
            raise ModelProvisionError(
                "model staging store parent has an untrusted owner"
            )
        writable_by_group_or_other = mode & 0o022
        safe_sticky_directory = (
            info.st_uid == 0 and mode & 0o1000 and writable_by_group_or_other
        )
        if writable_by_group_or_other and not safe_sticky_directory:
            raise ModelProvisionError(
                "model staging store parent is writable by an untrusted user"
            )


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
        # verify_artifact deliberately exposes a generic SpeechFailure, while
        # its ValueError cause contains only a safe validation category (for
        # example, "artifact file digest mismatch"). Keep that detail visible
        # to the operator without exposing arbitrary I/O exception text.
        detail = error.__cause__
        reason = f": {detail}" if isinstance(detail, ValueError) else ""
        raise ModelProvisionError(
            f"model artifact {model['id']} failed local verification{reason}"
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
    *,
    directory_mode: int = 0o700,
    file_mode: int = 0o600,
    expected_owner_uid: int | None = None,
    expected_group_gid: int | None = None,
) -> list[ModelResult]:
    if directory_mode not in {0o700, 0o750, 0o2750} or file_mode not in {
        0o600,
        0o640,
    }:
        raise ModelProvisionError("model staging modes are invalid")
    if (expected_owner_uid is None) != (expected_group_gid is None):
        raise ModelProvisionError(
            "model staging owner and group must be configured together"
        )
    if expected_group_gid is not None and (
        directory_mode != 0o2750 or file_mode != 0o640
    ):
        raise ModelProvisionError("group-readable staging requires modes 2750 and 0640")
    if expected_owner_uid is not None and os.geteuid() != expected_owner_uid:
        raise ModelProvisionError(
            "model staging owner does not match the deployment profile"
        )
    if expected_group_gid is not None and os.getegid() != expected_group_gid:
        raise ModelProvisionError(
            "model staging requires the configured reader group as the primary group"
        )
    root_path = Path(store_root)
    root_preexisting = root_path.exists()
    if expected_group_gid is not None:
        _validate_staging_parent(root_path.parent, expected_owner_uid)
    root = _store_root(root_path, create=True)
    if not root_preexisting and (
        expected_owner_uid is not None or expected_group_gid is not None
    ):
        os.chmod(root, directory_mode)
    if expected_owner_uid is not None or expected_group_gid is not None:
        root_info = root.stat()
        root_mode = root_info.st_mode & 0o7777
        if (
            (not root.is_dir())
            or (
                expected_owner_uid is not None
                and root_info.st_uid != expected_owner_uid
            )
            or (
                expected_group_gid is not None
                and root_info.st_gid != expected_group_gid
            )
            or (expected_group_gid is not None and root_mode & 0o007)
            or (expected_group_gid is not None and root_mode & 0o020)
            or (expected_group_gid is not None and root_mode not in {0o2710, 0o2750})
        ):
            raise ModelProvisionError(
                "model staging store ownership does not match the deployment profile"
            )
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
                os.chmod(staging_manifest, file_mode)
                staged_artifacts = staging / "artifact"
                staged_artifacts.mkdir(mode=directory_mode)
                for entry in artifact_manifest["files"]:
                    relative_path = PurePosixPath(entry["path"])
                    target = staged_artifacts.joinpath(*relative_path.parts)
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    download_file(model, entry["path"], target, entry["size_bytes"])
                    if target.is_symlink() or not target.is_file():
                        raise ModelProvisionError(
                            f"download did not produce a regular file for {entry['path']}"
                        )
                    os.chmod(target, file_mode)

                for directory in sorted(
                    (path for path in staging.rglob("*") if path.is_dir()),
                    key=lambda path: len(path.parts),
                    reverse=True,
                ):
                    os.chmod(directory, directory_mode)
                os.chmod(staging, directory_mode)
                if expected_owner_uid is not None or expected_group_gid is not None:
                    for path in (staging, *staging.rglob("*")):
                        info = path.stat()
                        if (
                            expected_owner_uid is not None
                            and info.st_uid != expected_owner_uid
                        ) or (
                            expected_group_gid is not None
                            and info.st_gid != expected_group_gid
                        ):
                            raise ModelProvisionError(
                                "staged model ownership differs from the deployment profile"
                            )

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
