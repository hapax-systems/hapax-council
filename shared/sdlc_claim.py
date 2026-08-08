"""Crash-recoverable, dispatch-bound claim publication.

The task vault and claim cache cannot be changed by one POSIX rename. This
module journals the seven mutation projections plus any immutable admission
proof projections and emits a self-hashed applied receipt only after every
postimage is durable. Readers must require that receipt before treating an
individual claim file as authoritative.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from shared.coord_projection import (
    CapturedFile,
    FileProjection,
    LifecycleTransitionError,
    PinnedDirectory,
    ReadOnlyFsSnapshot,
    ReadOnlySnapshotError,
    _assert_preimages,
    _file_state,
)
from shared.execution_admission import (
    ActionIntent,
    AuthorityEvidence,
    ContentAddress,
    ExecutionAdmission,
    ExecutionLease,
    ProspectiveClaimPublicationBasis,
    ValidAuthorityGrant,
    build_prospective_claim_publication_basis,
    require_admitted_execution_lease,
)
from shared.frontmatter import parse_frontmatter_with_diagnostics
from shared.sdlc_lifecycle import TASK_CLAIMABLE_STATUSES, TASK_RESUMABLE_STATUSES
from shared.sdlc_task_store import (
    ClaimDispatchBinding,
    ClaimLeaseSnapshot,
    TaskNoteSnapshot,
    TaskStoreError,
    claim_dispatch_binding_path,
    load_claim_dispatch_binding,
    resolve_task_note,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

CLAIM_PUBLICATION_SCHEMA = "hapax.claim-publication-transaction.v1"
CLAIM_PUBLICATION_RECEIPT_SCHEMA = "hapax.claim-publication-receipt.v2"
HISTORICAL_ADMITTED_CLAIM_PUBLICATION_SCHEMA = "hapax.claim-publication-transaction.v2"
ADMITTED_CLAIM_PUBLICATION_SCHEMA = "hapax.claim-publication-transaction.v3"
HISTORICAL_ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA = "hapax.claim-publication-receipt.v3"
ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA = "hapax.claim-publication-receipt.v4"
HISTORICAL_CLAIM_ADMISSION_CONSUMPTION_SCHEMA = "hapax.claim-admission-consumption.v1"
CLAIM_ADMISSION_CONSUMPTION_SCHEMA = "hapax.claim-admission-consumption.v2"
CLAIM_PUBLICATION_INSPECTION_SCHEMA = "hapax.claim-publication-inspection.v1"
_STATES = frozenset(
    {
        "created",
        "projecting",
        "postimage_complete",
        "applied",
        "aborted",
        "recovery_required",
    }
)


class ClaimPublicationError(RuntimeError):
    """Typed refusal or recovery failure for one claim publication."""

    def __init__(self, reason_code: str, repair_action: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        self.repair_action = repair_action
        self.detail = detail
        message = f"{reason_code}: {repair_action}"
        if detail:
            message += f" ({detail})"
        super().__init__(message)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_timestamp(value: str | datetime) -> str:
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except ValueError as exc:
        raise ClaimPublicationError(
            "claim_admission_timestamp_invalid",
            "use one timezone-aware ISO-8601 timestamp",
            str(value),
        ) from exc
    if parsed.tzinfo is None:
        raise ClaimPublicationError(
            "claim_admission_timestamp_invalid",
            "use one timezone-aware ISO-8601 timestamp",
            str(value),
        )
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _model_bytes(value: BaseModel) -> bytes:
    return _canonical(value.model_dump(mode="json", by_alias=True)) + b"\n"


def _require_canonical_content_address(label: str, address: ContentAddress) -> None:
    if not address.ref.endswith(f"@sha256:{address.sha256}"):
        raise ClaimPublicationError(
            "claim_admission_content_address_noncanonical",
            "bind every admitted proof reference to its exact sha256 content address",
            label,
        )


def _normalized(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _unique_pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in values:
        if key in output:
            raise ClaimPublicationError(
                "claim_publication_json_duplicate_key",
                "remove duplicate keys from the durable claim journal",
                key,
            )
        output[key] = value
    return output


def _strict_file(path: Path, *, reason_code: str) -> tuple[bytes, int]:
    try:
        content, mode = _file_state(_normalized(path))
    except LifecycleTransitionError as exc:
        raise ClaimPublicationError(
            reason_code,
            "restore the exact regular file below real non-symlink directories",
            str(path),
        ) from exc
    if content is None or mode is None:
        raise ClaimPublicationError(
            reason_code,
            "restore the exact regular file below real non-symlink directories",
            str(path),
        )
    return content, mode


def _strict_json(
    path: Path,
    *,
    content: bytes | None = None,
) -> tuple[dict[str, object], bytes]:
    try:
        payload = (
            content
            if content is not None
            else _strict_file(path, reason_code="claim_publication_journal_unreadable")[0]
        )
        value = json.loads(payload.decode("ascii"), object_pairs_hook=_unique_pairs)
    except ClaimPublicationError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ClaimPublicationError(
            "claim_publication_journal_unreadable",
            "restore or quarantine the malformed claim publication journal",
            str(path),
        ) from exc
    if not isinstance(value, dict) or payload != _canonical(value) + b"\n":
        raise ClaimPublicationError(
            "claim_publication_journal_noncanonical",
            "restore the exact canonical ASCII journal record",
            str(path),
        )
    return value, payload


def _binding_bytes(binding: ClaimDispatchBinding) -> bytes:
    return _canonical(binding.to_record()) + b"\n"


def _validate_note_after(
    content: bytes,
    *,
    task_id: str,
    role: str,
    authority_case: str,
    expected_status: str,
    require_claimed_at: bool,
) -> None:
    try:
        parsed = parse_frontmatter_with_diagnostics(content.decode("utf-8"))
    except UnicodeError as exc:
        raise ClaimPublicationError(
            "claim_publication_note_postimage_unreadable",
            "publish one UTF-8 task note postimage",
            task_id,
        ) from exc
    if not parsed.ok or parsed.frontmatter is None:
        raise ClaimPublicationError(
            "claim_publication_note_postimage_malformed",
            "publish a task note with one closed YAML frontmatter mapping",
            parsed.error_kind or task_id,
        )
    frontmatter = parsed.frontmatter
    expected = {
        "assigned_to": role,
        "authority_case": authority_case,
        "status": expected_status,
        "task_id": task_id,
    }
    mismatches = [
        f"{key}={frontmatter.get(key)!r}"
        for key, value in expected.items()
        if str(frontmatter.get(key) or "").strip() != value
    ]
    if require_claimed_at and not str(frontmatter.get("claimed_at") or "").strip():
        mismatches.append("claimed_at=missing")
    if mismatches:
        raise ClaimPublicationError(
            "claim_publication_note_postimage_identity_mismatch",
            "bind the claimed note to the exact task, lane, AuthorityCase, and claim time",
            ",".join(mismatches),
        )


@dataclass(frozen=True)
class ClaimPublicationIntent:
    """Exact task-note and dispatch identity to publish as one claim."""

    task_id: str
    role: str
    session_id: str
    claim_epoch: int
    claim_mode: str
    from_status: str
    to_status: str
    cache_dir: Path
    note_path: Path
    note_before: bytes
    note_after: bytes
    note_mode: int
    binding: ClaimDispatchBinding

    @classmethod
    def create(
        cls,
        *,
        task: TaskNoteSnapshot,
        cache_dir: Path,
        note_after: bytes,
        binding: ClaimDispatchBinding,
    ) -> ClaimPublicationIntent:
        if task.state != "active":
            raise ClaimPublicationError(
                "claim_publication_task_not_active",
                "resolve the exact active task note before constructing a claim",
                task.task_id,
            )
        if (
            binding.task_id != task.task_id
            or binding.claim_epoch <= 0
            or not binding.lane.strip()
            or not binding.session_id.strip()
        ):
            raise ClaimPublicationError(
                "claim_publication_binding_identity_mismatch",
                "bind the dispatch receipt to this exact task, lane, session, and epoch",
                task.task_id,
            )
        from_status = str(task.frontmatter.get("status") or "offered").strip()
        assigned_to = str(task.frontmatter.get("assigned_to") or "").strip()
        if task.frontmatter.get("claimable") is not True:
            raise ClaimPublicationError(
                "claim_publication_task_not_claimable",
                "advance the task through a lawful claimable lifecycle projection",
                f"{task.task_id}:claimable={task.frontmatter.get('claimable')!r}",
            )
        if from_status in TASK_CLAIMABLE_STATUSES and assigned_to.lower() in {
            "",
            "none",
            "null",
            "unassigned",
            "~",
        }:
            claim_mode = "claim"
            to_status = "claimed"
        elif from_status in TASK_RESUMABLE_STATUSES and assigned_to == binding.lane:
            claim_mode = "resume"
            to_status = from_status
        else:
            raise ClaimPublicationError(
                "claim_publication_task_not_claimable",
                "use one unassigned offered task or an owned resumable task",
                f"{from_status}:{assigned_to or 'unassigned'}",
            )
        _validate_note_after(
            note_after,
            task_id=task.task_id,
            role=binding.lane,
            authority_case=binding.authority_case,
            expected_status=to_status,
            require_claimed_at=claim_mode == "claim",
        )
        if note_after == task.content:
            raise ClaimPublicationError(
                "claim_publication_note_postimage_unchanged",
                "construct the exact claimed task-note postimage",
                task.task_id,
            )
        return cls(
            task_id=task.task_id,
            role=binding.lane,
            session_id=binding.session_id,
            claim_epoch=binding.claim_epoch,
            claim_mode=claim_mode,
            from_status=from_status,
            to_status=to_status,
            cache_dir=_normalized(cache_dir),
            note_path=_normalized(task.path),
            note_before=task.content,
            note_after=note_after,
            note_mode=task.mode,
            binding=binding,
        )

    def to_record(self) -> dict[str, object]:
        return {
            "binding": self.binding.to_record(),
            "cache_dir": str(self.cache_dir),
            "claim_epoch": self.claim_epoch,
            "claim_mode": self.claim_mode,
            "from_status": self.from_status,
            "note_after_sha256": _sha256(self.note_after),
            "note_before_sha256": _sha256(self.note_before),
            "note_mode": self.note_mode,
            "note_path": str(self.note_path),
            "role": self.role,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "to_status": self.to_status,
        }

    @property
    def intent_sha256(self) -> str:
        return _sha256(_canonical(self.to_record()))

    @property
    def intent_ref(self) -> str:
        """Canonical preclaim root; positions bind this without creating a hash cycle."""

        return f"claim-publication-intent@sha256:{self.intent_sha256}"


def claim_publication_task_note_address(
    intent: ClaimPublicationIntent,
    *,
    postimage: bool = False,
) -> ContentAddress:
    content = intent.note_after if postimage else intent.note_before
    return ContentAddress(ref=str(intent.note_path), sha256=_sha256(content))


def prospective_claim_publication_basis(
    intent: ClaimPublicationIntent,
) -> ProspectiveClaimPublicationBasis:
    mutation_scope_hash = _sha256(
        b"hapax.claim-publication-mutation-scope.v1\0"
        + _canonical([str(path) for path in _publication_paths(intent)])
    )
    return build_prospective_claim_publication_basis(
        claim_publication_intent=ContentAddress(
            ref=intent.intent_ref,
            sha256=intent.intent_sha256,
        ),
        task_ref=intent.task_id,
        lane=intent.role,
        session_ref=intent.session_id,
        claim_epoch=intent.claim_epoch,
        authority_case=intent.binding.authority_case,
        dispatch_message_id=intent.binding.dispatch_message_id,
        dispatch_binding_hash=intent.binding.binding_hash,
        dispatch_binding_receipt_hash=intent.binding.receipt_hash,
        coord_dispatch_idempotency_key=intent.binding.coord_dispatch_idempotency_key,
        claim_mode=intent.claim_mode,
        from_status=intent.from_status,
        to_status=intent.to_status,
        task_note_before_sha256=_sha256(intent.note_before),
        task_note_after_sha256=_sha256(intent.note_after),
        task_note_mode=intent.note_mode,
        mutation_scope_hash=mutation_scope_hash,
    )


def claim_publication_mutation_scope_address(
    intent: ClaimPublicationIntent,
) -> ContentAddress:
    """Address the exact seven-path publication mutation set."""

    digest = prospective_claim_publication_basis(intent).mutation_scope_hash
    return ContentAddress(
        ref=f"claim-publication-mutation-scope@sha256:{digest}",
        sha256=digest,
    )


AdmissionArtifactKind = Literal[
    "action_intent",
    "authority_evidence",
    "execution_admission",
    "execution_lease",
    "valid_authority_grant",
]


@dataclass(frozen=True)
class AdmissionArtifactSnapshot:
    """Exact immutable admission artifact consumed under the claim lock."""

    kind: AdmissionArtifactKind
    path: Path
    content: bytes
    mode: int
    object_ref: str
    object_hash: str
    content_sha256: str
    model: (
        ActionIntent | AuthorityEvidence | ExecutionAdmission | ExecutionLease | ValidAuthorityGrant
    )

    def to_record(self) -> dict[str, object]:
        return {
            "content_sha256": self.content_sha256,
            "kind": self.kind,
            "mode": self.mode,
            "object_hash": self.object_hash,
            "object_ref": self.object_ref,
            "path": str(self.path),
        }

    def proof_projection(self) -> FileProjection:
        return FileProjection.from_snapshot(
            self.path,
            before=self.content,
            before_mode=self.mode,
            after=self.content,
            after_mode=self.mode,
        )


def _artifact_identity(
    kind: AdmissionArtifactKind,
    model: ActionIntent
    | AuthorityEvidence
    | ExecutionAdmission
    | ExecutionLease
    | ValidAuthorityGrant,
) -> tuple[str, str]:
    if kind == "action_intent" and isinstance(model, ActionIntent):
        return model.intent_ref, model.intent_hash
    if kind == "execution_admission" and isinstance(model, ExecutionAdmission):
        return model.admission_ref, model.admission_hash
    if kind == "valid_authority_grant" and isinstance(model, ValidAuthorityGrant):
        return model.grant_ref, model.grant_hash
    if kind == "authority_evidence" and isinstance(model, AuthorityEvidence):
        return model.evidence_ref, model.evidence_hash
    if kind == "execution_lease" and isinstance(model, ExecutionLease):
        return model.lease_ref, model.lease_hash
    raise ClaimPublicationError(
        "claim_admission_artifact_kind_mismatch",
        "bind each proof kind to its exact typed admission artifact",
        kind,
    )


def _parse_admission_artifact(
    *,
    kind: AdmissionArtifactKind,
    path: Path,
    content: bytes,
    mode: int,
) -> AdmissionArtifactSnapshot:
    if mode != 0o600:
        raise ClaimPublicationError(
            "claim_admission_artifact_mode_mismatch",
            "materialize each admission artifact as an euid-owned mode-0600 regular file",
            str(path),
        )
    model_type: (
        type[ActionIntent]
        | type[AuthorityEvidence]
        | type[ExecutionAdmission]
        | type[ExecutionLease]
        | type[ValidAuthorityGrant]
    )
    if kind == "action_intent":
        model_type = ActionIntent
    elif kind == "execution_admission":
        model_type = ExecutionAdmission
    elif kind == "execution_lease":
        model_type = ExecutionLease
    elif kind == "valid_authority_grant":
        model_type = ValidAuthorityGrant
    else:
        model_type = AuthorityEvidence
    try:
        model = model_type.model_validate_json(content)
    except Exception as exc:
        raise ClaimPublicationError(
            "claim_admission_artifact_malformed",
            "restore the exact typed, self-validating admission artifact",
            f"{kind}:{path}",
        ) from exc
    if content != _model_bytes(model):
        raise ClaimPublicationError(
            "claim_admission_artifact_noncanonical",
            "materialize canonical ASCII JSON followed by one newline",
            f"{kind}:{path}",
        )
    object_ref, object_hash = _artifact_identity(kind, model)
    return AdmissionArtifactSnapshot(
        kind=kind,
        path=_normalized(path),
        content=content,
        mode=mode,
        object_ref=object_ref,
        object_hash=object_hash,
        content_sha256=_sha256(content),
        model=model,
    )


def _load_admission_artifact(kind: AdmissionArtifactKind, path: Path) -> AdmissionArtifactSnapshot:
    normalized = _normalized(path)
    content, mode = _strict_file(normalized, reason_code="claim_admission_artifact_unreadable")
    return _parse_admission_artifact(
        kind=kind,
        path=normalized,
        content=content,
        mode=mode,
    )


@dataclass(frozen=True)
class HistoricalClaimAdmissionConsumptionV1:
    """Historical three-proof vector retained for exact recovery and inspection.

    The admitted boundary deliberately narrows generic ``ContentAddress``
    values: every consumed reference must embed its own ``@sha256`` digest.
    """

    consumption_ref: str
    consumption_hash: str
    claim_publication_intent: ContentAddress
    execution_admission: ContentAddress
    valid_authority_grant: ContentAddress
    authority_evidence: ContentAddress
    authenticated_authority_receipt: ContentAddress
    context_position: ContentAddress
    task_id: str
    lane: str
    session_id: str
    claim_epoch: int
    authority_case: str
    dispatch_message_id: str
    idempotency_key: str
    supersession_frontier_ref: str
    checked_at: str
    valid_until: str
    proofs: tuple[AdmissionArtifactSnapshot, ...]
    may_authorize: Literal[False]

    @classmethod
    def create(
        cls,
        intent: ClaimPublicationIntent,
        *,
        execution_admission_path: Path,
        valid_authority_grant_path: Path,
        authority_evidence_path: Path,
        checked_at: str | datetime,
    ) -> HistoricalClaimAdmissionConsumptionV1:
        proofs = tuple(
            sorted(
                (
                    _load_admission_artifact("execution_admission", execution_admission_path),
                    _load_admission_artifact("valid_authority_grant", valid_authority_grant_path),
                    _load_admission_artifact("authority_evidence", authority_evidence_path),
                ),
                key=lambda item: item.kind,
            )
        )
        return cls._from_proofs(intent, proofs=proofs, checked_at=checked_at)

    @classmethod
    def _from_proofs(
        cls,
        intent: ClaimPublicationIntent,
        *,
        proofs: Sequence[AdmissionArtifactSnapshot],
        checked_at: str | datetime,
    ) -> HistoricalClaimAdmissionConsumptionV1:
        ordered = tuple(sorted(proofs, key=lambda item: item.kind))
        expected_kinds = (
            "authority_evidence",
            "execution_admission",
            "valid_authority_grant",
        )
        if tuple(item.kind for item in ordered) != expected_kinds:
            raise ClaimPublicationError(
                "claim_admission_proof_vector_invalid",
                "provide exactly one admission, grant, and authority-evidence proof",
            )
        if len({item.path for item in ordered}) != len(ordered):
            raise ClaimPublicationError(
                "claim_admission_proof_path_collision",
                "materialize each admission proof at one distinct normalized path",
            )
        by_kind = {item.kind: item for item in ordered}
        admission = by_kind["execution_admission"].model
        grant = by_kind["valid_authority_grant"].model
        evidence = by_kind["authority_evidence"].model
        if not isinstance(admission, ExecutionAdmission):
            raise ClaimPublicationError(
                "claim_admission_artifact_kind_mismatch",
                "restore the typed execution admission proof",
            )
        if not isinstance(grant, ValidAuthorityGrant):
            raise ClaimPublicationError(
                "claim_admission_artifact_kind_mismatch",
                "restore the typed valid-authority-grant proof",
            )
        if not isinstance(evidence, AuthorityEvidence):
            raise ClaimPublicationError(
                "claim_admission_artifact_kind_mismatch",
                "restore the typed authority-evidence proof",
            )
        checked = _canonical_timestamp(checked_at)
        claim_intent = ContentAddress(ref=intent.intent_ref, sha256=intent.intent_sha256)
        admission_address = ContentAddress(
            ref=admission.admission_ref, sha256=admission.admission_hash
        )
        expected_grant = ContentAddress(ref=grant.grant_ref, sha256=grant.grant_hash)
        expected_evidence = ContentAddress(ref=evidence.evidence_ref, sha256=evidence.evidence_hash)
        for label, address in (
            ("claim_publication_intent", claim_intent),
            ("execution_admission", admission_address),
            ("valid_authority_grant", expected_grant),
            ("authority_evidence", expected_evidence),
            ("authenticated_authority_receipt", evidence.authenticated_receipt),
            ("context_position", admission.context_position),
        ):
            _require_canonical_content_address(label, address)
        mismatches: list[str] = []
        if admission.decision != "admit" or not admission.lease_eligible:
            mismatches.append("execution_admission_not_admitted")
        if not admission.issued_at <= checked < admission.valid_until:
            mismatches.append("execution_admission_not_current")
        if not grant.issued_at <= checked < grant.valid_until:
            mismatches.append("valid_authority_grant_not_current")
        if not evidence.not_before <= checked < evidence.valid_until:
            mismatches.append("authority_evidence_not_current")
        if evidence.revoked_by_refs:
            mismatches.append("authority_evidence_revoked")
        if admission.claim_publication_intent != claim_intent:
            mismatches.append("claim_publication_intent_mismatch")
        if (
            admission.task_ref != intent.task_id
            or admission.lane != intent.role
            or admission.session_ref != intent.session_id
            or admission.authority_case != intent.binding.authority_case
        ):
            mismatches.append("claim_binding_identity_mismatch")
        if admission.dispatch_message_id != intent.binding.dispatch_message_id:
            mismatches.append("dispatch_message_mismatch")
        if admission.idempotency_key != intent.binding.coord_dispatch_idempotency_key:
            mismatches.append("dispatch_idempotency_mismatch")
        if admission.authority_grant != expected_grant:
            mismatches.append("admission_grant_mismatch")
        if admission.intent.ref != grant.intent_ref or admission.intent.sha256 != grant.intent_hash:
            mismatches.append("grant_intent_mismatch")
        if (
            grant.evidence_ref != evidence.evidence_ref
            or grant.evidence_hash != evidence.evidence_hash
        ):
            mismatches.append("grant_evidence_mismatch")
        if grant.authenticated_receipt != evidence.authenticated_receipt:
            mismatches.append("authority_receipt_mismatch")
        if grant.authority_source != evidence.authority_source:
            mismatches.append("authority_source_mismatch")
        if (
            grant.position_ref != admission.context_position.ref
            or grant.position_hash != admission.context_position.sha256
        ):
            mismatches.append("authority_position_mismatch")
        if (
            grant.task_ref != admission.task_ref
            or grant.authority_case != admission.authority_case
            or evidence.authority_case != admission.authority_case
        ):
            mismatches.append("authority_identity_mismatch")
        if (
            grant.supersession_frontier_ref != admission.supersession_frontier_ref
            or evidence.supersession_frontier_ref != admission.supersession_frontier_ref
        ):
            mismatches.append("authority_frontier_mismatch")
        if grant.authorized_flags != admission.authorized_flags:
            mismatches.append("authority_flags_mismatch")
        if grant.scope_refs != admission.immutable_scope_refs:
            mismatches.append("authority_scope_mismatch")
        if mismatches:
            raise ClaimPublicationError(
                "claim_admission_identity_mismatch",
                "rebuild the claim from one current, cross-bound admission proof vector",
                ",".join(sorted(set(mismatches))),
            )
        valid_until = min(admission.valid_until, grant.valid_until, evidence.valid_until)
        values: dict[str, object] = {
            "schema": HISTORICAL_CLAIM_ADMISSION_CONSUMPTION_SCHEMA,
            "claim_publication_intent": claim_intent.model_dump(mode="json"),
            "execution_admission": admission_address.model_dump(mode="json"),
            "valid_authority_grant": expected_grant.model_dump(mode="json"),
            "authority_evidence": expected_evidence.model_dump(mode="json"),
            "authenticated_authority_receipt": evidence.authenticated_receipt.model_dump(
                mode="json"
            ),
            "context_position": admission.context_position.model_dump(mode="json"),
            "task_id": intent.task_id,
            "lane": intent.role,
            "session_id": intent.session_id,
            "claim_epoch": intent.claim_epoch,
            "authority_case": intent.binding.authority_case,
            "dispatch_message_id": intent.binding.dispatch_message_id,
            "idempotency_key": admission.idempotency_key,
            "supersession_frontier_ref": admission.supersession_frontier_ref,
            "checked_at": checked,
            "valid_until": valid_until,
            "proofs": tuple(item.to_record() for item in ordered),
            "may_authorize": False,
        }
        digest = _sha256(b"hapax.claim-admission-consumption.v1\0" + _canonical(values))
        return cls(
            consumption_ref=f"claim-admission-consumption@sha256:{digest}",
            consumption_hash=digest,
            claim_publication_intent=claim_intent,
            execution_admission=admission_address,
            valid_authority_grant=expected_grant,
            authority_evidence=expected_evidence,
            authenticated_authority_receipt=evidence.authenticated_receipt,
            context_position=admission.context_position,
            task_id=intent.task_id,
            lane=intent.role,
            session_id=intent.session_id,
            claim_epoch=intent.claim_epoch,
            authority_case=intent.binding.authority_case,
            dispatch_message_id=intent.binding.dispatch_message_id,
            idempotency_key=admission.idempotency_key,
            supersession_frontier_ref=admission.supersession_frontier_ref,
            checked_at=checked,
            valid_until=valid_until,
            proofs=ordered,
            may_authorize=False,
        )

    def to_record(self) -> dict[str, object]:
        return {
            "admission_consumption_hash": self.consumption_hash,
            "admission_consumption_ref": self.consumption_ref,
            "authenticated_authority_receipt": self.authenticated_authority_receipt.model_dump(
                mode="json"
            ),
            "authority_case": self.authority_case,
            "authority_evidence": self.authority_evidence.model_dump(mode="json"),
            "checked_at": self.checked_at,
            "claim_epoch": self.claim_epoch,
            "claim_publication_intent": self.claim_publication_intent.model_dump(mode="json"),
            "context_position": self.context_position.model_dump(mode="json"),
            "dispatch_message_id": self.dispatch_message_id,
            "execution_admission": self.execution_admission.model_dump(mode="json"),
            "idempotency_key": self.idempotency_key,
            "lane": self.lane,
            "may_authorize": self.may_authorize,
            "proofs": [item.to_record() for item in self.proofs],
            "schema": HISTORICAL_CLAIM_ADMISSION_CONSUMPTION_SCHEMA,
            "session_id": self.session_id,
            "supersession_frontier_ref": self.supersession_frontier_ref,
            "task_id": self.task_id,
            "valid_authority_grant": self.valid_authority_grant.model_dump(mode="json"),
            "valid_until": self.valid_until,
        }

    def proof_projections(self) -> tuple[FileProjection, ...]:
        return tuple(item.proof_projection() for item in self.proofs)

    def require_source_proofs(self, intent: ClaimPublicationIntent) -> None:
        try:
            refreshed = HistoricalClaimAdmissionConsumptionV1.create(
                intent,
                execution_admission_path=next(
                    item.path for item in self.proofs if item.kind == "execution_admission"
                ),
                valid_authority_grant_path=next(
                    item.path for item in self.proofs if item.kind == "valid_authority_grant"
                ),
                authority_evidence_path=next(
                    item.path for item in self.proofs if item.kind == "authority_evidence"
                ),
                checked_at=self.checked_at,
            )
        except (ClaimPublicationError, StopIteration) as exc:
            raise ClaimPublicationError(
                "claim_admission_proof_drift",
                "retry with the exact current admission proof vector",
                self.consumption_ref,
            ) from exc
        if refreshed != self:
            raise ClaimPublicationError(
                "claim_admission_proof_drift",
                "retry with the exact current admission proof vector",
                self.consumption_ref,
            )


@dataclass(frozen=True)
class ClaimAdmissionConsumption:
    """Current five-proof publication lease consumed by transaction v3."""

    consumption_ref: str
    consumption_hash: str
    claim_publication_intent: ContentAddress
    prospective_claim_basis: ContentAddress
    action_intent: ContentAddress
    execution_admission: ContentAddress
    valid_authority_grant: ContentAddress
    authority_evidence: ContentAddress
    authenticated_authority_receipt: ContentAddress
    context_position: ContentAddress
    execution_lease: ContentAddress
    bound_execution_call: ContentAddress
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    task_id: str
    lane: str
    session_id: str
    claim_epoch: int
    authority_case: str
    dispatch_message_id: str
    idempotency_key: str
    invocation_id: str
    attempt_fence: str
    supersession_frontier_ref: str
    checked_at: str
    valid_until: str
    proofs: tuple[AdmissionArtifactSnapshot, ...]
    may_authorize: Literal[False]

    @classmethod
    def create(
        cls,
        intent: ClaimPublicationIntent,
        *,
        action_intent_path: Path,
        execution_admission_path: Path,
        valid_authority_grant_path: Path,
        authority_evidence_path: Path,
        execution_lease_path: Path,
        checked_at: str | datetime,
    ) -> ClaimAdmissionConsumption:
        proofs = tuple(
            sorted(
                (
                    _load_admission_artifact("action_intent", action_intent_path),
                    _load_admission_artifact("authority_evidence", authority_evidence_path),
                    _load_admission_artifact("execution_admission", execution_admission_path),
                    _load_admission_artifact("execution_lease", execution_lease_path),
                    _load_admission_artifact(
                        "valid_authority_grant",
                        valid_authority_grant_path,
                    ),
                ),
                key=lambda item: item.kind,
            )
        )
        return cls._from_proofs(intent, proofs=proofs, checked_at=checked_at)

    @classmethod
    def _from_proofs(
        cls,
        intent: ClaimPublicationIntent,
        *,
        proofs: Sequence[AdmissionArtifactSnapshot],
        checked_at: str | datetime,
    ) -> ClaimAdmissionConsumption:
        ordered = tuple(sorted(proofs, key=lambda item: item.kind))
        expected_kinds = (
            "action_intent",
            "authority_evidence",
            "execution_admission",
            "execution_lease",
            "valid_authority_grant",
        )
        if tuple(item.kind for item in ordered) != expected_kinds:
            raise ClaimPublicationError(
                "claim_admission_proof_vector_invalid",
                "provide exactly one intent, evidence, admission, lease, and grant proof",
            )
        if len({item.path for item in ordered}) != len(ordered):
            raise ClaimPublicationError(
                "claim_admission_proof_path_collision",
                "materialize each publication proof at one distinct normalized path",
            )
        by_kind = {item.kind: item.model for item in ordered}
        action = by_kind["action_intent"]
        evidence = by_kind["authority_evidence"]
        admission = by_kind["execution_admission"]
        lease = by_kind["execution_lease"]
        grant = by_kind["valid_authority_grant"]
        if not isinstance(action, ActionIntent):
            raise ClaimPublicationError(
                "claim_admission_artifact_kind_mismatch",
                "restore the typed claim-publication action intent",
            )
        if not isinstance(evidence, AuthorityEvidence):
            raise ClaimPublicationError(
                "claim_admission_artifact_kind_mismatch",
                "restore the typed authority evidence",
            )
        if not isinstance(admission, ExecutionAdmission):
            raise ClaimPublicationError(
                "claim_admission_artifact_kind_mismatch",
                "restore the typed execution admission",
            )
        if not isinstance(lease, ExecutionLease):
            raise ClaimPublicationError(
                "claim_admission_artifact_kind_mismatch",
                "restore the active execution lease",
            )
        if not isinstance(grant, ValidAuthorityGrant):
            raise ClaimPublicationError(
                "claim_admission_artifact_kind_mismatch",
                "restore the typed valid authority grant",
            )
        lease = require_admitted_execution_lease(lease)
        checked = _canonical_timestamp(checked_at)
        basis = prospective_claim_publication_basis(intent)
        claim_intent = ContentAddress(ref=intent.intent_ref, sha256=intent.intent_sha256)
        basis_address = ContentAddress(ref=basis.basis_ref, sha256=basis.basis_hash)
        action_address = ContentAddress(ref=action.intent_ref, sha256=action.intent_hash)
        admission_address = ContentAddress(
            ref=admission.admission_ref,
            sha256=admission.admission_hash,
        )
        grant_address = ContentAddress(ref=grant.grant_ref, sha256=grant.grant_hash)
        evidence_address = ContentAddress(
            ref=evidence.evidence_ref,
            sha256=evidence.evidence_hash,
        )
        lease_address = ContentAddress(ref=lease.lease_ref, sha256=lease.lease_hash)
        call_address = ContentAddress(
            ref=lease.bound_call.call_ref,
            sha256=lease.bound_call.call_hash,
        )
        addressed_roots = {
            "claim_publication_intent": claim_intent,
            "prospective_claim_basis": basis_address,
            "action_intent": action_address,
            "execution_admission": admission_address,
            "valid_authority_grant": grant_address,
            "authority_evidence": evidence_address,
            "authenticated_authority_receipt": evidence.authenticated_receipt,
            "context_position": admission.context_position,
            "execution_lease": lease_address,
            "bound_execution_call": call_address,
            "effect_manifest": lease.effect_manifest,
            "executor_descriptor": lease.executor_descriptor,
            "executor_registry_projection": lease.executor_registry_projection,
        }
        for label, address in addressed_roots.items():
            _require_canonical_content_address(label, address)
        expected_task_note = claim_publication_task_note_address(intent)
        expected_mutation_scope = claim_publication_mutation_scope_address(intent)
        mismatches: list[str] = []
        if action.operation != "claim.publish" or action.action_class != "claim_publication":
            mismatches.append("claim_publication_action_not_exact")
        if not action.mutating:
            mismatches.append("claim_publication_action_not_mutating")
        if action.requested_scope_refs != (
            expected_mutation_scope.ref,
        ) or action.requested_effect_targets != (expected_mutation_scope,):
            mismatches.append("claim_publication_mutation_scope_not_exact")
        if admission.decision != "admit" or not admission.lease_eligible:
            mismatches.append("execution_admission_not_admitted")
        if not admission.issued_at <= checked < admission.valid_until:
            mismatches.append("execution_admission_not_current")
        if not grant.issued_at <= checked < grant.valid_until:
            mismatches.append("valid_authority_grant_not_current")
        if not evidence.not_before <= checked < evidence.valid_until:
            mismatches.append("authority_evidence_not_current")
        if not lease.not_before <= checked < lease.expires_at:
            mismatches.append("execution_lease_not_current")
        if evidence.revoked_by_refs:
            mismatches.append("authority_evidence_revoked")
        if (
            admission.intent != action_address
            or grant.intent_ref != action.intent_ref
            or grant.intent_hash != action.intent_hash
            or lease.bound_call.action_intent != action_address
        ):
            mismatches.append("publication_action_intent_mismatch")
        if (
            admission.authority_grant != grant_address
            or lease.authority_grant != grant_address
            or lease.bound_call.authority_grant != grant_address
        ):
            mismatches.append("publication_authority_grant_mismatch")
        if (
            grant.evidence_ref != evidence.evidence_ref
            or grant.evidence_hash != evidence.evidence_hash
            or grant.authenticated_receipt != evidence.authenticated_receipt
        ):
            mismatches.append("publication_authority_evidence_mismatch")
        if lease.admission != admission_address or lease.bound_call.admission != admission_address:
            mismatches.append("publication_admission_mismatch")
        if (
            not isinstance(lease.claim_basis, ProspectiveClaimPublicationBasis)
            or lease.claim_basis != basis
            or lease.claim_coordinates.state != "prospective"
            or lease.claim_coordinates.claim_basis != basis_address
            or lease.bound_call.claim_basis != basis_address
        ):
            mismatches.append("prospective_claim_basis_mismatch")
        if (
            admission.claim_publication_intent != claim_intent
            or action.task_ref != intent.task_id
            or admission.task_ref != intent.task_id
            or grant.task_ref != intent.task_id
            or lease.task_ref != intent.task_id
            or lease.lane != intent.role
            or lease.session_ref != intent.session_id
            or lease.claim_epoch != intent.claim_epoch
            or admission.lane != intent.role
            or admission.session_ref != intent.session_id
        ):
            mismatches.append("claim_binding_identity_mismatch")
        if (
            admission.task_note != expected_task_note
            or lease.bound_call.task_note != expected_task_note
        ):
            mismatches.append("claim_publication_task_note_preimage_mismatch")
        if (
            admission.dispatch_message_id != intent.binding.dispatch_message_id
            or admission.idempotency_key != intent.binding.coord_dispatch_idempotency_key
            or lease.idempotency_key != intent.binding.coord_dispatch_idempotency_key
            or basis.dispatch_binding_hash != intent.binding.binding_hash
            or basis.dispatch_binding_receipt_hash != intent.binding.receipt_hash
        ):
            mismatches.append("claim_dispatch_binding_mismatch")
        if (
            grant.operation != action.operation
            or grant.action_class != action.action_class
            or grant.authorized_flags != admission.authorized_flags
            or grant.scope_refs != admission.immutable_scope_refs
            or action.requested_scope_refs != admission.immutable_scope_refs
        ):
            mismatches.append("claim_publication_authority_scope_mismatch")
        if (
            grant.authenticated_receipt != evidence.authenticated_receipt
            or grant.authority_source != evidence.authority_source
            or grant.acting_subject != action.acting_subject
            or grant.authority_issuer != evidence.issuer
            or evidence.subject != action.acting_subject
            or grant.authority_ceiling != evidence.authority_ceiling
        ):
            mismatches.append("claim_publication_authority_subject_mismatch")
        if (
            grant.position_ref != admission.context_position.ref
            or grant.position_hash != admission.context_position.sha256
            or action.position_ref != admission.context_position.ref
            or action.position_hash != admission.context_position.sha256
        ):
            mismatches.append("claim_publication_context_position_mismatch")
        if (
            grant.authority_case != intent.binding.authority_case
            or admission.authority_case != intent.binding.authority_case
            or evidence.authority_case != intent.binding.authority_case
        ):
            mismatches.append("claim_publication_authority_case_mismatch")
        if (
            grant.supersession_frontier_ref != admission.supersession_frontier_ref
            or evidence.supersession_frontier_ref != admission.supersession_frontier_ref
            or lease.supersession_frontier_ref != admission.supersession_frontier_ref
        ):
            mismatches.append("claim_publication_frontier_mismatch")
        if (
            admission.effect_manifest != action.effect_manifest
            or lease.effect_manifest != action.effect_manifest
            or lease.bound_call.effect_manifest != action.effect_manifest
            or lease.bound_call.protected_action_request != action.protected_action_request
        ):
            mismatches.append("claim_publication_effect_mismatch")
        if (
            action.required_authorization_flags != grant.authorized_flags
            or action.required_authorization_flags != admission.authorized_flags
            or action.action_class not in evidence.authorized_action_classes
            or action.operation not in evidence.authorized_operations
            or not set(action.required_authorization_flags).issubset(evidence.authorized_flags)
            or not set(action.requested_scope_refs).issubset(evidence.scope_refs)
        ):
            mismatches.append("claim_publication_authority_narrowing_mismatch")
        if (
            admission.parent_spec != action.parent_spec
            or admission.decomposition != action.decomposition
        ):
            mismatches.append("claim_publication_decomposition_mismatch")
        call = lease.bound_call
        if (
            call.capability_role != action.capability_role
            or call.execution_host != action.execution_host
            or call.acting_subject != action.acting_subject
            or call.requested_effect_targets != action.requested_effect_targets
            or call.requested_scope_refs != action.requested_scope_refs
            or call.required_authorization_flags != action.required_authorization_flags
            or call.operation != action.operation
            or call.action_class != action.action_class
            or call.authority_case != intent.binding.authority_case
            or call.dispatch_message_id != intent.binding.dispatch_message_id
            or call.platform != intent.binding.platform
            or call.mode != intent.binding.mode
            or call.profile != intent.binding.profile
        ):
            mismatches.append("claim_publication_bound_call_mismatch")
        if (
            admission.route_decision != call.route_decision
            or admission.execution_target != call.execution_target
            or admission.selected_descriptor_leaf != call.selected_descriptor_leaf
            or lease.execution_target != call.execution_target
            or lease.selected_descriptor_leaf != call.selected_descriptor_leaf
        ):
            mismatches.append("claim_publication_route_target_mismatch")
        coordinates = lease.claim_coordinates
        if (
            coordinates.task_ref != intent.task_id
            or coordinates.lane != intent.role
            or coordinates.session_ref != intent.session_id
            or coordinates.claim_epoch != intent.claim_epoch
            or coordinates.claim_publication_intent != claim_intent
        ):
            mismatches.append("claim_publication_coordinates_mismatch")
        if mismatches:
            raise ClaimPublicationError(
                "claim_admission_identity_mismatch",
                "rebuild the publication from one current five-proof lease vector",
                ",".join(sorted(set(mismatches))),
            )
        valid_until = min(
            admission.valid_until,
            grant.valid_until,
            evidence.valid_until,
            lease.expires_at,
        )
        values: dict[str, object] = {
            "schema": CLAIM_ADMISSION_CONSUMPTION_SCHEMA,
            **{
                label: address.model_dump(mode="json") for label, address in addressed_roots.items()
            },
            "task_id": intent.task_id,
            "lane": intent.role,
            "session_id": intent.session_id,
            "claim_epoch": intent.claim_epoch,
            "authority_case": intent.binding.authority_case,
            "dispatch_message_id": intent.binding.dispatch_message_id,
            "idempotency_key": admission.idempotency_key,
            "invocation_id": lease.invocation_id,
            "attempt_fence": lease.attempt_fence,
            "supersession_frontier_ref": admission.supersession_frontier_ref,
            "checked_at": checked,
            "valid_until": valid_until,
            "proofs": tuple(item.to_record() for item in ordered),
            "may_authorize": False,
        }
        digest = _sha256(
            CLAIM_ADMISSION_CONSUMPTION_SCHEMA.encode("ascii") + b"\0" + _canonical(values)
        )
        return cls(
            consumption_ref=f"claim-admission-consumption@sha256:{digest}",
            consumption_hash=digest,
            claim_publication_intent=claim_intent,
            prospective_claim_basis=basis_address,
            action_intent=action_address,
            execution_admission=admission_address,
            valid_authority_grant=grant_address,
            authority_evidence=evidence_address,
            authenticated_authority_receipt=evidence.authenticated_receipt,
            context_position=admission.context_position,
            execution_lease=lease_address,
            bound_execution_call=call_address,
            effect_manifest=lease.effect_manifest,
            executor_descriptor=lease.executor_descriptor,
            executor_registry_projection=lease.executor_registry_projection,
            task_id=intent.task_id,
            lane=intent.role,
            session_id=intent.session_id,
            claim_epoch=intent.claim_epoch,
            authority_case=intent.binding.authority_case,
            dispatch_message_id=intent.binding.dispatch_message_id,
            idempotency_key=admission.idempotency_key,
            invocation_id=lease.invocation_id,
            attempt_fence=lease.attempt_fence,
            supersession_frontier_ref=admission.supersession_frontier_ref,
            checked_at=checked,
            valid_until=valid_until,
            proofs=ordered,
            may_authorize=False,
        )

    def to_record(self) -> dict[str, object]:
        return {
            "action_intent": self.action_intent.model_dump(mode="json"),
            "admission_consumption_hash": self.consumption_hash,
            "admission_consumption_ref": self.consumption_ref,
            "attempt_fence": self.attempt_fence,
            "authenticated_authority_receipt": self.authenticated_authority_receipt.model_dump(
                mode="json"
            ),
            "authority_case": self.authority_case,
            "authority_evidence": self.authority_evidence.model_dump(mode="json"),
            "bound_execution_call": self.bound_execution_call.model_dump(mode="json"),
            "checked_at": self.checked_at,
            "claim_epoch": self.claim_epoch,
            "claim_publication_intent": self.claim_publication_intent.model_dump(mode="json"),
            "context_position": self.context_position.model_dump(mode="json"),
            "dispatch_message_id": self.dispatch_message_id,
            "effect_manifest": self.effect_manifest.model_dump(mode="json"),
            "execution_admission": self.execution_admission.model_dump(mode="json"),
            "execution_lease": self.execution_lease.model_dump(mode="json"),
            "executor_descriptor": self.executor_descriptor.model_dump(mode="json"),
            "executor_registry_projection": self.executor_registry_projection.model_dump(
                mode="json"
            ),
            "idempotency_key": self.idempotency_key,
            "invocation_id": self.invocation_id,
            "lane": self.lane,
            "may_authorize": self.may_authorize,
            "proofs": [item.to_record() for item in self.proofs],
            "prospective_claim_basis": self.prospective_claim_basis.model_dump(mode="json"),
            "schema": CLAIM_ADMISSION_CONSUMPTION_SCHEMA,
            "session_id": self.session_id,
            "supersession_frontier_ref": self.supersession_frontier_ref,
            "task_id": self.task_id,
            "valid_authority_grant": self.valid_authority_grant.model_dump(mode="json"),
            "valid_until": self.valid_until,
        }

    def proof_projections(self) -> tuple[FileProjection, ...]:
        return tuple(item.proof_projection() for item in self.proofs)

    def require_source_proofs(self, intent: ClaimPublicationIntent) -> None:
        try:
            refreshed = ClaimAdmissionConsumption._from_proofs(
                intent,
                proofs=tuple(
                    _load_admission_artifact(item.kind, item.path) for item in self.proofs
                ),
                checked_at=self.checked_at,
            )
        except ClaimPublicationError as exc:
            raise ClaimPublicationError(
                "claim_admission_proof_drift",
                "retry with the exact current five-proof publication vector",
                self.consumption_ref,
            ) from exc
        if refreshed != self:
            raise ClaimPublicationError(
                "claim_admission_proof_drift",
                "retry with the exact current five-proof publication vector",
                self.consumption_ref,
            )


ClaimAdmissionConsumptionRecord = HistoricalClaimAdmissionConsumptionV1 | ClaimAdmissionConsumption


def _historical_claim_admission_consumption_from_record(
    intent: ClaimPublicationIntent,
    record: object,
    projections: Sequence[FileProjection],
) -> HistoricalClaimAdmissionConsumptionV1:
    expected_keys = {
        "admission_consumption_hash",
        "admission_consumption_ref",
        "authenticated_authority_receipt",
        "authority_case",
        "authority_evidence",
        "checked_at",
        "claim_epoch",
        "claim_publication_intent",
        "context_position",
        "dispatch_message_id",
        "execution_admission",
        "idempotency_key",
        "lane",
        "may_authorize",
        "proofs",
        "schema",
        "session_id",
        "supersession_frontier_ref",
        "task_id",
        "valid_authority_grant",
        "valid_until",
    }
    if (
        not isinstance(record, dict)
        or set(record) != expected_keys
        or record.get("schema") != HISTORICAL_CLAIM_ADMISSION_CONSUMPTION_SCHEMA
        or record.get("may_authorize") is not False
        or not isinstance(record.get("proofs"), list)
        or len(record["proofs"]) != 3
        or len(projections) != 3
    ):
        raise ClaimPublicationError(
            "claim_admission_consumption_malformed",
            "restore the exact three-proof admission consumption record",
        )
    proofs: list[AdmissionArtifactSnapshot] = []
    for proof_record, projection in zip(record["proofs"], projections, strict=True):
        if not isinstance(proof_record, dict):
            raise ClaimPublicationError(
                "claim_admission_consumption_malformed",
                "restore each exact admission proof record",
            )
        kind = proof_record.get("kind")
        if kind not in {
            "authority_evidence",
            "execution_admission",
            "valid_authority_grant",
        }:
            raise ClaimPublicationError(
                "claim_admission_consumption_malformed",
                "restore each typed admission proof kind",
                str(kind),
            )
        if (
            projection.before is None
            or projection.after != projection.before
            or projection.before_mode != 0o600
            or projection.after_mode != 0o600
        ):
            raise ClaimPublicationError(
                "claim_admission_projection_malformed",
                "restore each immutable mode-0600 no-op admission proof projection",
                str(projection.path),
            )
        snapshot = _parse_admission_artifact(
            kind=kind,
            path=projection.path,
            content=projection.before,
            mode=projection.before_mode,
        )
        if snapshot.to_record() != proof_record:
            raise ClaimPublicationError(
                "claim_admission_proof_record_mismatch",
                "restore the proof record bound to its exact journal blob",
                str(projection.path),
            )
        proofs.append(snapshot)
    consumption = HistoricalClaimAdmissionConsumptionV1._from_proofs(
        intent,
        proofs=proofs,
        checked_at=str(record.get("checked_at")),
    )
    if consumption.to_record() != record:
        raise ClaimPublicationError(
            "claim_admission_consumption_identity_mismatch",
            "restore the self-hashed consumption bound to its exact proof vector",
        )
    return consumption


def _current_claim_admission_consumption_from_record(
    intent: ClaimPublicationIntent,
    record: object,
    projections: Sequence[FileProjection],
) -> ClaimAdmissionConsumption:
    expected_keys = set(ClaimAdmissionConsumption.__dataclass_fields__) - {
        "consumption_ref",
        "consumption_hash",
        "proofs",
    }
    expected_keys.update(
        {
            "admission_consumption_hash",
            "admission_consumption_ref",
            "proofs",
            "schema",
        }
    )
    if (
        not isinstance(record, dict)
        or set(record) != expected_keys
        or record.get("schema") != CLAIM_ADMISSION_CONSUMPTION_SCHEMA
        or record.get("may_authorize") is not False
        or not isinstance(record.get("proofs"), list)
        or len(record["proofs"]) != 5
        or len(projections) != 5
    ):
        raise ClaimPublicationError(
            "claim_admission_consumption_malformed",
            "restore the exact five-proof publication consumption record",
        )
    proofs: list[AdmissionArtifactSnapshot] = []
    allowed_kinds = {
        "action_intent",
        "authority_evidence",
        "execution_admission",
        "execution_lease",
        "valid_authority_grant",
    }
    for proof_record, projection in zip(record["proofs"], projections, strict=True):
        if not isinstance(proof_record, dict) or proof_record.get("kind") not in allowed_kinds:
            raise ClaimPublicationError(
                "claim_admission_consumption_malformed",
                "restore each typed publication proof record",
            )
        if (
            projection.before is None
            or projection.after != projection.before
            or projection.before_mode != 0o600
            or projection.after_mode != 0o600
        ):
            raise ClaimPublicationError(
                "claim_admission_projection_malformed",
                "restore each immutable mode-0600 no-op publication proof",
                str(projection.path),
            )
        snapshot = _parse_admission_artifact(
            kind=proof_record["kind"],
            path=projection.path,
            content=projection.before,
            mode=projection.before_mode,
        )
        if snapshot.to_record() != proof_record:
            raise ClaimPublicationError(
                "claim_admission_proof_record_mismatch",
                "restore the proof record bound to its exact journal blob",
                str(projection.path),
            )
        proofs.append(snapshot)
    consumption = ClaimAdmissionConsumption._from_proofs(
        intent,
        proofs=proofs,
        checked_at=str(record.get("checked_at")),
    )
    if consumption.to_record() != record:
        raise ClaimPublicationError(
            "claim_admission_consumption_identity_mismatch",
            "restore the self-hashed five-proof consumption",
        )
    return consumption


def _claim_admission_consumption_from_record(
    intent: ClaimPublicationIntent,
    record: object,
    projections: Sequence[FileProjection],
) -> HistoricalClaimAdmissionConsumptionV1 | ClaimAdmissionConsumption:
    schema = record.get("schema") if isinstance(record, dict) else None
    if schema == HISTORICAL_CLAIM_ADMISSION_CONSUMPTION_SCHEMA:
        return _historical_claim_admission_consumption_from_record(
            intent,
            record,
            projections,
        )
    if schema == CLAIM_ADMISSION_CONSUMPTION_SCHEMA:
        return _current_claim_admission_consumption_from_record(
            intent,
            record,
            projections,
        )
    raise ClaimPublicationError(
        "claim_admission_consumption_schema_unknown",
        "supply exact historical-v1 or active-v2 consumption bytes",
        str(schema),
    )


@dataclass(frozen=True)
class ClaimPublicationReceipt:
    publication_id: str
    binding_receipt_hash: str
    task_id: str
    role: str
    session_id: str
    claim_epoch: int
    intent_sha256: str
    manifest_static_sha256: str
    projection_vector_sha256: str
    claim_note_postimage_sha256: str
    manifest_path: Path
    receipt_path: Path
    receipt_hash: str
    recovered: bool = False
    schema: str = CLAIM_PUBLICATION_RECEIPT_SCHEMA
    admission_consumption: ContentAddress | None = None
    execution_admission: ContentAddress | None = None
    valid_authority_grant: ContentAddress | None = None
    authority_evidence: ContentAddress | None = None
    authenticated_authority_receipt: ContentAddress | None = None
    context_position: ContentAddress | None = None
    action_intent: ContentAddress | None = None
    prospective_claim_basis: ContentAddress | None = None
    execution_lease: ContentAddress | None = None
    bound_execution_call: ContentAddress | None = None
    effect_manifest: ContentAddress | None = None
    executor_descriptor: ContentAddress | None = None
    executor_registry_projection: ContentAddress | None = None
    invocation_id: str | None = None
    attempt_fence: str | None = None
    supersession_frontier_ref: str | None = None
    admission_valid_until: str | None = None


@dataclass(frozen=True)
class ClaimPublicationRecoveryResult:
    publication_id: str
    state: str
    reason_code: str | None = None


@dataclass(frozen=True)
class ClaimPublicationInspection:
    """Self-hashed, non-authorizing estate observation at one bounded frontier."""

    publication_id: str
    task_id: str | None
    disposition: Literal["terminal_applied", "terminal_aborted", "hold"]
    journal_schema: str | None
    journal_state: str | None
    journal_reason_code: str | None
    claim_epoch: int | None
    binding_receipt_hash: str | None
    manifest_address: ContentAddress | None
    receipt_address: ContentAddress | None
    journal_addresses: tuple[ContentAddress, ...]
    projection_addresses: tuple[ContentAddress, ...]
    observation_frontier: tuple[ContentAddress, ...]
    observed_at: str
    reason_code: str | None = None
    repair_action: str | None = None
    detail: str | None = None
    inspection_ref: str = ""
    inspection_hash: str = ""
    may_authorize: Literal[False] = False
    schema: str = CLAIM_PUBLICATION_INSPECTION_SCHEMA

    @staticmethod
    def _address_record(value: ContentAddress | None) -> dict[str, str] | None:
        return None if value is None else value.model_dump(mode="json")

    @classmethod
    def create(
        cls,
        *,
        publication_id: str,
        task_id: str | None,
        disposition: Literal["terminal_applied", "terminal_aborted", "hold"],
        journal_schema: str | None,
        journal_state: str | None,
        journal_reason_code: str | None,
        claim_epoch: int | None,
        binding_receipt_hash: str | None,
        manifest_address: ContentAddress | None,
        receipt_address: ContentAddress | None,
        journal_addresses: Sequence[ContentAddress],
        projection_addresses: Sequence[ContentAddress],
        observation_frontier: Sequence[ContentAddress],
        observed_at: str | datetime,
        reason_code: str | None = None,
        repair_action: str | None = None,
        detail: str | None = None,
    ) -> ClaimPublicationInspection:
        journal = tuple(
            sorted(
                {(item.ref, item.sha256): item for item in journal_addresses}.values(),
                key=lambda item: (item.ref, item.sha256),
            )
        )
        projections = tuple(projection_addresses)
        frontier = tuple(
            sorted(
                {(item.ref, item.sha256): item for item in observation_frontier}.values(),
                key=lambda item: (item.ref, item.sha256),
            )
        )
        timestamp = _canonical_timestamp(observed_at)
        body: dict[str, object] = {
            "binding_receipt_hash": binding_receipt_hash,
            "claim_epoch": claim_epoch,
            "detail": detail,
            "disposition": disposition,
            "journal_addresses": tuple(cls._address_record(item) for item in journal),
            "journal_reason_code": journal_reason_code,
            "journal_schema": journal_schema,
            "journal_state": journal_state,
            "manifest_address": cls._address_record(manifest_address),
            "may_authorize": False,
            "observation_frontier": tuple(cls._address_record(item) for item in frontier),
            "observed_at": timestamp,
            "projection_addresses": tuple(cls._address_record(item) for item in projections),
            "publication_id": publication_id,
            "reason_code": reason_code,
            "receipt_address": cls._address_record(receipt_address),
            "repair_action": repair_action,
            "schema": CLAIM_PUBLICATION_INSPECTION_SCHEMA,
            "task_id": task_id,
        }
        digest = _sha256(
            CLAIM_PUBLICATION_INSPECTION_SCHEMA.encode("ascii") + b"\0" + _canonical(body)
        )
        return cls(
            publication_id=publication_id,
            task_id=task_id,
            disposition=disposition,
            journal_schema=journal_schema,
            journal_state=journal_state,
            journal_reason_code=journal_reason_code,
            claim_epoch=claim_epoch,
            binding_receipt_hash=binding_receipt_hash,
            manifest_address=manifest_address,
            receipt_address=receipt_address,
            journal_addresses=journal,
            projection_addresses=projections,
            observation_frontier=frontier,
            observed_at=timestamp,
            reason_code=reason_code,
            repair_action=repair_action,
            detail=detail,
            inspection_ref=f"claim-publication-inspection@sha256:{digest}",
            inspection_hash=digest,
        )

    def identity_body(self) -> dict[str, object]:
        return {
            "binding_receipt_hash": self.binding_receipt_hash,
            "claim_epoch": self.claim_epoch,
            "detail": self.detail,
            "disposition": self.disposition,
            "journal_addresses": tuple(
                self._address_record(item) for item in self.journal_addresses
            ),
            "journal_reason_code": self.journal_reason_code,
            "journal_schema": self.journal_schema,
            "journal_state": self.journal_state,
            "manifest_address": self._address_record(self.manifest_address),
            "may_authorize": self.may_authorize,
            "observation_frontier": tuple(
                self._address_record(item) for item in self.observation_frontier
            ),
            "observed_at": self.observed_at,
            "projection_addresses": tuple(
                self._address_record(item) for item in self.projection_addresses
            ),
            "publication_id": self.publication_id,
            "reason_code": self.reason_code,
            "receipt_address": self._address_record(self.receipt_address),
            "repair_action": self.repair_action,
            "schema": self.schema,
            "task_id": self.task_id,
        }

    def to_record(self) -> dict[str, object]:
        return {
            **self.identity_body(),
            "inspection_hash": self.inspection_hash,
            "inspection_ref": self.inspection_ref,
        }

    def __post_init__(self) -> None:
        if self.schema != CLAIM_PUBLICATION_INSPECTION_SCHEMA or self.may_authorize is not False:
            raise ValueError("claim publication inspection must be non-authorizing v1")
        if not self.observation_frontier:
            raise ValueError("claim publication inspection requires an observation frontier")
        if self.observed_at != _canonical_timestamp(self.observed_at):
            raise ValueError("claim publication inspection requires canonical observed_at")
        if self.disposition == "hold":
            if not self.reason_code or not self.repair_action:
                raise ValueError("claim publication HOLD requires reason and repair")
        elif self.reason_code is not None or self.repair_action is not None:
            raise ValueError("terminal history cannot carry a refusal")
        if self.disposition == "terminal_applied" and (
            self.manifest_address is None or self.receipt_address is None
        ):
            raise ValueError("terminal applied history requires manifest and receipt")
        if self.disposition == "terminal_aborted" and self.manifest_address is None:
            raise ValueError("terminal aborted history requires a manifest")
        if self.disposition != "hold" and self.projection_addresses:
            raise ValueError("terminal history cannot depend on current projections")
        digest = _sha256(
            CLAIM_PUBLICATION_INSPECTION_SCHEMA.encode("ascii")
            + b"\0"
            + _canonical(self.identity_body())
        )
        if (
            self.inspection_hash != digest
            or self.inspection_ref != f"claim-publication-inspection@sha256:{digest}"
        ):
            raise ValueError("claim publication inspection identity mismatch")


@dataclass(frozen=True)
class AppliedClaimPublicationSnapshot:
    """Stable applied claim root plus the independently mutable current task."""

    intent: ClaimPublicationIntent
    current_task: TaskNoteSnapshot
    leases: tuple[ClaimLeaseSnapshot, ...]
    receipt: ClaimPublicationReceipt
    receipt_content: bytes
    receipt_mode: int
    manifest_content: bytes
    manifest_mode: int
    admission_consumption: ClaimAdmissionConsumptionRecord | None = None

    def proof_projections(self) -> tuple[FileProjection, FileProjection]:
        """No-op projections that lock the proof during a consuming transaction."""

        return (
            FileProjection.from_snapshot(
                self.receipt.receipt_path,
                before=self.receipt_content,
                before_mode=self.receipt_mode,
                after=self.receipt_content,
                after_mode=self.receipt_mode,
            ),
            FileProjection.from_snapshot(
                self.receipt.manifest_path,
                before=self.manifest_content,
                before_mode=self.manifest_mode,
                after=self.manifest_content,
                after_mode=self.manifest_mode,
            ),
        )


@dataclass(frozen=True)
class ClaimPublicationAdmissionProvenance:
    """Validated publication roots retained as history, never reusable authority."""

    admission_consumption: ClaimAdmissionConsumptionRecord
    execution_admission: ExecutionAdmission
    valid_authority_grant: ValidAuthorityGrant
    authority_evidence: AuthorityEvidence
    publication_action_intent: ContentAddress
    action_intent: ActionIntent | None = None
    execution_lease: ExecutionLease | None = None
    prospective_claim_basis: ProspectiveClaimPublicationBasis | None = None
    may_authorize: Literal[False] = False


def resolve_claim_publication_admission_provenance(
    snapshot: AppliedClaimPublicationSnapshot,
) -> ClaimPublicationAdmissionProvenance:
    consumption = snapshot.admission_consumption
    if consumption is None:
        raise ClaimPublicationError(
            "claim_admission_consumption_missing",
            "resolve one admitted transaction-v2 claim publication",
            snapshot.receipt.publication_id,
        )
    models = {proof.kind: proof.model for proof in consumption.proofs}
    admission = models.get("execution_admission")
    grant = models.get("valid_authority_grant")
    evidence = models.get("authority_evidence")
    action = models.get("action_intent")
    lease = models.get("execution_lease")
    if (
        not isinstance(admission, ExecutionAdmission)
        or not isinstance(grant, ValidAuthorityGrant)
        or not isinstance(evidence, AuthorityEvidence)
    ):
        raise ClaimPublicationError(
            "claim_admission_provenance_invalid",
            "restore the typed publication admission proof vector",
            snapshot.receipt.publication_id,
        )
    receipt = snapshot.receipt
    expected_schema = (
        HISTORICAL_ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
        if isinstance(consumption, HistoricalClaimAdmissionConsumptionV1)
        else ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
    )
    expected = (
        (
            receipt.admission_consumption,
            ContentAddress(
                ref=consumption.consumption_ref,
                sha256=consumption.consumption_hash,
            ),
        ),
        (
            receipt.execution_admission,
            ContentAddress(ref=admission.admission_ref, sha256=admission.admission_hash),
        ),
        (
            consumption.execution_admission,
            ContentAddress(ref=admission.admission_ref, sha256=admission.admission_hash),
        ),
        (
            receipt.valid_authority_grant,
            ContentAddress(ref=grant.grant_ref, sha256=grant.grant_hash),
        ),
        (
            consumption.valid_authority_grant,
            ContentAddress(ref=grant.grant_ref, sha256=grant.grant_hash),
        ),
        (
            receipt.authority_evidence,
            ContentAddress(ref=evidence.evidence_ref, sha256=evidence.evidence_hash),
        ),
        (
            consumption.authority_evidence,
            ContentAddress(ref=evidence.evidence_ref, sha256=evidence.evidence_hash),
        ),
        (
            receipt.authenticated_authority_receipt,
            evidence.authenticated_receipt,
        ),
        (
            consumption.authenticated_authority_receipt,
            evidence.authenticated_receipt,
        ),
        (receipt.context_position, admission.context_position),
        (consumption.context_position, admission.context_position),
    )
    if (
        receipt.schema != expected_schema
        or any(observed != wanted for observed, wanted in expected)
        or receipt.supersession_frontier_ref != consumption.supersession_frontier_ref
        or receipt.admission_valid_until != consumption.valid_until
        or receipt.task_id != consumption.task_id
        or receipt.role != consumption.lane
        or receipt.session_id != consumption.session_id
        or receipt.claim_epoch != consumption.claim_epoch
        or receipt.intent_sha256 != consumption.claim_publication_intent.sha256
        or admission.intent.ref != grant.intent_ref
        or admission.intent.sha256 != grant.intent_hash
    ):
        raise ClaimPublicationError(
            "claim_admission_provenance_mismatch",
            "restore the exact receipt-bound publication admission proof vector",
            receipt.publication_id,
        )
    basis: ProspectiveClaimPublicationBasis | None = None
    if isinstance(consumption, ClaimAdmissionConsumption):
        if not isinstance(action, ActionIntent) or not isinstance(lease, ExecutionLease):
            raise ClaimPublicationError(
                "claim_admission_provenance_invalid",
                "restore the current action-intent and execution-lease proofs",
                receipt.publication_id,
            )
        basis = prospective_claim_publication_basis(snapshot.intent)
        if (
            lease.claim_basis != basis
            or receipt.action_intent != consumption.action_intent
            or receipt.execution_lease != consumption.execution_lease
            or receipt.bound_execution_call != consumption.bound_execution_call
            or receipt.prospective_claim_basis != consumption.prospective_claim_basis
        ):
            raise ClaimPublicationError(
                "claim_admission_provenance_mismatch",
                "restore the receipt-bound universal publication lease roots",
                receipt.publication_id,
            )
    return ClaimPublicationAdmissionProvenance(
        admission_consumption=consumption,
        execution_admission=admission,
        valid_authority_grant=grant,
        authority_evidence=evidence,
        publication_action_intent=admission.intent,
        action_intent=action if isinstance(action, ActionIntent) else None,
        execution_lease=lease if isinstance(lease, ExecutionLease) else None,
        prospective_claim_basis=basis,
    )


def _publication_paths(intent: ClaimPublicationIntent) -> tuple[Path, ...]:
    paths: list[Path] = [intent.note_path]
    for key in (intent.role, f"{intent.role}-{intent.session_id}"):
        paths.extend(
            (
                intent.cache_dir / f"cc-active-task-{key}",
                intent.cache_dir / f"cc-claim-epoch-{key}",
                claim_dispatch_binding_path(intent.cache_dir, key),
            )
        )
    return tuple(paths)


def _validate_intent(intent: ClaimPublicationIntent) -> None:
    try:
        checked_binding = ClaimDispatchBinding.create(
            task_id=intent.binding.task_id,
            lane=intent.binding.lane,
            session_id=intent.binding.session_id,
            claim_epoch=intent.binding.claim_epoch,
            dispatch_message_id=intent.binding.dispatch_message_id,
            platform=intent.binding.platform,
            mode=intent.binding.mode,
            profile=intent.binding.profile,
            authority_case=intent.binding.authority_case,
            binding_hash=intent.binding.binding_hash,
            coord_dispatch_idempotency_key=intent.binding.coord_dispatch_idempotency_key,
        )
    except (AttributeError, TaskStoreError) as exc:
        raise ClaimPublicationError(
            "claim_publication_intent_binding_invalid",
            "construct the intent from one valid dispatch binding",
            intent.task_id,
        ) from exc
    if (
        checked_binding != intent.binding
        or intent.task_id != intent.binding.task_id
        or intent.role != intent.binding.lane
        or intent.session_id != intent.binding.session_id
        or intent.claim_epoch != intent.binding.claim_epoch
        or intent.note_path != _normalized(intent.note_path)
        or intent.cache_dir != _normalized(intent.cache_dir)
        or not isinstance(intent.note_mode, int)
        or not 0 <= intent.note_mode <= 0o777
        or not intent.note_before
        or not intent.note_after
        or (
            intent.claim_mode == "claim"
            and (intent.from_status not in TASK_CLAIMABLE_STATUSES or intent.to_status != "claimed")
        )
        or (
            intent.claim_mode == "resume"
            and (
                intent.from_status not in TASK_RESUMABLE_STATUSES
                or intent.to_status != intent.from_status
            )
        )
        or intent.claim_mode not in {"claim", "resume"}
    ):
        raise ClaimPublicationError(
            "claim_publication_intent_identity_mismatch",
            "bind one exact task, lane, session, epoch, note, and dispatch vector",
            intent.task_id,
        )
    _validate_note_after(
        intent.note_after,
        task_id=intent.task_id,
        role=intent.role,
        authority_case=intent.binding.authority_case,
        expected_status=intent.to_status,
        require_claimed_at=intent.claim_mode == "claim",
    )


def _projections(intent: ClaimPublicationIntent) -> tuple[FileProjection, ...]:
    _validate_intent(intent)
    claim = f"{intent.task_id}\n".encode()
    epoch = f"{intent.claim_epoch} {intent.task_id}\n".encode()
    binding = _binding_bytes(intent.binding)
    projections = [
        FileProjection.from_snapshot(
            intent.note_path,
            before=intent.note_before,
            before_mode=intent.note_mode,
            after=intent.note_after,
            after_mode=intent.note_mode,
        )
    ]
    for key in (intent.role, f"{intent.role}-{intent.session_id}"):
        projections.extend(
            (
                FileProjection.from_snapshot(
                    intent.cache_dir / f"cc-active-task-{key}",
                    before=None,
                    before_mode=None,
                    after=claim,
                    after_mode=0o644,
                ),
                FileProjection.from_snapshot(
                    intent.cache_dir / f"cc-claim-epoch-{key}",
                    before=None,
                    before_mode=None,
                    after=epoch,
                    after_mode=0o644,
                ),
                FileProjection.from_snapshot(
                    claim_dispatch_binding_path(intent.cache_dir, key),
                    before=None,
                    before_mode=None,
                    after=binding,
                    after_mode=0o600,
                ),
            )
        )
    return tuple(projections)


def _admitted_projections(
    intent: ClaimPublicationIntent, consumption: ClaimAdmissionConsumptionRecord
) -> tuple[FileProjection, ...]:
    return (*_projections(intent), *consumption.proof_projections())


def _projection_vector(projections: Sequence[FileProjection]) -> str:
    return _sha256(
        b"hapax.claim-publication-projection-vector.v1\0"
        + _canonical([item.to_record() for item in projections])
    )


def claim_publication_id(intent: ClaimPublicationIntent) -> str:
    body = {
        "intent": intent.to_record(),
        "projections": [item.to_record() for item in _projections(intent)],
        "schema": CLAIM_PUBLICATION_SCHEMA,
    }
    digest = _sha256(b"hapax.claim-publication.v1\0" + _canonical(body))
    return f"claim-pub-{digest}"


def admitted_claim_publication_id(
    intent: ClaimPublicationIntent, consumption: ClaimAdmissionConsumptionRecord
) -> str:
    body = {
        "admission_consumption": consumption.to_record(),
        "intent": intent.to_record(),
        "projections": [item.to_record() for item in _admitted_projections(intent, consumption)],
        "schema": (
            HISTORICAL_ADMITTED_CLAIM_PUBLICATION_SCHEMA
            if isinstance(consumption, HistoricalClaimAdmissionConsumptionV1)
            else ADMITTED_CLAIM_PUBLICATION_SCHEMA
        ),
    }
    domain = (
        b"hapax.claim-publication.v2\0"
        if isinstance(consumption, HistoricalClaimAdmissionConsumptionV1)
        else b"hapax.claim-publication.v3\0"
    )
    digest = _sha256(domain + _canonical(body))
    return f"claim-pub-{digest}"


def _manifest_root(path: Path | None, cache_dir: Path | None = None) -> Path:
    cache = _normalized(cache_dir or (Path.home() / ".cache" / "hapax"))
    return _normalized(path or (cache / "claim-publications"))


def _lock_root(path: Path | None) -> Path:
    return _normalized(path or (Path.home() / ".cache" / "hapax" / "task-locks"))


def _receipt_root(cache_dir: Path, path: Path | None) -> Path:
    return _normalized(path or (_normalized(cache_dir) / "claim-publication-receipts"))


def claim_publication_receipt_path(
    cache_dir: Path,
    binding: ClaimDispatchBinding,
    *,
    receipt_root: Path | None = None,
) -> Path:
    """Return the deterministic applied-receipt locator rooted only in D."""

    digest = binding.receipt_hash
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ClaimPublicationError(
            "claim_publication_binding_receipt_hash_invalid",
            "restore one exact self-hashed dispatch binding",
            digest,
        )
    return _receipt_root(cache_dir, receipt_root) / f"{digest}.json"


def _static_manifest(
    intent: ClaimPublicationIntent,
    projections: Sequence[FileProjection],
    publication_id: str,
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for index, projection in enumerate(projections):
        record: dict[str, object] = dict(projection.to_record())
        record["before_blob"] = f"{index:04d}.before" if projection.before is not None else None
        record["after_blob"] = f"{index:04d}.after" if projection.after is not None else None
        records.append(record)
    return {
        "intent": intent.to_record(),
        "publication_id": publication_id,
        "projections": records,
        "schema": CLAIM_PUBLICATION_SCHEMA,
    }


def _manifest_static_sha256(
    intent: ClaimPublicationIntent,
    projections: Sequence[FileProjection],
    publication_id: str,
) -> str:
    return _sha256(
        b"hapax.claim-publication-manifest-static.v1\0"
        + _canonical(_static_manifest(intent, projections, publication_id))
    )


def _admitted_static_manifest(
    intent: ClaimPublicationIntent,
    consumption: ClaimAdmissionConsumptionRecord,
    projections: Sequence[FileProjection],
    publication_id: str,
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for index, projection in enumerate(projections):
        record: dict[str, object] = dict(projection.to_record())
        record["before_blob"] = f"{index:04d}.before" if projection.before is not None else None
        record["after_blob"] = f"{index:04d}.after" if projection.after is not None else None
        records.append(record)
    return {
        "admission_consumption": consumption.to_record(),
        "intent": intent.to_record(),
        "publication_id": publication_id,
        "projections": records,
        "schema": (
            HISTORICAL_ADMITTED_CLAIM_PUBLICATION_SCHEMA
            if isinstance(consumption, HistoricalClaimAdmissionConsumptionV1)
            else ADMITTED_CLAIM_PUBLICATION_SCHEMA
        ),
    }


def _admitted_manifest_static_sha256(
    intent: ClaimPublicationIntent,
    consumption: ClaimAdmissionConsumptionRecord,
    projections: Sequence[FileProjection],
    publication_id: str,
) -> str:
    domain = (
        b"hapax.claim-publication-manifest-static.v2\0"
        if isinstance(consumption, HistoricalClaimAdmissionConsumptionV1)
        else b"hapax.claim-publication-manifest-static.v3\0"
    )
    return _sha256(
        domain
        + _canonical(_admitted_static_manifest(intent, consumption, projections, publication_id))
    )


def _binding_from_record(value: object) -> ClaimDispatchBinding:
    exact = {
        "authority_case",
        "binding_hash",
        "claim_epoch",
        "coord_dispatch_idempotency_key",
        "dispatch_message_id",
        "lane",
        "may_authorize",
        "mode",
        "platform",
        "profile",
        "receipt_hash",
        "schema",
        "session_id",
        "task_id",
    }
    if (
        not isinstance(value, dict)
        or set(value) != exact
        or value.get("may_authorize") is not False
    ):
        raise ClaimPublicationError(
            "claim_publication_binding_malformed",
            "restore the exact dispatch binding in the publication intent",
        )
    try:
        binding = ClaimDispatchBinding.create(
            task_id=str(value["task_id"]),
            lane=str(value["lane"]),
            session_id=str(value["session_id"]),
            claim_epoch=value["claim_epoch"],
            dispatch_message_id=str(value["dispatch_message_id"]),
            platform=str(value["platform"]),
            mode=str(value["mode"]),
            profile=str(value["profile"]),
            authority_case=str(value["authority_case"]),
            binding_hash=str(value["binding_hash"]),
            coord_dispatch_idempotency_key=value["coord_dispatch_idempotency_key"],
        )
    except (KeyError, TypeError, TaskStoreError) as exc:
        raise ClaimPublicationError(
            "claim_publication_binding_malformed",
            "restore the exact dispatch binding in the publication intent",
        ) from exc
    if value.get("receipt_hash") != binding.receipt_hash or value != binding.to_record():
        raise ClaimPublicationError(
            "claim_publication_binding_hash_mismatch",
            "restore the exact self-hashed dispatch binding",
        )
    return binding


def _load_manifest_record(
    path: Path,
    *,
    admitted: bool,
    manifest_content: bytes | None = None,
    captured_blobs: Mapping[str, tuple[bytes, int]] | None = None,
) -> tuple[
    ClaimPublicationIntent,
    tuple[FileProjection, ...],
    str,
    str,
    ClaimAdmissionConsumptionRecord | None,
]:
    record, _ = _strict_json(path, content=manifest_content)
    manifest_keys = {
        "intent",
        "projections",
        "publication_id",
        "reason_code",
        "schema",
        "state",
    }
    expected_schema = CLAIM_PUBLICATION_SCHEMA
    projection_count = 7
    if admitted:
        manifest_keys.add("admission_consumption")
        if record.get("schema") == HISTORICAL_ADMITTED_CLAIM_PUBLICATION_SCHEMA:
            expected_schema = HISTORICAL_ADMITTED_CLAIM_PUBLICATION_SCHEMA
            projection_count = 10
        else:
            expected_schema = ADMITTED_CLAIM_PUBLICATION_SCHEMA
            projection_count = 12
    if set(record) != manifest_keys or record.get("schema") != expected_schema:
        raise ClaimPublicationError(
            "claim_publication_manifest_schema_unknown",
            "restore the exact claim publication manifest schema",
            str(path),
        )
    state = record.get("state")
    publication_id = record.get("publication_id")
    intent_record = record.get("intent")
    projection_records = record.get("projections")
    intent_keys = {
        "binding",
        "cache_dir",
        "claim_epoch",
        "claim_mode",
        "from_status",
        "note_after_sha256",
        "note_before_sha256",
        "note_mode",
        "note_path",
        "role",
        "session_id",
        "task_id",
        "to_status",
    }
    if (
        state not in _STATES
        or not isinstance(publication_id, str)
        or path.parent.name != publication_id
        or not isinstance(intent_record, dict)
        or set(intent_record) != intent_keys
        or not isinstance(projection_records, list)
        or len(projection_records) != projection_count
    ):
        raise ClaimPublicationError(
            "claim_publication_manifest_shape_malformed",
            f"restore the exact intent and {projection_count} projection records",
            str(path),
        )
    binding = _binding_from_record(intent_record["binding"])
    directory = path.parent
    used_blob_names: set[str] = set()

    def blob(index: int, label: str, item: Mapping[str, object]) -> bytes | None:
        name = item.get(f"{label}_blob")
        present = item.get(f"{label}_present")
        digest = item.get(f"{label}_sha256")
        if name is None:
            if present is not False or digest is not None:
                raise ClaimPublicationError(
                    "claim_publication_projection_malformed",
                    "bind absent bytes without a blob or digest",
                    f"{index}:{label}",
                )
            return None
        if name != f"{index:04d}.{label}" or present is not True:
            raise ClaimPublicationError(
                "claim_publication_blob_name_unsafe",
                "use only the deterministic local journal blob name",
                str(name),
            )
        blob_name = str(name)
        candidate = directory / blob_name
        used_blob_names.add(blob_name)
        if captured_blobs is None:
            content, mode = _strict_file(candidate, reason_code="claim_publication_blob_missing")
        else:
            captured = captured_blobs.get(blob_name)
            if captured is None:
                raise ClaimPublicationError(
                    "claim_publication_blob_missing",
                    "restore the exact manifest-declared private journal blob",
                    str(candidate),
                )
            content, mode = captured
        if mode != 0o600:
            raise ClaimPublicationError(
                "claim_publication_blob_mode_mismatch",
                "restore the private journal blob mode to 0600",
                str(candidate),
            )
        if _sha256(content) != digest:
            raise ClaimPublicationError(
                "claim_publication_blob_hash_mismatch",
                "restore the exact content-addressed journal blob",
                str(candidate),
            )
        return content

    projection_keys = {
        "after_blob",
        "after_mode",
        "after_present",
        "after_sha256",
        "before_blob",
        "before_mode",
        "before_present",
        "before_sha256",
        "path",
    }
    projections: list[FileProjection] = []
    for index, item in enumerate(projection_records):
        if not isinstance(item, dict) or set(item) != projection_keys:
            raise ClaimPublicationError(
                "claim_publication_projection_malformed",
                "restore every exact projection record",
                str(index),
            )
        raw_path = item.get("path")
        if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
            raise ClaimPublicationError(
                "claim_publication_projection_path_invalid",
                "bind every projection to one normalized absolute path",
                str(raw_path),
            )
        try:
            projection = FileProjection(
                path=Path(raw_path),
                before=blob(index, "before", item),
                after=blob(index, "after", item),
                before_mode=item.get("before_mode"),
                after_mode=item.get("after_mode"),
            )
        except LifecycleTransitionError as exc:
            raise ClaimPublicationError(
                "claim_publication_projection_malformed",
                "restore every exact projection record",
                str(index),
            ) from exc
        if str(projection.path) != raw_path:
            raise ClaimPublicationError(
                "claim_publication_projection_path_invalid",
                "bind every projection to one normalized absolute path",
                raw_path,
            )
        projections.append(projection)

    if captured_blobs is not None and set(captured_blobs) != used_blob_names:
        unknown = sorted(set(captured_blobs) - used_blob_names)
        raise ClaimPublicationError(
            "claim_publication_blob_set_mismatch",
            "remove undeclared blobs and restore every manifest-declared blob",
            f"{directory}:{','.join(unknown)}",
        )

    note_before = projections[0].before
    note_after = projections[0].after
    if note_before is None or note_after is None:
        raise ClaimPublicationError(
            "claim_publication_note_projection_missing",
            "restore the exact note preimage and postimage blobs",
            publication_id,
        )
    try:
        intent = ClaimPublicationIntent(
            task_id=str(intent_record["task_id"]),
            role=str(intent_record["role"]),
            session_id=str(intent_record["session_id"]),
            claim_epoch=intent_record["claim_epoch"],
            claim_mode=str(intent_record["claim_mode"]),
            from_status=str(intent_record["from_status"]),
            to_status=str(intent_record["to_status"]),
            cache_dir=_normalized(Path(str(intent_record["cache_dir"]))),
            note_path=_normalized(Path(str(intent_record["note_path"]))),
            note_before=note_before,
            note_after=note_after,
            note_mode=intent_record["note_mode"],
            binding=binding,
        )
    except (TypeError, ValueError) as exc:
        raise ClaimPublicationError(
            "claim_publication_intent_malformed",
            "restore the exact typed claim publication intent",
            publication_id,
        ) from exc
    consumption: ClaimAdmissionConsumptionRecord | None = None
    if admitted:
        consumption = _claim_admission_consumption_from_record(
            intent,
            record.get("admission_consumption"),
            projections[7:],
        )
        expected_projections = _admitted_projections(intent, consumption)
        expected_publication_id = admitted_claim_publication_id(intent, consumption)
    else:
        expected_projections = _projections(intent)
        expected_publication_id = claim_publication_id(intent)
    if (
        intent.to_record() != intent_record
        or tuple(projections) != expected_projections
        or expected_publication_id != publication_id
    ):
        raise ClaimPublicationError(
            "claim_publication_manifest_identity_mismatch",
            "restore the manifest bound to its exact intent and projections",
            publication_id,
        )
    return intent, tuple(projections), publication_id, str(state), consumption


def _load_manifest(
    path: Path,
    *,
    manifest_content: bytes | None = None,
    captured_blobs: Mapping[str, tuple[bytes, int]] | None = None,
) -> tuple[ClaimPublicationIntent, tuple[FileProjection, ...], str, str]:
    intent, projections, publication_id, state, consumption = _load_manifest_record(
        path,
        admitted=False,
        manifest_content=manifest_content,
        captured_blobs=captured_blobs,
    )
    assert consumption is None
    return intent, projections, publication_id, state


def _load_admitted_manifest(
    path: Path,
    *,
    manifest_content: bytes | None = None,
    captured_blobs: Mapping[str, tuple[bytes, int]] | None = None,
) -> tuple[
    ClaimPublicationIntent,
    tuple[FileProjection, ...],
    str,
    str,
    ClaimAdmissionConsumptionRecord,
]:
    intent, projections, publication_id, state, consumption = _load_manifest_record(
        path,
        admitted=True,
        manifest_content=manifest_content,
        captured_blobs=captured_blobs,
    )
    assert consumption is not None
    return intent, projections, publication_id, state, consumption


def _load_any_manifest(
    path: Path,
    *,
    manifest_content: bytes | None = None,
    captured_blobs: Mapping[str, tuple[bytes, int]] | None = None,
) -> tuple[
    ClaimPublicationIntent,
    tuple[FileProjection, ...],
    str,
    str,
    ClaimAdmissionConsumptionRecord | None,
]:
    record, _ = _strict_json(path, content=manifest_content)
    schema = record.get("schema")
    if schema == CLAIM_PUBLICATION_SCHEMA:
        return _load_manifest_record(
            path,
            admitted=False,
            manifest_content=manifest_content,
            captured_blobs=captured_blobs,
        )
    if schema in {
        HISTORICAL_ADMITTED_CLAIM_PUBLICATION_SCHEMA,
        ADMITTED_CLAIM_PUBLICATION_SCHEMA,
    }:
        return _load_manifest_record(
            path,
            admitted=True,
            manifest_content=manifest_content,
            captured_blobs=captured_blobs,
        )
    raise ClaimPublicationError(
        "claim_publication_manifest_schema_unknown",
        "restore exact transaction-v1 or admitted transaction-v2/v3 bytes",
        str(path),
    )


def _receipt_body(
    intent: ClaimPublicationIntent,
    projections: Sequence[FileProjection],
    publication_id: str,
) -> dict[str, object]:
    return {
        "authority_case": intent.binding.authority_case,
        "binding_receipt_hash": intent.binding.receipt_hash,
        "claim_epoch": intent.claim_epoch,
        "claim_mode": intent.claim_mode,
        "claim_note_path": str(intent.note_path),
        "claim_note_postimage_sha256": _sha256(intent.note_after),
        "from_status": intent.from_status,
        "intent_sha256": intent.intent_sha256,
        "manifest_static_sha256": _manifest_static_sha256(intent, projections, publication_id),
        "may_authorize": False,
        "projection_vector_sha256": _projection_vector(projections),
        "publication_id": publication_id,
        "role": intent.role,
        "schema": CLAIM_PUBLICATION_RECEIPT_SCHEMA,
        "session_id": intent.session_id,
        "task_id": intent.task_id,
        "to_status": intent.to_status,
    }


def _receipt_record(
    intent: ClaimPublicationIntent,
    projections: Sequence[FileProjection],
    publication_id: str,
) -> dict[str, object]:
    body = _receipt_body(intent, projections, publication_id)
    return {**body, "receipt_hash": _sha256(_canonical(body))}


def _admitted_receipt_body(
    intent: ClaimPublicationIntent,
    consumption: ClaimAdmissionConsumptionRecord,
    projections: Sequence[FileProjection],
    publication_id: str,
) -> dict[str, object]:
    body: dict[str, object] = {
        "admission_consumption_hash": consumption.consumption_hash,
        "admission_consumption_ref": consumption.consumption_ref,
        "admission_valid_until": consumption.valid_until,
        "authenticated_authority_receipt_hash": (
            consumption.authenticated_authority_receipt.sha256
        ),
        "authenticated_authority_receipt_ref": consumption.authenticated_authority_receipt.ref,
        "authority_case": intent.binding.authority_case,
        "authority_evidence_hash": consumption.authority_evidence.sha256,
        "authority_evidence_ref": consumption.authority_evidence.ref,
        "binding_receipt_hash": intent.binding.receipt_hash,
        "claim_epoch": intent.claim_epoch,
        "claim_mode": intent.claim_mode,
        "claim_note_path": str(intent.note_path),
        "claim_note_postimage_sha256": _sha256(intent.note_after),
        "claim_publication_intent_ref": consumption.claim_publication_intent.ref,
        "context_position_hash": consumption.context_position.sha256,
        "context_position_ref": consumption.context_position.ref,
        "execution_admission_hash": consumption.execution_admission.sha256,
        "execution_admission_ref": consumption.execution_admission.ref,
        "from_status": intent.from_status,
        "intent_sha256": intent.intent_sha256,
        "manifest_static_sha256": _admitted_manifest_static_sha256(
            intent, consumption, projections, publication_id
        ),
        "may_authorize": False,
        "projection_vector_sha256": _projection_vector(projections),
        "publication_id": publication_id,
        "role": intent.role,
        "schema": (
            HISTORICAL_ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
            if isinstance(consumption, HistoricalClaimAdmissionConsumptionV1)
            else ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
        ),
        "session_id": intent.session_id,
        "supersession_frontier_ref": consumption.supersession_frontier_ref,
        "task_id": intent.task_id,
        "to_status": intent.to_status,
        "valid_authority_grant_hash": consumption.valid_authority_grant.sha256,
        "valid_authority_grant_ref": consumption.valid_authority_grant.ref,
    }
    if isinstance(consumption, ClaimAdmissionConsumption):
        body.update(
            {
                "action_intent_hash": consumption.action_intent.sha256,
                "action_intent_ref": consumption.action_intent.ref,
                "attempt_fence": consumption.attempt_fence,
                "bound_execution_call_hash": consumption.bound_execution_call.sha256,
                "bound_execution_call_ref": consumption.bound_execution_call.ref,
                "effect_manifest_hash": consumption.effect_manifest.sha256,
                "effect_manifest_ref": consumption.effect_manifest.ref,
                "execution_lease_hash": consumption.execution_lease.sha256,
                "execution_lease_ref": consumption.execution_lease.ref,
                "executor_descriptor_hash": consumption.executor_descriptor.sha256,
                "executor_descriptor_ref": consumption.executor_descriptor.ref,
                "executor_registry_projection_hash": (
                    consumption.executor_registry_projection.sha256
                ),
                "executor_registry_projection_ref": (consumption.executor_registry_projection.ref),
                "invocation_id": consumption.invocation_id,
                "prospective_claim_basis_hash": consumption.prospective_claim_basis.sha256,
                "prospective_claim_basis_ref": consumption.prospective_claim_basis.ref,
            }
        )
    return body


def _admitted_receipt_record(
    intent: ClaimPublicationIntent,
    consumption: ClaimAdmissionConsumptionRecord,
    projections: Sequence[FileProjection],
    publication_id: str,
) -> dict[str, object]:
    body = _admitted_receipt_body(intent, consumption, projections, publication_id)
    return {**body, "receipt_hash": _sha256(_canonical(body))}


def load_claim_publication_receipt(
    path: Path,
    *,
    content: bytes | None = None,
) -> dict[str, object]:
    """Load one exact v2 receipt from its dispatch-binding-derived locator."""

    payload = (
        content
        if content is not None
        else _strict_file(path, reason_code="claim_publication_receipt_unreadable")[0]
    )
    try:
        record = json.loads(payload.decode("ascii"), object_pairs_hook=_unique_pairs)
    except ClaimPublicationError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ClaimPublicationError(
            "claim_publication_receipt_unreadable",
            "restore the exact canonical applied receipt",
            str(path),
        ) from exc
    if not isinstance(record, dict) or payload != _canonical(record) + b"\n":
        raise ClaimPublicationError(
            "claim_publication_receipt_noncanonical",
            "restore the exact canonical ASCII applied receipt",
            str(path),
        )
    exact_keys = {
        "authority_case",
        "binding_receipt_hash",
        "claim_epoch",
        "claim_mode",
        "claim_note_path",
        "claim_note_postimage_sha256",
        "from_status",
        "intent_sha256",
        "manifest_static_sha256",
        "may_authorize",
        "projection_vector_sha256",
        "publication_id",
        "receipt_hash",
        "role",
        "schema",
        "session_id",
        "task_id",
        "to_status",
    }
    string_fields = exact_keys - {"claim_epoch", "may_authorize"}
    hash_fields = {
        "binding_receipt_hash",
        "claim_note_postimage_sha256",
        "intent_sha256",
        "manifest_static_sha256",
        "projection_vector_sha256",
        "receipt_hash",
    }

    def is_hash(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    publication_id = record.get("publication_id")
    publication_digest = (
        publication_id.removeprefix("claim-pub-") if isinstance(publication_id, str) else None
    )
    if (
        set(record) != exact_keys
        or record.get("schema") != CLAIM_PUBLICATION_RECEIPT_SCHEMA
        or record.get("may_authorize") is not False
        or type(record.get("claim_epoch")) is not int
        or record.get("claim_epoch", 0) <= 0
        or any(not isinstance(record.get(key), str) or not record.get(key) for key in string_fields)
        or any(not is_hash(record.get(key)) for key in hash_fields)
        or not isinstance(publication_id, str)
        or not publication_id.startswith("claim-pub-")
        or not is_hash(publication_digest)
        or record.get("claim_mode") not in {"claim", "resume"}
        or (record.get("claim_mode") == "claim" and record.get("to_status") != "claimed")
        or (
            record.get("claim_mode") == "resume"
            and record.get("to_status") != record.get("from_status")
        )
        or not Path(str(record.get("claim_note_path"))).is_absolute()
        or str(_normalized(Path(str(record.get("claim_note_path")))))
        != record.get("claim_note_path")
        or path.name != f"{record.get('binding_receipt_hash')}.json"
    ):
        raise ClaimPublicationError(
            "claim_publication_receipt_malformed",
            "restore the exact v2 applied-publication receipt shape and locator",
            str(path),
        )
    body = dict(record)
    receipt_hash = body.pop("receipt_hash")
    if receipt_hash != _sha256(_canonical(body)):
        raise ClaimPublicationError(
            "claim_publication_receipt_hash_mismatch",
            "restore the exact self-hashed applied receipt",
            str(path),
        )
    return record


def load_admitted_claim_publication_receipt(
    path: Path,
    *,
    content: bytes | None = None,
) -> dict[str, object]:
    """Load one exact admitted v3/v4 receipt by schema without upgrading."""

    payload = (
        content
        if content is not None
        else _strict_file(path, reason_code="claim_publication_receipt_unreadable")[0]
    )
    try:
        record = json.loads(payload.decode("ascii"), object_pairs_hook=_unique_pairs)
    except ClaimPublicationError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ClaimPublicationError(
            "claim_publication_receipt_unreadable",
            "restore the exact canonical admitted receipt",
            str(path),
        ) from exc
    if not isinstance(record, dict) or payload != _canonical(record) + b"\n":
        raise ClaimPublicationError(
            "claim_publication_receipt_noncanonical",
            "restore the exact canonical ASCII admitted receipt",
            str(path),
        )
    historical_keys = {
        "admission_consumption_hash",
        "admission_consumption_ref",
        "admission_valid_until",
        "authenticated_authority_receipt_hash",
        "authenticated_authority_receipt_ref",
        "authority_case",
        "authority_evidence_hash",
        "authority_evidence_ref",
        "binding_receipt_hash",
        "claim_epoch",
        "claim_mode",
        "claim_note_path",
        "claim_note_postimage_sha256",
        "claim_publication_intent_ref",
        "context_position_hash",
        "context_position_ref",
        "execution_admission_hash",
        "execution_admission_ref",
        "from_status",
        "intent_sha256",
        "manifest_static_sha256",
        "may_authorize",
        "projection_vector_sha256",
        "publication_id",
        "receipt_hash",
        "role",
        "schema",
        "session_id",
        "supersession_frontier_ref",
        "task_id",
        "to_status",
        "valid_authority_grant_hash",
        "valid_authority_grant_ref",
    }
    active_extra_keys = {
        "action_intent_hash",
        "action_intent_ref",
        "attempt_fence",
        "bound_execution_call_hash",
        "bound_execution_call_ref",
        "effect_manifest_hash",
        "effect_manifest_ref",
        "execution_lease_hash",
        "execution_lease_ref",
        "executor_descriptor_hash",
        "executor_descriptor_ref",
        "executor_registry_projection_hash",
        "executor_registry_projection_ref",
        "invocation_id",
        "prospective_claim_basis_hash",
        "prospective_claim_basis_ref",
    }
    schema = record.get("schema")
    exact_keys = (
        historical_keys
        if schema == HISTORICAL_ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
        else historical_keys | active_extra_keys
    )
    hash_fields = {
        "admission_consumption_hash",
        "authenticated_authority_receipt_hash",
        "authority_evidence_hash",
        "binding_receipt_hash",
        "claim_note_postimage_sha256",
        "context_position_hash",
        "execution_admission_hash",
        "intent_sha256",
        "manifest_static_sha256",
        "projection_vector_sha256",
        "receipt_hash",
        "valid_authority_grant_hash",
    }
    if schema == ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA:
        hash_fields.update(
            {
                "action_intent_hash",
                "bound_execution_call_hash",
                "effect_manifest_hash",
                "execution_lease_hash",
                "executor_descriptor_hash",
                "executor_registry_projection_hash",
                "prospective_claim_basis_hash",
            }
        )

    def is_hash(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    publication_id = record.get("publication_id")
    publication_digest = (
        publication_id.removeprefix("claim-pub-") if isinstance(publication_id, str) else None
    )
    string_fields = exact_keys - {"claim_epoch", "may_authorize"}
    address_pairs = (
        ("admission_consumption_ref", "admission_consumption_hash"),
        ("authenticated_authority_receipt_ref", "authenticated_authority_receipt_hash"),
        ("authority_evidence_ref", "authority_evidence_hash"),
        ("context_position_ref", "context_position_hash"),
        ("execution_admission_ref", "execution_admission_hash"),
        ("valid_authority_grant_ref", "valid_authority_grant_hash"),
        *(
            (
                ("action_intent_ref", "action_intent_hash"),
                ("bound_execution_call_ref", "bound_execution_call_hash"),
                ("effect_manifest_ref", "effect_manifest_hash"),
                ("execution_lease_ref", "execution_lease_hash"),
                ("executor_descriptor_ref", "executor_descriptor_hash"),
                (
                    "executor_registry_projection_ref",
                    "executor_registry_projection_hash",
                ),
                ("prospective_claim_basis_ref", "prospective_claim_basis_hash"),
            )
            if schema == ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
            else ()
        ),
    )
    if (
        set(record) != exact_keys
        or schema
        not in {
            HISTORICAL_ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA,
            ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA,
        }
        or record.get("may_authorize") is not False
        or type(record.get("claim_epoch")) is not int
        or record.get("claim_epoch", 0) <= 0
        or any(not isinstance(record.get(key), str) or not record.get(key) for key in string_fields)
        or any(not is_hash(record.get(key)) for key in hash_fields)
        or not isinstance(publication_id, str)
        or not publication_id.startswith("claim-pub-")
        or not is_hash(publication_digest)
        or record.get("claim_mode") not in {"claim", "resume"}
        or (record.get("claim_mode") == "claim" and record.get("to_status") != "claimed")
        or (
            record.get("claim_mode") == "resume"
            and record.get("to_status") != record.get("from_status")
        )
        or not Path(str(record.get("claim_note_path"))).is_absolute()
        or str(_normalized(Path(str(record.get("claim_note_path")))))
        != record.get("claim_note_path")
        or path.name != f"{record.get('binding_receipt_hash')}.json"
        or record.get("claim_publication_intent_ref")
        != f"claim-publication-intent@sha256:{record.get('intent_sha256')}"
        or any(
            not str(record.get(ref_field)).endswith(f"@sha256:{record.get(hash_field)}")
            for ref_field, hash_field in address_pairs
        )
    ):
        raise ClaimPublicationError(
            "claim_publication_receipt_malformed",
            "restore the exact schema-dispatched admitted-publication receipt",
            str(path),
        )
    try:
        canonical_valid_until = _canonical_timestamp(str(record["admission_valid_until"]))
    except ClaimPublicationError as exc:
        raise ClaimPublicationError(
            "claim_publication_receipt_malformed",
            "restore the canonical admitted validity horizon",
            str(path),
        ) from exc
    if canonical_valid_until != record["admission_valid_until"]:
        raise ClaimPublicationError(
            "claim_publication_receipt_malformed",
            "restore the canonical admitted validity horizon",
            str(path),
        )
    body = dict(record)
    receipt_hash = body.pop("receipt_hash")
    if receipt_hash != _sha256(_canonical(body)):
        raise ClaimPublicationError(
            "claim_publication_receipt_hash_mismatch",
            "restore the exact self-hashed admitted receipt",
            str(path),
        )
    return record


def _load_any_claim_publication_receipt(
    path: Path,
    *,
    content: bytes | None = None,
) -> dict[str, object]:
    payload = (
        content
        if content is not None
        else _strict_file(path, reason_code="claim_publication_receipt_unreadable")[0]
    )
    try:
        candidate = json.loads(payload.decode("ascii"), object_pairs_hook=_unique_pairs)
    except ClaimPublicationError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ClaimPublicationError(
            "claim_publication_receipt_unreadable",
            "restore one canonical applied receipt",
            str(path),
        ) from exc
    schema = candidate.get("schema") if isinstance(candidate, dict) else None
    if schema == CLAIM_PUBLICATION_RECEIPT_SCHEMA:
        return load_claim_publication_receipt(path, content=payload)
    if schema in {
        HISTORICAL_ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA,
        ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA,
    }:
        return load_admitted_claim_publication_receipt(path, content=payload)
    raise ClaimPublicationError(
        "claim_publication_receipt_schema_unknown",
        "restore exact legacy-v2, admitted-v3, or admitted-v4 receipt bytes",
        str(path),
    )


def _locked_preflight(
    intent: ClaimPublicationIntent, projections: Sequence[FileProjection]
) -> None:
    try:
        task = resolve_task_note(
            intent.note_path.parent.parent,
            intent.task_id,
            state="active",
            require_no_other_state=True,
        )
    except TaskStoreError as exc:
        raise ClaimPublicationError(
            "claim_publication_task_resolution_refused",
            "restore exactly one active task note and no closed duplicate",
            exc.reason_code,
        ) from exc
    if (
        task.path != intent.note_path
        or task.content != intent.note_before
        or task.mode != intent.note_mode
    ):
        raise ClaimPublicationError(
            "claim_publication_task_preimage_changed",
            "resolve the current active task note and construct a fresh claim intent",
            intent.task_id,
        )
    try:
        _assert_preimages(projections)
    except LifecycleTransitionError as exc:
        raise ClaimPublicationError(
            "claim_publication_preimage_changed",
            "preserve the current claim files and construct a fresh claim intent",
            exc.detail,
        ) from exc


def _require_exact_task_postimage(intent: ClaimPublicationIntent) -> None:
    try:
        task = resolve_task_note(
            intent.note_path.parent.parent,
            intent.task_id,
            state="active",
            require_no_other_state=True,
        )
    except TaskStoreError as exc:
        raise ClaimPublicationError(
            "claim_publication_task_projection_invalid",
            "hold the claim until exactly one active receipt-bound task note remains",
            exc.reason_code,
        ) from exc
    if (
        task.path != intent.note_path
        or task.content != intent.note_after
        or task.mode != intent.note_mode
    ):
        raise ClaimPublicationError(
            "claim_publication_task_projection_invalid",
            "restore the exact receipt-bound active task-note postimage",
            intent.task_id,
        )


def _as_receipt(
    manifest_path: Path,
    receipt_path: Path,
    intent: ClaimPublicationIntent,
    projections: Sequence[FileProjection],
    publication_id: str,
    *,
    recovered: bool,
    receipt_content: bytes | None = None,
    receipt_mode: int | None = None,
) -> ClaimPublicationReceipt:
    if receipt_content is None or receipt_mode is None:
        if receipt_content is not None or receipt_mode is not None:
            raise ClaimPublicationError(
                "claim_publication_receipt_capture_incomplete",
                "provide both captured receipt bytes and mode or neither",
                str(receipt_path),
            )
        receipt_content, receipt_mode = _strict_file(
            receipt_path, reason_code="claim_publication_receipt_unreadable"
        )
    if receipt_mode != 0o600:
        raise ClaimPublicationError(
            "claim_publication_receipt_mode_mismatch",
            "restore the immutable applied receipt mode to 0600",
            str(receipt_path),
        )
    record = load_claim_publication_receipt(receipt_path, content=receipt_content)
    expected = _receipt_record(intent, projections, publication_id)
    if record != expected:
        raise ClaimPublicationError(
            "claim_publication_receipt_mismatch",
            "restore the exact self-hashed applied receipt",
            publication_id,
        )
    body = dict(record)
    receipt_hash = body.pop("receipt_hash", None)
    if receipt_hash != _sha256(_canonical(body)):
        raise ClaimPublicationError(
            "claim_publication_receipt_hash_mismatch",
            "restore the exact self-hashed applied receipt",
            publication_id,
        )
    return ClaimPublicationReceipt(
        publication_id=publication_id,
        binding_receipt_hash=intent.binding.receipt_hash,
        task_id=intent.task_id,
        role=intent.role,
        session_id=intent.session_id,
        claim_epoch=intent.claim_epoch,
        intent_sha256=intent.intent_sha256,
        manifest_static_sha256=_manifest_static_sha256(intent, projections, publication_id),
        projection_vector_sha256=_projection_vector(projections),
        claim_note_postimage_sha256=_sha256(intent.note_after),
        manifest_path=manifest_path,
        receipt_path=receipt_path,
        receipt_hash=str(receipt_hash),
        recovered=recovered,
    )


def _as_admitted_receipt(
    manifest_path: Path,
    receipt_path: Path,
    intent: ClaimPublicationIntent,
    consumption: ClaimAdmissionConsumptionRecord,
    projections: Sequence[FileProjection],
    publication_id: str,
    *,
    recovered: bool,
    receipt_content: bytes | None = None,
    receipt_mode: int | None = None,
) -> ClaimPublicationReceipt:
    if receipt_content is None or receipt_mode is None:
        if receipt_content is not None or receipt_mode is not None:
            raise ClaimPublicationError(
                "claim_publication_receipt_capture_incomplete",
                "provide both captured receipt bytes and mode or neither",
                str(receipt_path),
            )
        receipt_content, receipt_mode = _strict_file(
            receipt_path, reason_code="claim_publication_receipt_unreadable"
        )
    if receipt_mode != 0o600:
        raise ClaimPublicationError(
            "claim_publication_receipt_mode_mismatch",
            "restore the immutable admitted receipt mode to 0600",
            str(receipt_path),
        )
    record = load_admitted_claim_publication_receipt(receipt_path, content=receipt_content)
    expected = _admitted_receipt_record(intent, consumption, projections, publication_id)
    if record != expected:
        raise ClaimPublicationError(
            "claim_publication_receipt_mismatch",
            "restore the exact self-hashed admitted receipt",
            publication_id,
        )
    body = dict(record)
    receipt_hash = body.pop("receipt_hash", None)
    if receipt_hash != _sha256(_canonical(body)):
        raise ClaimPublicationError(
            "claim_publication_receipt_hash_mismatch",
            "restore the exact self-hashed admitted receipt",
            publication_id,
        )
    return ClaimPublicationReceipt(
        publication_id=publication_id,
        binding_receipt_hash=intent.binding.receipt_hash,
        task_id=intent.task_id,
        role=intent.role,
        session_id=intent.session_id,
        claim_epoch=intent.claim_epoch,
        intent_sha256=intent.intent_sha256,
        manifest_static_sha256=_admitted_manifest_static_sha256(
            intent, consumption, projections, publication_id
        ),
        projection_vector_sha256=_projection_vector(projections),
        claim_note_postimage_sha256=_sha256(intent.note_after),
        manifest_path=manifest_path,
        receipt_path=receipt_path,
        receipt_hash=str(receipt_hash),
        recovered=recovered,
        schema=(
            HISTORICAL_ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
            if isinstance(consumption, HistoricalClaimAdmissionConsumptionV1)
            else ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
        ),
        admission_consumption=ContentAddress(
            ref=consumption.consumption_ref, sha256=consumption.consumption_hash
        ),
        execution_admission=consumption.execution_admission,
        valid_authority_grant=consumption.valid_authority_grant,
        authority_evidence=consumption.authority_evidence,
        authenticated_authority_receipt=consumption.authenticated_authority_receipt,
        context_position=consumption.context_position,
        action_intent=(
            consumption.action_intent
            if isinstance(consumption, ClaimAdmissionConsumption)
            else None
        ),
        prospective_claim_basis=(
            consumption.prospective_claim_basis
            if isinstance(consumption, ClaimAdmissionConsumption)
            else None
        ),
        execution_lease=(
            consumption.execution_lease
            if isinstance(consumption, ClaimAdmissionConsumption)
            else None
        ),
        bound_execution_call=(
            consumption.bound_execution_call
            if isinstance(consumption, ClaimAdmissionConsumption)
            else None
        ),
        effect_manifest=(
            consumption.effect_manifest
            if isinstance(consumption, ClaimAdmissionConsumption)
            else None
        ),
        executor_descriptor=(
            consumption.executor_descriptor
            if isinstance(consumption, ClaimAdmissionConsumption)
            else None
        ),
        executor_registry_projection=(
            consumption.executor_registry_projection
            if isinstance(consumption, ClaimAdmissionConsumption)
            else None
        ),
        invocation_id=(
            consumption.invocation_id
            if isinstance(consumption, ClaimAdmissionConsumption)
            else None
        ),
        attempt_fence=(
            consumption.attempt_fence
            if isinstance(consumption, ClaimAdmissionConsumption)
            else None
        ),
        supersession_frontier_ref=consumption.supersession_frontier_ref,
        admission_valid_until=consumption.valid_until,
    )


def _as_any_receipt(
    manifest_path: Path,
    receipt_path: Path,
    intent: ClaimPublicationIntent,
    projections: Sequence[FileProjection],
    publication_id: str,
    consumption: ClaimAdmissionConsumptionRecord | None,
    *,
    recovered: bool,
    receipt_content: bytes | None = None,
    receipt_mode: int | None = None,
) -> ClaimPublicationReceipt:
    if consumption is None:
        return _as_receipt(
            manifest_path,
            receipt_path,
            intent,
            projections,
            publication_id,
            recovered=recovered,
            receipt_content=receipt_content,
            receipt_mode=receipt_mode,
        )
    return _as_admitted_receipt(
        manifest_path,
        receipt_path,
        intent,
        consumption,
        projections,
        publication_id,
        recovered=recovered,
        receipt_content=receipt_content,
        receipt_mode=receipt_mode,
    )


def publish_claim(
    intent: ClaimPublicationIntent,
    *,
    transaction_root: Path | None = None,
    receipt_root: Path | None = None,
    lock_root: Path | None = None,
    failure_hook: Callable[[str, int | None], None] | None = None,
) -> ClaimPublicationReceipt:
    """Refuse new transaction-v1 claims; retained v1 bytes are history only."""

    del transaction_root, receipt_root, lock_root, failure_hook
    raise ClaimPublicationError(
        "unadmitted_claim_publication_forbidden",
        "publish through one current five-proof claim-publication execution lease",
        intent.task_id,
    )


def publish_admitted_claim(
    intent: ClaimPublicationIntent,
    consumption: ClaimAdmissionConsumption,
    *,
    transaction_root: Path | None = None,
    receipt_root: Path | None = None,
    lock_root: Path | None = None,
    now: str | datetime | None = None,
    failure_hook: Callable[[str, int | None], None] | None = None,
) -> ClaimPublicationReceipt:
    """Gate-0A HOLD: publication effects require the universal adapter carrier."""

    del consumption, transaction_root, receipt_root, lock_root, now, failure_hook
    raise ClaimPublicationError(
        "claim_publication_effect_activation_unvalidated",
        "dispatch the publication lease through a Gate-0B activated universal executor",
        intent.task_id,
    )


def _apply_admitted_claim_publication_transaction(
    intent: ClaimPublicationIntent,
    consumption: ClaimAdmissionConsumption,
    *,
    transaction_root: Path | None = None,
    receipt_root: Path | None = None,
    lock_root: Path | None = None,
    now: str | datetime | None = None,
    failure_hook: Callable[[str, int | None], None] | None = None,
) -> ClaimPublicationReceipt:
    """Dormant Gate-0A engine; Gate-0B must supply a typed effect carrier."""

    del consumption, transaction_root, receipt_root, lock_root, now, failure_hook
    raise ClaimPublicationError(
        "claim_publication_effect_activation_unvalidated",
        "bind a validated generation and currentness carrier before restoring mutation",
        intent.task_id,
    )


_CLAIM_SNAPSHOT_MAX_TASK_NOTE_BYTES = 32 * 1024 * 1024
_CLAIM_SNAPSHOT_MAX_SIDECAR_BYTES = 8 * 1024 * 1024
_CLAIM_SNAPSHOT_MAX_JOURNAL_CHILDREN = 32
_CLAIM_SNAPSHOT_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_CLAIM_SNAPSHOT_MAX_BLOB_BYTES = 32 * 1024 * 1024
_CLAIM_SNAPSHOT_MAX_PROJECTION_BYTES = 32 * 1024 * 1024
_CLAIM_SESSION_FRAGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{3,127}")


@dataclass(frozen=True)
class _CapturedPublicationJournalBytes:
    manifest_path: Path
    manifest_content: bytes
    manifest_mode: int
    blobs: Mapping[str, tuple[bytes, int]]


def _raise_snapshot_error(exc: ReadOnlySnapshotError) -> None:
    raise ClaimPublicationError(exc.reason_code, exc.repair_action, exc.detail) from exc


def _task_note_from_capture(
    captured: CapturedFile,
    *,
    expected_task_id: str,
    state: Literal["active", "closed"],
) -> TaskNoteSnapshot:
    try:
        text = captured.content.decode("utf-8")
    except UnicodeError as exc:
        raise ClaimPublicationError(
            "task_note_unreadable",
            "restore the exact UTF-8 task note and retry resolution",
            str(captured.path),
        ) from exc
    parsed = parse_frontmatter_with_diagnostics(text)
    if not parsed.ok or parsed.frontmatter is None:
        raise ClaimPublicationError(
            "task_note_frontmatter_malformed",
            "restore one closed YAML frontmatter mapping",
            f"{captured.path}:{parsed.error_kind or 'unknown'}",
        )
    observed_task_id = str(parsed.frontmatter.get("task_id") or "").strip()
    if observed_task_id != expected_task_id:
        raise ClaimPublicationError(
            "task_note_identity_mismatch",
            "make the filename candidate and frontmatter task_id name the same task",
            f"{captured.path}:{observed_task_id or 'missing'}",
        )
    return TaskNoteSnapshot(
        task_id=expected_task_id,
        state=state,
        path=_normalized(captured.path),
        content=captured.content,
        mode=stat.S_IMODE(captured.stamp.mode),
        frontmatter=dict(parsed.frontmatter),
        body=parsed.body,
    )


def _capture_task_state_candidates(
    snapshot: ReadOnlyFsSnapshot,
    vault_root: Path,
    task_id: str,
    state: Literal["active", "closed"],
    *,
    ignore_identity_mismatch: bool = False,
) -> tuple[TaskNoteSnapshot, ...]:
    directory_path = _normalized(vault_root / state)
    directory = snapshot.pin_absolute_dir(
        directory_path,
        private_final=False,
        allow_missing=True,
    )
    if directory is None:
        return ()
    names = snapshot.list_names(directory)
    exact = f"{task_id}.md"
    prefix = f"{task_id}-"
    candidates = tuple(
        name
        for name in names
        if name == exact or (name.startswith(prefix) and name.endswith(".md"))
    )
    resolved: list[TaskNoteSnapshot] = []
    for name in candidates:
        observed = snapshot.observe_file_at(
            directory,
            name,
            private=False,
            max_bytes=_CLAIM_SNAPSHOT_MAX_TASK_NOTE_BYTES,
        )
        if observed.captured is None:
            raise ClaimPublicationError(
                "task_note_path_unsafe",
                "restore the exact regular task note below real non-symlink directories",
                str(observed.path),
            )
        try:
            resolved.append(
                _task_note_from_capture(
                    observed.captured,
                    expected_task_id=task_id,
                    state=state,
                )
            )
        except ClaimPublicationError as exc:
            if not ignore_identity_mismatch or exc.reason_code != "task_note_identity_mismatch":
                raise
    return tuple(resolved)


def _capture_current_task_note(
    snapshot: ReadOnlyFsSnapshot,
    vault_root: Path,
    task_id: str,
) -> TaskNoteSnapshot:
    normalized = task_id.strip()
    if not normalized or "/" in normalized or normalized in {".", ".."}:
        raise ClaimPublicationError(
            "task_id_invalid",
            "use one non-path task identifier",
            task_id,
        )
    active = _capture_task_state_candidates(snapshot, vault_root, normalized, "active")
    if not active:
        raise ClaimPublicationError(
            "task_note_not_found",
            "restore the active task note before lifecycle mutation",
            normalized,
        )
    if len(active) != 1:
        raise ClaimPublicationError(
            "task_note_identity_ambiguous",
            "retain exactly one task note for this identity in the requested state",
            ",".join(str(item.path) for item in active),
        )
    closed_candidates = _capture_task_state_candidates(
        snapshot,
        vault_root,
        normalized,
        "closed",
        ignore_identity_mismatch=True,
    )
    if closed_candidates:
        raise ClaimPublicationError(
            "task_note_cross_state_duplicate",
            "reconcile the active and closed copies before lifecycle mutation",
            ",".join(str(item.path) for item in closed_candidates),
        )
    return active[0]


def _capture_claim_leases(
    snapshot: ReadOnlyFsSnapshot,
    cache_dir: Path,
    *,
    role: str,
    task_id: str,
    session_id: str | None,
) -> tuple[ClaimLeaseSnapshot, ...]:
    if not role.strip() or role == "unknown":
        raise ClaimPublicationError(
            "claim_identity_missing",
            "bind one real lane identity before lifecycle mutation",
        )
    cache = _normalized(cache_dir)
    try:
        claim_dispatch_binding_path(cache, role)
    except TaskStoreError as exc:
        raise ClaimPublicationError(exc.reason_code, exc.repair_action, exc.detail) from exc
    directory = snapshot.pin_absolute_dir(cache, private_final=False)
    assert directory is not None
    observations: dict[str, CapturedFile | None] = {}

    def captured(name: str, *, reason_code: str) -> CapturedFile:
        if name not in observations:
            observations[name] = snapshot.observe_file_at(
                directory,
                name,
                private=False,
                max_bytes=_CLAIM_SNAPSHOT_MAX_SIDECAR_BYTES,
            ).captured
        value = observations[name]
        if value is None:
            raise ClaimPublicationError(
                reason_code,
                "restore the exact regular claim, epoch, and dispatch-binding sidecars",
                str(cache / name),
            )
        return value

    role_binding_path = claim_dispatch_binding_path(cache, role)
    role_binding_file = captured(
        role_binding_path.name,
        reason_code="claim_dispatch_binding_missing",
    )
    try:
        role_binding = load_claim_dispatch_binding(
            role_binding_path,
            content=role_binding_file.content,
        )
    except TaskStoreError as exc:
        raise ClaimPublicationError(exc.reason_code, exc.repair_action, exc.detail) from exc
    resolved_session = role_binding.session_id if session_id is None else session_id
    if (
        _CLAIM_SESSION_FRAGMENT_RE.fullmatch(resolved_session) is None
        or resolved_session.isdecimal()
        or "/" in resolved_session
    ):
        raise ClaimPublicationError(
            "claim_session_identity_invalid",
            "bind one non-PID claim-keyable harness session before lifecycle mutation",
            resolved_session,
        )
    if session_id is None and (
        role_binding.task_id != task_id
        or role_binding.lane != role
        or not role_binding.session_id.strip()
    ):
        raise ClaimPublicationError(
            "claim_role_binding_mismatch",
            "restore the role binding for this exact task, lane, and claim session",
            role,
        )

    leases: list[ClaimLeaseSnapshot] = []
    for key in (role, f"{role}-{resolved_session}"):
        claim_path = cache / f"cc-active-task-{key}"
        epoch_path = cache / f"cc-claim-epoch-{key}"
        binding_path = claim_dispatch_binding_path(cache, key)
        claim_file = captured(claim_path.name, reason_code="claim_cache_missing")
        epoch_file = captured(epoch_path.name, reason_code="claim_epoch_missing")
        binding_file = captured(
            binding_path.name,
            reason_code="claim_dispatch_binding_missing",
        )
        try:
            claim_task = claim_file.content.decode("utf-8").strip()
        except UnicodeError as exc:
            raise ClaimPublicationError(
                "claim_cache_missing",
                "restore the exact regular claim, epoch, and dispatch-binding sidecars",
                str(claim_path),
            ) from exc
        if claim_task != task_id:
            raise ClaimPublicationError(
                "claim_task_mismatch",
                "bind every current claim cache to the exact task",
                str(claim_path),
            )
        try:
            epoch_text, epoch_task = epoch_file.content.decode("utf-8").split()
            epoch = int(epoch_text)
        except (UnicodeError, ValueError) as exc:
            raise ClaimPublicationError(
                "claim_epoch_malformed",
                "restore the '<epoch> <task_id>' claim epoch sidecar",
                str(epoch_path),
            ) from exc
        try:
            binding = load_claim_dispatch_binding(binding_path, content=binding_file.content)
        except TaskStoreError as exc:
            raise ClaimPublicationError(exc.reason_code, exc.repair_action, exc.detail) from exc
        if (
            epoch <= 0
            or epoch_task != task_id
            or binding.claim_epoch != epoch
            or binding.task_id != task_id
            or binding.lane != role
            or binding.session_id != resolved_session
        ):
            raise ClaimPublicationError(
                "claim_binding_vector_mismatch",
                "reclaim through the exact governed dispatch so all claim sidecars agree",
                key,
            )
        leases.append(
            ClaimLeaseSnapshot(
                claim_key=key,
                claim_path=claim_path,
                claim_content=claim_file.content,
                claim_mode=stat.S_IMODE(claim_file.stamp.mode),
                epoch_path=epoch_path,
                epoch_content=epoch_file.content,
                epoch_mode=stat.S_IMODE(epoch_file.stamp.mode),
                binding_path=binding_path,
                binding_content=binding_file.content,
                binding_mode=stat.S_IMODE(binding_file.stamp.mode),
                binding=binding,
            )
        )
    if any(item.binding != leases[0].binding for item in leases[1:]):
        raise ClaimPublicationError(
            "claim_binding_sidecars_conflict",
            "restore identical role and session claim dispatch bindings",
            role,
        )
    if session_id is None and (
        leases[0].binding_path != role_binding_path
        or leases[0].binding_content != role_binding_file.content
        or leases[0].binding_mode != stat.S_IMODE(role_binding_file.stamp.mode)
        or leases[0].binding != role_binding
    ):
        raise ClaimPublicationError(
            "claim_role_binding_changed_during_resolution",
            "retry after the exact role binding stabilizes",
            role,
        )
    return tuple(leases)


def _capture_publication_journal(
    snapshot: ReadOnlyFsSnapshot,
    manifest_path: Path,
) -> _CapturedPublicationJournalBytes:
    normalized_manifest = _normalized(manifest_path)
    directory = snapshot.pin_absolute_dir(
        normalized_manifest.parent,
        private_final=True,
    )
    assert directory is not None
    names = snapshot.list_names(directory)
    if len(names) > _CLAIM_SNAPSHOT_MAX_JOURNAL_CHILDREN:
        raise ClaimPublicationError(
            "claim_publication_journal_entry_limit",
            "restore the bounded deterministic journal file set",
            f"{directory.path}:{len(names)}",
        )
    if "manifest.json" not in names:
        raise ClaimPublicationError(
            "claim_publication_manifest_unreadable",
            "restore the exact private claim publication manifest",
            str(normalized_manifest),
        )
    manifest_observation = snapshot.observe_file_at(
        directory,
        "manifest.json",
        private=True,
        max_bytes=_CLAIM_SNAPSHOT_MAX_MANIFEST_BYTES,
    )
    if manifest_observation.captured is None:
        raise ClaimPublicationError(
            "claim_publication_manifest_unreadable",
            "restore the exact private claim publication manifest",
            str(normalized_manifest),
        )
    blobs: dict[str, tuple[bytes, int]] = {}
    for name in names:
        if name == "manifest.json":
            continue
        observed = snapshot.observe_file_at(
            directory,
            name,
            private=True,
            max_bytes=_CLAIM_SNAPSHOT_MAX_BLOB_BYTES,
        )
        if observed.captured is None:
            raise ClaimPublicationError(
                "claim_publication_blob_missing",
                "restore every manifest-declared private journal blob",
                str(observed.path),
            )
        blobs[name] = (
            observed.captured.content,
            stat.S_IMODE(observed.captured.stamp.mode),
        )
    return _CapturedPublicationJournalBytes(
        manifest_path=normalized_manifest,
        manifest_content=manifest_observation.captured.content,
        manifest_mode=stat.S_IMODE(manifest_observation.captured.stamp.mode),
        blobs=blobs,
    )


def _capture_receipt(
    snapshot: ReadOnlyFsSnapshot,
    receipt_path: Path,
) -> CapturedFile:
    normalized_receipt = _normalized(receipt_path)
    directory = snapshot.pin_absolute_dir(
        normalized_receipt.parent,
        private_final=True,
    )
    assert directory is not None
    observed = snapshot.observe_file_at(
        directory,
        normalized_receipt.name,
        private=True,
        max_bytes=_CLAIM_SNAPSHOT_MAX_MANIFEST_BYTES,
    )
    if observed.captured is None:
        raise ClaimPublicationError(
            "claim_publication_receipt_unreadable",
            "restore the exact canonical applied receipt",
            str(normalized_receipt),
        )
    return observed.captured


def _require_captured_postimages(
    snapshot: ReadOnlyFsSnapshot,
    projections: Sequence[FileProjection],
) -> None:
    directories: dict[Path, PinnedDirectory] = {}
    drift: list[str] = []
    for projection in projections:
        parent_path = _normalized(projection.path.parent)
        parent = directories.get(parent_path)
        if parent is None:
            pinned = snapshot.pin_absolute_dir(parent_path, private_final=False)
            assert pinned is not None
            directories[parent_path] = pinned
            parent = pinned
        observed = snapshot.observe_file_at(
            parent,
            projection.path.name,
            private=False,
            max_bytes=_CLAIM_SNAPSHOT_MAX_PROJECTION_BYTES,
        )
        if observed.captured is None:
            content = None
            mode = None
        else:
            content = observed.captured.content
            mode = stat.S_IMODE(observed.captured.stamp.mode)
        if content != projection.after or mode != projection.after_mode:
            drift.append(str(projection.path))
    if drift:
        raise ClaimPublicationError(
            "claim_publication_postimage_drift",
            "hold the claim and restore its exact receipt-bound postimages",
            ",".join(drift),
        )


def _require_captured_task_postimage(
    current_task: TaskNoteSnapshot,
    intent: ClaimPublicationIntent,
) -> None:
    if (
        current_task.path != intent.note_path
        or current_task.content != intent.note_after
        or current_task.mode != intent.note_mode
    ):
        raise ClaimPublicationError(
            "claim_publication_task_projection_invalid",
            "restore the exact receipt-bound active task-note postimage",
            intent.task_id,
        )


def require_applied_claim_publication(
    intent: ClaimPublicationIntent,
    *,
    transaction_root: Path | None = None,
    receipt_root: Path | None = None,
    lock_root: Path | None = None,
    _already_locked: bool = False,
) -> ClaimPublicationReceipt:
    """Fail closed unless the exact claim, note, journal, and receipt are applied."""

    del lock_root, _already_locked
    root = _manifest_root(transaction_root, intent.cache_dir)
    publication_id = claim_publication_id(intent)
    manifest_path = root / publication_id / "manifest.json"
    receipt_path = claim_publication_receipt_path(
        intent.cache_dir, intent.binding, receipt_root=receipt_root
    )
    try:
        with ReadOnlyFsSnapshot(change_scope="observed_paths") as snapshot:
            current_task = _capture_current_task_note(
                snapshot,
                intent.note_path.parent.parent,
                intent.task_id,
            )
            journal = _capture_publication_journal(snapshot, manifest_path)
            receipt_capture = _capture_receipt(snapshot, receipt_path)
            loaded_intent, projections, loaded_id, state = _load_manifest(
                journal.manifest_path,
                manifest_content=journal.manifest_content,
                captured_blobs=journal.blobs,
            )
            if loaded_intent != intent or loaded_id != publication_id or state != "applied":
                raise ClaimPublicationError(
                    "claim_publication_not_applied",
                    "recover and require the exact applied claim publication receipt",
                    f"{publication_id}:{state}",
                )
            _require_captured_postimages(snapshot, projections)
            _require_captured_task_postimage(current_task, loaded_intent)
            receipt = _as_receipt(
                journal.manifest_path,
                _normalized(receipt_path),
                loaded_intent,
                projections,
                publication_id,
                recovered=False,
                receipt_content=receipt_capture.content,
                receipt_mode=stat.S_IMODE(receipt_capture.stamp.mode),
            )
            snapshot.seal()
            return receipt
    except ReadOnlySnapshotError as exc:
        _raise_snapshot_error(exc)


def require_applied_admitted_claim_publication(
    intent: ClaimPublicationIntent,
    consumption: ClaimAdmissionConsumptionRecord,
    *,
    transaction_root: Path | None = None,
    receipt_root: Path | None = None,
    lock_root: Path | None = None,
    _already_locked: bool = False,
) -> ClaimPublicationReceipt:
    """Require the exact applied admitted publication without rereading proof sources."""

    del lock_root, _already_locked
    root = _manifest_root(transaction_root, intent.cache_dir)
    publication_id = admitted_claim_publication_id(intent, consumption)
    manifest_path = root / publication_id / "manifest.json"
    receipt_path = claim_publication_receipt_path(
        intent.cache_dir, intent.binding, receipt_root=receipt_root
    )
    try:
        with ReadOnlyFsSnapshot(change_scope="observed_paths") as snapshot:
            current_task = _capture_current_task_note(
                snapshot,
                intent.note_path.parent.parent,
                intent.task_id,
            )
            journal = _capture_publication_journal(snapshot, manifest_path)
            receipt_capture = _capture_receipt(snapshot, receipt_path)
            (
                loaded_intent,
                loaded_projections,
                loaded_id,
                state,
                loaded_consumption,
            ) = _load_admitted_manifest(
                journal.manifest_path,
                manifest_content=journal.manifest_content,
                captured_blobs=journal.blobs,
            )
            if (
                loaded_intent != intent
                or loaded_consumption != consumption
                or loaded_id != publication_id
                or state != "applied"
            ):
                raise ClaimPublicationError(
                    "claim_publication_not_applied",
                    "recover and require the exact admitted claim publication receipt",
                    f"{publication_id}:{state}",
                )
            _require_captured_postimages(snapshot, loaded_projections[:7])
            _require_captured_task_postimage(current_task, loaded_intent)
            receipt = _as_admitted_receipt(
                journal.manifest_path,
                _normalized(receipt_path),
                loaded_intent,
                loaded_consumption,
                loaded_projections,
                publication_id,
                recovered=False,
                receipt_content=receipt_capture.content,
                receipt_mode=stat.S_IMODE(receipt_capture.stamp.mode),
            )
            snapshot.seal()
            return receipt
    except ReadOnlySnapshotError as exc:
        _raise_snapshot_error(exc)


def _resolve_applied_captured(
    *,
    current_task: TaskNoteSnapshot,
    leases: tuple[ClaimLeaseSnapshot, ...],
    journal: _CapturedPublicationJournalBytes,
    receipt_path: Path,
    receipt_content: bytes,
    receipt_mode: int,
) -> AppliedClaimPublicationSnapshot:
    if len(leases) != 2 or leases[0].binding != leases[1].binding:
        raise ClaimPublicationError(
            "claim_publication_lease_vector_invalid",
            "restore identical role and role-session lease vectors",
            current_task.task_id,
        )
    binding = leases[0].binding
    if receipt_mode != 0o600:
        raise ClaimPublicationError(
            "claim_publication_receipt_mode_mismatch",
            "restore the immutable applied receipt mode to 0600",
            str(receipt_path),
        )
    record = _load_any_claim_publication_receipt(receipt_path, content=receipt_content)
    publication_id = str(record["publication_id"])
    manifest_path = journal.manifest_path
    manifest_content = journal.manifest_content
    manifest_mode = journal.manifest_mode
    if manifest_path.parent.name != publication_id:
        raise ClaimPublicationError(
            "claim_publication_manifest_identity_mismatch",
            "restore the manifest selected by the exact applied receipt",
            f"{manifest_path.parent.name}!={publication_id}",
        )
    if manifest_mode != 0o600:
        raise ClaimPublicationError(
            "claim_publication_manifest_mode_mismatch",
            "restore the immutable applied manifest mode to 0600",
            str(manifest_path),
        )
    intent, projections, loaded_id, state, consumption = _load_any_manifest(
        manifest_path,
        manifest_content=manifest_content,
        captured_blobs=journal.blobs,
    )
    if loaded_id != publication_id or state != "applied":
        raise ClaimPublicationError(
            "claim_publication_not_applied",
            "recover the exact publication before consuming its claim",
            f"{publication_id}:{state}",
        )
    if (
        intent.binding != binding
        or intent.task_id != current_task.task_id
        or intent.role != binding.lane
        or intent.session_id != binding.session_id
        or intent.claim_epoch != binding.claim_epoch
    ):
        raise ClaimPublicationError(
            "claim_publication_current_identity_mismatch",
            "restore the task, lease, dispatch, and publication identity vector",
            current_task.task_id,
        )
    receipt = _as_any_receipt(
        manifest_path,
        receipt_path,
        intent,
        projections,
        publication_id,
        consumption,
        recovered=False,
        receipt_content=receipt_content,
        receipt_mode=receipt_mode,
    )
    if (
        record.get("binding_receipt_hash") != binding.receipt_hash
        or record.get("task_id") != current_task.task_id
        or record.get("role") != binding.lane
        or record.get("session_id") != binding.session_id
        or record.get("claim_epoch") != binding.claim_epoch
        or record.get("authority_case") != binding.authority_case
    ):
        raise ClaimPublicationError(
            "claim_publication_receipt_identity_mismatch",
            "restore the applied receipt bound to the exact current lease",
            current_task.task_id,
        )

    lease_projections = projections[1:7]
    lease_states = tuple(
        state
        for lease in leases
        for state in (
            (lease.claim_path, lease.claim_content, lease.claim_mode),
            (lease.epoch_path, lease.epoch_content, lease.epoch_mode),
            (lease.binding_path, lease.binding_content, lease.binding_mode),
        )
    )
    if len(lease_projections) != len(lease_states) or any(
        projection.path != path
        or projection.after != content
        or projection.after_mode != mode
        or projection.before is not None
        or projection.before_mode is not None
        for projection, (path, content, mode) in zip(lease_projections, lease_states, strict=True)
    ):
        raise ClaimPublicationError(
            "claim_publication_immutable_lease_mismatch",
            "reclaim through the exact applied claim publication",
            current_task.task_id,
        )
    frontmatter = current_task.frontmatter
    if (
        current_task.path != intent.note_path
        or current_task.mode != intent.note_mode
        or str(frontmatter.get("assigned_to") or "").strip() != binding.lane
        or str(frontmatter.get("authority_case") or "").strip() != binding.authority_case
    ):
        raise ClaimPublicationError(
            "claim_publication_current_task_identity_mismatch",
            "restore one active task with the receipt-bound path, lane, and AuthorityCase",
            current_task.task_id,
        )
    return AppliedClaimPublicationSnapshot(
        intent=intent,
        current_task=current_task,
        leases=leases,
        receipt=receipt,
        receipt_content=receipt_content,
        receipt_mode=receipt_mode,
        manifest_content=manifest_content,
        manifest_mode=manifest_mode,
        admission_consumption=consumption,
    )


def _resolve_applied_claim_publication(
    *,
    vault_root: Path,
    cache_dir: Path,
    role: str,
    task_id: str,
    session_id: str | None,
    transaction_root: Path | None,
    receipt_root: Path | None,
    lock_root: Path | None,
) -> AppliedClaimPublicationSnapshot:
    del lock_root
    cache = _normalized(cache_dir)
    root = _manifest_root(transaction_root, cache)
    try:
        with ReadOnlyFsSnapshot(change_scope="observed_paths") as snapshot:
            current_task = _capture_current_task_note(snapshot, vault_root, task_id)
            leases = _capture_claim_leases(
                snapshot,
                cache,
                role=role,
                task_id=task_id,
                session_id=session_id,
            )
            binding = leases[0].binding
            receipt_path = claim_publication_receipt_path(
                cache,
                binding,
                receipt_root=receipt_root,
            )
            receipt_capture = _capture_receipt(snapshot, receipt_path)
            record = _load_any_claim_publication_receipt(
                receipt_path,
                content=receipt_capture.content,
            )
            manifest_path = root / str(record["publication_id"]) / "manifest.json"
            journal = _capture_publication_journal(snapshot, manifest_path)
            resolved = _resolve_applied_captured(
                current_task=current_task,
                leases=leases,
                journal=journal,
                receipt_path=_normalized(receipt_path),
                receipt_content=receipt_capture.content,
                receipt_mode=stat.S_IMODE(receipt_capture.stamp.mode),
            )
            snapshot.seal()
            return resolved
    except ReadOnlySnapshotError as exc:
        _raise_snapshot_error(exc)


def resolve_applied_claim_publication(
    *,
    vault_root: Path,
    cache_dir: Path,
    role: str,
    session_id: str,
    task_id: str,
    transaction_root: Path | None = None,
    receipt_root: Path | None = None,
    lock_root: Path | None = None,
) -> AppliedClaimPublicationSnapshot:
    """Resolve an exact session-bound applied claim while permitting note evolution."""

    return _resolve_applied_claim_publication(
        vault_root=vault_root,
        cache_dir=cache_dir,
        role=role,
        session_id=session_id,
        task_id=task_id,
        transaction_root=transaction_root,
        receipt_root=receipt_root,
        lock_root=lock_root,
    )


def resolve_applied_claim_publication_for_task(
    *,
    vault_root: Path,
    cache_dir: Path,
    role: str,
    task_id: str,
    transaction_root: Path | None = None,
    receipt_root: Path | None = None,
    lock_root: Path | None = None,
) -> AppliedClaimPublicationSnapshot:
    """Resolve an applied claim from the role binding's exact durable session."""

    return _resolve_applied_claim_publication(
        vault_root=vault_root,
        cache_dir=cache_dir,
        role=role,
        session_id=None,
        task_id=task_id,
        transaction_root=transaction_root,
        receipt_root=receipt_root,
        lock_root=lock_root,
    )


