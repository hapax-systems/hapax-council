"""Position-bound epistemic impingement traces and pull-portal receipts."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, Self

from hapax.context_canon import (
    ContextImpingement,
    ContextPosition,
    ContextState,
    PortalOffer,
    canonical_json_bytes,
)
from hapax.context_canon.contract import _domain_hash
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from shared.impingement import Impingement, render_impingement_text

TRACE_SCHEMA = "hapax.epistemic-impingement-trace.v1"
PORTAL_RECEIPT_SCHEMA = "hapax.portal-consumption-receipt.v1"
SCHEMA_ID = "https://hapax.systems/schemas/epistemic-impingement-envelope.schema.json"
DEFAULT_TRACE_BUDGET_BYTES = 32_768


class EpistemicImpingementError(RuntimeError):
    """A typed refusal at the epistemic trace boundary."""

    def __init__(self, reason_code: str, repair_action: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.repair_action = repair_action
        self.detail = detail
        rendered = f"{reason_code}: {repair_action}"
        if detail:
            rendered += f" ({detail})"
        super().__init__(rendered)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def _nonblank(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("wire strings must be nonblank without edge whitespace")
    value.encode("utf-8", errors="strict")
    return value


def _string_set(value: tuple[str, ...], *, allow_empty: bool = False) -> tuple[str, ...]:
    if not allow_empty and not value:
        raise ValueError("string set must not be empty")
    if value != tuple(sorted(set(value))):
        raise ValueError("string set must be sorted and unique")
    if any(_nonblank(item) != item for item in value):
        raise ValueError("string set contains an invalid entry")
    return value


def _canonical_timestamp(value: str | datetime) -> str:
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must carry a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _checked_timestamp(value: str) -> str:
    canonical = _canonical_timestamp(value)
    if canonical != value:
        raise ValueError("timestamp must be canonical UTC with microseconds")
    return value


def context_impingement_digest(items: Sequence[ContextImpingement]) -> str:
    return _domain_hash(
        "hapax.context-impingements.v1",
        tuple(sorted(items, key=lambda item: item.impingement_id)),
    )


def portal_set_digest(items: Sequence[PortalOffer]) -> str:
    return _domain_hash(
        "hapax.portal-set.v1",
        tuple(sorted(items, key=lambda item: item.portal_ref)),
    )


class EpistemicImpingementTrace(_FrozenModel):
    schema_id: Literal["hapax.epistemic-impingement-trace.v1"] = Field(alias="schema")
    trace_ref: str
    trace_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_ref: str
    task_ref: str
    position_ref: str
    position_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage_token: str
    fact_frontier_ref: str
    fact_refs: tuple[str, ...] = Field(min_length=1)
    source_event_refs: tuple[str, ...] = Field(min_length=1)
    impingements: tuple[ContextImpingement, ...]
    portal_offers: tuple[PortalOffer, ...]
    impingement_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    portal_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_ref: str
    observed_at: str
    checked_at: str
    stale_after: str
    max_bytes: int = Field(ge=1024, le=65_536, strict=True)
    may_authorize: Literal[False]

    @field_validator(
        "trace_ref",
        "session_ref",
        "task_ref",
        "position_ref",
        "stage_token",
        "fact_frontier_ref",
        "method_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("fact_refs", "source_event_refs")
    @classmethod
    def validate_string_set(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value)

    @field_validator("observed_at", "checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_trace(self) -> Self:
        if not (self.observed_at <= self.checked_at <= self.stale_after):
            raise ValueError("trace timestamps must be observed <= checked <= stale_after")
        if self.impingements != tuple(
            sorted(self.impingements, key=lambda item: item.impingement_id)
        ):
            raise ValueError("impingements must be sorted")
        if self.portal_offers != tuple(
            sorted(self.portal_offers, key=lambda item: item.portal_ref)
        ):
            raise ValueError("portal offers must be sorted")
        if len({item.impingement_id for item in self.impingements}) != len(self.impingements):
            raise ValueError("impingement ids must be unique")
        if len({item.portal_ref for item in self.portal_offers}) != len(self.portal_offers):
            raise ValueError("portal refs must be unique")
        known_facts = set(self.fact_refs)
        referenced_facts = {
            ref
            for item in (*self.impingements, *self.portal_offers)
            for ref in item.source_fact_refs
        }
        if not referenced_facts.issubset(known_facts):
            raise ValueError("trace objects reference facts outside the frozen frontier")
        # The trace already binds every portal to the exact position and stage.
        # Requiring the position ref inside PortalOffer would be circular because
        # ContextPosition itself commits to the portal-set digest.
        if any(
            not ({"pull_only", "non_mutating_pull"} & set(item.effectivity_basis))
            for item in self.portal_offers
        ):
            raise ValueError("portal effectivity must remain pull-only")
        if self.impingement_digest != context_impingement_digest(self.impingements):
            raise ValueError("impingement_digest does not bind the impingements")
        if self.portal_set_digest != portal_set_digest(self.portal_offers):
            raise ValueError("portal_set_digest does not bind the portals")
        body = self.model_dump(mode="json", by_alias=True, exclude={"trace_ref", "trace_hash"})
        expected_hash = _domain_hash("hapax.epistemic-impingement-trace.v1", body)
        if self.trace_hash != expected_hash:
            raise ValueError("trace_hash does not bind the trace")
        if self.trace_ref != f"epistemic-impingement@sha256:{expected_hash}":
            raise ValueError("trace_ref does not bind trace_hash")
        if len(canonical_json_bytes(self.model_dump(mode="json", by_alias=True))) > self.max_bytes:
            raise ValueError("trace exceeds its declared byte budget")
        return self


class PortalConsumptionReceipt(_FrozenModel):
    schema_id: Literal["hapax.portal-consumption-receipt.v1"] = Field(alias="schema")
    receipt_ref: str
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trace_ref: str
    trace_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_ref: str
    task_ref: str
    position_ref: str
    position_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage_token: str
    portal_ref: str
    requester_ref: str
    purpose: str
    requested_at: str
    consumed_at: str
    projection_ref: str
    budget_ref: str
    budget_receipt_ref: str
    outcome: Literal["consumed"]
    no_effect: Literal[True]
    may_authorize: Literal[False]

    @field_validator(
        "receipt_ref",
        "trace_ref",
        "session_ref",
        "task_ref",
        "position_ref",
        "stage_token",
        "portal_ref",
        "requester_ref",
        "purpose",
        "projection_ref",
        "budget_ref",
        "budget_receipt_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("requested_at", "consumed_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.requested_at > self.consumed_at:
            raise ValueError("portal consumption cannot precede its request")
        body = self.model_dump(mode="json", by_alias=True, exclude={"receipt_ref", "receipt_hash"})
        expected_hash = _domain_hash("hapax.portal-consumption-receipt.v1", body)
        if self.receipt_hash != expected_hash:
            raise ValueError("receipt_hash does not bind the portal consumption")
        if self.receipt_ref != f"portal-consumption@sha256:{expected_hash}":
            raise ValueError("receipt_ref does not bind receipt_hash")
        return self


def build_epistemic_impingement_trace(
    position: ContextPosition,
    *,
    session_ref: str,
    fact_frontier_ref: str,
    fact_refs: Sequence[str],
    source_event_refs: Sequence[str],
    impingements: Sequence[ContextImpingement],
    portal_offers: Sequence[PortalOffer],
    method_ref: str,
    observed_at: str | datetime,
    checked_at: str | datetime,
    stale_after: str | datetime,
    max_bytes: int = DEFAULT_TRACE_BUDGET_BYTES,
) -> EpistemicImpingementTrace:
    normalized_impingements = tuple(sorted(impingements, key=lambda item: item.impingement_id))
    normalized_portals = tuple(sorted(portal_offers, key=lambda item: item.portal_ref))
    impingement_hash = context_impingement_digest(normalized_impingements)
    portal_hash = portal_set_digest(normalized_portals)
    if position.impingement_digest != impingement_hash or position.portal_set_digest != portal_hash:
        raise EpistemicImpingementError(
            "epistemic_trace_position_digest_mismatch",
            "rebuild the trace from the exact impingements and portals bound to the position",
            position.position_ref,
        )
    body: dict[str, Any] = {
        "schema": TRACE_SCHEMA,
        "session_ref": _nonblank(session_ref),
        "task_ref": position.task_ref,
        "position_ref": position.position_ref,
        "position_hash": position.position_hash,
        "stage_token": position.stage_token,
        "fact_frontier_ref": _nonblank(fact_frontier_ref),
        "fact_refs": tuple(sorted(set(fact_refs))),
        "source_event_refs": tuple(sorted(set(source_event_refs))),
        "impingements": normalized_impingements,
        "portal_offers": normalized_portals,
        "impingement_digest": impingement_hash,
        "portal_set_digest": portal_hash,
        "method_ref": _nonblank(method_ref),
        "observed_at": _canonical_timestamp(observed_at),
        "checked_at": _canonical_timestamp(checked_at),
        "stale_after": _canonical_timestamp(stale_after),
        "max_bytes": max_bytes,
        "may_authorize": False,
    }
    trace_hash = _domain_hash("hapax.epistemic-impingement-trace.v1", body)
    return EpistemicImpingementTrace.model_validate(
        {
            **body,
            "trace_ref": f"epistemic-impingement@sha256:{trace_hash}",
            "trace_hash": trace_hash,
        }
    )


def require_current_epistemic_trace(
    trace: EpistemicImpingementTrace,
    position: ContextPosition,
    *,
    now: str | datetime,
) -> EpistemicImpingementTrace:
    checked = EpistemicImpingementTrace.model_validate(trace.model_dump(mode="json", by_alias=True))
    if (
        checked.task_ref != position.task_ref
        or checked.position_ref != position.position_ref
        or checked.position_hash != position.position_hash
        or checked.stage_token != position.stage_token
        or checked.impingement_digest != position.impingement_digest
        or checked.portal_set_digest != position.portal_set_digest
    ):
        raise EpistemicImpingementError(
            "epistemic_trace_position_mismatch",
            "materialize a fresh trace for the exact current lifecycle position",
            position.position_ref,
        )
    observed_now = _canonical_timestamp(now)
    if observed_now < checked.checked_at or observed_now >= checked.stale_after:
        raise EpistemicImpingementError(
            "epistemic_trace_stale",
            "reobserve the changed facts and reissue the current position-bound trace",
            checked.trace_ref,
        )
    return checked


def consume_portal(
    trace: EpistemicImpingementTrace,
    position: ContextPosition,
    *,
    portal_ref: str,
    requester_ref: str,
    requested_at: str | datetime,
    consumed_at: str | datetime,
    projection_ref: str,
    budget_receipt_ref: str,
    now: str | datetime,
) -> PortalConsumptionReceipt:
    checked = require_current_epistemic_trace(trace, position, now=now)
    portal = next((item for item in checked.portal_offers if item.portal_ref == portal_ref), None)
    if portal is None:
        raise EpistemicImpingementError(
            "epistemic_portal_not_offered",
            "consume only a portal offered by the exact current trace",
            portal_ref,
        )
    if portal.state.value_state != "present":
        raise EpistemicImpingementError(
            "epistemic_portal_unavailable",
            "repair the portal evidence or leave the optional pull unconsumed",
            ",".join(portal.state.reason_codes),
        )
    requested = _canonical_timestamp(requested_at)
    consumed = _canonical_timestamp(consumed_at)
    if consumed >= checked.stale_after:
        raise EpistemicImpingementError(
            "epistemic_portal_consumed_after_trace_expiry",
            "reissue the trace before consuming the portal",
            portal_ref,
        )
    body = {
        "schema": PORTAL_RECEIPT_SCHEMA,
        "trace_ref": checked.trace_ref,
        "trace_hash": checked.trace_hash,
        "session_ref": checked.session_ref,
        "task_ref": checked.task_ref,
        "position_ref": checked.position_ref,
        "position_hash": checked.position_hash,
        "stage_token": checked.stage_token,
        "portal_ref": portal.portal_ref,
        "requester_ref": _nonblank(requester_ref),
        "purpose": portal.purpose,
        "requested_at": requested,
        "consumed_at": consumed,
        "projection_ref": _nonblank(projection_ref),
        "budget_ref": portal.budget_ref,
        "budget_receipt_ref": _nonblank(budget_receipt_ref),
        "outcome": "consumed",
        "no_effect": True,
        "may_authorize": False,
    }
    receipt_hash = _domain_hash("hapax.portal-consumption-receipt.v1", body)
    return PortalConsumptionReceipt.model_validate(
        {
            **body,
            "receipt_ref": f"portal-consumption@sha256:{receipt_hash}",
            "receipt_hash": receipt_hash,
        }
    )


def project_legacy_impingement(
    impingement: Impingement,
    *,
    source_fact_refs: Sequence[str],
    protects: Sequence[str],
    legal_next: Sequence[str] = (),
    state: ContextState,
) -> ContextImpingement:
    """Project the existing activation currency without granting it authority."""

    summary = render_impingement_text(impingement)
    return ContextImpingement(
        impingement_id=f"impingement:{impingement.id}",
        kind=f"legacy:{impingement.type.value}",
        summary=summary[:1024],
        source_fact_refs=tuple(sorted(set(source_fact_refs))),
        protects=tuple(sorted(set(protects))),
        legal_next=tuple(sorted(set(legal_next))),
        state=state,
        may_authorize=False,
    )


def epistemic_impingement_schema() -> Mapping[str, Any]:
    schema = TypeAdapter(EpistemicImpingementTrace | PortalConsumptionReceipt).json_schema(
        by_alias=True, ref_template="#/$defs/{model}"
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
    }


if __name__ == "__main__":
    print(json.dumps(epistemic_impingement_schema(), ensure_ascii=True, indent=2, sort_keys=True))
