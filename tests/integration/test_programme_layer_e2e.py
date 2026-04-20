"""End-to-end programme-layer acceptance — Phase 12 (terminal).

Walks 3 programmes through the full lifecycle and pins every auto-
checkable acceptance item from plan §lines 1146-1212.

Auto-checkable items the synthetic test covers:

  1. Programme plan generated via ProgrammePlanner (mocked LLM)
  2. Plan saved to ProgrammePlanStore; programmes are inspectable
  3. ProgrammeManager walks transitions (programme 1 → 2 → 3)
  4. TransitionChoreographer emits ritual impingements per boundary
  5. Metrics: programme_start_total / programme_end_total / programme_active
     fire correctly across the lifecycle
  6. Invariant: hapax_programme_candidate_set_reduction_total stays at 0
     (grounding-expansion: bias never shrinks the candidate set)
  7. Invariant: hapax_programme_soft_prior_overridden_total > 0 per
     programme (soft-prior-not-hardening detector fires)
  8. Reverie substrate compose honours each programme's saturation
     target (the visual surface reads as the programme says it should)
  9. Structural director stamps programme_id on every emitted intent
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import pytest
from prometheus_client import REGISTRY

from agents.programme_manager.abort_evaluator import VETO_INTENT_FAMILY, AbortEvaluator
from agents.programme_manager.manager import (
    ProgrammeManager,
)
from agents.programme_manager.planner import ProgrammePlanner
from agents.programme_manager.transition import TransitionChoreographer
from agents.reverie.substrate_palette import compute_substrate_saturation
from agents.studio_compositor import structural_director as sd
from shared.affordance import SelectionCandidate
from shared.affordance_pipeline import AffordancePipeline
from shared.impingement import Impingement, ImpingementType
from shared.programme import (
    ProgrammeRole,
)
from shared.programme_store import ProgrammePlanStore

# ── Helpers ─────────────────────────────────────────────────────────────


def _three_programme_plan_payload(show_id: str) -> dict:
    """Listening → Work-block → Wind-down. Each programme has the
    bias / saturation / cadence priors that downstream consumers honour.
    """
    return {
        "plan_id": f"plan-{show_id}",
        "show_id": show_id,
        "plan_author": "hapax-director-planner",
        "programmes": [
            {
                "programme_id": "prog-listening",
                "role": ProgrammeRole.LISTENING.value,
                "planned_duration_s": 60.0,
                "constraints": {
                    "capability_bias_negative": {"speech_production": 0.5},
                    "capability_bias_positive": {"recall.web_search": 1.5},
                    "preset_family_priors": ["calm-textural"],
                    "homage_rotation_modes": ["paused"],
                    "surface_threshold_prior": 0.85,
                    "reverie_saturation_target": 0.30,
                },
                "content": {"narrative_beat": "Sit with the music."},
                "success": {
                    "completion_predicates": [],
                    "abort_predicates": [],
                    "min_duration_s": 5.0,
                    "max_duration_s": 60.0,
                },
                "parent_show_id": show_id,
                "authorship": "hapax",
            },
            {
                "programme_id": "prog-work-block",
                "role": ProgrammeRole.WORK_BLOCK.value,
                "planned_duration_s": 60.0,
                "constraints": {
                    "capability_bias_negative": {"camera.hero": 0.4},
                    "capability_bias_positive": {"recall.web_search": 1.8},
                    "preset_family_priors": ["warm-minimal"],
                    "surface_threshold_prior": 0.6,
                    "reverie_saturation_target": 0.50,
                },
                "content": {"narrative_beat": "Heads-down focused work."},
                "success": {
                    "completion_predicates": [],
                    "abort_predicates": [],
                    "min_duration_s": 5.0,
                    "max_duration_s": 60.0,
                },
                "parent_show_id": show_id,
                "authorship": "hapax",
            },
            {
                "programme_id": "prog-wind-down",
                "role": ProgrammeRole.WIND_DOWN.value,
                "planned_duration_s": 60.0,
                "constraints": {
                    "capability_bias_negative": {"speech_production": 0.3},
                    "preset_family_priors": ["calm-textural"],
                    "homage_rotation_modes": ["paused"],
                    "surface_threshold_prior": 0.9,
                    "reverie_saturation_target": 0.25,
                    "narrative_cadence_prior_s": 60.0,
                },
                "content": {"narrative_beat": "Slow tempo. Wind down."},
                "success": {
                    "completion_predicates": [],
                    "abort_predicates": [],
                    "min_duration_s": 5.0,
                    "max_duration_s": 60.0,
                },
                "parent_show_id": show_id,
                "authorship": "hapax",
            },
        ],
    }


def _stub_llm(payload: dict) -> Callable[[str], str]:
    def fn(prompt: str) -> str:  # noqa: ARG001
        return json.dumps(payload)

    return fn


def _read_counter(name: str, **labels) -> float:
    """Sum a labelled Prometheus counter family across matching label sets."""
    total = 0.0
    for collector in REGISTRY.collect():
        for metric in collector.samples:
            if metric.name == name and all(metric.labels.get(k) == v for k, v in labels.items()):
                total += float(metric.value)
    return total


class _Clock:
    def __init__(self, t0: float = 1000.0) -> None:
        self.t = t0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


# ── E2E walk ────────────────────────────────────────────────────────────


class TestProgrammeLayerE2E:
    """Synthetic 3-programme acceptance — listening → work-block → wind-down."""

    @pytest.fixture
    def store(self, tmp_path):
        return ProgrammePlanStore(path=tmp_path / "programmes.jsonl")

    @pytest.fixture
    def show_id(self) -> str:
        return f"show-e2e-{int(time.time() * 1000)}"

    def test_planner_emits_three_programme_plan(self, show_id: str) -> None:
        payload = _three_programme_plan_payload(show_id)
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id=show_id)
        assert plan is not None
        assert len(plan.programmes) == 3
        assert [p.role for p in plan.programmes] == [
            ProgrammeRole.LISTENING,
            ProgrammeRole.WORK_BLOCK,
            ProgrammeRole.WIND_DOWN,
        ]
        # Hapax-authored invariant
        assert plan.plan_author == "hapax-director-planner"

    def test_plan_persists_to_store(self, store, show_id: str) -> None:
        payload = _three_programme_plan_payload(show_id)
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id=show_id)
        assert plan is not None
        for prog in plan.programmes:
            store.add(prog)
        # All three programmes round-tripped
        names = {p.programme_id for p in store.all()}
        assert names == {"prog-listening", "prog-work-block", "prog-wind-down"}

    def test_manager_walks_three_programmes(self, store, show_id: str) -> None:
        payload = _three_programme_plan_payload(show_id)
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id=show_id)
        assert plan is not None
        for prog in plan.programmes:
            store.add(prog)

        clock = _Clock(t0=1000.0)
        manager = ProgrammeManager(
            store=store,
            choreographer=TransitionChoreographer(),
            now_fn=clock,
        )

        # Tick #1 — promotes first programme
        d1 = manager.tick()
        assert d1.transitioned
        assert d1.to_programme is not None
        assert d1.to_programme.programme_id == "prog-listening"

        # Advance past planned_duration → planned transition fires
        clock.advance(120.0)
        d2 = manager.tick()
        assert d2.transitioned
        assert d2.from_programme is not None and d2.from_programme.programme_id == "prog-listening"
        assert d2.to_programme is not None and d2.to_programme.programme_id == "prog-work-block"

        # Advance again → wind-down
        clock.advance(120.0)
        d3 = manager.tick()
        assert d3.transitioned
        assert d3.from_programme is not None and d3.from_programme.programme_id == "prog-work-block"
        assert d3.to_programme is not None and d3.to_programme.programme_id == "prog-wind-down"

    def test_each_boundary_emits_four_ritual_impingements(self, store, show_id: str) -> None:
        payload = _three_programme_plan_payload(show_id)
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id=show_id)
        assert plan is not None
        for prog in plan.programmes:
            store.add(prog)

        clock = _Clock(t0=1000.0)
        manager = ProgrammeManager(
            store=store,
            choreographer=TransitionChoreographer(),
            now_fn=clock,
        )
        manager.tick()  # promote first
        clock.advance(120.0)
        decision = manager.tick()  # transition

        assert decision.impingements is not None
        as_list = decision.impingements.as_list()
        # boundary_freeze + exit_ritual + palette_shift + entry_ritual
        # (boundary_freeze always fires; the other three depend on side
        # presence. Both sides exist here so all 4 emit.)
        families = {imp.intent_family for imp in as_list}
        assert any("boundary.freeze" in f for f in families if f)
        assert any("exit_ritual" in f for f in families if f)
        assert any("palette.shift" in f for f in families if f)
        assert any("entry_ritual" in f for f in families if f)

    def test_metrics_fire_across_lifecycle(self, store, show_id: str) -> None:
        payload = _three_programme_plan_payload(show_id)
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id=show_id)
        assert plan is not None
        for prog in plan.programmes:
            store.add(prog)

        clock = _Clock(t0=1000.0)
        manager = ProgrammeManager(
            store=store,
            choreographer=TransitionChoreographer(),
            now_fn=clock,
        )

        starts_before = _read_counter("hapax_programme_start_total", show_id=show_id)
        manager.tick()  # promote first → start fires
        for _ in range(2):
            clock.advance(120.0)
            manager.tick()
        starts_after = _read_counter("hapax_programme_start_total", show_id=show_id)
        ends_after = _read_counter("hapax_programme_end_total", show_id=show_id)

        # 3 programmes activated → 3 starts
        assert starts_after - starts_before >= 3.0
        # 2 completed transitions → 2 ends
        assert ends_after >= 2.0

    def test_candidate_set_reduction_stays_at_zero(self, show_id: str) -> None:
        """Grounding-expansion invariant: across the full lifecycle the
        candidate-set-reduction counter must remain at 0.
        """
        payload = _three_programme_plan_payload(show_id)
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id=show_id)
        assert plan is not None

        before = _read_counter("hapax_programme_candidate_set_reduction_total")
        pipeline = AffordancePipeline()
        for prog in plan.programmes:
            cands = [
                SelectionCandidate(
                    capability_name="speech_production", similarity=0.8, combined=0.8, payload={}
                ),
                SelectionCandidate(
                    capability_name="recall.web_search", similarity=0.6, combined=0.6, payload={}
                ),
                SelectionCandidate(
                    capability_name="camera.hero", similarity=0.7, combined=0.7, payload={}
                ),
            ]
            result = pipeline._apply_programme_bias(cands, prog)
            assert len(result) == 3, f"set size shrank under {prog.programme_id!r}"
        after = _read_counter("hapax_programme_candidate_set_reduction_total")
        assert after == before  # invariant: zero increment

    def test_soft_prior_override_fires_per_programme(self, show_id: str) -> None:
        """Soft-prior-not-hardening invariant: each programme produces at
        least one override event when its negative-biased capability has
        strong base similarity.
        """
        payload = _three_programme_plan_payload(show_id)
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id=show_id)
        assert plan is not None

        pipeline = AffordancePipeline()
        for prog in plan.programmes:
            before = _read_counter(
                "hapax_programme_soft_prior_overridden_total",
                programme_id=prog.programme_id,
            )
            # A capability with negative bias + high base similarity →
            # post-bias > THRESHOLD → override fires
            for cap_name in prog.constraints.capability_bias_negative:
                cands = [
                    SelectionCandidate(
                        capability_name=cap_name, similarity=0.95, combined=0.95, payload={}
                    )
                ]
                pipeline._apply_programme_bias(cands, prog)
            after = _read_counter(
                "hapax_programme_soft_prior_overridden_total",
                programme_id=prog.programme_id,
            )
            if prog.constraints.capability_bias_negative:
                assert after > before, (
                    f"override counter did not fire for {prog.programme_id!r} — "
                    "soft prior may be hardening into a gate"
                )

    def test_reverie_substrate_honours_each_programme_target(self, show_id: str) -> None:
        """Each programme's reverie_saturation_target reaches the
        substrate compose function.
        """
        payload = _three_programme_plan_payload(show_id)
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id=show_id)
        assert plan is not None
        for prog in plan.programmes:
            target = prog.constraints.reverie_saturation_target
            if target is None:
                continue
            composed = compute_substrate_saturation(prog)
            assert composed == pytest.approx(target), (
                f"{prog.programme_id!r}: composed={composed} != target={target}"
            )

    def test_structural_director_stamps_programme_id(
        self, store, show_id: str, tmp_path, monkeypatch
    ) -> None:
        """Phase 5 invariant: emitted StructuralIntent carries the active
        programme's id during its window.
        """
        # Pre-existing leak: director.tick_once() writes
        # homage_rotation_mode=paused to /dev/shm/hapax-structural/intent.json
        # (the module's hard-coded path), which the choreographer's
        # default _STRUCTURAL_INTENT_FILE then reads in subsequent
        # invariant tests, silently flipping them all to the paused
        # early-return branch and producing empty plans. Redirect the
        # writes to tmp_path so the test stays self-contained.
        monkeypatch.setattr(sd, "_STRUCTURAL_INTENT_PATH", tmp_path / "intent.json")
        monkeypatch.setattr(sd, "_STRUCTURAL_INTENT_JSONL", tmp_path / "structural-intent.jsonl")

        payload = _three_programme_plan_payload(show_id)
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id=show_id)
        assert plan is not None
        for prog in plan.programmes:
            store.add(prog)

        active = store.activate(plan.programmes[0].programme_id, now=1000.0)

        director = sd.StructuralDirector(
            llm_fn=_stub_llm(
                {
                    "scene_mode": "idle-ambient",
                    "preset_family_hint": "calm-textural",
                    "long_horizon_direction": "stay quiet",
                    "homage_rotation_mode": "paused",
                }
            ),
            programme_provider=lambda: active,
        )
        intent = director.tick_once()
        assert intent is not None
        assert intent.programme_id == active.programme_id

    def test_abort_evaluator_veto_path_e2e(self, show_id: str) -> None:
        """Abort + 5s veto + commit FSM works on a real Programme."""
        payload = _three_programme_plan_payload(show_id)
        planner = ProgrammePlanner(llm_fn=_stub_llm(payload))
        plan = planner.plan(show_id=show_id)
        assert plan is not None
        prog = plan.programmes[0]
        # Add a real abort predicate name + register a fired implementation
        prog.success.abort_predicates.append("operator_left_room")
        clock = _Clock(t0=1000.0)
        evaluator = AbortEvaluator(
            predicates={"operator_left_room": lambda p, s: True},
            now_fn=clock,
        )
        decision = evaluator.evaluate(prog)
        assert decision is not None
        # Operator vetos within window
        clock.advance(2.0)
        veto = Impingement(
            timestamp=clock(),
            source="operator",
            type=ImpingementType.PATTERN_MATCH,
            strength=1.0,
            content={"narrative": "no, keep going"},
            intent_family=VETO_INTENT_FAMILY,
        )
        assert evaluator.handle_veto_impingement(veto) is True
        assert evaluator.pending_abort is None