def _recover_one(
    manifest_path: Path,
    *,
    lock_root: Path,
    receipt_root: Path | None,
) -> ClaimPublicationRecoveryResult:
    """Gate-0A HOLD: recovery is an effect and requires activated dispatch."""

    del lock_root, receipt_root
    raise ClaimPublicationError(
        "claim_publication_recovery_activation_unvalidated",
        "dispatch recovery through a Gate-0B activated universal executor",
        str(manifest_path),
    )


def _content_address_for_file(path: Path, content: bytes) -> ContentAddress:
    digest = _sha256(content)
    return ContentAddress(ref=f"file:{_normalized(path)}@sha256:{digest}", sha256=digest)


_CLAIM_PUBLICATION_DIRECTORY_RE = re.compile(r"^claim-pub-[0-9a-f]{64}$")
_CLAIM_PUBLICATION_BLOB_RE = re.compile(r"^[0-9]{4}\.(?:before|after)$")
_MAX_CLAIM_PUBLICATIONS = 4096
_MAX_CLAIM_JOURNAL_CHILDREN = 32
_MAX_CLAIM_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_CLAIM_BLOB_BYTES = 32 * 1024 * 1024
_MAX_CLAIM_PROJECTION_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class _CapturedClaimJournal:
    publication_id: str
    manifest_path: Path
    manifest: CapturedFile
    blobs: tuple[tuple[str, CapturedFile], ...]
    journal_addresses: tuple[ContentAddress, ...]
    frontier: tuple[ContentAddress, ...]


