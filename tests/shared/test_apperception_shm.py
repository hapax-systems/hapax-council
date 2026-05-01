"""Tests for ``shared.apperception_shm``.

The module reads self-band state from ``/dev/shm`` and formats it for
LLM prompt injection. It must degrade silently to an empty string on
any read / parse failure (no exceptions propagate to the prompt-build
path) and must skip stale data older than 30 seconds.

These tests pin those contracts deterministically by writing fixtures
to a tmp_path and overriding the ``path`` argument so the live
``/dev/shm`` location is never touched.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

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


# ── Module surface ───────────────────────────────────────────────────


class TestModuleSurface:
    def test_canonical_path_under_dev_shm(self) -> None:
        # Don't accidentally relocate the canonical write site.
        assert Path("/dev/shm/hapax-apperception/self-band.json") == APPERCEPTION_SHM_PATH

    def test_staleness_threshold_30s(self) -> None:
        # Pin the threshold; any change is a behavior change worth a
        # test failure.
        assert _STALENESS_THRESHOLD == 30


# ── Failure paths return empty string ────────────────────────────────


class TestFailurePaths:
    def test_missing_path_returns_empty(self, tmp_path: Path) -> None:
        result = read_apperception_block(tmp_path / "nonexistent.json")
        assert result == ""

    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        target.write_text("{not valid json", encoding="utf-8")
        assert read_apperception_block(target) == ""

    def test_empty_dict_returns_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        _write_state(target, {})
        assert read_apperception_block(target) == ""

    def test_stale_data_returns_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now() - 60,  # 60s old, > 30s threshold
                "self_model": {"dimensions": {"x": {"confidence": 0.7}}},
            },
        )
        assert read_apperception_block(target) == ""

    def test_no_dimensions_or_observations_returns_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    # Both empty — the module treats this as "nothing
                    # interesting to inject".
                    "dimensions": {},
                    "recent_observations": [],
                },
            },
        )
        assert read_apperception_block(target) == ""


# ── Successful render paths ──────────────────────────────────────────


class TestSuccessfulRender:
    def test_dimensions_block_renders(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "dimensions": {
                        "alpha": {
                            "confidence": 0.85,
                            "affirming_count": 4,
                            "problematizing_count": 1,
                        },
                    },
                    "recent_observations": [],
                },
            },
        )
        result = read_apperception_block(target)
        assert "Self-dimensions:" in result
        assert "alpha" in result
        assert "0.85" in result
        assert "+4" in result
        assert "-1" in result

    def test_dimensions_sorted_alphabetically(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "dimensions": {
                        "zeta": {"confidence": 0.5},
                        "alpha": {"confidence": 0.9},
                        "mu": {"confidence": 0.7},
                    },
                    "recent_observations": [],
                },
            },
        )
        result = read_apperception_block(target)
        # Each name must appear, with alpha before mu before zeta.
        a_idx = result.index("alpha")
        m_idx = result.index("mu")
        z_idx = result.index("zeta")
        assert a_idx < m_idx < z_idx

    def test_low_coherence_emits_warning(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "coherence": 0.2,
                    "dimensions": {"x": {"confidence": 0.6}},
                    "recent_observations": [],
                },
            },
        )
        result = read_apperception_block(target)
        # Two-byte unicode warning sigil + the coherence value.
        assert "Self-coherence low" in result
        assert "0.20" in result

    def test_high_coherence_no_warning(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "coherence": 0.85,
                    "dimensions": {"x": {"confidence": 0.6}},
                    "recent_observations": [],
                },
            },
        )
        result = read_apperception_block(target)
        assert "Self-coherence low" not in result

    def test_observations_truncated_to_last_five(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "dimensions": {},
                    "recent_observations": [f"obs-{i}" for i in range(10)],
                },
            },
        )
        result = read_apperception_block(target)
        # Only the last 5 should render.
        for i in range(5, 10):
            assert f"obs-{i}" in result
        for i in range(0, 5):
            assert f"obs-{i}" not in result

    def test_reflections_truncated_to_last_three(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "dimensions": {},
                    "recent_observations": ["seed"],  # ensures non-empty render
                    "recent_reflections": [f"ref-{i}" for i in range(8)],
                },
            },
        )
        result = read_apperception_block(target)
        for i in range(5, 8):
            assert f"ref-{i}" in result
        for i in range(0, 5):
            assert f"ref-{i}" not in result

    def test_pending_actions_truncated_to_three(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "dimensions": {},
                    "recent_observations": ["seed"],
                },
                "pending_actions": [f"act-{i}" for i in range(6)],
            },
        )
        result = read_apperception_block(target)
        # First 3 only.
        for i in range(0, 3):
            assert f"act-{i}" in result
        for i in range(3, 6):
            assert f"act-{i}" not in result

    def test_no_timestamp_field_treated_as_fresh(self, tmp_path: Path) -> None:
        # Defensive: when ``timestamp`` is missing/zero the module
        # falls through (does NOT treat as stale; staleness only kicks
        # in when ts > 0). This avoids dropping the very first read
        # before the writer has a chance to set ts.
        target = tmp_path / "self-band.json"
        _write_state(
            target,
            {
                "self_model": {
                    "dimensions": {"alpha": {"confidence": 0.7}},
                    "recent_observations": [],
                },
            },
        )
        result = read_apperception_block(target)
        assert "alpha" in result


# ── Format invariants ─────────────────────────────────────────────────


class TestFormat:
    def test_starts_with_self_awareness_header(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "dimensions": {"x": {"confidence": 0.6}},
                    "recent_observations": [],
                },
            },
        )
        result = read_apperception_block(target)
        assert result.startswith("Self-awareness")

    def test_returns_str_type(self, tmp_path: Path) -> None:
        target = tmp_path / "self-band.json"
        _write_state(
            target,
            {
                "timestamp": _fresh_now(),
                "self_model": {
                    "dimensions": {"x": {"confidence": 0.6}},
                    "recent_observations": [],
                },
            },
        )
        assert isinstance(read_apperception_block(target), str)
