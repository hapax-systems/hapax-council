"""Tests for ``agents.refused_lifecycle.state`` Pydantic models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agents.refused_lifecycle.state import (
    ProbeResult,
    RefusalHistoryEntry,
    RefusalTask,
    RemovalSignal,
    TransitionEvent,
)


def _now() -> datetime:
    return datetime.now(UTC)


class TestRefusalHistoryEntry:
    def test_minimal_construction(self):
        entry = RefusalHistoryEntry(
            date=_now(),
            transition="created",
            reason="initial refusal",
        )
        assert entry.evidence_url is None

    def test_rejects_invalid_transition_kind(self):
        with pytest.raises(ValidationError):
            RefusalHistoryEntry(date=_now(), transition="bogus", reason="x")


class TestProbeResult:
    def test_default_outcome_is_unchanged(self):
        probe = ProbeResult(changed=False)
        assert probe.changed is False
        assert probe.evidence_url is None
        assert probe.snippet is None
        assert probe.error is None

    def test_full_construction(self):
        probe = ProbeResult(
            changed=True,
            evidence_url="https://example.com/page",
            snippet="lift keyword present",
            error=None,
        )
        assert probe.changed is True


class TestTransitionEvent:
    def test_minimal_construction(self):
        ev = TransitionEvent(
            timestamp=_now(),
            cc_task_slug="leverage-twitter-linkedin",
            from_state="REFUSED",
            to_state="REFUSED",
            transition="re-affirmed",
            trigger=["constitutional"],
            reason="probe-content-unchanged",
        )
        assert ev.evidence_url is None

    def test_rejects_unknown_trigger_category(self):
        with pytest.raises(ValidationError):
            TransitionEvent(
                timestamp=_now(),
                cc_task_slug="x",
                from_state="REFUSED",
                to_state="REFUSED",
                transition="re-affirmed",
                trigger=["bogus-trigger"],
                reason="x",
            )


class TestRefusalTask:
    def test_minimal_construction(self):
        task = RefusalTask(
            slug="leverage-twitter",
            path="/tmp/x.md",
            automation_status="REFUSED",
            refusal_reason="single_user axiom",
            evaluation_trigger=["constitutional"],
            evaluation_probe={"depends_on_slug": None},
        )
        assert task.refusal_history == []
        assert task.superseded_by is None
        assert task.acceptance_evidence is None


class TestRemovalSignal:
    def test_minimal_construction(self):
        sig = RemovalSignal(reason="axiom retired")
        assert sig.superseded_by is None
