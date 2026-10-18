"""One-time, read-only collector for local containerd image identity evidence.

This is an operator diagnostic, not part of deployment validation. It uses the
installed ``ctr`` and Docker CLIs only to read image metadata and content.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import selectors
import shutil
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path

OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_LAYER_TYPES = {
    "application/vnd.oci.image.layer.v1.tar",
    "application/vnd.oci.image.layer.v1.tar+gzip",
    "application/vnd.oci.image.layer.v1.tar+zstd",
    "application/vnd.docker.image.rootfs.diff.tar.gzip",
}
MAX_INDEX_BYTES = 1024 * 1024
MAX_DOCKER_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_RAW_MANIFEST_BYTES = 12 * 1024 * 1024
MAX_CONFIG_BYTES = 16 * 1024 * 1024
MAX_SMALL_COMMAND_BYTES = 2 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024


class CollectionError(Exception):
    """Safe, fixed diagnostic code; never contains command output or paths."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _sha256_digest(value: object, code: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise CollectionError(code)
    return value


def _decode_json(raw: bytes, code: str):
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        raise CollectionError(code) from None
    if not isinstance(value, dict):
        raise CollectionError(code)
    return value


def _digest_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _check_deadline(deadline: float | None):
    if deadline is not None and time.monotonic() >= deadline:
        raise CollectionError("collection_timeout")


def _hash_stream(chunks, expected_size: int | None = None):
    digest = hashlib.sha256()
    count = 0
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise CollectionError("invalid_stream")
        count += len(chunk)
        if expected_size is not None and count > expected_size:
            raise CollectionError("content_size_mismatch")
        digest.update(chunk)
    return "sha256:" + digest.hexdigest(), count


class SubprocessReader:
    """Run bounded commands and stream content without retaining layer bytes."""

    def run_text(self, argv: list[str], deadline: float) -> str:
        raw = bytearray()
        for chunk in self.stream(argv, deadline):
            if len(raw) + len(chunk) > MAX_SMALL_COMMAND_BYTES:
                raise CollectionError("command_output_too_large")
            raw.extend(chunk)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise CollectionError("command_output_invalid") from None

    def stream(self, argv: list[str], deadline: float):
        try:
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError:
            raise CollectionError("command_unavailable") from None
        if process.stdout is None:
            process.kill()
            process.wait()
            raise CollectionError("command_output_unavailable")

        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            os.set_blocking(process.stdout.fileno(), False)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CollectionError("command_timeout")
                events = selector.select(remaining)
                if not events:
                    if process.poll() is None:
                        raise CollectionError("command_timeout")
                    # EOF becomes readable after the child closes its pipe.
                    continue
                chunk = os.read(process.stdout.fileno(), READ_CHUNK_BYTES)
                if not chunk:
                    break
                yield chunk
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CollectionError("command_timeout")
            try:
                code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise CollectionError("command_timeout") from None
            if code != 0:
                raise CollectionError("command_failed")
        finally:
            selector.close()
            process.stdout.close()
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    raise CollectionError("command_cleanup_unconfirmed") from None


def _read_tar_member(archive: tarfile.TarFile, members: dict, path: str, limit: int):
    member = members.get(path)
    if member is None or not member.isfile() or member.size > limit:
        raise CollectionError("archive_member_invalid")
    source = archive.extractfile(member)
    if source is None:
        raise CollectionError("archive_member_missing")
    with source:
        raw = source.read(limit + 1)
    if len(raw) != member.size:
        raise CollectionError("archive_member_truncated")
    return raw


def _hash_tar_member(
    archive: tarfile.TarFile,
    members: dict,
    path: str,
    deadline: float | None = None,
):
    member = members.get(path)
    if member is None or not member.isfile():
        raise CollectionError("archive_layer_missing")
    source = archive.extractfile(member)
    if source is None:
        raise CollectionError("archive_layer_missing")
    with source:
        digest = hashlib.sha256()
        count = 0
        for block in iter(lambda: source.read(READ_CHUNK_BYTES), b""):
            _check_deadline(deadline)
            digest.update(block)
            count += len(block)
    if count != member.size:
        raise CollectionError("archive_layer_truncated")
    return "sha256:" + digest.hexdigest(), count


