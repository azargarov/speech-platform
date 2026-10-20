"""Read-only, bounded inventory for M01F-B3.1 storage qualification.

The CLI has a fixed host path allowlist. It does not invoke external commands,
read configuration files, or perform filesystem mutations. Run it with
operator-authorized privilege only when full host metadata is required.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from services.stt.artifacts import load_artifact_manifest, verify_artifact
from services.stt.config import ArtifactRoot, ModelConfig
from services.stt.domain import ModelIdentity

TARGETS = {
    "speech_platform": Path("/srv/speech-platform"),
    "models": Path("/srv/speech-platform/models"),
    "deployment_state": Path("/srv/speech-platform/deployment-state"),
    "model_store": Path("/var/tmp/speech-platform-m01e-fresh-v012/model-store"),
}
MAX_TREE_ENTRIES = 5000
MAX_TREE_DEPTH = 12
MODEL_ID = "large-v3-turbo"
MODEL_FAMILY = "whisper"
MODEL_REVISION = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
MODEL_MANIFEST_SHA256 = (
    "86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6"
)
MODEL_ARTIFACT_FORMAT = "ctranslate2-whisper"


def _decode_mount_field(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def _mount_table(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        separator = fields.index("-")
        records.append(
            {
                "mount_id": int(fields[0]),
                "device": fields[2],
                "mount_root": _decode_mount_field(fields[3]),
                "mount_point": Path(_decode_mount_field(fields[4])),
                "mount_options": fields[5],
                "filesystem": fields[separator + 1],
                "source": _decode_mount_field(fields[separator + 2]),
                "super_options": fields[separator + 3],
            }
        )
    return records


def _mount_for(path: Path, mounts: list[dict]) -> dict | None:
    candidates = [
        item
        for item in mounts
        if path == item["mount_point"] or item["mount_point"] in path.parents
    ]
    if not candidates:
        return None
    item = max(candidates, key=lambda record: len(record["mount_point"].parts))
    return {
        "mount_id": item["mount_id"],
        "device": item["device"],
        "mount_root": str(item["mount_root"]),
        "mount_point": str(item["mount_point"]),
        "filesystem": item["filesystem"],
        "source": item["source"],
        "mount_options": item["mount_options"],
        "super_options": item["super_options"],
    }


def _acl_status(path: Path, *, directory: bool) -> dict:
    if not hasattr(os, "getxattr"):
        return {"access": "unavailable", "default": "unavailable"}
    result = {}
    attributes = [("access", "system.posix_acl_access")]
    if directory:
        attributes.append(("default", "system.posix_acl_default"))
    else:
        result["default"] = "not_applicable"
    for label, attribute in attributes:
        try:
            os.getxattr(path, attribute, follow_symlinks=False)
        except OSError as error:
            if error.errno == errno.ENODATA:
                result[label] = "absent"
            elif error.errno in {errno.ENOTSUP, errno.EOPNOTSUPP}:
                result[label] = "unsupported"
            elif error.errno in {errno.EACCES, errno.EPERM}:
                result[label] = "inaccessible"
            else:
                result[label] = "error"
        else:
            result[label] = "present"
    return result


def _metadata(path: Path, *, relative: str | None = None) -> dict:
    try:
        info = path.lstat()
    except OSError as error:
        return {
            "path": str(path),
            "relative_path": relative,
            "status": "inaccessible",
            "error": errno.errorcode.get(error.errno, "OS_ERROR"),
        }
    if stat.S_ISDIR(info.st_mode):
        kind = "directory"
    elif stat.S_ISREG(info.st_mode):
        kind = "regular_file"
    elif stat.S_ISLNK(info.st_mode):
        kind = "symlink"
    else:
        kind = "other"
    result = {
        "path": str(path),
        "relative_path": relative,
        "status": "present",
        "kind": kind,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode_octal": f"{stat.S_IMODE(info.st_mode):04o}",
        "link_count": info.st_nlink,
        "device": info.st_dev,
        "inode": info.st_ino,
        "size_bytes": info.st_size if stat.S_ISREG(info.st_mode) else None,
        "symlink_target": os.readlink(path) if stat.S_ISLNK(info.st_mode) else None,
        "unexpected_hard_link": stat.S_ISREG(info.st_mode) and info.st_nlink != 1,
        "acl": _acl_status(path, directory=stat.S_ISDIR(info.st_mode)),
    }
    return result


def _existing_directory(path: Path) -> Path | None:
    current = path
    while True:
        try:
            info = current.lstat()
        except OSError:
            pass
        else:
            if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                return current
            if stat.S_ISLNK(info.st_mode):
                return None
        if current.parent == current:
            return None
        current = current.parent


def _capacity(path: Path) -> dict:
    existing = _existing_directory(path)
    if existing is None:
        return {"status": "unavailable", "measured_at": None}
    try:
        usage = os.statvfs(existing)
    except OSError as error:
        return {
            "status": "unavailable",
            "measured_at": str(existing),
            "error": errno.errorcode.get(error.errno, "OS_ERROR"),
        }
    return {
        "status": "available",
        "measured_at": str(existing),
        "total_bytes": usage.f_blocks * usage.f_frsize,
        "free_bytes": usage.f_bfree * usage.f_frsize,
        "available_bytes": usage.f_bavail * usage.f_frsize,
    }


def _inventory_tree(
    root: Path,
    *,
    recursive: bool,
    max_depth: int = MAX_TREE_DEPTH,
    max_entries: int = MAX_TREE_ENTRIES,
) -> dict:
    entries = []
    truncated = False
    try:
        root_info = root.lstat()
    except OSError as error:
        return {
            "status": "inaccessible",
            "error": errno.errorcode.get(error.errno, "OS_ERROR"),
            "entries": entries,
            "truncated": False,
        }
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        return {"status": "not_a_directory", "entries": entries, "truncated": False}

    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as iterator:
                children = []
                for child in iterator:
                    children.append(child)
                    if len(entries) + len(children) > max_entries:
                        truncated = True
                        break
            children.sort(key=lambda item: item.name)
        except OSError:
            entries.append(
                {
                    "relative_path": "."
                    if current == root
                    else str(current.relative_to(root)),
                    "status": "inaccessible",
                    "error": "DIRECTORY_READ_FAILED",
                }
            )
            continue
        child_directories = []
        for child in children:
            if len(entries) >= max_entries:
                truncated = True
                break
            child_path = Path(child.path)
            relative = child_path.relative_to(root).as_posix()
            entry = _metadata(child_path, relative=relative)
            entries.append(entry)
            if recursive and entry.get("kind") == "directory" and depth < max_depth:
                child_directories.append((child_path, depth + 1))
            elif recursive and entry.get("kind") == "directory":
                truncated = True
        if truncated:
            break
        stack.extend(reversed(child_directories))
    if stack:
        truncated = True
    partial = truncated or any(
        entry.get("status") == "inaccessible" for entry in entries
    )
    return {
        "status": "partial" if partial else "available",
        "entries": entries,
        "truncated": truncated,
    }


def _ancestry(path: Path, mounts: list[dict]) -> list[dict]:
    chain = list(reversed(path.parents)) + [path]
    output = []
    blocked = False
    for item in chain:
        if blocked:
            output.append(
                {"path": str(item), "status": "not_inspected_after_unsafe_ancestor"}
            )
            continue
        record = _metadata(item)
        record["filesystem"] = _mount_for(item, mounts)
        output.append(record)
        if record.get("kind") == "symlink" or record.get("status") == "inaccessible":
            blocked = True
    return output


def _parent_chain_is_safe(path: Path) -> bool:
    for component in reversed(path.parents):
        try:
            info = component.lstat()
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            return False
    return True


def _model_evidence(
    model_store: Path,
    *,
    verifier: Callable = verify_artifact,
    manifest_loader: Callable = load_artifact_manifest,
) -> dict:
    result = {
        "status": "unavailable",
        "model_store": str(model_store),
        "model_id": MODEL_ID,
        "manifest": None,
        "payloads": [],
        "verification": "not_run",
    }
    try:
        directory = model_store / MODEL_MANIFEST_SHA256
        artifact_directory = directory / "artifact"
        actual_manifest_path = directory / "manifest.yaml"
        for candidate in (model_store, directory, artifact_directory):
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ValueError("model directory is not a real directory")
        manifest_info = actual_manifest_path.lstat()
        if (
            stat.S_ISLNK(manifest_info.st_mode)
            or not stat.S_ISREG(manifest_info.st_mode)
            or manifest_info.st_nlink != 1
        ):
            raise ValueError("model manifest is not a single-link regular file")
        with actual_manifest_path.open("rb") as stream:
            raw_manifest = stream.read(1024 * 1024 + 1)
        if len(raw_manifest) > 1024 * 1024:
            result["status"] = "manifest_too_large"
            return result
        artifact_manifest = manifest_loader(actual_manifest_path, MODEL_MANIFEST_SHA256)
        model_identity = artifact_manifest["model"]
        artifact_identity = artifact_manifest["artifact"]
        result["manifest"] = {
            "path": str(actual_manifest_path),
            "readable": True,
            "bytes": len(raw_manifest),
            "raw_sha256": hashlib.sha256(raw_manifest).hexdigest(),
            "expected_identity_sha256": MODEL_MANIFEST_SHA256,
            "model_revision": model_identity["revision"],
            "artifact_format": artifact_identity["format"],
        }
        result["payloads"] = [
            {
                "path": entry["path"],
                "size_bytes": entry["size_bytes"],
                "sha256": entry["sha256"],
                "readable_and_verified": False,
            }
            for entry in artifact_manifest["files"]
        ]
        verifier(
            ModelConfig(
                MODEL_ID,
                ModelIdentity(MODEL_FAMILY, MODEL_REVISION),
                MODEL_ID,
                MODEL_MANIFEST_SHA256,
                MODEL_ARTIFACT_FORMAT,
            ),
            ArtifactRoot(artifact_directory, actual_manifest_path),
        )
        for payload in result["payloads"]:
            payload["readable_and_verified"] = True
        result["verification"] = "complete_manifest_and_payload_verification_passed"
        result["status"] = "available"
    except Exception as error:  # Output must not include arbitrary file contents.
        result["status"] = "verification_failed"
        result["verification"] = type(error).__name__
    return result


def inspect_storage(
    *,
    targets: Mapping[str, Path] = TARGETS,
    mountinfo_path: Path = Path("/proc/self/mountinfo"),
    model_verifier: Callable = verify_artifact,
    manifest_loader: Callable = load_artifact_manifest,
    collected_at: datetime | None = None,
) -> dict:
    """Collect only fixed-role storage metadata; injectable roots support tests."""
    if set(targets) != set(TARGETS):
        raise ValueError("storage inspection target roles are fixed")
    mounts = _mount_table(mountinfo_path)
    locations = {}
    for role, path in targets.items():
        shallow = role in {"speech_platform", "deployment_state"}
        ancestry_safe = _parent_chain_is_safe(path)
        structure = (
            _inventory_tree(path, recursive=not shallow)
            if ancestry_safe
            else {
                "status": "not_inspected_unsafe_or_inaccessible_ancestry",
                "entries": [],
                "truncated": False,
            }
        )
        locations[role] = {
            "path": str(path),
            "ancestry": _ancestry(path, mounts),
            "target": (
                _metadata(path)
                if ancestry_safe
                else {
                    "path": str(path),
                    "status": "not_inspected_unsafe_or_inaccessible_ancestry",
                }
            ),
            "filesystem": _mount_for(path, mounts),
            "capacity": (
                _capacity(path)
                if ancestry_safe
                else {"status": "unavailable", "measured_at": None}
            ),
            "structure": structure,
            "recursion": "immediate_children_only" if shallow else "bounded_tree",
        }
    if _parent_chain_is_safe(targets["model_store"]):
        model_evidence = _model_evidence(
            targets["model_store"],
            verifier=model_verifier,
            manifest_loader=manifest_loader,
        )
    else:
        model_evidence = {
            "status": "unsafe_or_inaccessible_ancestry",
            "model_store": str(targets["model_store"]),
            "model_id": MODEL_ID,
            "manifest": None,
            "payloads": [],
            "verification": "not_run",
        }
    moment = collected_at or datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "read_only": True,
        "collected_at_utc": moment.astimezone(timezone.utc).isoformat(),
        "scope": [str(targets[key]) for key in TARGETS],
        "mountinfo_source": str(mountinfo_path),
        "locations": locations,
        "model_artifact_evidence": model_evidence,
        "safety_limits": {
            "deployment_state_recursion": False,
            "max_tree_entries": MAX_TREE_ENTRIES,
            "max_tree_depth": MAX_TREE_DEPTH,
            "configuration_contents_read": False,
            "mutations_performed": False,
            "external_commands_executed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pretty", action="store_true", help="indent JSON output for review"
    )
    args = parser.parse_args()
    try:
        result = inspect_storage()
    except (OSError, ValueError, IndexError) as error:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "read_only": True,
                    "status": "inspection_incomplete",
                    "error": type(error).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
