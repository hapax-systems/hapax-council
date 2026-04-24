"""Tests for shared/programme_observability.py — Phase 9 partial of D-28.

Verifies the Prometheus metric scaffolding + emit functions. Wires
into ProgrammeManager (Phase 7) when that module exists; until then
the emit functions are tested in isolation against synthetic Programme
stubs.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest  # noqa: TC002
from prometheus_client import REGISTRY

from shared.programme_observability import (
    emit_programme_dwell_update,
    emit_programme_end,
    emit_programme_start,
    emit_soft_prior_override,
)


@dataclass
class _StubProgramme:
    """Minimal Programme structural stub for emit-function tests."""

    programme_id: str = "test-001"
    role: str = "showcase"
    parent_show_id: str = "test-show"
    planned_duration_s: float = 60.0
    elapsed_s: float | None = None


def _read_counter(name: str, **labels) -> float:
    """Read the current value of a labelled Prometheus counter family."""
    for collector in REGISTRY.collect():
        for metric in collector.samples:
            if metric.name == name and metric.labels == labels:
                return float(metric.value)
    return 0.0


def _read_gauge(name: str, **labels) -> float:
    """Read the current value of a labelled Prometheus gauge."""
    for collector in REGISTRY.collect():
        for metric in collector.samples:
            if metric.name == name and metric.labels == labels:
                return float(metric.value)
    return 0.0


class TestEmitProgrammeStart:
    def test_increments_start_counter(self) -> None:
        prog = _StubProgramme(programme_id="prog-start-1", role="ambient", parent_show_id="show-a")
        before = _read_counter("hapax_programme_start_total", role="ambient", show_id="show-a")
        emit_programme_start(prog)
        after = _read_counter("hapax_programme_start_total", role="ambient", show_id="show-a")
        assert after == before + 1.0

    def test_sets_active_gauge_to_1(self) -> None:
        prog = _StubProgramme(programme_id="prog-active-1", role="showcase")
        emit_programme_start(prog)
        v = _read_gauge("hapax_programme_active", programme_id="prog-active-1", role="showcase")
        assert v == 1.0

    def test_sets_planned_duration(self) -> None:
        prog = _StubProgramme(programme_id="prog-dur-1", planned_duration_s=120.0)
        emit_programme_start(prog)
        v = _read_gauge("hapax_programme_duration_planned_seconds", programme_id="prog-dur-1")
        assert v == 120.0

    def test_handles_missing_attrs_gracefully(self) -> None:
        """Programme stub without expected attrs must not crash the emit."""

        class _Bare:
            pass

        # Must not raise.
        emit_programme_start(_Bare())


class TestEmitProgrammeEnd:
    def test_increments_end_counter(self) -> None:
        prog = _StubProgramme(programme_id="prog-end-1", role="ambient", parent_show_id="show-b")
        before = _read_counter(
            "hapax_programme_end_total", role="ambient", show_id="show-b", reason="planned"
        )
        emit_programme_end(prog, reason="planned")
        after = _read_counter(
            "hapax_programme_end_total", role="ambient", show_id="show-b", reason="planned"
        )
        assert after == before + 1.0

    def test_deactivates_gauge(self) -> None:
        prog = _StubProgramme(programme_id="prog-deact-1", role="showcase")
        emit_programme_start(prog)
        emit_programme_end(prog)
        v = _read_gauge("hapax_programme_active", programme_id="prog-deact-1", role="showcase")
        assert v == 0.0

    def test_records_actual_duration_from_elapsed_s(self) -> None:
        prog = _StubProgramme(programme_id="prog-actual-1", elapsed_s=45.5)
        emit_programme_end(prog)
        v = _read_gauge("hapax_programme_duration_actual_seconds", programme_id="prog-actual-1")
        assert v == 45.5

    def test_actual_duration_zero_when_elapsed_none(self) -> None:
        prog = _StubProgramme(programme_id="prog-actual-2", elapsed_s=None)
        emit_programme_end(prog)
        v = _read_gauge("hapax_programme_duration_actual_seconds", programme_id="prog-actual-2")
        assert v == 0.0

    @pytest.mark.parametrize("reason", ["planned", "operator", "emergent", "aborted"])
    def test_all_reason_labels_accepted(self, reason: str) -> None:
        prog = _StubProgramme(
            programme_id=f"prog-reason-{reason}", role="ambient", parent_show_id=f"show-{reason}"
        )
        before = _read_counter(
            "hapax_programme_end_total",
            role="ambient",
            show_id=f"show-{reason}",
            reason=reason,
        )
        emit_programme_end(prog, reason=reason)  # type: ignore[arg-type]
        after = _read_counter(
            "hapax_programme_end_total",
            role="ambient",
            show_id=f"show-{reason}",
            reason=reason,
        )
        assert after == before + 1.0


class TestEmitSoftPriorOverride:
    def test_increments_override_counter(self) -> None:
        before = _read_counter(
            "hapax_programme_soft_prior_overridden_total",
            programme_id="prog-override-1",
            reason="high_pressure",
        )
        emit_soft_prior_override("prog-override-1", reason="high_pressure")
        after = _read_counter(
            "hapax_programme_soft_prior_overridden_total",
            programme_id="prog-override-1",
            reason="high_pressure",
        )
        assert after == before + 1.0

    def test_default_reason_is_high_pressure(self) -> None:
        before = _read_counter(
            "hapax_programme_soft_prior_overridden_total",
            programme_id="prog-override-2",
            reason="high_pressure",
        )
        emit_soft_prior_override("prog-override-2")
        after = _read_counter(
            "hapax_programme_soft_prior_overridden_total",
            programme_id="prog-override-2",
            reason="high_pressure",
        )
        assert after == before + 1.0

    def test_custom_reason_label(self) -> None:
        emit_soft_prior_override("prog-override-3", reason="impingement_burst")
        v = _read_counter(
            "hapax_programme_soft_prior_overridden_total",
            programme_id="prog-override-3",
            reason="impingement_burst",
        )
        assert v == 1.0


class TestEmitProgrammeDwellUpdate:
    def test_on_time_ratio_is_one(self) -> None:
        prog = _StubProgramme(
            programme_id="prog-dwell-1",
            role="showcase",
            planned_duration_s=60.0,
            elapsed_s=60.0,
        )
        emit_programme_dwell_update(prog)
        v = _read_gauge(
            "hapax_programme_dwell_overshoot_ratio",
            programme_id="prog-dwell-1",
            role="showcase",
        )
        assert v == 1.0

    def test_halfway_ratio_is_half(self) -> None:
        prog = _StubProgramme(
            programme_id="prog-dwell-half",
            role="ambient",
            planned_duration_s=120.0,
            elapsed_s=60.0,
        )
        emit_programme_dwell_update(prog)
        v = _read_gauge(
            "hapax_programme_dwell_overshoot_ratio",
            programme_id="prog-dwell-half",
            role="ambient",
        )
        assert v == 0.5

    def test_overshoot_ratio_exceeds_one(self) -> None:
        prog = _StubProgramme(
            programme_id="prog-dwell-over",
            role="showcase",
            planned_duration_s=60.0,
            elapsed_s=120.0,
        )
        emit_programme_dwell_update(prog)
        v = _read_gauge(
            "hapax_programme_dwell_overshoot_ratio",
            programme_id="prog-dwell-over",
            role="showcase",
        )
        assert v == 2.0

    def test_none_programme_sets_sentinel_to_zero(self) -> None:
        emit_programme_dwell_update(None)
        v = _read_gauge(
            "hapax_programme_dwell_overshoot_ratio",
            programme_id="__none__",
            role="__none__",
        )
        assert v == 0.0

    def test_elapsed_none_leaves_gauge_untouched(self) -> None:
        """Programme not yet started → no gauge emission (no divide-by-zero)."""
        prog = _StubProgramme(
            programme_id="prog-dwell-pristine",
            role="showcase",
            planned_duration_s=60.0,
            elapsed_s=None,
        )
        # No prior value on this label → reading returns 0.0 from helper default.
        emit_programme_dwell_update(prog)
        v = _read_gauge(
            "hapax_programme_dwell_overshoot_ratio",
            programme_id="prog-dwell-pristine",
            role="showcase",
        )
        assert v == 0.0  # unchanged from the helper's default

    def test_zero_planned_duration_leaves_gauge_untouched(self) -> None:
        """Programme with zero planned duration must not divide by zero."""
        prog = _StubProgramme(
            programme_id="prog-dwell-zero",
            role="showcase",
            planned_duration_s=0.0,
            elapsed_s=10.0,
        )
        emit_programme_dwell_update(prog)
        v = _read_gauge(
            "hapax_programme_dwell_overshoot_ratio",
            programme_id="prog-dwell-zero",
            role="showcase",
        )
        assert v == 0.0

    def test_exception_in_attribute_access_does_not_propagate(self) -> None:
        class _Trap:
            @property
            def elapsed_s(self) -> float:
                raise RuntimeError("kaboom")

            programme_id = "trap-dwell"
            role = "showcase"
            planned_duration_s = 60.0

        emit_programme_dwell_update(_Trap())  # must not raise


class TestMetricsUnavailableGracefulNoOp:
    def test_no_op_when_metrics_unavailable(self) -> None:
        """All emit functions must be no-ops when prometheus_client is
        unavailable (or _METRICS_AVAILABLE is False). Synthetic test
        patches the module-level flag."""
        from shared import programme_observability as obs_mod

        with patch.object(obs_mod, "_METRICS_AVAILABLE", False):
            # Must not raise on any of the four.
            emit_programme_start(_StubProgramme())
            emit_programme_end(_StubProgramme(elapsed_s=10.0))
            emit_soft_prior_override("prog-x")
            emit_programme_dwell_update(_StubProgramme(elapsed_s=10.0))
            emit_programme_dwell_update(None)


class TestExceptionsCaught:
    def test_exception_in_attribute_access_does_not_propagate(self) -> None:
        """Programme with a property that raises must not break the emit."""

        class _Trap:
            @property
            def role(self) -> str:
                raise RuntimeError("kaboom")

            programme_id = "trap-001"
            parent_show_id = "show"
            planned_duration_s = 60.0

        # Must not raise.
        emit_programme_start(_Trap())


class TestInvariantsDocumented:
    """The two invariant metrics carry semantic contracts. These tests
    don't execute the contracts (they're system-level, not unit-level),
    but they pin the metric NAMES so a future rename trips a regression."""

    def test_set_reduction_metric_named(self) -> None:
        # The set-reduction sentinel lives in demonet_metrics; just verify
        # the name used by Phase 4 matches what Phase 9 documents.
        from shared.governance.demonet_metrics import METRICS

        assert hasattr(METRICS, "inc_programme_candidate_set_reduction")

    def test_soft_prior_override_metric_named(self) -> None:
        # Just-in-this-module: name pin via emit-function existence.
        from shared.programme_observability import emit_soft_prior_override

        assert callable(emit_soft_prior_override)