def _safe_archive(archive_path: Path, expected_archive_sha256: str, deadline: float):
    digest = hashlib.sha256()
    try:
        with archive_path.open("rb") as source:
            for block in iter(lambda: source.read(READ_CHUNK_BYTES), b""):
                _check_deadline(deadline)
                digest.update(block)
    except OSError:
        raise CollectionError("archive_unavailable") from None
    if digest.hexdigest() != expected_archive_sha256:
        raise CollectionError("archive_digest_mismatch")

    try:
        archive = tarfile.open(archive_path, "r:")
        members = archive.getmembers()
    except (OSError, tarfile.TarError):
        raise CollectionError("archive_invalid") from None
    if len(members) > 10000:
        archive.close()
        raise CollectionError("archive_inventory_too_large")
    by_name = {}
    for member in members:
        if (
            member.name.startswith("/")
            or ".." in Path(member.name).parts
            or member.name in by_name
            or not (member.isfile() or member.isdir())
        ):
            archive.close()
            raise CollectionError("archive_path_invalid")
        by_name[member.name] = member
    return archive, by_name


def _approved_archive_identity(
    archive_path: Path,
    archive_sha256: str,
    expected_manifest_digest: str,
    expected_config_digest: str,
    deadline: float,
):
    archive, members = _safe_archive(archive_path, archive_sha256, deadline)
    try:
        index = _decode_json(
            _read_tar_member(archive, members, "index.json", MAX_INDEX_BYTES),
            "archive_index_invalid",
        )
        if (
            index.get("schemaVersion") != 2
            or index.get("mediaType") != "application/vnd.oci.image.index.v1+json"
            or set(index) != {"schemaVersion", "mediaType", "manifests"}
        ):
            raise CollectionError("archive_index_invalid")
        descriptors = index.get("manifests")
        if not isinstance(descriptors, list) or len(descriptors) != 1:
            raise CollectionError("archive_manifest_ambiguous")
        manifest_descriptor = descriptors[0]
        if not isinstance(manifest_descriptor, dict) or set(manifest_descriptor) != {
            "mediaType",
            "digest",
            "size",
        }:
            raise CollectionError("archive_manifest_descriptor_invalid")
        if manifest_descriptor.get("mediaType") != OCI_MANIFEST:
            raise CollectionError("manifest_media_type_unsupported")
        manifest_digest = _sha256_digest(
            manifest_descriptor.get("digest"), "manifest_digest_invalid"
        )
        if manifest_digest != expected_manifest_digest:
            raise CollectionError("manifest_identity_mismatch")
        manifest_blob_path = "blobs/sha256/" + manifest_digest.split(":", 1)[1]
        raw_manifest = _read_tar_member(
            archive, members, manifest_blob_path, MAX_RAW_MANIFEST_BYTES
        )
        if (
            len(raw_manifest) != manifest_descriptor.get("size")
            or _digest_bytes(raw_manifest) != manifest_digest
        ):
            raise CollectionError("manifest_digest_or_size_mismatch")
        manifest = _decode_json(raw_manifest, "manifest_invalid")
        if (
            manifest.get("schemaVersion") != 2
            or manifest.get("mediaType") != OCI_MANIFEST
            or set(manifest) - {"schemaVersion", "mediaType", "config", "layers"}
        ):
            raise CollectionError("manifest_media_type_unsupported")

        config_descriptor = manifest.get("config")
        if not isinstance(config_descriptor, dict) or set(config_descriptor) != {
            "mediaType",
            "digest",
            "size",
        }:
            raise CollectionError("config_descriptor_invalid")
        config_digest = _sha256_digest(
            config_descriptor.get("digest"), "config_digest_invalid"
        )
        if config_digest != expected_config_digest:
            raise CollectionError("config_identity_mismatch")
        if config_descriptor.get("mediaType") != OCI_CONFIG:
            raise CollectionError("config_media_type_unsupported")
        config_path = "blobs/sha256/" + config_digest.split(":", 1)[1]
        raw_config = _read_tar_member(archive, members, config_path, MAX_CONFIG_BYTES)
        if (
            len(raw_config) != config_descriptor.get("size")
            or _digest_bytes(raw_config) != config_digest
        ):
            raise CollectionError("config_digest_or_size_mismatch")
        config = _decode_json(raw_config, "config_invalid")
        platform = f"{config.get('os')}/{config.get('architecture')}"
        if platform != "linux/amd64":
            raise CollectionError("platform_unsupported")
        diff_ids = config.get("rootfs", {}).get("diff_ids")
        if not isinstance(diff_ids, list) or not diff_ids:
            raise CollectionError("rootfs_identity_missing")
        for item in diff_ids:
            _sha256_digest(item, "rootfs_identity_invalid")

        layers = manifest.get("layers")
        if not isinstance(layers, list) or len(layers) != len(diff_ids):
            raise CollectionError("layer_inventory_mismatch")
        normalized_layers = []
        for descriptor in layers:
            if not isinstance(descriptor, dict) or set(descriptor) != {
                "mediaType",
                "digest",
                "size",
            }:
                raise CollectionError("layer_descriptor_invalid")
            layer_digest = _sha256_digest(
                descriptor.get("digest"), "layer_digest_invalid"
            )
            media_type = descriptor.get("mediaType")
            size = descriptor.get("size")
            if media_type not in OCI_LAYER_TYPES:
                raise CollectionError("layer_media_type_unsupported")
            if type(size) is not int or size <= 0:
                raise CollectionError("layer_size_invalid")
            path = "blobs/sha256/" + layer_digest.split(":", 1)[1]
            actual_digest, actual_size = _hash_tar_member(
                archive, members, path, deadline
            )
            if actual_digest != layer_digest or actual_size != size:
                raise CollectionError("archive_layer_mismatch")
            normalized_layers.append(
                {
                    "digest": layer_digest,
                    "media_type": media_type,
                    "size_bytes": size,
                }
            )

        docker_manifest = json.loads(
            _read_tar_member(
                archive, members, "manifest.json", MAX_DOCKER_MANIFEST_BYTES
            )
        )
        if not isinstance(docker_manifest, list) or len(docker_manifest) != 1:
            raise CollectionError("docker_archive_manifest_invalid")
        docker_entry = docker_manifest[0]
        if not isinstance(docker_entry, dict) or docker_entry.get("RepoTags") not in (
            None,
            [],
        ):
            raise CollectionError("docker_archive_tags_unexpected")
        if docker_entry.get("Config") != config_path:
            raise CollectionError("docker_archive_config_mismatch")
        docker_layers = docker_entry.get("Layers")
        if not isinstance(docker_layers, list) or len(docker_layers) != len(diff_ids):
            raise CollectionError("docker_archive_layer_inventory_mismatch")
        expected_layer_paths = [
            "blobs/sha256/" + layer["digest"].split(":", 1)[1]
            for layer in normalized_layers
        ]
        if docker_layers != expected_layer_paths:
            raise CollectionError("docker_archive_layer_order_mismatch")
        for layer_path in docker_layers:
            member = members.get(layer_path)
            if member is None or not member.isfile():
                raise CollectionError("docker_archive_layer_missing")

        return {
            "archive_sha256": archive_sha256,
            "config_digest": config_digest,
            "raw_config_sha256": _digest_bytes(raw_config),
            "rootfs_diff_ids": diff_ids,
            "manifest_digest": manifest_digest,
            "manifest_media_type": OCI_MANIFEST,
            "manifest_config_digest": config_digest,
            "manifest_config_media_type": OCI_CONFIG,
            "manifest_config_size_bytes": config_descriptor["size"],
            "manifest_layers": normalized_layers,
            "raw_manifest": raw_manifest,
            "platform": platform,
        }
    except (OSError, tarfile.TarError, json.JSONDecodeError, TypeError):
        raise CollectionError("archive_invalid") from None
    finally:
        archive.close()


