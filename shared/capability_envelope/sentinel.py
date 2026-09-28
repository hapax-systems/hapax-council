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
import time
from collections.abc import Iterable
from pathlib import Path
from types import TracebackType

_IN_ACCESS = 0x00000001
_IN_OPEN = 0x00000020
_IN_Q_OVERFLOW = 0x00004000
_IN_NONBLOCK = 0o4000
_IN_CLOEXEC = 0o2000000
_EVENT_HEADER = struct.Struct("iIII")
_READ_SIZE = 65536
# A drain that happens after the watched work has returned still waits this long with no new
# event: a grandchild that closed its pipes can open a sentinel after its parent returned, and
# that event is queued after the process the caller waited for is gone (clause (6) of the row).
_SETTLE_SECONDS = 0.5
# Hard bound on that wait, so a writer that never stops cannot wedge a drain.
_SETTLE_BOUND_SECONDS = 30.0
# Poll interval while settling: short enough not to overshoot the settle window.
_POLL_SECONDS = 0.01


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
        self._overflowed = False
        self._truncated = False
        self._buf = b""

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
        self._drain(settle=True)
        self.close()

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def _drain(self, *, settle: bool = False) -> None:
        """Read the queue, keeping any partial event for the next read.

        An event can straddle two reads; a drain that restarts parsing at each read misparses the
        tail, so the leftover bytes are carried into the next read — the buffer lives on the
        instance for that, not in this call (review of #4793, gemini-1, 2026-09-28). Linux returns
        only whole events from an inotify fd, so the straddle is belt-and-braces rather than the
        only guard, and the straddle test pins the parser's own behaviour.

        ``settle`` is the drain-after-return path used by ``__exit__``: the queue is read until a
        settle window passes with no new event, bounded by ``_SETTLE_BOUND_SECONDS``. Hitting that
        bound with the queue still being written sets ``_truncated``, because the read is then
        incomplete and the caller must not read it as a complete observation.
        """
        buf = self._buf
        quiet_since: float | None = None
        deadline = time.monotonic() + _SETTLE_BOUND_SECONDS if settle else None
        while self._fd >= 0:
            # The bound is checked here, not only on the empty-queue branch: a queue written
            # continuously never raises EAGAIN, so a bound checked only there would never fire
            # (found while testing the truncated path, 2026-09-28).
            if deadline is not None and time.monotonic() >= deadline:
                self._truncated = True
                self._buf = buf
                return
            while len(buf) >= _EVENT_HEADER.size:
                wd, mask, _cookie, name_len = _EVENT_HEADER.unpack_from(buf, 0)
                # An overflowed queue means opens were dropped: the observation is incomplete,
                # which must read as inconclusive, never as "nothing was opened" (review of
                # #4793, codex-1, 2026-09-28).
                if mask & _IN_Q_OVERFLOW or wd == -1:
                    self._overflowed = True
                event_len = _EVENT_HEADER.size + name_len
                if len(buf) < event_len:
                    break
                if wd in self._watches:
                    self._opened.add(self._watches[wd])
                buf = buf[event_len:]
            try:
                buf += os.read(self._fd, _READ_SIZE)
                quiet_since = None
            except BlockingIOError:
                if not settle:
                    self._buf = buf
                    return
                now = time.monotonic()
                if quiet_since is None:
                    quiet_since = now
                elif now - quiet_since >= _SETTLE_SECONDS:
                    self._buf = buf
                    return
                if deadline is not None and now >= deadline:
                    # The bound is a safety valve, not a licence to report a complete
                    # observation: events may still be arriving, so the read is TRUNCATED and the
                    # caller must treat it like an overflow (review of #4793, codex-1, 2026-09-28).
                    self._truncated = True
                    self._buf = buf
                    return
                time.sleep(_POLL_SECONDS)

    def opened(self) -> set[Path]:
        """The watched files something opened or read, so far."""
        self._drain()
        return set(self._opened)

    def overflowed(self) -> bool:
        """Whether the kernel dropped events from the watch queue.

        An overflowed queue can hide an open, so a caller must treat the observation as
        inconclusive rather than clean.
        """
        self._drain()
        return self._overflowed

    def truncated(self) -> bool:
        """Whether the drain hit its settle bound with the queue still being written.

        A truncated read can hide an open, exactly as an overflow does.
        """
        self._drain()
        return self._truncated
