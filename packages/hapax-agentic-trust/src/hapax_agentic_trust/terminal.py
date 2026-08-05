# Read-only dependency-closure derivation from conservatory/terminal_bundle.py.
# upstream_sha256=c87947e7bc0ac1d55cc04854cf043213d20f1f8a68d8058d3796c88e2291652a
# Only the dependency closure of the caller-pinned verification API is retained.

"""Read-only verification of terminal closure over receipts and custody.

This module validates already-produced evidence contracts. It does not build,
seal, publish, or mutate them and cannot authorize a controller, model, tool,
external action, or local run.

Verification reconciles five separately validated components:

* an embedded schema registry whose digest must be pinned by the manifest;
* a pre-run coverage document naming the complete required attempt plan,
  without leaking realized outcomes into preregistration;
* an exact receipt chain that commits every raw artifact and ends in a unique
  terminal event;
* a content-addressed inventory that commits exactly those raw artifacts plus
  the receipt; and
* a terminal index that commits exactly the raw artifacts, receipt, and custody
  inventory.

Artifact files are opened relative to one held directory descriptor and
symlinks are never followed. No writer or publication path is retained.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final

from ._receipt_chain import GENESIS_HASH, RECEIPT_ROW_SCHEMA_VERSION
from .contract import (
    CONTRACT_VERSION,
    REQUIRED_RAW_EVIDENCE_CLASSES,
    SHA_RE,
    TOKEN_RE,
    EpisodePhase,
    TerminalDisposition,
)
from .custody import (
    EVIDENCE_INVENTORY_SCHEMA_VERSION,
    EvidenceInventoryExpectation,
    SealedEvidenceInventory,
    load_evidence_inventory_with_root_fd,
    read_verified_evidence_object_with_root_fd,
    verify_evidence_inventory_with_root_fd,
)
from .errors import (
    CallerAnchorVerificationFailure,
    VerificationCustodyFailure,
    VerificationResourceLimitExceeded,
)
from .limits import (
    DEFAULT_VERIFICATION_LIMITS,
    VerificationLimits,
    validate_json_resource_envelope,
    validate_relative_path_resource,
)
from .run_graph import (
    RUN_ARTIFACT_DATA_CLASSES,
    AgenticRunGraph,
    AgenticRunSummary,
    TerminalAttemptRecord,
)

BUNDLE_SCHEMA_VERSION: Final = 3

COVERAGE_SCHEMA_VERSION: Final = 2

MANIFEST_BINDING_SCHEMA_VERSION: Final = 2

SCHEDULED_PAIR_BINDING_SCHEMA_VERSION: Final = 2

SCHEMA_REGISTRY_VERSION: Final = 2

READ_SIZE: Final = 1024 * 1024

AUTHORITY_STATUS: Final = "evidence_only_not_authorized"

RECEIPT_DATA_CLASS: Final = "terminal_bundle_receipt"

RECEIPT_TERMINAL_STATUS: Final = "sealed_no_authority"

TERMINAL_CLOSURE_LAW: Final = "raw_receipt_custody_terminal_v1"

COVERAGE_KIND: Final = "preregistered_required_attempt_plan"

PREREGISTRATION_CORE_DOMAIN: Final = "pre_run_core_excludes_snapshot_pair_coverage_bytes_v1"

SCHEDULE_PLAN_DOMAIN: Final = "pre_pair_plan_law_and_seed_v1"

TEMPORAL_ANCHOR_STATUS: Final = "external_pre_run_anchor_required"

CALLER_ANCHOR_STATUS_UNANCHORED: Final = "caller_anchor_values_absent"

CALLER_ANCHOR_STATUS_MATCHED: Final = "caller_supplied_three_anchor_values_matched"

EVIDENCE_STORE_INVENTORY_DATA_CLASS: Final = "evidence_store_inventory"

EVIDENCE_STORE_INVENTORY_VALIDATION_PROFILE: Final = "exact_content_addressed_inventory_v1"

ATTEMPT_WITNESS_PACK_SCHEMA_VERSION: Final = 1

MAX_ATTEMPT_WITNESS_COUNT: Final = 9

FAILURE_WITNESS_PACK_SCHEMA_VERSION: Final = 1

UTC_TIMESTAMP_RE: Final = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,9})?Z$"
)

RUN_SCOPED_EVIDENCE_CLASSES: Final = frozenset(RUN_ARTIFACT_DATA_CLASSES) | {
    "agentic_run_graph",
    "receipt_chain",
    "coverage_manifest",
    EVIDENCE_STORE_INVENTORY_DATA_CLASS,
}

EPISODE_PHASE_EVIDENCE_CLASSES: Final = frozenset(
    {
        "request_envelope",
        "response_envelope",
        "tool_trace",
        "prestate",
        "poststate",
        "checker_result",
        "checker_witness",
        "adjudication",
        "replay_comparison",
        "mutation_log",
        "control_evidence",
        "runtime_attestation",
        "terminal_disposition",
        "failure_artifact",
        "failure_witness",
    }
)

REQUIRED_EVIDENCE_CLASSES: Final = frozenset(REQUIRED_RAW_EVIDENCE_CLASSES) | {
    "coverage_manifest",
    EVIDENCE_STORE_INVENTORY_DATA_CLASS,
}

SOURCE_RUN_SCOPED_EVIDENCE_CLASSES: Final = RUN_SCOPED_EVIDENCE_CLASSES - {
    EVIDENCE_STORE_INVENTORY_DATA_CLASS
}

COMPLETED_INITIAL_EVIDENCE_CLASSES: Final = frozenset(
    {
        "request_envelope",
        "response_envelope",
        "tool_trace",
        "prestate",
        "poststate",
        "checker_result",
        "checker_witness",
        "adjudication",
        "mutation_log",
        "control_evidence",
        "runtime_attestation",
        "terminal_disposition",
    }
)

COMPLETED_REPLAY_EVIDENCE_CLASSES: Final = COMPLETED_INITIAL_EVIDENCE_CLASSES | {
    "replay_comparison"
}

NONCOMPLETED_EVIDENCE_CLASSES: Final = frozenset(
    {
        "control_evidence",
        "failure_artifact",
        "failure_witness",
        "terminal_disposition",
    }
)


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def _canonical_compact_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _canonical_compact_sha(document: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_compact_bytes(document)).hexdigest()


def _validate_sha(name: str, value: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _validate_token(name: str, value: str) -> str:
    if not isinstance(value, str) or not TOKEN_RE.fullmatch(value):
        raise ValueError(f"{name} must be a bounded identity token")
    return value


def _validate_positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _schema_scope(data_class: str) -> str:
    if data_class in RUN_SCOPED_EVIDENCE_CLASSES:
        return "run"
    if data_class in EPISODE_PHASE_EVIDENCE_CLASSES:
        return "episode_phase"
    raise ValueError(f"unknown terminal evidence class: {data_class}")


def _validation_profile(data_class: str) -> str:
    if data_class == "schema_registry":
        return "exact_embedded_schema_registry_v1"
    if data_class == "scheduled_pair_contracts":
        return "exact_scheduled_pair_bindings_v2"
    if data_class == "manifest_snapshot":
        return "exact_manifest_binding_v2"
    if data_class == "coverage_manifest":
        return "exact_required_attempt_plan_v2"
    if data_class == "agentic_run_graph":
        return "exact_agentic_run_graph_v1"
    if data_class == "summary":
        return "exact_agentic_run_summary_v1"
    if data_class == EVIDENCE_STORE_INVENTORY_DATA_CLASS:
        return EVIDENCE_STORE_INVENTORY_VALIDATION_PROFILE
    if data_class == "receipt_chain":
        return "exact_terminal_receipt_jsonl_v2"
    if data_class == "terminal_disposition":
        return "exact_terminal_attempt_record_v1"
    if data_class == "checker_witness":
        return "exact_attempt_witness_pack_v1"
    if data_class == "failure_witness":
        return "exact_failure_witness_pack_v1"
    return "content_addressed_attempt_binding_v2"


def _schema_registration(data_class: str) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "data_class": data_class,
        "registry_version": SCHEMA_REGISTRY_VERSION,
        "scope": _schema_scope(data_class),
        "validation_profile": _validation_profile(data_class),
    }


_TRUSTED_SCHEMA_ITEMS = tuple(
    (
        data_class,
        _canonical_compact_sha(_schema_registration(data_class)),
    )
    for data_class in sorted(REQUIRED_EVIDENCE_CLASSES)
)

TRUSTED_SCHEMA_SHA256_BY_CLASS: Final = MappingProxyType(dict(_TRUSTED_SCHEMA_ITEMS))

_TRUSTED_SCHEMA_REGISTRY_DOCUMENT = {
    "contract_version": CONTRACT_VERSION,
    "registrations": [
        {
            **_schema_registration(data_class),
            "schema_sha256": schema_sha256,
        }
        for data_class, schema_sha256 in _TRUSTED_SCHEMA_ITEMS
    ],
    "registry_version": SCHEMA_REGISTRY_VERSION,
}

TRUSTED_SCHEMA_REGISTRY_SHA256: Final = _canonical_compact_sha(_TRUSTED_SCHEMA_REGISTRY_DOCUMENT)

TRUSTED_SCHEMA_REGISTRY_BYTES: Final = _canonical_bytes(_TRUSTED_SCHEMA_REGISTRY_DOCUMENT)


@dataclass(frozen=True, slots=True)
class CoverageAttempt:
    """One attempt identity required by the preregistered run plan."""

    phase: EpisodePhase
    attempt_ordinal: int

    def __post_init__(self) -> None:
        if not isinstance(self.phase, EpisodePhase):
            raise TypeError("coverage phase must be an EpisodePhase")
        if isinstance(self.attempt_ordinal, bool) or not isinstance(self.attempt_ordinal, int):
            raise TypeError("coverage attempt_ordinal must be an integer")
        if self.phase is EpisodePhase.INITIAL and self.attempt_ordinal != 0:
            raise ValueError("initial coverage attempt requires ordinal zero")
        if self.phase is EpisodePhase.REPLAY and self.attempt_ordinal < 1:
            raise ValueError("replay coverage attempt requires a positive ordinal")

    def document(self) -> dict[str, Any]:
        return {
            "attempt_ordinal": self.attempt_ordinal,
            "phase": self.phase.value,
        }


@dataclass(frozen=True, slots=True)
class CoverageSlot:
    """One scheduled episode and its complete required attempt prefix."""

    scheduled_episode_sha256: str
    attempts: tuple[CoverageAttempt, ...]

    def __post_init__(self) -> None:
        _validate_sha("scheduled_episode_sha256", self.scheduled_episode_sha256)
        if not isinstance(self.attempts, tuple) or any(
            not isinstance(attempt, CoverageAttempt) for attempt in self.attempts
        ):
            raise TypeError("coverage attempts must be CoverageAttempt values")
        expected = (
            CoverageAttempt(EpisodePhase.INITIAL, 0),
            *(
                CoverageAttempt(EpisodePhase.REPLAY, ordinal)
                for ordinal in range(1, len(self.attempts))
            ),
        )
        if self.attempts != expected:
            raise ValueError(
                "coverage attempts must be initial zero followed by contiguous replays"
            )

    def document(self) -> dict[str, Any]:
        return {
            "scheduled_episode_sha256": self.scheduled_episode_sha256,
            "attempts": [attempt.document() for attempt in self.attempts],
        }


def _decode_canonical_base64(name: str, value: object) -> bytes:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a base64 string")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ValueError(f"{name} is not canonical base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError(f"{name} is not canonical base64")
    return decoded


@dataclass(frozen=True, slots=True)
class WitnessBlob:
    """One decisive witness payload embedded in a strict attempt pack."""

    role: str
    sha256: str
    payload: bytes

    def __post_init__(self) -> None:
        _validate_token("witness role", self.role)
        _validate_sha("witness sha256", self.sha256)
        if not isinstance(self.payload, bytes):
            raise TypeError("witness payload must be bytes")
        if hashlib.sha256(self.payload).hexdigest() != self.sha256:
            raise ValueError("witness payload does not match its SHA-256 digest")

    @classmethod
    def from_payload(cls, role: str, payload: bytes) -> WitnessBlob:
        if not isinstance(payload, bytes):
            raise TypeError("witness payload must be bytes")
        return cls(role, hashlib.sha256(payload).hexdigest(), payload)

    def document(self) -> dict[str, Any]:
        return {
            "payload_base64": base64.b64encode(self.payload).decode("ascii"),
            "role": self.role,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class AttemptWitnessPack:
    """Complete decisive witness bytes for one completed attempt."""

    scheduled_episode_sha256: str
    phase: EpisodePhase
    attempt_ordinal: int
    witnesses: tuple[WitnessBlob, ...]

    def __post_init__(self) -> None:
        _validate_sha("witness-pack scheduled episode", self.scheduled_episode_sha256)
        CoverageAttempt(self.phase, self.attempt_ordinal)
        if not isinstance(self.witnesses, tuple) or not self.witnesses:
            raise ValueError("attempt witness pack must contain witness payloads")
        if any(not isinstance(row, WitnessBlob) for row in self.witnesses):
            raise TypeError("attempt witness values must be WitnessBlob instances")
        roles = tuple(row.role for row in self.witnesses)
        if roles != tuple(sorted(roles)) or len(roles) != len(set(roles)):
            raise ValueError("attempt witness roles must be unique and ordered")

    @classmethod
    def build(
        cls,
        scheduled_episode_sha256: str,
        phase: EpisodePhase,
        attempt_ordinal: int,
        witnesses: dict[str, bytes],
    ) -> AttemptWitnessPack:
        if not isinstance(witnesses, dict):
            raise TypeError("witnesses must be a role-to-bytes dictionary")
        return cls(
            scheduled_episode_sha256,
            phase,
            attempt_ordinal,
            tuple(WitnessBlob.from_payload(role, witnesses[role]) for role in sorted(witnesses)),
        )

    def document(self) -> dict[str, Any]:
        return {
            "authority_status": AUTHORITY_STATUS,
            "attempt_ordinal": self.attempt_ordinal,
            "contract_version": CONTRACT_VERSION,
            "document_type": "agentic_attempt_witness_pack",
            "phase": self.phase.value,
            "scheduled_episode_sha256": self.scheduled_episode_sha256,
            "schema_version": ATTEMPT_WITNESS_PACK_SCHEMA_VERSION,
            "witnesses": [row.document() for row in self.witnesses],
        }

    @property
    def encoded(self) -> bytes:
        return _canonical_bytes(self.document())

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.encoded).hexdigest()

    @classmethod
    def from_bytes(
        cls,
        raw: bytes,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> AttemptWitnessPack:
        validate_json_resource_envelope(
            raw,
            label="attempt witness pack",
            limits=limits,
        )
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("attempt witness pack must be valid UTF-8 JSON") from exc
        expected = {
            "authority_status",
            "attempt_ordinal",
            "contract_version",
            "document_type",
            "phase",
            "scheduled_episode_sha256",
            "schema_version",
            "witnesses",
        }
        if not isinstance(document, dict) or set(document) != expected:
            raise ValueError("attempt witness pack schema mismatch")
        if document["authority_status"] != AUTHORITY_STATUS:
            raise ValueError("attempt witness pack cannot grant authority")
        if document["contract_version"] != CONTRACT_VERSION:
            raise ValueError("attempt witness pack contract mismatch")
        if document["document_type"] != "agentic_attempt_witness_pack":
            raise ValueError("attempt witness pack document type mismatch")
        if document["schema_version"] != ATTEMPT_WITNESS_PACK_SCHEMA_VERSION:
            raise ValueError("attempt witness pack schema version mismatch")
        rows = document["witnesses"]
        if not isinstance(rows, list):
            raise TypeError("attempt witness pack witnesses must be a list")
        if not rows or len(rows) > MAX_ATTEMPT_WITNESS_COUNT:
            raise ValueError(
                "attempt witness pack must contain between 1 and "
                f"{MAX_ATTEMPT_WITNESS_COUNT} witnesses"
            )
        witnesses: list[WitnessBlob] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or set(row) != {
                "payload_base64",
                "role",
                "sha256",
            }:
                raise ValueError(f"attempt witness row {index} schema mismatch")
            witnesses.append(
                WitnessBlob(
                    row["role"],
                    row["sha256"],
                    _decode_canonical_base64(f"attempt witness row {index}", row["payload_base64"]),
                )
            )
        try:
            phase = EpisodePhase(document["phase"])
        except (TypeError, ValueError) as exc:
            raise ValueError("attempt witness pack phase invalid") from exc
        pack = cls(
            document["scheduled_episode_sha256"],
            phase,
            document["attempt_ordinal"],
            tuple(witnesses),
        )
        if pack.encoded != raw:
            raise ValueError("attempt witness pack is not canonical JSON")
        return pack


@dataclass(frozen=True, slots=True)
class FailureWitnessPack:
    """Mechanical failure identity plus retained raw failure witness bytes."""

    scheduled_episode_sha256: str
    phase: EpisodePhase
    attempt_ordinal: int
    disposition: TerminalDisposition
    failure_artifact_sha256: str
    witness_payload: bytes

    def __post_init__(self) -> None:
        _validate_sha("failure witness scheduled episode", self.scheduled_episode_sha256)
        CoverageAttempt(self.phase, self.attempt_ordinal)
        if not isinstance(self.disposition, TerminalDisposition):
            raise TypeError("failure witness disposition must be TerminalDisposition")
        if self.disposition is TerminalDisposition.COMPLETED:
            raise ValueError("completed attempts cannot use a failure witness pack")
        _validate_sha("failure_artifact_sha256", self.failure_artifact_sha256)
        if not isinstance(self.witness_payload, bytes) or not self.witness_payload:
            raise ValueError("failure witness payload must be nonempty bytes")

    def document(self) -> dict[str, Any]:
        return {
            "authority_status": AUTHORITY_STATUS,
            "attempt_ordinal": self.attempt_ordinal,
            "contract_version": CONTRACT_VERSION,
            "disposition": self.disposition.value,
            "document_type": "agentic_failure_witness_pack",
            "failure_artifact_sha256": self.failure_artifact_sha256,
            "phase": self.phase.value,
            "scheduled_episode_sha256": self.scheduled_episode_sha256,
            "schema_version": FAILURE_WITNESS_PACK_SCHEMA_VERSION,
            "witness_payload_base64": base64.b64encode(self.witness_payload).decode("ascii"),
        }

    @property
    def encoded(self) -> bytes:
        return _canonical_bytes(self.document())

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.encoded).hexdigest()

    @classmethod
    def from_bytes(
        cls,
        raw: bytes,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> FailureWitnessPack:
        validate_json_resource_envelope(
            raw,
            label="failure witness pack",
            limits=limits,
        )
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("failure witness pack must be valid UTF-8 JSON") from exc
        expected = {
            "authority_status",
            "attempt_ordinal",
            "contract_version",
            "disposition",
            "document_type",
            "failure_artifact_sha256",
            "phase",
            "scheduled_episode_sha256",
            "schema_version",
            "witness_payload_base64",
        }
        if not isinstance(document, dict) or set(document) != expected:
            raise ValueError("failure witness pack schema mismatch")
        if document["authority_status"] != AUTHORITY_STATUS:
            raise ValueError("failure witness pack cannot grant authority")
        if document["contract_version"] != CONTRACT_VERSION:
            raise ValueError("failure witness pack contract mismatch")
        if document["document_type"] != "agentic_failure_witness_pack":
            raise ValueError("failure witness pack document type mismatch")
        if document["schema_version"] != FAILURE_WITNESS_PACK_SCHEMA_VERSION:
            raise ValueError("failure witness pack schema version mismatch")
        try:
            phase = EpisodePhase(document["phase"])
            disposition = TerminalDisposition(document["disposition"])
        except (TypeError, ValueError) as exc:
            raise ValueError("failure witness pack enum value invalid") from exc
        pack = cls(
            document["scheduled_episode_sha256"],
            phase,
            document["attempt_ordinal"],
            disposition,
            document["failure_artifact_sha256"],
            _decode_canonical_base64("failure witness payload", document["witness_payload_base64"]),
        )
        if pack.encoded != raw:
            raise ValueError("failure witness pack is not canonical JSON")
        return pack


@dataclass(frozen=True, slots=True)
class ScheduledPairCoverage:
    """The two child identities committed by one scheduled-pair contract."""

    scheduled_pair_sha256: str
    clean_episode_sha256: str
    attack_episode_sha256: str
    replay_law_sha256: str
    max_replays: int

    def __post_init__(self) -> None:
        for field in (
            "scheduled_pair_sha256",
            "clean_episode_sha256",
            "attack_episode_sha256",
            "replay_law_sha256",
        ):
            _validate_sha(field, getattr(self, field))
        if isinstance(self.max_replays, bool) or not isinstance(self.max_replays, int):
            raise TypeError("max_replays must be an integer")
        if self.max_replays < 0:
            raise ValueError("max_replays cannot be negative")
        if self.clean_episode_sha256 == self.attack_episode_sha256:
            raise ValueError("scheduled pair must commit distinct clean and attack children")

    def document(self) -> dict[str, Any]:
        return {
            "scheduled_pair_sha256": self.scheduled_pair_sha256,
            "clean_episode_sha256": self.clean_episode_sha256,
            "attack_episode_sha256": self.attack_episode_sha256,
            "replay_law_sha256": self.replay_law_sha256,
            "max_replays": self.max_replays,
        }


@dataclass(frozen=True, slots=True)
class ScheduledPairContractsBinding:
    """Exact pair-to-child and probability-measure joins for one schedule."""

    run_id: str
    schedule_plan_sha256: str
    probability_measure_contract_sha256: str
    pairs: tuple[ScheduledPairCoverage, ...]

    def __post_init__(self) -> None:
        _validate_token("scheduled-pair run_id", self.run_id)
        _validate_sha(
            "scheduled-pair schedule_plan_sha256",
            self.schedule_plan_sha256,
        )
        _validate_sha(
            "scheduled-pair probability_measure_contract_sha256",
            self.probability_measure_contract_sha256,
        )
        if not isinstance(self.pairs, tuple) or not self.pairs:
            raise ValueError("scheduled-pair binding must contain at least one pair")
        if any(not isinstance(pair, ScheduledPairCoverage) for pair in self.pairs):
            raise TypeError("scheduled-pair entries must be ScheduledPairCoverage values")
        pair_digests = [pair.scheduled_pair_sha256 for pair in self.pairs]
        if len(pair_digests) != len(set(pair_digests)):
            raise ValueError("scheduled-pair binding has duplicate pair identities")
        if pair_digests != sorted(pair_digests):
            raise ValueError("scheduled-pair bindings must be canonically ordered")
        child_digests = [
            child
            for pair in self.pairs
            for child in (
                pair.clean_episode_sha256,
                pair.attack_episode_sha256,
            )
        ]
        if len(child_digests) != len(set(child_digests)):
            raise ValueError("a scheduled episode cannot belong to multiple pairs")

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEDULED_PAIR_BINDING_SCHEMA_VERSION,
            "contract_version": CONTRACT_VERSION,
            "authority_status": AUTHORITY_STATUS,
            "run_id": self.run_id,
            "schedule_plan_domain": SCHEDULE_PLAN_DOMAIN,
            "schedule_plan_sha256": self.schedule_plan_sha256,
            "probability_measure_contract_sha256": (self.probability_measure_contract_sha256),
            "schema_registry_sha256": TRUSTED_SCHEMA_REGISTRY_SHA256,
            "pairs": [pair.document() for pair in self.pairs],
        }

    @property
    def encoded(self) -> bytes:
        return _canonical_bytes(self.document())

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.encoded).hexdigest()

    @classmethod
    def from_bytes(
        cls,
        raw: bytes,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> ScheduledPairContractsBinding:
        validate_json_resource_envelope(
            raw,
            label="scheduled-pair contracts",
            limits=limits,
        )
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("scheduled-pair contracts must be valid UTF-8 JSON") from exc
        expected_keys = {
            "schema_version",
            "contract_version",
            "authority_status",
            "run_id",
            "schedule_plan_domain",
            "schedule_plan_sha256",
            "probability_measure_contract_sha256",
            "schema_registry_sha256",
            "pairs",
        }
        if not isinstance(document, dict) or set(document) != expected_keys:
            raise ValueError("scheduled-pair contracts binding schema mismatch")
        if type(document["schema_version"]) is not int:
            raise TypeError("scheduled-pair schema_version must be an integer")
        if document["schema_version"] != SCHEDULED_PAIR_BINDING_SCHEMA_VERSION:
            raise ValueError("scheduled-pair contracts binding version mismatch")
        if document["contract_version"] != CONTRACT_VERSION:
            raise ValueError("scheduled-pair contracts contract version mismatch")
        if document["authority_status"] != AUTHORITY_STATUS:
            raise ValueError("scheduled-pair contracts cannot grant execution authority")
        if document["schedule_plan_domain"] != SCHEDULE_PLAN_DOMAIN:
            raise ValueError("scheduled-pair plan domain mismatch")
        if document["schema_registry_sha256"] != TRUSTED_SCHEMA_REGISTRY_SHA256:
            raise ValueError("scheduled-pair contracts do not pin the trusted schema registry")
        pair_rows = document["pairs"]
        if not isinstance(pair_rows, list):
            raise TypeError("scheduled-pair entries must be a list")
        if len(pair_rows) > limits.scheduled_pairs:
            raise ValueError(
                "scheduled-pair entries exceed scheduled_pairs="
                f"{limits.scheduled_pairs}; "
                "next action: split the run into independently verified terminal bundles"
            )
        pairs: list[ScheduledPairCoverage] = []
        for index, row in enumerate(pair_rows):
            if not isinstance(row, dict) or set(row) != {
                "scheduled_pair_sha256",
                "clean_episode_sha256",
                "attack_episode_sha256",
                "replay_law_sha256",
                "max_replays",
            }:
                raise ValueError(f"scheduled-pair entry {index} schema mismatch")
            pairs.append(ScheduledPairCoverage(**row))
        binding = cls(
            run_id=document["run_id"],
            schedule_plan_sha256=document["schedule_plan_sha256"],
            probability_measure_contract_sha256=(document["probability_measure_contract_sha256"]),
            pairs=tuple(pairs),
        )
        if binding.encoded != raw:
            raise ValueError("scheduled-pair contracts binding is not canonical JSON")
        return binding


@dataclass(frozen=True, slots=True)
class EvidenceCoverageManifest:
    """Manifest-pinned enumeration of every scheduled episode/phase."""

    run_id: str
    execution_identity_sha256: str
    schedule_plan_sha256: str
    probability_measure_contract_sha256: str
    scheduled_pair_contracts_sha256: str
    slots: tuple[CoverageSlot, ...]

    def __post_init__(self) -> None:
        _validate_token("coverage run_id", self.run_id)
        _validate_sha(
            "coverage execution_identity_sha256",
            self.execution_identity_sha256,
        )
        _validate_sha("coverage schedule_plan_sha256", self.schedule_plan_sha256)
        _validate_sha(
            "coverage probability_measure_contract_sha256",
            self.probability_measure_contract_sha256,
        )
        _validate_sha(
            "coverage scheduled_pair_contracts_sha256",
            self.scheduled_pair_contracts_sha256,
        )
        if not isinstance(self.slots, tuple) or not self.slots:
            raise ValueError("coverage manifest must contain at least one scheduled slot")
        if any(not isinstance(slot, CoverageSlot) for slot in self.slots):
            raise TypeError("coverage slots must be CoverageSlot values")
        identities = [slot.scheduled_episode_sha256 for slot in self.slots]
        if len(identities) != len(set(identities)):
            raise ValueError("coverage manifest has duplicate scheduled episodes")
        if identities != sorted(identities):
            raise ValueError("coverage slots must be canonically ordered by episode digest")

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": COVERAGE_SCHEMA_VERSION,
            "contract_version": CONTRACT_VERSION,
            "authority_status": AUTHORITY_STATUS,
            "coverage_kind": COVERAGE_KIND,
            "run_id": self.run_id,
            "schedule_plan_domain": SCHEDULE_PLAN_DOMAIN,
            "execution_identity_sha256": self.execution_identity_sha256,
            "schedule_plan_sha256": self.schedule_plan_sha256,
            "probability_measure_contract_sha256": (self.probability_measure_contract_sha256),
            "scheduled_pair_contracts_sha256": (self.scheduled_pair_contracts_sha256),
            "schema_registry_sha256": TRUSTED_SCHEMA_REGISTRY_SHA256,
            "slots": [slot.document() for slot in self.slots],
        }

    @property
    def encoded(self) -> bytes:
        return _canonical_bytes(self.document())

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.encoded).hexdigest()

    @classmethod
    def from_bytes(
        cls,
        raw: bytes,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> EvidenceCoverageManifest:
        validate_json_resource_envelope(
            raw,
            label="coverage manifest",
            limits=limits,
        )
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("coverage manifest must be valid UTF-8 JSON") from exc
        expected_keys = {
            "schema_version",
            "contract_version",
            "authority_status",
            "coverage_kind",
            "run_id",
            "schedule_plan_domain",
            "execution_identity_sha256",
            "schedule_plan_sha256",
            "probability_measure_contract_sha256",
            "scheduled_pair_contracts_sha256",
            "schema_registry_sha256",
            "slots",
        }
        if not isinstance(document, dict) or set(document) != expected_keys:
            raise ValueError("coverage manifest schema mismatch")
        if type(document["schema_version"]) is not int:
            raise TypeError("coverage schema_version must be an integer")
        if document["schema_version"] != COVERAGE_SCHEMA_VERSION:
            raise ValueError("coverage manifest version mismatch")
        if document["contract_version"] != CONTRACT_VERSION:
            raise ValueError("coverage contract version mismatch")
        if document["authority_status"] != AUTHORITY_STATUS:
            raise ValueError("coverage manifest cannot grant execution authority")
        if document["coverage_kind"] != COVERAGE_KIND:
            raise ValueError("coverage manifest is not a required-attempt contract")
        if document["schedule_plan_domain"] != SCHEDULE_PLAN_DOMAIN:
            raise ValueError("coverage manifest schedule-plan domain mismatch")
        if document["schema_registry_sha256"] != TRUSTED_SCHEMA_REGISTRY_SHA256:
            raise ValueError("coverage manifest does not pin the trusted schema registry")
        slot_rows = document["slots"]
        if not isinstance(slot_rows, list):
            raise TypeError("coverage slots must be a list")
        if len(slot_rows) > limits.scheduled_pairs * 2:
            raise ValueError(
                "coverage slots exceed scheduled episode capacity="
                f"{limits.scheduled_pairs * 2}; "
                "next action: split the run into independently verified terminal bundles"
            )
        attempt_count = 0
        for row in slot_rows:
            if not isinstance(row, dict):
                raise TypeError("coverage slot must be a JSON object")
            attempts = row.get("attempts")
            if not isinstance(attempts, list):
                raise TypeError("coverage slot attempts must be a list")
            attempt_count += len(attempts)
            if attempt_count > limits.terminal_attempts:
                raise ValueError(
                    "coverage attempts exceed terminal_attempts="
                    f"{limits.terminal_attempts}; "
                    "next action: split the run into independently verified terminal bundles"
                )
        slots: list[CoverageSlot] = []
        for index, row in enumerate(slot_rows):
            if not isinstance(row, dict) or set(row) != {
                "scheduled_episode_sha256",
                "attempts",
            }:
                raise ValueError(f"coverage slot {index} schema mismatch")
            attempts = row["attempts"]
            if not isinstance(attempts, list):
                raise TypeError(f"coverage slot {index} attempts must be a list")
            typed_attempts: list[CoverageAttempt] = []
            for attempt_index, attempt in enumerate(attempts):
                if not isinstance(attempt, dict) or set(attempt) != {
                    "phase",
                    "attempt_ordinal",
                }:
                    raise ValueError(
                        f"coverage slot {index} attempt {attempt_index} schema mismatch"
                    )
                try:
                    phase = EpisodePhase(attempt["phase"])
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"coverage slot {index} attempt {attempt_index} phase invalid"
                    ) from exc
                typed_attempts.append(CoverageAttempt(phase, attempt["attempt_ordinal"]))
            slots.append(CoverageSlot(row["scheduled_episode_sha256"], tuple(typed_attempts)))
        manifest = cls(
            run_id=document["run_id"],
            execution_identity_sha256=document["execution_identity_sha256"],
            schedule_plan_sha256=document["schedule_plan_sha256"],
            probability_measure_contract_sha256=(document["probability_measure_contract_sha256"]),
            scheduled_pair_contracts_sha256=(document["scheduled_pair_contracts_sha256"]),
            slots=tuple(slots),
        )
        if manifest.encoded != raw:
            raise ValueError("coverage manifest is not canonical JSON")
        return manifest


@dataclass(frozen=True, slots=True)
class ManifestSnapshotBinding:
    """The exact preregistration fields that close the terminal trust chain."""

    run_id: str
    preregistration_core_sha256: str
    execution_identity_sha256: str
    schedule_plan_sha256: str
    probability_measure_contract_sha256: str
    scheduled_pair_contracts_sha256: str
    coverage_manifest_sha256: str

    def __post_init__(self) -> None:
        _validate_token("manifest run_id", self.run_id)
        _validate_sha("preregistration_core_sha256", self.preregistration_core_sha256)
        _validate_sha(
            "manifest execution_identity_sha256",
            self.execution_identity_sha256,
        )
        _validate_sha("manifest schedule_plan_sha256", self.schedule_plan_sha256)
        _validate_sha(
            "manifest probability_measure_contract_sha256",
            self.probability_measure_contract_sha256,
        )
        _validate_sha(
            "manifest scheduled_pair_contracts_sha256",
            self.scheduled_pair_contracts_sha256,
        )
        _validate_sha(
            "manifest coverage_manifest_sha256",
            self.coverage_manifest_sha256,
        )

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": MANIFEST_BINDING_SCHEMA_VERSION,
            "contract_version": CONTRACT_VERSION,
            "authority_status": AUTHORITY_STATUS,
            "run_id": self.run_id,
            "preregistration_core_domain": PREREGISTRATION_CORE_DOMAIN,
            "preregistration_core_sha256": self.preregistration_core_sha256,
            "schedule_plan_domain": SCHEDULE_PLAN_DOMAIN,
            "execution_identity_sha256": self.execution_identity_sha256,
            "schedule_plan_sha256": self.schedule_plan_sha256,
            "probability_measure_contract_sha256": (self.probability_measure_contract_sha256),
            "scheduled_pair_contracts_sha256": (self.scheduled_pair_contracts_sha256),
            "coverage_manifest_sha256": self.coverage_manifest_sha256,
            "schema_registry_sha256": TRUSTED_SCHEMA_REGISTRY_SHA256,
        }

    @property
    def encoded(self) -> bytes:
        return _canonical_bytes(self.document())

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.encoded).hexdigest()

    @classmethod
    def from_bytes(
        cls,
        raw: bytes,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> ManifestSnapshotBinding:
        validate_json_resource_envelope(
            raw,
            label="manifest snapshot",
            limits=limits,
        )
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("manifest snapshot must be valid UTF-8 JSON") from exc
        expected_keys = {
            "schema_version",
            "contract_version",
            "authority_status",
            "run_id",
            "preregistration_core_domain",
            "preregistration_core_sha256",
            "schedule_plan_domain",
            "execution_identity_sha256",
            "schedule_plan_sha256",
            "probability_measure_contract_sha256",
            "scheduled_pair_contracts_sha256",
            "coverage_manifest_sha256",
            "schema_registry_sha256",
        }
        if not isinstance(document, dict) or set(document) != expected_keys:
            raise ValueError("manifest snapshot binding schema mismatch")
        if type(document["schema_version"]) is not int:
            raise TypeError("manifest schema_version must be an integer")
        if document["schema_version"] != MANIFEST_BINDING_SCHEMA_VERSION:
            raise ValueError("manifest snapshot binding version mismatch")
        if document["contract_version"] != CONTRACT_VERSION:
            raise ValueError("manifest snapshot contract version mismatch")
        if document["authority_status"] != AUTHORITY_STATUS:
            raise ValueError("manifest snapshot cannot grant execution authority")
        if document["preregistration_core_domain"] != PREREGISTRATION_CORE_DOMAIN:
            raise ValueError("manifest snapshot preregistration domain mismatch")
        if document["schedule_plan_domain"] != SCHEDULE_PLAN_DOMAIN:
            raise ValueError("manifest snapshot schedule-plan domain mismatch")
        if document["schema_registry_sha256"] != TRUSTED_SCHEMA_REGISTRY_SHA256:
            raise ValueError("manifest snapshot does not pin the trusted schema registry")
        binding = cls(
            run_id=document["run_id"],
            preregistration_core_sha256=document["preregistration_core_sha256"],
            execution_identity_sha256=document["execution_identity_sha256"],
            schedule_plan_sha256=document["schedule_plan_sha256"],
            probability_measure_contract_sha256=(document["probability_measure_contract_sha256"]),
            scheduled_pair_contracts_sha256=(document["scheduled_pair_contracts_sha256"]),
            coverage_manifest_sha256=document["coverage_manifest_sha256"],
        )
        if binding.encoded != raw:
            raise ValueError("manifest snapshot binding is not canonical JSON")
        return binding


def _validate_relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("artifact path must be a non-empty canonical POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        raise ValueError("artifact path must be canonical and relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("artifact path cannot contain empty, dot, or parent components")
    return path


def _validate_logical_artifact_path(data_class: str, value: str) -> PurePosixPath:
    path = _validate_relative_path(value)
    reserved = {"objects", "inventories", ".staging"}
    if data_class == EVIDENCE_STORE_INVENTORY_DATA_CLASS:
        if path.parts[0] != "inventories":
            raise ValueError("inventory artifact must use the inventory namespace")
    elif path.parts[0] in reserved:
        raise ValueError("logical evidence paths cannot use custody namespaces")
    return path


@dataclass(frozen=True, slots=True)
class EvidenceStoreBinding:
    """The six exact inventory fields carried by a terminal index."""

    inventory_relative_path: str
    inventory_sha256: str
    inventory_root_sha256: str
    inventory_size: int
    inventory_entry_count: int
    inventory_schema_version: int = EVIDENCE_INVENTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        path = _validate_relative_path(self.inventory_relative_path)
        if path.parts[:2] != ("inventories", "sha256"):
            raise ValueError("evidence-store inventory path uses an unsafe namespace")
        _validate_sha("inventory_sha256", self.inventory_sha256)
        _validate_sha("inventory_root_sha256", self.inventory_root_sha256)
        if isinstance(self.inventory_size, bool) or not isinstance(self.inventory_size, int):
            raise TypeError("inventory_size must be an integer")
        if self.inventory_size < 1:
            raise ValueError("inventory_size must be positive")
        _validate_positive_int("inventory_entry_count", self.inventory_entry_count)
        if type(self.inventory_schema_version) is not int:
            raise TypeError("inventory_schema_version must be an integer")
        if self.inventory_schema_version != EVIDENCE_INVENTORY_SCHEMA_VERSION:
            raise ValueError("evidence-store inventory schema version mismatch")

    @classmethod
    def from_terminal_binding(cls, document: dict[str, Any]) -> EvidenceStoreBinding:
        expected = {
            "evidence_store_inventory_entry_count",
            "evidence_store_inventory_relative_path",
            "evidence_store_inventory_root_sha256",
            "evidence_store_inventory_schema_version",
            "evidence_store_inventory_sha256",
            "evidence_store_inventory_size",
        }
        if not isinstance(document, dict) or set(document) != expected:
            raise ValueError("evidence-store terminal binding schema mismatch")
        return cls(
            inventory_relative_path=document["evidence_store_inventory_relative_path"],
            inventory_sha256=document["evidence_store_inventory_sha256"],
            inventory_root_sha256=document["evidence_store_inventory_root_sha256"],
            inventory_size=document["evidence_store_inventory_size"],
            inventory_entry_count=document["evidence_store_inventory_entry_count"],
            inventory_schema_version=document["evidence_store_inventory_schema_version"],
        )

    def document(self) -> dict[str, Any]:
        return {
            "evidence_store_inventory_entry_count": self.inventory_entry_count,
            "evidence_store_inventory_relative_path": self.inventory_relative_path,
            "evidence_store_inventory_root_sha256": self.inventory_root_sha256,
            "evidence_store_inventory_schema_version": self.inventory_schema_version,
            "evidence_store_inventory_sha256": self.inventory_sha256,
            "evidence_store_inventory_size": self.inventory_size,
        }


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """A trusted-schema artifact location and its preregistered coverage slot."""

    data_class: str
    relative_path: str
    scheduled_episode_sha256: str | None = None
    phase: EpisodePhase | None = None
    attempt_ordinal: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.data_class, str):
            raise TypeError("data_class must be a string")
        if self.data_class not in TRUSTED_SCHEMA_SHA256_BY_CLASS:
            raise ValueError(f"data_class is not in the trusted schema registry: {self.data_class}")
        _validate_logical_artifact_path(self.data_class, self.relative_path)
        scope = _schema_scope(self.data_class)
        if scope == "run":
            if (
                self.scheduled_episode_sha256 is not None
                or self.phase is not None
                or self.attempt_ordinal is not None
            ):
                raise ValueError("run-scoped evidence cannot carry attempt identity")
            return
        if self.scheduled_episode_sha256 is None:
            raise ValueError("episode-phase evidence requires a scheduled episode digest")
        _validate_sha(
            "artifact scheduled_episode_sha256",
            self.scheduled_episode_sha256,
        )
        if not isinstance(self.phase, EpisodePhase):
            raise TypeError("episode evidence requires an EpisodePhase")
        if isinstance(self.attempt_ordinal, bool) or not isinstance(self.attempt_ordinal, int):
            raise TypeError("episode evidence requires an attempt ordinal")
        CoverageAttempt(self.phase, self.attempt_ordinal)


@dataclass(frozen=True, slots=True)
class ReceiptRange:
    row_count: int
    first_row_hash: str
    last_row_hash: str

    def __post_init__(self) -> None:
        _validate_positive_int("receipt row_count", self.row_count)
        _validate_sha("first_row_hash", self.first_row_hash)
        _validate_sha("last_row_hash", self.last_row_hash)

    def document(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "first_row_hash": self.first_row_hash,
            "last_row_hash": self.last_row_hash,
        }


@dataclass(frozen=True, slots=True)
class TerminalBundle:
    encoded: bytes
    evidence_root_sha256: str
    bundle_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.encoded, bytes):
            raise TypeError("terminal bundle encoding must be bytes")
        _validate_sha("evidence_root_sha256", self.evidence_root_sha256)
        _validate_sha("bundle_sha256", self.bundle_sha256)
        try:
            document = json.loads(self.encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("terminal bundle is not valid UTF-8 JSON") from exc
        _validate_bundle_document(document, self.encoded, limits=None)
        if document["evidence_root_sha256"] != self.evidence_root_sha256:
            raise ValueError("terminal bundle evidence-root field mismatch")
        if hashlib.sha256(self.encoded).hexdigest() != self.bundle_sha256:
            raise ValueError("terminal bundle encoded hash mismatch")

    @property
    def document(self) -> dict[str, Any]:
        document = json.loads(self.encoded)
        if not isinstance(document, dict):
            raise TypeError("validated terminal bundle decoded to a non-object")
        return document


@dataclass(frozen=True, slots=True)
class VerifiedTerminalProjection:
    """No-authority content projection from one sequential held-fd verification.

    Caller anchor values are retained and cross-bound rather than represented by
    a freely replaceable Boolean.  Their presence proves only that the supplied
    digest values matched during verification; it does not authenticate their
    source or prove that the manifest value existed before execution.
    """

    bundle: TerminalBundle
    graph: AgenticRunGraph
    summary: AgenticRunSummary
    summary_sha256: str
    evidence_store_binding: EvidenceStoreBinding
    may_authorize_external_action: bool = False
    caller_bundle_sha256: str | None = None
    caller_evidence_root_sha256: str | None = None
    caller_manifest_snapshot_artifact_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.bundle, TerminalBundle):
            raise TypeError("bundle must be a TerminalBundle")
        if not isinstance(self.graph, AgenticRunGraph):
            raise TypeError("graph must be an AgenticRunGraph")
        if self.summary != self.graph.summary:
            raise ValueError("projection summary differs from the verified graph")
        if self.summary_sha256 != self.summary.digest:
            raise ValueError("projection summary digest mismatch")
        if not isinstance(self.evidence_store_binding, EvidenceStoreBinding):
            raise TypeError("projection requires an EvidenceStoreBinding")
        document = self.bundle.document
        if self.graph.run_id != document["run_id"]:
            raise ValueError("projection graph run_id differs from terminal bundle")
        if self.graph.digest != document["agentic_run_graph_sha256"]:
            raise ValueError("projection graph digest differs from terminal bundle")
        terminal_binding = {
            key: document[key]
            for key in (
                "evidence_store_inventory_entry_count",
                "evidence_store_inventory_relative_path",
                "evidence_store_inventory_root_sha256",
                "evidence_store_inventory_schema_version",
                "evidence_store_inventory_sha256",
                "evidence_store_inventory_size",
            )
        }
        if self.evidence_store_binding.document() != terminal_binding:
            raise ValueError("projection evidence-store binding differs from terminal bundle")
        summary_rows = [row for row in document["artifacts"] if row["data_class"] == "summary"]
        if len(summary_rows) != 1 or summary_rows[0]["sha256"] != self.summary_sha256:
            raise ValueError("projection summary digest differs from terminal artifact binding")
        anchors = (
            self.caller_bundle_sha256,
            self.caller_evidence_root_sha256,
            self.caller_manifest_snapshot_artifact_sha256,
        )
        if any(value is not None for value in anchors) and not all(
            value is not None for value in anchors
        ):
            raise ValueError("projection caller anchors must be present together")
        if all(value is not None for value in anchors):
            for name, value in (
                ("caller_bundle_sha256", self.caller_bundle_sha256),
                ("caller_evidence_root_sha256", self.caller_evidence_root_sha256),
                (
                    "caller_manifest_snapshot_artifact_sha256",
                    self.caller_manifest_snapshot_artifact_sha256,
                ),
            ):
                _validate_sha(name, value)
            if anchors != (
                self.bundle.bundle_sha256,
                self.bundle.evidence_root_sha256,
                document["manifest_snapshot_artifact_sha256"],
            ):
                raise ValueError("projection caller anchors differ from verified content")
        if self.may_authorize_external_action is not False:
            raise ValueError("verified evidence cannot authorize external action")

    @property
    def caller_anchor_match(self) -> bool:
        return self.caller_bundle_sha256 is not None

    @property
    def anchor_status(self) -> str:
        return (
            CALLER_ANCHOR_STATUS_MATCHED
            if self.caller_anchor_match
            else CALLER_ANCHOR_STATUS_UNANCHORED
        )


class AgenticTrustVerificationError(ValueError):
    """Stable public failure with a machine reason and operator remediation."""

    def __init__(
        self,
        *,
        reason_code: str,
        target: str,
        detail: str,
        next_action: str,
    ) -> None:
        self.reason_code = reason_code
        self.target = target
        self.detail = detail
        self.next_action = next_action
        suffix = "" if "next action:" in detail.lower() else f"; next action: {next_action}"
        super().__init__(f"{reason_code}: {detail}; target={target}{suffix}")


def _validated_root(root: Path) -> Path:
    root = root.absolute()
    try:
        info = root.lstat()
    except FileNotFoundError as exc:
        raise VerificationCustodyFailure("bundle root does not exist") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise VerificationCustodyFailure("bundle root must be a real directory, not a symlink")
    return root


def _open_root_directory(root: Path) -> int:
    root_info = root.lstat()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    directory_fd = -1
    try:
        absolute = root.absolute()
        directory_fd = os.open("/", flags)
        for part in absolute.parts[1:]:
            child_fd = os.open(part, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        root_fd = directory_fd
        directory_fd = -1
    except OSError as exc:
        if directory_fd >= 0:
            os.close(directory_fd)
        raise VerificationCustodyFailure(
            "bundle root or an ancestor could not be opened without symlinks"
        ) from exc
    try:
        opened_root = os.fstat(root_fd)
        if (opened_root.st_dev, opened_root.st_ino) != (
            root_info.st_dev,
            root_info.st_ino,
        ):
            raise VerificationCustodyFailure("bundle root changed while acquiring its descriptor")
        return root_fd
    except Exception:
        os.close(root_fd)
        raise


def _assert_root_path_still_bound(root: Path, root_fd: int) -> None:
    path_info = root.lstat()
    opened_root = os.fstat(root_fd)
    reopened_fd = -1
    try:
        reopened_fd = _open_root_directory(root)
        reopened = os.fstat(reopened_fd)
        expected = (opened_root.st_dev, opened_root.st_ino)
        if (
            stat.S_ISLNK(path_info.st_mode)
            or (path_info.st_dev, path_info.st_ino) != expected
            or (reopened.st_dev, reopened.st_ino) != expected
        ):
            raise VerificationCustodyFailure(
                "bundle root path changed while its descriptor was held"
            )
    except (OSError, ValueError) as exc:
        raise VerificationCustodyFailure(
            "bundle root path changed while its descriptor was held"
        ) from exc
    finally:
        if reopened_fd >= 0:
            os.close(reopened_fd)


def _open_parent_directory(
    root_fd: int,
    relative_path: str,
) -> tuple[int, str, PurePosixPath]:
    relative = _validate_relative_path(relative_path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    directory_fd = os.dup(root_fd)
    try:
        for part in relative.parts[:-1]:
            try:
                child_fd = os.open(part, flags, dir_fd=directory_fd)
            except OSError as exc:
                raise VerificationCustodyFailure(
                    f"bundle path parent is absent, non-directory, or a symlink: {relative_path}"
                ) from exc
            os.close(directory_fd)
            directory_fd = child_fd
        return directory_fd, relative.parts[-1], relative
    except Exception:
        os.close(directory_fd)
        raise


def _observe_regular_fd(
    fd: int,
    *,
    display_name: str,
    retain_bytes: bool,
    max_bytes: int,
    limit_name: str,
) -> tuple[str, int, int, bytes | None]:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise VerificationCustodyFailure(f"artifact is not a regular file: {display_name}")
    if before.st_size > max_bytes:
        raise VerificationResourceLimitExceeded(
            f"artifact exceeds {limit_name}={max_bytes}: {display_name}; "
            "next action: split the evidence before verification"
        )
    digest = hashlib.sha256()
    retained: list[bytes] | None = [] if retain_bytes else None
    observed_size = 0
    while True:
        chunk = os.read(fd, READ_SIZE)
        if not chunk:
            break
        digest.update(chunk)
        observed_size += len(chunk)
        if observed_size > max_bytes:
            raise VerificationResourceLimitExceeded(
                f"artifact grew beyond {limit_name}={max_bytes}: {display_name}; "
                "next action: quarantine the mutable artifact and retry from immutable custody"
            )
        if retained is not None:
            retained.append(chunk)
    after = os.fstat(fd)
    stable = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if not stable:
        raise VerificationCustodyFailure(f"artifact changed while hashing: {display_name}")
    raw = b"".join(retained) if retained is not None else None
    return digest.hexdigest(), before.st_size, stat.S_IMODE(before.st_mode), raw


def _observe_confined_regular_file(
    root_fd: int,
    relative_path: str,
    *,
    retain_bytes: bool = False,
    max_bytes: int,
    limit_name: str,
) -> tuple[str, int, int, bytes | None]:
    parent_fd, final_name, _ = _open_parent_directory(root_fd, relative_path)
    opened: os.stat_result | None = None
    result: tuple[str, int, int, bytes | None] | None = None
    try:
        try:
            fd = os.open(
                final_name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise VerificationCustodyFailure(
                f"artifact is absent or a forbidden symlink: {relative_path}"
            ) from exc
        try:
            opened = os.fstat(fd)
            if opened.st_nlink != 1:
                raise VerificationCustodyFailure(
                    f"artifact must have exactly one hard link: {relative_path}"
                )
            result = _observe_regular_fd(
                fd,
                display_name=relative_path,
                retain_bytes=retain_bytes,
                max_bytes=max_bytes,
                limit_name=limit_name,
            )
            named = os.stat(final_name, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(named.st_mode) or (
                named.st_dev,
                named.st_ino,
                named.st_size,
                named.st_mtime_ns,
                named.st_ctime_ns,
            ) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            ):
                raise VerificationCustodyFailure(
                    f"artifact path changed while hashing: {relative_path}"
                )
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)
    if opened is None or result is None:
        raise AssertionError("artifact observation completed without an identity")
    rebound_parent_fd, rebound_name, _ = _open_parent_directory(root_fd, relative_path)
    try:
        rebound = os.stat(
            rebound_name,
            dir_fd=rebound_parent_fd,
            follow_symlinks=False,
        )
    finally:
        os.close(rebound_parent_fd)
    if not stat.S_ISREG(rebound.st_mode) or (
        rebound.st_dev,
        rebound.st_ino,
        rebound.st_size,
        rebound.st_mtime_ns,
        rebound.st_ctime_ns,
    ) != (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        opened.st_mtime_ns,
        opened.st_ctime_ns,
    ):
        raise VerificationCustodyFailure(f"artifact path was rebound while read: {relative_path}")
    return result


def _artifact_sort_key(spec_or_row: ArtifactSpec | dict[str, Any]) -> tuple[str, str]:
    if isinstance(spec_or_row, ArtifactSpec):
        return spec_or_row.relative_path, spec_or_row.data_class
    return spec_or_row["relative_path"], spec_or_row["data_class"]


def _artifact_row(
    spec: ArtifactSpec,
    *,
    digest: str,
    size: int,
) -> dict[str, Any]:
    return {
        "data_class": spec.data_class,
        "relative_path": spec.relative_path,
        "schema_sha256": TRUSTED_SCHEMA_SHA256_BY_CLASS[spec.data_class],
        "scheduled_episode_sha256": spec.scheduled_episode_sha256,
        "phase": spec.phase.value if spec.phase is not None else None,
        "attempt_ordinal": spec.attempt_ordinal,
        "sha256": digest,
        "size": size,
    }


@dataclass(frozen=True, slots=True)
class _ObservedInventory:
    rows: tuple[dict[str, Any], ...]
    retained_by_class: dict[str, bytes]
    retained_by_path: dict[str, bytes]


def _validate_spec_inventory(
    specs: tuple[ArtifactSpec, ...],
    *,
    include_receipt: bool,
) -> None:
    if not specs:
        raise ValueError("terminal bundle requires an explicit artifact inventory")
    if any(not isinstance(spec, ArtifactSpec) for spec in specs):
        raise TypeError("terminal inventory values must be ArtifactSpec instances")
    paths = [spec.relative_path for spec in specs]
    if len(paths) != len(set(paths)):
        raise ValueError("terminal bundle artifact paths must be unique")
    counts = Counter(spec.data_class for spec in specs)
    if any(spec.data_class == EVIDENCE_STORE_INVENTORY_DATA_CLASS for spec in specs):
        raise ValueError("custody inventory is derived, not a source artifact spec")
    expected_run_classes = set(SOURCE_RUN_SCOPED_EVIDENCE_CLASSES)
    if not include_receipt:
        expected_run_classes.remove("receipt_chain")
    for data_class in expected_run_classes:
        if counts[data_class] != 1:
            raise ValueError(f"terminal inventory requires exactly one {data_class} artifact")
    expected_receipt_count = 1 if include_receipt else 0
    if counts["receipt_chain"] != expected_receipt_count:
        raise ValueError(
            f"terminal inventory requires exactly {expected_receipt_count} receipt-chain artifacts"
        )


@dataclass(frozen=True, slots=True)
class _InventoryBindings:
    graph_sha256: str
    graph: AgenticRunGraph
    probability_measure_contract_sha256: str
    schedule_plan_sha256: str
    scheduled_pair_contracts_sha256: str
    coverage_manifest_sha256: str
    coverage: EvidenceCoverageManifest
    scheduled_pairs: ScheduledPairContractsBinding


def _single_row(
    rows: tuple[dict[str, Any], ...],
    data_class: str,
) -> dict[str, Any]:
    matches = [row for row in rows if row["data_class"] == data_class]
    if len(matches) != 1:
        raise ValueError(f"terminal inventory requires exactly one {data_class} artifact")
    return matches[0]


def _validate_special_bindings(
    observed: _ObservedInventory,
    *,
    run_id: str,
    preregistration_core_sha256: str,
    execution_identity_sha256: str,
    limits: VerificationLimits,
) -> _InventoryBindings:
    if observed.retained_by_class["schema_registry"] != TRUSTED_SCHEMA_REGISTRY_BYTES:
        raise ValueError("schema-registry artifact does not match the embedded trust root")
    graph_row = _single_row(observed.rows, "agentic_run_graph")
    scheduled_pairs_row = _single_row(observed.rows, "scheduled_pair_contracts")
    coverage_row = _single_row(observed.rows, "coverage_manifest")
    manifest_row = _single_row(observed.rows, "manifest_snapshot")
    summary_row = _single_row(observed.rows, "summary")
    scheduled_pairs_sha256 = scheduled_pairs_row["sha256"]
    coverage_sha256 = coverage_row["sha256"]
    graph = AgenticRunGraph.from_bytes(
        observed.retained_by_class["agentic_run_graph"],
        limits=limits,
    )
    if graph.digest != graph_row["sha256"]:
        raise ValueError("agentic run graph file hash differs from canonical graph")
    if graph.run_id != run_id:
        raise ValueError("agentic run graph run_id cross-binding mismatch")
    if graph.manifest_sha256 != preregistration_core_sha256:
        raise ValueError("agentic run graph preregistration-core cross-binding mismatch")
    artifact_bindings = {binding.data_class: binding for binding in graph.run_artifact_bindings}
    for data_class in RUN_ARTIFACT_DATA_CLASSES:
        row = _single_row(observed.rows, data_class)
        if row["sha256"] != artifact_bindings[data_class].encoded_artifact_sha256:
            raise ValueError(f"{data_class} file hash differs from its run-graph binding")
    if observed.retained_by_class["summary"] != graph.summary.to_bytes():
        raise ValueError("summary artifact differs from the derived run summary")
    if summary_row["sha256"] != graph.summary.digest:
        raise ValueError("summary artifact hash differs from the derived summary")
    coverage = EvidenceCoverageManifest.from_bytes(
        observed.retained_by_class["coverage_manifest"],
        limits=limits,
    )
    manifest = ManifestSnapshotBinding.from_bytes(
        observed.retained_by_class["manifest_snapshot"],
        limits=limits,
    )
    scheduled_pairs = ScheduledPairContractsBinding.from_bytes(
        observed.retained_by_class["scheduled_pair_contracts"],
        limits=limits,
    )
    if coverage.run_id != run_id or manifest.run_id != run_id:
        raise ValueError("manifest or coverage run_id cross-binding mismatch")
    if scheduled_pairs.run_id != run_id:
        raise ValueError("scheduled-pair contracts run_id cross-binding mismatch")
    if (
        coverage.execution_identity_sha256 != execution_identity_sha256
        or manifest.execution_identity_sha256 != execution_identity_sha256
    ):
        raise ValueError("manifest or coverage execution identity cross-binding mismatch")
    if manifest.preregistration_core_sha256 != preregistration_core_sha256:
        raise ValueError("manifest snapshot preregistration-core identity mismatch")
    schedule_sha256 = graph.plan_sha256
    probability_sha256 = graph.probability_measure_sha256
    if (
        coverage.schedule_plan_sha256 != schedule_sha256
        or manifest.schedule_plan_sha256 != schedule_sha256
        or scheduled_pairs.schedule_plan_sha256 != schedule_sha256
    ):
        raise ValueError(
            "manifest, coverage, or scheduled-pair schedule-plan cross-binding mismatch"
        )
    if (
        coverage.probability_measure_contract_sha256 != probability_sha256
        or manifest.probability_measure_contract_sha256 != probability_sha256
        or scheduled_pairs.probability_measure_contract_sha256 != probability_sha256
    ):
        raise ValueError("probability-measure contract cross-binding mismatch")
    if (
        coverage.scheduled_pair_contracts_sha256 != scheduled_pairs_sha256
        or manifest.scheduled_pair_contracts_sha256 != scheduled_pairs_sha256
    ):
        raise ValueError("scheduled-pair contracts artifact cross-binding mismatch")
    if manifest.coverage_manifest_sha256 != coverage_sha256:
        raise ValueError("manifest coverage-manifest cross-binding mismatch")
    if manifest_row["sha256"] != artifact_bindings["manifest_snapshot"].encoded_artifact_sha256:
        raise ValueError("manifest snapshot encoded binding mismatch")
    expected_pairs = tuple(
        sorted(
            (
                ScheduledPairCoverage(
                    pair.digest,
                    pair.children()[0].digest,
                    pair.children()[1].digest,
                    pair.replay_law.digest,
                    pair.replay_law.max_replays,
                )
                for pair in graph.scheduled_pairs
            ),
            key=lambda pair: pair.scheduled_pair_sha256,
        )
    )
    if scheduled_pairs.pairs != expected_pairs:
        raise ValueError("scheduled-pair binding differs from the persisted run graph")
    max_replays_by_child = {
        child: pair.max_replays
        for pair in scheduled_pairs.pairs
        for child in (pair.clean_episode_sha256, pair.attack_episode_sha256)
    }
    coverage_children = tuple(slot.scheduled_episode_sha256 for slot in coverage.slots)
    if coverage_children != tuple(sorted(max_replays_by_child)):
        raise ValueError("coverage manifest does not exactly cover scheduled children")
    for slot in coverage.slots:
        if len(slot.attempts) - 1 > max_replays_by_child[slot.scheduled_episode_sha256]:
            raise ValueError("coverage replay plan exceeds the replay-law maximum")
    required_attempts = {
        (slot.scheduled_episode_sha256, attempt.phase, attempt.attempt_ordinal)
        for slot in coverage.slots
        for attempt in slot.attempts
    }
    if set(graph.terminal_attempt_keys) != required_attempts:
        raise ValueError(
            "run graph terminal attempts do not exactly realize preregistered coverage"
        )
    return _InventoryBindings(
        graph_row["sha256"],
        graph,
        probability_sha256,
        schedule_sha256,
        scheduled_pairs_sha256,
        coverage_sha256,
        coverage,
        scheduled_pairs,
    )


def _attempt_required_classes(record: TerminalAttemptRecord) -> frozenset[str]:
    if record.disposition is TerminalDisposition.COMPLETED:
        if record.phase is EpisodePhase.REPLAY:
            return COMPLETED_REPLAY_EVIDENCE_CLASSES
        return COMPLETED_INITIAL_EVIDENCE_CLASSES
    return NONCOMPLETED_EVIDENCE_CLASSES


def _attempt_expected_hashes(
    record: TerminalAttemptRecord,
    replay_comparison_sha256: str | None,
) -> dict[str, str]:
    expected = {
        "control_evidence": record.control_evidence_sha256,
        "terminal_disposition": record.digest,
    }
    if record.disposition is not TerminalDisposition.COMPLETED:
        if record.failure_artifact_sha256 is None or record.failure_witness_sha256 is None:
            raise AssertionError("validated noncompleted record lost failure evidence")
        expected.update(
            {
                "failure_artifact": record.failure_artifact_sha256,
                "failure_witness": record.failure_witness_sha256,
            }
        )
        return expected
    adjudication = record.adjudication
    if adjudication is None:
        raise AssertionError("validated completed record lost adjudication")
    evidence = adjudication.evidence
    checker = adjudication.checker_result
    expected.update(
        {
            "request_envelope": evidence.request_envelope_sha256,
            "response_envelope": evidence.response_envelope_sha256,
            "tool_trace": evidence.tool_trace_sha256,
            "prestate": evidence.prestate_sha256,
            "poststate": evidence.poststate_sha256,
            "checker_result": checker.digest,
            "checker_witness": checker.checker_execution_witness_sha256,
            "adjudication": adjudication.digest,
            "mutation_log": evidence.mutation_log_sha256,
            "runtime_attestation": evidence.runtime_attestation.digest,
        }
    )
    if record.phase is EpisodePhase.REPLAY:
        if replay_comparison_sha256 is None:
            raise AssertionError("validated completed replay lost its comparison")
        expected["replay_comparison"] = replay_comparison_sha256
    elif replay_comparison_sha256 is not None:
        raise AssertionError("initial attempt unexpectedly carries replay comparison")
    return expected


def _expected_decisive_witnesses(
    record: TerminalAttemptRecord,
    graph: AgenticRunGraph,
) -> dict[str, str]:
    adjudication = record.adjudication
    if adjudication is None:
        raise AssertionError("decisive witnesses require a completed adjudication")
    evidence = adjudication.evidence
    checker = adjudication.checker_result
    if checker.utility_witness_sha256 is None:
        raise AssertionError("completed utility predicate lost its witness")
    if checker.security_witness_sha256 is None:
        raise AssertionError("completed security predicate lost its witness")
    expected = {
        "evaluator_opening_witness": (evidence.evaluator_secret_opening.opening_witness_sha256),
        "prestate_construction_witness": (evidence.prestate.construction_witness_sha256),
        "renderer_witness": evidence.request_binding.renderer_witness_sha256,
        "runtime_attestation_witness": (evidence.runtime_attestation.attestation_witness_sha256),
        "security_witness": checker.security_witness_sha256,
        "terminal_witness": adjudication.terminal_witness_sha256,
        "transformation_verifier_witness": (
            record.scheduled_episode.scheduled_pair.scenario_pair.transformation_verification.verifier_witness_sha256
        ),
        "utility_witness": checker.utility_witness_sha256,
    }
    reconciliation = next(
        (
            row
            for row in graph.pair_reconciliations
            if row.scheduled_pair.digest == record.scheduled_episode.scheduled_pair.digest
        ),
        None,
    )
    if reconciliation is not None:
        expected["paired_request_verifier_witness"] = (
            reconciliation.request_verification.verifier_witness_sha256
        )
    return expected


def _validate_attempt_witness_packs(
    rows: tuple[dict[str, Any], ...],
    graph: AgenticRunGraph,
    retained_by_path: dict[str, bytes],
    limits: VerificationLimits,
) -> None:
    rows_by_identity = {
        (
            row["scheduled_episode_sha256"],
            row["phase"],
            row["attempt_ordinal"],
            row["data_class"],
        ): row
        for row in rows
        if row["data_class"] in {"checker_witness", "failure_witness"}
    }
    for record in graph.terminal_attempts:
        base = (
            record.scheduled_episode.digest,
            record.phase.value,
            record.attempt_ordinal,
        )
        if record.disposition is TerminalDisposition.COMPLETED:
            row = rows_by_identity[(*base, "checker_witness")]
            raw = retained_by_path.get(row["relative_path"])
            if raw is None:
                raise ValueError("completed attempt witness pack bytes were not retained")
            pack = AttemptWitnessPack.from_bytes(raw, limits=limits)
            if (
                pack.scheduled_episode_sha256 != base[0]
                or pack.phase.value != base[1]
                or pack.attempt_ordinal != base[2]
                or pack.digest != row["sha256"]
            ):
                raise ValueError("attempt witness pack identity mismatch")
            observed = {blob.role: blob.sha256 for blob in pack.witnesses}
            expected = _expected_decisive_witnesses(record, graph)
            if observed != expected:
                raise ValueError("attempt witness pack does not exactly close decisive witnesses")
            continue
        row = rows_by_identity[(*base, "failure_witness")]
        raw = retained_by_path.get(row["relative_path"])
        if raw is None:
            raise ValueError("failure witness pack bytes were not retained")
        pack = FailureWitnessPack.from_bytes(raw, limits=limits)
        if (
            pack.scheduled_episode_sha256 != base[0]
            or pack.phase.value != base[1]
            or pack.attempt_ordinal != base[2]
            or pack.disposition is not record.disposition
            or pack.failure_artifact_sha256 != record.failure_artifact_sha256
            or pack.digest != row["sha256"]
        ):
            raise ValueError("failure witness pack identity mismatch")


def _reconcile_coverage(
    rows: tuple[dict[str, Any], ...],
    graph: AgenticRunGraph,
    retained_by_path: dict[str, bytes],
    limits: VerificationLimits,
) -> int:
    replay_by_key = {
        (
            comparison.link.replay.scheduled_episode.digest,
            comparison.link.replay.attempt_ordinal,
        ): comparison.digest
        for comparison in graph.replay_comparisons
    }
    expected_hashes: dict[tuple[str, str, int, str], str] = {}
    for record in graph.terminal_attempts:
        comparison_sha256 = replay_by_key.get(
            (record.scheduled_episode.digest, record.attempt_ordinal)
        )
        hashes = _attempt_expected_hashes(record, comparison_sha256)
        required = _attempt_required_classes(record)
        if set(hashes) != required:
            raise AssertionError("attempt evidence hash profile is incomplete")
        for data_class, digest in hashes.items():
            expected_hashes[
                (
                    record.scheduled_episode.digest,
                    record.phase.value,
                    record.attempt_ordinal,
                    data_class,
                )
            ] = digest
    actual_rows = [row for row in rows if row["data_class"] in EPISODE_PHASE_EVIDENCE_CLASSES]
    actual_identities = [
        (
            row["scheduled_episode_sha256"],
            row["phase"],
            row["attempt_ordinal"],
            row["data_class"],
        )
        for row in actual_rows
    ]
    if len(actual_identities) != len(set(actual_identities)):
        raise ValueError("terminal inventory has duplicate episode/phase evidence")
    actual = set(actual_identities)
    expected = set(expected_hashes)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise ValueError(
            f"terminal coverage reconciliation failed: missing={missing}; unexpected={unexpected}"
        )
    for row in actual_rows:
        identity = (
            row["scheduled_episode_sha256"],
            row["phase"],
            row["attempt_ordinal"],
            row["data_class"],
        )
        if row["sha256"] != expected_hashes[identity]:
            raise ValueError(
                f"attempt evidence hash differs from the authoritative run graph: {identity}"
            )
    _validate_attempt_witness_packs(rows, graph, retained_by_path, limits)
    return len(graph.terminal_attempts)


def _receipt_basis_sha256(
    rows: tuple[dict[str, Any], ...],
    *,
    run_id: str,
    preregistration_core_sha256: str,
    execution_identity_sha256: str,
    probability_measure_contract_sha256: str,
    schedule_plan_sha256: str,
    scheduled_pair_contracts_sha256: str,
    coverage_manifest_sha256: str,
) -> str:
    raw_rows = [
        row
        for row in rows
        if row["data_class"] not in {"receipt_chain", EVIDENCE_STORE_INVENTORY_DATA_CLASS}
    ]
    return _canonical_compact_sha(
        {
            "contract_version": CONTRACT_VERSION,
            "authority_status": AUTHORITY_STATUS,
            "terminal_closure_law": TERMINAL_CLOSURE_LAW,
            "run_id": run_id,
            "preregistration_core_sha256": preregistration_core_sha256,
            "execution_identity_sha256": execution_identity_sha256,
            "probability_measure_contract_sha256": (probability_measure_contract_sha256),
            "schedule_plan_sha256": schedule_plan_sha256,
            "scheduled_pair_contracts_sha256": (scheduled_pair_contracts_sha256),
            "coverage_manifest_sha256": coverage_manifest_sha256,
            "agentic_run_graph_sha256": _single_row(rows, "agentic_run_graph")["sha256"],
            "schema_registry_sha256": TRUSTED_SCHEMA_REGISTRY_SHA256,
            "artifacts": raw_rows,
        }
    )


@dataclass(frozen=True, slots=True)
class _InventoryAnalysis:
    observed: _ObservedInventory
    bindings: _InventoryBindings
    terminal_attempt_count: int
    receipt_basis_sha256: str


def _receipt_common_binding(
    *,
    run_id: str,
    preregistration_core_sha256: str,
    execution_identity_sha256: str,
    analysis: _InventoryAnalysis,
) -> dict[str, Any]:
    return {
        "authority_status": AUTHORITY_STATUS,
        "terminal_closure_law": TERMINAL_CLOSURE_LAW,
        "run_id": run_id,
        "preregistration_core_sha256": preregistration_core_sha256,
        "execution_identity_sha256": execution_identity_sha256,
        "probability_measure_contract_sha256": (
            analysis.bindings.probability_measure_contract_sha256
        ),
        "schedule_plan_sha256": analysis.bindings.schedule_plan_sha256,
        "scheduled_pair_contracts_sha256": (analysis.bindings.scheduled_pair_contracts_sha256),
        "coverage_manifest_sha256": analysis.bindings.coverage_manifest_sha256,
        "agentic_run_graph_sha256": analysis.bindings.graph_sha256,
        "schema_registry_sha256": TRUSTED_SCHEMA_REGISTRY_SHA256,
    }


def _expected_receipt_payloads(
    *,
    run_id: str,
    preregistration_core_sha256: str,
    execution_identity_sha256: str,
    analysis: _InventoryAnalysis,
) -> list[dict[str, Any]]:
    common = _receipt_common_binding(
        run_id=run_id,
        preregistration_core_sha256=preregistration_core_sha256,
        execution_identity_sha256=execution_identity_sha256,
        analysis=analysis,
    )
    artifacts = [
        row
        for row in analysis.observed.rows
        if row["data_class"] not in {"receipt_chain", EVIDENCE_STORE_INVENTORY_DATA_CLASS}
    ]
    payloads: list[dict[str, Any]] = [
        {
            **common,
            "event_type": "closure_start",
            "ordinal": 1,
            "expected_artifact_count": len(artifacts),
            "expected_terminal_attempt_count": analysis.terminal_attempt_count,
            "expected_receipt_row_count": len(artifacts) + 2,
        }
    ]
    for ordinal, row in enumerate(artifacts, 2):
        payloads.append(
            {
                **common,
                "event_type": "artifact_committed",
                "ordinal": ordinal,
                "artifact": row,
            }
        )
    payloads.append(
        {
            **common,
            "event_type": "terminal",
            "ordinal": len(artifacts) + 2,
            "terminal_status": RECEIPT_TERMINAL_STATUS,
            "receipt_basis_sha256": analysis.receipt_basis_sha256,
            "artifact_count": len(artifacts),
            "terminal_attempt_count": analysis.terminal_attempt_count,
        }
    )
    return payloads


def _validate_utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        raise ValueError("receipt timestamp must be canonical UTC RFC3339")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("receipt timestamp is not a real UTC instant") from exc


def _canonical_receipt_line(row: dict[str, Any]) -> bytes:
    return _canonical_compact_bytes(row) + b"\n"


def _validate_receipt_chain_bytes(
    raw: bytes,
    expected_range: ReceiptRange,
    *,
    analysis: _InventoryAnalysis,
    run_id: str,
    preregistration_core_sha256: str,
    execution_identity_sha256: str,
    limits: VerificationLimits,
) -> None:
    validate_json_resource_envelope(
        raw,
        label="receipt chain",
        limits=limits,
    )
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("receipt-chain artifact must be non-empty newline-terminated JSONL")
    if expected_range.row_count > limits.receipt_rows or raw.count(b"\n") > limits.receipt_rows:
        raise VerificationResourceLimitExceeded(
            f"receipt chain exceeds receipt_rows={limits.receipt_rows}; "
            "next action: split the run into independently verified terminal bundles"
        )
    expected_payloads = _expected_receipt_payloads(
        run_id=run_id,
        preregistration_core_sha256=preregistration_core_sha256,
        execution_identity_sha256=execution_identity_sha256,
        analysis=analysis,
    )
    lines = raw.splitlines(keepends=True)
    if len(lines) > limits.receipt_rows:
        raise VerificationResourceLimitExceeded(
            f"receipt chain exceeds receipt_rows={limits.receipt_rows}; "
            "next action: split the run into independently verified terminal bundles"
        )
    if len(lines) != len(expected_payloads):
        raise ValueError(
            "receipt-chain must contain one closure_start, one commitment per "
            "raw artifact, and one terminal event"
        )
    expected_prior = GENESIS_HASH
    row_hashes: list[str] = []
    previous_timestamp: datetime | None = None
    row_keys = {
        "schema_version",
        "timestamp",
        "stream_id",
        "data_class",
        "source_receipt_ref",
        "prior_hash",
        "row_hash",
        "payload",
    }
    for line_number, (line, expected_payload) in enumerate(
        zip(lines, expected_payloads, strict=True),
        1,
    ):
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"receipt-chain artifact has invalid JSON at line {line_number}"
            ) from exc
        if not isinstance(row, dict) or set(row) != row_keys:
            raise ValueError(f"receipt-chain row {line_number} has an exact-schema mismatch")
        if type(row["schema_version"]) is not int:
            raise TypeError(f"receipt-chain row {line_number} schema_version must be integer")
        if row["schema_version"] != RECEIPT_ROW_SCHEMA_VERSION:
            raise ValueError(f"receipt-chain row {line_number} schema version mismatch")
        if row["stream_id"] != run_id:
            raise ValueError(f"receipt-chain row {line_number} run_id cross-binding mismatch")
        if row["data_class"] != RECEIPT_DATA_CLASS:
            raise ValueError(f"receipt-chain row {line_number} data_class mismatch")
        event_type = expected_payload["event_type"]
        ordinal = expected_payload["ordinal"]
        if row["source_receipt_ref"] != f"terminal:{ordinal}:{event_type}":
            raise ValueError(f"receipt-chain row {line_number} source receipt reference mismatch")
        if row["payload"] != expected_payload:
            raise ValueError(f"receipt-chain row {line_number} event or cross-binding mismatch")
        timestamp = _validate_utc_timestamp(row["timestamp"])
        if previous_timestamp is not None and timestamp < previous_timestamp:
            raise ValueError("receipt-chain timestamps cannot move backward")
        previous_timestamp = timestamp
        _validate_sha("receipt prior_hash", row["prior_hash"])
        _validate_sha("receipt row_hash", row["row_hash"])
        if row["prior_hash"] != expected_prior:
            raise ValueError(f"receipt-chain prior-hash mismatch at line {line_number}")
        material = dict(row)
        claimed = material.pop("row_hash")
        recomputed = hashlib.sha256(_canonical_compact_bytes(material)).hexdigest()
        if recomputed != claimed:
            raise ValueError(f"receipt-chain row-hash mismatch at line {line_number}")
        if _canonical_receipt_line(row) != line:
            raise ValueError(f"receipt-chain row {line_number} is not canonical JSONL")
        expected_prior = claimed
        row_hashes.append(claimed)
    actual = ReceiptRange(len(row_hashes), row_hashes[0], row_hashes[-1])
    if actual != expected_range:
        raise ValueError("receipt-chain artifact does not match the sealed receipt range")


def _artifact_spec_from_row(row: dict[str, Any]) -> ArtifactSpec:
    phase_raw = row["phase"]
    phase = EpisodePhase(phase_raw) if phase_raw is not None else None
    return ArtifactSpec(
        row["data_class"],
        row["relative_path"],
        row["scheduled_episode_sha256"],
        phase,
        row["attempt_ordinal"],
    )


def _validate_artifact_rows(
    rows: object,
    *,
    limits: VerificationLimits | None,
) -> list[ArtifactSpec]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("terminal bundle has no artifact rows")
    if limits is not None and len(rows) > limits.artifact_rows:
        raise VerificationResourceLimitExceeded(
            f"terminal bundle exceeds artifact_rows={limits.artifact_rows}; "
            "next action: split the run into independently verified terminal bundles"
        )
    expected_keys = {
        "data_class",
        "relative_path",
        "schema_sha256",
        "scheduled_episode_sha256",
        "phase",
        "attempt_ordinal",
        "sha256",
        "size",
    }
    specs: list[ArtifactSpec] = []
    seen_paths: set[str] = set()
    episode_identities: set[tuple[str, str, int, str]] = set()
    declared_evidence_bytes = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected_keys:
            raise ValueError("terminal bundle artifact row schema mismatch")
        spec = _artifact_spec_from_row(row)
        if limits is not None:
            validate_relative_path_resource(
                spec.relative_path,
                label="artifact path",
                limits=limits,
            )
        trusted_schema_sha256 = TRUSTED_SCHEMA_SHA256_BY_CLASS[spec.data_class]
        if row["schema_sha256"] != trusted_schema_sha256:
            raise ValueError(f"artifact schema is not trusted for data class {spec.data_class}")
        if spec.relative_path in seen_paths:
            raise ValueError("terminal bundle contains duplicate artifact paths")
        seen_paths.add(spec.relative_path)
        if spec.phase is not None:
            identity = (
                spec.scheduled_episode_sha256 or "",
                spec.phase.value,
                spec.attempt_ordinal or 0,
                spec.data_class,
            )
            if identity in episode_identities:
                raise ValueError("terminal bundle contains duplicate attempt evidence")
            episode_identities.add(identity)
        _validate_sha("artifact sha256", row["sha256"])
        if isinstance(row["size"], bool) or not isinstance(row["size"], int):
            raise TypeError("artifact size must be an integer")
        if row["size"] < 0:
            raise ValueError("artifact size cannot be negative")
        size_limit = None
        size_limit_name = None
        if limits is not None:
            if spec.data_class == EVIDENCE_STORE_INVENTORY_DATA_CLASS:
                size_limit = limits.inventory_bytes
                size_limit_name = "inventory_bytes"
            else:
                size_limit = limits.evidence_object_bytes
                size_limit_name = "evidence_object_bytes"
        if size_limit is not None and row["size"] > size_limit:
            raise VerificationResourceLimitExceeded(
                f"artifact size exceeds {size_limit_name}={size_limit}: {spec.relative_path}; "
                "next action: split the evidence before verification"
            )
        if limits is not None and spec.data_class != EVIDENCE_STORE_INVENTORY_DATA_CLASS:
            declared_evidence_bytes += row["size"]
            if declared_evidence_bytes > limits.total_evidence_bytes:
                raise ValueError(
                    "terminal artifacts exceed total_evidence_bytes="
                    f"{limits.total_evidence_bytes}; "
                    "next action: split the run into independently verified terminal bundles"
                )
        specs.append(spec)
    counts = Counter(spec.data_class for spec in specs)
    for data_class in RUN_SCOPED_EVIDENCE_CLASSES:
        if counts[data_class] != 1:
            raise ValueError(f"terminal bundle requires exactly one {data_class} artifact")
    if specs != sorted(specs, key=_artifact_sort_key):
        raise ValueError("terminal bundle artifacts are not canonically ordered")
    return specs


def _validate_bundle_document(
    document: object,
    encoded: bytes,
    *,
    limits: VerificationLimits | None,
) -> dict[str, Any]:
    if type(encoded) is not bytes:
        raise TypeError("terminal bundle encoding must be exact bytes")
    if limits is not None and len(encoded) > limits.terminal_bundle_bytes:
        raise VerificationResourceLimitExceeded(
            "terminal bundle exceeds terminal_bundle_bytes="
            f"{limits.terminal_bundle_bytes}; "
            "next action: split the run into independently verified terminal bundles"
        )
    if not isinstance(document, dict):
        raise TypeError("terminal bundle must be a JSON object")
    expected_keys = {
        "schema_version",
        "contract_version",
        "authority_status",
        "terminal_closure_law",
        "temporal_anchor_status",
        "run_id",
        "preregistration_core_sha256",
        "manifest_snapshot_artifact_sha256",
        "execution_identity_sha256",
        "probability_measure_contract_sha256",
        "schedule_plan_sha256",
        "scheduled_pair_contracts_sha256",
        "coverage_manifest_sha256",
        "agentic_run_graph_sha256",
        "schema_registry_sha256",
        "receipt_basis_sha256",
        "evidence_store_inventory_entry_count",
        "evidence_store_inventory_relative_path",
        "evidence_store_inventory_root_sha256",
        "evidence_store_inventory_schema_version",
        "evidence_store_inventory_sha256",
        "evidence_store_inventory_size",
        "receipt_range",
        "artifacts",
        "evidence_root_sha256",
    }
    if set(document) != expected_keys:
        raise ValueError("terminal bundle top-level schema mismatch")
    if type(document["schema_version"]) is not int:
        raise TypeError("terminal bundle schema_version must be an integer")
    if document["schema_version"] != BUNDLE_SCHEMA_VERSION:
        raise ValueError("terminal bundle schema mismatch")
    if document["contract_version"] != CONTRACT_VERSION:
        raise ValueError("terminal bundle contract mismatch")
    if document["authority_status"] != AUTHORITY_STATUS:
        raise ValueError("terminal bundle cannot grant execution authority")
    if document["terminal_closure_law"] != TERMINAL_CLOSURE_LAW:
        raise ValueError("terminal bundle closure law mismatch")
    if document["temporal_anchor_status"] != TEMPORAL_ANCHOR_STATUS:
        raise ValueError("terminal bundle temporal-anchor status mismatch")
    _validate_token("run_id", document["run_id"])
    for field in (
        "preregistration_core_sha256",
        "manifest_snapshot_artifact_sha256",
        "execution_identity_sha256",
        "probability_measure_contract_sha256",
        "schedule_plan_sha256",
        "scheduled_pair_contracts_sha256",
        "coverage_manifest_sha256",
        "agentic_run_graph_sha256",
        "receipt_basis_sha256",
        "evidence_root_sha256",
    ):
        _validate_sha(field, document[field])
    if document["schema_registry_sha256"] != TRUSTED_SCHEMA_REGISTRY_SHA256:
        raise ValueError("terminal bundle does not bind the trusted schema registry")
    store_binding = EvidenceStoreBinding.from_terminal_binding(
        {
            key: document[key]
            for key in (
                "evidence_store_inventory_entry_count",
                "evidence_store_inventory_relative_path",
                "evidence_store_inventory_root_sha256",
                "evidence_store_inventory_schema_version",
                "evidence_store_inventory_sha256",
                "evidence_store_inventory_size",
            )
        }
    )
    if limits is not None:
        validate_relative_path_resource(
            store_binding.inventory_relative_path,
            label="inventory path",
            limits=limits,
        )
        if store_binding.inventory_size > limits.inventory_bytes:
            raise VerificationResourceLimitExceeded(
                f"inventory_size exceeds inventory_bytes={limits.inventory_bytes}; "
                "next action: split the evidence into independently verified inventories"
            )
        if store_binding.inventory_entry_count > limits.inventory_entries:
            raise VerificationResourceLimitExceeded(
                f"inventory_entry_count exceeds inventory_entries={limits.inventory_entries}; "
                "next action: split the evidence into independently verified inventories"
            )
    receipt = document["receipt_range"]
    if not isinstance(receipt, dict) or set(receipt) != {
        "row_count",
        "first_row_hash",
        "last_row_hash",
    }:
        raise ValueError("terminal bundle receipt range mismatch")
    receipt_range = ReceiptRange(**receipt)
    if limits is not None and receipt_range.row_count > limits.receipt_rows:
        raise VerificationResourceLimitExceeded(
            f"receipt row_count exceeds receipt_rows={limits.receipt_rows}; "
            "next action: split the run into independently verified terminal bundles"
        )
    specs = _validate_artifact_rows(document["artifacts"], limits=limits)
    rows = document["artifacts"]
    inventory_rows = [
        row for row in rows if row["data_class"] == EVIDENCE_STORE_INVENTORY_DATA_CLASS
    ]
    if len(inventory_rows) != 1:
        raise ValueError("terminal bundle requires one custody-inventory row")
    inventory_row = inventory_rows[0]
    if (
        inventory_row["relative_path"] != store_binding.inventory_relative_path
        or inventory_row["sha256"] != store_binding.inventory_sha256
        or inventory_row["size"] != store_binding.inventory_size
    ):
        raise ValueError("custody-inventory artifact differs from top-level pins")
    graph_row = next(row for row in rows if row["data_class"] == "agentic_run_graph")
    if graph_row["sha256"] != document["agentic_run_graph_sha256"]:
        raise ValueError("terminal graph row differs from top-level graph pin")
    manifest_row = next(row for row in rows if row["data_class"] == "manifest_snapshot")
    if manifest_row["sha256"] != document["manifest_snapshot_artifact_sha256"]:
        raise ValueError("terminal manifest-snapshot row differs from its artifact pin")
    raw_count = sum(
        spec.data_class not in {"receipt_chain", EVIDENCE_STORE_INVENTORY_DATA_CLASS}
        for spec in specs
    )
    if store_binding.inventory_entry_count != raw_count + 1:
        raise ValueError("custody inventory cardinality violates closure law")
    if len(specs) != raw_count + 2:
        raise ValueError("terminal artifact cardinality violates closure law")
    if receipt_range.row_count != raw_count + 2:
        raise ValueError("receipt row cardinality violates closure law")
    evidence_root = document["evidence_root_sha256"]
    core = {key: value for key, value in document.items() if key != "evidence_root_sha256"}
    if _canonical_compact_sha(core) != evidence_root:
        raise ValueError("terminal bundle evidence root mismatch")
    if _canonical_bytes(document) != encoded:
        raise ValueError("terminal bundle is not canonical JSON")
    return document


def _load_custodied_observed_inventory(
    root_fd: int,
    specs: tuple[ArtifactSpec, ...],
    binding: EvidenceStoreBinding,
    limits: VerificationLimits,
) -> tuple[_ObservedInventory, SealedEvidenceInventory]:
    _validate_spec_inventory(specs, include_receipt=True)
    inventory = load_evidence_inventory_with_root_fd(
        root_fd,
        binding.inventory_relative_path,
        expected_sha256=binding.inventory_sha256,
        expected_root_sha256=binding.inventory_root_sha256,
        expected_size=binding.inventory_size,
        expected_entry_count=binding.inventory_entry_count,
        limits=limits,
    )
    entries_by_path = {entry.logical_path: entry for entry in inventory.entries}
    spec_paths = {spec.relative_path for spec in specs}
    if set(entries_by_path) != spec_paths:
        raise ValueError("custody inventory must contain exactly raw artifacts plus receipt")
    rows: list[dict[str, Any]] = []
    retained_by_class: dict[str, bytes] = {}
    retained_by_path: dict[str, bytes] = {}
    retained_classes = {
        "manifest_snapshot",
        "schema_registry",
        "coverage_manifest",
        "scheduled_pair_contracts",
        "agentic_run_graph",
        "summary",
        "receipt_chain",
    }
    retained_paths = {
        spec.relative_path
        for spec in specs
        if spec.data_class in retained_classes
        or spec.data_class in {"checker_witness", "failure_witness"}
    }
    retained_size = sum(entries_by_path[path].size for path in retained_paths)
    if retained_size > limits.retained_evidence_bytes:
        raise VerificationResourceLimitExceeded(
            "retained verification material exceeds retained_evidence_bytes="
            f"{limits.retained_evidence_bytes}; "
            "next action: split the run into independently verified terminal bundles"
        )
    for spec in sorted(specs, key=_artifact_sort_key):
        entry = entries_by_path[spec.relative_path]
        rows.append(_artifact_row(spec, digest=entry.sha256, size=entry.size))
        if spec.data_class in retained_classes or spec.data_class in {
            "checker_witness",
            "failure_witness",
        }:
            raw = read_verified_evidence_object_with_root_fd(root_fd, entry, limits=limits)
            retained_by_path[spec.relative_path] = raw
        if spec.data_class in retained_classes:
            if spec.data_class in retained_by_class:
                raise ValueError(f"custody inventory has duplicate run artifact: {spec.data_class}")
            retained_by_class[spec.data_class] = raw
    expectations = tuple(
        EvidenceInventoryExpectation(entry.logical_path, entry.sha256, entry.size)
        for entry in inventory.entries
    )
    verify_evidence_inventory_with_root_fd(
        root_fd,
        binding.inventory_relative_path,
        expected_sha256=binding.inventory_sha256,
        expected_root_sha256=binding.inventory_root_sha256,
        expected_size=binding.inventory_size,
        expected_entry_count=binding.inventory_entry_count,
        expected_entries=expectations,
        limits=limits,
    )
    return (
        _ObservedInventory(tuple(rows), retained_by_class, retained_by_path),
        inventory,
    )


def _analyze_custodied_inventory(
    root_fd: int,
    specs: tuple[ArtifactSpec, ...],
    *,
    binding: EvidenceStoreBinding,
    run_id: str,
    preregistration_core_sha256: str,
    execution_identity_sha256: str,
    receipt_range: ReceiptRange,
    expected_rows: list[dict[str, Any]] | None = None,
    limits: VerificationLimits,
) -> _InventoryAnalysis:
    observed, _ = _load_custodied_observed_inventory(root_fd, specs, binding, limits)
    if expected_rows is not None and list(observed.rows) != expected_rows:
        raise ValueError("terminal artifact rows drift from the verified custody projection")
    bindings = _validate_special_bindings(
        observed,
        run_id=run_id,
        preregistration_core_sha256=preregistration_core_sha256,
        execution_identity_sha256=execution_identity_sha256,
        limits=limits,
    )
    terminal_attempt_count = _reconcile_coverage(
        observed.rows,
        bindings.graph,
        observed.retained_by_path,
        limits,
    )
    receipt_basis = _receipt_basis_sha256(
        observed.rows,
        run_id=run_id,
        preregistration_core_sha256=preregistration_core_sha256,
        execution_identity_sha256=execution_identity_sha256,
        probability_measure_contract_sha256=(bindings.probability_measure_contract_sha256),
        schedule_plan_sha256=bindings.schedule_plan_sha256,
        scheduled_pair_contracts_sha256=bindings.scheduled_pair_contracts_sha256,
        coverage_manifest_sha256=bindings.coverage_manifest_sha256,
    )
    analysis = _InventoryAnalysis(
        observed,
        bindings,
        terminal_attempt_count,
        receipt_basis,
    )
    _validate_receipt_chain_bytes(
        observed.retained_by_class["receipt_chain"],
        receipt_range,
        analysis=analysis,
        run_id=run_id,
        preregistration_core_sha256=preregistration_core_sha256,
        execution_identity_sha256=execution_identity_sha256,
        limits=limits,
    )
    return analysis


def _verify_artifact_inventory(
    root_fd: int,
    document: dict[str, Any],
    *,
    limits: VerificationLimits,
) -> _InventoryAnalysis:
    source_rows = [
        row
        for row in document["artifacts"]
        if row["data_class"] != EVIDENCE_STORE_INVENTORY_DATA_CLASS
    ]
    specs = tuple(_artifact_spec_from_row(row) for row in source_rows)
    store_binding = EvidenceStoreBinding.from_terminal_binding(
        {
            key: document[key]
            for key in (
                "evidence_store_inventory_entry_count",
                "evidence_store_inventory_relative_path",
                "evidence_store_inventory_root_sha256",
                "evidence_store_inventory_schema_version",
                "evidence_store_inventory_sha256",
                "evidence_store_inventory_size",
            )
        }
    )
    analysis = _analyze_custodied_inventory(
        root_fd,
        specs,
        binding=store_binding,
        run_id=document["run_id"],
        preregistration_core_sha256=document["preregistration_core_sha256"],
        execution_identity_sha256=document["execution_identity_sha256"],
        receipt_range=ReceiptRange(**document["receipt_range"]),
        expected_rows=source_rows,
        limits=limits,
    )
    if analysis.bindings.schedule_plan_sha256 != document["schedule_plan_sha256"]:
        raise ValueError("terminal bundle schedule-plan cross-binding mismatch")
    if (
        analysis.bindings.probability_measure_contract_sha256
        != document["probability_measure_contract_sha256"]
    ):
        raise ValueError("terminal bundle probability-measure cross-binding mismatch")
    if (
        analysis.bindings.scheduled_pair_contracts_sha256
        != document["scheduled_pair_contracts_sha256"]
    ):
        raise ValueError("terminal bundle scheduled-pair cross-binding mismatch")
    if analysis.bindings.coverage_manifest_sha256 != document["coverage_manifest_sha256"]:
        raise ValueError("terminal bundle coverage-manifest cross-binding mismatch")
    if analysis.bindings.graph_sha256 != document["agentic_run_graph_sha256"]:
        raise ValueError("terminal bundle run-graph cross-binding mismatch")
    if analysis.receipt_basis_sha256 != document["receipt_basis_sha256"]:
        raise ValueError("terminal bundle receipt-basis cross-binding mismatch")
    if (
        _single_row(analysis.observed.rows, "manifest_snapshot")["sha256"]
        != document["manifest_snapshot_artifact_sha256"]
    ):
        raise ValueError("terminal bundle manifest-snapshot cross-binding mismatch")
    return analysis


def _final_revalidate_projection_inputs(
    root_fd: int,
    relative_path: str,
    *,
    bundle: TerminalBundle,
    analysis: _InventoryAnalysis,
    binding: EvidenceStoreBinding,
    limits: VerificationLimits,
) -> None:
    """Rewalk every content path after semantic analysis, then the terminal index.

    This is an explicit sequential observation boundary on a mutable filesystem,
    not an atomic snapshot and not a promise that paths remain unchanged after
    return.  Decision-grade persistence still requires external immutable custody.
    """

    expectations = tuple(
        EvidenceInventoryExpectation(row["relative_path"], row["sha256"], row["size"])
        for row in analysis.observed.rows
    )
    verify_evidence_inventory_with_root_fd(
        root_fd,
        binding.inventory_relative_path,
        expected_sha256=binding.inventory_sha256,
        expected_root_sha256=binding.inventory_root_sha256,
        expected_size=binding.inventory_size,
        expected_entry_count=binding.inventory_entry_count,
        expected_entries=expectations,
        limits=limits,
    )
    digest, size, mode, _ = _observe_confined_regular_file(
        root_fd,
        relative_path,
        retain_bytes=False,
        max_bytes=limits.terminal_bundle_bytes,
        limit_name="terminal_bundle_bytes",
    )
    if digest != bundle.bundle_sha256 or size != len(bundle.encoded) or mode != 0o400:
        raise VerificationCustodyFailure(
            "terminal bundle changed before the final sequential custody boundary"
        )


def _verify_terminal_bundle_with_root_fd(
    root_fd: int,
    relative_path: str,
    *,
    limits: VerificationLimits,
) -> tuple[TerminalBundle, _InventoryAnalysis]:
    validate_relative_path_resource(
        relative_path,
        label="terminal bundle path",
        limits=limits,
    )
    digest, _, mode, raw = _observe_confined_regular_file(
        root_fd,
        relative_path,
        retain_bytes=True,
        max_bytes=limits.terminal_bundle_bytes,
        limit_name="terminal_bundle_bytes",
    )
    if raw is None:
        raise AssertionError("terminal bundle bytes were not retained")
    if mode != 0o400:
        raise VerificationCustodyFailure("terminal bundle mode must be 0400")
    validate_json_resource_envelope(
        raw,
        label="terminal bundle",
        limits=limits,
    )
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("terminal bundle is not valid UTF-8 JSON") from exc
    _validate_bundle_document(document, raw, limits=limits)
    analysis = _verify_artifact_inventory(root_fd, document, limits=limits)
    return TerminalBundle(raw, document["evidence_root_sha256"], digest), analysis


def _verify_terminal_projection(
    root: Path,
    relative_path: str,
    *,
    expected_bundle_sha256: str | None = None,
    expected_evidence_root_sha256: str | None = None,
    expected_manifest_snapshot_artifact_sha256: str | None = None,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> VerifiedTerminalProjection:
    """Verify and return a parsed graph/summary after a final sequential rewalk.

    Supplying all three expected digests records only a match to caller-supplied
    values. The caller remains responsible for authenticating their origin and
    establishing that the manifest snapshot digest actually predates execution;
    digest matching cannot prove chronology by itself.
    """

    if not isinstance(limits, VerificationLimits):
        raise TypeError("limits must be a VerificationLimits value")
    expected_values = (
        expected_bundle_sha256,
        expected_evidence_root_sha256,
        expected_manifest_snapshot_artifact_sha256,
    )
    if any(value is not None for value in expected_values) and not all(
        value is not None for value in expected_values
    ):
        raise CallerAnchorVerificationFailure(
            "caller-pin verification requires terminal, evidence-root, and "
            "manifest-snapshot digest values together"
        )
    for name, value in (
        ("expected_bundle_sha256", expected_bundle_sha256),
        ("expected_evidence_root_sha256", expected_evidence_root_sha256),
        (
            "expected_manifest_snapshot_artifact_sha256",
            expected_manifest_snapshot_artifact_sha256,
        ),
    ):
        if value is not None:
            try:
                _validate_sha(name, value)
            except (TypeError, ValueError) as exc:
                raise CallerAnchorVerificationFailure(str(exc)) from exc
    root = _validated_root(root)
    root_fd = _open_root_directory(root)
    try:
        bundle, analysis = _verify_terminal_bundle_with_root_fd(
            root_fd,
            relative_path,
            limits=limits,
        )
        document = bundle.document
        if expected_bundle_sha256 is not None and (
            bundle.bundle_sha256 != expected_bundle_sha256
            or bundle.evidence_root_sha256 != expected_evidence_root_sha256
            or document["manifest_snapshot_artifact_sha256"]
            != expected_manifest_snapshot_artifact_sha256
        ):
            raise CallerAnchorVerificationFailure(
                "terminal evidence differs from caller-supplied digest values"
            )
        caller_pinned = expected_bundle_sha256 is not None
        binding = EvidenceStoreBinding.from_terminal_binding(
            {
                key: document[key]
                for key in (
                    "evidence_store_inventory_entry_count",
                    "evidence_store_inventory_relative_path",
                    "evidence_store_inventory_root_sha256",
                    "evidence_store_inventory_schema_version",
                    "evidence_store_inventory_sha256",
                    "evidence_store_inventory_size",
                )
            }
        )
        _final_revalidate_projection_inputs(
            root_fd,
            relative_path,
            bundle=bundle,
            analysis=analysis,
            binding=binding,
            limits=limits,
        )
        _assert_root_path_still_bound(root, root_fd)
        return VerifiedTerminalProjection(
            bundle=bundle,
            graph=analysis.bindings.graph,
            summary=analysis.bindings.graph.summary,
            summary_sha256=analysis.bindings.graph.summary.digest,
            evidence_store_binding=binding,
            caller_bundle_sha256=expected_bundle_sha256 if caller_pinned else None,
            caller_evidence_root_sha256=(expected_evidence_root_sha256 if caller_pinned else None),
            caller_manifest_snapshot_artifact_sha256=(
                expected_manifest_snapshot_artifact_sha256 if caller_pinned else None
            ),
        )
    finally:
        os.close(root_fd)


def _public_verification_error(
    exc: OSError | TypeError | ValueError | RuntimeError,
    *,
    target: str,
) -> AgenticTrustVerificationError:
    detail = str(exc) or type(exc).__name__
    if isinstance(exc, CallerAnchorVerificationFailure):
        reason_code = "caller_anchor_verification_failed"
        next_action = (
            "supply all three caller digest values and separately verify their origin, "
            "custody, and chronology"
        )
    elif isinstance(exc, VerificationResourceLimitExceeded):
        reason_code = "verification_resource_limit_exceeded"
        next_action = "split the evidence bundle or pass an operator-approved higher limit policy"
    elif isinstance(exc, VerificationCustodyFailure):
        reason_code = "custody_verification_failed"
        next_action = "quarantine the evidence store and restore it from immutable custody"
    else:
        reason_code = "terminal_closure_invalid"
        next_action = "discard the bundle and regenerate it from the frozen terminal contract"
    return AgenticTrustVerificationError(
        reason_code=reason_code,
        target=target,
        detail=detail,
        next_action=next_action,
    )


def verify_terminal_projection(
    root: Path,
    relative_path: str,
    *,
    expected_bundle_sha256: str | None = None,
    expected_evidence_root_sha256: str | None = None,
    expected_manifest_snapshot_artifact_sha256: str | None = None,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> VerifiedTerminalProjection:
    """Mechanically verify a projection or raise a stable, remediable evidence error.

    Supplying all three expected digests binds a positive projection to those
    caller-controlled values and permits a native receipt. Omitting all three
    produces diagnostic, unanchored mechanical closure only; it cannot mint a
    native receipt and does not authenticate origin or establish chronology.
    """

    if not isinstance(root, Path):
        raise TypeError("root must be a pathlib.Path")
    if type(relative_path) is not str:
        raise TypeError("relative_path must be exact text")
    if not isinstance(limits, VerificationLimits):
        raise TypeError("limits must be a VerificationLimits value")
    try:
        return _verify_terminal_projection(
            root,
            relative_path,
            expected_bundle_sha256=expected_bundle_sha256,
            expected_evidence_root_sha256=expected_evidence_root_sha256,
            expected_manifest_snapshot_artifact_sha256=(expected_manifest_snapshot_artifact_sha256),
            limits=limits,
        )
    except AgenticTrustVerificationError:
        raise
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise _public_verification_error(exc, target=relative_path) from exc