def _validate_socket(path: str):
    try:
        mode = Path(path).lstat().st_mode
    except OSError:
        raise CollectionError("containerd_socket_unavailable") from None
    if not stat.S_ISSOCK(mode):
        raise CollectionError("containerd_socket_invalid")
    if not os.access(path, os.R_OK | os.W_OK):
        raise CollectionError("containerd_socket_inaccessible")


_INSPECT_ROOT_DESCRIPTOR = re.compile(
    r"^└── (?P<media_type>[A-Za-z0-9][A-Za-z0-9./+_-]*) "
    r"@(?P<digest>sha256:[0-9a-f]{64}) \((?P<size>[1-9][0-9]*) bytes\)$"
)


def _parse_inspect_output(raw: str, reference: str):
    """Parse the root descriptor from containerd 2.2.x `images inspect` output.

    This is a deliberately narrow parser for the versioned display format, not
    a general-purpose parser for arbitrary `ctr` output. A changed format fails
    closed instead of falling back to human-readable image-size columns.
    """
    lines = raw.splitlines()
    if not lines or lines[0] != reference:
        raise CollectionError("image_record_inspect_invalid")
    roots = [line for line in lines[1:] if line.startswith("└── ")]
    if not roots:
        raise CollectionError("image_record_descriptor_missing")
    if len(roots) != 1:
        raise CollectionError("image_record_descriptor_ambiguous")
    match = _INSPECT_ROOT_DESCRIPTOR.fullmatch(roots[0])
    if match is None:
        raise CollectionError("image_record_descriptor_invalid")
    size_text = match.group("size")
    if len(size_text) > len(str(MAX_RAW_MANIFEST_BYTES)):
        raise CollectionError("image_record_descriptor_invalid")
    size = int(size_text)
    if size > MAX_RAW_MANIFEST_BYTES:
        raise CollectionError("image_record_descriptor_invalid")
    return {
        "mediaType": match.group("media_type"),
        "digest": match.group("digest"),
        "size": size,
    }


