"""Daily rotation of the refusal log into the operator's archive.

The writer (``agents.refusal_brief.writer``) appends to ``log.jsonl``
in tmpfs (``/dev/shm/hapax-refusals/``). At midnight UTC a timer
fires this rotator:

1. Atomically rename ``log.jsonl`` → ``log.<date>.<pid>.rotating``
   (POSIX rename leaves concurrent writers' file descriptors valid;
   subsequent ``append()`` calls re-open under the original name).
2. Append-gzip the ``.rotating`` slice into
   ``~/hapax-state/refusals/<date>.jsonl.gz`` (gzip's stream-concat
   semantics make this safe across multiple same-day rotations —
   gunzip handles concatenated members transparently).
3. Unlink the ``.rotating`` slice.

The archive copy is the operator's record and is never deleted by
this daemon; the spec is explicit that any ``delete()`` / ``clear()``
affordance creates HITL pressure and is constitutionally disallowed.
"""

from __future__ import annotations

import gzip
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from prometheus_client import Counter

from agents.refusal_brief.writer import DEFAULT_LOG_PATH

log = logging.getLogger(__name__)

DEFAULT_ARCHIVE_DIR = Path(
    os.environ.get(
        "HAPAX_REFUSALS_ARCHIVE_DIR",
        str(Path.home() / "hapax-state" / "refusals"),
    )
)


# Outcomes:
#   ok      — log rotated + archive updated + tmp slice removed
#   noop    — log absent or empty (nothing to archive)
#   partial — rename succeeded but gzip / unlink path raised; tmp slice
#             may be left behind for next run to recover
#   error   — rename itself failed (perms / fs full); log untouched
refusal_rotations_total = Counter(
    "hapax_refusal_rotations_total",
    "Refusal log rotation attempts.",
    ["result"],
)


def _utc_today_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).date().isoformat()


def rotate(
    *,
    log_path: Path = DEFAULT_LOG_PATH,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
    now: datetime | None = None,
) -> str:
    """Rotate the live refusal log into the day-archive; return outcome.

    Outcome is one of ``"ok"``, ``"noop"``, ``"partial"``, ``"error"``
    — also emitted as the ``result`` label on
    :data:`refusal_rotations_total`. Best-effort: failure paths log
    and return rather than raise so the systemd timer never enters
    backoff state for a transient fs hiccup.

    Concurrency note: POSIX ``rename`` leaves any open file
    descriptors pointing at the renamed inode, so a writer mid-flush
    completes its append into the ``.rotating`` slice (which gets
    archived). The next ``append()`` re-opens ``log.jsonl`` (now
    absent) under the original name, creating a fresh file. No write
    is lost.
    """
    iso = _utc_today_iso(now)

    if not log_path.exists() or log_path.stat().st_size == 0:
        refusal_rotations_total.labels(result="noop").inc()
        return "noop"

    rotating_path = log_path.with_name(f"{log_path.name}.{iso}.{os.getpid()}.rotating")
    archive_path = archive_dir / f"{iso}.jsonl.gz"

    try:
        os.replace(log_path, rotating_path)
    except OSError:
        log.warning("refusal log rotate: rename failed at %s", log_path, exc_info=True)
        refusal_rotations_total.labels(result="error").inc()
        return "error"

    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        # Append-mode gzip: gunzip transparently concatenates members,
        # so multiple same-day rotations produce a single readable file.
        with rotating_path.open("rb") as src, gzip.open(archive_path, "ab") as dst:
            shutil.copyfileobj(src, dst)
        rotating_path.unlink()
    except OSError:
        log.warning(
            "refusal log rotate: archive path failed for %s (slice left at %s)",
            archive_path,
            rotating_path,
            exc_info=True,
        )
        refusal_rotations_total.labels(result="partial").inc()
        return "partial"

    refusal_rotations_total.labels(result="ok").inc()
    return "ok"


__all__ = [
    "DEFAULT_ARCHIVE_DIR",
    "refusal_rotations_total",
    "rotate",
]
