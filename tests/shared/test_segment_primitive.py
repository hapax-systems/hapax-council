"""Plan A Phase A1 — Segment + Beat + SegmentPlan primitive regression pins."""

from __future__ import annotations

import time
from typing import Any

import pytest
from pydantic import ValidationError

from shared.segment import Beat, CadenceArchetype, Segment, SegmentPlan


def _make_beat(beat_id: str = "b1", **overrides: Any) -> Beat:
    defaults: dict[str, Any] = {
        "beat_id": beat_id,
        "narrative_goal": "Set up the thesis.",
        "verbal_script": "Guidance, not mandatory script.",
        "screen_directions_prior": {},
        "planned_duration_s": 20.0,
        "min_duration_s": 10.0,
        "max_duration_s": 40.0,
    }
    defaults.update(overrides)
    return Beat(**defaults)


def _make_segment(segment_id: str = "s1", **overrides: Any) -> Segment:
    defaults: dict[str, Any] = {
        "segment_id": segment_id,
        "parent_programme_id": "p1",
        "format": "explainer",
        "thesis": "Example thesis about grounding.",
        "beats": [_make_beat("b1"), _make_beat("b2")],
    }
    defaults.update(overrides)
    return Segment(**defaults)


# ── Beat ────────────────────────────────────────────────────────────────────


def test_beat_round_trip() -> None:
    b = _make_beat()
    b2 = Beat.model_validate(b.model_dump())
    assert b == b2


def test_beat_rejects_zero_bias_prior() -> None:
    with pytest.raises(ValidationError) as exc:
        Beat(
            beat_id="b1",
            narrative_goal="x",
            screen_directions_prior={"ward.highlight.gem": 0.0},
            planned_duration_s=10,
            min_duration_s=5,
            max_duration_s=20,
        )
    assert "strictly positive" in str(exc.value)


def test_beat_rejects_bias_above_cap() -> None:
    with pytest.raises(ValidationError) as exc:
        _make_beat(screen_directions_prior={"x": 6.0})
    assert "<= 5.0" in str(exc.value)


def test_beat_rejects_disordered_durations() -> None:
    with pytest.raises(ValidationError) as exc:
        Beat(
            beat_id="b1",
            narrative_goal="x",
            planned_duration_s=5.0,
            min_duration_s=10.0,
            max_duration_s=20.0,
        )
    assert "duration ordering" in str(exc.value)


def test_beat_accepts_known_cadence_archetypes() -> None:
    for arch in ("clinical_pause", "freeze_frame_reaction", "percussive_glitch"):
        b = _make_beat(cadence_archetype=arch)
        assert b.cadence_archetype == arch


def test_beat_rejects_unknown_cadence_archetype() -> None:
    with pytest.raises(ValidationError):
        _make_beat(cadence_archetype="magical_realism")


# ── Segment ─────────────────────────────────────────────────────────────────


def test_segment_requires_non_empty_beats() -> None:
    with pytest.raises(ValidationError):
        Segment(
            segment_id="s1",
            parent_programme_id="p1",
            format="explainer",
            thesis="x",
            beats=[],
        )


def test_segment_author_pinned_to_hapax() -> None:
    with pytest.raises(ValidationError):
        Segment(
            segment_id="s1",
            parent_programme_id="p1",
            segment_author="operator",
            format="explainer",
            thesis="x",
            beats=[_make_beat()],
        )


def test_segment_rejects_duplicate_beat_ids() -> None:
    with pytest.raises(ValidationError) as exc:
        Segment(
            segment_id="s1",
            parent_programme_id="p1",
            format="explainer",
            thesis="x",
            beats=[_make_beat("same"), _make_beat("same")],
        )
    assert "duplicate beat_id" in str(exc.value)


def test_segment_bias_positive_band() -> None:
    seg = _make_segment(capability_bias_positive={"ward.highlight.gem": 3.0})
    assert seg.capability_bias_positive["ward.highlight.gem"] == 3.0
    with pytest.raises(ValidationError):
        _make_segment(capability_bias_positive={"x": 0.5})
    with pytest.raises(ValidationError):
        _make_segment(capability_bias_positive={"x": 6.0})


def test_segment_bias_negative_band() -> None:
    seg = _make_segment(capability_bias_negative={"x": 0.25})
    assert seg.capability_bias_negative["x"] == 0.25
    with pytest.raises(ValidationError):
        _make_segment(capability_bias_negative={"x": 0.0})
    with pytest.raises(ValidationError):
        _make_segment(capability_bias_negative={"x": 1.5})


# ── SegmentPlan ─────────────────────────────────────────────────────────────


def test_segment_plan_round_trip() -> None:
    plan = SegmentPlan(
        programme_id="p1",
        show_id="show-1",
        planned_at=time.time(),
        segments=[_make_segment("s1"), _make_segment("s2")],
    )
    plan2 = SegmentPlan.model_validate(plan.model_dump())
    assert plan == plan2


def test_segment_plan_rejects_mismatched_programme_id() -> None:
    with pytest.raises(ValidationError) as exc:
        SegmentPlan(
            programme_id="p1",
            show_id="show-1",
            planned_at=time.time(),
            segments=[_make_segment("s1", parent_programme_id="p2")],
        )
    assert "parent_programme_id" in str(exc.value)


def test_segment_plan_rejects_duplicate_segment_ids() -> None:
    with pytest.raises(ValidationError) as exc:
        SegmentPlan(
            programme_id="p1",
            show_id="show-1",
            planned_at=time.time(),
            segments=[_make_segment("dup"), _make_segment("dup")],
        )
    assert "duplicate segment_id" in str(exc.value)


def test_segment_plan_author_pinned() -> None:
    with pytest.raises(ValidationError):
        SegmentPlan(
            programme_id="p1",
            show_id="show-1",
            planned_at=time.time(),
            plan_author="operator",
            segments=[_make_segment()],
        )


_ = CadenceArchetype
