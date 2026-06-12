"""Programme outcome JSONL log — Phase 9 Critical #5 (B3 audit).

Writes one JSONL entry per programme lifecycle transition (start /
end) under
``~/hapax-state/programmes/<show_id>/<programme_id>.jsonl``. The
Bayesian validation pipeline reads these to slice posterior updates
by programme.

Rotation: 5 MiB per file, keep 3 generations (.jsonl, .jsonl.1,
.jsonl.2). Atomic append (sub-PIPE_BUF write under threading lock —
matches AttributionFileWriter's posture).

Defensive: every public method tolerates filesystem failures by
logging at WARNING and returning. The lifecycle path must not break
on a disk-full or permission error.

References:
- Plan: docs/superpowers/plans/2026-04-20-programme-layer-plan.md §Phase 9
- Audit: docs/superpowers/audits/2026-04-20-3h-work-audit-remediation.md (B3 / Critical #5)
- Sister writer: shared/attribution.AttributionFileWriter
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)


# 5 MiB per file matches the audit spec; smaller forces more rotations
# (cheap on tmpfs but noisy on disk), larger delays the per-file scan
# the validation pipeline performs (one mmap per file).
DEFAULT_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MiB
# Keep 3 generations so a Bayesian validation slice across two streams
# (typical 2-3 hour each) still has the older programme records.
DEFAULT_KEEP_GENERATIONS: int = 3

DEFAULT_PROGRAMMES_ROOT: Path = Path.home() / "hapax-state" / "programmes"

# Lifecycle event tags. Aligned with EndReason from
# shared.programme_observability so a single Bayesian slice can join
# both surfaces by programme_id.
ProgrammeOutcomeEvent = Literal[
    "started",  # programme transitioned from PENDING → ACTIVE
    "ended_planned",  # programme reached its planned duration
    "ended_operator",  # operator manually terminated
    "ended_emergent",  # abort predicate fired + operator did not veto
    "ended_aborted",  # general aborted catch-all
]


def _programme_attr(programme: Any, name: str, default: Any = None) -> Any:
    """Defensive attribute reader — programme may be a stub in tests."""
    try:
        return getattr(programme, name, default)
    except Exception:
        return default


def _path_for(programme: Any, root: Path) -> Path:
    """Compose the per-programme JSONL path under <root>/<show>/<id>.jsonl."""
    show_id = str(_programme_attr(programme, "parent_show_id", "unknown"))
    programme_id = str(_programme_attr(programme, "programme_id", "unknown"))
    # Sanitize show_id for filesystem safety — strip path separators
    # and other ambiguous chars. programme_id should already be uuid-
    # safe but apply the same hygiene defensively.
    safe_show = "".join(c for c in show_id if c.isalnum() or c in "-_") or "unknown"
    safe_pid = "".join(c for c in programme_id if c.isalnum() or c in "-_") or "unknown"
    return root / safe_show / f"{safe_pid}.jsonl"


class ProgrammeOutcomeLog:
    """Per-programme JSONL writer with size-based rotation.

    Construct once per process (typically from the daimonion startup or
    the ProgrammeManager). Lifecycle hooks call ``record_event`` on
    every transition; the writer composes the path, rotates if the
    file is at the size limit, and appends one JSONL line under the
    threading lock.
    """

    def __init__(
        self,
        root: Path = DEFAULT_PROGRAMMES_ROOT,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        keep_generations: int = DEFAULT_KEEP_GENERATIONS,
    ) -> None:
        self.root = root
        self.max_bytes = max_bytes
        self.keep_generations = keep_generations
        self._lock = threading.Lock()

    def record_event(
        self,
        programme: Any,
        event: ProgrammeOutcomeEvent,
        *,
        emitted_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append one outcome event for the programme. Defensive: never raises.

        Each entry serializes as a single JSONL line with the schema:

            {
                "event": "<event-tag>",
                "emitted_at": "<isoformat>",
                "programme_id": "<id>",
                "show_id": "<parent-show>",
                "role": "<programme-role>",
                "planned_duration_s": <float>,
                "elapsed_s": <float-or-null>,
                "metadata": {<caller-supplied>}
            }
        """
        try:
            path = _path_for(programme, self.root)
            entry = {
                "event": event,
                "emitted_at": (emitted_at or datetime.now(UTC)).isoformat(),
                "programme_id": str(_programme_attr(programme, "programme_id", "unknown")),
                "show_id": str(_programme_attr(programme, "parent_show_id", "unknown")),
                "role": str(_programme_attr(programme, "role", "unknown")),
                "planned_duration_s": float(_programme_attr(programme, "planned_duration_s", 0.0)),
                "elapsed_s": _safe_float(_programme_attr(programme, "elapsed_s", None)),
                "metadata": metadata or {},
            }
            line = json.dumps(entry, sort_keys=False) + "\n"
            with self._lock:
                self._maybe_rotate(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                # jsonl-rotation: exempt(domain rotation; _maybe_rotate caps each programme file)
                with path.open("a", encoding="utf-8") as f:
                    f.write(line)
        except Exception:  # noqa: BLE001 — never break the lifecycle path
            log.warning("ProgrammeOutcomeLog.record_event failed", exc_info=True)

    def _maybe_rotate(self, path: Path) -> None:
        """Rotate ``path`` to keep_generations when it exceeds max_bytes.

        Rotation rule: ``foo.jsonl`` → ``foo.jsonl.1`` (overwriting any
        existing); ``foo.jsonl.1`` → ``foo.jsonl.2``; the oldest
        generation is unlinked. Implemented as a downward shift to keep
        the active file at the canonical name.
        """
        if not path.exists():
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size < self.max_bytes:
            return
        # Shift older generations: drop the oldest, then move every
        # remaining generation down one slot.
        oldest = path.with_suffix(path.suffix + f".{self.keep_generations - 1}")
        if oldest.exists():
            try:
                oldest.unlink()
            except OSError:
                log.debug("could not unlink oldest rotation %s", oldest, exc_info=True)
        for i in range(self.keep_generations - 2, 0, -1):
            current = path.with_suffix(path.suffix + f".{i}")
            target = path.with_suffix(path.suffix + f".{i + 1}")
            if current.exists():
                try:
                    current.rename(target)
                except OSError:
                    log.debug("rotation rename failed %s → %s", current, target, exc_info=True)
        # Active file → .1.
        try:
            path.rename(path.with_suffix(path.suffix + ".1"))
        except OSError:
            log.debug("active file rotation failed for %s", path, exc_info=True)

    def read_all(self, programme: Any) -> list[dict[str, Any]]:
        """Read every outcome entry for ``programme`` (active file +
        rotated generations, oldest-first). Defensive: missing files +
        malformed lines yield empty / skip respectively.
        """
        path = _path_for(programme, self.root)
        out: list[dict[str, Any]] = []
        # Read oldest → newest so the result list is chronological.
        for i in range(self.keep_generations - 1, 0, -1):
            rotated = path.with_suffix(path.suffix + f".{i}")
            out.extend(self._read_one(rotated))
        out.extend(self._read_one(path))
        return out

    @staticmethod
    def _read_one(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
        except OSError:
            log.warning("ProgrammeOutcomeLog read failed for %s", path, exc_info=True)
        return out


def _safe_float(value: Any) -> float | None:
    """Coerce to float, returning None on any failure (incl. None input)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Module-level singleton for callers that don't manage their own
# instance. Lifecycle hooks (manager.py, abort_evaluator.py) reach
# for this to keep wire-in to one import line.
_DEFAULT_LOG: ProgrammeOutcomeLog | None = None


def get_default_log() -> ProgrammeOutcomeLog:
    """Lazy-construct + return the module-level outcome log."""
    global _DEFAULT_LOG
    if _DEFAULT_LOG is None:
        _DEFAULT_LOG = ProgrammeOutcomeLog()
    return _DEFAULT_LOG


__all__ = [
    "DEFAULT_KEEP_GENERATIONS",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_PROGRAMMES_ROOT",
    "ProgrammeOutcomeEvent",
    "ProgrammeOutcomeLog",
    "get_default_log",
]
