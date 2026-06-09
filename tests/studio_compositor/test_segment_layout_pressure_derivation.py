"""Declared needs derive bounded layout-pressure intents for the runner.

This is what stops ``DirectorSegmentRunner`` refusing with ``no_layout_needs``
when a segment declares needs but authored no ``current_beat_layout_intents``.
It reuses the EXISTING bounded normalisers (the contract's
``_layout_need_for_action_intent`` for authored action kinds + the runner's
``_proposal_needs_to_intents`` parser) — it does NOT introduce a new
need->layout table. Needs that are effects/media (not layout postures) and
needs without evidence simply produce no posture pressure.
"""

from __future__ import annotations

from agents.studio_compositor.segment_action_materializer import (
    derive_layout_pressure_intents,
)


def test_supported_source_affordance_kind_becomes_layout_intent() -> None:
    doc = {
        "programme_id": "prog-1",
        "current_beat_index": 2,
        "role": "tier_list",
        "source_affordance_kinds": ["ranked_list_visible", "source_card"],
        "source_refs": ["packet:prog-1:evidence"],
    }

    intents = derive_layout_pressure_intents(doc, now=1000.0)

    # ranked_list_visible normalises to the bounded RANKED_LIST need;
    # source_card is an effect/overlay need, not a layout posture -> dropped.
    assert len(intents) == 1
    assert intents[0].kind == "show_ranked_list"
    assert intents[0].programme_id == "prog-1"
    assert intents[0].beat_index == 2
    assert "packet:prog-1:evidence" in intents[0].evidence_refs


def test_authored_show_evidence_action_intent_becomes_layout_intent() -> None:
    doc = {
        "programme_id": "prog-1",
        "current_beat_index": 0,
        "current_beat_action_intents": [
            {
                "beat_index": 0,
                "intents": [{"kind": "show_evidence", "evidence_refs": ["artifact:card"]}],
            }
        ],
    }

    intents = derive_layout_pressure_intents(doc, now=1.0)

    # show_evidence -> contract EVIDENCE_VISIBLE -> runner ARTIFACT_DETAIL need.
    assert len(intents) == 1
    assert intents[0].kind == "show_artifact_detail"


def test_needs_without_evidence_produce_no_pressure() -> None:
    doc = {
        "programme_id": "prog-1",
        "current_beat_index": 0,
        "source_affordance_kinds": ["ranked_list_visible"],
        # no source_refs -> no evidence -> the runner parser drops it
    }

    assert derive_layout_pressure_intents(doc, now=1.0) == ()


def test_non_layout_needs_produce_no_pressure() -> None:
    doc = {
        "programme_id": "prog-1",
        "current_beat_index": 0,
        "source_affordance_kinds": ["claim_card", "media_locator"],
        "source_refs": ["packet:x"],
    }

    assert derive_layout_pressure_intents(doc, now=1.0) == ()
