"""Static host checks and actual write probe for the diagnostic report mount."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class ReportMountPreflightError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
        self.diagnostic_code = code


def _fail(code: str) -> None:
    raise ReportMountPreflightError(code)


def _has_acl(path: Path) -> bool:
    try:
        names = os.listxattr(path, follow_symlinks=False)
    except OSError:
        _fail("report_mount_acl_unreadable")
    return any(
        name in {"system.posix_acl_access", "system.posix_acl_default"}
        for name in names
    )


def validate_static_report_mount(
    directory: str | Path,
    command: list[str],
    *,
    expected_group: int,
    container_uid: int = 65532,
    container_gid: int = 65532,
) -> dict:
    """Validate host metadata and Docker identity/mount arguments, without impersonation."""
    path = Path(directory)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        _fail("report_mount_directory_missing_or_unsafe")
    for parent in (path, *path.parents):
        if parent.is_symlink() or not parent.is_dir() or not os.access(parent, os.X_OK):
            _fail("report_mount_parent_traversal_unavailable")
        if _has_acl(parent):
            _fail("report_mount_acl_present")

    metadata = path.stat(follow_symlinks=False)
    if metadata.st_uid != os.geteuid():
        _fail("report_mount_owner_mismatch")
    if metadata.st_gid != expected_group:
        _fail("report_mount_group_mismatch")
    if stat.S_IMODE(metadata.st_mode) != 0o2770:
        _fail("report_mount_mode_mismatch")
    host_groups = set(os.getgroups()) | {os.getegid()}
    if expected_group not in host_groups:
        _fail("report_mount_host_group_unavailable")

    args = command[2:] if len(command) >= 2 else []
    user = None
    groups = []
    mounts = []
    readonly_root = False
    for index, arg in enumerate(args):
        if arg == "--user" and index + 1 < len(args):
            user = args[index + 1]
        elif arg.startswith("--user="):
            user = arg.partition("=")[2]
        elif arg == "--group-add" and index + 1 < len(args):
            groups.extend(args[index + 1].split(","))
        elif arg.startswith("--group-add="):
            groups.extend(arg.partition("=")[2].split(","))
        elif arg == "--mount" and index + 1 < len(args):
            mounts.append(args[index + 1])
        elif arg.startswith("--mount="):
            mounts.append(arg.partition("=")[2])
        elif arg == "--read-only":
            readonly_root = True
    if user != f"{container_uid}:{container_gid}":
        _fail("report_mount_container_identity_mismatch")
    if groups != [str(expected_group)]:
        _fail("report_mount_supplementary_group_mismatch")
    if not readonly_root:
        _fail("report_mount_root_filesystem_not_readonly")

    expected_mount = False
    for mount in mounts:
        fields = dict(part.split("=", 1) for part in mount.split(",") if "=" in part)
        flags = set(mount.split(","))
        if (
            fields.get("type") == "bind"
            and Path(fields.get("src", "")) == path
            and fields.get("dst") == "/results"
            and "readonly" not in flags
            and "ro" not in flags
        ):
            expected_mount = True
    if not expected_mount:
        _fail("report_mount_bind_configuration_invalid")
    return {
        "owner_uid": metadata.st_uid,
        "group_gid": metadata.st_gid,
        "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
        "acl": "none",
        "container_uid": container_uid,
        "container_gid": container_gid,
        "supplementary_gids": groups,
        "bind_destination": "/results",
        "bind_readonly": False,
        "root_readonly": True,
    }


def validate_container_report_mount(
    report_path: str | Path, atomic_writer, *, cuda_requested: bool = True
) -> dict:
    """Prove effective container access through atomic create, replace and read."""
    target = Path(report_path)
    try:
        if target.parent.is_symlink() or not target.parent.is_dir():
            _fail("report_mount_directory_missing_or_unsafe")
        running = {
            "schema_version": 1,
            "outcome": "running",
            "cuda_requested": cuda_requested,
            "cpu_fallback": False,
            "preflight": {"report_mount": "running"},
            "stages": [],
        }
        atomic_writer(target, running)
        running["preflight"]["report_mount"] = "pass"
        atomic_writer(target, running)
        import json

        saved = json.loads(target.read_text(encoding="utf-8"))
        metadata = target.stat(follow_symlinks=False)
        groups = set(os.getgroups()) | {os.getegid()}
        if saved != running or metadata.st_uid != os.geteuid():
            _fail("report_mount_write_verification_failed")
        if metadata.st_gid not in groups:
            _fail("report_mount_group_not_effective")
        if stat.S_IMODE(metadata.st_mode) != 0o640:
            _fail("report_mount_report_mode_invalid")
        return {
            "write": "pass",
            "atomic_replace": "pass",
            "readback": "pass",
            "report_mode": "0640",
        }
    except ReportMountPreflightError as exc:
        try:
            atomic_writer(
                target,
                {
                    "schema_version": 1,
                    "outcome": "fail",
                    "cuda_requested": cuda_requested,
                    "cpu_fallback": False,
                    "preflight": {
                        "report_mount": "fail",
                        "diagnostic_code": exc.code,
                    },
                    "stages": [],
                },
            )
        except Exception:
            pass
        raise
    except Exception:
        try:
            atomic_writer(
                target,
                {
                    "schema_version": 1,
                    "outcome": "fail",
                    "cuda_requested": cuda_requested,
                    "cpu_fallback": False,
                    "preflight": {
                        "report_mount": "fail",
                        "diagnostic_code": "report_mount_write_failed",
                    },
                    "stages": [],
                },
            )
        except Exception:
            pass
        _fail("report_mount_write_failed")
