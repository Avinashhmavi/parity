"""Cross-process file lock so sync, export and apply never interleave."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:  # POSIX
    import fcntl

    def _lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)

except ImportError:  # Windows
    import msvcrt

    def _lock(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


class LockTimeout(RuntimeError):
    pass


@contextmanager
def file_lock(path: Path, timeout: float = 120.0, poll: float = 0.1) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT)
    deadline = time.monotonic() + timeout
    try:
        while not _lock(fd):
            if time.monotonic() >= deadline:
                raise LockTimeout(f"could not lock {path} within {timeout:.0f}s; is another sync running?")
            time.sleep(poll)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)