@dataclass(frozen=True)
class _ClaimJournalCaptureFailure:
    publication_id: str
    reason_code: str
    repair_action: str
    detail: str | None
    frontier: tuple[ContentAddress, ...]


@dataclass(frozen=True)
class _ClaimInspectionDraft:
    publication_id: str
    task_id: str | None
    disposition: Literal["terminal_applied", "terminal_aborted", "hold"]
    journal_schema: str | None
    journal_state: str | None
    journal_reason_code: str | None
    claim_epoch: int | None
    binding_receipt_hash: str | None
    manifest_address: ContentAddress | None
    receipt_address: ContentAddress | None
    journal_addresses: tuple[ContentAddress, ...]
    projection_addresses: tuple[ContentAddress, ...]
    frontier: tuple[ContentAddress, ...]
    reason_code: str | None
    repair_action: str | None
    detail: str | None

    def materialize(
        self,
        *,
        seal: ContentAddress,
        observed_at: str,
    ) -> ClaimPublicationInspection:
        return ClaimPublicationInspection.create(
            publication_id=self.publication_id,
            task_id=self.task_id,
            disposition=self.disposition,
            journal_schema=self.journal_schema,
            journal_state=self.journal_state,
            journal_reason_code=self.journal_reason_code,
            claim_epoch=self.claim_epoch,
            binding_receipt_hash=self.binding_receipt_hash,
            manifest_address=self.manifest_address,
            receipt_address=self.receipt_address,
            journal_addresses=self.journal_addresses,
            projection_addresses=self.projection_addresses,
            observation_frontier=(*self.frontier, seal),
            observed_at=observed_at,
            reason_code=self.reason_code,
            repair_action=self.repair_action,
            detail=self.detail,
        )


