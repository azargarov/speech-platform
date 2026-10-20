"""Host-local advisory deployment locks shared by project coordinators."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import time
from pathlib import Path

from scripts.deployment_state import (
    DEFAULT_STATE_ROOT,
    _filesystem_type,
    _reject_symlink_components,
)

DEFAULT_LOCK_ROOT = DEFAULT_STATE_ROOT / "locks"
LOCK_WAIT_SECONDS = 0.0
PROJECT_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")


class LockError(RuntimeError):
    """A deployment lock is unsafe, unavailable, busy, or has uncertain work."""


def _validate_root(root: Path, uid: int) -> None:
    if not root.is_absolute() or ".." in root.parts:
        raise LockError("deployment lock root must be an absolute path")
    try:
        _reject_symlink_components(root)
        if not root.exists():
            root.mkdir(mode=0o700)
        info = root.lstat()
    except OSError as error:
        raise LockError("deployment lock root is unavailable") from error
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid:
        raise LockError("deployment lock root owner or type is unsafe")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise LockError("deployment lock root permissions must be 0700")
    if _filesystem_type(root) not in {"ext4", "xfs", "btrfs"}:
        raise LockError("deployment lock filesystem is not an approved local type")


class ProjectLock:
    """Exclusive, non-unlinked project lock with a persistent uncertainty gate."""

    def __init__(
        self,
        project_name: str,
        root: str | Path | None = None,
        *,
        wait_seconds: float = LOCK_WAIT_SECONDS,
        expected_uid: int | None = None,
    ) -> None:
        if not isinstance(project_name, str) or not PROJECT_KEY.fullmatch(project_name):
            raise LockError("Compose project identity is invalid")
        if not isinstance(wait_seconds, (int, float)) or wait_seconds < 0:
            raise LockError("lock wait interval is invalid")
        self.project_name = project_name
        configured_root = root or os.environ.get("SPEECH_PLATFORM_LOCK_ROOT")
        self.root = Path(configured_root or DEFAULT_LOCK_ROOT)
        self.expected_uid = os.getuid() if expected_uid is None else expected_uid
        self.wait_seconds = float(wait_seconds)
        self.fd: int | None = None
        self.path = self.root / f"{project_name}.lock"
        self.uncertain_path = self.root / f"{project_name}.uncertain"
        self._lock_identity: tuple[int, int] | None = None
        self._uncertain_identity: tuple[int, int] | None = None

    def acquire(self, *, recovery: bool = False) -> "ProjectLock":
        try:
            _validate_root(self.root, self.expected_uid)
        except LockError:
            raise
        except (OSError, ValueError) as error:
            raise LockError(
                "deployment lock root failed filesystem validation"
            ) from error
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags, 0o600)
            info = os.fstat(fd)
            path_info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.expected_uid:
                raise LockError("project lock file owner or type is unsafe")
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise LockError("project lock file permissions must be 0600")
            if (info.st_dev, info.st_ino) != (path_info.st_dev, path_info.st_ino):
                raise LockError("project lock file changed while opening")
            self.fd = fd
            self._lock_identity = (info.st_dev, info.st_ino)
            deadline = time.monotonic() + self.wait_seconds
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as error:
                    if time.monotonic() >= deadline:
                        raise LockError(
                            "deployment operation is already active for this project"
                        ) from error
                    time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            self._verify_inode()
            if self.uncertain_path.exists() or self.uncertain_path.is_symlink():
                self._validate_uncertain_marker()
                if not recovery:
                    raise LockError(
                        "a prior deployment was interrupted; operator review is required"
                    )
            return self
        except LockError:
            self.release()
            raise
        except OSError as error:
            self.release()
            raise LockError(
                "could not safely acquire the project deployment lock"
            ) from error

    def resolve_uncertainty(
        self, *, approval_reference: str, determination: str
    ) -> None:
        """Record an explicit recovery decision, then remove the gate."""
        self._verify_inode()
        if self.fd is None:
            raise LockError("recovery resolution requires the exclusive project lock")
        if not isinstance(approval_reference, str) or not approval_reference.strip():
            raise LockError("recovery approval reference is required")
        if not isinstance(determination, str) or not determination.strip():
            raise LockError("recovery determination is required")
        self._validate_uncertain_marker()
        marker_info = self.uncertain_path.lstat()
        audit_path = self.root / (
            f"{self.project_name}.resolved.{time.time_ns()}.{os.getpid()}"
        )
        record = {
            "project": self.project_name,
            "operator_uid": os.getuid(),
            "approval_reference": approval_reference,
            "determination": determination,
            "resolved_at_ns": time.time_ns(),
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
        try:
            fd = os.open(audit_path, flags, 0o600)
            try:
                os.write(fd, (json.dumps(record, sort_keys=True) + "\n").encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            directory_fd = os.open(
                self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            current = self.uncertain_path.lstat()
            if (current.st_dev, current.st_ino) != (
                marker_info.st_dev,
                marker_info.st_ino,
            ):
                raise LockError("deployment uncertainty record was replaced")
            self.uncertain_path.unlink()
            directory_fd = os.open(
                self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as error:
            raise LockError("could not durably record recovery resolution") from error

    def _verify_inode(self) -> None:
        assert self.fd is not None and self._lock_identity is not None
        try:
            opened = os.fstat(self.fd)
            current = self.path.lstat()
        except OSError as error:
            raise LockError("project lock file was replaced or removed") from error
        if self._lock_identity != (
            opened.st_dev,
            opened.st_ino,
        ) or self._lock_identity != (
            current.st_dev,
            current.st_ino,
        ):
            raise LockError("project lock file was unexpectedly replaced")

    def assert_current(self) -> None:
        """Fail if the persistent path no longer names the locked inode."""
        self._verify_inode()

    def _validate_uncertain_marker(self) -> None:
        try:
            info = self.uncertain_path.lstat()
        except OSError as error:
            raise LockError("deployment uncertainty record is inaccessible") from error
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != self.expected_uid
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise LockError("deployment uncertainty record is unsafe")

    def mark_mutation_started(self) -> None:
        self._verify_inode()
        if self._uncertain_identity is not None:
            return
        try:
            fd = os.open(
                self.uncertain_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
            )
            info = os.fstat(fd)
            self._uncertain_identity = (info.st_dev, info.st_ino)
            try:
                os.write(fd, b"deployment mutation in progress\n")
                os.fsync(fd)
            finally:
                os.close(fd)
            directory_fd = os.open(
                self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except FileExistsError as error:
            raise LockError(
                "a prior deployment was interrupted; operator review is required"
            ) from error
        except OSError as error:
            raise LockError("could not record deployment mutation state") from error

    def mark_complete(self) -> None:
        self._verify_inode()
        if self._uncertain_identity is None:
            return
        try:
            current = self.uncertain_path.lstat()
            if (current.st_dev, current.st_ino) != self._uncertain_identity:
                raise LockError(
                    "deployment uncertainty record was unexpectedly replaced"
                )
            self.uncertain_path.unlink()
            directory_fd = os.open(
                self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self._uncertain_identity = None
        except LockError:
            raise
        except OSError as error:
            raise LockError("could not clear deployment uncertainty record") from error

    def release(self) -> None:
        fd, self.fd = self.fd, None
        if fd is not None:
            # Closing our reference preserves the lock while any child or
            # descendant still holds the inherited open-file description.
            # LOCK_UN would release it for every inherited descriptor.
            os.close(fd)

    def __enter__(self) -> "ProjectLock":
        return self.acquire()

    def __exit__(self, _type, _value, _traceback) -> None:
        self.release()
