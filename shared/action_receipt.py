"""Typed action receipts for command, application, and readback grounding."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.capability_outcome import AuthorityCeiling


class ActionReceiptStatus(StrEnum):
    REQUESTED = "requested"
    STAGED = "staged"
    CONFIRMED = "confirmed"
    APPLIED = "applied"
    READBACK = "readback"
    BLOCKED = "blocked"
    ERROR = "error"


class ActionReceipt(BaseModel):
    """Receipt for an action request before learning/speech treats it as done."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    receipt_id: str
    created_at: str
    request_id: str
    capability_name: str
    requested_action: str
    status: ActionReceiptStatus
    target_aperture: str | None = None
    wcs_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    command_ref: str | None = None
    confirmation_refs: list[str] = Field(default_factory=list)
    applied_refs: list[str] = Field(default_factory=list)
    readback_refs: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    error_refs: list[str] = Field(default_factory=list)
    upstream_outcome_refs: list[str] = Field(default_factory=list)
    authority_ceiling: AuthorityCeiling
    learning_update_allowed: bool = False
    structural_reflex: bool = False
    readback_required: bool = True
    operator_visible_summary: str

    @model_validator(mode="after")
    def _status_requires_state_specific_refs(self) -> Self:
        if self.status is ActionReceiptStatus.STAGED and not self.command_ref:
            raise ValueError(f"{self.receipt_id} staged receipts require command_ref")
        if self.status is ActionReceiptStatus.CONFIRMED:
            if not self.command_ref or not self.confirmation_refs:
                raise ValueError(
                    f"{self.receipt_id} confirmed receipts require command_ref and "
                    "confirmation_refs"
                )
        if self.status is ActionReceiptStatus.APPLIED and not self.applied_refs:
            raise ValueError(f"{self.receipt_id} applied receipts require applied_refs")
        if self.status is ActionReceiptStatus.READBACK:
            if not self.applied_refs or not self.readback_refs or not self.evidence_refs:
                raise ValueError(
                    f"{self.receipt_id} readback receipts require applied_refs, "
                    "readback_refs, and evidence_refs"
                )
        if self.status is ActionReceiptStatus.BLOCKED and not self.blocked_reasons:
            raise ValueError(f"{self.receipt_id} blocked receipts require blocked_reasons")
        if self.status is ActionReceiptStatus.ERROR and not (
            self.error_refs or self.blocked_reasons
        ):
            raise ValueError(f"{self.receipt_id} error receipts require error_refs")
        if self.structural_reflex and not self.readback_required:
            raise ValueError(f"{self.receipt_id} structural reflex receipts require readback")
        if self.structural_reflex and self.learning_update_allowed:
            raise ValueError(f"{self.receipt_id} structural reflex receipts cannot update learning")
        if self.status in {ActionReceiptStatus.APPLIED, ActionReceiptStatus.READBACK}:
            if not self.target_aperture:
                raise ValueError(
                    f"{self.receipt_id} applied/readback receipts require target_aperture"
                )
            if not self.wcs_refs:
                raise ValueError(f"{self.receipt_id} applied/readback receipts require wcs_refs")
        if self.learning_update_allowed and not (
            self.status is ActionReceiptStatus.READBACK
            and self.applied_refs
            and self.readback_refs
            and self.evidence_refs
            and self.wcs_refs
            and self.authority_ceiling
            in {
                AuthorityCeiling.EVIDENCE_BOUND,
                AuthorityCeiling.POSTERIOR_BOUND,
                AuthorityCeiling.PUBLIC_GATE_REQUIRED,
            }
            and not self.blocked_reasons
            and not self.error_refs
        ):
            raise ValueError(
                f"{self.receipt_id} learning updates require applied readback evidence "
                "with evidence-bound authority"
            )
        return self

    def can_support_affordance_success(self) -> bool:
        """Return true only when a readback witness can ground success learning."""

        return (
            self.status is ActionReceiptStatus.READBACK
            and self.learning_update_allowed
            and not self.structural_reflex
            and self.authority_ceiling
            in {
                AuthorityCeiling.EVIDENCE_BOUND,
                AuthorityCeiling.POSTERIOR_BOUND,
                AuthorityCeiling.PUBLIC_GATE_REQUIRED,
            }
            and bool(self.applied_refs)
            and bool(self.readback_refs)
            and bool(self.evidence_refs)
            and bool(self.wcs_refs)
            and not self.blocked_reasons
            and not self.error_refs
        )


__all__ = ["ActionReceipt", "ActionReceiptStatus"]
