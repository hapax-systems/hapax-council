"""Tests for the materializer's per-beat orchestration.

``materialize_beat`` is the executor: it resolves a beat's declared needs,
recruits + dispatches compositional effects through the live Via, gates + cues
media, and derives layout-pressure intents so the runner stops refusing — once
per beat (the loop-runaway guard). All side-effect collaborators are injected.
"""

from __future__ import annotations

from types import SimpleNamespace

from agents.studio_compositor.media_egress_gate import (
    MediaEgressDecision,
    MediaEgressOutcome,
)
from agents.studio_compositor.segment_action_materializer import (
    MaterializedAction,
    SegmentActionMaterializer,
)


def _allow_gate(object_ref: str, media_kind: str) -> MediaEgressDecision:
    return MediaEgressDecision(
        outcome=MediaEgressOutcome.ALLOWED,
        reason="ok",
        media_ref=object_ref,
        media_kind=media_kind,
    )


def _refuse_gate(object_ref: str, media_kind: str) -> MediaEgressDecision:
    return MediaEgressDecision(
        outcome=MediaEgressOutcome.REFUSED_CONSENT,
        reason="no",
        media_ref=None,
        media_kind=media_kind,
    )


def _materializer(*, dispatch, cue_media, media_gate, select=None):
    return SegmentActionMaterializer(
        select=select
        or (
            lambda imp, *, top_k=10, context=None: [
                SimpleNamespace(capability_name="ward.highlight.x.glow", combined=0.8)
            ]
        ),
        is_compositional=lambda name: True,
        dispatch=dispatch,
        cue_media=cue_media,
        media_gate=media_gate,
        clock=lambda: 1000.0,
    )


def test_abstract_need_recruits_and_dispatches_effect() -> None:
    dispatched: list[MaterializedAction] = []
    mat = _materializer(
        dispatch=lambda action: dispatched.append(action) or True,
        cue_media=lambda ref, kind: True,
        media_gate=_allow_gate,
    )
    doc = {
        "programme_id": "p1",
        "current_beat_index": 0,
        "source_affordance_kinds": ["source_card"],
        "source_refs": ["packet:x"],
    }

    receipt = mat.materialize_beat(doc)

    assert [a.capability for a in receipt.recruited] == ["ward.highlight.x.glow"]
    assert [a.capability for a in dispatched] == ["ward.highlight.x.glow"]


def test_youtube_media_need_is_gated_then_cued() -> None:
    cues: list[tuple[str, str]] = []
    mat = _materializer(
        dispatch=lambda action: True,
        cue_media=lambda ref, kind: cues.append((ref, kind)) or True,
        media_gate=_allow_gate,
    )
    doc = {"programme_id": "p1", "current_beat_index": 0}
    assets = [{"kind": "youtube", "url": "https://youtu.be/zzz", "caption": "clip"}]

    receipt = mat.materialize_beat(doc, assets=assets)

    assert len(receipt.media) == 1
    move = receipt.media[0]
    assert move.media_kind == "youtube"
    assert move.outcome == MediaEgressOutcome.ALLOWED.value
    assert move.cued is True
    assert cues == [("object:yt:zzz", "youtube")]


def test_refused_media_is_not_cued() -> None:
    cues: list[tuple[str, str]] = []
    mat = _materializer(
        dispatch=lambda action: True,
        cue_media=lambda ref, kind: cues.append((ref, kind)) or True,
        media_gate=_refuse_gate,
    )
    doc = {"programme_id": "p1", "current_beat_index": 0}
    assets = [{"kind": "youtube", "url": "https://youtu.be/zzz"}]

    receipt = mat.materialize_beat(doc, assets=assets)

    assert receipt.media[0].cued is False
    assert receipt.media[0].outcome == MediaEgressOutcome.REFUSED_CONSENT.value
    assert cues == []


def test_layout_intents_are_derived_so_runner_stops_refusing() -> None:
    mat = _materializer(
        dispatch=lambda action: True,
        cue_media=lambda ref, kind: True,
        media_gate=_allow_gate,
    )
    doc = {
        "programme_id": "p1",
        "current_beat_index": 3,
        "source_affordance_kinds": ["ranked_list_visible"],
        "source_refs": ["packet:x"],
    }

    receipt = mat.materialize_beat(doc)

    assert len(receipt.layout_intents) == 1
    assert receipt.layout_intents[0].kind == "show_ranked_list"


def test_loop_guard_does_not_rematerialize_same_beat() -> None:
    dispatch_calls: list[MaterializedAction] = []
    cue_calls: list[tuple[str, str]] = []
    mat = _materializer(
        dispatch=lambda action: dispatch_calls.append(action) or True,
        cue_media=lambda ref, kind: cue_calls.append((ref, kind)) or True,
        media_gate=_allow_gate,
    )
    doc = {
        "programme_id": "p1",
        "current_beat_index": 0,
        "source_affordance_kinds": ["source_card"],
        "source_refs": ["packet:x"],
    }
    assets = [{"kind": "youtube", "url": "https://youtu.be/zzz"}]

    first = mat.materialize_beat(doc, assets=assets)
    second = mat.materialize_beat(doc, assets=assets)

    assert first.reused is False
    assert second.reused is True
    # No re-dispatch / re-cue on the second tick of the same beat.
    assert len(dispatch_calls) == 1
    assert len(cue_calls) == 1


def test_new_beat_rematerializes() -> None:
    dispatch_calls: list[MaterializedAction] = []
    mat = _materializer(
        dispatch=lambda action: dispatch_calls.append(action) or True,
        cue_media=lambda ref, kind: True,
        media_gate=_allow_gate,
    )
    base = {"source_affordance_kinds": ["source_card"], "source_refs": ["packet:x"]}

    mat.materialize_beat({**base, "programme_id": "p1", "current_beat_index": 0})
    mat.materialize_beat({**base, "programme_id": "p1", "current_beat_index": 1})

    assert len(dispatch_calls) == 2
