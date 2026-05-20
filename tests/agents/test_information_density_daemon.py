"""Tests for narrative density audience relevance."""

from __future__ import annotations

import json

from agents import information_density_daemon


def test_narrative_relevance_combines_viewers_chat_and_concept_mastery(
    tmp_path, monkeypatch
) -> None:
    audience = tmp_path / "audience.json"
    audience.write_text(
        json.dumps(
            {
                "viewer_count": 5,
                "chat_rate_per_min": 2.0,
                "avg_watch_time_s": 180.0,
                "concept_mastery": {
                    "zpd_pressure": 0.6,
                    "unknown_pressure": 0.2,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(information_density_daemon, "AUDIENCE_SHM", audience)

    relevance = information_density_daemon.NarrativeSource([])._compute_relevance()

    assert 0.0 < relevance < 1.0


def test_narrative_relevance_uses_bkt_pressure_without_viewers(tmp_path, monkeypatch) -> None:
    audience = tmp_path / "audience.json"
    audience.write_text(
        json.dumps({"viewer_count": 0, "concept_mastery": {"unknown_pressure": 0.8}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(information_density_daemon, "AUDIENCE_SHM", audience)

    relevance = information_density_daemon.NarrativeSource([])._compute_relevance()

    assert relevance > 0.0
