"""Tests for shared.operator_dossier_value_braid_adapter."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.operator_dossier_value_braid_adapter import (
    DIVERGENCE_THRESHOLD,
    DossierBraidAdapterOutput,
    adapt_dossier_row,
)
from shared.operator_predictive_dossier_contract import (
    DossierRow,
    EvidenceRef,
    Governance,
    Prediction,
    ProductSpec,
    RowContext,
    SemanticRecruitment,
    ValueBraid,
)

NOW = datetime.now(UTC).isoformat()


def _make_row(
    *,
    probability: float = 0.8,
    confidence: float = 0.7,
    risk_penalty: float = 1.0,
    mode_ceiling: str = "private",
    hard_vetoes: tuple[str, ...] = (),
) -> DossierRow:
    return DossierRow(
        id="test-adapter-row",
        status="active",
        verticals=("research",),
        operator_dimensions=("work_patterns",),
        context=RowContext(condition="operator in R&D"),
        prediction=Prediction(
            outcome_kind="preference",
            statement="operator prefers concise responses",
            temporal_band="strategic",
            probability=probability,
            confidence=confidence,
            uncertainty_reason="low_support",
        ),
        evidence_refs=(
            EvidenceRef(
                path="/evidence/path.md",
                source_class="governed_authored",
                observed_at=NOW,
                excerpt_pointer="line:1",
            ),
        ),
        freshness_half_life_days=14.0,
        authority="operator_declared",
        product_spec=ProductSpec(
            implication="shorter responses save operator time",
            acceptance_signal="operator does not ask for shorter",
            negative_constraint="must not omit critical information",
        ),
        value_braid=ValueBraid(
            engagement=8,
            monetary=5,
            research=8,
            tree_effect=7,
            evidence_confidence=7,
            risk_penalty=risk_penalty,
            mode_ceiling=mode_ceiling,
            hard_vetoes=hard_vetoes,
        ),
        semantic_recruitment=SemanticRecruitment(
            dossier_row_recruitable=False,
            embedded_description="concise response preference",
        ),
        governance=Governance(
            consent_label="operator_only",
            privacy_label="private",
            claim_authority="provisional",
        ),
    )


def test_basic_adapter_output_structure() -> None:
    row = _make_row()
    output = adapt_dossier_row(row, base_wsjf=8.0)
    assert isinstance(output, DossierBraidAdapterOutput)
    assert output.selection_prior.task_id == "test-adapter-row"
    assert output.selection_prior.base_wsjf == 8.0
    assert output.operator_labor_risk.task_id == "test-adapter-row"
    assert output.confidence_mutations is None


def test_no_confidence_mutations_enforced() -> None:
    with pytest.raises(Exception):
        DossierBraidAdapterOutput(
            selection_prior=adapt_dossier_row(_make_row(), base_wsjf=5.0).selection_prior,
            operator_labor_risk=adapt_dossier_row(_make_row(), base_wsjf=5.0).operator_labor_risk,
            confidence_mutations="truth",
        )


def test_high_acceptance_boosts_wsjf() -> None:
    row = _make_row(probability=0.95, confidence=0.9)
    output = adapt_dossier_row(row, base_wsjf=10.0)
    assert output.selection_prior.dossier_adjusted_wsjf > 0


def test_high_risk_penalty_reduces_adjustment() -> None:
    low_risk = adapt_dossier_row(_make_row(risk_penalty=0.5), base_wsjf=10.0)
    high_risk = adapt_dossier_row(_make_row(risk_penalty=8.0), base_wsjf=10.0)
    assert high_risk.selection_prior.adjustment_factor < low_risk.selection_prior.adjustment_factor


def test_hard_vetoes_increase_labor_risk() -> None:
    no_veto = adapt_dossier_row(_make_row(hard_vetoes=()), base_wsjf=10.0)
    with_veto = adapt_dossier_row(_make_row(hard_vetoes=("legal_block",)), base_wsjf=10.0)
    assert with_veto.operator_labor_risk.risk_score > no_veto.operator_labor_risk.risk_score


def test_calibration_note_emitted_on_divergence() -> None:
    row = _make_row(risk_penalty=8.0, hard_vetoes=("block",))
    output = adapt_dossier_row(row, base_wsjf=10.0)
    assert output.calibration_note is not None
    assert output.calibration_note.divergence > DIVERGENCE_THRESHOLD


def test_no_calibration_note_when_within_threshold() -> None:
    row = _make_row(probability=0.8, confidence=0.7, risk_penalty=1.0)
    output = adapt_dossier_row(row, base_wsjf=10.0)
    if output.calibration_note is not None:
        assert output.calibration_note.divergence > DIVERGENCE_THRESHOLD


def test_zero_base_wsjf_no_calibration_note() -> None:
    output = adapt_dossier_row(_make_row(), base_wsjf=0.0)
    assert output.calibration_note is None


def test_private_ceiling_applies_discount() -> None:
    private = adapt_dossier_row(_make_row(mode_ceiling="private"), base_wsjf=10.0)
    dry_run = adapt_dossier_row(_make_row(mode_ceiling="dry_run"), base_wsjf=10.0)
    assert private.selection_prior.adjustment_factor < dry_run.selection_prior.adjustment_factor


def test_labor_risk_factors_populated() -> None:
    row = _make_row(risk_penalty=5.0, confidence=0.2, hard_vetoes=("legal",))
    output = adapt_dossier_row(row, base_wsjf=10.0)
    assert "high_risk_penalty" in output.operator_labor_risk.risk_factors
    assert "has_hard_vetoes" in output.operator_labor_risk.risk_factors
    assert "low_prediction_confidence" in output.operator_labor_risk.risk_factors
