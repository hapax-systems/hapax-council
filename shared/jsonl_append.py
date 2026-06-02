"""Single-writer-safe JSONL append for coordination ledgers.

Up to ~60 worktrees append to one HOME-based inode per ledger. ``O_APPEND`` alone
is atomic only for writes <= ``PIPE_BUF`` (4096B), and two live ledgers
(``cc-task-gate-decisions.jsonl`` at ~9KB, ``sdlc-invariant-findings.jsonl`` at
~3.4KB) exceed it; the Python writers also used buffered text-mode ``open("a")``
whose single logical record can split across multiple ``write()`` syscalls. A
per-file advisory ``flock`` held across one ``os.write`` of the fully-serialised
blob makes every append atomic for any record size, host-local.

Fails OPEN: a lock or IO failure returns ``False`` and never blocks the caller
(advisory-with-ledger; NEVER-FREEZE). A caller that must observe the error (the
coord JSONL mirror keeps a rich diagnostic) passes ``raising=True`` and wraps the
call in its own ``try``/``except``.

Byte identity: the serialisation is caller-controlled (``ensure_ascii`` /
``separators`` / ``sort_keys``, or an explicit ``serialize`` callback) so each
routed writer reproduces its pre-change bytes EXACTLY — the field-fix and the
event-sourcing replay round-trip stay uncoupled from this change.

``fcntl.flock`` is reliable only on a local filesystem; over NFS/CIFS it is
silently unreliable. All current ledgers are HOME-local single-host (podium
``~/.cache``). A future cross-host ledger (appendix, 192.168.68.50) MUST use a
single designated writer host or the SQLite/WAL canonical log — flock is
INSUFFICIENT cross-host; this helper introduces no cross-host write path.

The system ``flock(1)`` (util-linux) and ``fcntl.flock(2)`` both place a kernel
flock ``LOCK_EX`` on the inode, so a shell writer that locks the SAME sidecar
(``<name>.lock``) serialises with this helper — that is how the cc-task-gate
bash decision-log writer shares one lock with Python.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

_LOCK_SUFFIX = ".lock"

Record = Mapping[str, Any]
Serializer = Callable[[Record], str]


def _lock_path(target: Path) -> Path:
    """Sidecar lock path: ``<name>.lock`` beside the ledger.

    Keeping lock state off the data inode means truncation or rotation of the
    ledger never drops the lock; it MUST match the bash ``flock(1)`` sidecar.
    """
    return target.with_name(target.name + _LOCK_SUFFIX)


def _make_serializer(
    *, ensure_ascii: bool, separators: tuple[str, str], sort_keys: bool
) -> Serializer:
    def _serialize(record: Record) -> str:
        return json.dumps(
            dict(record), ensure_ascii=ensure_ascii, separators=separators, sort_keys=sort_keys
        )

    return _serialize


def append_jsonl(
    path: str | os.PathLike[str],
    record: Record,
    *,
    serialize: Serializer | None = None,
    ensure_ascii: bool = True,
    separators: tuple[str, str] = (", ", ": "),
    sort_keys: bool = False,
    raising: bool = False,
) -> bool:
    """Append one JSON record as a line, atomically across processes/worktrees.

    Returns ``True`` on durable append, ``False`` on a swallowed failure. Holds an
    exclusive ``flock`` on the ``<name>.lock`` sidecar across a single
    ``O_APPEND`` ``os.write`` so records > ``PIPE_BUF`` cannot interleave. The
    default serialisation matches bare ``json.dumps`` (``ensure_ascii=True``,
    spaced separators); pass ``serialize`` for an exact custom encoder.
    """
    return append_jsonl_lines(
        (record,),
        path,
        serialize=serialize,
        ensure_ascii=ensure_ascii,
        separators=separators,
        sort_keys=sort_keys,
        raising=raising,
    )


def append_jsonl_lines(
    records: Iterable[Record],
    path: str | os.PathLike[str],
    *,
    serialize: Serializer | None = None,
    ensure_ascii: bool = True,
    separators: tuple[str, str] = (", ", ": "),
    sort_keys: bool = False,
    raising: bool = False,
) -> bool:
    """Append many records under ONE lock acquisition (e.g. the findings loop).

    The whole batch is serialised, then written with a single ``os.write`` under
    one exclusive ``flock`` — the multi-row interleave risk is eliminated. Fails
    OPEN (returns ``False``) unless ``raising=True``.
    """
    target = Path(path)
    try:
        ser = serialize or _make_serializer(
            ensure_ascii=ensure_ascii, separators=separators, sort_keys=sort_keys
        )
        blob = "".join(ser(record) + "\n" for record in records).encode("utf-8")
        if not blob:
            return True
        target.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(_lock_path(target), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)  # blocking; ledger appends are sub-ms
            data_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(data_fd, blob)  # single syscall under the lock
            finally:
                os.close(data_fd)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        return True
    except Exception:  # noqa: BLE001 — advisory ledger; fail OPEN unless asked to raise.
        if raising:
            raise
        return False
