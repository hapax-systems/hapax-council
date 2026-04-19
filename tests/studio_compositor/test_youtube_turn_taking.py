"""Tests for the YouTube turn-taking gate (HOMAGE Phase D2).

The gate reads director-intent.jsonl and answers whether the director has
nominated YouTube content. Default is fail-closed (``enabled=False``) — only
a director-emitted ``intent_family=youtube.direction`` impingement within
the tail window flips it on.

Covers:

- No JSONL present → disabled, reason=jsonl-missing
- Empty JSONL → disabled, reason=read-error
- No youtube.direction records → disabled, reason=no-nomination
- Fresh youtube.direction record → enabled, reason=director-nominated
- Stale youtube.direction record (outside tail window) → disabled
- youtube.direction with cut-away cue in narrative → disabled, reason=cut-away
- Newest nomination wins (mixed ordering)
- Non-youtube intent_family (camera.hero etc.) → ignored
- Malformed lines skipped silently
- active_slot propagated from caller
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agents.studio_compositor.youtube_turn_taking import (
    DEFAULT_TAIL_WINDOW_S,
    YOUTUBE_DIRECTION_FAMILY,
    YouTubeGateState,
    read_gate_state,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Helper — write a list of dict records as a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) + "\n" for r in records]
    path.write_text("".join(lines), encoding="utf-8")


def _record(
    *,
    emitted_at: float,
    intent_family: str = YOUTUBE_DIRECTION_FAMILY,
    narrative: str = "shift focus to the YouTube slot",
) -> dict:
    """Minimal director-intent record with a single impingement."""
    return {
        "activity": "react",
        "stance": "NOMINAL",
        "narrative_text": "looking at the video",
        "emitted_at": emitted_at,
        "condition_id": "test",
        "compositional_impingements": [
            {
                "narrative": narrative,
                "intent_family": intent_family,
                "material": "water",
                "salience": 0.7,
                "dimensions": {},
                "grounding_provenance": [],
            }
        ],
    }


# ── Missing / empty / malformed inputs ─────────────────────────────────────


def test_missing_jsonl_disables_gate(tmp_path: Path) -> None:
    missing = tmp_path / "never-existed.jsonl"
    state = read_gate_state(jsonl_path=missing, now=1000.0)
    assert state.enabled is False
    assert state.reason == "jsonl-missing"
    assert state.last_nomination_ts is None


def test_empty_jsonl_disables_gate(tmp_path: Path) -> None:
    path = tmp_path / "director-intent.jsonl"
    path.touch()
    state = read_gate_state(jsonl_path=path, now=1000.0)
    assert state.enabled is False
    # Empty file reads zero lines → read-error branch per the module docs.
    assert state.reason == "read-error"


def test_malformed_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "director-intent.jsonl"
    # Two malformed lines and one valid fresh nomination.
    malformed_a = "not json at all\n"
    malformed_b = '{"incomplete": '  # truncated
    valid_rec = _record(emitted_at=1000.0)
    path.write_text(
        malformed_a + malformed_b + "\n" + json.dumps(valid_rec) + "\n",
        encoding="utf-8",
    )
    state = read_gate_state(jsonl_path=path, now=1000.5)
    assert state.enabled is True
    assert state.reason == "director-nominated"


# ── Nomination presence / absence ──────────────────────────────────────────


def test_no_youtube_direction_records_disables(tmp_path: Path) -> None:
    path = tmp_path / "director-intent.jsonl"
    _write_jsonl(
        path,
        [
            _record(emitted_at=1000.0, intent_family="camera.hero"),
            _record(emitted_at=1001.0, intent_family="preset.bias"),
        ],
    )
    state = read_gate_state(jsonl_path=path, now=1002.0)
    assert state.enabled is False
    assert state.reason == "no-nomination"
    assert state.last_nomination_ts is None


def test_fresh_youtube_direction_enables_gate(tmp_path: Path) -> None:
    path = tmp_path / "director-intent.jsonl"
    _write_jsonl(path, [_record(emitted_at=1000.0)])
    state = read_gate_state(jsonl_path=path, now=1001.0)
    assert state.enabled is True
    assert state.reason == "director-nominated"
    assert state.last_nomination_ts == pytest.approx(1000.0)


def test_stale_nomination_disables(tmp_path: Path) -> None:
    path = tmp_path / "director-intent.jsonl"
    _write_jsonl(path, [_record(emitted_at=1000.0)])
    # ``now`` is well past the tail window — default 90 s.
    state = read_gate_state(
        jsonl_path=path,
        now=1000.0 + DEFAULT_TAIL_WINDOW_S + 10.0,
    )
    assert state.enabled is False
    assert state.reason == "no-nomination"
    assert state.last_nomination_ts == pytest.approx(1000.0)


# ── Cut-away handling ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "narrative",
    [
        "cut away from the video",
        "directing a cut-away to the operator",
        "away from YouTube now",
        "time to pull away from the video entirely",
    ],
)
def test_cut_away_narrative_disables(tmp_path: Path, narrative: str) -> None:
    path = tmp_path / "director-intent.jsonl"
    _write_jsonl(path, [_record(emitted_at=1000.0, narrative=narrative)])
    state = read_gate_state(jsonl_path=path, now=1001.0)
    assert state.enabled is False
    assert state.reason == "cut-away"
    assert state.last_nomination_ts == pytest.approx(1000.0)


def test_non_cut_away_narrative_enables(tmp_path: Path) -> None:
    path = tmp_path / "director-intent.jsonl"
    _write_jsonl(
        path,
        [
            _record(
                emitted_at=1000.0,
                narrative="amplify the video slot and focus attention there",
            )
        ],
    )
    state = read_gate_state(jsonl_path=path, now=1001.0)
    assert state.enabled is True
    assert state.reason == "director-nominated"


# ── Ordering ───────────────────────────────────────────────────────────────


def test_newest_nomination_wins_over_older_cut_away(tmp_path: Path) -> None:
    """Older cut-away followed by newer cut-to → enabled."""
    path = tmp_path / "director-intent.jsonl"
    _write_jsonl(
        path,
        [
            _record(emitted_at=1000.0, narrative="cut away from the video"),
            _record(emitted_at=1001.0, narrative="bring the YouTube slot forward"),
        ],
    )
    state = read_gate_state(jsonl_path=path, now=1002.0)
    assert state.enabled is True
    assert state.reason == "director-nominated"
    assert state.last_nomination_ts == pytest.approx(1001.0)


def test_newest_cut_away_wins_over_older_nomination(tmp_path: Path) -> None:
    """Older nomination followed by newer cut-away → disabled."""
    path = tmp_path / "director-intent.jsonl"
    _write_jsonl(
        path,
        [
            _record(emitted_at=1000.0, narrative="bring the YouTube slot forward"),
            _record(emitted_at=1001.0, narrative="cut away from the video"),
        ],
    )
    state = read_gate_state(jsonl_path=path, now=1002.0)
    assert state.enabled is False
    assert state.reason == "cut-away"
    assert state.last_nomination_ts == pytest.approx(1001.0)


def test_intervening_non_youtube_records_do_not_steal(tmp_path: Path) -> None:
    """A fresh youtube.direction beats intervening camera.hero records."""
    path = tmp_path / "director-intent.jsonl"
    _write_jsonl(
        path,
        [
            _record(emitted_at=1000.0),  # youtube.direction
            _record(emitted_at=1001.0, intent_family="camera.hero"),
            _record(emitted_at=1002.0, intent_family="preset.bias"),
        ],
    )
    state = read_gate_state(jsonl_path=path, now=1003.0)
    # The most recent youtube.direction is at 1000.0, still within window.
    assert state.enabled is True
    assert state.reason == "director-nominated"
    assert state.last_nomination_ts == pytest.approx(1000.0)


# ── Advisory active_slot propagation ───────────────────────────────────────


def test_active_slot_passthrough(tmp_path: Path) -> None:
    path = tmp_path / "director-intent.jsonl"
    _write_jsonl(path, [_record(emitted_at=1000.0)])
    state = read_gate_state(jsonl_path=path, now=1001.0, active_slot=2)
    assert state.enabled is True
    assert state.active_slot == 2


def test_active_slot_retained_when_disabled(tmp_path: Path) -> None:
    path = tmp_path / "director-intent.jsonl"
    _write_jsonl(path, [_record(emitted_at=1000.0, intent_family="camera.hero")])
    state = read_gate_state(jsonl_path=path, now=1001.0, active_slot=1)
    assert state.enabled is False
    assert state.active_slot == 1


# ── Multi-impingement record ───────────────────────────────────────────────


def test_multi_impingement_youtube_direction_detected(tmp_path: Path) -> None:
    """A record with multiple impingements is still counted if one is YT."""
    path = tmp_path / "director-intent.jsonl"
    record = {
        "activity": "react",
        "stance": "NOMINAL",
        "narrative_text": "layered move",
        "emitted_at": 1000.0,
        "condition_id": "test",
        "compositional_impingements": [
            {
                "narrative": "hero the turntable camera",
                "intent_family": "camera.hero",
                "material": "earth",
                "salience": 0.6,
                "dimensions": {},
                "grounding_provenance": [],
            },
            {
                "narrative": "surface the video slot",
                "intent_family": YOUTUBE_DIRECTION_FAMILY,
                "material": "water",
                "salience": 0.7,
                "dimensions": {},
                "grounding_provenance": [],
            },
        ],
    }
    _write_jsonl(path, [record])
    state = read_gate_state(jsonl_path=path, now=1001.0)
    assert state.enabled is True
    assert state.reason == "director-nominated"


# ── Dataclass invariants ───────────────────────────────────────────────────


def test_youtube_gate_state_is_immutable() -> None:
    state = YouTubeGateState(enabled=True)
    with pytest.raises((AttributeError, TypeError)):
        state.enabled = False  # type: ignore[misc]


def test_default_state_shape() -> None:
    state = YouTubeGateState(enabled=False)
    assert state.enabled is False
    assert state.active_slot == 0
    assert state.reason == "no-nomination"
    assert state.last_nomination_ts is None


def test_real_time_clock_branch_smoke(tmp_path: Path) -> None:
    """Exercise the now=None branch (uses time.time())."""
    path = tmp_path / "director-intent.jsonl"
    _write_jsonl(path, [_record(emitted_at=time.time())])
    state = read_gate_state(jsonl_path=path)
    assert state.enabled is True
    assert state.reason == "director-nominated"
