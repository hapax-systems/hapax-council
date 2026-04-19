"""Phase C1 tests for HOMAGE Prometheus metrics pipeline.

Pins the six hapax_homage_* metric emitters the framework spec §6
prescribes (homage-completion-plan §C1):

  * hapax_homage_transition_total{package, ward, transition_name, phase}
  * hapax_homage_emphasis_applied_total{ward, intent_family}
  * hapax_homage_render_cadence_hz{ward}
  * hapax_homage_rotation_mode{mode}
  * hapax_homage_active_package{package}
  * hapax_homage_substrate_saturation_target

Each test calls its emitter and asserts the underlying prometheus_client
metric exposes the expected labelled series (or, for the single-series
gauge, the expected value). The tests do not assert on absolute values
because the prometheus_client registries persist across tests in the
same process; they assert on the DELTA produced by the emit call —
``after - before`` — which is invariant across ordering.
"""

from __future__ import annotations

import pytest

pytest.importorskip("prometheus_client")


def _sample_value(metric, labels: dict | None = None) -> float:
    """Read the current float value of a labelled (or unlabelled) metric.

    prometheus_client's ``_value.get()`` API is stable across the 0.x
    series. We avoid ``collect()`` because the compositor REGISTRY
    prepends its own collectors (freshness gauges, camera pad probes)
    making the collect output unwieldy for targeted assertions.
    """
    child = metric.labels(**labels) if labels else metric
    try:
        return float(child._value.get())  # type: ignore[attr-defined]
    except AttributeError:
        # Gauge without a private _value → collect and sum samples.
        total = 0.0
        for fam in metric.collect():
            for sample in fam.samples:
                if not labels or all(sample.labels.get(k) == v for k, v in labels.items()):
                    total += sample.value
        return total


class TestHomageTransitionTotal:
    def test_emit_increments_transition_counter_with_ward_and_phase(self):
        from shared import director_observability as obs

        labels = {
            "package": "bitchx",
            "ward": "test_ward_alpha",
            "transition_name": "ticker-scroll-in",
            "phase": "entry",
        }
        before = _sample_value(obs._homage_transition_total, labels)
        obs.emit_homage_transition(
            "bitchx",
            "ticker-scroll-in",
            ward="test_ward_alpha",
            phase="entry",
        )
        after = _sample_value(obs._homage_transition_total, labels)
        assert after - before == pytest.approx(1.0)

    def test_legacy_call_still_increments(self):
        """Legacy 2-arg calls (no ward/phase kwargs) must not raise."""
        from shared import director_observability as obs

        # Empty-string ward + phase labels — a valid (if coarse) series.
        labels = {
            "package": "bitchx",
            "ward": "",
            "transition_name": "ticker-scroll-in",
            "phase": "",
        }
        before = _sample_value(obs._homage_transition_total, labels)
        obs.emit_homage_transition("bitchx", "ticker-scroll-in")
        after = _sample_value(obs._homage_transition_total, labels)
        assert after - before == pytest.approx(1.0)


class TestHomageEmphasisApplied:
    def test_emit_increments_emphasis_counter(self):
        from shared import director_observability as obs

        labels = {"ward": "test_ward_beta", "intent_family": "structural.emphasis"}
        before = _sample_value(obs._homage_emphasis_applied_total, labels)
        obs.emit_homage_emphasis_applied(
            ward="test_ward_beta",
            intent_family="structural.emphasis",
        )
        after = _sample_value(obs._homage_emphasis_applied_total, labels)
        assert after - before == pytest.approx(1.0)


class TestHomageRenderCadence:
    def test_emit_sets_gauge_value_per_ward(self):
        from shared import director_observability as obs

        obs.emit_homage_render_cadence("test_ward_gamma", 12.5)
        assert _sample_value(
            obs._homage_render_cadence_hz, {"ward": "test_ward_gamma"}
        ) == pytest.approx(12.5)

        # Second emit overwrites (gauge semantics, not counter).
        obs.emit_homage_render_cadence("test_ward_gamma", 7.25)
        assert _sample_value(
            obs._homage_render_cadence_hz, {"ward": "test_ward_gamma"}
        ) == pytest.approx(7.25)


class TestHomageRotationMode:
    def test_emit_one_hots_active_mode(self):
        from shared import director_observability as obs

        obs.emit_homage_rotation_mode("weighted_by_salience")
        active = _sample_value(obs._homage_rotation_mode, {"mode": "weighted_by_salience"})
        sequential = _sample_value(obs._homage_rotation_mode, {"mode": "sequential"})
        paused = _sample_value(obs._homage_rotation_mode, {"mode": "paused"})
        random_mode = _sample_value(obs._homage_rotation_mode, {"mode": "random"})
        assert active == pytest.approx(1.0)
        assert sequential == pytest.approx(0.0)
        assert paused == pytest.approx(0.0)
        assert random_mode == pytest.approx(0.0)

        # Switching modes re-one-hots.
        obs.emit_homage_rotation_mode("paused")
        assert _sample_value(obs._homage_rotation_mode, {"mode": "paused"}) == pytest.approx(1.0)
        assert _sample_value(
            obs._homage_rotation_mode, {"mode": "weighted_by_salience"}
        ) == pytest.approx(0.0)


class TestHomageActivePackage:
    def test_emit_one_hots_active_package(self):
        from shared import director_observability as obs

        obs.emit_homage_active_package("bitchx")
        assert _sample_value(obs._homage_active_package, {"package": "bitchx"}) == pytest.approx(
            1.0
        )

        # A second package should flip bitchx to 0 and set the new one to 1.
        obs.emit_homage_active_package("bitchx-consent-safe")
        assert _sample_value(
            obs._homage_active_package, {"package": "bitchx-consent-safe"}
        ) == pytest.approx(1.0)
        assert _sample_value(obs._homage_active_package, {"package": "bitchx"}) == pytest.approx(
            0.0
        )


class TestHomageSubstrateSaturationTarget:
    def test_emit_sets_gauge(self):
        from shared import director_observability as obs

        obs.emit_homage_substrate_saturation_target(0.7)
        assert _sample_value(obs._homage_substrate_saturation_target) == pytest.approx(0.7)

        # Out-of-band values clamp to [0, 1].
        obs.emit_homage_substrate_saturation_target(2.5)
        assert _sample_value(obs._homage_substrate_saturation_target) == pytest.approx(1.0)

        obs.emit_homage_substrate_saturation_target(-0.3)
        assert _sample_value(obs._homage_substrate_saturation_target) == pytest.approx(0.0)


class TestAllExports:
    def test_phase_c1_emitters_in_dunder_all(self):
        from shared import director_observability as obs

        expected = {
            "emit_homage_transition",
            "emit_homage_emphasis_applied",
            "emit_homage_render_cadence",
            "emit_homage_rotation_mode",
            "emit_homage_active_package",
            "emit_homage_substrate_saturation_target",
        }
        assert expected.issubset(set(obs.__all__))
        for name in expected:
            assert callable(getattr(obs, name))
