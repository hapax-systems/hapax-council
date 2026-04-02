"""tests/test_chronicle_sampler.py — Unit tests for shared.chronicle_sampler."""

from __future__ import annotations

import json

from shared.chronicle_sampler import assemble_snapshot

# ── assemble_snapshot ─────────────────────────────────────────────────────────


def test_assemble_snapshot_returns_dict(tmp_path):
    """Missing stimmung + eigenform files → all sub-dicts are empty, not errors."""
    result = assemble_snapshot(
        stimmung_path=tmp_path / "no-stimmung.json",
        eigenform_path=tmp_path / "no-eigenform.jsonl",
    )
    assert isinstance(result, dict)
    assert result["stimmung"] == {}
    assert result["eigenform"] == {}
    assert result["signals"] == {}


def test_assemble_snapshot_reads_stimmung(tmp_path):
    """Reads stance and dimensions from a well-formed stimmung JSON file."""
    stimmung_file = tmp_path / "state.json"
    payload = {
        "stance": "SEEKING",
        "dimensions": {"intensity": 0.7, "tension": 0.3},
        "extra_field": "ignored",
    }
    stimmung_file.write_text(json.dumps(payload), encoding="utf-8")

    result = assemble_snapshot(
        stimmung_path=stimmung_file,
        eigenform_path=tmp_path / "no-eigenform.jsonl",
    )

    assert result["stimmung"]["stance"] == "SEEKING"
    assert result["stimmung"]["dimensions"] == {"intensity": 0.7, "tension": 0.3}
    # extra_field should not be surfaced
    assert "extra_field" not in result["stimmung"]


def test_assemble_snapshot_reads_eigenform_latest(tmp_path):
    """Reads only the *last* entry from a multi-line JSONL log."""
    eigenform_file = tmp_path / "state-log.jsonl"
    entries = [
        {"ts": 1000.0, "coherence": 0.1},
        {"ts": 2000.0, "coherence": 0.5},
        {"ts": 3000.0, "coherence": 0.9},
    ]
    eigenform_file.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )

    result = assemble_snapshot(
        stimmung_path=tmp_path / "no-stimmung.json",
        eigenform_path=eigenform_file,
    )

    assert result["eigenform"] == {"ts": 3000.0, "coherence": 0.9}


def test_assemble_snapshot_includes_signal_bus(tmp_path):
    """signal_bus_snapshot dict is passed through unchanged under 'signals'."""
    signals = {"hr_bpm": 72.0, "motion_delta": 0.15}

    result = assemble_snapshot(
        stimmung_path=tmp_path / "no-stimmung.json",
        eigenform_path=tmp_path / "no-eigenform.jsonl",
        signal_bus_snapshot=signals,
    )

    assert result["signals"] == signals


def test_assemble_snapshot_signal_bus_none_returns_empty(tmp_path):
    """Passing None for signal_bus_snapshot normalizes to an empty dict."""
    result = assemble_snapshot(
        stimmung_path=tmp_path / "no-stimmung.json",
        eigenform_path=tmp_path / "no-eigenform.jsonl",
        signal_bus_snapshot=None,
    )
    assert result["signals"] == {}


def test_assemble_snapshot_stimmung_missing_fields(tmp_path):
    """A stimmung file that omits 'dimensions' still returns the present field."""
    stimmung_file = tmp_path / "state.json"
    stimmung_file.write_text(json.dumps({"stance": "REST"}), encoding="utf-8")

    result = assemble_snapshot(
        stimmung_path=stimmung_file,
        eigenform_path=tmp_path / "no-eigenform.jsonl",
    )

    assert result["stimmung"] == {"stance": "REST"}
    assert "dimensions" not in result["stimmung"]


def test_assemble_snapshot_eigenform_empty_file(tmp_path):
    """An empty JSONL file returns an empty eigenform dict."""
    eigenform_file = tmp_path / "state-log.jsonl"
    eigenform_file.write_text("", encoding="utf-8")

    result = assemble_snapshot(
        stimmung_path=tmp_path / "no-stimmung.json",
        eigenform_path=eigenform_file,
    )

    assert result["eigenform"] == {}


def test_assemble_snapshot_stimmung_malformed(tmp_path):
    """Malformed JSON in stimmung file returns empty dict, not an exception."""
    stimmung_file = tmp_path / "state.json"
    stimmung_file.write_text("{ not valid json", encoding="utf-8")

    result = assemble_snapshot(
        stimmung_path=stimmung_file,
        eigenform_path=tmp_path / "no-eigenform.jsonl",
    )

    assert result["stimmung"] == {}
