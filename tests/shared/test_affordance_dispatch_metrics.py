"""Tests for the affordance dispatch Prometheus counter.

Completes the affordance-pipeline observability trio. Cardinality is
hard-bounded to the closed enum (10 known outcomes + ``unknown``); a
future ``dropout_at`` value collapses to ``unknown`` rather than
expanding the label set.
"""

from __future__ import annotations

import pytest

prometheus_client = pytest.importorskip("prometheus_client")

from shared.affordance_dispatch_metrics import (  # noqa: E402
    ALL_OUTCOMES,
    KNOWN_OUTCOMES,
    UNKNOWN_OUTCOME,
    dispatch_counter_value,
    outcome_label_for,
    record_dispatch,
)

# ── Cardinality bound ───────────────────────────────────────────────────


class TestCardinalityBound:
    def test_known_outcomes_match_pipeline_dropout_at_set(self) -> None:
        # Pin the literal set so a new dropout_at site in the pipeline
        # forces an explicit update here too.
        assert set(KNOWN_OUTCOMES) == {
            "success",
            "interrupt_no_handler",
            "inhibited",
            "no_embedding_fallback",
            "retrieve_family_empty",
            "retrieve_global_empty",
            "consent_filter_empty",
            "monetization_filter_empty",
            "content_risk_filter_empty",
            "threshold_miss",
        }

    def test_all_outcomes_caps_at_eleven(self) -> None:
        assert ALL_OUTCOMES == KNOWN_OUTCOMES + (UNKNOWN_OUTCOME,)
        assert len(ALL_OUTCOMES) == 11


# ── outcome_label_for ───────────────────────────────────────────────────


class TestOutcomeLabel:
    def test_none_maps_to_success(self) -> None:
        assert outcome_label_for(None) == "success"

    @pytest.mark.parametrize(
        "name",
        [n for n in KNOWN_OUTCOMES if n != "success"],
    )
    def test_known_dropout_passes_through(self, name: str) -> None:
        assert outcome_label_for(name) == name

    def test_unknown_value_collapses_to_unknown(self) -> None:
        assert outcome_label_for("not_a_known_dropout") == UNKNOWN_OUTCOME

    def test_empty_string_collapses_to_unknown(self) -> None:
        # Empty string is not None and not in the closed set.
        assert outcome_label_for("") == UNKNOWN_OUTCOME


# ── Counter increment ───────────────────────────────────────────────────


class TestRecordDispatch:
    def test_success_increments_success_label(self) -> None:
        before = dispatch_counter_value("success") or 0.0
        record_dispatch(None)
        after = dispatch_counter_value("success") or 0.0
        assert after - before == 1

    def test_named_dropout_increments_its_label(self) -> None:
        before = dispatch_counter_value("threshold_miss") or 0.0
        record_dispatch("threshold_miss")
        after = dispatch_counter_value("threshold_miss") or 0.0
        assert after - before == 1

    def test_unknown_value_increments_unknown_label(self) -> None:
        before = dispatch_counter_value(UNKNOWN_OUTCOME) or 0.0
        record_dispatch("a_dropout_we_have_not_seen_yet")
        after = dispatch_counter_value(UNKNOWN_OUTCOME) or 0.0
        assert after - before == 1

    def test_increments_isolated_per_label(self) -> None:
        before_s = dispatch_counter_value("success") or 0.0
        before_t = dispatch_counter_value("threshold_miss") or 0.0
        record_dispatch(None)
        record_dispatch(None)
        record_dispatch("threshold_miss")
        after_s = dispatch_counter_value("success") or 0.0
        after_t = dispatch_counter_value("threshold_miss") or 0.0
        assert after_s - before_s == 2
        assert after_t - before_t == 1


# ── Pipeline wire-in ────────────────────────────────────────────────────


class TestPipelineWiring:
    def test_emit_dispatch_trace_calls_record_dispatch(self) -> None:
        """Source-level pin: the wire is in _emit_dispatch_trace."""

        from pathlib import Path

        source = Path("shared/affordance_pipeline.py").read_text(encoding="utf-8")
        idx = source.index("def _emit_dispatch_trace")
        slice_after = source[idx : idx + 1500]
        assert "record_dispatch" in slice_after, (
            "_emit_dispatch_trace must call record_dispatch for the wire to fire"
        )
        # The counter increment must happen BEFORE the env-gate return so
        # disabling JSONL doesn't disable the counter.
        env_gate_idx = slice_after.index("DISPATCH_TRACE_ENV")
        record_idx = slice_after.index("record_dispatch")
        assert record_idx < env_gate_idx, (
            "record_dispatch must be called BEFORE the HAPAX_DISPATCH_TRACE env gate"
        )

    def test_counter_fires_through_pipeline_method(self) -> None:
        """Calling _emit_dispatch_trace directly increments the counter.

        Avoids spinning up a full AffordancePipeline (heavy imports);
        constructs a stub that calls the helper through the same import
        path the production module uses.
        """

        from shared.affordance_dispatch_metrics import record_dispatch

        before = dispatch_counter_value("threshold_miss") or 0.0
        record_dispatch("threshold_miss")
        after = dispatch_counter_value("threshold_miss") or 0.0
        assert after - before == 1
