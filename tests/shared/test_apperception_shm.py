"""Tests for shared.apperception_shm.read_apperception_block.

Pure-stdlib reader for /dev/shm/hapax-apperception/self-band.json
that formats apperception state into a text block for LLM prompt
injection. Untested before this commit.

The function takes a ``path`` parameter for test injection so we
never touch the real /dev/shm state.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from shared.apperception_shm import read_apperception_block


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


# ── Empty / missing / malformed input ──────────────────────────────


class TestEmptyAndMissing:
    def test_missing_file_returns_empty_string(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.json"
        assert read_apperception_block(path=path) == ""

    def test_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{ not valid json")
        assert read_apperception_block(path=path) == ""

    def test_empty_self_model_returns_empty(self, tmp_path: Path) -> None:
        """self_model with no dimensions and no observations → no block."""
        path = tmp_path / "empty.json"
        _write(path, {"timestamp": time.time(), "self_model": {}})
        assert read_apperception_block(path=path) == ""

    def test_only_reflections_no_dimensions_returns_empty(self, tmp_path: Path) -> None:
        """Reflections + pending_actions alone (no dims, no observations)
        do not satisfy the early-return guard."""
        path = tmp_path / "reflections.json"
        _write(
            path,
            {
                "timestamp": time.time(),
                "self_model": {"recent_reflections": ["x"]},
                "pending_actions": ["a"],
            },
        )
        assert read_apperception_block(path=path) == ""


# ── Staleness gate ─────────────────────────────────────────────────


class TestStaleness:
    def test_fresh_data_returned(self, tmp_path: Path) -> None:
        path = tmp_path / "fresh.json"
        _write(
            path,
            {
                "timestamp": time.time(),
                "self_model": {"dimensions": {"focus": {"confidence": 0.8}}},
            },
        )
        block = read_apperception_block(path=path)
        assert "Self-dimensions" in block
        assert "focus" in block

    def test_stale_data_returns_empty(self, tmp_path: Path) -> None:
        """Data older than 30s is filtered out."""
        path = tmp_path / "stale.json"
        with patch("shared.apperception_shm.time") as mock_time:
            mock_time.time.return_value = 10_000.0
            _write(
                path,
                {
                    "timestamp": 9_900.0,  # 100s old
                    "self_model": {"dimensions": {"focus": {"confidence": 0.8}}},
                },
            )
            assert read_apperception_block(path=path) == ""

    def test_no_timestamp_treated_as_fresh(self, tmp_path: Path) -> None:
        """timestamp == 0 (default in raw.get) bypasses the staleness gate
        per the `if ts > 0` guard — payload is rendered."""
        path = tmp_path / "no-ts.json"
        _write(
            path,
            {"self_model": {"dimensions": {"focus": {"confidence": 0.8}}}},
        )
        block = read_apperception_block(path=path)
        assert "focus" in block


# ── Section rendering ──────────────────────────────────────────────


class TestSectionRendering:
    def test_dimensions_render_with_counts(self, tmp_path: Path) -> None:
        path = tmp_path / "dims.json"
        _write(
            path,
            {
                "timestamp": time.time(),
                "self_model": {
                    "dimensions": {
                        "focus": {
                            "confidence": 0.92,
                            "affirming_count": 7,
                            "problematizing_count": 2,
                        }
                    }
                },
            },
        )
        block = read_apperception_block(path=path)
        assert "focus" in block
        assert "confidence=0.92" in block
        assert "(+7/-2)" in block

    def test_observations_render(self, tmp_path: Path) -> None:
        path = tmp_path / "obs.json"
        _write(
            path,
            {
                "timestamp": time.time(),
                "self_model": {
                    "dimensions": {"focus": {"confidence": 0.5}},
                    "recent_observations": ["obs-1", "obs-2", "obs-3"],
                },
            },
        )
        block = read_apperception_block(path=path)
        assert "Recent self-observations" in block
        for obs in ["obs-1", "obs-2", "obs-3"]:
            assert obs in block

    def test_observations_capped_at_last_five(self, tmp_path: Path) -> None:
        """Only the most-recent 5 observations are rendered."""
        path = tmp_path / "many.json"
        _write(
            path,
            {
                "timestamp": time.time(),
                "self_model": {
                    "dimensions": {"focus": {"confidence": 0.5}},
                    "recent_observations": [f"obs-{i}" for i in range(10)],
                },
            },
        )
        block = read_apperception_block(path=path)
        # First 5 should be dropped, last 5 kept
        assert "obs-0" not in block
        assert "obs-4" not in block
        assert "obs-5" in block
        assert "obs-9" in block

    def test_low_coherence_warning(self, tmp_path: Path) -> None:
        """Coherence < 0.4 surfaces a warning line."""
        path = tmp_path / "lowcoh.json"
        _write(
            path,
            {
                "timestamp": time.time(),
                "self_model": {
                    "dimensions": {"focus": {"confidence": 0.5}},
                    "coherence": 0.25,
                },
            },
        )
        block = read_apperception_block(path=path)
        assert "Self-coherence low" in block
        assert "0.25" in block

    def test_high_coherence_no_warning(self, tmp_path: Path) -> None:
        """Coherence >= 0.4 → no warning line."""
        path = tmp_path / "highcoh.json"
        _write(
            path,
            {
                "timestamp": time.time(),
                "self_model": {
                    "dimensions": {"focus": {"confidence": 0.5}},
                    "coherence": 0.85,
                },
            },
        )
        block = read_apperception_block(path=path)
        assert "Self-coherence low" not in block

    def test_pending_actions_capped_at_three(self, tmp_path: Path) -> None:
        path = tmp_path / "actions.json"
        _write(
            path,
            {
                "timestamp": time.time(),
                "self_model": {"dimensions": {"focus": {"confidence": 0.5}}},
                "pending_actions": [f"act-{i}" for i in range(8)],
            },
        )
        block = read_apperception_block(path=path)
        assert "act-0" in block
        assert "act-2" in block
        assert "act-3" not in block

    def test_reflections_capped_at_three(self, tmp_path: Path) -> None:
        path = tmp_path / "ref.json"
        _write(
            path,
            {
                "timestamp": time.time(),
                "self_model": {
                    "dimensions": {"focus": {"confidence": 0.5}},
                    "recent_reflections": [f"ref-{i}" for i in range(8)],
                },
            },
        )
        block = read_apperception_block(path=path)
        # Last 3 kept (index 5, 6, 7)
        assert "ref-5" in block
        assert "ref-6" in block
        assert "ref-7" in block
        assert "ref-4" not in block
