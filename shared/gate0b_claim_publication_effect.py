"""Typed dormant Gate-0B claim-publication effect carrier."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from shared.execution_admission import ActionIntent, ContentAddress, ExecutionLease
from shared.gate0b_claim_publication_install import (
    GATE0B_CLAIM_PUBLICATION_CAPABILITY_ROLE,
    GATE0B_CLAIM_PUBLICATION_OPERATION,
    Gate0BClaimPublicationInstallReceipt,
    require_claim_publication_install_receipt,
)
from shared.gate0b_claim_publication_lease import (
    ClaimPublicationAdmissionPackage,
    materialize_claim_publication_proofs,
    prepare_claim_publication_admission,
)
from shared.sdlc_claim import (
    ClaimAdmissionConsumption,
    ClaimPublicationError,
    ClaimPublicationIntent,
    ClaimPublicationReceipt,
    _apply_admitted_claim_publication_transaction,
)

CLAIM_PUBLICATION_EFFECT_INVOCATION_SCHEMA = "hapax.claim-publication-effect-invocation.v1"


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Path):
        return str(value)
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        _jsonable(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _self_hash(domain: str, body: object) -> str:
    return _sha256(domain.encode("ascii") + b"\0" + _canonical(body))


@dataclass(frozen=True)
class ClaimPublicationEffectInvocation:
    invocation_ref: str
    invocation_hash: str
    operation: Literal["claim.publish"]
    action_class: Literal["claim_publication"]
    capability_role: Literal["claim_publisher"]
    composition_manifest: ContentAddress
    install_receipt: ContentAddress
    claim_publication_intent: ContentAddress
    admission_consumption: ContentAddress
    action_intent: ContentAddress
    execution_lease: ContentAddress
    checked_at: str
    intent: ClaimPublicationIntent
    consumption: ClaimAdmissionConsumption
    may_authorize: Literal[False] = False
    authorizes_direct_fallthrough: Literal[False] = False
    schema: Literal["hapax.claim-publication-effect-invocation.v1"] = (
        CLAIM_PUBLICATION_EFFECT_INVOCATION_SCHEMA
    )

    @classmethod
    def create(
        cls,
        *,
        intent: ClaimPublicationIntent,
        consumption: ClaimAdmissionConsumption,
        package: ClaimPublicationAdmissionPackage,
        install_receipt: Gate0BClaimPublicationInstallReceipt,
        composition_manifest: ContentAddress,
    ) -> ClaimPublicationEffectInvocation:
        action_address = ContentAddress(
            ref=package.action_intent.intent_ref,
            sha256=package.action_intent.intent_hash,
        )
        lease_address = ContentAddress(
            ref=package.execution_lease.lease_ref,
            sha256=package.execution_lease.lease_hash,
        )
        values: dict[str, object] = {
            "schema": CLAIM_PUBLICATION_EFFECT_INVOCATION_SCHEMA,
            "operation": GATE0B_CLAIM_PUBLICATION_OPERATION,
            "action_class": "claim_publication",
            "capability_role": GATE0B_CLAIM_PUBLICATION_CAPABILITY_ROLE,
            "composition_manifest": composition_manifest,
            "install_receipt": ContentAddress(
                ref=install_receipt.receipt_ref,
                sha256=install_receipt.receipt_hash,
            ),
            "claim_publication_intent": ContentAddress(
                ref=intent.intent_ref,
                sha256=intent.intent_sha256,
            ),
            "admission_consumption": ContentAddress(
                ref=consumption.consumption_ref,
                sha256=consumption.consumption_hash,
            ),
            "action_intent": action_address,
            "execution_lease": lease_address,
            "checked_at": package.checked_at,
            "intent": intent.to_record(),
            "consumption": consumption.to_record(),
            "may_authorize": False,
            "authorizes_direct_fallthrough": False,
        }
        digest = _self_hash(CLAIM_PUBLICATION_EFFECT_INVOCATION_SCHEMA, values)
        return cls(
            invocation_ref=f"claim-publication-effect-invocation@sha256:{digest}",
            invocation_hash=digest,
            operation=GATE0B_CLAIM_PUBLICATION_OPERATION,
            action_class="claim_publication",
            capability_role=GATE0B_CLAIM_PUBLICATION_CAPABILITY_ROLE,
            composition_manifest=composition_manifest,
            install_receipt=ContentAddress(
                ref=install_receipt.receipt_ref,
                sha256=install_receipt.receipt_hash,
            ),
            claim_publication_intent=ContentAddress(
                ref=intent.intent_ref,
                sha256=intent.intent_sha256,
            ),
            admission_consumption=ContentAddress(
                ref=consumption.consumption_ref,
                sha256=consumption.consumption_hash,
            ),
            action_intent=action_address,
            execution_lease=lease_address,
            checked_at=package.checked_at,
            intent=intent,
            consumption=consumption,
        )

    def identity_body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "operation": self.operation,
            "action_class": self.action_class,
            "capability_role": self.capability_role,
            "composition_manifest": self.composition_manifest,
            "install_receipt": self.install_receipt,
            "claim_publication_intent": self.claim_publication_intent,
            "admission_consumption": self.admission_consumption,
            "action_intent": self.action_intent,
            "execution_lease": self.execution_lease,
            "checked_at": self.checked_at,
            "intent": self.intent.to_record(),
            "consumption": self.consumption.to_record(),
            "may_authorize": self.may_authorize,
            "authorizes_direct_fallthrough": self.authorizes_direct_fallthrough,
        }

    def __post_init__(self) -> None:
        expected = _self_hash(CLAIM_PUBLICATION_EFFECT_INVOCATION_SCHEMA, self.identity_body())
        if (
            self.invocation_hash != expected
            or self.invocation_ref != f"claim-publication-effect-invocation@sha256:{expected}"
            or self.claim_publication_intent
            != ContentAddress(ref=self.intent.intent_ref, sha256=self.intent.intent_sha256)
            or self.admission_consumption
            != ContentAddress(
                ref=self.consumption.consumption_ref,
                sha256=self.consumption.consumption_hash,
            )
        ):
            raise ValueError(
                "claim-publication effect invocation identity mismatch; Next action: recreate "
                "the carrier from the original intent, materialized proofs, and installed "
                "composition root"
            )


def _models(consumption: ClaimAdmissionConsumption) -> dict[str, object]:
    return {proof.kind: proof.model for proof in consumption.proofs}


def apply_claim_publication_effect(
    invocation: ClaimPublicationEffectInvocation,
    *,
    root,
    now: str | datetime | None = None,
    failure_hook: Callable[[str, int | None], None] | None = None,
) -> ClaimPublicationReceipt:
    del now
    receipt = require_claim_publication_install_receipt(root)
    if root.composition_manifest is None:
        raise ClaimPublicationError(
            "claim_publication_composition_missing",
            "install the exact claim-publication composition before applying effects",
        )
    manifest_address = ContentAddress(
        ref=root.composition_manifest.manifest_ref,
        sha256=root.composition_manifest.manifest_hash,
    )
    receipt_address = ContentAddress(ref=receipt.receipt_ref, sha256=receipt.receipt_hash)
    models = _models(invocation.consumption)
    action = models.get("action_intent")
    lease = models.get("execution_lease")
    if (
        invocation.operation != GATE0B_CLAIM_PUBLICATION_OPERATION
        or invocation.action_class != "claim_publication"
        or invocation.capability_role != GATE0B_CLAIM_PUBLICATION_CAPABILITY_ROLE
        or invocation.composition_manifest != manifest_address
        or invocation.install_receipt != receipt_address
        or not isinstance(action, ActionIntent)
        or not isinstance(lease, ExecutionLease)
        or action.operation != GATE0B_CLAIM_PUBLICATION_OPERATION
        or action.action_class != "claim_publication"
        or action.capability_role != GATE0B_CLAIM_PUBLICATION_CAPABILITY_ROLE
        or lease.bound_call.operation != GATE0B_CLAIM_PUBLICATION_OPERATION
        or lease.bound_call.action_class != "claim_publication"
    ):
        raise ClaimPublicationError(
            "claim_publication_effect_invocation_mismatch",
            "dispatch only the exact Gate-0B claim-publication lease carrier",
            invocation.invocation_ref,
        )
    return _apply_admitted_claim_publication_transaction(
        invocation.intent,
        invocation.consumption,
        transaction_root=root.claim_transaction_root,
        receipt_root=root.claim_receipt_root,
        lock_root=root.claim_lock_root,
        failure_hook=failure_hook,
    )


def publish_gate0b_claim(
    intent: ClaimPublicationIntent,
    *,
    root,
    now: str | datetime,
    failure_hook: Callable[[str, int | None], None] | None = None,
) -> ClaimPublicationReceipt:
    receipt = require_claim_publication_install_receipt(root)
    package = prepare_claim_publication_admission(
        intent,
        root=root,
        install_receipt=receipt,
        now=now,
    )
    consumption = materialize_claim_publication_proofs(package)
    assert root.composition_manifest is not None
    invocation = ClaimPublicationEffectInvocation.create(
        intent=intent,
        consumption=consumption,
        package=package,
        install_receipt=receipt,
        composition_manifest=ContentAddress(
            ref=root.composition_manifest.manifest_ref,
            sha256=root.composition_manifest.manifest_hash,
        ),
    )
    return apply_claim_publication_effect(
        invocation,
        root=root,
        now=now,
        failure_hook=failure_hook,
    )


__all__ = [
    "CLAIM_PUBLICATION_EFFECT_INVOCATION_SCHEMA",
    "ClaimPublicationEffectInvocation",
    "apply_claim_publication_effect",
    "publish_gate0b_claim",
]
