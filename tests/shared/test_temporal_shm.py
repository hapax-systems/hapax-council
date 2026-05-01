"""Tests for shared.temporal_shm.read_temporal_block.

48-LOC reader for /dev/shm/hapax-temporal/bands.json that formats
Husserlian temporal context (retention/impression/protention/surprise)
into a prompt-injection block. Untested before this commit.

The TEMPORAL_FILE constant is monkeypatched per test so the real
/dev/shm state is never read.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from shared import temporal_shm


@pytest.fixture
def fake_temporal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "bands.json"
    monkeypatch.setattr(temporal_shm, "TEMPORAL_FILE", path)
    return path


def _payload(
    *,
    xml: str = "<temporal_context>\n  <retention>x</retention>\n</temporal_context>",
    timestamp: float | None = None,
    max_surprise: float = 0.0,
) -> dict:
    return {
        "timestamp": timestamp if timestamp is not None else time.time(),
        "xml": xml,
        "max_surprise": max_surprise,
    }


# ── Empty / missing / malformed input ──────────────────────────────


class TestEmptyAndMissing:
    def test_missing_file_returns_empty(self, fake_temporal: Path) -> None:
        assert not fake_temporal.exists()
        assert temporal_shm.read_temporal_block() == ""

    def test_malformed_json_returns_empty(self, fake_temporal: Path) -> None:
        fake_temporal.write_text("{ not valid json")
        assert temporal_shm.read_temporal_block() == ""

    def test_empty_xml_returns_empty(self, fake_temporal: Path) -> None:
        fake_temporal.write_text(json.dumps(_payload(xml="")))
        assert temporal_shm.read_temporal_block() == ""

    def test_skeleton_only_xml_returns_empty(self, fake_temporal: Path) -> None:
        """The literal `<temporal_context>\\n</temporal_context>` skeleton
        is treated as empty — no actual band data is present."""
        fake_temporal.write_text(
            json.dumps(_payload(xml="<temporal_context>\n</temporal_context>"))
        )
        assert temporal_shm.read_temporal_block() == ""


# ── Staleness gate ─────────────────────────────────────────────────


class TestStaleness:
    def test_fresh_data_renders(self, fake_temporal: Path) -> None:
        fake_temporal.write_text(json.dumps(_payload()))
        result = temporal_shm.read_temporal_block()
        assert "Temporal context" in result
        assert "<temporal_context>" in result

    def test_stale_data_returns_empty(self, fake_temporal: Path) -> None:
        """timestamp older than 30s gates the block to empty."""
        fake_temporal.write_text(
            json.dumps(_payload(timestamp=time.time() - 100))
        )
        assert temporal_shm.read_temporal_block() == ""

    def test_no_timestamp_treated_as_fresh(self, fake_temporal: Path) -> None:
        """timestamp=0 (default in raw.get) bypasses the staleness gate
        per the `if ts > 0` guard — payload is rendered."""
        fake_temporal.write_text(
            json.dumps({"xml": "<temporal_context>\n  <r>x</r>\n</temporal_context>"})
        )
        assert "Temporal context" in temporal_shm.read_temporal_block()


# ── Preamble shaping ───────────────────────────────────────────────


class TestPreamble:
    def test_default_preamble_no_surprise(self, fake_temporal: Path) -> None:
        fake_temporal.write_text(json.dumps(_payload(max_surprise=0.0)))
        result = temporal_shm.read_temporal_block()
        assert "retention = fading past" in result
        assert "impression = vivid present" in result
        assert "protention = anticipated near-future" in result
        assert "SURPRISE" not in result

    def test_surprise_above_threshold_in_preamble(self, fake_temporal: Path) -> None:
        """max_surprise > 0.3 triggers the SURPRISE flag with the score."""
        fake_temporal.write_text(json.dumps(_payload(max_surprise=0.75)))
        result = temporal_shm.read_temporal_block()
        assert "SURPRISE detected: 0.75" in result

    def test_surprise_at_threshold_does_not_flag(self, fake_temporal: Path) -> None:
        """The check is `> 0.3`, not `>=`. max_surprise=0.3 should NOT
        trigger the flag."""
        fake_temporal.write_text(json.dumps(_payload(max_surprise=0.3)))
        result = temporal_shm.read_temporal_block()
        assert "SURPRISE" not in result

    def test_xml_appended_after_preamble(self, fake_temporal: Path) -> None:
        """The XML is the last segment after the colon-newline boundary."""
        xml = "<temporal_context>\n  <impression>now</impression>\n</temporal_context>"
        fake_temporal.write_text(json.dumps(_payload(xml=xml)))
        result = temporal_shm.read_temporal_block()
        assert result.endswith(xml)
        assert "):\n" in result
