"""Tests for stimmung-modulated reactive engine processing (WS2).

Tests the modulation logic without importing the full ReactiveEngine
(which has deep import chains involving watchdog + governance).
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.stimmung import Stance

# ── Test the modulation logic directly ───────────────────────────────────────

# Replicate the core modulation logic from ReactiveEngine._handle_change
# to test it in isolation without the circular import chain.


def _filter_actions_by_stimmung(actions: list[dict], stance: str) -> list[dict]:
    """Replicate the engine's stimmung modulation logic for testing.

    When degraded/critical, keep only phase 0 (deterministic) actions.
    """
    if stance in (Stance.DEGRADED, Stance.CRITICAL):
        return [a for a in actions if a["phase"] == 0]
    return actions


def _read_stimmung_stance(path: Path) -> str:
    """Read stimmung stance from file. Returns 'nominal' on error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("overall_stance", "nominal")
    except (OSError, json.JSONDecodeError):
        return "nominal"


class TestStimmungModulation:
    def test_nominal_keeps_all_phases(self):
        actions = [
            {"name": "cache-refresh", "phase": 0},
            {"name": "rag-ingest", "phase": 1},
            {"name": "knowledge-maint", "phase": 2},
        ]
        result = _filter_actions_by_stimmung(actions, "nominal")
        assert len(result) == 3

    def test_cautious_keeps_all_phases(self):
        actions = [
            {"name": "cache-refresh", "phase": 0},
            {"name": "rag-ingest", "phase": 1},
        ]
        result = _filter_actions_by_stimmung(actions, "cautious")
        assert len(result) == 2

    def test_degraded_keeps_only_phase_0(self):
        actions = [
            {"name": "cache-refresh", "phase": 0},
            {"name": "rag-ingest", "phase": 1},
            {"name": "knowledge-maint", "phase": 2},
        ]
        result = _filter_actions_by_stimmung(actions, "degraded")
        assert len(result) == 1
        assert result[0]["name"] == "cache-refresh"

    def test_critical_keeps_only_phase_0(self):
        actions = [
            {"name": "cache-refresh", "phase": 0},
            {"name": "rag-ingest", "phase": 1},
            {"name": "knowledge-maint", "phase": 2},
        ]
        result = _filter_actions_by_stimmung(actions, "critical")
        assert len(result) == 1
        assert result[0]["phase"] == 0

    def test_degraded_all_phase_0_keeps_all(self):
        actions = [
            {"name": "cache-refresh", "phase": 0},
            {"name": "config-changed", "phase": 0},
        ]
        result = _filter_actions_by_stimmung(actions, "degraded")
        assert len(result) == 2

    def test_degraded_no_phase_0_returns_empty(self):
        actions = [
            {"name": "rag-ingest", "phase": 1},
            {"name": "knowledge-maint", "phase": 2},
        ]
        result = _filter_actions_by_stimmung(actions, "degraded")
        assert len(result) == 0

    def test_stance_enum_values_match(self):
        """Ensure Stance enum values match the strings used in engine code."""
        assert Stance.NOMINAL == "nominal"
        assert Stance.CAUTIOUS == "cautious"
        assert Stance.DEGRADED == "degraded"
        assert Stance.CRITICAL == "critical"


class TestReadStimmungStance:
    def test_reads_from_file(self, tmp_path: Path):
        f = tmp_path / "state.json"
        f.write_text(json.dumps({"overall_stance": "degraded"}))
        assert _read_stimmung_stance(f) == "degraded"

    def test_missing_file_returns_nominal(self, tmp_path: Path):
        assert _read_stimmung_stance(tmp_path / "nonexistent.json") == "nominal"

    def test_corrupt_json_returns_nominal(self, tmp_path: Path):
        f = tmp_path / "state.json"
        f.write_text("not json{")
        assert _read_stimmung_stance(f) == "nominal"

    def test_missing_field_returns_nominal(self, tmp_path: Path):
        f = tmp_path / "state.json"
        f.write_text(json.dumps({"timestamp": 123}))
        assert _read_stimmung_stance(f) == "nominal"


class TestEngineCodeIntegrity:
    """Verify the engine code contains the stimmung modulation we added."""

    def test_engine_module_has_stimmung_import(self):
        """Verify the engine imports Stance from stimmung."""

        source = Path(__file__).parent.parent / "logos" / "engine" / "__init__.py"
        text = source.read_text()
        assert "from logos._stimmung import Stance" in text

    def test_engine_has_read_stimmung_method(self):
        source = Path(__file__).parent.parent / "logos" / "engine" / "__init__.py"
        text = source.read_text()
        assert "_read_stimmung_stance" in text

    def test_engine_handle_change_checks_stance(self):
        source = Path(__file__).parent.parent / "logos" / "engine" / "__init__.py"
        text = source.read_text()
        assert "Stance.DEGRADED" in text
        assert "Stance.CRITICAL" in text
        assert "a.phase == 0" in text