def _support_address(kind: str, label: str, body: object) -> ContentAddress:
    digest = _sha256(kind.encode("ascii") + b"\0" + _canonical(body))
    return ContentAddress(ref=f"{kind}:{label}@sha256:{digest}", sha256=digest)


def _directory_address(directory: PinnedDirectory) -> ContentAddress:
    return ContentAddress(
        ref=(f"fs-directory-observation:{directory.path}@sha256:{directory.observation_sha256}"),
        sha256=directory.observation_sha256,
    )


def _captured_observation_address(captured: CapturedFile) -> ContentAddress:
    return ContentAddress(
        ref=f"fs-file-observation:{captured.path}@sha256:{captured.observation_sha256}",
        sha256=captured.observation_sha256,
    )


def _missing_file_address(path: Path, observation_sha256: str) -> ContentAddress:
    return ContentAddress(
        ref=f"fs-file-observation:{path}@sha256:{observation_sha256}",
        sha256=observation_sha256,
    )


def _capture_failure(
    publication_id: str,
    exc: Exception,
    *,
    frontier: Sequence[ContentAddress],
) -> _ClaimJournalCaptureFailure:
    if isinstance(exc, (ClaimPublicationError, ReadOnlySnapshotError)):
        return _ClaimJournalCaptureFailure(
            publication_id,
            exc.reason_code,
            exc.repair_action,
            exc.detail,
            tuple(frontier),
        )
    return _ClaimJournalCaptureFailure(
        publication_id,
        "claim_publication_inspection_failed",
        "inspect the exact journal and retry after the observation stabilizes",
        type(exc).__name__,
        tuple(frontier),
    )


