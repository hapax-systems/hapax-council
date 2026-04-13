"""FreshnessGauge tests — Phase 8 / closes BETA-FINDING-2026-04-13-C.

Works in two modes depending on prometheus_client availability:

- **Without prometheus_client**: the in-memory counters and age timer
  are exercised; Prometheus-registration tests are skipped via
  :func:`pytest.importorskip`.
- **With prometheus_client**: the full suite runs, including registry
  collection assertions.

This mirrors the :mod:`shared.freshness_gauge` module's own graceful
degradation — the gauge works in either environment.
"""

from __future__ import annotations

import time

import pytest

from shared.freshness_gauge import FreshnessGauge


def _new_registry() -> object | None:
    """Return a fresh Prometheus registry if available, else None."""
    prometheus_client = pytest.importorskip(
        "prometheus_client",
        reason="prometheus_client not installed; skipping registry tests",
    )
    return prometheus_client.CollectorRegistry()


# ── Core in-memory contract (runs without prometheus_client) ────────


def test_age_before_first_publish_is_infinity() -> None:
    gauge = FreshnessGauge("t_init", expected_cadence_s=30)
    assert gauge.age_seconds() == float("inf")


def test_is_stale_true_before_first_publish() -> None:
    gauge = FreshnessGauge("t_stale", expected_cadence_s=30)
    assert gauge.is_stale()


def test_mark_published_resets_age_near_zero() -> None:
    gauge = FreshnessGauge("t_pub", expected_cadence_s=30)
    gauge.mark_published()
    assert gauge.age_seconds() < 0.1


def test_mark_published_increments_counter() -> None:
    gauge = FreshnessGauge("t_count", expected_cadence_s=30)
    assert gauge.published_count == 0
    gauge.mark_published()
    gauge.mark_published()
    gauge.mark_published()
    assert gauge.published_count == 3


def test_mark_failed_does_not_reset_age() -> None:
    gauge = FreshnessGauge("t_fail", expected_cadence_s=30)
    gauge.mark_published()
    time.sleep(0.05)
    gauge.mark_failed()
    # Age still counts from the last successful publish, not the failure.
    assert gauge.age_seconds() >= 0.05
    assert gauge.failed_count == 1


def test_is_stale_at_default_10x_threshold() -> None:
    gauge = FreshnessGauge("t_10x", expected_cadence_s=0.01)
    gauge.mark_published()
    time.sleep(0.15)  # 15x cadence
    assert gauge.is_stale()


def test_is_stale_custom_tolerance_mult() -> None:
    gauge = FreshnessGauge("t_tol", expected_cadence_s=0.01)
    gauge.mark_published()
    time.sleep(0.03)  # 3x cadence
    assert not gauge.is_stale(tolerance_mult=5.0)
    assert gauge.is_stale(tolerance_mult=2.0)


def test_name_validation_rejects_leading_digit() -> None:
    with pytest.raises(ValueError):
        FreshnessGauge("1_bad", expected_cadence_s=30)


def test_name_validation_rejects_hyphen() -> None:
    with pytest.raises(ValueError):
        FreshnessGauge("bad-name", expected_cadence_s=30)


def test_name_validation_rejects_uppercase() -> None:
    with pytest.raises(ValueError):
        FreshnessGauge("BadName", expected_cadence_s=30)


def test_rejects_zero_or_negative_cadence() -> None:
    with pytest.raises(ValueError):
        FreshnessGauge("t_zero", expected_cadence_s=0)
    with pytest.raises(ValueError):
        FreshnessGauge("t_neg", expected_cadence_s=-1)


def test_in_memory_mode_works_without_registry() -> None:
    """Constructing with ``registry=None`` still tracks publish counts + age."""
    gauge = FreshnessGauge("t_degraded", expected_cadence_s=30, registry=None)
    assert gauge.published_count == 0
    gauge.mark_published()
    assert gauge.published_count == 1
    assert gauge.age_seconds() < 0.1


# ── Prometheus registry integration (skips without prometheus_client) ──


def test_age_gauge_registered_in_registry() -> None:
    registry = _new_registry()
    gauge = FreshnessGauge("t_reg_age", expected_cadence_s=10, registry=registry)
    gauge.mark_published()
    families = list(registry.collect())  # type: ignore[attr-defined]
    names = {f.name for f in families}
    # Prometheus strips `_total` from the counter name when collecting.
    assert "t_reg_age_published" in names


def test_published_counter_value_visible_in_registry() -> None:
    registry = _new_registry()
    gauge = FreshnessGauge("t_reg_count", expected_cadence_s=10, registry=registry)
    gauge.mark_published()
    gauge.mark_published()
    families = {
        f.name: f
        for f in registry.collect()  # type: ignore[attr-defined]
    }
    assert "t_reg_count_published" in families
    totals = [
        s.value for s in families["t_reg_count_published"].samples if s.name.endswith("_total")
    ]
    assert totals == [2.0]


def test_failed_counter_value_visible_in_registry() -> None:
    registry = _new_registry()
    gauge = FreshnessGauge("t_reg_fail", expected_cadence_s=10, registry=registry)
    gauge.mark_failed()
    gauge.mark_failed()
    gauge.mark_failed()
    families = {
        f.name: f
        for f in registry.collect()  # type: ignore[attr-defined]
    }
    assert "t_reg_fail_failed" in families
    totals = [s.value for s in families["t_reg_fail_failed"].samples if s.name.endswith("_total")]
    assert totals == [3.0]