def _small_blob(runner, argv, deadline: float, expected_size: int, max_size: int):
    if expected_size > max_size:
        raise CollectionError("content_size_out_of_bounds")
    chunks = bytearray()
    for chunk in runner.stream(argv, deadline):
        if len(chunks) + len(chunk) > expected_size:
            raise CollectionError("content_size_mismatch")
        chunks.extend(chunk)
    if len(chunks) != expected_size:
        raise CollectionError("content_truncated")
    return bytes(chunks)


def _stream_blob(runner, argv, deadline, expected_digest, expected_size):
    actual_digest, actual_size = _hash_stream(
        runner.stream(argv, deadline), expected_size
    )
    if actual_size != expected_size:
        raise CollectionError("content_truncated")
    if actual_digest != expected_digest:
        raise CollectionError("content_digest_mismatch")


def _validate_namespace(value: str):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value
    ):
        raise CollectionError("namespace_invalid")


def _validate_image_record_reference(value: str):
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:sha256:[0-9a-f]{64}|"
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}(?::[0-9]{1,5})?"
        r"(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,127})*"
        r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?"
        r"(?:@sha256:[0-9a-f]{64})?)",
        value,
    ):
        raise CollectionError("image_record_reference_unsafe")
    if ".." in value or "//" in value:
        raise CollectionError("image_record_reference_unsafe")