def _capture_claim_journals(
    snapshot: ReadOnlyFsSnapshot,
    root: Path,
) -> tuple[
    tuple[_CapturedClaimJournal | _ClaimJournalCaptureFailure, ...],
    ContentAddress,
]:
    directory = snapshot.pin_absolute_dir(root, private_final=True, allow_missing=True)
    if directory is None:
        listing = _support_address(
            "claim-publication-listing",
            str(root),
            {"names": (), "present": False, "root": str(root)},
        )
        return (), listing
    names = snapshot.list_names(directory)
    listing = _support_address(
        "claim-publication-listing",
        str(root),
        {
            "directory_observation": directory.observation_sha256,
            "names": names,
            "present": True,
            "root": str(root),
        },
    )
    if len(names) > _MAX_CLAIM_PUBLICATIONS:
        raise ClaimPublicationError(
            "claim_publication_count_limit",
            "narrow the estate scan or raise an explicitly governed journal limit",
            str(len(names)),
        )
    entries: list[_CapturedClaimJournal | _ClaimJournalCaptureFailure] = []
    root_frontier = (listing, _directory_address(directory))
    for name in names:
        if _CLAIM_PUBLICATION_DIRECTORY_RE.fullmatch(name) is None:
            entries.append(
                _ClaimJournalCaptureFailure(
                    name,
                    "claim_publication_transaction_entry_unknown",
                    "quarantine every entry outside the exact claim publication grammar",
                    str(root / name),
                    root_frontier,
                )
            )
            continue
        try:
            transaction = snapshot.pin_dir_at(directory, name, private=True)
            children = snapshot.list_names(transaction)
            if len(children) > _MAX_CLAIM_JOURNAL_CHILDREN:
                raise ClaimPublicationError(
                    "claim_publication_journal_entry_limit",
                    "restore the bounded deterministic journal file set",
                    f"{root / name}:{len(children)}",
                )
            if "manifest.json" not in children:
                raise ClaimPublicationError(
                    "claim_publication_manifest_missing",
                    "restore the exact private manifest for this transaction",
                    str(root / name),
                )
            unknown = tuple(
                child
                for child in children
                if child != "manifest.json" and _CLAIM_PUBLICATION_BLOB_RE.fullmatch(child) is None
            )
            if unknown:
                raise ClaimPublicationError(
                    "claim_publication_journal_entry_unknown",
                    "remove undeclared files from the private journal directory",
                    f"{root / name}:{','.join(unknown)}",
                )
            manifest_observation = snapshot.observe_file_at(
                transaction,
                "manifest.json",
                private=True,
                max_bytes=_MAX_CLAIM_MANIFEST_BYTES,
            )
            assert manifest_observation.captured is not None
            blobs: list[tuple[str, CapturedFile]] = []
            observations = [
                _directory_address(transaction),
                _captured_observation_address(manifest_observation.captured),
            ]
            for child in children:
                if child == "manifest.json":
                    continue
                observed = snapshot.observe_file_at(
                    transaction,
                    child,
                    private=True,
                    max_bytes=_MAX_CLAIM_BLOB_BYTES,
                )
                assert observed.captured is not None
                blobs.append((child, observed.captured))
                observations.append(_captured_observation_address(observed.captured))
            entries.append(
                _CapturedClaimJournal(
                    publication_id=name,
                    manifest_path=transaction.path / "manifest.json",
                    manifest=manifest_observation.captured,
                    blobs=tuple(blobs),
                    journal_addresses=tuple(observations[1:]),
                    frontier=(*root_frontier, *observations),
                )
            )
        except Exception as exc:  # noqa: BLE001 - each corrupt entry becomes HOLD.
            entries.append(_capture_failure(name, exc, frontier=root_frontier))
    return tuple(entries), listing


