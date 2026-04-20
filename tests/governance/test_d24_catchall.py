"""Tests for D-24 catch-all bundle fixes (AUDIT §8.5, §10.3)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shared.mix_quality.aggregate import _loudness_to_band


class TestLoudnessToBandNaNGuard:
    """AUDIT §10.3 — NaN propagation guard in _loudness_to_band."""

    def test_none_returns_none(self) -> None:
        assert _loudness_to_band(None) is None

    def test_nan_returns_none(self) -> None:
        """NaN from pyloudnorm → None, not NaN propagation."""
        assert _loudness_to_band(float("nan")) is None

    def test_normal_value_unaffected(self) -> None:
        """A valid LUFS reading still computes normally."""
        result = _loudness_to_band(-15.0)
        assert result is not None
        assert result == 1.0

    def test_negative_infinity_returns_low_score(self) -> None:
        """-Inf LUFS (silence) is not NaN but produces 0.0 (way outside band)."""
        result = _loudness_to_band(float("-inf"))
        # offset = abs(-inf - -15) = inf; > falloff_end → returns 0.0.
        assert result == 0.0


class TestQdrantGateImportFailClosed:
    """AUDIT §8.5 — mental_state_redaction unavailable must fail closed."""

    def test_import_failure_raises_on_mental_state_collection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When mental_state_redaction cannot be imported, reads raise."""
        # Force an ImportError on the lazy import inside _redact_points.
        # Monkeypatch sys.modules to simulate module absence.
        import sys

        from agents._governance.qdrant_gate import ConsentGatedQdrant

        # Replace shared.governance.mental_state_redaction with a broken
        # stub whose import raises.
        monkeypatch.setitem(sys.modules, "shared.governance.mental_state_redaction", None)

        gate = ConsentGatedQdrant(inner=MagicMock())
        # Build a fake point with a payload.
        fake_point = MagicMock()
        fake_point.payload = {"thought": "anything"}
        with pytest.raises(RuntimeError, match="mental_state_redaction"):
            gate._redact_points("operator-episodes", [fake_point])

    def test_empty_points_still_pass(self) -> None:
        """Empty/falsy points short-circuit before import; no raise."""
        from agents._governance.qdrant_gate import ConsentGatedQdrant

        gate = ConsentGatedQdrant(inner=MagicMock())
        assert gate._redact_points("operator-episodes", []) == []
        assert gate._redact_points("operator-episodes", None) is None
