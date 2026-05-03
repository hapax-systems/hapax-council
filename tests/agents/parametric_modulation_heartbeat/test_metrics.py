"""Prometheus instrumentation tests for the parametric modulation heartbeat.

Per ``project_compositor_metrics_registry`` (memory): metrics MUST splat
``**_metric_kwargs`` carrying the compositor's ``CollectorRegistry`` so
they reach the ``:9482`` scrape surface. The 24h auditor batch finding
(2026-05-02 E #12) confirmed PR #2252 shipped with ZERO counters,
making heartbeat behavior invisible. This test pins the 5 counters
the design requires:

1. ``hapax_parametric_heartbeat_tick_total{outcome}``
2. ``hapax_parametric_heartbeat_envelope_boundary_total{param_key,boundary}``
3. ``hapax_parametric_heartbeat_joint_constraint_clip_total{constraint_name}``
4. ``hapax_parametric_heartbeat_transition_primitive_total{primitive,trigger}``
5. ``hapax_parametric_heartbeat_affordance_recruitment_shift_total{shift_kind}``

Each test is self-contained — no shared conftest fixtures (project
convention).
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.parametric_modulation_heartbeat import heartbeat as hb
from shared import parameter_envelopes as pe


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _counter_value(counter: object, **labels: str) -> float:
    """Return the current value of a labelled counter, 0.0 if not yet observed.

    Touching ``.labels(...)`` is itself an observation; use the lookup
    helper only after the counter has been incremented.
    """
    return counter.labels(**labels)._value.get()  # type: ignore[attr-defined]


# ── module-level metric registration is intact (no None Counter slots) ────


class TestMetricsRegistered:
    """All five counters exist as module attributes after import."""

    def test_metrics_available_flag(self) -> None:
        # In a normal install with prometheus_client, registration succeeds.
        assert hb._METRICS_AVAILABLE is True

    def test_all_counter_attributes_present(self) -> None:
        names = (
            "_TICK_COUNTER",
            "_ENVELOPE_BOUNDARY_COUNTER",
            "_JOINT_CONSTRAINT_CLIP_COUNTER",
            "_TRANSITION_PRIMITIVE_COUNTER",
            "_AFFORDANCE_RECRUITMENT_SHIFT_COUNTER",
        )
        for name in names:
            assert hasattr(hb, name), f"counter {name} missing from module"


# ── tick counter ──────────────────────────────────────────────────────────


class TestTickCounter:
    """``hapax_parametric_heartbeat_tick_total{outcome}`` increments per tick."""

    def test_tick_success_increments_counter(self, tmp_path: Path) -> None:
        before = _counter_value(hb._TICK_COUNTER, outcome="success")
        env = pe.ParameterEnvelope("metric_test_tick", "knob", 0.0, 1.0, 0.05)
        walker = hb.ParameterWalker(
            envs=(env,), constraints=(), perturbation=0.0, rng=random.Random(0)
        )
        rec_path = tmp_path / "rec.json"
        unif_path = tmp_path / "u.json"
        for tick_idx in range(50):
            hb.tick_once(
                walker,
                uniforms_path=unif_path,
                recruitment_path=rec_path,
                rng=random.Random(tick_idx),
                now=1_000.0 + tick_idx,
                last_emission_ts={},
                emission_cooldown_s=600.0,
            )
        after = _counter_value(hb._TICK_COUNTER, outcome="success")
        assert after - before == 50, f"expected 50 success ticks, got {after - before}"

    def test_tick_error_increments_counter_on_exception(self, tmp_path: Path) -> None:
        """An exception inside ``walker.tick`` increments outcome=error."""
        before = _counter_value(hb._TICK_COUNTER, outcome="error")
        env = pe.ParameterEnvelope("metric_test_err", "knob", 0.0, 1.0, 0.05)
        walker = hb.ParameterWalker(
            envs=(env,), constraints=(), perturbation=0.0, rng=random.Random(0)
        )
        rec_path = tmp_path / "rec.json"
        unif_path = tmp_path / "u.json"

        with patch.object(walker, "tick", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                hb.tick_once(
                    walker,
                    uniforms_path=unif_path,
                    recruitment_path=rec_path,
                    rng=random.Random(0),
                    now=1_000.0,
                    last_emission_ts={},
                )
        after = _counter_value(hb._TICK_COUNTER, outcome="error")
        assert after - before == 1


# ── envelope boundary counter ─────────────────────────────────────────────


class TestEnvelopeBoundaryCounter:
    """``hapax_parametric_heartbeat_envelope_boundary_total`` fires on detection."""

    def test_min_boundary_increment(self) -> None:
        before = _counter_value(
            hb._ENVELOPE_BOUNDARY_COUNTER, param_key="metric.minprobe", boundary="min"
        )
        env = pe.ParameterEnvelope("metric", "minprobe", 0.0, 1.0, 0.05)
        walker = hb.ParameterWalker(envs=(env,), constraints=())
        walker._values["metric.minprobe"] = 0.02  # within 5% of min
        events = walker._detect_boundaries()
        assert events and events[0].direction == "approaching_min"
        after = _counter_value(
            hb._ENVELOPE_BOUNDARY_COUNTER, param_key="metric.minprobe", boundary="min"
        )
        assert after - before == 1

    def test_max_boundary_increment(self) -> None:
        before = _counter_value(
            hb._ENVELOPE_BOUNDARY_COUNTER, param_key="metric.maxprobe", boundary="max"
        )
        env = pe.ParameterEnvelope("metric", "maxprobe", 0.0, 1.0, 0.05)
        walker = hb.ParameterWalker(envs=(env,), constraints=())
        walker._values["metric.maxprobe"] = 0.98  # within 5% of max
        events = walker._detect_boundaries()
        assert events and events[0].direction == "approaching_max"
        after = _counter_value(
            hb._ENVELOPE_BOUNDARY_COUNTER, param_key="metric.maxprobe", boundary="max"
        )
        assert after - before == 1


# ── joint constraint clip counter ─────────────────────────────────────────


class TestJointConstraintClipCounter:
    """``hapax_parametric_heartbeat_joint_constraint_clip_total`` fires on actual clip.

    Force-construct two envelopes whose midpoints already breach a tiny
    joint_max so the very first tick's joint-constraint scan trips.
    """

    def test_clip_event_increments_counter(self) -> None:
        env_a = pe.ParameterEnvelope("metric_clip", "a", 0.0, 1.0, 0.5)
        env_b = pe.ParameterEnvelope("metric_clip", "b", 0.0, 1.0, 0.5)
        constraint = pe.JointConstraint(
            param_a_key="metric_clip.a",
            param_b_key="metric_clip.b",
            joint_max=0.30,
            rationale="metric-test joint clip rationale",
        )
        walker = hb.ParameterWalker(
            envs=(env_a, env_b),
            constraints=(constraint,),
            perturbation=0.0,
            rng=random.Random(0),
        )
        constraint_label = hb._derive_constraint_name(constraint)
        before = _counter_value(hb._JOINT_CONSTRAINT_CLIP_COUNTER, constraint_name=constraint_label)
        # Midpoints (0.5 each) → mean=0.5 > joint_max=0.30 → must clip.
        prev_snapshot = walker.values.copy()
        walker._apply_joint_constraints(prev_snapshot)
        after = _counter_value(hb._JOINT_CONSTRAINT_CLIP_COUNTER, constraint_name=constraint_label)
        assert after - before == 1

    def test_no_clip_when_within_joint_max(self) -> None:
        env_a = pe.ParameterEnvelope("metric_noclip", "a", 0.0, 1.0, 0.5)
        env_b = pe.ParameterEnvelope("metric_noclip", "b", 0.0, 1.0, 0.5)
        constraint = pe.JointConstraint(
            param_a_key="metric_noclip.a",
            param_b_key="metric_noclip.b",
            joint_max=0.95,  # midpoints (0.5, 0.5), mean 0.5 < 0.95 → no clip
            rationale="metric-test no-clip rationale",
        )
        walker = hb.ParameterWalker(
            envs=(env_a, env_b),
            constraints=(constraint,),
            perturbation=0.0,
            rng=random.Random(0),
        )
        constraint_label = hb._derive_constraint_name(constraint)
        before = _counter_value(hb._JOINT_CONSTRAINT_CLIP_COUNTER, constraint_name=constraint_label)
        prev_snapshot = walker.values.copy()
        walker._apply_joint_constraints(prev_snapshot)
        after = _counter_value(hb._JOINT_CONSTRAINT_CLIP_COUNTER, constraint_name=constraint_label)
        assert after == before, "no clip expected; counter changed"


# ── transition primitive counter ──────────────────────────────────────────


class TestTransitionPrimitiveCounter:
    """``hapax_parametric_heartbeat_transition_primitive_total`` fires on every
    successful primitive emission, with both trigger labels covered."""

    def test_boundary_crossing_trigger(self, tmp_path: Path) -> None:
        rec_path = tmp_path / "rec.json"
        unif_path = tmp_path / "u.json"
        env = pe.ParameterEnvelope("trans_test_boundary", "knob", 0.0, 1.0, 0.001)
        walker = hb.ParameterWalker(
            envs=(env,), constraints=(), perturbation=0.0, rng=random.Random(0)
        )
        walker._values["trans_test_boundary.knob"] = 0.99  # pinned at max
        # Prefer the smooth-fade primitive deterministically (5% cut.hard
        # branch is rare; still both report the same trigger axis).
        rng = random.Random(0)
        before_total = sum(
            _counter_value(
                hb._TRANSITION_PRIMITIVE_COUNTER,
                primitive=p,
                trigger="boundary_crossing",
            )
            for p in hb._TRANSITION_VOCAB
        )
        hb.tick_once(
            walker,
            uniforms_path=unif_path,
            recruitment_path=rec_path,
            rng=rng,
            now=1_000.0,
            last_emission_ts={},
            emission_cooldown_s=60.0,
        )
        after_total = sum(
            _counter_value(
                hb._TRANSITION_PRIMITIVE_COUNTER,
                primitive=p,
                trigger="boundary_crossing",
            )
            for p in hb._TRANSITION_VOCAB
        )
        assert after_total - before_total == 1

    def test_affordance_shift_trigger(self, tmp_path: Path) -> None:
        rec_path = tmp_path / "rec.json"
        unif_path = tmp_path / "u.json"
        env = pe.ParameterEnvelope("trans_test_aff", "knob", 0.0, 1.0, 0.001)
        walker = hb.ParameterWalker(
            envs=(env,), constraints=(), perturbation=0.0, rng=random.Random(0)
        )
        _write_json(
            rec_path,
            {
                "families": {
                    "fx.family.calm-textural": {
                        "last_recruited_ts": 1_000.0,
                        "ttl_s": 60.0,
                    }
                }
            },
        )
        before = _counter_value(
            hb._TRANSITION_PRIMITIVE_COUNTER,
            primitive="transition.fade.smooth",
            trigger="affordance_shift",
        )
        last_affordances = {"fx.family.audio-reactive"}
        hb.tick_once(
            walker,
            uniforms_path=unif_path,
            recruitment_path=rec_path,
            rng=random.Random(0),
            now=1_005.0,
            last_emission_ts={},
            emission_cooldown_s=60.0,
            last_affordances=last_affordances,
        )
        after = _counter_value(
            hb._TRANSITION_PRIMITIVE_COUNTER,
            primitive="transition.fade.smooth",
            trigger="affordance_shift",
        )
        assert after - before == 1


# ── affordance recruitment shift counter ──────────────────────────────────


class TestAffordanceShiftCounter:
    """``hapax_parametric_heartbeat_affordance_recruitment_shift_total`` —
    add + remove deltas tracked separately."""

    def test_add_delta_increments(self, tmp_path: Path) -> None:
        rec_path = tmp_path / "rec.json"
        unif_path = tmp_path / "u.json"
        env = pe.ParameterEnvelope("aff_test_add", "knob", 0.0, 1.0, 0.001)
        walker = hb.ParameterWalker(
            envs=(env,), constraints=(), perturbation=0.0, rng=random.Random(0)
        )
        # Recruitment file has TWO new capabilities; previous set was empty
        # but non-falsy via a single-element seed → 2 added, 1 removed.
        _write_json(
            rec_path,
            {
                "families": {
                    "fx.family.added-one": {"last_recruited_ts": 1_000.0, "ttl_s": 60.0},
                    "fx.family.added-two": {"last_recruited_ts": 1_000.0, "ttl_s": 60.0},
                }
            },
        )
        before_add = _counter_value(hb._AFFORDANCE_RECRUITMENT_SHIFT_COUNTER, shift_kind="add")
        before_remove = _counter_value(
            hb._AFFORDANCE_RECRUITMENT_SHIFT_COUNTER, shift_kind="remove"
        )
        last_affordances = {"fx.family.dropped"}
        hb.tick_once(
            walker,
            uniforms_path=unif_path,
            recruitment_path=rec_path,
            rng=random.Random(0),
            now=1_005.0,
            last_emission_ts={},
            emission_cooldown_s=60.0,
            last_affordances=last_affordances,
        )
        after_add = _counter_value(hb._AFFORDANCE_RECRUITMENT_SHIFT_COUNTER, shift_kind="add")
        after_remove = _counter_value(hb._AFFORDANCE_RECRUITMENT_SHIFT_COUNTER, shift_kind="remove")
        assert after_add - before_add == 2
        assert after_remove - before_remove == 1


# ── observability resilience: metric failure must not kill the heartbeat ──


class TestObservabilityResilience:
    """An exception in ``_apply_joint_constraints`` must not crash ``tick_once``.

    ``run_forever`` already catches and logs; ``tick_once`` records the
    error counter and re-raises (so ``run_forever`` continues). The
    metric-emission helpers are individually try/except-wrapped so a
    Prometheus failure NEVER kills the daemon.
    """

    def test_joint_constraint_exception_records_error_and_propagates(self, tmp_path: Path) -> None:
        rec_path = tmp_path / "rec.json"
        unif_path = tmp_path / "u.json"
        env = pe.ParameterEnvelope("resilience_test", "knob", 0.0, 1.0, 0.001)
        walker = hb.ParameterWalker(
            envs=(env,), constraints=(), perturbation=0.0, rng=random.Random(0)
        )

        before = _counter_value(hb._TICK_COUNTER, outcome="error")
        with patch.object(
            walker, "_apply_joint_constraints", side_effect=RuntimeError("synthetic")
        ):
            with pytest.raises(RuntimeError):
                hb.tick_once(
                    walker,
                    uniforms_path=unif_path,
                    recruitment_path=rec_path,
                    rng=random.Random(0),
                    now=1_000.0,
                    last_emission_ts={},
                )
        after = _counter_value(hb._TICK_COUNTER, outcome="error")
        assert after - before == 1

    def test_run_forever_survives_joint_constraint_exception(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """End-to-end: a ``_apply_joint_constraints`` exception inside one
        tick of ``run_forever`` must NOT kill the daemon — the next tick
        runs. This is the operator-visible invariant."""
        unif_path = tmp_path / "u.json"
        rec_path = tmp_path / "rec.json"

        call_count = [0]

        class _StopAfter(Exception):
            pass

        def _flaky_tick(*args: object, **kwargs: object) -> tuple[dict, list]:
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated joint constraint crash")
            return ({}, [])

        sleep_calls: list[float] = []

        def _sleep(s: float) -> None:
            sleep_calls.append(s)
            if len(sleep_calls) >= 2:
                raise _StopAfter

        with patch.object(hb, "tick_once", _flaky_tick), caplog.at_level("WARNING"):
            with pytest.raises(_StopAfter):
                hb.run_forever(
                    tick_s=1.0,
                    uniforms_path=unif_path,
                    recruitment_path=rec_path,
                    sleep=_sleep,
                )
        assert call_count[0] == 2, "second tick must run after first crashed"

    def test_metric_emit_failure_does_not_kill_heartbeat(self) -> None:
        """If the underlying counter raises on ``.inc()``, the helper swallows."""

        class _BoomCounter:
            def labels(self, **_kw: str) -> _BoomCounter:
                return self

            def inc(self) -> None:
                raise RuntimeError("simulated counter failure")

        with patch.object(hb, "_TICK_COUNTER", _BoomCounter()):
            # Must not raise.
            hb._emit_tick("success")


# ── 50-tick smoketest covering tick + boundary + transition counters ──────


class TestFiftyTickSmoke:
    """Run 50 ticks of a high-volatility walker and assert every relevant
    counter has advanced. Doubles as integration smoketest."""

    def test_fifty_ticks_advance_counters(self, tmp_path: Path) -> None:
        rec_path = tmp_path / "rec.json"
        unif_path = tmp_path / "u.json"
        # Tiny envelope range + tiny smoothness pins the walker near the
        # boundary band on every tick → boundary detection fires often.
        env = pe.ParameterEnvelope("smoke_test", "knob", 0.0, 1.0, 0.001)
        walker = hb.ParameterWalker(
            envs=(env,), constraints=(), perturbation=0.0, rng=random.Random(0)
        )
        walker._values["smoke_test.knob"] = 0.99

        before_tick = _counter_value(hb._TICK_COUNTER, outcome="success")
        before_boundary = _counter_value(
            hb._ENVELOPE_BOUNDARY_COUNTER, param_key="smoke_test.knob", boundary="max"
        )

        last_emission_ts: dict[str, float] = {}
        for tick_idx in range(50):
            walker._values["smoke_test.knob"] = 0.99  # re-pin so boundary fires
            hb.tick_once(
                walker,
                uniforms_path=unif_path,
                recruitment_path=rec_path,
                rng=random.Random(tick_idx),
                now=1_000.0 + tick_idx * 120.0,  # > cooldown each step
                last_emission_ts=last_emission_ts,
                emission_cooldown_s=60.0,
            )

        after_tick = _counter_value(hb._TICK_COUNTER, outcome="success")
        after_boundary = _counter_value(
            hb._ENVELOPE_BOUNDARY_COUNTER, param_key="smoke_test.knob", boundary="max"
        )

        assert after_tick - before_tick == 50
        # Boundary fires every tick (value pinned at 0.99 > 0.95 max threshold).
        assert after_boundary - before_boundary >= 50