def _validate_captured_receipt(
    path: Path,
    content: bytes,
    intent: ClaimPublicationIntent,
    projections: Sequence[FileProjection],
    publication_id: str,
    consumption: ClaimAdmissionConsumptionRecord | None,
) -> None:
    record = _load_any_claim_publication_receipt(path, content=content)
    expected = (
        _receipt_record(intent, projections, publication_id)
        if consumption is None
        else _admitted_receipt_record(intent, consumption, projections, publication_id)
    )
    if record != expected:
        raise ClaimPublicationError(
            "claim_publication_receipt_mismatch",
            "restore the exact captured receipt bound to this journal",
            publication_id,
        )


def _draft_hold(
    *,
    publication_id: str,
    task_id: str | None,
    reason_code: str,
    repair_action: str,
    frontier: Sequence[ContentAddress],
    detail: str | None = None,
    journal_schema: str | None = None,
    journal_state: str | None = None,
    journal_reason_code: str | None = None,
    claim_epoch: int | None = None,
    binding_receipt_hash: str | None = None,
    manifest_address: ContentAddress | None = None,
    receipt_address: ContentAddress | None = None,
    journal_addresses: Sequence[ContentAddress] = (),
    projection_addresses: Sequence[ContentAddress] = (),
) -> _ClaimInspectionDraft:
    return _ClaimInspectionDraft(
        publication_id=publication_id,
        task_id=task_id,
        disposition="hold",
        journal_schema=journal_schema,
        journal_state=journal_state,
        journal_reason_code=journal_reason_code,
        claim_epoch=claim_epoch,
        binding_receipt_hash=binding_receipt_hash,
        manifest_address=manifest_address,
        receipt_address=receipt_address,
        journal_addresses=tuple(journal_addresses),
        projection_addresses=tuple(projection_addresses),
        frontier=tuple(frontier),
        reason_code=reason_code,
        repair_action=repair_action,
        detail=detail,
    )


