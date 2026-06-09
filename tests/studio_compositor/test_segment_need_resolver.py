"""Tests for the unified declared-need resolver.

One resolver, keyed on programme_id + beat_index, reads BOTH the
active-segment.json declared needs/authored action intents AND the
segment-playback.json media assets into a single ordered tuple of
:class:`DeclaredNeed`. The two SHM writers stay separate; only the read side
is unified (the spec's "unify the resolver, keep the two writers").
"""

from __future__ import annotations

from agents.studio_compositor.segment_action_materializer import (
    DeclaredNeed,
    beat_key,
    declared_needs_from_segment,
)


def test_source_affordance_kinds_become_declared_needs() -> None:
    doc = {
        "programme_id": "prog-1",
        "current_beat_index": 2,
        "role": "tier_list",
        "narrative_beat": "rank the five candidates against operator criteria",
        "source_affordance_kinds": ["ranked_list_visible", "tier_chart", "source_card"],
        "source_refs": ["packet:prog-1:evidence"],
    }

    needs = declared_needs_from_segment(doc)

    kinds = [n.need_kind for n in needs]
    assert kinds == ["ranked_list_visible", "tier_chart", "source_card"]
    for need in needs:
        assert need.origin == "source_affordance_kind"
        assert need.role == "tier_list"
        assert "rank the five candidates" in need.beat_text
        assert need.evidence_refs == ("packet:prog-1:evidence",)
        assert need.media_kind is None


def test_authored_action_intents_become_declared_needs_skipping_narrate() -> None:
    doc = {
        "programme_id": "prog-1",
        "current_beat_index": 1,
        "role": "rant",
        "current_beat_action_intents": [
            {
                "beat_index": 1,
                "intents": [
                    {"kind": "narrate"},
                    {"kind": "show_evidence", "evidence_refs": ["artifact:claim-card"]},
                    {"kind": "cite_source", "evidence_refs": ["artifact:source"]},
                ],
            }
        ],
    }

    needs = declared_needs_from_segment(doc)

    assert [n.need_kind for n in needs] == ["show_evidence", "cite_source"]
    assert all(n.origin == "beat_action_intent" for n in needs)
    assert needs[0].evidence_refs == ("artifact:claim-card",)


def test_image_and_youtube_assets_become_media_needs() -> None:
    doc = {"programme_id": "prog-1", "current_beat_index": 0, "role": "react"}
    assets = [
        {"kind": "image", "url": "/srv/assets/diagram.png", "caption": "the architecture"},
        {"kind": "youtube", "url": "https://www.youtube.com/watch?v=abc123", "caption": "clip"},
        {"kind": "text", "caption": "ignore me"},
    ]

    needs = declared_needs_from_segment(doc, assets=assets)

    media = [n for n in needs if n.media_kind is not None]
    assert [n.media_kind for n in media] == ["image", "youtube"]
    image_need = media[0]
    assert image_need.origin == "asset"
    assert image_need.object_ref is not None and image_need.object_ref.startswith("object:image:")
    yt_need = media[1]
    assert yt_need.object_ref is not None and yt_need.object_ref.startswith("object:yt:")
    # No text/url asset leaks in as a media need.
    assert all(n.media_kind in {"image", "youtube"} for n in media)


def test_duplicate_needs_are_deduplicated() -> None:
    doc = {
        "programme_id": "prog-1",
        "current_beat_index": 0,
        "source_affordance_kinds": ["source_card", "source_card"],
    }

    needs = declared_needs_from_segment(doc)

    assert [n.need_kind for n in needs] == ["source_card"]


def test_beat_key_identifies_programme_and_beat() -> None:
    doc = {"programme_id": "prog-9", "current_beat_index": 4}
    assert beat_key(doc) == ("prog-9", 4)
    assert beat_key({"programme_id": "prog-9"}) == ("prog-9", None)
    assert beat_key({}) == (None, None)


def test_resolver_ignores_non_segment_document() -> None:
    assert declared_needs_from_segment({}) == ()
    assert declared_needs_from_segment({"programme_id": "x"}) == ()


def test_declared_need_is_hashable_value() -> None:
    a = DeclaredNeed(need_kind="source_card")
    b = DeclaredNeed(need_kind="source_card")
    assert a == b
