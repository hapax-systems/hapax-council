"""Unit tests for agents.metadata_composer.chapters."""

from __future__ import annotations

from agents.metadata_composer.chapters import ChapterMarker, extract_chapters


def test_empty_event_stream_emits_only_opener():
    chapters = extract_chapters([], vod_start_s=0.0)
    assert len(chapters) == 1
    assert chapters[0].timestamp_s == 0
    assert chapters[0].label == "Opening"


def test_high_salience_event_becomes_marker():
    events = [
        {
            "ts": 100.0,
            "event_type": "moment",
            "payload": {"salience": 0.9, "intent_family": "vinyl.side_change"},
        }
    ]
    chapters = extract_chapters(events, vod_start_s=0.0)
    labels = [c.label for c in chapters]
    assert "Opening" in labels
    assert any("Vinyl" in label for label in labels)


def test_low_salience_event_filtered_out():
    events = [
        {
            "ts": 50.0,
            "event_type": "tick",
            "payload": {"salience": 0.3},
        }
    ]
    chapters = extract_chapters(events, vod_start_s=0.0)
    assert len(chapters) == 1  # only the opener


def test_intent_family_change_becomes_marker():
    events = [
        {
            "ts": 75.0,
            "event_type": "field_change",
            "payload": {"intent_family_changed": True, "intent_family": "programme.start"},
        }
    ]
    chapters = extract_chapters(events, vod_start_s=0.0)
    labels = [c.label for c in chapters]
    assert any("Programme" in label for label in labels)


def test_transition_event_type_always_significant():
    events = [
        {"ts": 25.0, "event_type": "programme.transition", "payload": {}},
    ]
    chapters = extract_chapters(events, vod_start_s=0.0)
    assert len(chapters) >= 2  # opener + transition


def test_coalesce_drops_neighbors_within_60s():
    events = [
        {
            "ts": ts,
            "event_type": "moment",
            "payload": {"salience": 0.9, "intent_family": "x.tag"},
        }
        for ts in (100.0, 130.0, 200.0)
    ]
    chapters = extract_chapters(events, vod_start_s=0.0)
    # opener + 100s + 200s; the 130s event is coalesced into the 100s window
    assert len(chapters) == 3
    offsets = [c.timestamp_s for c in chapters]
    assert offsets == [0, 100, 200]


def test_min_spacing_after_opener():
    events = [
        {
            "ts": 5.0,
            "event_type": "moment",
            "payload": {"salience": 0.9, "intent_family": "x"},
        }
    ]
    chapters = extract_chapters(events, vod_start_s=0.0)
    # 5s offset is < 10s spacing → dropped, only the opener remains
    assert len(chapters) == 1


def test_events_before_vod_start_dropped():
    events = [
        {
            "ts": 50.0,
            "event_type": "moment",
            "payload": {"salience": 0.9, "intent_family": "x"},
        }
    ]
    chapters = extract_chapters(events, vod_start_s=100.0)
    assert len(chapters) == 1  # only the opener


def test_chapter_marker_holds_label_and_offset():
    marker = ChapterMarker(timestamp_s=120, label="Beat change")
    assert marker.timestamp_s == 120
    assert marker.label == "Beat change"