def _projection_snapshots(
    snapshot: ReadOnlyFsSnapshot,
    projections: Sequence[FileProjection],
    directories: dict[Path, PinnedDirectory],
) -> tuple[tuple[bytes | None, int | None, ContentAddress], ...]:
    captured: list[tuple[bytes | None, int | None, ContentAddress]] = []
    for projection in projections:
        parent_path = _normalized(projection.path.parent)
        parent = directories.get(parent_path)
        if parent is None:
            pinned = snapshot.pin_absolute_dir(parent_path, private_final=False)
            assert pinned is not None
            directories[parent_path] = pinned
            parent = pinned
        observed = snapshot.observe_file_at(
            parent,
            projection.path.name,
            private=False,
            max_bytes=_MAX_CLAIM_PROJECTION_BYTES,
        )
        if observed.captured is None:
            captured.append(
                (
                    None,
                    None,
                    _missing_file_address(observed.path, observed.observation_sha256),
                )
            )
        else:
            captured.append(
                (
                    observed.captured.content,
                    stat.S_IMODE(observed.captured.stamp.mode),
                    _captured_observation_address(observed.captured),
                )
            )
    return tuple(captured)


def _classify_captured_journal(
    snapshot: ReadOnlyFsSnapshot,
    captured: _CapturedClaimJournal,
    *,
    listing: ContentAddress,
    trusted_cache: Path,
    receipt_directory: PinnedDirectory | None,
    receipt_root: Path,
    projection_directories: dict[Path, PinnedDirectory],
) -> _ClaimInspectionDraft:
    manifest_address = _content_address_for_file(captured.manifest_path, captured.manifest.content)
    blobs = {name: (item.content, stat.S_IMODE(item.stamp.mode)) for name, item in captured.blobs}
    intent, projections, publication_id, state, consumption = _load_any_manifest(
        captured.manifest_path,
        manifest_content=captured.manifest.content,
        captured_blobs=blobs,
    )
    record, _ = _strict_json(
        captured.manifest_path,
        content=captured.manifest.content,
    )
    schema = str(record["schema"])
    stored_reason = record.get("reason_code")
    journal_reason = stored_reason if isinstance(stored_reason, str) and stored_reason else None
    common = {
        "publication_id": publication_id,
        "task_id": intent.task_id,
        "journal_schema": schema,
        "journal_state": state,
        "journal_reason_code": journal_reason,
        "claim_epoch": intent.claim_epoch,
        "binding_receipt_hash": intent.binding.receipt_hash,
        "manifest_address": manifest_address,
    }
    if intent.cache_dir != trusted_cache:
        return _draft_hold(
            **common,
            reason_code="claim_publication_cache_root_mismatch",
            repair_action="bind inspection to the exact trusted cache root",
            detail=f"{intent.cache_dir}!={trusted_cache}",
            frontier=captured.frontier,
            journal_addresses=captured.journal_addresses,
        )
    receipt_path = claim_publication_receipt_path(
        trusted_cache,
        intent.binding,
        receipt_root=receipt_root,
    )
    if receipt_directory is None:
        receipt_observation = _support_address(
            "fs-file-observation",
            str(receipt_path),
            {"parent_present": False, "path": str(receipt_path), "present": False},
        )
        receipt_file = None
    else:
        observed_receipt = snapshot.observe_file_at(
            receipt_directory,
            receipt_path.name,
            private=True,
            max_bytes=_MAX_CLAIM_MANIFEST_BYTES,
        )
        receipt_observation = (
            _missing_file_address(receipt_path, observed_receipt.observation_sha256)
            if observed_receipt.captured is None
            else _captured_observation_address(observed_receipt.captured)
        )
        receipt_file = observed_receipt.captured
    receipt_address = (
        None
        if receipt_file is None
        else _content_address_for_file(receipt_path, receipt_file.content)
    )
    journal_addresses = (*captured.journal_addresses, receipt_observation)
    frontier = (*captured.frontier, listing, receipt_observation)

    if receipt_file is not None:
        try:
            _validate_captured_receipt(
                receipt_path,
                receipt_file.content,
                intent,
                projections,
                publication_id,
                consumption,
            )
        except ClaimPublicationError as exc:
            return _draft_hold(
                **common,
                reason_code=exc.reason_code,
                repair_action=exc.repair_action,
                detail=exc.detail,
                receipt_address=receipt_address,
                frontier=frontier,
                journal_addresses=journal_addresses,
            )

    if state == "applied":
        if receipt_file is None:
            return _draft_hold(
                **common,
                reason_code="claim_publication_applied_receipt_missing",
                repair_action="restore the exact immutable applied receipt",
                receipt_address=None,
                frontier=frontier,
                journal_addresses=journal_addresses,
            )
        if consumption is None:
            return _draft_hold(
                **common,
                reason_code="legacy_claim_publication_consumption_required",
                repair_action="republish through the admitted claim executor",
                receipt_address=receipt_address,
                frontier=frontier,
                journal_addresses=journal_addresses,
            )
        return _ClaimInspectionDraft(
            **common,
            disposition="terminal_applied",
            receipt_address=receipt_address,
            journal_addresses=tuple(journal_addresses),
            projection_addresses=(),
            frontier=tuple(frontier),
            reason_code=None,
            repair_action=None,
            detail=None,
        )

    if state == "aborted":
        if receipt_file is not None:
            return _draft_hold(
                **common,
                reason_code="claim_publication_aborted_receipt_contradiction",
                repair_action="preserve both artifacts and run admitted reconciliation",
                receipt_address=receipt_address,
                frontier=frontier,
                journal_addresses=journal_addresses,
            )
        return _ClaimInspectionDraft(
            **common,
            disposition="terminal_aborted",
            receipt_address=None,
            journal_addresses=tuple(journal_addresses),
            projection_addresses=(),
            frontier=tuple(frontier),
            reason_code=None,
            repair_action=None,
            detail=None,
        )

    if receipt_file is not None and state in {"created", "projecting"}:
        return _draft_hold(
            **common,
            reason_code="claim_publication_receipt_state_contradiction",
            repair_action="preserve the contradiction and run admitted reconciliation",
            receipt_address=receipt_address,
            frontier=frontier,
            journal_addresses=journal_addresses,
        )

    if consumption is None:
        return _draft_hold(
            **common,
            reason_code="legacy_claim_publication_reconciliation_forbidden",
            repair_action="migrate the journal through a separately admitted executor",
            receipt_address=receipt_address,
            frontier=frontier,
            journal_addresses=journal_addresses,
        )

    inspected_projections = projections[:7] if receipt_file is not None else projections
    projection_snapshots = _projection_snapshots(
        snapshot,
        inspected_projections,
        projection_directories,
    )
    projection_addresses = tuple(item[2] for item in projection_snapshots)
    frontier = (*frontier, *projection_addresses)

    def matches(
        observed: tuple[bytes | None, int | None, ContentAddress],
        content: bytes | None,
        mode: int | None,
    ) -> bool:
        return observed[0] == content and observed[1] == mode

    all_before = all(
        matches(observed, projection.before, projection.before_mode)
        for projection, observed in zip(inspected_projections, projection_snapshots, strict=True)
    )
    all_after = all(
        matches(observed, projection.after, projection.after_mode)
        for projection, observed in zip(inspected_projections, projection_snapshots, strict=True)
    )
    if receipt_file is not None:
        reason = (
            "admitted_claim_publication_postimage_requires_reconciliation"
            if all_after
            else "claim_publication_receipt_postimage_contradiction"
        )
        repair = (
            "run the separately admitted reconciliation executor"
            if all_after
            else "preserve receipt and projections for contradiction review"
        )
    elif state == "recovery_required":
        reason = "admitted_claim_publication_reconciliation_required"
        repair = "run the separately admitted reconciliation executor"
    elif all_after:
        reason = "admitted_claim_publication_outcome_receipt_missing"
        repair = "run admitted reconciliation to emit the exact outcome receipt"
    elif all_before:
        reason = "admitted_claim_publication_interrupted_before_projection"
        repair = "run admitted reconciliation or explicitly retire the journal"
    elif state == "postimage_complete":
        reason = "claim_publication_postimage_state_contradiction"
        repair = "preserve the mixed state and run admitted reconciliation"
    else:
        reason = "admitted_claim_publication_partial_projection"
        repair = "preserve every byte and run the separately admitted reconciler"
    return _draft_hold(
        **common,
        reason_code=reason,
        repair_action=repair,
        receipt_address=receipt_address,
        frontier=frontier,
        journal_addresses=journal_addresses,
        projection_addresses=projection_addresses,
    )


