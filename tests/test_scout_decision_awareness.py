"""Tests for scout decision-awareness (cooldown suppression)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agents.scout import load_decisions, DECISION_COOLDOWN_DAYS


@pytest.fixture
def decisions_file(tmp_path):
    return tmp_path / "scout-decisions.jsonl"


def _write_decision(path: Path, component: str, decision: str, days_ago: int) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    with open(path, "a") as f:
        f.write(json.dumps({
            "component": component,
            "decision": decision,
            "timestamp": ts,
            "notes": "",
        }) + "\n")


def test_dismissed_within_cooldown_skipped(decisions_file):
    _write_decision(decisions_file, "vector-database", "dismissed", days_ago=30)
    decisions = load_decisions(decisions_file)
    assert "vector-database" in decisions
    assert decisions["vector-database"]["decision"] == "dismissed"
    ts = datetime.fromisoformat(decisions["vector-database"]["timestamp"])
    age_days = (datetime.now(timezone.utc) - ts).days
    assert age_days < DECISION_COOLDOWN_DAYS


def test_dismissed_past_cooldown_evaluated(decisions_file):
    _write_decision(decisions_file, "vector-database", "dismissed", days_ago=100)
    decisions = load_decisions(decisions_file)
    assert "vector-database" in decisions
    ts = datetime.fromisoformat(decisions["vector-database"]["timestamp"])
    age_days = (datetime.now(timezone.utc) - ts).days
    assert age_days >= DECISION_COOLDOWN_DAYS


def test_deferred_within_cooldown_skipped(decisions_file):
    _write_decision(decisions_file, "embedding-model", "deferred", days_ago=60)
    decisions = load_decisions(decisions_file)
    assert "embedding-model" in decisions
    assert decisions["embedding-model"]["decision"] == "deferred"
    ts = datetime.fromisoformat(decisions["embedding-model"]["timestamp"])
    age_days = (datetime.now(timezone.utc) - ts).days
    assert age_days < DECISION_COOLDOWN_DAYS


def test_adopted_not_skipped(decisions_file):
    _write_decision(decisions_file, "agent-framework", "adopted", days_ago=10)
    decisions = load_decisions(decisions_file)
    assert "agent-framework" in decisions
    assert decisions["agent-framework"]["decision"] == "adopted"


def test_latest_decision_wins(decisions_file):
    _write_decision(decisions_file, "vector-database", "dismissed", days_ago=100)
    _write_decision(decisions_file, "vector-database", "dismissed", days_ago=10)
    decisions = load_decisions(decisions_file)
    ts = datetime.fromisoformat(decisions["vector-database"]["timestamp"])
    age_days = (datetime.now(timezone.utc) - ts).days
    assert age_days < 15


def test_missing_file_returns_empty(tmp_path):
    decisions = load_decisions(tmp_path / "nonexistent.jsonl")
    assert decisions == {}
