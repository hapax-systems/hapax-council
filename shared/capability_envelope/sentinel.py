"""Boundary observation for the envelope: did anything open a sentinel file?

Canary C10 (DESIGN v1.3 section 1.2) plants sentinel files wherever a harness might import from,
runs the job, and fails on any open of a sentinel. Asking the model what it saw is complementary
evidence, never the check. The watch uses inotify, which needs no privilege and sees opens made
through bind mounts, because a bind mount exposes the same inode.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import secrets
import struct
from collections.abc import Iterable
from pathlib import Path
from types import TracebackType

_IN_ACCESS = 0x00000001
_IN_OPEN = 0x00000020
_IN_NONBLOCK = 0o4000
_IN_CLOEXEC = 0o2000000
_EVENT_HEADER = struct.Struct("iIII")


def sentinel_token(label: str) -> str:
    """A unique marker to plant in a sentinel file and search for in job output."""
    return f"HAPAX-SENTINEL-{label}-{secrets.token_hex(6)}"


def find_tokens(text: str, tokens: Iterable[str]) -> set[str]:
    """The tokens that occur in ``text``."""
    return {token for token in tokens if token in text}


class OpenWatch:
    """Record every open or read of the given files while the context is active."""

    def __init__(self, paths: Iterable[Path]) -> None:
        self._paths = [Path(p) for p in paths]
        self._fd = -1
        self._watches: dict[int, Path] = {}
        self._opened: set[Path] = set()

    def __enter__(self) -> OpenWatch:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        fd = libc.inotify_init1(_IN_NONBLOCK | _IN_CLOEXEC)
        if fd < 0:
            err = ctypes.get_errno()
            raise OSError(
                err,
                f"inotify_init1 failed: {os.strerror(err)}; next action: raise "
                "fs.inotify.max_user_instances or run the audit on another host",
            )
        self._fd = fd
        for path in self._paths:
            wd = libc.inotify_add_watch(fd, os.fsencode(path), _IN_OPEN | _IN_ACCESS)
            if wd < 0:
                err = ctypes.get_errno()
                self.close()
                raise OSError(
                    err,
                    f"cannot watch sentinel {path}: {os.strerror(err)}; next "
                    "action: plant the sentinel before starting the watch",
                )
            self._watches[wd] = path
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._drain()
        self.close()

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def _drain(self) -> None:
        while self._fd >= 0:
            try:
                buf = os.read(self._fd, 65536)
            except BlockingIOError:
                return
            offset = 0
            while offset + _EVENT_HEADER.size <= len(buf):
                wd, _mask, _cookie, name_len = _EVENT_HEADER.unpack_from(buf, offset)
                if wd in self._watches:
                    self._opened.add(self._watches[wd])
                offset += _EVENT_HEADER.size + name_len

    def opened(self) -> set[Path]:
        """The watched files something opened or read, so far."""
        self._drain()
        return set(self._opened)
