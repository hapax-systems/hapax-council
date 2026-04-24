"""Tests for agents.programme_manager.manager.

Phase 7 of the programme-layer plan. Verifies:
  - lifecycle PENDING → ACTIVE → COMPLETED stamping (timestamps written)
  - planned trigger fires at elapsed >= planned AND predicates satisfied
  - planned trigger blocks on unknown predicates by default (fail-closed)
  - min_duration_s and max_duration_s caps respected
  - emergent abort fires when an abort predicate is true
  - operator-trigger impingement promotes the targeted programme directly
  - operator-trigger ignores non-matching intent families
  - operator-trigger handles missing target programme gracefully
  - emergent transitions stamp ABORTED rather than COMPLETED
  - empty store on tick returns NONE without raising
  - first PENDING auto-promotes when no ACTIVE record exists
  - choreographer is invoked exactly once per transition
  - operator-trigger when target is already ACTIVE is a no-op decision
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agents.programme_manager.manager import (
    OPERATOR_INTENT_FAMILY_PREFIX,
    BoundaryDecision,
    BoundaryTrigger,
    ProgrammeManager,
)
from agents.programme_manager.transition import TransitionChoreographer
from shared.impingement import Impingement, ImpingementType
from shared.programme import (
    Programme,
    ProgrammeConstraintEnvelope,
    ProgrammeRitual,
    ProgrammeRole,
    ProgrammeStatus,
    ProgrammeSuccessCriteria,
)
from shared.programme_store import ProgrammePlanStore


def _programme(
    pid: str,
    role: ProgrammeRole = ProgrammeRole.LISTENING,
    *,
    duration: float = 100.0,
    min_s: float = 30.0,
    max_s: float = 600.0,
    completion_predicates: list[str] | None = None,
    abort_predicates: list[str] | None = None,
    status: ProgrammeStatus = ProgrammeStatus.PENDING,
    started_at: float | None = None,
) -> Programme:
    return Programme(
        programme_id=pid,
        role=role,
        status=status,
        planned_duration_s=duration,
        actual_started_at=started_at,
        ritual=ProgrammeRitual(boundary_freeze_s=4.0),
        constraints=ProgrammeConstraintEnvelope(),
        success=ProgrammeSuccessCriteria(
            completion_predicates=list(completion_predicates or []),
            abort_predicates=list(abort_predicates or []),
            min_duration_s=min_s,
            max_duration_s=max_s,
        ),
        parent_show_id="test-show",
    )


@pytest.fixture
def store(tmp_path: Path) -> ProgrammePlanStore:
    return ProgrammePlanStore(path=tmp_path / "programmes.jsonl")


@pytest.fixture
def imp_file(tmp_path: Path) -> Path:
    return tmp_path / "impingements.jsonl"


@pytest.fixture
def chor(imp_file: Path) -> TransitionChoreographer:
    return TransitionChoreographer(impingements_file=imp_file, now_fn=lambda: 1_000.0)


class TestEmptyStore:
    def test_empty_store_tick_returns_none(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        mgr = ProgrammeManager(store, chor)
        decision = mgr.tick()
        assert decision.trigger == BoundaryTrigger.NONE
        assert decision.from_programme is None
        assert decision.to_programme is None
        assert decision.impingements is None


class TestDwellUpdatePerTick:
    """ytb-QM3: emit_programme_dwell_update fires on every tick, active or not."""

    def test_dwell_emit_called_when_no_active_programme(
        self,
        store: ProgrammePlanStore,
        chor: TransitionChoreographer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list = []
        from agents.programme_manager import manager as mgr_mod

        monkeypatch.setattr(mgr_mod, "emit_programme_dwell_update", lambda p: calls.append(p))
        ProgrammeManager(store, chor).tick()
        assert calls == [None]

    def test_dwell_emit_called_with_active_programme(
        self,
        store: ProgrammePlanStore,
        chor: TransitionChoreographer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list = []
        from agents.programme_manager import manager as mgr_mod

        monkeypatch.setattr(mgr_mod, "emit_programme_dwell_update", lambda p: calls.append(p))
        store.add(_programme("active", status=ProgrammeStatus.ACTIVE, started_at=1_000.0))
        ProgrammeManager(store, chor, now_fn=lambda: 1_050.0).tick()
        assert len(calls) == 1
        assert calls[0] is not None
        assert calls[0].programme_id == "active"

    def test_first_pending_auto_promotes(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("first"))
        store.add(_programme("second"))
        mgr = ProgrammeManager(store, chor, now_fn=lambda: 1_500.0)
        decision = mgr.tick()
        assert decision.trigger == BoundaryTrigger.PLANNED
        assert decision.to_programme is not None
        assert decision.to_programme.programme_id == "first"
        assert decision.to_programme.status == ProgrammeStatus.ACTIVE
        assert decision.to_programme.actual_started_at == pytest.approx(1_500.0)
        # Choreographer fires.
        assert decision.impingements is not None


class TestPlannedTrigger:
    def test_does_not_fire_below_planned_duration(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=300.0))
        store.add(_programme("b"))
        store.activate("a", now=0.0)
        # 60s elapsed, planned 300s → block.
        mgr = ProgrammeManager(store, chor, now_fn=lambda: 60.0)
        decision = mgr.tick()
        assert decision.trigger == BoundaryTrigger.NONE

    def test_fires_at_planned_when_no_predicates(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=100.0))
        store.add(_programme("b"))
        store.activate("a", now=0.0)
        mgr = ProgrammeManager(store, chor, now_fn=lambda: 150.0)
        decision = mgr.tick()
        assert decision.trigger == BoundaryTrigger.PLANNED
        assert decision.to_programme is not None
        assert decision.to_programme.programme_id == "b"

    def test_unknown_predicate_blocks_by_default(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=100.0, completion_predicates=["mystery_pred"]))
        store.add(_programme("b"))
        store.activate("a", now=0.0)
        mgr = ProgrammeManager(store, chor, now_fn=lambda: 200.0)
        decision = mgr.tick()
        assert decision.trigger == BoundaryTrigger.NONE

    def test_unknown_predicate_satisfies_when_configured(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=100.0, completion_predicates=["mystery_pred"]))
        store.add(_programme("b"))
        store.activate("a", now=0.0)
        mgr = ProgrammeManager(store, chor, now_fn=lambda: 200.0, unknown_predicate_satisfies=True)
        decision = mgr.tick()
        assert decision.trigger == BoundaryTrigger.PLANNED

    def test_predicate_must_all_be_true_to_fire(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=100.0, completion_predicates=["t", "f"]))
        store.add(_programme("b"))
        store.activate("a", now=0.0)
        registry = {"t": lambda p: True, "f": lambda p: False}
        mgr = ProgrammeManager(store, chor, now_fn=lambda: 200.0, completion_predicates=registry)
        decision = mgr.tick()
        assert decision.trigger == BoundaryTrigger.NONE

    def test_predicate_raising_treated_as_false(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=100.0, completion_predicates=["boom"]))
        store.add(_programme("b"))
        store.activate("a", now=0.0)

        def boom(p: Programme) -> bool:
            raise RuntimeError("boom")

        mgr = ProgrammeManager(
            store, chor, now_fn=lambda: 200.0, completion_predicates={"boom": boom}
        )
        decision = mgr.tick()
        assert decision.trigger == BoundaryTrigger.NONE


class TestTimeCap:
    def test_max_duration_forces_transition_even_with_unmet_predicates(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(
            _programme(
                "a",
                duration=100.0,
                max_s=300.0,
                completion_predicates=["never"],
            )
        )
        store.add(_programme("b"))
        store.activate("a", now=0.0)
        mgr = ProgrammeManager(
            store,
            chor,
            now_fn=lambda: 350.0,
            completion_predicates={"never": lambda p: False},
        )
        decision = mgr.tick()
        assert decision.trigger == BoundaryTrigger.TIME_CAP
        assert decision.to_programme is not None
        assert decision.to_programme.programme_id == "b"


class TestEmergentAbort:
    def test_abort_predicate_fires_emergent(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(
            _programme(
                "a", duration=300.0, abort_predicates=["bad"], status=ProgrammeStatus.PENDING
            )
        )
        store.add(_programme("b"))
        store.activate("a", now=0.0)
        mgr = ProgrammeManager(
            store,
            chor,
            now_fn=lambda: 60.0,
            abort_predicates={"bad": lambda p: True},
        )
        decision = mgr.tick()
        assert decision.trigger == BoundaryTrigger.EMERGENT
        # Aborted from-programme stamped ABORTED rather than COMPLETED.
        deactivated = store.get("a")
        assert deactivated is not None
        assert deactivated.status == ProgrammeStatus.ABORTED


class TestOperatorTrigger:
    def test_handle_impingement_routes_to_target(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=300.0))
        store.add(_programme("b", role=ProgrammeRole.SHOWCASE))
        store.activate("a", now=0.0)
        mgr = ProgrammeManager(store, chor, now_fn=lambda: 30.0)
        imp = _operator_imp("b")
        decision = mgr.handle_impingement(imp)
        assert decision is not None
        assert decision.trigger == BoundaryTrigger.OPERATOR
        assert decision.to_programme is not None
        assert decision.to_programme.programme_id == "b"
        assert decision.to_programme.status == ProgrammeStatus.ACTIVE

    def test_handle_impingement_ignores_non_matching_family(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=300.0))
        store.activate("a", now=0.0)
        mgr = ProgrammeManager(store, chor)
        imp = Impingement(
            timestamp=0.0,
            source="test",
            type=ImpingementType.PATTERN_MATCH,
            strength=0.5,
            content={},
            intent_family="ward.choreography",
        )
        assert mgr.handle_impingement(imp) is None

    def test_handle_impingement_ignores_unknown_target(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=300.0))
        store.activate("a", now=0.0)
        mgr = ProgrammeManager(store, chor)
        decision = mgr.handle_impingement(_operator_imp("does-not-exist"))
        assert decision is None

    def test_handle_impingement_empty_target_id_ignored(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=300.0))
        store.activate("a", now=0.0)
        mgr = ProgrammeManager(store, chor)
        # Family ends right after the prefix → empty target.
        bare = Impingement(
            timestamp=0.0,
            source="test",
            type=ImpingementType.PATTERN_MATCH,
            strength=0.5,
            content={},
            intent_family=OPERATOR_INTENT_FAMILY_PREFIX,
        )
        assert mgr.handle_impingement(bare) is None

    def test_handle_impingement_already_active_target_is_noop(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a"))
        store.activate("a", now=0.0)
        mgr = ProgrammeManager(store, chor)
        decision = mgr.handle_impingement(_operator_imp("a"))
        assert decision is not None
        assert decision.trigger == BoundaryTrigger.OPERATOR
        assert decision.impingements is None  # no choreographer fire
        assert "no-op" in decision.notes


class TestStoreInteraction:
    def test_planned_transition_stamps_actual_ended_at_on_from_programme(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=100.0))
        store.add(_programme("b"))
        store.activate("a", now=0.0)
        ProgrammeManager(store, chor, now_fn=lambda: 200.0).tick()
        deactivated = store.get("a")
        activated = store.get("b")
        assert deactivated is not None
        assert deactivated.status == ProgrammeStatus.COMPLETED
        assert deactivated.actual_ended_at == pytest.approx(200.0)
        assert activated is not None
        assert activated.status == ProgrammeStatus.ACTIVE
        assert activated.actual_started_at == pytest.approx(200.0)

    def test_choreographer_invoked_exactly_once_per_transition(
        self, store: ProgrammePlanStore, imp_file: Path
    ) -> None:
        call_log: list[tuple[str | None, str | None]] = []

        class _SpyChoreographer(TransitionChoreographer):
            def transition(self, *, from_programme, to_programme):
                call_log.append(
                    (
                        from_programme.programme_id if from_programme else None,
                        to_programme.programme_id if to_programme else None,
                    )
                )
                return super().transition(from_programme=from_programme, to_programme=to_programme)

        chor = _SpyChoreographer(impingements_file=imp_file, now_fn=lambda: 200.0)
        store.add(_programme("a", duration=100.0))
        store.add(_programme("b"))
        store.activate("a", now=0.0)
        ProgrammeManager(store, chor, now_fn=lambda: 200.0).tick()
        assert call_log == [("a", "b")]


class TestNoNextProgramme:
    def test_planned_transition_with_no_pending_completes_only(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=100.0))
        store.activate("a", now=0.0)
        decision = ProgrammeManager(store, chor, now_fn=lambda: 200.0).tick()
        assert decision.trigger == BoundaryTrigger.PLANNED
        assert decision.to_programme is None
        # Choreographer still fired exit + freeze (end-of-stream).
        assert decision.impingements is not None
        assert decision.impingements.exit_ritual is not None
        assert decision.impingements.boundary_freeze is not None
        assert decision.impingements.entry_ritual is None


class TestRitualGroundingExpansion:
    """The keystone architectural assertion: every transition step is a
    normal Impingement (recruited through the pipeline), never a direct
    capability invocation. Matches plan §Phase 7 success criterion
    lines 791-795.
    """

    def test_every_transition_step_is_an_impingement_not_a_dispatch(
        self, store: ProgrammePlanStore, chor: TransitionChoreographer
    ) -> None:
        store.add(_programme("a", duration=50.0))
        store.add(_programme("b"))
        store.activate("a", now=0.0)
        decision = ProgrammeManager(store, chor, now_fn=lambda: 100.0).tick()
        assert decision.impingements is not None
        for imp in decision.impingements.as_list():
            assert isinstance(imp, Impingement)
            assert imp.intent_family is not None
            assert imp.intent_family.startswith("programme.")


def _operator_imp(target_id: str) -> Impingement:
    return Impingement(
        timestamp=0.0,
        source="operator.trigger",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.95,
        content={"narrative": f"transition to {target_id}"},
        intent_family=f"{OPERATOR_INTENT_FAMILY_PREFIX}{target_id}",
    )


# Convenience: assert BoundaryDecision exposes the .transitioned helper.
class TestBoundaryDecisionShape:
    def test_transitioned_property(self) -> None:
        bd_no = BoundaryDecision(
            trigger=BoundaryTrigger.NONE,
            from_programme=None,
            to_programme=None,
            impingements=None,
        )
        assert not bd_no.transitioned
        bd_yes = BoundaryDecision(
            trigger=BoundaryTrigger.PLANNED,
            from_programme=None,
            to_programme=None,
            impingements=None,
        )
        assert bd_yes.transitioned


# Type-check the module's public exports are exactly what's documented.
def test_module_exports() -> None:
    from agents import programme_manager as pm

    assert pm.BoundaryDecision is BoundaryDecision
    assert pm.BoundaryTrigger is BoundaryTrigger
    assert pm.ProgrammeManager is ProgrammeManager
    assert pm.TransitionChoreographer is TransitionChoreographer


def test_callable_predicates_signature() -> None:
    """Predicate registry value is Callable[[Programme], bool]."""

    def fn(p: Programme) -> bool:
        return p.role == ProgrammeRole.LISTENING

    typed: Callable[[Programme], bool] = fn
    p = _programme("x")
    assert typed(p) is True
