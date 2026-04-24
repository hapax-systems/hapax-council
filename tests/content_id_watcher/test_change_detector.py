"""Unit tests for agents.content_id_watcher.change_detector."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from agents.content_id_watcher.change_detector import ChangeEvent, detect_changes
from agents.content_id_watcher.salience import (
    KIND_CONTENT_ID_MATCH,
    KIND_INGEST_UNBIND,
    KIND_KIDS_CLASSIFICATION_CHANGE,
    KIND_LIFECYCLE_COMPLETE,
    KIND_METADATA_YT_EDITED,
    KIND_MONETIZATION_DRIFT,
    KIND_PRIORITY_CHANGE,
    KIND_VISIBILITY_CHANGE,
)


def _snapshot(**overrides) -> dict:
    base = {
        "status": {
            "lifeCycleStatus": "live",
            "liveBroadcastPriority": "normal",
            "rejectionReason": None,
            "publicStatsViewable": True,
            "madeForKids": False,
        },
        "contentDetails": {"boundStreamId": "stream-1"},
        "monetizationDetails": {"cuepointSchedule": {"strategy": "off"}},
        "snippet": {"title": "Live", "description": "desc"},
    }
    for path, value in overrides.items():
        cursor = base
        parts = path.split(".")
        for p in parts[:-1]:
            cursor = cursor.setdefault(p, {})
        cursor[parts[-1]] = value
    return base


# ── cold-start / no-change ─────────────────────────────────────────────────


def test_cold_start_emits_nothing():
    assert detect_changes(None, _snapshot(), broadcast_id="bx") == []


def test_no_change_emits_nothing():
    snap = _snapshot()
    assert detect_changes(snap, snap, broadcast_id="bx") == []


# ── per-field change detection ─────────────────────────────────────────────


def test_lifecycle_complete_change():
    old = _snapshot()
    new = _snapshot(**{"status.lifeCycleStatus": "complete"})
    events = detect_changes(old, new, broadcast_id="bx")
    assert any(e.kind == KIND_LIFECYCLE_COMPLETE and e.new_value == "complete" for e in events)


def test_priority_change():
    old = _snapshot()
    new = _snapshot(**{"status.liveBroadcastPriority": "low"})
    events = detect_changes(old, new, broadcast_id="bx")
    assert any(e.kind == KIND_PRIORITY_CHANGE for e in events)


def test_ingest_unbind():
    old = _snapshot()
    new = _snapshot(**{"contentDetails.boundStreamId": None})
    events = detect_changes(old, new, broadcast_id="bx")
    assert any(e.kind == KIND_INGEST_UNBIND for e in events)


def test_monetization_drift():
    old = _snapshot()
    new = _snapshot(**{"monetizationDetails.cuepointSchedule.strategy": "scheduled"})
    events = detect_changes(old, new, broadcast_id="bx")
    assert any(e.kind == KIND_MONETIZATION_DRIFT for e in events)


def test_title_yt_edit():
    old = _snapshot()
    new = _snapshot(**{"snippet.title": "YouTube edited me"})
    events = detect_changes(old, new, broadcast_id="bx")
    metadata_events = [e for e in events if e.kind == KIND_METADATA_YT_EDITED]
    assert len(metadata_events) == 1
    assert metadata_events[0].new_value == "YouTube edited me"


def test_description_yt_edit():
    old = _snapshot()
    new = _snapshot(**{"snippet.description": "edited"})
    events = detect_changes(old, new, broadcast_id="bx")
    metadata_events = [e for e in events if e.kind == KIND_METADATA_YT_EDITED]
    assert len(metadata_events) == 1


def test_title_and_description_coalesced():
    """Both metadata edits in one tick → single coalesced event."""
    old = _snapshot()
    new = _snapshot(**{"snippet.title": "new title", "snippet.description": "new desc"})
    events = detect_changes(old, new, broadcast_id="bx")
    metadata_events = [e for e in events if e.kind == KIND_METADATA_YT_EDITED]
    assert len(metadata_events) == 1
    coalesced = metadata_events[0]
    assert coalesced.new_value == {"title": "new title", "description": "new desc"}


def test_content_id_match():
    old = _snapshot()
    new = _snapshot(**{"status.rejectionReason": "copyrightStrike"})
    events = detect_changes(old, new, broadcast_id="bx")
    cid_events = [e for e in events if e.kind == KIND_CONTENT_ID_MATCH]
    assert cid_events
    assert cid_events[0].new_value == "copyrightStrike"
    assert cid_events[0].salience == 1.0
    assert cid_events[0].ntfy_eligible


def test_visibility_change():
    old = _snapshot()
    new = _snapshot(**{"status.publicStatsViewable": False})
    events = detect_changes(old, new, broadcast_id="bx")
    assert any(e.kind == KIND_VISIBILITY_CHANGE for e in events)


def test_kids_classification_change():
    old = _snapshot()
    new = _snapshot(**{"status.madeForKids": True})
    events = detect_changes(old, new, broadcast_id="bx")
    kids_events = [e for e in events if e.kind == KIND_KIDS_CLASSIFICATION_CHANGE]
    assert kids_events
    assert kids_events[0].salience == 1.0
    assert kids_events[0].ntfy_eligible


# ── ChangeEvent metadata ──────────────────────────────────────────────────


def test_change_event_intent_family_namespaced():
    event = ChangeEvent(
        kind=KIND_CONTENT_ID_MATCH, broadcast_id="bx", old_value=None, new_value="x"
    )
    assert event.intent_family == "egress.youtube_content_id_match"


def test_low_salience_kind_not_ntfy_eligible():
    event = ChangeEvent(
        kind=KIND_VISIBILITY_CHANGE, broadcast_id="bx", old_value=True, new_value=False
    )
    assert not event.ntfy_eligible
    assert event.salience == 0.4


def test_change_event_narrative_includes_diff():
    event = ChangeEvent(
        kind=KIND_PRIORITY_CHANGE, broadcast_id="bx", old_value="normal", new_value="low"
    )
    narrative = event.narrative()
    assert "bx" in narrative
    assert "normal" in narrative
    assert "low" in narrative


# ── Hypothesis property ───────────────────────────────────────────────────


@given(
    new_status=st.sampled_from(["live", "complete", "liveStarting", "ready"]),
)
def test_detect_changes_deterministic(new_status):
    """Same (old, new) inputs always yield the same event list."""
    old = _snapshot()
    new = _snapshot(**{"status.lifeCycleStatus": new_status})
    a = detect_changes(old, new, broadcast_id="bx")
    b = detect_changes(old, new, broadcast_id="bx")
    assert [e.kind for e in a] == [e.kind for e in b]
    assert [e.new_value for e in a] == [e.new_value for e in b]
