"""Fail-closed integrity checks for a small allowlist of tracked inputs."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Callable, Mapping


TRACKED_SOURCE_PATHS = {
    "compose.yaml": Path("deployments/compose/compose.yaml"),
    "compose.stt-cuda.yaml": Path("deployments/compose/compose.stt-cuda.yaml"),
    "release.yaml": Path("releases/voiceservice-v0.1.2.yaml"),
}
COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
OBJECT_RE = re.compile(r"^[0-9a-f]{40,64}$")
TRUSTED_UIDS = frozenset({0})


class TrackedSourceError(ValueError):
    """Tracked source cannot be proven to match the approved Git tree."""


CommandRunner = Callable[..., subprocess.CompletedProcess]


def _run(command, *, cwd, input=None):
    return subprocess.run(
        command,
        cwd=cwd,
        input=input,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _checked(runner, command, *, cwd, input=None) -> bytes:
    try:
        result = runner(command, cwd=cwd, input=input)
    except Exception:
        raise TrackedSourceError("tracked source evidence command failed") from None
    if result.returncode != 0:
        raise TrackedSourceError("tracked source evidence is unavailable")
    value = result.stdout
    return value if isinstance(value, bytes) else str(value).encode()


def _is_trusted_uid(uid: int, current_uid: int) -> bool:
    return uid == current_uid or uid in TRUSTED_UIDS


def _group_membership(runner, gid: int, *, cwd: Path, current_uid: int) -> None:
    try:
        passwd = _checked(runner, ["getent", "passwd"], cwd=cwd).decode(
            "utf-8", errors="strict"
        )
        group = _checked(runner, ["getent", "group", str(gid)], cwd=cwd).decode(
            "utf-8", errors="strict"
        )
    except (TrackedSourceError, UnicodeError):
        raise TrackedSourceError(
            "tracked source group membership evidence is unavailable"
        ) from None
    uid_by_name = {}
    primary_gids = {}
    try:
        for line in passwd.splitlines():
            fields = line.split(":")
            if len(fields) < 4:
                raise ValueError
            uid, primary_gid = int(fields[2]), int(fields[3])
            uid_by_name[fields[0]] = uid
            primary_gids[fields[0]] = primary_gid
        entries = [line.split(":") for line in group.splitlines()]
        entries = [entry for entry in entries if len(entry) == 4]
        if len(entries) != 1 or int(entries[0][2]) != gid:
            raise ValueError
        member_names = set(filter(None, entries[0][3].split(",")))
        member_names.update(
            name for name, primary_gid in primary_gids.items() if primary_gid == gid
        )
        if not any(uid == current_uid for uid in uid_by_name.values()):
            raise ValueError
        if any(
            name not in uid_by_name
            or not _is_trusted_uid(uid_by_name[name], current_uid)
            for name in member_names
        ):
            raise ValueError
    except (UnicodeError, ValueError, IndexError):
        raise TrackedSourceError(
            "tracked source group membership could not be trusted"
        ) from None


def _check_metadata(path: Path, *, repo: Path, current_uid: int, runner) -> None:
    try:
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError
        resolved = path.resolve(strict=True)
        if resolved != path.absolute() or repo not in resolved.parents:
            raise ValueError
        relative = resolved.relative_to(repo)
        if relative not in TRACKED_SOURCE_PATHS.values():
            raise ValueError
        components = list(reversed(repo.parents)) + [repo]
        current = repo
        for part in relative.parts[:-1]:
            current = current / part
            components.append(current)
        for directory in components:
            info = directory.lstat()
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                opened = os.fstat(fd)
                xattrs = os.listxattr(fd)
            finally:
                os.close(fd)
            mode = stat.S_IMODE(info.st_mode)
            if (
                not stat.S_ISDIR(info.st_mode)
                or not _is_trusted_uid(info.st_uid, current_uid)
                or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino)
                or (mode & 0o002 and not (info.st_uid == 0 and mode & stat.S_ISVTX))
                or any(x.startswith("system.posix_acl_") for x in xattrs)
            ):
                raise ValueError
            if mode & 0o020:
                _group_membership(
                    runner, info.st_gid, cwd=repo, current_uid=current_uid
                )
        info = resolved.lstat()
        fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            opened = os.fstat(fd)
            xattrs = os.listxattr(fd)
        finally:
            os.close(fd)
        mode = stat.S_IMODE(info.st_mode)
        if (
            not stat.S_ISREG(info.st_mode)
            or not _is_trusted_uid(info.st_uid, current_uid)
            or info.st_nlink != 1
            or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino)
            or mode & 0o002
            or mode & ~0o777
            or any(x.startswith("system.posix_acl_") for x in xattrs)
        ):
            raise ValueError
        if mode & 0o020:
            _group_membership(runner, info.st_gid, cwd=repo, current_uid=current_uid)
    except TrackedSourceError:
        raise
    except Exception:
        raise TrackedSourceError(
            "tracked source ownership, path, ACL or file identity is unsafe"
        ) from None


def _read_stable(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            before = os.fstat(fd)
            chunks = []
            total = 0
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 16 * 1024 * 1024:
                    raise ValueError
                chunks.append(chunk)
            after = os.fstat(fd)
            current = path.lstat()
        finally:
            os.close(fd)
        first = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
        )
        second = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
        )
        current_identity = (
            current.st_dev,
            current.st_ino,
            current.st_size,
            current.st_mtime_ns,
            current.st_ctime_ns,
            current.st_mode,
            current.st_uid,
            current.st_gid,
            current.st_nlink,
        )
        raw = b"".join(chunks)
        if first != second or first != current_identity or len(raw) != before.st_size:
            raise ValueError
        return raw
    except Exception:
        raise TrackedSourceError("tracked source changed while being read") from None


def validate_tracked_sources(
    source_paths: Mapping[str, Path],
    captured_bytes: Mapping[str, bytes] | None,
    *,
    approved_revision: str,
    repository_root: Path,
    runner: CommandRunner = _run,
    current_uid: int | None = None,
) -> dict[str, str]:
    """Prove the allowlisted files and captured bytes match one exact commit."""
    repo = Path(repository_root).resolve(strict=True)
    uid = os.getuid() if current_uid is None else current_uid
    if not isinstance(approved_revision, str) or not COMMIT_RE.fullmatch(
        approved_revision
    ):
        raise TrackedSourceError("approved Git commit identity is malformed")
    if set(source_paths) != set(TRACKED_SOURCE_PATHS):
        raise TrackedSourceError("tracked source role set is invalid")
    if captured_bytes is not None and set(captured_bytes) != set(TRACKED_SOURCE_PATHS):
        raise TrackedSourceError("captured tracked source role set is invalid")

    try:
        resolved_commit = (
            _checked(
                runner,
                ["git", "rev-parse", "--verify", f"{approved_revision}^{{commit}}"],
                cwd=repo,
            )
            .decode("ascii")
            .strip()
        )
    except UnicodeError:
        raise TrackedSourceError("approved Git commit identity is invalid") from None
    if resolved_commit != approved_revision:
        raise TrackedSourceError("approved Git commit did not resolve exactly")

    relative_paths = [str(TRACKED_SOURCE_PATHS[role]) for role in sorted(source_paths)]
    for command in (
        ["git", "diff", "--quiet", approved_revision, "--", *relative_paths],
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
            approved_revision,
            "--",
            *relative_paths,
        ],
    ):
        try:
            result = runner(command, cwd=repo, input=None)
        except Exception:
            raise TrackedSourceError("tracked Git status is unavailable") from None
        if result.returncode != 0:
            raise TrackedSourceError("tracked source has staged or working changes")

    tree = _checked(
        runner,
        ["git", "ls-tree", "-z", approved_revision, "--", *relative_paths],
        cwd=repo,
    )
    tree_entries = {}
    try:
        for entry in tree.split(b"\0"):
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split()
            tree_entries[raw_path.decode("utf-8")] = (mode, kind, object_id)
    except (UnicodeError, ValueError):
        raise TrackedSourceError("approved Git tree evidence is malformed") from None

    identities = {}
    for role, expected_relative in TRACKED_SOURCE_PATHS.items():
        if source_paths[role].absolute() != (repo / expected_relative).absolute():
            raise TrackedSourceError("tracked source path differs from approved role")
        tree_entry = tree_entries.get(str(expected_relative))
        if (
            tree_entry is None
            or tree_entry[0] != "100644"
            or tree_entry[1] != "blob"
            or not OBJECT_RE.fullmatch(tree_entry[2])
        ):
            raise TrackedSourceError("approved Git blob identity is invalid")
        _check_metadata(source_paths[role], repo=repo, current_uid=uid, runner=runner)
        try:
            committed = _checked(
                runner,
                ["git", "cat-file", "blob", f"{approved_revision}:{expected_relative}"],
                cwd=repo,
            )
            working = _read_stable(source_paths[role])
            expected_captured = (
                working if captured_bytes is None else captured_bytes[role]
            )
            object_id = (
                _checked(
                    runner,
                    ["git", "hash-object", "--stdin"],
                    cwd=repo,
                    input=expected_captured,
                )
                .decode("ascii")
                .strip()
            )
        except (OSError, UnicodeError):
            raise TrackedSourceError("tracked source bytes are unavailable") from None
        if (
            committed != working
            or expected_captured != working
            or object_id != tree_entry[2]
        ):
            raise TrackedSourceError(
                "tracked source bytes differ from approved Git blob"
            )
        identities[role] = object_id
    return identities
