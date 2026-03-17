"""Tests for circulatory system telemetry instrumentation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared.telemetry import (
    _system_tags,
    hapax_event,
    hapax_interaction,
    hapax_score,
    hapax_span,
    trace_episode_closed,
    trace_perception_tick,
    trace_prediction_tick,
    trace_stimmung_update,
    trace_visual_tick,
)


class TestSystemTags:
    def test_basic(self):
        tags = _system_tags("perception")
        assert tags == ["system:perception"]

    def test_with_extras(self):
        tags = _system_tags("stimmung", ["stance:nominal", "flow:active"])
        assert "system:stimmung" in tags
        assert "stance:nominal" in tags
        assert len(tags) == 3


class TestHapaxSpan:
    def test_span_yields_none_when_unavailable(self):
        with patch("shared.telemetry._get_langfuse", return_value=None):
            with hapax_span("perception", "tick") as span:
                assert span is None

    def test_span_context_manager_doesnt_crash(self):
        """Even with no Langfuse, the context manager works."""
        with patch("shared.telemetry._get_langfuse", return_value=None):
            with hapax_span("stimmung", "update", metadata={"stance": "nominal"}) as _span:
                pass  # no crash


class TestHapaxEvent:
    def test_event_doesnt_crash_when_unavailable(self):
        with patch("shared.telemetry._get_langfuse", return_value=None):
            hapax_event("stimmung", "stance_change", metadata={"from": "nominal", "to": "cautious"})

    def test_event_with_level(self):
        with patch("shared.telemetry._get_langfuse", return_value=None):
            hapax_event("stimmung", "stance_change", level="WARNING")


class TestHapaxScore:
    def test_score_none_span_noop(self):
        hapax_score(None, "confidence", 0.85)  # no crash

    def test_score_calls_span(self):
        mock_span = MagicMock()
        hapax_score(mock_span, "confidence", 0.85, comment="test")
        mock_span.score.assert_called_once_with(
            name="confidence", value=0.85, data_type="NUMERIC", comment="test"
        )


class TestHapaxInteraction:
    def test_interaction_doesnt_crash(self):
        with patch("shared.telemetry._get_langfuse", return_value=None):
            hapax_interaction(
                "stimmung", "engine", "phase_gating",
                metadata={"stance": "degraded", "skipped": 2},
            )


class TestConvenienceFunctions:
    """All convenience functions should be no-ops when Langfuse unavailable."""

    def test_trace_perception_tick(self):
        with patch("shared.telemetry._get_langfuse", return_value=None):
            trace_perception_tick(
                flow_score=0.7, activity="coding",
                audio_energy=0.01, confidence=0.85,
            )

    def test_trace_stimmung_update(self):
        with patch("shared.telemetry._get_langfuse", return_value=None):
            trace_stimmung_update(
                stance="cautious", health=0.1, resource_pressure=0.3,
                error_rate=0.0, throughput=0.2, perception_confidence=0.8,
                llm_cost=0.1, prev_stance="nominal",
            )

    def test_trace_visual_tick(self):
        with patch("shared.telemetry._get_langfuse", return_value=None):
            trace_visual_tick(
                display_state="ambient", signal_count=2,
                tick_interval=3.0, stimmung_stance="nominal",
            )

    def test_trace_episode_closed(self):
        with patch("shared.telemetry._get_langfuse", return_value=None):
            trace_episode_closed(
                activity="coding", duration_s=300,
                flow_state="active", snapshot_count=120,
            )

    def test_trace_prediction_tick(self):
        with patch("shared.telemetry._get_langfuse", return_value=None):
            trace_prediction_tick(
                predictions=3, cache_hit=True,
                cache_hit_rate=0.6, surprise_max=0.3,
            )


class TestLangfuseAvailable:
    """Test behavior when Langfuse client IS available."""

    def test_span_graceful_when_langfuse_import_fails(self):
        """When langfuse module can't be imported, span still works."""
        mock_client = MagicMock()
        with patch("shared.telemetry._get_langfuse", return_value=mock_client):
            # propagate_attributes import will fail if langfuse not installed
            # — the except clause should handle it gracefully
            with hapax_span("perception", "tick", metadata={"flow": 0.7}) as _span:
                # Span is either real or None — both are acceptable
                pass

    def test_score_with_mock_client(self):
        mock_span = MagicMock()
        hapax_score(mock_span, "test_score", 0.5)
        mock_span.score.assert_called_once()
