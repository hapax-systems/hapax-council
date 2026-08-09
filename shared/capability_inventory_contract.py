"""Tagged capability inventory contract.

The capability inventory has two intentionally disjoint planes:

* admitted supply may be selected by existing supply consumers;
* evidence-only non-supply is visible to operators and CI but cannot satisfy demand.

Keeping the disposition in the record and fingerprint prevents an evidence surface
from becoming supply through an untyped descriptor projection or baseline migration.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    SerializerFunctionWrapHandler,
    StrictInt,
    field_serializer,
    model_serializer,
    model_validator,
)

from shared.agentic_trust_boundary import (
    AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS,
    AGENTIC_TRUST_EVIDENCE_SURFACE_ID,
    is_agentic_trust_supply_evidence_reference,
)
from shared.capability_harness_descriptor import (
    CapabilityHarnessDescriptor,
    CapabilityInventoryDelta,
    descriptor_fingerprint,
)
from shared.platform_capability_registry import (
    CapabilityShapeDescriptor,
    CapabilityShapeState,
)

__all__ = [
    "AdmittedSupplyInventoryRecord",
    "CapabilityInventoryBaselineRecord",
    "CapabilityInventoryBaselineV2",
    "CapabilityInventoryRecord",
    "CapabilityInventorySnapshot",
    "EvidenceOnlyNonSupplyInventoryRecord",
    "InventoryDisposition",
    "discover_inventory",
    "inventory_baseline",
    "inventory_record_fingerprint",
    "wrap_supply_descriptor_fingerprint",
]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class InventoryDisposition(StrEnum):
    ADMITTED_SUPPLY = "admitted_supply"
    EVIDENCE_ONLY_NON_SUPPLY = "evidence_only_non_supply"


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


class _DescriptorGuardedRecord(StrictFrozenModel):
    """Freeze a private descriptor copy and reject every later nested mutation."""

    _descriptor_canonical: bytes = PrivateAttr(default=b"")

    def _validate_current_descriptor(self) -> None:
        raise NotImplementedError

    def _seal_descriptor(self) -> None:
        descriptor = self.descriptor  # type: ignore[attr-defined]
        descriptor_type = type(descriptor)
        descriptor_type.model_validate(descriptor.model_dump(mode="python"))
        self._validate_current_descriptor()
        canonical = _canonical_json_bytes(descriptor.model_dump(mode="json"))
        if self._descriptor_canonical and canonical != self._descriptor_canonical:
            raise ValueError(
                f"inventory descriptor mutated after admission: {self.inventory_id}; "
                "construct a new tagged inventory record for intentional changes"
            )
        object.__setattr__(self, "descriptor", descriptor.model_copy(deep=True))
        self._descriptor_canonical = canonical

    def _assert_descriptor_unchanged(self) -> None:
        descriptor = self.descriptor  # type: ignore[attr-defined]
        type(descriptor).model_validate(descriptor.model_dump(mode="python"))
        self._validate_current_descriptor()
        if _canonical_json_bytes(descriptor.model_dump(mode="json")) != self._descriptor_canonical:
            raise ValueError(
                f"inventory descriptor mutated after admission: {self.inventory_id}; "
                "construct a new tagged inventory record for intentional changes"
            )

    @model_serializer(mode="wrap")
    def _serialize_guarded(self, handler: SerializerFunctionWrapHandler) -> object:
        self._assert_descriptor_unchanged()
        return handler(self)

    @classmethod
    def model_validate(cls, obj: object, **kwargs: Any) -> Self:
        if isinstance(obj, cls):
            obj._assert_descriptor_unchanged()
        return super().model_validate(obj, **kwargs)


class AdmittedSupplyInventoryRecord(_DescriptorGuardedRecord):
    inventory_schema: Literal[2] = 2
    inventory_id: str
    inventory_disposition: Literal[InventoryDisposition.ADMITTED_SUPPLY] = (
        InventoryDisposition.ADMITTED_SUPPLY
    )
    descriptor: CapabilityHarnessDescriptor

    @model_validator(mode="after")
    def _id_matches_descriptor(self) -> Self:
        self._seal_descriptor()
        return self

    def _validate_current_descriptor(self) -> None:
        if self.inventory_id != self.descriptor.capability_id:
            raise ValueError("inventory_id must equal the admitted descriptor capability_id")
        if any(
            is_agentic_trust_supply_evidence_reference(identity)
            for identity in (
                self.descriptor.capability_id,
                self.descriptor.platform_id,
                self.descriptor.route_id,
                self.descriptor.execution_harness_id,
                self.descriptor.provider,
                self.descriptor.backend,
                self.descriptor.model,
                self.descriptor.effort,
                self.descriptor.context_window,
                *self.descriptor.mutation_surfaces,
                *self.descriptor.quality_floors,
                self.descriptor.privacy_posture,
                self.descriptor.public_claim_ceiling,
                *self.descriptor.resource_pools,
                *self.descriptor.freshness_evidence,
                *self.descriptor.receipt_classes,
                *self.descriptor.failure_classes,
                *self.descriptor.kill_switches,
                self.descriptor.fallback_policy,
                self.descriptor.stale_after,
            )
        ):
            raise ValueError(
                "agentic-trust evaluator observation identity is permanently non-supply"
            )


class EvidenceOnlyNonSupplyInventoryRecord(_DescriptorGuardedRecord):
    inventory_schema: Literal[2] = 2
    inventory_id: str
    inventory_disposition: Literal[InventoryDisposition.EVIDENCE_ONLY_NON_SUPPLY] = (
        InventoryDisposition.EVIDENCE_ONLY_NON_SUPPLY
    )
    descriptor: CapabilityShapeDescriptor

    @model_validator(mode="after")
    def _id_matches_descriptor(self) -> Self:
        self._seal_descriptor()
        return self

    def _validate_current_descriptor(self) -> None:
        if self.inventory_id != self.descriptor.shape_id:
            raise ValueError("inventory_id must equal the non-supply descriptor shape_id")
        if self.inventory_id == AGENTIC_TRUST_EVIDENCE_SURFACE_ID and (
            self.descriptor.shape_state is not CapabilityShapeState.EVIDENCE_ONLY
            or self.descriptor.observation_receipt_class != AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS
        ):
            raise ValueError(
                "agentic-trust evaluator must retain its evidence-only native receipt contract"
            )


CapabilityInventoryRecord = Annotated[
    AdmittedSupplyInventoryRecord | EvidenceOnlyNonSupplyInventoryRecord,
    Field(discriminator="inventory_disposition"),
]


class CapabilityInventorySnapshot(StrictFrozenModel):
    inventory_schema: Literal[2] = 2
    records: tuple[CapabilityInventoryRecord, ...]

    @classmethod
    def model_validate(cls, obj: object, **kwargs: Any) -> Self:
        if isinstance(obj, cls):
            obj.validated_records()
        return super().model_validate(obj, **kwargs)

    @model_validator(mode="before")
    @classmethod
    def _existing_snapshot_is_unchanged(cls, value: object) -> object:
        if isinstance(value, cls):
            value.validated_records()
        return value

    @model_validator(mode="after")
    def _ids_are_unique_across_planes(self) -> Self:
        records = tuple(_revalidate_record(record) for record in self.records)
        counts = Counter(record.inventory_id for record in records)
        duplicates = sorted(inventory_id for inventory_id, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(
                "duplicate inventory_id(s) across capability inventory planes: "
                + ", ".join(duplicates)
            )
        object.__setattr__(self, "records", records)
        return self

    def validated_records(self) -> tuple[CapabilityInventoryRecord, ...]:
        """Return deep-copied records after revalidating nested mutable descriptors.

        Pydantic's frozen setting is shallow. All authoritative projections call this
        boundary so post-construction mutation of a nested descriptor cannot bypass ID,
        route-emptiness, demand, or cross-plane uniqueness checks.
        """

        records = tuple(_revalidate_record(record) for record in self.records)
        counts = Counter(record.inventory_id for record in records)
        duplicates = sorted(inventory_id for inventory_id, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(
                "duplicate inventory_id(s) across capability inventory planes: "
                + ", ".join(duplicates)
            )
        return records

    @field_serializer("records")
    def _serialize_validated_records(
        self,
        _records: tuple[CapabilityInventoryRecord, ...],
    ) -> tuple[CapabilityInventoryRecord, ...]:
        """Preserve normal Pydantic shape while guarding every nested record."""

        return self.validated_records()

    def record_map(self) -> dict[str, CapabilityInventoryRecord]:
        return {record.inventory_id: record for record in self.validated_records()}

    def admitted_supply_descriptors(self) -> tuple[CapabilityHarnessDescriptor, ...]:
        return tuple(
            record.descriptor
            for record in self.validated_records()
            if isinstance(record, AdmittedSupplyInventoryRecord)
        )

    def evidence_only_non_supply_descriptors(self) -> tuple[CapabilityShapeDescriptor, ...]:
        return tuple(
            record.descriptor
            for record in self.validated_records()
            if isinstance(record, EvidenceOnlyNonSupplyInventoryRecord)
        )


class CapabilityInventoryBaselineRecord(StrictFrozenModel):
    inventory_disposition: InventoryDisposition
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class CapabilityInventoryBaselineV2(StrictFrozenModel):
    _records_canonical: bytes = PrivateAttr(default=b"")

    schema_version: Literal[2]
    count: StrictInt = Field(ge=0)
    records: dict[str, CapabilityInventoryBaselineRecord]

    @classmethod
    def model_validate(cls, obj: object, **kwargs: Any) -> Self:
        if isinstance(obj, cls):
            obj._assert_records_unchanged()
        return super().model_validate(obj, **kwargs)

    @model_validator(mode="before")
    @classmethod
    def _existing_baseline_is_unchanged(cls, value: object) -> object:
        if isinstance(value, cls):
            value._assert_records_unchanged()
        return value

    @model_validator(mode="after")
    def _count_matches_records(self) -> Self:
        records = {
            inventory_id: CapabilityInventoryBaselineRecord.model_validate(record)
            for inventory_id, record in self.records.items()
        }
        if self.count != len(records):
            raise ValueError(f"baseline count {self.count} does not match {len(records)} records")
        if any(not inventory_id.strip() for inventory_id in records):
            raise ValueError("baseline inventory IDs must be non-empty")
        reserved_keys = [
            inventory_id
            for inventory_id in records
            if is_agentic_trust_supply_evidence_reference(inventory_id)
        ]
        if any(key != AGENTIC_TRUST_EVIDENCE_SURFACE_ID for key in reserved_keys):
            raise ValueError(
                "agentic-trust observation identity cannot be admitted by an inventory baseline"
            )
        evaluator = records.get(AGENTIC_TRUST_EVIDENCE_SURFACE_ID)
        if (
            evaluator is not None
            and evaluator.inventory_disposition is not InventoryDisposition.EVIDENCE_ONLY_NON_SUPPLY
        ):
            raise ValueError("agentic-trust evaluator baseline identity is permanently non-supply")
        canonical = self._canonical_records(records)
        if self._records_canonical and canonical != self._records_canonical:
            raise ValueError("capability inventory baseline mutated after validation")
        object.__setattr__(self, "records", dict(records))
        self._records_canonical = canonical
        return self

    def _canonical_records(
        self,
        records: Mapping[str, CapabilityInventoryBaselineRecord],
    ) -> bytes:
        return _canonical_json_bytes(
            {
                "count": self.count,
                "records": {
                    inventory_id: record.model_dump(mode="json")
                    for inventory_id, record in records.items()
                },
                "schema_version": self.schema_version,
            }
        )

    def _assert_records_unchanged(self) -> None:
        records = {
            inventory_id: CapabilityInventoryBaselineRecord.model_validate(record)
            for inventory_id, record in self.records.items()
        }
        if (
            self.count != len(records)
            or self._canonical_records(records) != self._records_canonical
        ):
            raise ValueError("capability inventory baseline mutated after validation")

    @model_serializer(mode="wrap")
    def _serialize_guarded(self, handler: SerializerFunctionWrapHandler) -> object:
        self._assert_records_unchanged()
        return handler(self)


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _revalidate_record(record: CapabilityInventoryRecord) -> CapabilityInventoryRecord:
    payload = record.model_dump(mode="python")
    if isinstance(record, AdmittedSupplyInventoryRecord):
        return AdmittedSupplyInventoryRecord.model_validate(payload)
    return EvidenceOnlyNonSupplyInventoryRecord.model_validate(payload)


def wrap_supply_descriptor_fingerprint(descriptor_sha256: str) -> str:
    """Upgrade a legacy supply fingerprint into the disposition-bound v2 scheme."""

    return _canonical_sha256(
        {
            "inventory_disposition": InventoryDisposition.ADMITTED_SUPPLY.value,
            "descriptor_fingerprint": descriptor_sha256,
        }
    )


def inventory_record_fingerprint(record: CapabilityInventoryRecord) -> str:
    """Return a stable fingerprint binding both descriptor semantics and disposition."""

    record = _revalidate_record(record)
    if isinstance(record, AdmittedSupplyInventoryRecord):
        return wrap_supply_descriptor_fingerprint(descriptor_fingerprint(record.descriptor))

    descriptor_payload = record.descriptor.model_dump(mode="json", exclude={"summary"})
    return _canonical_sha256(
        {
            "inventory_disposition": record.inventory_disposition.value,
            "descriptor": descriptor_payload,
        }
    )


def discover_inventory(
    snapshot: CapabilityInventorySnapshot,
    registered: Mapping[str, CapabilityInventoryBaselineRecord],
) -> CapabilityInventoryDelta:
    """Compare a tagged snapshot with a tagged baseline without projecting non-supply."""

    observed = {
        record.inventory_id: CapabilityInventoryBaselineRecord(
            inventory_disposition=record.inventory_disposition,
            fingerprint=inventory_record_fingerprint(record),
        )
        for record in snapshot.validated_records()
    }
    new_ids = sorted(inventory_id for inventory_id in observed if inventory_id not in registered)
    changed_ids = sorted(
        inventory_id
        for inventory_id, current in observed.items()
        if inventory_id in registered and current != registered[inventory_id]
    )
    missing_ids = sorted(
        inventory_id for inventory_id in registered if inventory_id not in observed
    )
    return CapabilityInventoryDelta(
        new_capability_ids=new_ids,
        changed_capability_ids=changed_ids,
        missing_capability_ids=missing_ids,
    )


def inventory_baseline(snapshot: CapabilityInventorySnapshot) -> CapabilityInventoryBaselineV2:
    """Build the deterministic v2 baseline for a validated tagged snapshot."""

    records = {
        record.inventory_id: CapabilityInventoryBaselineRecord(
            inventory_disposition=record.inventory_disposition,
            fingerprint=inventory_record_fingerprint(record),
        )
        for record in sorted(snapshot.validated_records(), key=lambda item: item.inventory_id)
    }
    return CapabilityInventoryBaselineV2(schema_version=2, count=len(records), records=records)
