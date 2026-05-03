"""Tests for ``_engine_says_playing`` — the engine-driven producer-side gate.

cc-task ``album-identifier-playing-flag-periodic-engine-truth``: the
producer side of the metalfingers ghost-claim regression. Verifies the
album-identifier daemon's ``playing`` field is driven by
``VinylSpinningEngine.is_spinning`` (cross-modal Bayesian posterior with
hysteresis), not the legacy IR-zone-only gate alone.

Acceptance criteria covered:

- override flag → playing flips True regardless of IR/audio (hard short-circuit)
- engine fallback to legacy gate when engine import / construction fails
- engine fallback to legacy gate when ``engine.tick()`` raises
- engine ``is_spinning`` is the truth source when no override
- engine instance is a singleton (constructed once across calls)
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def album_identifier(tmp_path, monkeypatch):
    """Load ``scripts/album-identifier.py`` with isolated state-file paths.

    Each test gets a clean module instance with the singleton engine reset
    and the override-flag path pointed at a tmp file we control.
    """
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "album-identifier.py"
    spec = importlib.util.spec_from_file_location("album_identifier_engine_test", module_path)
    if spec is None or spec.loader is None:
        pytest.fail(f"could not load module spec at {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["album_identifier_engine_test"] = mod
    spec.loader.exec_module(mod)

    override_flag = tmp_path / "vinyl-operator-active.flag"
    perception_state = tmp_path / "perception-state.json"

    monkeypatch.setattr(mod, "_VINYL_OVERRIDE_FLAG", override_flag)
    monkeypatch.setattr(mod, "_PERCEPTION_STATE_FILE", perception_state)
    monkeypatch.setattr(mod, "_vinyl_engine", None)
    monkeypatch.setattr(mod, "_vinyl_engine_init_failed", False)

    yield mod

    sys.modules.pop("album_identifier_engine_test", None)


class TestOverrideShortCircuit:
    """Override flag is a hard short-circuit — immediate True."""

    def test_override_flag_present_returns_true_without_engine(self, album_identifier, monkeypatch):
        album_identifier._VINYL_OVERRIDE_FLAG.touch()
        engine_construct = MagicMock(side_effect=AssertionError("must not construct on override"))
        monkeypatch.setattr(
            "agents.hapax_daimonion.vinyl_spinning_engine.VinylSpinningEngine",
            engine_construct,
        )
        assert album_identifier._engine_says_playing() is True
        assert engine_construct.call_count == 0

    def test_override_flag_present_ticks_existing_engine(self, album_identifier):
        engine = MagicMock()
        engine.is_spinning = False
        album_identifier._vinyl_engine = engine

        album_identifier._VINYL_OVERRIDE_FLAG.touch()
        assert album_identifier._engine_says_playing() is True
        engine.tick.assert_called_once()


class TestEngineDrivenTruth:
    """When no override, engine.is_spinning is the truth."""

    def test_engine_asserted_returns_true(self, album_identifier):
        engine = MagicMock()
        engine.is_spinning = True
        album_identifier._vinyl_engine = engine

        assert album_identifier._engine_says_playing() is True
        engine.tick.assert_called_once()

    def test_engine_not_asserted_returns_false(self, album_identifier):
        engine = MagicMock()
        engine.is_spinning = False
        album_identifier._vinyl_engine = engine

        assert album_identifier._engine_says_playing() is False
        engine.tick.assert_called_once()


class TestSingleton:
    """Engine is constructed once across calls."""

    def test_singleton_constructed_lazily_on_first_call(self, album_identifier, monkeypatch):
        construct_count = {"n": 0}

        class FakeEngine:
            def __init__(self):
                construct_count["n"] += 1
                self.is_spinning = False

            def tick(self):
                pass

        monkeypatch.setattr(
            "agents.hapax_daimonion.vinyl_spinning_engine.VinylSpinningEngine",
            FakeEngine,
        )
        for _ in range(5):
            album_identifier._engine_says_playing()
        assert construct_count["n"] == 1


class TestFallbackOnEngineUnavailable:
    """Engine import failure → falls back to legacy gate, logs once."""

    def test_import_failure_falls_back_to_legacy(self, album_identifier, monkeypatch, tmp_path):
        def failing_import(_name):
            raise ImportError("simulated engine module missing")

        original_import = (
            __builtins__["__import__"]
            if isinstance(__builtins__, dict)
            else __builtins__.__import__
        )

        def patched_import(name, *args, **kwargs):
            if name == "agents.hapax_daimonion.vinyl_spinning_engine":
                raise ImportError("simulated")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", patched_import)

        # Make legacy gate return True via override path so we can confirm
        # the fallback path is exercised end-to-end.
        album_identifier._VINYL_OVERRIDE_FLAG.touch()
        # Override short-circuit fires before fallback would matter, so
        # remove the file and instead assert the legacy IR-zone-only gate
        # is the path that runs.
        album_identifier._VINYL_OVERRIDE_FLAG.unlink()
        album_identifier._PERCEPTION_STATE_FILE.write_text('{"ir_hand_zone": "turntable"}')

        result = album_identifier._engine_says_playing()
        assert result is True  # legacy gate said yes via hand-zone
        assert album_identifier._vinyl_engine_init_failed is True
        assert album_identifier._vinyl_engine is None

    def test_engine_tick_failure_falls_back_per_tick(self, album_identifier):
        engine = MagicMock()
        engine.tick.side_effect = RuntimeError("simulated tick failure")
        album_identifier._vinyl_engine = engine
        album_identifier._PERCEPTION_STATE_FILE.write_text('{"ir_hand_activity": "scratching"}')

        # Per-tick failure routes through the legacy gate and returns its
        # answer; engine instance is NOT marked permanently failed (that
        # is reserved for construction-time failure).
        result = album_identifier._engine_says_playing()
        assert result is True  # legacy gate hit on hand_activity=scratching
        assert album_identifier._vinyl_engine is engine  # still installed


class TestPlayingTrajectory:
    """Synthetic IR-state sequence produces the expected playing trajectory."""

    def test_cold_start_no_signals_returns_false(self, album_identifier, monkeypatch):
        from agents.hapax_daimonion.vinyl_spinning_engine import VinylSpinningEngine

        # Engine constructed against tmp paths so fixture files don't bleed.
        engine = VinylSpinningEngine(
            album_state_file=Path("/nonexistent/album-state.json"),
            perception_state_file=Path("/nonexistent/perception-state.json"),
            operator_override_flag=Path("/nonexistent/override.flag"),
        )
        album_identifier._vinyl_engine = engine

        # Cold start — no signals, posterior at prior 0.10. Engine state
        # is RETRACTED (default), is_spinning is False.
        assert album_identifier._engine_says_playing() is False

    def test_override_flips_true_immediately_even_at_engine_cold_start(self, album_identifier):
        from agents.hapax_daimonion.vinyl_spinning_engine import VinylSpinningEngine

        engine = VinylSpinningEngine(
            album_state_file=Path("/nonexistent/album-state.json"),
            perception_state_file=Path("/nonexistent/perception-state.json"),
            operator_override_flag=Path("/nonexistent/override.flag"),
        )
        album_identifier._vinyl_engine = engine

        # Override flag short-circuits the cold-start engine (which would
        # otherwise need k_enter=6 ticks before is_spinning flips True).
        album_identifier._VINYL_OVERRIDE_FLAG.touch()
        assert album_identifier._engine_says_playing() is True