def _global_inspection_failure(
    root: Path,
    exc: Exception,
    *,
    observed_at: str,
) -> tuple[ClaimPublicationInspection, ...]:
    failure = _capture_failure(f"transaction-root:{root}", exc, frontier=())
    address = _support_address(
        "claim-publication-inspection-failure",
        str(root),
        {
            "detail": failure.detail,
            "reason_code": failure.reason_code,
            "root": str(root),
        },
    )
    seal = _support_address(
        "read-only-fs-snapshot",
        str(root),
        {"complete": False, "failure": address.model_dump(mode="json")},
    )
    draft = _draft_hold(
        publication_id=failure.publication_id,
        task_id=None,
        reason_code=failure.reason_code,
        repair_action=failure.repair_action,
        detail=failure.detail,
        frontier=(address,),
    )
    return (draft.materialize(seal=seal, observed_at=observed_at),)


def inspect_claim_publications(
    *,
    cache_dir: Path | None = None,
    transaction_root: Path | None = None,
    receipt_root: Path | None = None,
    task_id: str | None = None,
    expected_publication_id: str | None = None,
    expected_disposition: Literal["terminal_applied", "terminal_aborted"] | None = None,
) -> tuple[ClaimPublicationInspection, ...]:
    """Inspect estate history and unresolved journals without granting current eligibility."""

    trusted_cache = _normalized(cache_dir or (Path.home() / ".cache" / "hapax"))
    root = _manifest_root(transaction_root, trusted_cache)
    trusted_receipt_root = _receipt_root(trusted_cache, receipt_root)
    observed_at = _canonical_timestamp(datetime.now(UTC))
    try:
        snapshot = ReadOnlyFsSnapshot()
    except Exception as exc:  # noqa: BLE001 - unavailable guard is a typed HOLD.
        return _global_inspection_failure(root, exc, observed_at=observed_at)
    try:
        with snapshot:
            entries, listing = _capture_claim_journals(snapshot, root)
            receipt_directory = snapshot.pin_absolute_dir(
                trusted_receipt_root,
                private_final=True,
                allow_missing=True,
            )
            if receipt_directory is not None:
                snapshot.list_names(receipt_directory)
            projection_directories: dict[Path, PinnedDirectory] = {}
            drafts: list[_ClaimInspectionDraft] = []
            for entry in entries:
                if isinstance(entry, _ClaimJournalCaptureFailure):
                    draft = _draft_hold(
                        publication_id=entry.publication_id,
                        task_id=None,
                        reason_code=entry.reason_code,
                        repair_action=entry.repair_action,
                        detail=entry.detail,
                        frontier=entry.frontier,
                    )
                else:
                    try:
                        draft = _classify_captured_journal(
                            snapshot,
                            entry,
                            listing=listing,
                            trusted_cache=trusted_cache,
                            receipt_directory=receipt_directory,
                            receipt_root=trusted_receipt_root,
                            projection_directories=projection_directories,
                        )
                    except Exception as exc:  # noqa: BLE001 - corrupt journal is HOLD.
                        failure = _capture_failure(
                            entry.publication_id,
                            exc,
                            frontier=entry.frontier,
                        )
                        draft = _draft_hold(
                            publication_id=failure.publication_id,
                            task_id=None,
                            reason_code=failure.reason_code,
                            repair_action=failure.repair_action,
                            detail=failure.detail,
                            manifest_address=_content_address_for_file(
                                entry.manifest_path, entry.manifest.content
                            ),
                            journal_addresses=entry.journal_addresses,
                            frontier=failure.frontier,
                        )
                if (
                    task_id is None
                    or draft.task_id in {None, task_id}
                    or draft.publication_id == expected_publication_id
                ):
                    drafts.append(draft)
            expected_valid = (
                expected_publication_id is None
                or _CLAIM_PUBLICATION_DIRECTORY_RE.fullmatch(expected_publication_id) is not None
            )
            if not expected_valid:
                assert expected_publication_id is not None
                drafts = [draft for draft in drafts if draft.disposition == "hold"]
                drafts.append(
                    _draft_hold(
                        publication_id=expected_publication_id,
                        task_id=task_id,
                        reason_code="claim_publication_expected_id_invalid",
                        repair_action="use one canonical claim-pub-<64 lowercase hex> id",
                        frontier=(listing,),
                    )
                )
            elif expected_disposition is not None and expected_publication_id is None:
                drafts = [draft for draft in drafts if draft.disposition == "hold"]
                drafts.append(
                    _draft_hold(
                        publication_id="expected-publication:missing",
                        task_id=task_id,
                        reason_code="claim_publication_expected_mode_without_id",
                        repair_action="bind the required terminal mode to one exact publication id",
                        frontier=(listing,),
                    )
                )
            elif expected_publication_id is not None:
                matching = [
                    draft for draft in drafts if draft.publication_id == expected_publication_id
                ]
                if not matching:
                    drafts.append(
                        _draft_hold(
                            publication_id=expected_publication_id,
                            task_id=task_id,
                            reason_code="claim_publication_manifest_missing",
                            repair_action="restore the exact expected journal or refresh its locator",
                            frontier=(listing,),
                        )
                    )
                elif task_id is not None and matching[0].task_id not in {None, task_id}:
                    mismatch = _draft_hold(
                        publication_id=expected_publication_id,
                        task_id=task_id,
                        reason_code="claim_publication_expected_task_mismatch",
                        repair_action="bind the expected publication to its exact task",
                        detail=f"observed:{matching[0].task_id}",
                        frontier=matching[0].frontier,
                    )
                    drafts = [
                        draft for draft in drafts if draft.publication_id != expected_publication_id
                    ]
                    drafts.append(mismatch)
                elif (
                    expected_disposition is not None
                    and matching[0].disposition != "hold"
                    and matching[0].disposition != expected_disposition
                ):
                    mismatch = _draft_hold(
                        publication_id=expected_publication_id,
                        task_id=task_id,
                        reason_code="claim_publication_expected_disposition_mismatch",
                        repair_action="resolve the exact required terminal history state",
                        detail=(
                            f"expected:{expected_disposition};observed:{matching[0].disposition}"
                        ),
                        frontier=matching[0].frontier,
                    )
                    drafts = [
                        draft for draft in drafts if draft.publication_id != expected_publication_id
                    ]
                    drafts.append(mismatch)
            seal_record = snapshot.seal()
            seal = ContentAddress(ref=seal_record.seal_ref, sha256=seal_record.seal_hash)
    except Exception as exc:  # noqa: BLE001 - no partial snapshot can escape.
        return _global_inspection_failure(root, exc, observed_at=observed_at)
    return tuple(draft.materialize(seal=seal, observed_at=observed_at) for draft in drafts)


def recover_claim_publications(
    *,
    cache_dir: Path | None = None,
    transaction_root: Path | None = None,
    receipt_root: Path | None = None,
    lock_root: Path | None = None,
    task_id: str | None = None,
) -> tuple[ClaimPublicationRecoveryResult, ...]:
    """Gate-0A HOLD: recovery effects require activated universal dispatch."""

    del cache_dir, transaction_root, receipt_root, lock_root
    raise ClaimPublicationError(
        "claim_publication_recovery_activation_unvalidated",
        "dispatch recovery through a Gate-0B activated universal executor",
        task_id,
    )


__all__ = [
    "ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA",
    "ADMITTED_CLAIM_PUBLICATION_SCHEMA",
    "CLAIM_ADMISSION_CONSUMPTION_SCHEMA",
    "CLAIM_PUBLICATION_RECEIPT_SCHEMA",
    "CLAIM_PUBLICATION_SCHEMA",
    "AppliedClaimPublicationSnapshot",
    "ClaimAdmissionConsumption",
    "ClaimPublicationAdmissionProvenance",
    "ClaimPublicationError",
    "ClaimPublicationIntent",
    "ClaimPublicationInspection",
    "ClaimPublicationReceipt",
    "ClaimPublicationRecoveryResult",
    "admitted_claim_publication_id",
    "claim_publication_id",
    "claim_publication_mutation_scope_address",
    "claim_publication_receipt_path",
    "load_admitted_claim_publication_receipt",
    "load_claim_publication_receipt",
    "publish_admitted_claim",
    "publish_claim",
    "prospective_claim_publication_basis",
    "inspect_claim_publications",
    "recover_claim_publications",
    "resolve_applied_claim_publication",
    "resolve_applied_claim_publication_for_task",
    "resolve_claim_publication_admission_provenance",
    "require_applied_admitted_claim_publication",
    "require_applied_claim_publication",
]
