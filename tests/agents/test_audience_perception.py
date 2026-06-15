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


def _stub_concept_mastery(monkeypatch) -> None:
    monkeypatch.setattr(
        audience_perception,
        "_concept_mastery_payload",
        lambda: {
            "tracked_count": 0,
            "zpd_concepts": [],
            "unknown_concepts": [],
            "zpd_pressure": 0.0,
            "unknown_pressure": 0.0,
        },
    )


def test_youtube_path_declares_unsensed_psi_fields(tmp_path, monkeypatch) -> None:
    """I2: the live YouTube path must DECLARE avg_watch_time_s / subscriber_delta as
    unsensed stubs (the producer exposes neither), not present them as measured."""
    viewer_file = tmp_path / "viewer-count.txt"
    viewer_file.write_text("7", encoding="utf-8")
    monkeypatch.setattr(audience_perception, "OVERRIDE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(audience_perception, "VIEWER_COUNT_FILE", viewer_file)
    monkeypatch.setattr(audience_perception, "CHAT_RECENT_FILE", tmp_path / "no-chat.jsonl")
    _stub_concept_mastery(monkeypatch)

    state = audience_perception._poll_audience()

    assert state["source"] == "youtube_api"
    assert state["unsensed_fields"] == ["avg_watch_time_s", "subscriber_delta"]
    # declared, NOT closed: the numeric value/type is unchanged for the density consumer
    assert state["avg_watch_time_s"] == 0.0
    assert state["subscriber_delta"] == 0


def test_fallback_path_declares_unsensed_psi_fields(tmp_path, monkeypatch) -> None:
    """No override + no viewer sample → the fallback path still declares the ψ stubs."""
    monkeypatch.setattr(audience_perception, "OVERRIDE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(audience_perception, "VIEWER_COUNT_FILE", tmp_path / "no-viewer.txt")
    _stub_concept_mastery(monkeypatch)

    state = audience_perception._poll_audience()

    assert state["source"] == "fallback"
    assert state["unsensed_fields"] == ["avg_watch_time_s", "subscriber_delta"]


def test_override_declares_unsensed_only_for_fields_operator_omitted(tmp_path, monkeypatch) -> None:
    """The override path is path-sensitive: a ψ field the operator SUPPLIED is a real
    sensed value (not unsensed); one the operator omitted is declared unsensed."""
    _stub_concept_mastery(monkeypatch)

    full = tmp_path / "audience-override.json"
    full.write_text(
        json.dumps({"viewer_count": 5, "avg_watch_time_s": 120.0, "subscriber_delta": 3}),
        encoding="utf-8",
    )
    monkeypatch.setattr(audience_perception, "OVERRIDE_FILE", full)
    state = audience_perception._poll_audience()
    assert state["source"] == "override"
    assert state["unsensed_fields"] == []

    partial = tmp_path / "audience-override-partial.json"
    partial.write_text(json.dumps({"viewer_count": 5, "avg_watch_time_s": 120.0}), encoding="utf-8")
    monkeypatch.setattr(audience_perception, "OVERRIDE_FILE", partial)
    state = audience_perception._poll_audience()
    assert state["unsensed_fields"] == ["subscriber_delta"]
