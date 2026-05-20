"""Operator dossier → value-braid selection prior adapter.

Maps private dossier prediction rows into value-braid selection priors
and operator-labor risk estimates. The adapter is private-mode only and
CANNOT modify truth, rights, privacy, egress, public-mode, monetization,
or research-validity confidence.

Authority case: CASE-OPERATOR-PREDICTIVE-DOSSIER-PRODUCTIZATI
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.operator_predictive_dossier_contract import DossierRow, ValueBraid
from shared.operator_quality_posterior import PosteriorRow

log = logging.getLogger(__name__)

FORBIDDEN_CONFIDENCE_DOMAINS: frozenset[str] = frozenset(
    {
        "truth",
        "rights",
        "privacy",
        "egress",
        "public_mode",
        "monetization",
        "research_validity",
    }
)


class AdapterModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SelectionPrior(AdapterModel):
    task_id: str = Field(min_length=1)
    base_wsjf: float = Field(ge=0.0)
    dossier_adjusted_wsjf: float = Field(ge=0.0)
    adjustment_factor: float = Field(ge=0.0, le=2.0)
    adjustment_reason: str


class OperatorLaborRisk(AdapterModel):
    task_id: str = Field(min_length=1)
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_factors: tuple[str, ...] = Field(default_factory=tuple)


class CalibrationNote(AdapterModel):
    task_id: str = Field(min_length=1)
    base_wsjf: float
    dossier_adjusted_wsjf: float
    divergence: float
    note: str


class DossierBraidAdapterOutput(AdapterModel):
    selection_prior: SelectionPrior
    operator_labor_risk: OperatorLaborRisk
    calibration_note: CalibrationNote | None = None
    confidence_mutations: Literal[None] = None

    @model_validator(mode="after")
    def _no_confidence_mutations(self):
        if self.confidence_mutations is not None:
            raise ValueError("adapter output must never carry confidence mutations")
        return self


DIVERGENCE_THRESHOLD = 0.15


def adapt_dossier_row(
    row: DossierRow,
    *,
    posterior: PosteriorRow | None = None,
    base_wsjf: float = 0.0,
) -> DossierBraidAdapterOutput:
    braid = row.value_braid
    prediction = row.prediction

    operator_acceptance = _estimate_operator_acceptance(prediction, posterior)
    labor_risk = _estimate_labor_risk(row, posterior)
    adjustment = _compute_adjustment(operator_acceptance, labor_risk, braid)
    adjusted_wsjf = base_wsjf * adjustment

    selection_prior = SelectionPrior(
        task_id=row.id,
        base_wsjf=base_wsjf,
        dossier_adjusted_wsjf=adjusted_wsjf,
        adjustment_factor=adjustment,
        adjustment_reason=_adjustment_reason(operator_acceptance, labor_risk, braid),
    )

    labor = OperatorLaborRisk(
        task_id=row.id,
        risk_score=labor_risk,
        risk_factors=_labor_risk_factors(row, posterior),
    )

    calibration = None
    if base_wsjf > 0:
        divergence = abs(adjusted_wsjf - base_wsjf) / base_wsjf
        if divergence > DIVERGENCE_THRESHOLD:
            calibration = CalibrationNote(
                task_id=row.id,
                base_wsjf=base_wsjf,
                dossier_adjusted_wsjf=adjusted_wsjf,
                divergence=divergence,
                note=f"dossier adjustment diverges {divergence:.0%} from base WSJF",
            )

    return DossierBraidAdapterOutput(
        selection_prior=selection_prior,
        operator_labor_risk=labor,
        calibration_note=calibration,
    )


def _estimate_operator_acceptance(
    prediction: object,
    posterior: PosteriorRow | None,
) -> float:
    prob = getattr(prediction, "probability", 0.5)
    conf = getattr(prediction, "confidence", 0.5)
    base = prob * conf

    if posterior is not None:
        posterior_mean = getattr(posterior, "posterior_mean", 0.5)
        return 0.6 * base + 0.4 * posterior_mean

    return base


def _estimate_labor_risk(row: DossierRow, posterior: PosteriorRow | None) -> float:
    risk = row.value_braid.risk_penalty / 10.0
    risk = min(risk, 1.0)

    if row.value_braid.hard_vetoes:
        risk = min(risk + 0.2, 1.0)

    if posterior is not None:
        variance = getattr(posterior, "posterior_variance", 0.0)
        if variance > 0.1:
            risk = min(risk + 0.1, 1.0)

    return risk


def _compute_adjustment(
    operator_acceptance: float,
    labor_risk: float,
    braid: ValueBraid,
) -> float:
    acceptance_boost = 0.5 + (operator_acceptance * 0.5)
    risk_penalty = 1.0 - (labor_risk * 0.3)
    ceiling_factor = 1.0 if braid.mode_ceiling != "private" else 0.9
    return min(acceptance_boost * risk_penalty * ceiling_factor, 2.0)


def _adjustment_reason(
    operator_acceptance: float,
    labor_risk: float,
    braid: ValueBraid,
) -> str:
    parts = [f"acceptance={operator_acceptance:.2f}"]
    if labor_risk > 0.3:
        parts.append(f"labor_risk={labor_risk:.2f}")
    if braid.hard_vetoes:
        parts.append(f"vetoes={len(braid.hard_vetoes)}")
    if braid.mode_ceiling == "private":
        parts.append("private_ceiling")
    return "; ".join(parts)


def _labor_risk_factors(row: DossierRow, posterior: PosteriorRow | None) -> tuple[str, ...]:
    factors: list[str] = []
    if row.value_braid.risk_penalty > 3.0:
        factors.append("high_risk_penalty")
    if row.value_braid.hard_vetoes:
        factors.append("has_hard_vetoes")
    if row.prediction.confidence < 0.3:
        factors.append("low_prediction_confidence")
    if posterior is not None and getattr(posterior, "posterior_variance", 0.0) > 0.1:
        factors.append("high_posterior_variance")
    return tuple(factors)


__all__ = [
    "DIVERGENCE_THRESHOLD",
    "FORBIDDEN_CONFIDENCE_DOMAINS",
    "CalibrationNote",
    "DossierBraidAdapterOutput",
    "OperatorLaborRisk",
    "SelectionPrior",
    "adapt_dossier_row",
]
