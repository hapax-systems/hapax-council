"""Tests for the weekly research digest producer."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from shared.weekly_research_digest_producer import (
    build_digest_event,
    build_digest_thread,
    emit_digest,
    load_recent_events,
    run_weekly_digest,
)


def _make_events_file(tmp_path, events):
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


def _pr_event(occurred_at, pr_number=1):
    return {
        "event_id": f"pr-merge-{pr_number}",
        "event_type": "metadata.update",
        "occurred_at": occurred_at,
    }


def _other_event(occurred_at, event_type="chronicle.high_salience"):
    return {"event_id": "other-1", "event_type": event_type, "occurred_at": occurred_at}


class TestLoadRecentEvents:
    def test_loads_recent_only(self, tmp_path):
        now = datetime.now(UTC)
        old = (now - timedelta(days=10)).isoformat()
        recent = (now - timedelta(days=2)).isoformat()
        path = _make_events_file(tmp_path, [_pr_event(old), _pr_event(recent, 2)])
        events = load_recent_events(path, days=7)
        assert len(events) == 1
        assert events[0]["event_id"] == "pr-merge-2"

    def test_empty_file(self, tmp_path):
        path = tmp_path / "events.jsonl"
        path.write_text("")
        assert load_recent_events(path) == []

    def test_missing_file(self, tmp_path):
        assert load_recent_events(tmp_path / "nonexistent.jsonl") == []


class TestBuildDigestThread:
    def test_thread_with_pr_events(self):
        events = [_pr_event("2026-05-20T00:00:00Z", i) for i in range(5)]
        thread = build_digest_thread(events, "2026-05-20")
        assert "5 PRs merged" in thread[1]
        assert "2026-05-20" in thread[0]

    def test_thread_with_mixed_events(self):
        events = [
            _pr_event("2026-05-20T00:00:00Z"),
            _other_event("2026-05-20T00:00:00Z", "chronicle.high_salience"),
            _other_event("2026-05-20T00:00:00Z", "chronicle.high_salience"),
        ]
        thread = build_digest_thread(events, "2026-05-20")
        assert "3 events" in thread[0]
        assert "1 PRs" in thread[1]

    def test_empty_week(self):
        thread = build_digest_thread([], "2026-05-20")
        assert "quiet week" in thread[0]


class TestBuildDigestEvent:
    def test_builds_valid_event(self):
        thread = ["Week summary.", "5 PRs merged."]
        event = build_digest_event(thread, "2026-05-20", 5)
        assert event.event_id.startswith("weekly-digest-")
        assert event.event_type == "velocity.digest"
        assert event.rights_class == "operator_original"

    def test_dry_run_sets_reason(self):
        event = build_digest_event(["test"], "2026-05-20", 0, dry_run=True)
        assert event.surface_policy.dry_run_reason == "dry_run_mode"

    def test_non_dry_run_no_reason(self):
        event = build_digest_event(["test"], "2026-05-20", 0, dry_run=False)
        assert event.surface_policy.dry_run_reason is None


class TestEmitDigest:
    def test_emits_to_file(self, tmp_path):
        event = build_digest_event(["test"], "2026-05-20", 0)
        output = tmp_path / "out.jsonl"
        emit_digest(event, output)
        assert output.exists()
        parsed = json.loads(output.read_text().strip())
        assert parsed["event_type"] == "velocity.digest"


class TestRunWeeklyDigest:
    def test_dry_run_does_not_emit(self, tmp_path):
        events_path = _make_events_file(
            tmp_path,
            [
                _pr_event(datetime.now(UTC).isoformat()),
            ],
        )
        output = tmp_path / "out.jsonl"
        event = run_weekly_digest(events_path=events_path, output_path=output, dry_run=True)
        assert event.event_id.startswith("weekly-digest-")
        assert not output.exists()

    def test_non_dry_run_emits(self, tmp_path):
        events_path = _make_events_file(
            tmp_path,
            [
                _pr_event(datetime.now(UTC).isoformat()),
            ],
        )
        output = tmp_path / "out.jsonl"
        run_weekly_digest(events_path=events_path, output_path=output, dry_run=False)
        assert output.exists()
