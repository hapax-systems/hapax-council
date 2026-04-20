"""ProgrammePlanStore — persistence for ``shared.programme.Programme``.

Phase 2 of ``docs/superpowers/plans/2026-04-20-programme-layer-plan.md``.
The Programme primitive (Phase 1, commit ``f6cc0b42b``) is runtime data;
without persistence the planner can't survive a daimonion restart and
the demonet Phase 11 quiet-frame programme can't hot-reload. This
module is the storage layer.

Storage format: one JSONL file per store. Each line is a full Programme
as ``model_dump_json()`` output — no partial / diff records. Append-only
writes from the planner; full rewrites on status transitions.

Chosen over SQLite because:

- Filesystem-as-bus architecture (see council CLAUDE.md) already
  prefers text-on-disk for inspectability.
- Programme volume is low (operator-run Programmes in the tens to
  hundreds over a session) — SQLite index overhead is unwarranted.
- Daily-note / replay agents can grep the JSONL directly without
  opening a DB connection.
- No schema-migration tax when Programme gains fields; Pydantic's
  forgiving model_validate handles old records.

Atomic writes via tmp+rename. Active-programme resolver returns at
most one Programme with ``status=ACTIVE``; the planner guarantees
this invariant on ``activate()``.

References:
    - docs/superpowers/plans/2026-04-20-programme-layer-plan.md §Phase 2
    - docs/research/2026-04-19-content-programming-layer-design.md
    - shared/programme.py — Programme primitive
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Final

from shared.programme import Programme, ProgrammeStatus

log = logging.getLogger(__name__)

DEFAULT_STORE_PATH: Final[Path] = Path.home() / "hapax-state" / "programmes.jsonl"


class ProgrammePlanStore:
    """File-backed store for Programme instances.

    Per-instance ``path`` attribute so tests can isolate and the
    daimonion + logos-api can share the default store without drifting.

    Loading strategy: whole-file read on each public method — Programme
    lists stay small enough (<1 k rows in any realistic session) that
    streaming / incremental indexing is not yet worth the complexity.
    If the file grows large, swap to SQLite without changing the public
    API.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else DEFAULT_STORE_PATH

    # --- Reads ------------------------------------------------------

    def all(self) -> list[Programme]:
        """Return every Programme in the store, oldest-first.

        Deduplicates by ``programme_id``: the LAST record wins, so
        after ``activate(x)`` followed by ``deactivate(x)`` the store
        returns the deactivated instance. Corrupt rows are logged +
        skipped (the store is fail-safe — one bad JSON line doesn't
        break every later read).
        """
        if not self.path.exists():
            return []
        by_id: dict[str, Programme] = {}
        order: list[str] = []
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                programme = Programme.model_validate_json(line)
            except Exception:
                log.debug("programme_store: skipping malformed row", exc_info=True)
                continue
            if programme.programme_id not in by_id:
                order.append(programme.programme_id)
            by_id[programme.programme_id] = programme
        return [by_id[pid] for pid in order]

    def get(self, programme_id: str) -> Programme | None:
        """Return the Programme with ``programme_id`` or None if absent."""
        for p in self.all():
            if p.programme_id == programme_id:
                return p
        return None

    def active_programme(self) -> Programme | None:
        """Return the Programme with status=ACTIVE, or None.

        The planner guarantees at most one ACTIVE Programme; if multiple
        appear (a write-race between planner + operator CLI, or a
        manual edit), this returns the most-recent one by
        ``actual_started_at`` descending.
        """
        actives = [p for p in self.all() if p.status == ProgrammeStatus.ACTIVE]
        if not actives:
            return None
        # Ties broken by started_at; None sorts last.
        return max(actives, key=lambda p: p.actual_started_at or 0.0)

    # --- Writes -----------------------------------------------------

    def add(self, programme: Programme) -> None:
        """Append a Programme to the store as a new JSONL line.

        Caller sets the status; ``add`` does NOT transition PENDING →
        ACTIVE implicitly. Use ``activate`` for that.
        """
        self._rewrite([*self.all(), programme])

    def activate(self, programme_id: str, now: float | None = None) -> Programme:
        """Transition ``programme_id`` to ACTIVE + deactivate any prior active.

        Enforces the one-ACTIVE invariant: any Programme currently in
        ACTIVE status is transitioned to COMPLETED (with
        ``actual_ended_at=now``) before the target is promoted. Raises
        ``KeyError`` when the programme_id is not in the store.
        """
        ts = now if now is not None else time.time()
        records = self.all()
        found = False
        updated: list[Programme] = []
        for p in records:
            if p.programme_id == programme_id:
                updated.append(
                    p.model_copy(update={"status": ProgrammeStatus.ACTIVE, "actual_started_at": ts})
                )
                found = True
            elif p.status == ProgrammeStatus.ACTIVE:
                # Deactivate the prior active.
                updated.append(
                    p.model_copy(
                        update={"status": ProgrammeStatus.COMPLETED, "actual_ended_at": ts}
                    )
                )
            else:
                updated.append(p)
        if not found:
            raise KeyError(f"no programme in store with id {programme_id!r}")
        self._rewrite(updated)
        return next(p for p in updated if p.programme_id == programme_id)

    def deactivate(
        self,
        programme_id: str,
        status: ProgrammeStatus = ProgrammeStatus.COMPLETED,
        now: float | None = None,
    ) -> Programme:
        """Transition ``programme_id`` to COMPLETED (default) or ABORTED.

        ``status`` must be a terminal status (``COMPLETED`` or
        ``ABORTED``). Raises ValueError otherwise + KeyError when the
        programme is absent.
        """
        if status not in (ProgrammeStatus.COMPLETED, ProgrammeStatus.ABORTED):
            raise ValueError(f"deactivate status must be COMPLETED or ABORTED; got {status!r}")
        ts = now if now is not None else time.time()
        records = self.all()
        found = False
        updated: list[Programme] = []
        for p in records:
            if p.programme_id == programme_id:
                updated.append(p.model_copy(update={"status": status, "actual_ended_at": ts}))
                found = True
            else:
                updated.append(p)
        if not found:
            raise KeyError(f"no programme in store with id {programme_id!r}")
        self._rewrite(updated)
        return next(p for p in updated if p.programme_id == programme_id)

    # --- Internals --------------------------------------------------

    def _rewrite(self, programmes: list[Programme]) -> None:
        """Atomic full-file rewrite via tmp+rename."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w") as f:
            for p in programmes:
                f.write(p.model_dump_json() + "\n")
        os.replace(tmp, self.path)


def default_store() -> ProgrammePlanStore:
    """Module-level convenience — the shared store at DEFAULT_STORE_PATH."""
    return ProgrammePlanStore()
