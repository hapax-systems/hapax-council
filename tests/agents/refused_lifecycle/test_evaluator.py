"""Tests for ``agents.refused_lifecycle.evaluator.decide_transition``.

Pure decision logic — 12+ cases covering all transition kinds + conservative
defaults + multi-trigger.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agents.refused_lifecycle.evaluator import decide_transition
from agents.refused_lifecycle.state import (
    ProbeResult,
    RefusalTask,
    RemovalSignal,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _refused_task(**overrides) -> RefusalTask:
    defaults = dict(
        slug="leverage-twitter",
        path="/tmp/leverage-twitter.md",
        automation_status="REFUSED",
        refusal_reason="single_user axiom",
        evaluation_trigger=["constitutional"],
        evaluation_probe={"depends_on_slug": None},
    )
    defaults.update(overrides)
    return RefusalTask(**defaults)


def _offered_task(**overrides) -> RefusalTask:
    return _refused_task(automation_status="OFFERED", **overrides)


def _clear_probe() -> ProbeResult:
    return ProbeResult(
        changed=True,
        evidence_url="https://example.com/policy",
        snippet="policy lifted as of 2026-04-26",
    )


# ── REFUSED state ────────────────────────────────────────────────────


class TestFromRefused:
    def test_all_clear_probes_accept(self):
        task = _refused_task()
        ev = decide_transition(task, [_clear_probe()])
        assert ev.from_state == "REFUSED"
        assert ev.to_state == "ACCEPTED"
        assert ev.transition == "accepted"
        assert ev.evidence_url == "https://example.com/policy"

    def test_multi_probe_all_clear_accepts(self):
        task = _refused_task()
        probes = [_clear_probe(), _clear_probe()]
        ev = decide_transition(task, probes)
        assert ev.transition == "accepted"

    def test_one_probe_error_re_affirms(self):
        task = _refused_task()
        probes = [_clear_probe(), ProbeResult(changed=False, error="HTTP 503")]
        ev = decide_transition(task, probes)
        assert ev.transition == "re-affirmed"
        assert ev.from_state == "REFUSED"
        assert ev.to_state == "REFUSED"
        assert "HTTP 503" in ev.reason

    def test_one_probe_unchanged_re_affirms(self):
        task = _refused_task()
        probes = [_clear_probe(), ProbeResult(changed=False)]
        ev = decide_transition(task, probes)
        assert ev.transition == "re-affirmed"

    def test_missing_evidence_url_re_affirms(self):
        task = _refused_task()
        probes = [ProbeResult(changed=True, snippet="lifted", evidence_url=None)]
        ev = decide_transition(task, probes)
        assert ev.transition == "re-affirmed"
        assert "evidence-incomplete" in ev.reason

    def test_missing_snippet_re_affirms(self):
        task = _refused_task()
        probes = [ProbeResult(changed=True, evidence_url="https://x.example", snippet=None)]
        ev = decide_transition(task, probes)
        assert ev.transition == "re-affirmed"
        assert "evidence-incomplete" in ev.reason

    def test_empty_probes_re_affirms(self):
        task = _refused_task()
        ev = decide_transition(task, [])
        assert ev.transition == "re-affirmed"
        assert "no-probes" in ev.reason

    def test_removal_signal_routes_to_removed(self):
        task = _refused_task()
        sig = RemovalSignal(reason="axiom retired", superseded_by="leverage-twitter-v2")
        ev = decide_transition(task, [], removal_signal=sig)
        assert ev.from_state == "REFUSED"
        assert ev.to_state == "REMOVED"
        assert ev.transition == "removed"
        assert "axiom retired" in ev.reason


# ── OFFERED state (post-acceptance) ─────────────────────────────────


class TestFromAccepted:
    def test_all_clear_probes_regress(self):
        task = _offered_task()
        ev = decide_transition(task, [_clear_probe()])
        assert ev.from_state == "ACCEPTED"
        assert ev.to_state == "REFUSED"
        assert ev.transition == "regressed"

    def test_unchanged_probes_re_affirm_acceptance(self):
        task = _offered_task()
        ev = decide_transition(task, [ProbeResult(changed=False)])
        assert ev.transition == "re-affirmed"
        assert ev.from_state == "ACCEPTED"
        assert ev.to_state == "ACCEPTED"

    def test_probe_error_re_affirms_acceptance(self):
        task = _offered_task()
        ev = decide_transition(task, [ProbeResult(changed=False, error="timeout")])
        assert ev.transition == "re-affirmed"
        assert ev.to_state == "ACCEPTED"

    def test_removal_signal_routes_to_removed(self):
        task = _offered_task()
        sig = RemovalSignal(reason="cc-task closed")
        ev = decide_transition(task, [], removal_signal=sig)
        assert ev.from_state == "ACCEPTED"
        assert ev.to_state == "REMOVED"
        assert ev.transition == "removed"


# ── REMOVED is terminal ──────────────────────────────────────────────


class TestFromRemoved:
    def test_terminal_state_raises(self):
        task = _refused_task(automation_status="REMOVED")
        with pytest.raises(ValueError, match="REMOVED"):
            decide_transition(task, [])
