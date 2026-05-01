"""Tests for shared.chronicle_sampler.assemble_snapshot.

182-LOC periodic state sampler. The assemble_snapshot helper +
private _read_* functions are pure-IO (no asyncio); the long-lived
coroutine path is left to integration tests.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.chronicle_sampler import assemble_snapshot

# ── assemble_snapshot ──────────────────────────────────────────────


class TestAssembleSnapshotShape:
    def test_returns_three_top_level_keys(self, tmp_path: Path) -> None:
        result = assemble_snapshot(
            stimmung_path=tmp_path / "missing.json",
            eigenform_path=tmp_path / "missing.jsonl",
            signal_bus_snapshot=None,
        )
        assert set(result.keys()) == {"stimmung", "eigenform", "signals"}

    def test_missing_files_yield_empty_dicts(self, tmp_path: Path) -> None:
        result = assemble_snapshot(
            stimmung_path=tmp_path / "no.json",
            eigenform_path=tmp_path / "no.jsonl",
        )
        assert result == {"stimmung": {}, "eigenform": {}, "signals": {}}

    def test_signal_bus_snapshot_passed_through(self, tmp_path: Path) -> None:
        signals = {"a": 0.4, "b": 0.7}
        result = assemble_snapshot(
            stimmung_path=tmp_path / "no.json",
            eigenform_path=tmp_path / "no.jsonl",
            signal_bus_snapshot=signals,
        )
        assert result["signals"] == signals


# ── stimmung reader ────────────────────────────────────────────────


class TestStimmungReader:
    def test_overall_stance_field_used(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        path.write_text(json.dumps({"overall_stance": "cautious"}))
        result = assemble_snapshot(
            stimmung_path=path, eigenform_path=tmp_path / "no.jsonl"
        )
        assert result["stimmung"]["stance"] == "cautious"

    def test_stance_field_fallback(self, tmp_path: Path) -> None:
        """When overall_stance is absent but `stance` is set, that's used."""
        path = tmp_path / "s.json"
        path.write_text(json.dumps({"stance": "degraded"}))
        result = assemble_snapshot(
            stimmung_path=path, eigenform_path=tmp_path / "no.jsonl"
        )
        assert result["stimmung"]["stance"] == "degraded"

    def test_nested_dimensions_passed_through(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        path.write_text(
            json.dumps(
                {"dimensions": {"health": {"value": 0.9}, "operator_energy": 0.5}}
            )
        )
        result = assemble_snapshot(
            stimmung_path=path, eigenform_path=tmp_path / "no.jsonl"
        )
        assert result["stimmung"]["dimensions"]["health"] == {"value": 0.9}
        assert result["stimmung"]["dimensions"]["operator_energy"] == 0.5

    def test_top_level_dim_dict_value_extracted(self, tmp_path: Path) -> None:
        """Top-level dimension as {value: X, ...} dict → just the value
        is kept under dimensions."""
        path = tmp_path / "s.json"
        path.write_text(
            json.dumps({"health": {"value": 0.85, "trend": "rising"}})
        )
        result = assemble_snapshot(
            stimmung_path=path, eigenform_path=tmp_path / "no.jsonl"
        )
        assert result["stimmung"]["dimensions"]["health"] == 0.85

    def test_top_level_dim_scalar_passed(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        path.write_text(json.dumps({"resource_pressure": 0.4}))
        result = assemble_snapshot(
            stimmung_path=path, eigenform_path=tmp_path / "no.jsonl"
        )
        assert result["stimmung"]["dimensions"]["resource_pressure"] == 0.4

    def test_invalid_json_returns_empty_dict(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        path.write_text("{ invalid")
        result = assemble_snapshot(
            stimmung_path=path, eigenform_path=tmp_path / "no.jsonl"
        )
        assert result["stimmung"] == {}

    def test_unknown_top_level_keys_ignored(self, tmp_path: Path) -> None:
        """Top-level keys not in the canonical _DIMENSION_NAMES set are
        not picked up under dimensions."""
        path = tmp_path / "s.json"
        path.write_text(json.dumps({"unrelated_field": 0.99}))
        result = assemble_snapshot(
            stimmung_path=path, eigenform_path=tmp_path / "no.jsonl"
        )
        assert "dimensions" not in result["stimmung"]


# ── eigenform reader ──────────────────────────────────────────────


class TestEigenformReader:
    def test_returns_last_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        path.write_text(
            json.dumps({"t": 1.0, "v": "a"})
            + "\n"
            + json.dumps({"t": 2.0, "v": "b"})
            + "\n"
            + json.dumps({"t": 3.0, "v": "c"})
            + "\n"
        )
        result = assemble_snapshot(
            stimmung_path=tmp_path / "no.json", eigenform_path=path
        )
        assert result["eigenform"] == {"t": 3.0, "v": "c"}

    def test_skips_blank_trailing_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        path.write_text(json.dumps({"t": 1.0}) + "\n\n   \n")
        result = assemble_snapshot(
            stimmung_path=tmp_path / "no.json", eigenform_path=path
        )
        assert result["eigenform"] == {"t": 1.0}

    def test_invalid_last_line_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        path.write_text(json.dumps({"t": 1.0}) + "\n{ broken json\n")
        result = assemble_snapshot(
            stimmung_path=tmp_path / "no.json", eigenform_path=path
        )
        assert result["eigenform"] == {}

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        path.write_text("")
        result = assemble_snapshot(
            stimmung_path=tmp_path / "no.json", eigenform_path=path
        )
        assert result["eigenform"] == {}
