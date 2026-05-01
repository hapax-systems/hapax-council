"""Tests for ``shared.apperception_shm`` prompt-block rendering."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from shared.apperception_shm import (
    _STALENESS_THRESHOLD,
    APPERCEPTION_SHM_PATH,
    read_apperception_block,
)


def _write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fresh_now() -> float:
    return time.time()


class TestModuleSurface:
    def test_canonical_path_under_dev_shm(self) -> None:
        assert Path("/dev/shm/hapax-apperception/self-band.json") == APPERCEPTION_SHM_PATH

    def test_staleness_threshold_30s(self) -> None:
        assert _STALENESS_THRESHOLD == 30


class TestEmptyAndMalformedInput:
    def test_missing_path_returns_empty(self, tmp_path: Path) -> None:
        assert read_apperception_block(tmp_path / "missing.json") == ""

    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "bad.json"
        target.write_text("{not valid json", encoding="utf-8")
        assert read_apperception_block(target) == ""

    def test_empty_dict_returns_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "empty.json"
        _write_state(target, {})
        assert read_apperception_block(target) == ""

    def test_empty_self_model_returns_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "empty-self-model.json"
        _write_state(target, {"timestamp": _fresh_now(), "self_model": {}})
        assert read_apperception_block(target) == ""

    def test_reflections_without_dimensions_or_observations_return_empty(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "reflections-only.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {"recent_reflections": ["reflection"]},
                "pending_actions": ["action"],
            },
        )
        assert read_apperception_block(target) == ""

    def test_no_dimensions_or_observations_returns_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "empty-content.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {"dimensions": {}, "recent_observations": []},
            },
        )
        assert read_apperception_block(target) == ""


class TestStaleness:
    def test_fresh_data_returned(self, tmp_path: Path) -> None:
        target = tmp_path / "fresh.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {"dimensions": {"focus": {"confidence": 0.8}}},
            },
        )
        block = read_apperception_block(target)
        assert "Self-dimensions" in block
        assert "focus" in block

    def test_stale_data_returns_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "stale.json"
        with patch("shared.apperception_shm.time") as mock_time:
            mock_time.time.return_value = 10_000.0
            _write_state(
                target,
                {
                    "timestamp": 9_900.0,
                    "self_model": {"dimensions": {"focus": {"confidence": 0.8}}},
                },
            )
            assert read_apperception_block(target) == ""

    def test_no_timestamp_field_treated_as_fresh(self, tmp_path: Path) -> None:
        target = tmp_path / "no-timestamp.json"
        _write_state(
            target,
            {"self_model": {"dimensions": {"alpha": {"confidence": 0.7}}}},
        )
        assert "alpha" in read_apperception_block(target)


class TestSectionRendering:
    def test_dimensions_render_with_counts(self, tmp_path: Path) -> None:
        target = tmp_path / "dimensions.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
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
        block = read_apperception_block(target)
        assert "focus" in block
        assert "confidence=0.92" in block
        assert "(+7/-2)" in block

    def test_dimensions_sorted_alphabetically(self, tmp_path: Path) -> None:
        target = tmp_path / "sorted-dimensions.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "dimensions": {
                        "zeta": {"confidence": 0.5},
                        "alpha": {"confidence": 0.9},
                        "mu": {"confidence": 0.7},
                    }
                },
            },
        )
        block = read_apperception_block(target)
        assert block.index("alpha") < block.index("mu") < block.index("zeta")

    def test_observations_render(self, tmp_path: Path) -> None:
        target = tmp_path / "observations.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "dimensions": {"focus": {"confidence": 0.5}},
                    "recent_observations": ["obs-1", "obs-2", "obs-3"],
                },
            },
        )
        block = read_apperception_block(target)
        assert "Recent self-observations" in block
        for observation in ["obs-1", "obs-2", "obs-3"]:
            assert observation in block

    def test_observations_truncated_to_last_five(self, tmp_path: Path) -> None:
        target = tmp_path / "many-observations.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "dimensions": {"focus": {"confidence": 0.5}},
                    "recent_observations": [f"obs-{i}" for i in range(10)],
                },
            },
        )
        block = read_apperception_block(target)
        for i in range(5):
            assert f"obs-{i}" not in block
        for i in range(5, 10):
            assert f"obs-{i}" in block

    def test_low_coherence_emits_warning(self, tmp_path: Path) -> None:
        target = tmp_path / "low-coherence.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "coherence": 0.25,
                    "dimensions": {"focus": {"confidence": 0.5}},
                },
            },
        )
        block = read_apperception_block(target)
        assert "Self-coherence low" in block
        assert "0.25" in block

    def test_high_coherence_no_warning(self, tmp_path: Path) -> None:
        target = tmp_path / "high-coherence.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "coherence": 0.85,
                    "dimensions": {"focus": {"confidence": 0.5}},
                },
            },
        )
        assert "Self-coherence low" not in read_apperception_block(target)

    def test_reflections_truncated_to_last_three(self, tmp_path: Path) -> None:
        target = tmp_path / "reflections.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "dimensions": {"focus": {"confidence": 0.5}},
                    "recent_reflections": [f"ref-{i}" for i in range(8)],
                },
            },
        )
        block = read_apperception_block(target)
        assert "ref-4" not in block
        for i in range(5, 8):
            assert f"ref-{i}" in block

    def test_pending_actions_truncated_to_three(self, tmp_path: Path) -> None:
        target = tmp_path / "actions.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {"dimensions": {"focus": {"confidence": 0.5}}},
                "pending_actions": [f"act-{i}" for i in range(8)],
            },
        )
        block = read_apperception_block(target)
        assert "act-0" in block
        assert "act-2" in block
        assert "act-3" not in block


class TestFormat:
    def test_starts_with_self_awareness_header(self, tmp_path: Path) -> None:
        target = tmp_path / "header.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {"dimensions": {"focus": {"confidence": 0.6}}},
            },
        )
        assert read_apperception_block(target).startswith("Self-awareness")

    def test_returns_str_type(self, tmp_path: Path) -> None:
        target = tmp_path / "type.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {"dimensions": {"focus": {"confidence": 0.6}}},
            },
        )
        assert isinstance(read_apperception_block(target), str)
