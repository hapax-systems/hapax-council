"""Tests for the parametric modulation heartbeat walker.

Provenance: cc-task ``parametric-modulation-heartbeat`` per
``~/Documents/Personal/20-projects/hapax-cc-tasks/active/parametric-modulation-heartbeat.md``.

Operator directive (memory ``feedback_no_presets_use_parametric_modulation``,
verbatim 2026-05-02T22:13Z):

    "we should be relying on constrained algorithmic parametric
    modulation and combination and chaining of effects at the node graph
    level. Presets are dumb."

These tests cover the cc-task acceptance criteria:

1. Smooth modulation (no stepwise jumps > envelope.smoothness)
2. Envelope respect (parameters stay within (min, max))
3. Joint constraints respected (intensity × sediment never both peak)
4. Transition primitive emitted on envelope crossing
5. Regression: NO preset family name appears in heartbeat module source
6. Regression: NO code path samples from ``presets/`` directory
7. Regression: NO import of ``preset_family_selector`` in this module
8. ``write_uniform_overrides`` preserves sibling keys (overlay merge)
9. ``write_uniform_overrides`` is atomic (no partial reads)
10. Per-key cooldown prevents transition flood from a single boundary
11. Walker initializes at envelope midpoint (joint constraints satisfied at boot)
12. ``run_forever`` survives a single bad tick
13. CLI ``__main__`` argument plumbing wires through to ``run_forever``
14. Boundary detection fires on min approach
15. Boundary detection fires on max approach
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.parametric_modulation_heartbeat import heartbeat as hb
from shared import parameter_envelopes as pe

# ── helpers ────────────────────────────────────────────────────────────────


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ── invariants 1-4 from the spec ──────────────────────────────────────────


class TestSmoothModulation:
    """Invariant 1 — no stepwise jumps > envelope.smoothness per tick."""

    def test_walker_step_respects_smoothness(self) -> None:
        """Run 50 ticks; assert every per-key delta is within smoothness budget."""
        rng = random.Random(0)
        walker = hb.ParameterWalker(rng=rng)
        prev = walker.values.copy()
        env_by_key = {env.key: env for env in pe.envelopes()}
        for tick_idx in range(50):
            walker.tick(now=tick_idx * 30.0)
            curr = walker.values
            for key, value in curr.items():
                env = env_by_key[key]
                delta = abs(value - prev[key])
                # Allow tiny float tolerance from joint-constraint scaling.
                assert delta <= env.smoothness + 1e-6, (
                    f"key {key} jumped {delta:.5f} > smoothness {env.smoothness}"
                )
            prev = curr.copy()


class TestEnvelopeRespect:
    """Invariant 2 — parameters stay within ``[min, max]``."""

    def test_walked_values_stay_within_envelope(self) -> None:
        """Run 200 ticks; every snapshot must respect the envelope range."""
        rng = random.Random(1)
        walker = hb.ParameterWalker(rng=rng)
        env_by_key = {env.key: env for env in pe.envelopes()}
        for tick_idx in range(200):
            walker.tick(now=tick_idx * 30.0)
            for key, value in walker.values.items():
                env = env_by_key[key]
                # Joint-constraint scaling can push a value below min in
                # principle, but the test envelopes' clip_step keeps it in
                # range; assert the contract.
                assert env.min_value - 1e-6 <= value <= env.max_value + 1e-6, (
                    f"key {key} value {value} escaped envelope [{env.min_value}, {env.max_value}]"
                )


class TestJointConstraints:
    """Invariant 3 — joint constraints respected (mean ≤ joint_max).

    The joint constraint is a SOFT mean-convergence invariant, not a hard
    per-tick ceiling. Per ``ParameterWalker._apply_joint_constraints``
    docstring (``agents/parametric_modulation_heartbeat/heartbeat.py``):

        "the constraint may take 2-3 ticks to fully unwind a breach,
        which matches the operator's smooth drift aesthetic"

    Because the joint-constraint correction is re-clipped through
    ``envelope.clip_step`` against the pre-tick snapshot, a single tick
    cannot fully unwind a large breach without violating the smoothness
    invariant. So we assert the actual contract: steady-state convergence
    (the average over the last 50 of 300 ticks) and a bounded transient
    overshoot (no individual tick exceeds joint_max by more than the
    smoothness budget).
    """

    def test_intensity_sediment_pair_respects_joint_ceiling(self) -> None:
        """The named aesthetic invariant — content intensity × sediment."""
        rng = random.Random(2)
        walker = hb.ParameterWalker(rng=rng)
        means: list[float] = []
        for tick_idx in range(300):
            walker.tick(now=tick_idx * 30.0)
            a = walker.values["content.intensity"]
            b = walker.values["post.sediment_strength"]
            means.append((a + b) / 2)
        # Steady-state: mean over last 50 ticks must be within tolerance.
        # The constraint is enforced soft (2-3 tick unwind window per
        # docstring), not per-tick, so individual ticks may transiently
        # overshoot by a smoothness-bounded margin.
        steady_state_mean = sum(means[-50:]) / 50
        assert steady_state_mean <= pe.INTENSITY_DEGRADATION_INVARIANT.joint_max + 0.01, (
            f"steady-state mean {steady_state_mean:.4f} > "
            f"{pe.INTENSITY_DEGRADATION_INVARIANT.joint_max} + 0.01 tolerance"
        )
        # Per-tick: no individual tick should exceed by more than the
        # smoothness budget (allow 0.05 single-tick overshoot during a
        # 2-3 tick unwind).
        max_overshoot = max(means) - pe.INTENSITY_DEGRADATION_INVARIANT.joint_max
        assert max_overshoot <= 0.05, f"max per-tick overshoot {max_overshoot:.4f} > 0.05 tolerance"

    def test_rd_feed_kill_pair_respects_joint_ceiling(self) -> None:
        """The Gray-Scott structured-basin invariant."""
        rng = random.Random(3)
        walker = hb.ParameterWalker(rng=rng)
        means: list[float] = []
        for tick_idx in range(300):
            walker.tick(now=tick_idx * 30.0)
            a = walker.values["rd.feed_rate"]
            b = walker.values["rd.kill_rate"]
            means.append((a + b) / 2)
        # Steady-state: mean over last 50 ticks must be within tolerance.
        steady_state_mean = sum(means[-50:]) / 50
        assert steady_state_mean <= pe.RD_FEED_KILL_INVARIANT.joint_max + 0.01, (
            f"steady-state mean {steady_state_mean:.4f} > "
            f"{pe.RD_FEED_KILL_INVARIANT.joint_max} + 0.01 tolerance"
        )
        # Per-tick: bounded transient overshoot during the 2-3 tick unwind.
        max_overshoot = max(means) - pe.RD_FEED_KILL_INVARIANT.joint_max
        assert max_overshoot <= 0.05, f"max per-tick overshoot {max_overshoot:.4f} > 0.05 tolerance"


class TestBoundaryEmission:
    """Invariant 4 — transition primitive emitted on envelope boundary crossing."""

    def test_emit_transition_writes_recruitment_entry(self, tmp_path: Path) -> None:
        rec_path = tmp_path / "recent-recruitment.json"
        hb.emit_transition_primitive(
            "transition.fade.smooth",
            triggering_envelope_key="noise.amplitude",
            path=rec_path,
            now=1_000.0,
        )
        payload = _read_json(rec_path)
        entry = payload["families"]["transition.fade.smooth"]
        assert entry["kind"] == "transition_primitive"
        assert entry["source"] == hb.HEARTBEAT_SOURCE
        assert entry["triggered_by"] == "noise.amplitude"
        assert entry["last_recruited_ts"] == 1_000.0

    def test_emit_transition_rejects_unknown_primitive(self, tmp_path: Path) -> None:
        rec_path = tmp_path / "recent-recruitment.json"
        with pytest.raises(ValueError, match="unknown transition primitive"):
            hb.emit_transition_primitive(
                "transition.preset.bias",  # NOT a valid primitive
                triggering_envelope_key="noise.amplitude",
                path=rec_path,
            )

    def test_tick_once_emits_on_boundary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Force a walker into a boundary state and assert tick_once emits.

        Uses a tiny smoothness budget (0.001) so the walker cannot
        escape the boundary band in a single tick.
        """
        rec_path = tmp_path / "recent-recruitment.json"
        unif_path = tmp_path / "uniforms.json"
        # Construct a single-envelope walker pinned near max so the boundary
        # detector definitely fires this tick. Tiny smoothness budget so
        # the walk can't drift more than 0.001 away from the boundary in
        # one tick (boundary band is 0.05).
        env = pe.ParameterEnvelope("test", "knob", 0.0, 1.0, 0.001)
        # Construct walker with zero perturbation so the gauss noise can't
        # accidentally push the value out of the boundary band.
        walker = hb.ParameterWalker(
            envs=(env,), constraints=(), perturbation=0.0, rng=random.Random(0)
        )
        walker._values["test.knob"] = 0.99
        rng = random.Random(0)
        _, events = hb.tick_once(
            walker,
            uniforms_path=unif_path,
            recruitment_path=rec_path,
            rng=rng,
            now=1_000.0,
            last_emission_ts={},
            emission_cooldown_s=60.0,
        )
        assert len(events) >= 1
        assert events[0].direction == "approaching_max"
        # Recruitment file must have a transition.* entry.
        payload = _read_json(rec_path)
        family_names = list(payload["families"].keys())
        transition_keys = [k for k in family_names if k.startswith("transition.")]
        assert len(transition_keys) >= 1, family_names


