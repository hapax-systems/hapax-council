"""Tests for logos.accommodations — negotiated accommodation engine."""

from __future__ import annotations

from unittest.mock import patch

from logos.accommodations import (
    Accommodation,
    AccommodationSet,
    confirm_accommodation,
    disable_accommodation,
    load_accommodations,
    propose_accommodation,
    save_accommodations,
)

# ── propose_accommodation tests ────────────────────────────────────────────


def test_propose_time_perception():
    proposals = propose_accommodation("time_perception")
    assert len(proposals) >= 1
    assert proposals[0].id == "time_anchor"
    assert proposals[0].active is False
    assert proposals[0].proposed_at != ""


def test_propose_demand_sensitivity():
    proposals = propose_accommodation("demand_sensitivity")
    assert len(proposals) >= 1
    assert proposals[0].id == "soft_framing"


def test_propose_energy_cycles():
    proposals = propose_accommodation("energy_cycles")
    assert len(proposals) >= 1
    assert proposals[0].id == "energy_aware"


def test_propose_unknown_category():
    proposals = propose_accommodation("nonexistent_category")
    assert proposals == []


def test_propose_task_initiation():
    proposals = propose_accommodation("task_initiation")
    assert len(proposals) >= 1
    assert proposals[0].id == "smallest_step"


# ── AccommodationSet tests ─────────────────────────────────────────────────


def test_accommodation_set_defaults():
    acc = AccommodationSet()
    assert acc.time_anchor_enabled is False
    assert acc.soft_framing is False
    assert acc.energy_aware is False
    assert acc.peak_hours == []
    assert acc.low_hours == []


# ── Save/load tests ────────────────────────────────────────────────────────


def test_save_and_load(tmp_path):
    path = tmp_path / "accommodations.json"
    acc = AccommodationSet(
        accommodations=[
            Accommodation(
                id="time_anchor",
                pattern_category="time_perception",
                description="Show elapsed time",
                active=True,
                proposed_at="2026-03-01T10:00:00Z",
                confirmed_at="2026-03-01T10:05:00Z",
            ),
        ]
    )
    with patch("logos.accommodations._ACCOMMODATIONS_PATH", path):
        with patch("logos.accommodations.PROFILES_DIR", tmp_path):
            save_accommodations(acc)
            loaded = load_accommodations()
    assert len(loaded.accommodations) == 1
    assert loaded.accommodations[0].id == "time_anchor"
    assert loaded.accommodations[0].active is True
    assert loaded.time_anchor_enabled is True


def test_load_missing_file(tmp_path):
    path = tmp_path / "does_not_exist.json"
    with patch("logos.accommodations._ACCOMMODATIONS_PATH", path):
        loaded = load_accommodations()
    assert loaded.accommodations == []
    assert loaded.time_anchor_enabled is False


def test_load_corrupt_file(tmp_path):
    path = tmp_path / "accommodations.json"
    path.write_text("not valid json")
    with patch("logos.accommodations._ACCOMMODATIONS_PATH", path):
        loaded = load_accommodations()
    assert loaded.accommodations == []


# ── confirm/disable tests ──────────────────────────────────────────────────


def test_confirm_accommodation(tmp_path):
    path = tmp_path / "accommodations.json"
    acc = AccommodationSet(
        accommodations=[
            Accommodation(
                id="soft_framing",
                pattern_category="demand_sensitivity",
                description="Use observational framing",
                active=False,
                proposed_at="2026-03-01T10:00:00Z",
            ),
        ]
    )
    with patch("logos.accommodations._ACCOMMODATIONS_PATH", path):
        with patch("logos.accommodations.PROFILES_DIR", tmp_path):
            result = confirm_accommodation(acc, "soft_framing")
    assert result is True
    assert acc.accommodations[0].active is True
    assert acc.accommodations[0].confirmed_at != ""


def test_confirm_nonexistent():
    acc = AccommodationSet()
    with patch("logos.accommodations._ACCOMMODATIONS_PATH"):
        result = confirm_accommodation(acc, "nonexistent")
    assert result is False


def test_disable_accommodation(tmp_path):
    path = tmp_path / "accommodations.json"
    acc = AccommodationSet(
        accommodations=[
            Accommodation(
                id="time_anchor",
                pattern_category="time_perception",
                description="Show elapsed time",
                active=True,
                proposed_at="2026-03-01T10:00:00Z",
                confirmed_at="2026-03-01T10:05:00Z",
            ),
        ]
    )
    with patch("logos.accommodations._ACCOMMODATIONS_PATH", path):
        with patch("logos.accommodations.PROFILES_DIR", tmp_path):
            result = disable_accommodation(acc, "time_anchor")
    assert result is True
    assert acc.accommodations[0].active is False
    assert acc.accommodations[0].confirmed_at == ""


# ── Copilot accommodation tests ───────────────────────────────────────────


def test_copilot_time_anchor():
    from logos.copilot import CopilotContext, CopilotEngine

    acc = AccommodationSet(time_anchor_enabled=True)
    ctx = CopilotContext(
        health_status="healthy",
        session_age_s=600,  # 10 minutes
        accommodations=acc,
    )
    engine = CopilotEngine()
    msg = engine.evaluate(ctx)
    assert "(10m in)" in msg


def test_copilot_no_time_anchor_when_disabled():
    from logos.copilot import CopilotContext, CopilotEngine

    acc = AccommodationSet(time_anchor_enabled=False)
    ctx = CopilotContext(
        health_status="healthy",
        session_age_s=600,
        accommodations=acc,
    )
    engine = CopilotEngine()
    msg = engine.evaluate(ctx)
    assert "(10m in)" not in msg


def test_copilot_no_accommodations():
    from logos.copilot import CopilotContext, CopilotEngine

    ctx = CopilotContext(
        health_status="healthy",
        session_age_s=600,
        accommodations=None,
    )
    engine = CopilotEngine()
    msg = engine.evaluate(ctx)
    assert "m in)" not in msg


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_load_accommodations_non_dict_root(tmp_path, payload, kind, monkeypatch):
    """Pin load_accommodations against non-dict JSON. The for loop calls
    data.get('accommodations', []) and item['id']; the existing
    (json.JSONDecodeError, KeyError) catch missed AttributeError on
    non-dict roots."""
    from logos import accommodations as acc

    path = tmp_path / "accommodations.json"
    path.write_text(payload)
    monkeypatch.setattr(acc, "_ACCOMMODATIONS_PATH", path)
    result = acc.load_accommodations()
    assert result.accommodations == [], f"non-dict root={kind} must yield empty"
    assert result.time_anchor_enabled is False
    assert result.energy_aware is False


def test_load_accommodations_non_dict_entry_skipped(tmp_path, monkeypatch):
    """If the root is dict but an individual accommodation entry is
    non-dict (schema drift), skip that entry instead of crashing on
    item['id']."""
    from logos import accommodations as acc

    path = tmp_path / "accommodations.json"
    path.write_text('{"accommodations": [{"id": "valid", "active": true},"garbage-string-entry"]}')
    monkeypatch.setattr(acc, "_ACCOMMODATIONS_PATH", path)
    result = acc.load_accommodations()
    # Only the valid entry survives.
    assert len(result.accommodations) == 1
    assert result.accommodations[0].id == "valid"
