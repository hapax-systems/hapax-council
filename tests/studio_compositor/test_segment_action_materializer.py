"""Tests for the segment director action materializer.

The materializer turns a segment beat's *declared directorial needs* into
recruited *surface actions* by building an impingement per need and asking
``AffordancePipeline.select()`` to score it against the live affordance
catalogue. The make-or-break invariant: the recruited capability comes from
scoring, NOT from a ``if need == X: show_card`` lookup table. These tests pin
that invariant by injecting the recruiter and proving the same need recruits
whatever ``select`` returns.
"""

from __future__ import annotations

from types import SimpleNamespace

from agents.studio_compositor.segment_action_materializer import (
    DeclaredNeed,
    SegmentActionMaterializer,
)


def _candidate(name: str, combined: float) -> SimpleNamespace:
    """Duck-typed SelectionCandidate (``.capability_name`` + ``.combined``)."""

    return SimpleNamespace(capability_name=name, combined=combined)


def test_declared_need_recruits_capability_returned_by_select() -> None:
    captured: dict[str, object] = {}

    def fake_select(impingement, *, top_k=10, context=None):
        captured["impingement"] = impingement
        return [_candidate("overlay.foreground.coding-activity", 0.71)]

    materializer = SegmentActionMaterializer(
        select=fake_select,
        is_compositional=lambda name: True,
        clock=lambda: 1000.0,
    )
    need = DeclaredNeed(
        need_kind="source_card",
        beat_text="ranking these five candidates against the operator criteria",
        role="tier_list",
        evidence_refs=("prepared_artifact:abc",),
    )

    action = materializer.recruit_for_need(need)

    assert action is not None
    # The capability is whatever select() recruited — never derived from need_kind.
    assert action.capability == "overlay.foreground.coding-activity"
    assert action.score == 0.71
    assert action.need_kind == "source_card"
    # The impingement that drove recruitment carries a narrative built from the
    # need semantics + beat text, and does NOT pre-name a capability.
    imp = captured["impingement"]
    narrative = imp.content["narrative"]
    assert "source card" in narrative.lower()
    assert "candidates against the operator criteria" in narrative.lower()
    assert "overlay.foreground.coding-activity" not in narrative
    assert need.evidence_refs[0] in imp.content.get("evidence_refs", ())


def test_same_need_recruits_different_capability_under_different_select() -> None:
    """No need->capability table: the same need follows scoring, not a switch."""

    need = DeclaredNeed(need_kind="source_card", beat_text="cite the origin")

    mat_a = SegmentActionMaterializer(
        select=lambda imp, *, top_k=10, context=None: [
            _candidate("ward.highlight.source-panel.glow", 0.8)
        ],
        is_compositional=lambda name: True,
        clock=lambda: 1.0,
    )
    mat_b = SegmentActionMaterializer(
        select=lambda imp, *, top_k=10, context=None: [_candidate("gem.spawn.fresh-mural", 0.6)],
        is_compositional=lambda name: True,
        clock=lambda: 1.0,
    )

    action_a = mat_a.recruit_for_need(need)
    action_b = mat_b.recruit_for_need(need)

    assert action_a is not None and action_b is not None
    assert action_a.capability == "ward.highlight.source-panel.glow"
    assert action_b.capability == "gem.spawn.fresh-mural"


def test_recruitment_skips_non_compositional_candidates() -> None:
    """A higher-scoring non-director capability must not win a director slot."""

    def fake_select(impingement, *, top_k=10, context=None):
        return [
            _candidate("node.add.kaleidoscope", 0.95),  # reverie shader, not a director move
            _candidate("ward.highlight.tier-panel.glow", 0.55),
        ]

    materializer = SegmentActionMaterializer(
        select=fake_select,
        is_compositional=lambda name: name.startswith(("ward.", "overlay.", "gem.")),
        clock=lambda: 1.0,
    )

    action = materializer.recruit_for_need(DeclaredNeed(need_kind="tier_chart"))

    assert action is not None
    assert action.capability == "ward.highlight.tier-panel.glow"


def test_recruitment_returns_none_below_threshold() -> None:
    materializer = SegmentActionMaterializer(
        select=lambda imp, *, top_k=10, context=None: [_candidate("overlay.dim.all-chrome", 0.12)],
        is_compositional=lambda name: True,
        threshold=0.3,
        clock=lambda: 1.0,
    )

    assert materializer.recruit_for_need(DeclaredNeed(need_kind="source_card")) is None


def test_recruitment_returns_none_when_select_is_empty() -> None:
    materializer = SegmentActionMaterializer(
        select=lambda imp, *, top_k=10, context=None: [],
        is_compositional=lambda name: True,
        clock=lambda: 1.0,
    )

    assert materializer.recruit_for_need(DeclaredNeed(need_kind="media_locator")) is None
