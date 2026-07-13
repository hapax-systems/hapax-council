"""Canon-bound terminal close admission and atomic S10 -> S11 projection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from shared.coord_event_log import CoordEventLog, default_event_log
from shared.coord_projection import (
    NO_GO_BOOLEANS,
    FileProjection,
    LifecycleTransitionIntent,
    LifecycleTransitionReceipt,
    _execute_terminal_close_transition,
    capture_coord_replay_snapshot,
    inspect_lifecycle_transactions,
)
from shared.relay_lifecycle import (
    parse_relay_document,
    relay_status_values,
    relay_values_are_retired,
)
from shared.relay_mq import (
    CanonEchoError,
    ExpectedCanonEcho,
    reconcile_canon_echo,
    require_matching_canon_echo,
    resolve_claim_bound_canon_position,
)
from shared.sdlc_claim import (
    ClaimPublicationError,
    inspect_claim_publications,
    resolve_applied_claim_publication,
)
from shared.sdlc_lifecycle import (
    acceptance_criteria_state,
    acceptance_receipt_blockers,
    acceptance_receipt_path,
    requires_acceptance_receipt,
    stage_token,
)
from shared.sdlc_task_store import (
    TaskNoteSnapshot,
    TaskStoreError,
    resolve_claim_leases,
    resolve_task_note,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VAULT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
DEFAULT_CACHE = Path.home() / ".cache" / "hapax"


class TerminalCloseError(RuntimeError):
    def __init__(self, reason_code: str, repair_action: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        self.repair_action = repair_action
        self.detail = detail
        message = f"{reason_code}: {repair_action}"
        if detail:
            message += f" ({detail})"
        super().__init__(message)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def _frontmatter_set(text: str, key: str, rendered_value: str) -> str:
    close = text.find("\n---", 3) if text.startswith("---") else -1
    if close < 0:
        raise TerminalCloseError(
            "terminal_close_frontmatter_malformed",
            "restore one closed frontmatter mapping before close",
        )
    frontmatter = text[:close]
    body = text[close:]
    pattern = rf"(?m)^{re.escape(key)}:\s*.*$"
    if re.search(pattern, frontmatter):
        frontmatter = re.sub(pattern, f"{key}: {rendered_value}", frontmatter, count=1)
    else:
        frontmatter += f"\n{key}: {rendered_value}"
    return frontmatter + body


@dataclass(frozen=True)
class _RelaySnapshot:
    path: Path
    content: bytes
    mode: int
    document: dict[str, object]


def _relay_snapshots(
    cache_dir: Path,
    role: str,
    session_id: str,
    task_id: str,
) -> tuple[_RelaySnapshot, ...]:
    relay_dir = cache_dir / "relay"
    candidates = [
        relay_dir / f"{role}-status.yaml",
        relay_dir / f"{role}.yaml",
        relay_dir / f"status-{role}.yaml",
        relay_dir / f"peer-status-{role}.yaml",
    ]
    if session_id:
        candidates.append(relay_dir / f"peer-status-{session_id}.yaml")
    snapshots: list[_RelaySnapshot] = []
    for path in candidates:
        projection = FileProjection.capture(path, after=b"", after_mode=0o600)
        if projection.before is None or projection.before_mode is None:
            continue
        document = parse_relay_document(projection.before.decode("utf-8"))
        relay_claim = document.get("current_claim") or document.get("task_id")
        if (
            not document
            or relay_values_are_retired(relay_status_values(document))
            or document.get("role") != role
            or document.get("session_id") != session_id
            or relay_claim != task_id
        ):
            raise TerminalCloseError(
                "terminal_close_relay_claim_mismatch",
                "make every live relay alias agree with the exact role, session, and task claim",
                str(path),
            )
        snapshots.append(_RelaySnapshot(path, projection.before, projection.before_mode, document))
    if not snapshots:
        raise TerminalCloseError(
            "terminal_close_relay_missing",
            "restore one current relay mapping for the owning lane",
            role,
        )
    return tuple(snapshots)


def _render_expected_payload(expected: ExpectedCanonEcho) -> str:
    from shared.session_context_canon import build_canon_bundle

    bundle = build_canon_bundle()
    if bundle.canon_hash != expected.canon_hash:
        raise TerminalCloseError(
            "terminal_close_canon_hash_mismatch",
            "restore the canon committed by the claim-bound position",
        )
    image = next(
        (
            item
            for item in bundle.images
            if item.stage_token == expected.stage_token and item.level.value == expected.canon_level
        ),
        None,
    )
    if (
        image is None
        or image.image_hash != expected.canon_image_hash
        or hashlib.sha256(image.rendered_payload.encode()).hexdigest()
        != expected.canon_payload_sha256
    ):
        raise TerminalCloseError(
            "terminal_close_canon_image_mismatch",
            "restore the exact current-stage canon image",
        )
    return image.rendered_payload


@dataclass(frozen=True)
class CloseGateEvidence:
    gate: str
    outcome: str
    task_id: str
    note_sha256: str
    authority_case: str
    final_status: str
    observed_at: str
    command: tuple[str, ...] = ()
    returncode: int | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None

    def to_record(self) -> dict[str, object]:
        return {
            "authority_case": self.authority_case,
            "command": list(self.command),
            "final_status": self.final_status,
            "gate": self.gate,
            "may_authorize": False,
            "note_sha256": self.note_sha256,
            "observed_at": self.observed_at,
            "outcome": self.outcome,
            "returncode": self.returncode,
            "schema": "hapax.terminal-close-gate-evidence.v1",
            "stderr_sha256": self.stderr_sha256,
            "stdout_sha256": self.stdout_sha256,
            "task_id": self.task_id,
        }

    @property
    def evidence_ref(self) -> str:
        return f"terminal-close-gate@sha256:{_sha256(_canonical_json_bytes(self.to_record()))}"


def _default_done_gate_runner(
    snapshot: TaskNoteSnapshot,
    final_status: str,
    pr: str,
    retroactive: bool,
    _debt_reason: str | None,
) -> tuple[CloseGateEvidence, ...]:
    observed_at = datetime.now(UTC).isoformat()
    authority_case = str(snapshot.frontmatter.get("authority_case") or "")
    if final_status != "done":
        return (
            CloseGateEvidence(
                gate="done-only-gates",
                outcome="not_applicable",
                task_id=snapshot.task_id,
                note_sha256=snapshot.sha256,
                authority_case=authority_case,
                final_status=final_status,
                observed_at=observed_at,
            ),
        )
    blockers: list[str] = []
    criteria = acceptance_criteria_state(snapshot.content.decode("utf-8"))
    if criteria.section_present and criteria.unchecked_items:
        blockers.append("acceptance_criteria_incomplete")
    if requires_acceptance_receipt(snapshot.frontmatter):
        blockers.extend(acceptance_receipt_blockers(snapshot.frontmatter, snapshot.path))
    claimed_at = snapshot.frontmatter.get("claimed_at")
    if claimed_at and not retroactive:
        try:
            claimed = datetime.fromisoformat(str(claimed_at).replace("Z", "+00:00"))
            if (datetime.now(UTC) - claimed.astimezone(UTC)).total_seconds() < 300:
                blockers.append("rapid_close_requires_retroactive")
        except ValueError:
            blockers.append("claimed_at_malformed")
    if blockers:
        raise TerminalCloseError(
            "terminal_close_done_gate_refused",
            "satisfy every done-only closure gate before retrying",
            ",".join(blockers),
        )
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    for key in (
        "HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF",
        "HAPAX_ARTIFACT_DISPOSITION_GATE_OFF",
        "HAPAX_CC_TASK_CLOSURE_GATE_OFF",
        "HAPAX_PR_MERGE_GATE_OFF",
    ):
        environment.pop(key, None)
    commands: list[tuple[str, list[str]]] = []
    merge_checker = REPO_ROOT / "scripts" / "cc-close-pr-merge-check.py"
    if not merge_checker.is_file():
        raise TerminalCloseError(
            "terminal_close_pr_merge_checker_missing",
            "restore the governed PR merge checker before close",
            str(merge_checker),
        )
    commands.append(
        (
            "pr-merge",
            [
                sys.executable,
                "-I",
                str(merge_checker),
                str(snapshot.path),
                *(["--pr", pr] if pr else []),
            ],
        )
    )
    disposition = REPO_ROOT / "scripts" / "cc-task-artifact-disposition-check.py"
    if not disposition.is_file():
        raise TerminalCloseError(
            "terminal_close_artifact_disposition_checker_missing",
            "restore the governed artifact disposition checker before close",
            str(disposition),
        )
    command = [
        sys.executable,
        "-I",
        str(disposition),
        str(snapshot.path),
        snapshot.task_id,
    ]
    commands.append(("artifact-disposition", command))
    evidence = [
        CloseGateEvidence(
            gate="task-close-internal",
            outcome="pass",
            task_id=snapshot.task_id,
            note_sha256=snapshot.sha256,
            authority_case=authority_case,
            final_status=final_status,
            observed_at=observed_at,
        )
    ]
    for name, command in commands:
        before_hash = _sha256(snapshot.path.read_bytes())
        result = subprocess.run(
            command, env=environment, capture_output=True, text=True, check=False
        )
        after_hash = _sha256(snapshot.path.read_bytes())
        if before_hash != snapshot.sha256 or after_hash != snapshot.sha256:
            raise TerminalCloseError(
                "terminal_close_preflight_note_drift",
                "rerun close against one stable exact note preimage",
                name,
            )
        if result.returncode != 0:
            raise TerminalCloseError(
                f"terminal_close_{name}_refused",
                "satisfy the governed checker before retrying close",
                result.stderr.strip() or str(result.returncode),
            )
        evidence.append(
            CloseGateEvidence(
                gate=name,
                outcome="pass",
                task_id=snapshot.task_id,
                note_sha256=snapshot.sha256,
                authority_case=authority_case,
                final_status=final_status,
                observed_at=datetime.now(UTC).isoformat(),
                command=tuple(command),
                returncode=result.returncode,
                stdout_sha256=_sha256(result.stdout.encode()),
                stderr_sha256=_sha256(result.stderr.encode()),
            )
        )
    return tuple(evidence)


@dataclass(frozen=True)
class TerminalCloseAdmission:
    task_id: str
    final_status: str
    actor: str
    session_id: str
    authority_case: str
    note_path: str
    note_mode: int
    note_sha256: str
    receipt_path: str | None
    receipt_mode: int | None
    receipt_sha256: str | None
    claim_publication_proof: tuple[dict[str, object], ...]
    claim_vector: tuple[dict[str, object], ...]
    relay_vector: tuple[dict[str, object], ...]
    position_ref: str
    echo_message_id: str
    gate_evidence: tuple[CloseGateEvidence, ...]

    @property
    def gate_refs(self) -> tuple[str, ...]:
        return tuple(item.evidence_ref for item in self.gate_evidence)

    def to_record(self) -> dict[str, object]:
        return {
            "actor": self.actor,
            "authority_case": self.authority_case,
            "claim_publication_proof": list(self.claim_publication_proof),
            "claim_vector": list(self.claim_vector),
            "echo_message_id": self.echo_message_id,
            "final_status": self.final_status,
            "gate_evidence": [item.to_record() for item in self.gate_evidence],
            "gate_refs": list(self.gate_refs),
            "may_authorize": False,
            "note_mode": self.note_mode,
            "note_path": self.note_path,
            "note_sha256": self.note_sha256,
            "position_ref": self.position_ref,
            "receipt_mode": self.receipt_mode,
            "receipt_path": self.receipt_path,
            "receipt_sha256": self.receipt_sha256,
            "relay_vector": list(self.relay_vector),
            "schema": "hapax.terminal-close-admission.v2",
            "session_id": self.session_id,
            "task_id": self.task_id,
        }

    @property
    def admission_ref(self) -> str:
        return f"terminal-close-admission@sha256:{_sha256(_canonical_json_bytes(self.to_record()))}"

    def receipt_payload(self) -> bytes:
        body = {**self.to_record(), "admission_ref": self.admission_ref}
        return (
            _canonical_json_bytes({**body, "receipt_hash": _sha256(_canonical_json_bytes(body))})
            + b"\n"
        )


def close_task(
    task_id: str,
    *,
    final_status: str = "done",
    pr: str = "",
    actor: str,
    session_id: str,
    retroactive: bool = False,
    debt_reason: str | None = None,
    vault_root: Path = DEFAULT_VAULT,
    cache_dir: Path = DEFAULT_CACHE,
    relay_db: Path | None = None,
    dispatch_ledger: Path | None = None,
    event_log: CoordEventLog | None = None,
) -> LifecycleTransitionReceipt:
    del dispatch_ledger
    if final_status not in {"done", "withdrawn", "superseded"}:
        raise TerminalCloseError(
            "terminal_close_status_invalid",
            "use done, withdrawn, or superseded",
            final_status,
        )
    if final_status != "done":
        raise TerminalCloseError(
            "terminal_close_operator_disposition_receipt_required",
            "keep the task active until an operator-minted withdrawn or superseded receipt is available",
            final_status,
        )
    if debt_reason:
        raise TerminalCloseError(
            "terminal_close_debt_override_requires_receipt",
            "record a governed override receipt before canon-bound close; raw --debt is legacy-only",
        )
    if retroactive:
        raise TerminalCloseError(
            "terminal_close_retroactive_receipt_required",
            "bind typed operator evidence through the admitted close contract; a raw retroactive assertion cannot authorize close",
        )
    if not actor or actor == "unknown" or not session_id:
        raise TerminalCloseError(
            "terminal_close_identity_missing",
            "bind the real lane and claim session before close",
        )
    event_log = event_log or default_event_log()
    lifecycle_inspection = inspect_lifecycle_transactions(
        task_id=task_id,
        event_plane_snapshot=capture_coord_replay_snapshot(event_log),
    )
    if not lifecycle_inspection.scope_complete:
        raise TerminalCloseError(
            "terminal_close_lifecycle_inspection_hold",
            "reconcile the inspected lifecycle frontier before retrying",
            ",".join(lifecycle_inspection.reason_codes),
        )
    claim_inspection = inspect_claim_publications(cache_dir=cache_dir, task_id=task_id)
    held_claims = [item for item in claim_inspection if item.disposition == "hold"]
    if held_claims:
        raise TerminalCloseError(
            "terminal_close_claim_inspection_hold",
            "reconcile the inspected claim publication before close",
            ",".join(f"{item.publication_id}:{item.reason_code}" for item in held_claims),
        )
    try:
        applied_claim = resolve_applied_claim_publication(
            vault_root=vault_root,
            cache_dir=cache_dir,
            role=actor,
            session_id=session_id,
            task_id=task_id,
        )
        snapshot = applied_claim.current_task
        leases = applied_claim.leases
    except (ClaimPublicationError, TaskStoreError) as exc:
        raise TerminalCloseError(exc.reason_code, exc.repair_action, exc.detail) from exc
    frontmatter = snapshot.frontmatter
    try:
        current_stage = stage_token(str(frontmatter.get("stage") or ""))
    except ValueError as exc:
        raise TerminalCloseError(
            "terminal_close_stage_invalid",
            "restore exact S10 before terminal close",
        ) from exc
    authority_case = str(frontmatter.get("authority_case") or "").strip()
    if (
        current_stage != "S10"
        or str(frontmatter.get("status") or "") not in {"claimed", "in_progress"}
        or str(frontmatter.get("assigned_to") or "").strip() != actor
        or not authority_case
        or leases[0].binding.authority_case != authority_case
    ):
        raise TerminalCloseError(
            "terminal_close_task_identity_mismatch",
            "make S10 task, lane, claim, session, and AuthorityCase agree",
        )
    try:
        expected = resolve_claim_bound_canon_position(
            leases[0].binding,
            stage_token="S10",
        )
    except (CanonEchoError, OSError, RuntimeError, ValueError) as exc:
        raise TerminalCloseError(
            getattr(exc, "reason_code", "terminal_close_echo_unavailable"),
            "repair the exact claim-bound S10 Echo before close",
            str(exc),
        ) from exc
    relays = _relay_snapshots(cache_dir, actor, session_id, task_id)
    receipt_path = acceptance_receipt_path(snapshot.path, task_id)
    receipt_bytes = receipt_path.read_bytes() if receipt_path.is_file() else None
    receipt_mode = _mode(receipt_path) if receipt_bytes is not None else None
    gate_evidence = _default_done_gate_runner(
        snapshot,
        final_status,
        pr,
        retroactive,
        debt_reason,
    )
    if snapshot.path.read_bytes() != snapshot.content:
        raise TerminalCloseError(
            "terminal_close_preflight_note_drift",
            "rerun close against one stable exact note preimage",
        )
    observed_receipt = receipt_path.read_bytes() if receipt_path.is_file() else None
    observed_receipt_mode = _mode(receipt_path) if observed_receipt is not None else None
    if observed_receipt != receipt_bytes or observed_receipt_mode != receipt_mode:
        raise TerminalCloseError(
            "terminal_close_preflight_receipt_drift",
            "rerun close against the exact acceptance receipt validated by the gates",
        )
    relay_db = relay_db or cache_dir / "relay" / "messages.db"
    try:
        rendered_payload = _render_expected_payload(expected)
        reconciliation = reconcile_canon_echo(
            relay_db,
            expected,
            rendered_payload=rendered_payload,
            now=datetime.now(UTC),
            expected_sender=actor,
            expected_session_id=session_id,
        )
    except (CanonEchoError, OSError, RuntimeError, ValueError) as exc:
        raise TerminalCloseError(
            getattr(exc, "reason_code", "terminal_close_echo_unavailable"),
            "repair the exact claim-bound S10 Echo before close",
            str(exc),
        ) from exc
    if reconciliation.action != "grounded" or reconciliation.echo_message_id is None:
        raise TerminalCloseError(
            reconciliation.reason_code,
            "supply the source-local immutable current relay projection required to ground the exact S10 Echo",
            reconciliation.action,
        )
    claim_vector = tuple(
        {
            "binding_mode": lease.binding_mode,
            "binding_path": str(lease.binding_path),
            "binding_sha256": _sha256(lease.binding_content),
            "claim_key": lease.claim_key,
            "claim_mode": lease.claim_mode,
            "claim_path": str(lease.claim_path),
            "claim_sha256": _sha256(lease.claim_content),
            "epoch_mode": lease.epoch_mode,
            "epoch_path": str(lease.epoch_path),
            "epoch_sha256": _sha256(lease.epoch_content),
        }
        for lease in leases
    )
    claim_publication_proof = (
        {
            "kind": "receipt",
            "mode": applied_claim.receipt_mode,
            "path": str(applied_claim.receipt.receipt_path),
            "sha256": _sha256(applied_claim.receipt_content),
        },
        {
            "kind": "manifest",
            "mode": applied_claim.manifest_mode,
            "path": str(applied_claim.receipt.manifest_path),
            "sha256": _sha256(applied_claim.manifest_content),
        },
    )
    relay_vector = tuple(
        {
            "relay_mode": relay.mode,
            "relay_path": str(relay.path),
            "relay_sha256": _sha256(relay.content),
        }
        for relay in relays
    )
    admission = TerminalCloseAdmission(
        task_id=task_id,
        final_status=final_status,
        actor=actor,
        session_id=session_id,
        authority_case=authority_case,
        note_path=str(snapshot.path),
        note_mode=snapshot.mode,
        note_sha256=snapshot.sha256,
        receipt_path=str(receipt_path) if receipt_bytes is not None else None,
        receipt_mode=receipt_mode,
        receipt_sha256=_sha256(receipt_bytes) if receipt_bytes is not None else None,
        claim_publication_proof=claim_publication_proof,
        claim_vector=claim_vector,
        relay_vector=relay_vector,
        position_ref=expected.position_ref,
        echo_message_id=reconciliation.echo_message_id,
        gate_evidence=gate_evidence,
    )
    admission_payload = admission.receipt_payload()
    admission_path = (
        event_log.db_path.parent
        / f"terminal-close-admission-{admission.admission_ref.rsplit(':', 1)[-1]}.json"
    )
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    postimage = snapshot.content.decode("utf-8")
    for key, value in (
        ("stage", "S11"),
        ("status", final_status),
        ("completed_at", timestamp),
        ("updated_at", timestamp),
    ):
        postimage = _frontmatter_set(postimage, key, value)
    if pr:
        postimage = _frontmatter_set(postimage, "pr", pr)
    log_line = (
        f"- {timestamp} {actor} closed as {final_status} "
        f"(S10 -> S11; admission={admission.admission_ref}).\n"
    )
    if "## Session log\n" in postimage:
        postimage = postimage.replace("## Session log\n", f"## Session log\n{log_line}", 1)
    else:
        postimage = postimage.rstrip("\n") + "\n\n## Session log\n" + log_line
    closed_note = vault_root / "closed" / snapshot.path.name
    projections: list[FileProjection] = [
        FileProjection.from_snapshot(
            admission_path,
            before=None,
            before_mode=None,
            after=admission_payload,
            after_mode=0o600,
        ),
        FileProjection.from_snapshot(
            closed_note,
            before=None,
            before_mode=None,
            after=postimage.encode("utf-8"),
            after_mode=snapshot.mode,
        ),
        FileProjection.from_snapshot(
            snapshot.path,
            before=snapshot.content,
            before_mode=snapshot.mode,
            after=None,
        ),
    ]
    if receipt_bytes is not None:
        closed_receipt = vault_root / "closed" / receipt_path.name
        projections.extend(
            [
                FileProjection.from_snapshot(
                    closed_receipt,
                    before=None,
                    before_mode=None,
                    after=receipt_bytes,
                    after_mode=receipt_mode,
                ),
                FileProjection.from_snapshot(
                    receipt_path,
                    before=receipt_bytes,
                    before_mode=receipt_mode,
                    after=None,
                ),
            ]
        )
    for lease in leases:
        for path, content, mode in (
            (lease.claim_path, lease.claim_content, lease.claim_mode),
            (lease.epoch_path, lease.epoch_content, lease.epoch_mode),
            (lease.binding_path, lease.binding_content, lease.binding_mode),
        ):
            projections.append(
                FileProjection.from_snapshot(
                    path,
                    before=content,
                    before_mode=mode,
                    after=None,
                )
            )
    projections.extend(applied_claim.proof_projections())
    for relay in relays:
        relay_document = dict(relay.document)
        relay_document.update(
            {
                "status": "idle",
                "current_claim": None,
                "task_id": None,
                "stage_token": None,
                "updated": timestamp,
                "last_task": {
                    "close_admission_ref": admission.admission_ref,
                    "disposition": final_status,
                    "stage_token": "S11",
                    "task_id": task_id,
                },
            }
        )
        projections.append(
            FileProjection.from_snapshot(
                relay.path,
                before=relay.content,
                before_mode=relay.mode,
                after=yaml.safe_dump(relay_document, sort_keys=False).encode("utf-8"),
            )
        )
    no_go = {key: frontmatter.get(key) is True for key in sorted(NO_GO_BOOLEANS)}
    intent = LifecycleTransitionIntent.create(
        task_id=task_id,
        from_stage="S10",
        to_stage="S11",
        edge_class="next",
        authority_case=authority_case,
        actor=actor,
        no_go_snapshot=no_go,
        guard_evidence={
            "closure_receipts_present": (f"receipt:{admission.admission_ref}",),
            "cc_close_ready": (f"receipt:{admission.admission_ref}",),
        },
        parent_spec=str(frontmatter.get("parent_spec") or "") or None,
        predecessor_position_ref=expected.position_ref,
        echo_receipt_ref=f"mq:{reconciliation.echo_message_id}",
        evidence_type="terminal_close_admission",
        evidence_summary=admission.admission_ref,
        origin="cc-close",
    )

    def locked_preflight() -> None:
        try:
            current_snapshot = resolve_task_note(
                vault_root,
                task_id,
                state="active",
                require_no_other_state=True,
            )
            current_leases = resolve_claim_leases(
                cache_dir,
                role=actor,
                session_id=session_id,
                task_id=task_id,
            )
        except TaskStoreError as exc:
            raise TerminalCloseError(exc.reason_code, exc.repair_action, exc.detail) from exc
        if current_snapshot != snapshot or current_leases != leases:
            raise TerminalCloseError(
                "terminal_close_locked_position_drift",
                "rerun close after task and claim identity stabilize",
            )
        if _relay_snapshots(cache_dir, actor, session_id, task_id) != relays:
            raise TerminalCloseError(
                "terminal_close_locked_relay_drift",
                "rerun close after the owning relay stabilizes",
            )
        current_receipt = receipt_path.read_bytes() if receipt_path.is_file() else None
        current_receipt_mode = _mode(receipt_path) if current_receipt is not None else None
        if current_receipt != receipt_bytes or current_receipt_mode != receipt_mode:
            raise TerminalCloseError(
                "terminal_close_locked_receipt_drift",
                "rerun the done gates against the exact current acceptance receipt",
            )
        current_expected = resolve_claim_bound_canon_position(
            leases[0].binding,
            stage_token="S10",
        )
        if current_expected != expected:
            raise TerminalCloseError(
                "terminal_close_locked_canon_position_drift",
                "reconcile and Echo the new claim-bound position before close",
            )
        require_matching_canon_echo(
            relay_db,
            expected,
            echo_message_id=reconciliation.echo_message_id,
            now=datetime.now(UTC),
            expected_sender=actor,
            expected_session_id=session_id,
        )

    return _execute_terminal_close_transition(
        event_log=event_log,
        intent=intent,
        projections=projections,
        timestamp=timestamp,
        terminal_close_admission={
            **admission.to_record(),
            "admission_ref": admission.admission_ref,
        },
        locked_preflight=locked_preflight,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m shared.sdlc_close")
    parser.add_argument("task_id")
    parser.add_argument("--status", default="done")
    parser.add_argument("--pr", default="")
    parser.add_argument("--retroactive", action="store_true")
    parser.add_argument("--debt", default=None)
    args = parser.parse_args(argv)
    actor = (
        os.environ.get("HAPAX_AGENT_ROLE")
        or os.environ.get("CODEX_ROLE")
        or os.environ.get("CLAUDE_ROLE")
        or "unknown"
    )
    session_id = os.environ.get("HAPAX_SESSION_ID", "")
    try:
        receipt = close_task(
            args.task_id,
            final_status=args.status,
            pr=args.pr,
            actor=actor,
            session_id=session_id,
            retroactive=args.retroactive,
            debt_reason=args.debt,
        )
    except (TerminalCloseError, TaskStoreError) as exc:
        print(f"cc-close: REFUSED - {exc}", file=sys.stderr)
        return 2
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"cc-close: ERROR - {exc}", file=sys.stderr)
        return 3
    print(
        f"cc-close: {args.task_id} -> S11 transaction={receipt.transaction_id}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
