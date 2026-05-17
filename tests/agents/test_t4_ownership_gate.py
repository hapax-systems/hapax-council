"""T4 ownership gate — test suite for perspective-t4-ownership-gate.

Authority: CASE-PERSPECTIVE-001
CC-task: perspective-t4-ownership-gate

Tests the Bayesian presence-posterior gate that conditionally suppresses
director compositional emissions when operator ownership confidence is low.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


class TestReadPresencePosterior:
    """_read_presence_posterior reads from perception-state.json."""

    def test_returns_float_and_state_from_file(self, tmp_path: Path) -> None:
        state_file = tmp_path / "perception-state.json"
        state_file.write_text(
            json.dumps({"presence_probability": 0.85, "presence_state": "PRESENT"}),
            encoding="utf-8",
        )
        from agents.studio_compositor.director_loop import _read_presence_posterior

        with patch(
            "agents.studio_compositor.director_loop._PERCEPTION_STATE_PATH", state_file
        ):
            # Clear cache so patch takes effect
            from agents.studio_compositor.director_loop import _PRESENCE_CACHE

            _PRESENCE_CACHE.clear()
            prob, state = _read_presence_posterior()

        assert prob == pytest.approx(0.85)
        assert state == "PRESENT"

    def test_returns_defaults_on_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.json"
        from agents.studio_compositor.director_loop import _read_presence_posterior

        with patch(
            "agents.studio_compositor.director_loop._PERCEPTION_STATE_PATH", missing
        ):
            from agents.studio_compositor.director_loop import _PRESENCE_CACHE

            _PRESENCE_CACHE.clear()
            prob, state = _read_presence_posterior()

        assert prob == 0.0
        assert state == "UNKNOWN"

    def test_returns_defaults_on_corrupt_json(self, tmp_path: Path) -> None:
        state_file = tmp_path / "perception-state.json"
        state_file.write_text("NOT VALID JSON {{{", encoding="utf-8")
        from agents.studio_compositor.director_loop import _read_presence_posterior

        with patch(
            "agents.studio_compositor.director_loop._PERCEPTION_STATE_PATH", state_file
        ):
            from agents.studio_compositor.director_loop import _PRESENCE_CACHE

            _PRESENCE_CACHE.clear()
            prob, state = _read_presence_posterior()

        assert prob == 0.0
        assert state == "UNKNOWN"

    def test_caches_result_within_ttl(self, tmp_path: Path) -> None:
        state_file = tmp_path / "perception-state.json"
        state_file.write_text(
            json.dumps({"presence_probability": 0.7, "presence_state": "PRESENT"}),
            encoding="utf-8",
        )
        from agents.studio_compositor.director_loop import (
            _PRESENCE_CACHE,
            _read_presence_posterior,
        )

        with patch(
            "agents.studio_compositor.director_loop._PERCEPTION_STATE_PATH", state_file
        ):
            _PRESENCE_CACHE.clear()
            prob1, _ = _read_presence_posterior()
            # Update file — should still get cached value
            state_file.write_text(
                json.dumps({"presence_probability": 0.1, "presence_state": "ABSENT"}),
                encoding="utf-8",
            )
            prob2, _ = _read_presence_posterior()

        assert prob1 == pytest.approx(0.7)
        assert prob2 == pytest.approx(0.7)  # cached


class TestOwnershipGateLogic:
    """_ownership_gate_passes implements the 3-tier decision."""

    def _make_intent(self, intent_family: str = "camera.hero"):
        """Minimal mock intent with compositional_impingements."""
        from unittest.mock import MagicMock

        intent = MagicMock()
        imp = MagicMock()
        imp.intent_family = intent_family
        intent.compositional_impingements = [imp]
        return intent

    def test_pass_when_posterior_above_threshold(self, tmp_path: Path) -> None:
        state_file = tmp_path / "perception-state.json"
        state_file.write_text(
            json.dumps({"presence_probability": 0.85, "presence_state": "PRESENT"}),
            encoding="utf-8",
        )
        from agents.studio_compositor.director_loop import (
            _PRESENCE_CACHE,
            _ownership_gate_passes,
        )

        with patch(
            "agents.studio_compositor.director_loop._PERCEPTION_STATE_PATH", state_file
        ), patch("agents.studio_compositor.director_loop.TAU_OWNERSHIP", 0.60):
            _PRESENCE_CACHE.clear()
            result = _ownership_gate_passes(self._make_intent(), "test-cond")

        assert result is True

    def test_fail_when_posterior_below_lower_bound(self, tmp_path: Path) -> None:
        state_file = tmp_path / "perception-state.json"
        state_file.write_text(
            json.dumps({"presence_probability": 0.2, "presence_state": "ABSENT"}),
            encoding="utf-8",
        )
        from agents.studio_compositor.director_loop import (
            _PRESENCE_CACHE,
            _ownership_gate_passes,
        )

        with patch(
            "agents.studio_compositor.director_loop._PERCEPTION_STATE_PATH", state_file
        ), patch("agents.studio_compositor.director_loop.TAU_OWNERSHIP", 0.60):
            _PRESENCE_CACHE.clear()
            result = _ownership_gate_passes(self._make_intent(), "test-cond")

        assert result is False

    def test_uncertain_passes_diagnostic_impingements(self, tmp_path: Path) -> None:
        state_file = tmp_path / "perception-state.json"
        state_file.write_text(
            json.dumps({"presence_probability": 0.5, "presence_state": "UNCERTAIN"}),
            encoding="utf-8",
        )
        from agents.studio_compositor.director_loop import (
            _PRESENCE_CACHE,
            _ownership_gate_passes,
        )

        with patch(
            "agents.studio_compositor.director_loop._PERCEPTION_STATE_PATH", state_file
        ), patch("agents.studio_compositor.director_loop.TAU_OWNERSHIP", 0.60):
            _PRESENCE_CACHE.clear()
            # diagnostic intent families pass in uncertain zone
            intent = self._make_intent(intent_family="diagnostic.heartbeat")
            result = _ownership_gate_passes(intent, "test-cond")

        assert result is True

    def test_uncertain_blocks_non_diagnostic(self, tmp_path: Path) -> None:
        state_file = tmp_path / "perception-state.json"
        state_file.write_text(
            json.dumps({"presence_probability": 0.5, "presence_state": "UNCERTAIN"}),
            encoding="utf-8",
        )
        from agents.studio_compositor.director_loop import (
            _PRESENCE_CACHE,
            _ownership_gate_passes,
        )

        with patch(
            "agents.studio_compositor.director_loop._PERCEPTION_STATE_PATH", state_file
        ), patch("agents.studio_compositor.director_loop.TAU_OWNERSHIP", 0.60):
            _PRESENCE_CACHE.clear()
            intent = self._make_intent(intent_family="camera.hero")
            result = _ownership_gate_passes(intent, "test-cond")

        assert result is False

    def test_bypass_env_var_overrides(self, tmp_path: Path) -> None:
        state_file = tmp_path / "perception-state.json"
        state_file.write_text(
            json.dumps({"presence_probability": 0.1, "presence_state": "ABSENT"}),
            encoding="utf-8",
        )
        from agents.studio_compositor.director_loop import (
            _PRESENCE_CACHE,
            _ownership_gate_passes,
        )

        with (
            patch(
                "agents.studio_compositor.director_loop._PERCEPTION_STATE_PATH",
                state_file,
            ),
            patch("agents.studio_compositor.director_loop.TAU_OWNERSHIP", 0.60),
            patch.dict(os.environ, {"HAPAX_BAYESIAN_BYPASS": "1"}),
        ):
            _PRESENCE_CACHE.clear()
            result = _ownership_gate_passes(self._make_intent(), "test-cond")

        assert result is True

    def test_missing_file_fails_open(self, tmp_path: Path) -> None:
        """Fail-open: missing perception state defaults to allowing emissions."""
        missing = tmp_path / "nonexistent.json"
        from agents.studio_compositor.director_loop import (
            _PRESENCE_CACHE,
            _ownership_gate_passes,
        )

        with patch(
            "agents.studio_compositor.director_loop._PERCEPTION_STATE_PATH", missing
        ), patch("agents.studio_compositor.director_loop.TAU_OWNERSHIP", 0.60):
            _PRESENCE_CACHE.clear()
            # presence_probability=0.0 is below threshold, but missing file
            # means we can't be confident → fail-open
            result = _ownership_gate_passes(self._make_intent(), "test-cond")

        # The gate should fail-open when file is missing/unreadable
        assert result is True
