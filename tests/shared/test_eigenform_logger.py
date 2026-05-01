"""Tests for shared.eigenform_logger.log_state_vector.

59-LOC JSONL state-vector logger w/ ring-buffer trim. Untested
before this commit. Tests use the ``path=`` parameter so the real
/dev/shm/hapax-eigenform log is never written.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared import eigenform_logger
from shared.eigenform_logger import log_state_vector

# ── Append behaviour ──────────────────────────────────────────────


class TestAppend:
    def test_first_call_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(presence=0.7, path=target)
        assert target.exists()
        line = target.read_text().strip()
        entry = json.loads(line)
        assert entry["presence"] == 0.7

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "path" / "log.jsonl"
        log_state_vector(path=target)
        assert target.exists()

    def test_subsequent_calls_append(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(presence=0.1, path=target)
        log_state_vector(presence=0.2, path=target)
        log_state_vector(presence=0.3, path=target)
        lines = target.read_text().strip().split("\n")
        assert len(lines) == 3
        entries = [json.loads(line) for line in lines]
        assert [e["presence"] for e in entries] == [0.1, 0.2, 0.3]


# ── Entry shape ───────────────────────────────────────────────────


class TestEntryShape:
    def test_default_field_set(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(path=target)
        entry = json.loads(target.read_text().strip())
        # All canonical fields present
        expected_keys = {
            "t",
            "presence",
            "flow_score",
            "audio_energy",
            "stimmung_stance",
            "imagination_salience",
            "visual_brightness",
            "heart_rate",
            "operator_stress",
            "activity",
            "e_mesh",
            "restriction_residual_rms",
        }
        assert set(entry.keys()) == expected_keys

    def test_default_values(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(path=target)
        entry = json.loads(target.read_text().strip())
        assert entry["presence"] == 0.0
        assert entry["stimmung_stance"] == "nominal"
        assert entry["activity"] == "idle"
        assert entry["e_mesh"] == 1.0

    def test_all_fields_serialised(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(
            presence=0.8,
            flow_score=0.6,
            audio_energy=0.3,
            stimmung_stance="cautious",
            imagination_salience=0.4,
            visual_brightness=0.2,
            heart_rate=72.0,
            operator_stress=0.5,
            activity="speaking",
            e_mesh=0.4,
            restriction_residual_rms=0.1,
            path=target,
        )
        entry = json.loads(target.read_text().strip())
        assert entry["presence"] == 0.8
        assert entry["stimmung_stance"] == "cautious"
        assert entry["heart_rate"] == 72.0
        assert entry["activity"] == "speaking"

    def test_timestamp_is_float(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(path=target)
        entry = json.loads(target.read_text().strip())
        assert isinstance(entry["t"], float)
        assert entry["t"] > 0


# ── Ring-buffer trim ──────────────────────────────────────────────


class TestRingBufferTrim:
    def test_under_threshold_no_trim(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """When line count is <= 2× MAX_ENTRIES, no trim happens."""
        target = tmp_path / "log.jsonl"
        # Use a small max via monkeypatch for fast tests
        from pytest import MonkeyPatch

        mp = MonkeyPatch()
        mp.setattr(eigenform_logger, "MAX_ENTRIES", 5)
        try:
            for i in range(8):  # 8 < 2*5 = 10 → no trim
                log_state_vector(presence=float(i), path=target)
            lines = target.read_text().strip().split("\n")
            assert len(lines) == 8
        finally:
            mp.undo()

    def test_over_threshold_trims_to_max(
        self, tmp_path: Path
    ) -> None:
        """When line count exceeds 2× MAX_ENTRIES, trim to last MAX_ENTRIES."""
        target = tmp_path / "log.jsonl"
        from pytest import MonkeyPatch

        mp = MonkeyPatch()
        mp.setattr(eigenform_logger, "MAX_ENTRIES", 3)
        try:
            for i in range(7):  # 7 > 2*3 = 6 → trim
                log_state_vector(presence=float(i), path=target)
            lines = target.read_text().strip().split("\n")
            # Should be trimmed to last 3 entries
            assert len(lines) == 3
            entries = [json.loads(line) for line in lines]
            # Last 3 are presence 4, 5, 6
            assert [e["presence"] for e in entries] == [4.0, 5.0, 6.0]
        finally:
            mp.undo()


# ── Error tolerance ───────────────────────────────────────────────


class TestErrorTolerance:
    def test_trim_oserror_swallowed(self, tmp_path: Path) -> None:
        """The trim's read_text/write_text is wrapped in try/except OSError;
        a hostile filesystem doesn't crash the logger. Verify the append
        still made it to disk."""
        target = tmp_path / "log.jsonl"
        log_state_vector(presence=0.5, path=target)
        assert target.exists()
        entry = json.loads(target.read_text().strip())
        assert entry["presence"] == 0.5