def collect_evidence(
    *,
    socket_path: str,
    namespace: str,
    docker_context: str,
    manifest_digest: str,
    config_digest: str,
    archive_path: Path,
    archive_sha256: str,
    overall_timeout_seconds: int,
    ctr_command: str = "ctr",
    docker_command: str = "docker",
    runner=None,
):
    """Collect and validate exact image-store facts; return validator schema data."""
    if (
        type(overall_timeout_seconds) is not int
        or not 1 <= overall_timeout_seconds <= 86400
    ):
        raise CollectionError("overall_timeout_invalid")
    deadline = time.monotonic() + overall_timeout_seconds
    _validate_socket(socket_path)
    _validate_namespace(namespace)
    _sha256_digest(manifest_digest, "manifest_digest_invalid")
    _sha256_digest(config_digest, "config_digest_invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", archive_sha256):
        raise CollectionError("archive_digest_invalid")
    if not isinstance(docker_context, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", docker_context
    ):
        raise CollectionError("docker_context_invalid")
    if runner is None and (
        shutil.which(ctr_command) is None or shutil.which(docker_command) is None
    ):
        raise CollectionError("required_cli_unavailable")

    approved = _approved_archive_identity(
        archive_path,
        archive_sha256,
        manifest_digest,
        config_digest,
        deadline,
    )
    if runner is None:
        runner = SubprocessReader()

    ctr_prefix = [
        ctr_command,
        "--address",
        socket_path,
        "--namespace",
        namespace,
    ]
    namespaces = runner.run_text(
        ctr_prefix + ["namespaces", "list", "--quiet"], deadline
    ).splitlines()
    if namespace not in namespaces:
        raise CollectionError("namespace_not_found")
    references = runner.run_text(
        ctr_prefix + ["images", "list", "--quiet"], deadline
    ).splitlines()
    if (
        not references
        or len(references) > 4096
        or len(set(references)) != len(references)
    ):
        raise CollectionError("image_record_inventory_invalid")
    matches = []
    for reference in references:
        _validate_image_record_reference(reference)
        raw_inspect = runner.run_text(
            ctr_prefix + ["images", "inspect", reference], deadline
        )
        target = _parse_inspect_output(raw_inspect, reference)
        if target["digest"] == manifest_digest:
            if target["mediaType"] != approved["manifest_media_type"] or target[
                "size"
            ] != len(approved["raw_manifest"]):
                raise CollectionError("image_record_manifest_mismatch")
            matches.append(reference)
    if not matches:
        raise CollectionError("matching_image_record_missing")
    if len(matches) != 1:
        raise CollectionError("matching_image_record_ambiguous")
    image_record_reference = matches[0]

    manifest_bytes = _small_blob(
        runner,
        ctr_prefix + ["content", "get", manifest_digest],
        deadline,
        len(approved["raw_manifest"]),
        MAX_RAW_MANIFEST_BYTES,
    )
    if manifest_bytes != approved["raw_manifest"]:
        raise CollectionError("target_manifest_mismatch")
    config_digest_ref = approved["config_digest"]
    config_bytes = _small_blob(
        runner,
        ctr_prefix + ["content", "get", config_digest_ref],
        deadline,
        approved["manifest_config_size_bytes"],
        MAX_CONFIG_BYTES,
    )
    if _digest_bytes(config_bytes) != approved["config_digest"]:
        raise CollectionError("target_config_mismatch")
    try:
        target_config = json.loads(config_bytes)
    except json.JSONDecodeError:
        raise CollectionError("target_config_invalid") from None
    target_rootfs = target_config.get("rootfs")
    if (
        not isinstance(target_rootfs, dict)
        or target_rootfs.get("diff_ids") != approved["rootfs_diff_ids"]
    ):
        raise CollectionError("target_rootfs_mismatch")

    verified_layer_digests = []
    for layer in approved["manifest_layers"]:
        digest = layer["digest"]
        _stream_blob(
            runner,
            ctr_prefix + ["content", "get", digest],
            deadline,
            digest,
            layer["size_bytes"],
        )
        verified_layer_digests.append(digest)

    docker_template = "{{.Id}}|{{.Os}}/{{.Architecture}}|{{json .RootFS.Layers}}"
    docker_output = runner.run_text(
        [
            docker_command,
            "--context",
            docker_context,
            "image",
            "inspect",
            "--format",
            docker_template,
            manifest_digest,
        ],
        deadline,
    ).strip()
    parts = docker_output.split("|", 2)
    if len(parts) != 3:
        raise CollectionError("docker_inspection_invalid")
    docker_image_id, platform, rootfs_json = parts
    if docker_image_id != manifest_digest or platform != approved["platform"]:
        raise CollectionError("docker_identity_mismatch")
    try:
        docker_diff_ids = json.loads(rootfs_json)
    except json.JSONDecodeError:
        raise CollectionError("docker_inspection_invalid") from None
    if docker_diff_ids != approved["rootfs_diff_ids"]:
        raise CollectionError("docker_rootfs_mismatch")

    return {
        "schema_version": 1,
        "docker_image_id": docker_image_id,
        "platform": platform,
        "identity_kind": "containerd_oci_manifest",
        "archive_sha256": archive_sha256,
        "config_digest": approved["config_digest"],
        "raw_config_sha256": _digest_bytes(config_bytes),
        "rootfs_diff_ids": approved["rootfs_diff_ids"],
        "namespace": namespace,
        "image_record_reference": image_record_reference,
        "matching_image_records": 1,
        "manifest_digest": manifest_digest,
        "manifest_media_type": approved["manifest_media_type"],
        "manifest_config_digest": approved["manifest_config_digest"],
        "manifest_config_media_type": approved["manifest_config_media_type"],
        "manifest_config_size_bytes": approved["manifest_config_size_bytes"],
        "manifest_layers": approved["manifest_layers"],
        "verified_layer_digests": verified_layer_digests,
        "raw_manifest_base64": base64.b64encode(manifest_bytes).decode("ascii"),
    }


