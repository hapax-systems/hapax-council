"""Tests for the operator predictive dossier productization contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.operator_predictive_dossier_contract import (
    DossierRow,
    EvidenceRef,
    Governance,
    OperatorPredictiveDossier,
    Prediction,
    ProductSpec,
    RowContext,
    SemanticRecruitment,
    ValueBraid,
    detect_evidence_ref_leaks,
    empty_dossier,
    render_dossier_for_prompt,
    render_row_for_prompt,
)

NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)


def _make_row(
    *,
    id: str = "test-row",
    status: str = "active",
    statement: str = "operator prefers terse responses",
    implication: str = "default to terse",
    negative_constraint: str = "do not omit required citations",
    embedded_description: str = "operator preference for terse responses",
    privacy_label: str = "private",
    mode_ceiling: str = "private",
    claim_authority: str = "provisional",
    evidence_refs: tuple = (),
) -> DossierRow:
    if not evidence_refs:
        evidence_refs = (
            EvidenceRef(
                path="/operator/profile.md",
                source_class="governed_authored",
                observed_at=NOW,
                excerpt_pointer="line:42",
            ),
        )
    return DossierRow(
        id=id,
        status=status,  # type: ignore[arg-type]
        verticals=("research",),
        operator_dimensions=("work_patterns",),
        context=RowContext(condition="operator is in R&D mode"),
        prediction=Prediction(
            outcome_kind="preference",
            statement=statement,
            temporal_band="strategic",
            probability=0.8,
            confidence=0.7,
            uncertainty_reason="low_support",
        ),
        evidence_refs=evidence_refs,
        freshness_half_life_days=14.0,
        authority="operator_declared",
        product_spec=ProductSpec(
            implication=implication,
            acceptance_signal="operator does not ask for shorter response",
            negative_constraint=negative_constraint,
        ),
        value_braid=ValueBraid(
            engagement=8,
            monetary=5,
            research=8,
            tree_effect=7,
            evidence_confidence=7,
            risk_penalty=1.0,
            mode_ceiling=mode_ceiling,  # type: ignore[arg-type]
        ),
        semantic_recruitment=SemanticRecruitment(
            dossier_row_recruitable=False,
            embedded_description=embedded_description,
        ),
        governance=Governance(
            consent_label="operator_only",
            privacy_label=privacy_label,  # type: ignore[arg-type]
            claim_authority=claim_authority,  # type: ignore[arg-type]
        ),
    )


def test_minimal_valid_row_constructs() -> None:
    row = _make_row()
    assert row.id == "test-row"
    assert row.status == "active"


def test_row_status_other_than_active_skips_evidence_sufficiency_validation() -> None:
    """Spec: only 'active' rows are claim-affecting and require sufficient evidence."""

    # A blocked row with NO tier-1 source and only 1 ref should still construct.
    row = _make_row(
        status="blocked",
        evidence_refs=(
            EvidenceRef(
                path="/some/path.md",
                source_class="derivative_summary",
                observed_at=NOW,
                excerpt_pointer="line:1",
            ),
        ),
    )
    assert row.status == "blocked"


def test_active_row_without_tier1_or_2_independent_sources_fails_construction() -> None:
    with pytest.raises(ValueError, match="independent or 1 Tier-1"):
        _make_row(
            status="active",
            evidence_refs=(
                EvidenceRef(
                    path="/some/path.md",
                    source_class="derivative_summary",
                    observed_at=NOW,
                    excerpt_pointer="line:1",
                ),
            ),
        )


def test_active_row_with_two_independent_non_tier1_sources_constructs() -> None:
    row = _make_row(
        status="active",
        evidence_refs=(
            EvidenceRef(
                path="/source/a.md",
                source_class="derivative_summary",
                observed_at=NOW,
                excerpt_pointer="line:1",
            ),
            EvidenceRef(
                path="/source/b.md",
                source_class="derivative_summary",
                observed_at=NOW,
                excerpt_pointer="line:2",
            ),
        ),
    )
    assert len(row.evidence_refs) == 2


def test_private_ceiling_with_assertable_authority_fails() -> None:
    with pytest.raises(ValueError, match="claim_authority"):
        _make_row(
            mode_ceiling="private",
            claim_authority="assertable",
        )


def test_private_ceiling_with_grounding_act_authority_fails() -> None:
    with pytest.raises(ValueError, match="claim_authority"):
        _make_row(
            mode_ceiling="private",
            claim_authority="grounding_act",
        )


def test_renderer_admits_clean_private_row_at_private_ceiling() -> None:
    row = _make_row()
    rendering = render_row_for_prompt(row, requested_ceiling="private")
    assert not rendering.refused
    assert "operator prefers terse responses" in rendering.summary
    assert "default to terse" in rendering.summary
    assert "do not omit required citations" in rendering.summary


def test_renderer_refuses_when_ceiling_below_requested() -> None:
    """Row at private ceiling cannot render for public_live consumer."""

    row = _make_row(mode_ceiling="private")
    rendering = render_row_for_prompt(row, requested_ceiling="public_live")
    assert rendering.refused
    assert any("mode_ceiling" in r for r in rendering.refusal_reasons)


def test_renderer_refuses_raw_transcript_in_statement() -> None:
    row = _make_row(statement="user: what is the operator's preference?  assistant: terse")
    rendering = render_row_for_prompt(row, requested_ceiling="private")
    assert rendering.refused
    assert any(f.leak_kind == "raw_transcript" for f in rendering.leak_findings)


def test_renderer_refuses_secret_in_implication() -> None:
    row = _make_row(implication="set OPENAI_API_KEY=sk-abc1234567890ABCDEFGHIJK0123456789")
    rendering = render_row_for_prompt(row, requested_ceiling="private")
    assert rendering.refused
    assert any(f.leak_kind == "secret" for f in rendering.leak_findings)


def test_renderer_refuses_biometric_in_negative_constraint() -> None:
    row = _make_row(negative_constraint="do not infer mood from heart_rate_bpm: 88")
    rendering = render_row_for_prompt(row, requested_ceiling="private")
    assert rendering.refused
    assert any(f.leak_kind == "biometric" for f in rendering.leak_findings)


def test_renderer_refuses_browser_store_in_embedded_description() -> None:
    row = _make_row(
        embedded_description="see operator history at Login Data store under chrome",
    )
    rendering = render_row_for_prompt(row, requested_ceiling="private")
    assert rendering.refused
    assert any(f.leak_kind == "browser_store" for f in rendering.leak_findings)


def test_renderer_refuses_side_chat_in_implication() -> None:
    row = _make_row(implication="surface the DM thread context for Slack")
    rendering = render_row_for_prompt(row, requested_ceiling="private")
    assert rendering.refused
    assert any(f.leak_kind == "side_chat" for f in rendering.leak_findings)


def test_renderer_refuses_non_operator_person_name() -> None:
    row = _make_row(statement="operator should defer to Jason on this branch")
    rendering = render_row_for_prompt(
        row,
        requested_ceiling="private",
        non_operator_person_names=("Jason",),
    )
    assert rendering.refused
    assert any(f.leak_kind == "non_operator_person" for f in rendering.leak_findings)


def test_renderer_refuses_stale_row() -> None:
    row = _make_row(status="stale")
    rendering = render_row_for_prompt(row, requested_ceiling="private")
    assert rendering.refused


def test_volatile_sensitive_evidence_with_long_excerpt_flagged() -> None:
    long_excerpt = "user: long inline transcript " + ("blah " * 30)
    row = _make_row(
        evidence_refs=(
            EvidenceRef(
                path="/operator/profile.md",
                source_class="governed_authored",
                observed_at=NOW,
                excerpt_pointer="line:42",
            ),
            EvidenceRef(
                path="/private/transcript.md",
                source_class="volatile_sensitive",
                observed_at=NOW,
                excerpt_pointer=long_excerpt,
            ),
        ),
    )
    findings = detect_evidence_ref_leaks(row)
    assert len(findings) == 1
    assert findings[0].leak_kind == "raw_transcript"


def test_dossier_render_filters_by_vertical() -> None:
    research_row = _make_row(id="research-row")
    dossier = OperatorPredictiveDossier(
        generated_at=NOW,
        rows=(research_row,),
    )
    research_renders = render_dossier_for_prompt(
        dossier,
        requested_ceiling="private",
        verticals=("research",),
    )
    assert len(research_renders) == 1

    studio_renders = render_dossier_for_prompt(
        dossier,
        requested_ceiling="private",
        verticals=("studio",),
    )
    assert len(studio_renders) == 0


def test_empty_dossier_factory() -> None:
    dossier = empty_dossier()
    assert dossier.subject == "operator"
    assert dossier.schema_version == 1
    assert dossier.rows == ()
    assert dossier.active_rows() == ()


def test_dossier_query_helpers() -> None:
    row = _make_row()
    dossier = OperatorPredictiveDossier(generated_at=NOW, rows=(row,))
    assert dossier.by_id() == {"test-row": row}
    assert dossier.active_rows() == (row,)
    assert dossier.for_vertical("research") == (row,)
    assert dossier.for_vertical("studio") == ()
    assert dossier.for_operator_dimension("work_patterns") == (row,)
    assert dossier.for_operator_dimension("identity") == ()


def test_anti_overclaim_value_braid_score_does_not_unlock_authority() -> None:
    """Even with a perfect 10/10 value-braid score, a private-ceiling row
    cannot acquire grounding_act authority (the spec's anti-overclaim
    invariant). Validation must reject the construction."""

    with pytest.raises(ValueError):
        _make_row(
            mode_ceiling="private",
            claim_authority="grounding_act",
        )


def test_render_summary_carries_uncertainty_reason() -> None:
    """The renderer surfaces uncertainty_reason so prompt consumers can
    see calibration discipline rather than just probability."""

    row = _make_row()
    rendering = render_row_for_prompt(row, requested_ceiling="private")
    assert "uncertainty=low_support" in rendering.summary
