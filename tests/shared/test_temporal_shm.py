"""Tests for shared.temporal_shm.read_temporal_block.

The public reader name remains for compatibility, but the implementation now
renders WCS temporal/perceptual health rows instead of injecting raw temporal
XML from shared memory.
"""

from __future__ import annotations

from shared import temporal_shm


def test_temporal_reader_delegates_to_wcs_prompt_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        temporal_shm,
        "render_default_temporal_prompt_block",
        lambda: "## Temporal/Perceptual WCS Prompt Gate\nblock_state: blocked",
    )

    result = temporal_shm.read_temporal_block()

    assert "Temporal/Perceptual WCS Prompt Gate" in result
    assert "block_state: blocked" in result


def test_temporal_reader_fails_closed_when_wcs_gate_raises(monkeypatch) -> None:
    def _raise() -> str:
        raise ValueError("bad WCS rows")

    monkeypatch.setattr(temporal_shm, "render_default_temporal_prompt_block", _raise)

    assert temporal_shm.read_temporal_block() == ""


def test_raw_temporal_xml_file_is_not_prompt_authority(monkeypatch, tmp_path) -> None:
    raw_temporal = tmp_path / "bands.json"
    raw_temporal.write_text(
        '{"xml": "<temporal_context>raw current truth</temporal_context>", "timestamp": 1}',
        encoding="utf-8",
    )
    monkeypatch.setattr(temporal_shm, "TEMPORAL_FILE", raw_temporal)
    monkeypatch.setattr(
        temporal_shm,
        "render_default_temporal_prompt_block",
        lambda: "## Temporal/Perceptual WCS Prompt Gate\nsource=WCS",
    )

    result = temporal_shm.read_temporal_block()

    assert "source=WCS" in result
    assert "<temporal_context>" not in result
    assert "raw current truth" not in result