def _atomic_private_json(path: Path, value: dict):
    directory_fd = None
    temporary_name = None
    try:
        if not path.is_absolute():
            raise CollectionError("output_path_invalid")
        if path.name in ("", ".", "..") or ".." in path.parts:
            raise CollectionError("output_path_invalid")

        # Walk from / using directory descriptors and O_NOFOLLOW so an
        # intermediate symlink cannot redirect evidence after validation.
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        try:
            directory_fd = os.open(path.anchor, flags | nofollow)
            for component in path.parent.parts[1:]:
                next_fd = os.open(component, flags | nofollow, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
        except OSError:
            raise CollectionError("output_directory_invalid") from None
        parent_info = os.fstat(directory_fd)
        if not stat.S_ISDIR(parent_info.st_mode):
            raise CollectionError("output_directory_invalid")
        if (
            parent_info.st_uid != os.geteuid()
            or stat.S_IMODE(parent_info.st_mode) & 0o077
        ):
            raise CollectionError("output_directory_permissions_invalid")
        raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
        output_name = path.name
        try:
            os.stat(output_name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise CollectionError("output_already_exists")

        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow
        for _ in range(8):
            temporary_name = f".image-store-evidence-{secrets.token_hex(12)}"
            try:
                fd = os.open(
                    temporary_name,
                    file_flags,
                    0o600,
                    dir_fd=directory_fd,
                )
                break
            except FileExistsError:
                temporary_name = None
        else:
            raise CollectionError("output_write_failed")
        try:
            try:
                output_file = os.fdopen(fd, "wb")
            except OSError:
                os.close(fd)
                raise
            with output_file as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            # Link is atomic and refuses to replace existing operator evidence.
            try:
                os.link(
                    temporary_name,
                    output_name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                raise CollectionError("output_already_exists") from None
            os.unlink(temporary_name, dir_fd=directory_fd)
            temporary_name = None
            os.fsync(directory_fd)
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
        return hashlib.sha256(raw).hexdigest()
    except CollectionError:
        raise
    except OSError:
        raise CollectionError("output_write_failed") from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _evidence_json(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--containerd-socket", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--docker-context", required=True)
    parser.add_argument("--manifest-digest", required=True)
    parser.add_argument("--config-digest", required=True)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--overall-timeout-seconds", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ctr-command", default="ctr")
    parser.add_argument("--docker-command", default="docker")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        evidence = collect_evidence(
            socket_path=args.containerd_socket,
            namespace=args.namespace,
            docker_context=args.docker_context,
            manifest_digest=args.manifest_digest,
            config_digest=args.config_digest,
            archive_path=args.archive,
            archive_sha256=args.archive_sha256,
            overall_timeout_seconds=args.overall_timeout_seconds,
            ctr_command=args.ctr_command,
            docker_command=args.docker_command,
        )
        if str(args.output) == "-":
            raw = _evidence_json(evidence)
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()
            digest = hashlib.sha256(raw).hexdigest()
        else:
            digest = _atomic_private_json(args.output, evidence)
    except CollectionError as exc:
        print(f"FAIL: image-store evidence collection ({exc.code})", file=sys.stderr)
        return 2
    except Exception:
        print("FAIL: image-store evidence collection (internal_error)", file=sys.stderr)
        return 2
    print(
        f"PASS: typed image-store evidence collected; sha256={digest}", file=sys.stderr
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