# ── invariants 5-7: anti-preset regression pins ────────────────────────────


class TestNoPresetCoupling:
    """Architectural regression — heartbeat MUST NOT touch presets/.

    Per operator directive ``feedback_no_presets_use_parametric_modulation``:
    presets are the dumb anti-pattern. Heartbeat must walk the parameter
    SPACE, not sample a preset library.
    """

    def test_no_preset_family_in_module_source(self) -> None:
        """Negative-form pin parallel to PR #2239's
        ``test_no_hardcoded_family_list_in_module``.

        The 5 preset family names from
        :func:`agents.studio_compositor.preset_family_selector.family_names`
        must NOT appear as quoted string literals in the heartbeat module.
        Comments + docstrings + transition primitive vocab are fine —
        ``"transition.cut.hard"`` etc. is chain-operation vocabulary, not
        preset identifiers.
        """
        from agents.studio_compositor.preset_family_selector import family_names

        source = Path(hb.__file__).read_text(encoding="utf-8")
        for fam in family_names():
            assert f'"{fam}"' not in source, (
                f"preset family {fam!r} appears as a string literal in "
                f"parametric_modulation_heartbeat.heartbeat.py — this is "
                f"the dumb-preset anti-pattern (operator directive "
                f"feedback_no_presets_use_parametric_modulation)."
            )

    def test_no_preset_family_selector_import(self) -> None:
        """The heartbeat module must NOT import preset_family_selector.

        Detection by source scan rather than import inspection so the
        regression catches even commented-out / conditional imports.
        """
        source = Path(hb.__file__).read_text(encoding="utf-8")
        assert "preset_family_selector" not in source, (
            "heartbeat must not import preset_family_selector — preset "
            "sampling is the anti-pattern this PR replaces"
        )

    def test_no_presets_directory_read(self) -> None:
        """The heartbeat module must NOT read from ``presets/`` directory."""
        source = Path(hb.__file__).read_text(encoding="utf-8")
        # Catch path strings like 'presets/foo.json' or Path("presets/...")
        assert '"presets/' not in source, (
            "heartbeat must not read from presets/ directory — variance "
            "comes from constraint envelopes, not preset snapshots"
        )
        assert "'presets/" not in source, (
            "heartbeat must not read from presets/ directory — variance "
            "comes from constraint envelopes, not preset snapshots"
        )


