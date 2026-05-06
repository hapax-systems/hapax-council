"""Tests for chronicle salience tagging on narration_triad emit paths.

Pairs with the m8/stimmung salience layers — closes the chronicle-ticker
ward's *no in-tree emitter sets salience* gap for the narration-triad
source. ``narration_triad`` is not in the ticker's source allow-list,
so without ``salience >= 0.7`` triad transitions never surface.
"""

from __future__ import annotations

from unittest import mock

import pytest


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        ("narration.triad.closed", 0.85),
        ("narration.triad.opened", 0.8),
        ("narration.triad.updated", 0.75),
    ],
)
def test_event_salience_floor(event_type: str, expected: float) -> None:
    from shared.narration_triad import _TRIAD_EVENT_SALIENCE

    assert _TRIAD_EVENT_SALIENCE[event_type] == expected
    # All variants must clear the chronicle-ticker floor (0.7) so they
    # surface independent of the source allow-list.
    assert _TRIAD_EVENT_SALIENCE[event_type] >= 0.7


def test_unknown_event_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_record_triad_chronicle_event`` resolves unknown event_types to 0.75 default."""
    from shared.narration_triad import _record_triad_chronicle_event

    captured: list = []

    def fake_record(event):  # type: ignore[no-untyped-def]
        captured.append(event)

    monkeypatch.setattr("shared.narration_triad.chronicle_record", fake_record)
    # Build a minimal envelope mock — only the fields the emitter reads.
    envelope = mock.MagicMock()
    envelope.status = "in_progress"  # Not in _CLOSED_STATUSES, not "open" → maps to "updated"
    envelope.updated_at = "2026-05-06T12:00:00Z"
    envelope.triad_id = "t-test"
    envelope.speech_event_id = "se-test"
    envelope.programme_id = "prog-test"
    envelope.source_path = "/tmp/test"

    _record_triad_chronicle_event(envelope)
    assert len(captured) == 1
    event = captured[0]
    assert event.event_type == "narration.triad.updated"
    assert event.payload["salience"] == 0.75


def test_closed_envelope_carries_higher_salience(monkeypatch: pytest.MonkeyPatch) -> None:
    """Closed-status envelopes get the highest salience floor."""
    from shared.narration_triad import _CLOSED_STATUSES, _record_triad_chronicle_event

    captured: list = []

    def fake_record(event):  # type: ignore[no-untyped-def]
        captured.append(event)

    monkeypatch.setattr("shared.narration_triad.chronicle_record", fake_record)
    envelope = mock.MagicMock()
    # Pick any status from the closed set; the helper maps all to "closed".
    envelope.status = next(iter(_CLOSED_STATUSES))
    envelope.updated_at = "2026-05-06T12:00:00Z"
    envelope.triad_id = "t-closed"
    envelope.speech_event_id = "se-closed"
    envelope.programme_id = "prog-closed"
    envelope.source_path = "/tmp/closed"

    _record_triad_chronicle_event(envelope)
    assert len(captured) == 1
    event = captured[0]
    assert event.event_type == "narration.triad.closed"
    assert event.payload["salience"] == 0.85
