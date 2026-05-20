"""Tests for audience perception SHM shaping."""

from __future__ import annotations

import json

from agents import audience_perception


def test_poll_audience_reads_youtube_viewer_count_and_bkt_pressure(tmp_path, monkeypatch) -> None:
    viewer_file = tmp_path / "viewer-count.txt"
    viewer_file.write_text("7", encoding="utf-8")
    chat_file = tmp_path / "recent.jsonl"
    chat_file.write_text(
        "\n".join(
            [
                json.dumps({"timestamp": 1_000.0, "text": "first"}),
                json.dumps({"timestamp": 1_030.0, "text": "second"}),
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(audience_perception, "OVERRIDE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(audience_perception, "VIEWER_COUNT_FILE", viewer_file)
    monkeypatch.setattr(audience_perception, "CHAT_RECENT_FILE", chat_file)
    monkeypatch.setattr(audience_perception.time, "time", lambda: 1_040.0)
    monkeypatch.setattr(
        audience_perception,
        "_concept_mastery_payload",
        lambda: {
            "tracked_count": 3,
            "zpd_concepts": ["density"],
            "unknown_concepts": ["narrative arc"],
            "zpd_pressure": 1 / 3,
            "unknown_pressure": 1 / 3,
        },
    )

    state = audience_perception._poll_audience()

    assert state["source"] == "youtube_api"
    assert state["viewer_count"] == 7
    assert state["chat_rate_per_min"] == 2.0
    assert state["concept_mastery"]["tracked_count"] == 3
    assert state["zpd_pressure"] == 1 / 3


def test_poll_audience_override_is_still_enriched_with_bkt_pressure(tmp_path, monkeypatch) -> None:
    override = tmp_path / "audience-override.json"
    override.write_text(json.dumps({"viewer_count": 2, "chat_rate_per_min": 1.5}), encoding="utf-8")

    monkeypatch.setattr(audience_perception, "OVERRIDE_FILE", override)
    monkeypatch.setattr(
        audience_perception,
        "_concept_mastery_payload",
        lambda: {
            "tracked_count": 1,
            "zpd_concepts": ["intro"],
            "unknown_concepts": [],
            "zpd_pressure": 1.0,
            "unknown_pressure": 0.0,
        },
    )

    state = audience_perception._poll_audience()

    assert state["source"] == "override"
    assert state["viewer_count"] == 2
    assert state["concept_mastery"]["zpd_concepts"] == ["intro"]
    assert state["zpd_pressure"] == 1.0
