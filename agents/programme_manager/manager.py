"""ProgrammeManager — the lifecycle loop.

Reads the ProgrammePlanStore, tracks the active programme's elapsed
time, evaluates boundary triggers, invokes the TransitionChoreographer,
and stamps lifecycle timestamps back into the store.

Three boundary-trigger types (research §6 + plan §Phase 7 lines 738-748):

1. **Planned**: ``elapsed_s >= planned_duration_s`` AND every named
   completion predicate in ``programme.success.completion_predicates``
   evaluates true. Time-cap forced if ``elapsed_s >= max_duration_s``
   regardless of predicate state.
2. **Operator-triggered**: an impingement arrives with
   ``intent_family="programme.transition.<next_programme_id>"``. The
   manager's ``handle_impingement`` consumer applies the transition
   directly without waiting for the tick-loop.
3. **Emergent**: ``programme.success.abort_predicates`` evaluate true.
   The manager exposes the predicate-evaluator hook; the actual abort
   predicates land in Phase 10.

Predicates are NAMED rather than inline lambdas — programmes are
JSON-round-trippable. Unknown predicate names default to UNSATISFIED so
an operator-authored gate isn't silently bypassed by a missing wiring.
The ``max_duration_s`` cap still forces the transition when the
predicate machinery can't agree.

References:
- docs/superpowers/plans/2026-04-20-programme-layer-plan.md §Phase 7
- docs/research/2026-04-19-content-programming-layer-design.md §6
- shared/programme.py — Programme + ProgrammeStatus
- shared/programme_store.py — ProgrammePlanStore
- shared/programme_observability.py — emit_programme_start/end
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from agents.programme_manager.transition import (
    TransitionChoreographer,
    TransitionImpingements,
)
from shared import programme_outcome_log as _outcome_log_module
from shared.impingement import Impingement
from shared.programme import Programme, ProgrammeStatus
from shared.programme_observability import emit_programme_end, emit_programme_start
from shared.programme_outcome_log import ProgrammeOutcomeLog
from shared.programme_store import ProgrammePlanStore

log = logging.getLogger(__name__)


OPERATOR_INTENT_FAMILY_PREFIX = "programme.transition."


class BoundaryTrigger(StrEnum):
    """Why a transition fired."""

    PLANNED = "planned"
    OPERATOR = "operator"
    EMERGENT = "emergent"
    TIME_CAP = "time_cap"
    NONE = "none"  # tick observed no boundary


@dataclass(frozen=True)
class BoundaryDecision:
    """Outcome of one ProgrammeManager.tick call."""

    trigger: BoundaryTrigger
    from_programme: Programme | None
    to_programme: Programme | None
    impingements: TransitionImpingements | None
    notes: str = ""

    @property
    def transitioned(self) -> bool:
        return self.trigger != BoundaryTrigger.NONE


PredicateFn = Callable[[Programme], bool]
PredicateRegistry = Mapping[str, PredicateFn]


class ProgrammeManager:
    """Lifecycle loop for the meso-tier programme layer.

    The manager is tick-driven. Callers (the daimonion + a future
    standalone systemd unit) invoke ``tick()`` at a low cadence (1 Hz
    is plenty — programmes are minutes-long). Operator triggers route
    through ``handle_impingement`` for immediate response.

    Activation is performed against the store: when a transition
    fires, the prior ACTIVE record is deactivated (status COMPLETED or
    ABORTED, ``actual_ended_at`` stamped) and the next PENDING record
    is promoted to ACTIVE (``actual_started_at`` stamped). The store
    enforces the one-ACTIVE invariant.
    """

    def __init__(
        self,
        store: ProgrammePlanStore,
        choreographer: TransitionChoreographer,
        *,
        completion_predicates: PredicateRegistry | None = None,
        abort_predicates: PredicateRegistry | None = None,
        unknown_predicate_satisfies: bool = False,
        now_fn: Callable[[], float] = time.time,
        outcome_log: ProgrammeOutcomeLog | None = None,
    ) -> None:
        self.store = store
        self.choreographer = choreographer
        self.completion_predicates: PredicateRegistry = (
            dict(completion_predicates) if completion_predicates else {}
        )
        self.abort_predicates: PredicateRegistry = (
            dict(abort_predicates) if abort_predicates else {}
        )
        self.unknown_predicate_satisfies = unknown_predicate_satisfies
        self.now_fn = now_fn
        # B3 Critical #5: per-programme JSONL outcome log under
        # ~/hapax-state/programmes/<show>/<programme-id>.jsonl. Default
        # singleton when caller doesn't inject; tests monkeypatch
        # _outcome_log_module.get_default_log to inject a tmp_path-rooted
        # instance (see tests/programme_manager/conftest.py).
        self._outcome_log = (
            outcome_log if outcome_log is not None else _outcome_log_module.get_default_log()
        )

    # --- public API ------------------------------------------------

    def tick(self) -> BoundaryDecision:
        """Evaluate the active programme and emit a transition if due.

        Order of resolution within one tick:
          1. Time cap (forces transition past max_duration_s).
          2. Emergent abort (any abort predicate evaluates true).
          3. Planned (elapsed >= planned AND completion predicates all
             satisfied).
          4. None (no boundary).

        Operator-triggered transitions arrive through ``handle_impingement``
        and don't wait for ``tick``.
        """
        active = self.store.active_programme()
        if active is None:
            return self._maybe_promote_first_pending()

        trigger = self._evaluate_trigger(active)
        if trigger == BoundaryTrigger.NONE:
            return BoundaryDecision(
                trigger=trigger,
                from_programme=active,
                to_programme=None,
                impingements=None,
                notes="no boundary condition met",
            )

        next_pending = self._next_pending_after(active)
        return self._apply_transition(
            from_programme=active,
            to_programme=next_pending,
            trigger=trigger,
        )

    def handle_impingement(self, imp: Impingement) -> BoundaryDecision | None:
        """Process an operator-triggered transition impingement.

        Returns the BoundaryDecision when the impingement matches the
        operator-trigger family AND a target programme is resolvable;
        returns ``None`` for any other impingement (the caller can
        ignore the return value safely).
        """
        family = imp.intent_family or ""
        if not family.startswith(OPERATOR_INTENT_FAMILY_PREFIX):
            return None

        target_id = family[len(OPERATOR_INTENT_FAMILY_PREFIX) :].strip()
        if not target_id:
            log.warning(
                "handle_impingement: operator-trigger family with empty target id (%s)",
                family,
            )
            return None

        target = self.store.get(target_id)
        if target is None:
            log.warning(
                "handle_impingement: operator-trigger requested unknown programme_id=%s",
                target_id,
            )
            return None

        if target.status == ProgrammeStatus.ACTIVE:
            return BoundaryDecision(
                trigger=BoundaryTrigger.OPERATOR,
                from_programme=target,
                to_programme=target,
                impingements=None,
                notes="operator-trigger requested already-active programme; no-op",
            )

        active = self.store.active_programme()
        return self._apply_transition(
            from_programme=active,
            to_programme=target,
            trigger=BoundaryTrigger.OPERATOR,
        )

    # --- trigger evaluation ----------------------------------------

    def _evaluate_trigger(self, active: Programme) -> BoundaryTrigger:
        if active.actual_started_at is None:
            # Active record without an actual_started_at stamp — the
            # store invariants make this only possible if a hand-edit
            # forced the file. Treat as no boundary so the next tick
            # can correct via maybe_promote.
            return BoundaryTrigger.NONE
        # Compute elapsed against the manager's injected clock so tests
        # and the live tick share a single source of time. Programme.elapsed_s
        # falls through to wall-clock when actual_ended_at is unset, which
        # is wrong for an in-flight active programme being measured.
        elapsed = max(0.0, self.now_fn() - active.actual_started_at)

        # 1. Hard time cap.
        if elapsed >= active.success.max_duration_s:
            return BoundaryTrigger.TIME_CAP

        # 2. Emergent abort.
        if self._any_predicate_true(
            active.success.abort_predicates,
            self.abort_predicates,
            active,
        ):
            return BoundaryTrigger.EMERGENT

        # 3. Planned (predicate-gated). Below min_duration_s never fires.
        if elapsed < active.success.min_duration_s:
            return BoundaryTrigger.NONE
        if elapsed < active.planned_duration_s:
            return BoundaryTrigger.NONE
        if self._all_predicates_true(
            active.success.completion_predicates,
            self.completion_predicates,
            active,
        ):
            return BoundaryTrigger.PLANNED

        return BoundaryTrigger.NONE

    def _all_predicates_true(
        self,
        names: list[str],
        registry: PredicateRegistry,
        programme: Programme,
    ) -> bool:
        if not names:
            return True
        return all(self._evaluate_one(name, registry, programme) for name in names)

    def _any_predicate_true(
        self,
        names: list[str],
        registry: PredicateRegistry,
        programme: Programme,
    ) -> bool:
        if not names:
            return False
        return any(self._evaluate_one(name, registry, programme) for name in names)

    def _evaluate_one(
        self,
        name: str,
        registry: PredicateRegistry,
        programme: Programme,
    ) -> bool:
        fn = registry.get(name)
        if fn is None:
            log.debug(
                "predicate %r not registered; defaulting to %s",
                name,
                self.unknown_predicate_satisfies,
            )
            return self.unknown_predicate_satisfies
        try:
            return bool(fn(programme, {}))
        except Exception:
            log.warning("predicate %r raised; treating as False", name, exc_info=True)
            return False

    # --- transition application ------------------------------------

    def _apply_transition(
        self,
        *,
        from_programme: Programme | None,
        to_programme: Programme | None,
        trigger: BoundaryTrigger,
    ) -> BoundaryDecision:
        """Apply a transition: choreograph, deactivate old, activate new."""
        impingements = self.choreographer.transition(
            from_programme=from_programme,
            to_programme=to_programme,
        )

        ts = self.now_fn()
        notes_parts: list[str] = []
        deactivated: Programme | None = None
        activated: Programme | None = None

        if from_programme is not None:
            terminal_status = (
                ProgrammeStatus.ABORTED
                if trigger == BoundaryTrigger.EMERGENT
                else ProgrammeStatus.COMPLETED
            )
            try:
                deactivated = self.store.deactivate(
                    from_programme.programme_id,
                    status=terminal_status,
                    now=ts,
                )
                end_reason = _reason_for_trigger(trigger)
                emit_programme_end(deactivated, reason=end_reason)
                # B3 Critical #5: also persist to per-programme JSONL.
                self._outcome_log.record_event(deactivated, f"ended_{end_reason}")  # type: ignore[arg-type]
            except KeyError:
                notes_parts.append(f"prior active {from_programme.programme_id!r} not in store")

        if to_programme is not None:
            try:
                activated = self.store.activate(to_programme.programme_id, now=ts)
                emit_programme_start(activated)
                # B3 Critical #5: persist start event to JSONL.
                self._outcome_log.record_event(activated, "started")
            except KeyError:
                notes_parts.append(f"target {to_programme.programme_id!r} not in store")

        return BoundaryDecision(
            trigger=trigger,
            from_programme=deactivated or from_programme,
            to_programme=activated or to_programme,
            impingements=impingements,
            notes="; ".join(notes_parts),
        )

    def _maybe_promote_first_pending(self) -> BoundaryDecision:
        """When no programme is ACTIVE, promote the first PENDING in store order."""
        pending = [p for p in self.store.all() if p.status == ProgrammeStatus.PENDING]
        if not pending:
            return BoundaryDecision(
                trigger=BoundaryTrigger.NONE,
                from_programme=None,
                to_programme=None,
                impingements=None,
                notes="no active programme; no pending programme to promote",
            )
        first = pending[0]
        return self._apply_transition(
            from_programme=None,
            to_programme=first,
            trigger=BoundaryTrigger.PLANNED,
        )

    def _next_pending_after(self, active: Programme) -> Programme | None:
        records = self.store.all()
        seen_active = False
        for p in records:
            if seen_active and p.status == ProgrammeStatus.PENDING:
                return p
            if p.programme_id == active.programme_id:
                seen_active = True
        # Fall through: no pending after the active record. Look for any
        # pending record (the planner may have prepended one).
        for p in records:
            if p.status == ProgrammeStatus.PENDING:
                return p
        return None


def _reason_for_trigger(trigger: BoundaryTrigger) -> str:
    """Map a BoundaryTrigger to a programme-end reason label."""
    return {
        BoundaryTrigger.PLANNED: "planned",
        BoundaryTrigger.OPERATOR: "operator",
        BoundaryTrigger.EMERGENT: "emergent",
        BoundaryTrigger.TIME_CAP: "planned",
        BoundaryTrigger.NONE: "planned",
    }.get(trigger, "planned")
