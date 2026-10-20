"""Small durable filesystem primitives shared by B1 and private snapshots."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Callable


def fsync_directory(path: Path, fsync: Callable[[int], None] = os.fsync) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fsync(fd)
    finally:
        os.close(fd)


def mkdir_private(path: Path, fsync: Callable[[int], None] = os.fsync) -> None:
    """Create one new private directory and durably record it in its parent."""
    path = Path(path)
    path.mkdir(mode=0o700)
    # mkdir's mode is filtered by umask; chmod only the directory just created.
    os.chmod(path, 0o700, follow_symlinks=False)
    for directory in (path, path.parent):
        fsync_directory(directory, fsync)


def publish_immutable_file(
    directory: Path,
    name: str,
    data: bytes,
    *,
    fsync: Callable[[int], None] = os.fsync,
    before_publish: Callable[[Path, Path], None] | None = None,
    replace: bool = False,
) -> None:
    """Durably publish a mode-0600 file by replacement or no-replace link."""
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or not re.fullmatch(r"[A-Za-z0-9._-]+", name)
    ):
        raise ValueError("published file name is invalid")
    directory = Path(directory)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary_name = f".pending-{uuid.uuid4().hex}"
    try:
        fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        temporary_path = directory / temporary_name
        target_path = directory / name
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                fsync(stream.fileno())
            if before_publish is not None:
                before_publish(temporary_path, target_path)
            if replace:
                os.replace(
                    temporary_name,
                    name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
            else:
                os.link(
                    temporary_name,
                    name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                os.unlink(temporary_name, dir_fd=directory_fd)
            fsync(directory_fd)
        finally:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
    finally:
        os.close(directory_fd)
