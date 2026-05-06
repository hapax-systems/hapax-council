"""Tests for shared.mesh_health.aggregate_mesh_health.

52-LOC mesh-wide health aggregator that scans
/dev/shm/hapax-*/health.json files and computes E_mesh (mean control
error). Untested before this commit.

Tests use the ``shm_root=`` parameter so the real /dev/shm is never
read or written.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from shared.mesh_health import aggregate_mesh_health


def _write_component_health(
    shm_root: Path,
    component: str,
    error: float,
    *,
    timestamp: float | None = None,
) -> None:
    """Mint a health file at shm_root/hapax-<component>/health.json."""
    target = shm_root / f"hapax-{component}" / "health.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "component": component,
                "reference": 0.0,
                "perception": error,
                "error": error,
                "timestamp": timestamp if timestamp is not None else time.time(),
            }
        )
    )


# ── Empty mesh ─────────────────────────────────────────────────────


class TestEmptyMesh:
    def test_no_components_returns_sentinel(self, tmp_path: Path) -> None:
        result = aggregate_mesh_health(shm_root=tmp_path)
        assert result == {
            "e_mesh": 1.0,
            "component_count": 0,
            "worst_component": "none",
            "components": {},
        }


# ── Single + multi-component aggregation ──────────────────────────


class TestAggregation:
    def test_single_component(self, tmp_path: Path) -> None:
        _write_component_health(tmp_path, "ir", 0.4)
        result = aggregate_mesh_health(shm_root=tmp_path)
        assert result["component_count"] == 1
        assert result["e_mesh"] == 0.4
        assert result["worst_component"] == "ir"
        assert result["components"] == {"ir": 0.4}

    def test_mean_across_components(self, tmp_path: Path) -> None:
        _write_component_health(tmp_path, "ir", 0.3)
        _write_component_health(tmp_path, "voice", 0.5)
        _write_component_health(tmp_path, "vla", 0.1)
        result = aggregate_mesh_health(shm_root=tmp_path)
        assert result["component_count"] == 3
        assert abs(result["e_mesh"] - 0.3) < 1e-9
        assert result["worst_component"] == "voice"

    def test_components_dict_includes_all_fresh(self, tmp_path: Path) -> None:
        _write_component_health(tmp_path, "a", 0.1)
        _write_component_health(tmp_path, "b", 0.9)
        result = aggregate_mesh_health(shm_root=tmp_path)
        assert result["components"] == {"a": 0.1, "b": 0.9}


# ── Staleness ──────────────────────────────────────────────────────


class TestStaleness:
    def test_stale_components_excluded(self, tmp_path: Path) -> None:
        """Components older than stale_s seconds are dropped from the
        aggregation."""
        _write_component_health(tmp_path, "fresh", 0.2)
        _write_component_health(tmp_path, "stale", 0.8, timestamp=time.time() - 1000)
        result = aggregate_mesh_health(shm_root=tmp_path, stale_s=120.0)
        assert result["component_count"] == 1
        assert "fresh" in result["components"]
        assert "stale" not in result["components"]

    def test_all_stale_returns_empty_sentinel(self, tmp_path: Path) -> None:
        _write_component_health(tmp_path, "x", 0.5, timestamp=time.time() - 1000)
        _write_component_health(tmp_path, "y", 0.6, timestamp=time.time() - 1000)
        result = aggregate_mesh_health(shm_root=tmp_path, stale_s=120.0)
        assert result["component_count"] == 0
        assert result["worst_component"] == "none"


# ── Malformed input ────────────────────────────────────────────────


class TestMalformed:
    def test_invalid_json_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "hapax-bad").mkdir()
        (tmp_path / "hapax-bad" / "health.json").write_text("{ invalid json")
        _write_component_health(tmp_path, "good", 0.2)
        result = aggregate_mesh_health(shm_root=tmp_path)
        assert result["component_count"] == 1
        assert "good" in result["components"]

    def test_missing_required_keys_skipped(self, tmp_path: Path) -> None:
        """Files missing 'component' or 'error' keys are silently skipped
        (the KeyError is in the except)."""
        (tmp_path / "hapax-incomplete").mkdir()
        (tmp_path / "hapax-incomplete" / "health.json").write_text(
            json.dumps({"timestamp": time.time()})
        )
        _write_component_health(tmp_path, "good", 0.5)
        result = aggregate_mesh_health(shm_root=tmp_path)
        assert result["component_count"] == 1


# ── Custom thresholds ──────────────────────────────────────────────


class TestCustomThresholds:
    def test_short_stale_window(self, tmp_path: Path) -> None:
        """A 5-second stale window drops anything older than 5s."""
        _write_component_health(tmp_path, "x", 0.5, timestamp=time.time() - 6.0)
        _write_component_health(tmp_path, "y", 0.4, timestamp=time.time() - 1.0)
        result = aggregate_mesh_health(shm_root=tmp_path, stale_s=5.0)
        assert result["component_count"] == 1
        assert "y" in result["components"]


class TestMalformedFieldsDoNotCrashAggregator:
    """Regression — string timestamps + non-numeric error fields used to
    crash the entire aggregator with TypeError, blocking the
    `agents.health_monitor` snapshot path. Per never-remove: malformed
    files are skipped, healthy ones still report.
    """

    def test_string_timestamp_skipped_does_not_crash(self, tmp_path: Path) -> None:
        target = tmp_path / "hapax-bad" / "health.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"component": "bad", "error": 0.5, "timestamp": "2026-05-06T20:00:00Z"})
        )
        _write_component_health(tmp_path, "ok", 0.3)
        result = aggregate_mesh_health(shm_root=tmp_path)
        assert "bad" not in result["components"]
        assert "ok" in result["components"]

    def test_non_numeric_error_skipped_does_not_crash(self, tmp_path: Path) -> None:
        target = tmp_path / "hapax-bad" / "health.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"component": "bad", "error": "n/a", "timestamp": time.time()})
        )
        _write_component_health(tmp_path, "ok", 0.3)
        result = aggregate_mesh_health(shm_root=tmp_path)
        assert "bad" not in result["components"]
        assert "ok" in result["components"]

    def test_string_numeric_timestamp_coerces_cleanly(self, tmp_path: Path) -> None:
        target = tmp_path / "hapax-stringts" / "health.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"component": "stringts", "error": 0.4, "timestamp": str(time.time())})
        )
        result = aggregate_mesh_health(shm_root=tmp_path)
        assert "stringts" in result["components"]
        assert result["components"]["stringts"] == pytest.approx(0.4)
