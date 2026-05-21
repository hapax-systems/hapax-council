"""Tests for the react and watch-along media reference adapter."""

from __future__ import annotations

from shared.react_watchalong_adapter import (
    FormatKind,
    MediaReference,
    ReferenceMode,
    build_render_plan,
    check_prohibited_source,
)
from shared.rights_safe_media_reference_gate import Decision


def _make_ref(**overrides) -> MediaReference:
    defaults = dict(
        upstream_id="https://example.com/video/123",
        upstream_title="Example Video",
        upstream_creator="Example Creator",
        upstream_total_seconds=600.0,
        source_type="platform_embed",
        proposed_mode=ReferenceMode.METADATA_FIRST,
        rights_class="unknown",
    )
    defaults.update(overrides)
    return MediaReference(**defaults)


def test_metadata_first_mode_shows_no_av() -> None:
    plan = build_render_plan(FormatKind.REACT, [_make_ref()])
    assert len(plan.references) == 1
    ref = plan.references[0]
    assert ref.show_timer is True
    assert ref.show_source_link is True
    assert ref.show_commentary is True
    assert ref.show_claim_trail is True


def test_prohibited_source_produces_refusal() -> None:
    ref = _make_ref(source_type="stream_rip")
    refusal = check_prohibited_source(ref)
    assert refusal is not None
    assert "stream_rip" in refusal.reason


def test_prohibited_sources_excluded_from_render_plan() -> None:
    refs = [
        _make_ref(
            upstream_id="good", source_type="platform_embed", rights_class="explicit_license"
        ),
        _make_ref(upstream_id="bad", source_type="raw_commercial_music"),
    ]
    plan = build_render_plan(FormatKind.COMMENTARY, refs)
    assert len(plan.references) == 1
    assert plan.references[0].upstream_id == "good"
    prohibited_refusals = [r for r in plan.refusals if "prohibited" in r.reason]
    assert len(prohibited_refusals) == 1
    assert "raw_commercial_music" in prohibited_refusals[0].reason


def test_all_prohibited_sources_are_refused() -> None:
    from shared.react_watchalong_adapter import PROHIBITED_SOURCES

    for source_type in PROHIBITED_SOURCES:
        ref = _make_ref(source_type=source_type)
        refusal = check_prohibited_source(ref)
        assert refusal is not None, f"{source_type} should be prohibited"


def test_unknown_rights_refuses_excerpt_mode() -> None:
    ref = _make_ref(
        proposed_mode=ReferenceMode.EXCERPT,
        excerpt_seconds=30.0,
        commentary_seconds=60.0,
        rights_class="unknown",
    )
    plan = build_render_plan(FormatKind.REACT, [ref])
    assert len(plan.references) == 1
    resolved = plan.references[0]
    assert resolved.gate_decision == Decision.REFUSE
    assert resolved.show_refusal_state is True
    assert resolved.refusal_artifact is not None


def test_link_along_passes_gate() -> None:
    ref = _make_ref(
        proposed_mode=ReferenceMode.LINK_ALONG,
        rights_class="explicit_license",
    )
    plan = build_render_plan(FormatKind.WATCH_ALONG, [ref])
    assert len(plan.references) == 1
    resolved = plan.references[0]
    assert resolved.effective_mode == ReferenceMode.LINK_ALONG
    assert resolved.show_source_link is True


def test_explicit_license_excerpt_allowed() -> None:
    ref = _make_ref(
        proposed_mode=ReferenceMode.EXCERPT,
        excerpt_seconds=30.0,
        commentary_seconds=60.0,
        upstream_total_seconds=600.0,
        rights_class="explicit_license",
        transformation_evidence="Voice commentary overlay with comparative analysis",
        non_substitution_rationale="Review covers 5% of runtime with critical analysis",
    )
    plan = build_render_plan(FormatKind.REVIEW, [ref])
    assert len(plan.references) == 1
    resolved = plan.references[0]
    assert resolved.gate_decision == Decision.ALLOW
    assert resolved.effective_mode == ReferenceMode.EXCERPT
    assert resolved.refusal_artifact is None


def test_render_plan_covers_all_format_kinds() -> None:
    for kind in FormatKind:
        plan = build_render_plan(kind, [_make_ref()])
        assert plan.format_kind == kind


def test_kill_switch_refuses_regardless() -> None:
    ref = _make_ref(
        proposed_mode=ReferenceMode.EXCERPT,
        excerpt_seconds=10.0,
        commentary_seconds=60.0,
        rights_class="explicit_license",
        live_rights_kill_switch_active=True,
    )
    plan = build_render_plan(FormatKind.REACT, [ref])
    resolved = plan.references[0]
    assert resolved.gate_decision == Decision.REFUSE
    assert resolved.show_refusal_state is True
