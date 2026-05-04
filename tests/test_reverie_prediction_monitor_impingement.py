"""Audit-3 fix #1 regression: reverie_prediction_monitor emits impingements
on each prediction miss. Pins the wiring added in
``agents/reverie_prediction_monitor.py::_emit_prediction_miss_impingements``.
"""

from __future__ import annotations

from unittest.mock import patch

from agents import reverie_prediction_monitor as monitor
from agents.reverie_prediction_monitor import PredictionResult


class TestPredictionMissImpingementEmitter:
    def test_each_unhealthy_prediction_yields_one_impingement(self) -> None:
        predictions = [
            PredictionResult(
                name="P1_thompson_convergence",
                expected="≥0.70",
                actual=0.35,
                healthy=False,
                alert="Thompson mean below 0.70",
                detail='{"foo":"bar"}',
            ),
            PredictionResult(
                name="P5_content_vocabulary_balance",
                expected="0.05–0.5",
                actual=0.91,
                healthy=False,
                alert="extreme modulation",
                detail='{"mean":0.91}',
            ),
            PredictionResult(
                name="P7_uniforms_freshness",
                expected="< 30s",
                actual=12.0,
                healthy=True,
                alert=None,  # NOT a miss; should be skipped
            ),
        ]
        with patch.object(monitor, "emit_prediction_miss_impingement") as mock_emit:
            monitor._emit_prediction_miss_impingements(predictions)
        assert mock_emit.call_count == 2
        first_kwargs = mock_emit.call_args_list[0].kwargs
        assert first_kwargs["prediction_name"] == "P1_thompson_convergence"
        assert first_kwargs["observed"] == 0.35
        assert first_kwargs["alert"] == "Thompson mean below 0.70"
        second_kwargs = mock_emit.call_args_list[1].kwargs
        assert second_kwargs["prediction_name"] == "P5_content_vocabulary_balance"
        assert second_kwargs["observed"] == 0.91

    def test_no_emit_when_all_predictions_healthy(self) -> None:
        predictions = [
            PredictionResult(
                name="P1_thompson_convergence",
                expected="≥0.70",
                actual=0.85,
                healthy=True,
                alert=None,
            ),
        ]
        with patch.object(monitor, "emit_prediction_miss_impingement") as mock_emit:
            monitor._emit_prediction_miss_impingements(predictions)
        assert mock_emit.call_count == 0

    def test_emit_failure_does_not_crash_monitor(self) -> None:
        """Bus write failures must NOT break the prediction-monitor tick loop."""
        predictions = [
            PredictionResult(
                name="P1_thompson_convergence",
                expected="≥0.70",
                actual=0.35,
                healthy=False,
                alert="below threshold",
            ),
        ]
        with patch.object(monitor, "emit_prediction_miss_impingement") as mock_emit:
            mock_emit.side_effect = OSError("bus full")
            monitor._emit_prediction_miss_impingements(predictions)
        assert mock_emit.call_count == 1