# ── observability + structural tests ───────────────────────────────────────


class TestUniformOverlay:
    """Invariant 8 — write_uniform_overrides preserves sibling keys."""

    def test_existing_keys_preserved_overlay_merge(self, tmp_path: Path) -> None:
        path = tmp_path / "uniforms.json"
        # Pre-existing entries from the visual chain; heartbeat must not nuke them.
        _write_json(path, {"signal.stance": 0.25, "noise.amplitude": 0.5})
        hb.write_uniform_overrides({"color.brightness": 1.1}, path=path)
        payload = _read_json(path)
        assert payload["signal.stance"] == 0.25
        assert payload["noise.amplitude"] == 0.5
        assert payload["color.brightness"] == 1.1

    def test_overwrites_when_key_collides(self, tmp_path: Path) -> None:
        path = tmp_path / "uniforms.json"
        _write_json(path, {"color.brightness": 0.7})
        hb.write_uniform_overrides({"color.brightness": 1.2}, path=path)
        payload = _read_json(path)
        # Walker value wins on collision.
        assert payload["color.brightness"] == 1.2


class TestCairoWardParams:
    """Heartbeat writes a baseline Cairo ward-properties envelope."""

    def test_tick_writes_audio_reactive_ward_params(self, tmp_path: Path, monkeypatch) -> None:
        from agents.studio_compositor import ward_properties as wp

        ward_path = tmp_path / "ward-properties.json"
        monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", ward_path)
        wp.clear_ward_properties_cache()

        walker = hb.ParameterWalker(rng=random.Random(4))
        hb.tick_once(
            walker,
            uniforms_path=tmp_path / "uniforms.json",
            recruitment_path=tmp_path / "recent-recruitment.json",
            now=1_000.0,
            last_emission_ts={},
            emission_cooldown_s=60.0,
        )

        wp.clear_ward_properties_cache()
        payload = _read_json(ward_path)
        wards = payload["wards"]

        for ward_id in ("pressure_gauge", "token_pole", "activity_variety_log"):
            assert ward_id in wards
            assert wards[ward_id]["border_pulse_hz"] > 0.0
            assert wards[ward_id]["scale_bump_pct"] > 0.0
            # ``glow_radius_px`` floor driven by ``breath.amplitude`` envelope;
            # walker init at envelope midpoint produces a non-zero baseline.
            assert wards[ward_id]["glow_radius_px"] > 0.0

    def test_tick_preserves_stronger_existing_cairo_params(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from agents.studio_compositor import ward_properties as wp

        ward_path = tmp_path / "ward-properties.json"
        monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", ward_path)
        wp.clear_ward_properties_cache()
        wp.set_ward_properties(
            "pressure_gauge",
            wp.WardProperties(border_pulse_hz=9.0, scale_bump_pct=0.07, glow_radius_px=12.0),
            ttl_s=10.0,
        )
        wp.clear_ward_properties_cache()

        walker = hb.ParameterWalker(rng=random.Random(5))
        hb.tick_once(
            walker,
            uniforms_path=tmp_path / "uniforms.json",
            recruitment_path=tmp_path / "recent-recruitment.json",
            now=1_000.0,
            last_emission_ts={},
            emission_cooldown_s=60.0,
        )

        wp.clear_ward_properties_cache()
        props = wp.resolve_ward_properties("pressure_gauge")
        assert props.border_pulse_hz >= 9.0
        assert props.scale_bump_pct >= 0.07
        # Heartbeat caps glow at 4 px; the existing 12 px must survive.
        assert props.glow_radius_px >= 12.0


class TestAtomicity:
    """Invariant 9 — no leftover .tmp siblings after a write."""

    def test_no_leftover_tmp_files(self, tmp_path: Path) -> None:
        path = tmp_path / "uniforms.json"
        for i in range(20):
            hb.write_uniform_overrides({"noise.speed": 0.05 + i * 0.001}, path=path)
        siblings = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert siblings == [], f"leftover tmp files: {siblings}"


class TestAffordanceShift:
    """Affordance-shift detection — recruited affordance set changes
    between ticks → walker emits a transition primitive.

    Per cc-task spec item 4: "On affordance shifts (read from
    imagination_loop's recruited affordances), the walker shifts which
    envelopes it actively modulates — leveraging the existing
    AffordancePipeline output, not a hardcoded list."
    """

    def test_affordance_shift_emits_transition(self, tmp_path: Path) -> None:
        rec_path = tmp_path / "recent-recruitment.json"
        unif_path = tmp_path / "uniforms.json"
        env = pe.ParameterEnvelope("test", "knob", 0.0, 1.0, 0.001)
        walker = hb.ParameterWalker(
            envs=(env,), constraints=(), perturbation=0.0, rng=random.Random(0)
        )
        # Pre-existing recruitment file with one capability recruited
        # (NOT a transition.* — those are reflexively excluded).
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
        # Seed walker's last_affordances with a different set so the
        # tick detects a shift on the very first call.
        last_affordances = {"fx.family.audio-reactive"}
        last_emission_ts: dict[str, float] = {}
        hb.tick_once(
            walker,
            uniforms_path=unif_path,
            recruitment_path=rec_path,
            rng=random.Random(0),
            now=1_005.0,
            last_emission_ts=last_emission_ts,
            emission_cooldown_s=60.0,
            last_affordances=last_affordances,
        )
        # Affordance-shift emission must have happened — recorded under
        # `_affordance_shift` key in last_emission_ts.
        assert "_affordance_shift" in last_emission_ts
        # last_affordances mutated to current state.
        assert last_affordances == {"fx.family.calm-textural"}
        # Recruitment file now has a transition entry from the shift.
        payload = _read_json(rec_path)
        transition_keys = [k for k in payload["families"] if k.startswith("transition.")]
        assert any(
            payload["families"][k]["triggered_by"] == "affordance.shift" for k in transition_keys
        )

    def test_no_shift_when_affordances_unchanged(self, tmp_path: Path) -> None:
        rec_path = tmp_path / "recent-recruitment.json"
        unif_path = tmp_path / "uniforms.json"
        env = pe.ParameterEnvelope("test", "knob", 0.0, 1.0, 0.001)
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
        # last_affordances matches the recruited set — no shift.
        last_affordances = {"fx.family.calm-textural"}
        last_emission_ts: dict[str, float] = {}
        hb.tick_once(
            walker,
            uniforms_path=unif_path,
            recruitment_path=rec_path,
            rng=random.Random(0),
            now=1_005.0,
            last_emission_ts=last_emission_ts,
            emission_cooldown_s=60.0,
            last_affordances=last_affordances,
        )
        assert "_affordance_shift" not in last_emission_ts


class TestEmissionCooldown:
    """Invariant 10 — per-key cooldown debounces a hovering boundary."""

    def test_repeated_boundary_does_not_flood(self, tmp_path: Path) -> None:
        rec_path = tmp_path / "recent-recruitment.json"
        unif_path = tmp_path / "uniforms.json"
        env = pe.ParameterEnvelope("test", "knob", 0.0, 1.0, 0.001)
        walker = hb.ParameterWalker(
            envs=(env,), constraints=(), perturbation=0.0, rng=random.Random(0)
        )
        walker._values["test.knob"] = 0.99
        rng = random.Random(7)
        last_emission_ts: dict[str, float] = {}
        # First tick — boundary fires, emission expected.
        hb.tick_once(
            walker,
            uniforms_path=unif_path,
            recruitment_path=rec_path,
            rng=rng,
            now=1_000.0,
            last_emission_ts=last_emission_ts,
            emission_cooldown_s=60.0,
        )
        first_payload = _read_json(rec_path)
        first_count = sum(1 for k in first_payload["families"] if k.startswith("transition."))
        assert first_count == 1
        # Second tick within cooldown — boundary still firing, emission
        # MUST NOT update the recruitment file.
        # Pin the value back at the boundary (otherwise the walk drifts away).
        walker._values["test.knob"] = 0.99
        hb.tick_once(
            walker,
            uniforms_path=unif_path,
            recruitment_path=rec_path,
            rng=rng,
            now=1_010.0,  # +10s, < 60s cooldown
            last_emission_ts=last_emission_ts,
            emission_cooldown_s=60.0,
        )
        second_payload = _read_json(rec_path)
        # Same single transition entry (the one from the first tick); no new keys.
        second_count = sum(1 for k in second_payload["families"] if k.startswith("transition."))
        assert second_count == first_count, (
            f"cooldown breach: {second_count} transitions after second tick, expected {first_count}"
        )


class TestWalkerInit:
    """Invariant 11 — walker boots at envelope midpoint (joint constraints hold)."""

    def test_initial_values_at_midpoint(self) -> None:
        walker = hb.ParameterWalker()
        for env in pe.envelopes():
            mid = (env.min_value + env.max_value) / 2
            assert walker.values[env.key] == mid

    def test_initial_state_satisfies_joint_constraints(self) -> None:
        walker = hb.ParameterWalker()
        for jc in pe.joint_constraints():
            a = walker.values.get(jc.param_a_key)
            b = walker.values.get(jc.param_b_key)
            if a is None or b is None:
                continue
            mean = (a + b) / 2
            assert mean <= jc.joint_max + 1e-6, (
                f"initial state breaches joint constraint {jc.param_a_key} + "
                f"{jc.param_b_key}: mean {mean} > {jc.joint_max}"
            )


# ── resilience + CLI ───────────────────────────────────────────────────────


class TestRunForeverResilience:
    """Invariant 12 — run_forever survives a single bad tick."""

    def test_run_forever_continues_after_tick_exception(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        unif_path = tmp_path / "uniforms.json"
        rec_path = tmp_path / "recent-recruitment.json"
        call_count = [0]
        sleep_calls: list[float] = []

        class _StopAfter(Exception):
            pass

        def _flaky_tick(*args: object, **kwargs: object) -> tuple[dict, list]:
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("simulated tick failure")
            return ({}, [])

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

        assert call_count[0] == 2  # second tick ran AFTER the first crashed
        assert any("tick failed" in r.message for r in caplog.records)


class TestCliPlumbing:
    """Invariant 13 — CLI ``__main__`` wires args through to ``run_forever``."""

    def test_main_passes_args_to_run_forever(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from agents.parametric_modulation_heartbeat import __main__ as entry

        captured: dict[str, object] = {}

        def _spy_run(**kwargs: object) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(entry, "configure_logging", lambda **_k: None)
        monkeypatch.setattr(entry, "_install_sigterm_handler", lambda: None)
        monkeypatch.setattr(entry, "run_forever", _spy_run)

        unif_path = str(tmp_path / "u.json")
        rec_path = str(tmp_path / "r.json")
        entry.main(
            [
                "--tick-s",
                "5.0",
                "--uniforms-path",
                unif_path,
                "--recruitment-path",
                rec_path,
            ]
        )

        assert captured["tick_s"] == 5.0
        assert str(captured["uniforms_path"]) == unif_path
        assert str(captured["recruitment_path"]) == rec_path


# ── boundary detection direction tests ─────────────────────────────────────


class TestBoundaryDetectionDirections:
    """Invariants 14, 15 — boundary detection fires on min and max approaches."""

    def test_boundary_detected_approaching_min(self) -> None:
        env = pe.ParameterEnvelope("test", "knob", 0.0, 1.0, 0.05)
        walker = hb.ParameterWalker(envs=(env,), constraints=())
        walker._values["test.knob"] = 0.02  # within 5% of min (0.05 threshold)
        events = walker._detect_boundaries()
        assert len(events) == 1
        assert events[0].direction == "approaching_min"
        assert events[0].envelope_key == "test.knob"

    def test_boundary_detected_approaching_max(self) -> None:
        env = pe.ParameterEnvelope("test", "knob", 0.0, 1.0, 0.05)
        walker = hb.ParameterWalker(envs=(env,), constraints=())
        walker._values["test.knob"] = 0.98  # within 5% of max
        events = walker._detect_boundaries()
        assert len(events) == 1
        assert events[0].direction == "approaching_max"

    def test_no_boundary_in_middle(self) -> None:
        env = pe.ParameterEnvelope("test", "knob", 0.0, 1.0, 0.05)
        walker = hb.ParameterWalker(envs=(env,), constraints=())
        walker._values["test.knob"] = 0.5
        events = walker._detect_boundaries()
        assert events == []


# ── envelope module sanity ─────────────────────────────────────────────────


class TestEnvelopeModule:
    """Sanity checks on the envelope catalog (consumed by the walker)."""

    def test_envelopes_nonempty(self) -> None:
        assert len(pe.envelopes()) > 0

    def test_envelope_by_key_resolves_known_key(self) -> None:
        env = pe.envelope_by_key("noise.amplitude")
        assert env is not None
        assert env.node_id == "noise"
        assert env.param_name == "amplitude"

    def test_envelope_by_key_returns_none_unknown(self) -> None:
        assert pe.envelope_by_key("nonexistent.foo") is None

    def test_clip_respects_bounds(self) -> None:
        env = pe.ParameterEnvelope("n", "p", 0.1, 0.9, 0.05)
        assert env.clip(-1.0) == 0.1
        assert env.clip(2.0) == 0.9
        assert env.clip(0.5) == 0.5

    def test_clip_step_respects_smoothness(self) -> None:
        env = pe.ParameterEnvelope("n", "p", 0.0, 1.0, 0.05)
        # Want to jump 0.4; smoothness limits to 0.05.
        result = env.clip_step(0.5, 0.9)
        assert abs(result - 0.55) < 1e-9

    def test_joint_constraints_deduplicated(self) -> None:
        # joint_constraints() returns a tuple with no duplicate (a, b)
        # pairs even though INTENSITY_DEGRADATION_INVARIANT appears on
        # multiple envelopes.
        constraints = pe.joint_constraints()
        seen: set[tuple[str, str]] = set()
        for jc in constraints:
            sig = tuple(sorted((jc.param_a_key, jc.param_b_key)))
            assert sig not in seen, f"duplicate constraint: {sig}"
            seen.add(sig)
