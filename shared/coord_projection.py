"""Canonical coordination projection + typed event emitters.

Coordination reform Phase 4 (CASE-SDLC-REFORM-001): the daemon-owned coord event
log (``shared/coord_event_log``) is the SSOT for SDLC stage and the no-go
authorization booleans. This module is the ONLY sanctioned way to:

* emit a typed :class:`CoordEvent` for a stage transition, a no-go-boolean flip,
  an evidence append, or a migration annotation — so "a typed ledger append is
  the only way to flip a no-go boolean" (master design §4.3) is realized in code;
* fold the replayed log back into a per-task projection (stage + no-go vector)
  that vault frontmatter and dashboards are diffed against for drift.

Two emit disciplines:

* **strict** (:func:`emit_stage_transition` / :func:`emit_authorization_flip` /
  :func:`emit_stage_transition_intent`): the transition is authoritative, so the
  append must succeed. Only :class:`DuplicateEventError` is swallowed (an
  idempotent retry of the same event); every other error propagates so the caller
  ABORTS rather than leave the vault projecting state the ledger does not back.
* **best-effort** (:func:`emit_evidence_appended` / :func:`emit_migration_annotated`):
  an observability mirror that is off by default, never raises, and is
  load-bearing for no invariant.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shared.coord_event_log import (
    AppendReceipt,
    CoordEvent,
    CoordWriter,
    DuplicateEventError,
    default_event_log,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from shared.coord_event_log import CoordEventLog, ReplayResult

# --- canonical coord event types ---------------------------------------------
CANON_STAGE_TRANSITION = "sdlc.stage_transition"
CANON_AUTHZ_FLIP = "sdlc.authorization_flip"
CANON_EVIDENCE_APPENDED = "evidence.appended"
CANON_MIGRATION_ANNOTATED = "migration.annotated"

#: Opt-in env var: when set (and no event_log is injected) the best-effort
#: evidence mirror writes to the default coord log instead of no-op'ing.
EVIDENCE_MIRROR_ENV = "HAPAX_COORD_EVIDENCE_MIRROR"

#: The no-go authorization booleans a typed flip event may carry. Every consumer
#: across the stack (policy_decide, cc-task-repair, cc-task-backfill-nogo,
#: cc-stage-advance, case_migration) draws its fields from this set.
NO_GO_BOOLEANS = frozenset(
    {
        "implementation_authorized",
        "source_mutation_authorized",
        "docs_mutation_authorized",
        "runtime_mutation_authorized",
        "vault_mutation_authorized",
        "release_authorized",
        "public_current",
        "axiom_mutation_authorized",
    }
)

#: Vault cc-task store (the stage projection is diffed against its frontmatter).
DEFAULT_VAULT_TASKS = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest(*parts: object) -> str:
    payload = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()


# --- deterministic event-id builders -----------------------------------------
# Same load-bearing inputs -> same id, so an idempotent retry collapses to one
# durable event; a changed field (e.g. a different to_stage) yields a new id.
def stage_transition_event_id(
    *, task_id: str, authority_case: str | None, from_stage: str, to_stage: str, timestamp: str
) -> str:
    return f"sdlc-stage-{_digest(task_id, authority_case, from_stage, to_stage, timestamp)}"


def authorization_flip_event_id(
    *, task_id: str, field: str, old: object, new: object, timestamp: str
) -> str:
    return f"authz-flip-{_digest(task_id, field, old, new, timestamp)}"


def evidence_appended_event_id(*, evidence_id: str) -> str:
    return f"evidence-{_digest(evidence_id)}"


def migration_annotated_event_id(*, task_id: str, stage: str, risk_tier: str, decision: str) -> str:
    return f"migration-{_digest(task_id, stage, risk_tier, decision)}"


# --- strict append discipline ------------------------------------------------
def _strict_append(event_log: CoordEventLog, event: CoordEvent) -> AppendReceipt:
    """Append authoritatively. Swallow ONLY a duplicate (idempotent success)."""
    try:
        return event_log.append(event, writer=CoordWriter.daemon())
    except DuplicateEventError:
        return AppendReceipt(
            event_id=event.event_id,
            appended=True,
            spooled=False,
            sequence=None,
            db_path=event_log.db_path,
            jsonl_path=event_log.jsonl_path,
        )


def emit_stage_transition(
    *,
    event_log: CoordEventLog,
    task_id: str,
    from_stage: str,
    to_stage: str,
    authority_case: str | None,
    actor: str,
    no_go_snapshot: Mapping[str, bool],
    parent_spec: str | None = None,
    timestamp: str | None = None,
    evidence_type: str | None = None,
    evidence_summary: str | None = None,
    origin: str = "cli",
) -> AppendReceipt:
    """Record an authoritative S-stage transition in the coord SSOT log."""
    ts = timestamp or _now_iso()
    payload: dict[str, Any] = {
        "from_stage": from_stage,
        "to_stage": to_stage,
        "no_go_snapshot": dict(no_go_snapshot),
        "origin": origin,
    }
    if evidence_type is not None:
        payload["evidence_type"] = evidence_type
    if evidence_summary is not None:
        payload["evidence_summary"] = evidence_summary
    event = CoordEvent(
        event_id=stage_transition_event_id(
            task_id=task_id,
            authority_case=authority_case,
            from_stage=from_stage,
            to_stage=to_stage,
            timestamp=ts,
        ),
        timestamp=ts,
        event_type=CANON_STAGE_TRANSITION,
        actor=actor,
        subject=task_id,
        authority_case=authority_case,
        parent_spec=parent_spec,
        payload=payload,
    )
    return _strict_append(event_log, event)


def emit_authorization_flip(
    *,
    event_log: CoordEventLog,
    task_id: str,
    field: str,
    old: object,
    new: object,
    authority_case: str | None,
    actor: str,
    reason: str = "",
    timestamp: str | None = None,
) -> AppendReceipt:
    """Record an authoritative no-go-boolean flip — the keystone SSOT write."""
    if field not in NO_GO_BOOLEANS:
        raise ValueError(f"{field!r} is not a no-go boolean (one of {sorted(NO_GO_BOOLEANS)})")
    ts = timestamp or _now_iso()
    event = CoordEvent(
        event_id=authorization_flip_event_id(
            task_id=task_id, field=field, old=old, new=new, timestamp=ts
        ),
        timestamp=ts,
        event_type=CANON_AUTHZ_FLIP,
        actor=actor,
        subject=task_id,
        authority_case=authority_case,
        payload={"field": field, "old": old, "new": new, "reason": reason, "actor": actor},
    )
    return _strict_append(event_log, event)


def emit_stage_transition_intent(
    *,
    event_log: CoordEventLog,
    task_id: str,
    from_stage: str,
    to_stage: str,
    authority_case: str | None,
    actor: str,
    no_go_snapshot: Mapping[str, bool],
    timestamp: str | None = None,
    reason: str = "daemon_down",
) -> AppendReceipt:
    """Spool a stage transition for boot reconciliation (daemon-down shim path).

    The shim cannot reach the daemon to append the canonical log, so it writes a
    fail-open spool intent the daemon ingests on boot. Nothing canonical is
    written here — the receipt is ``spooled``, not ``appended``.
    """
    ts = timestamp or _now_iso()
    event = CoordEvent(
        event_id=stage_transition_event_id(
            task_id=task_id,
            authority_case=authority_case,
            from_stage=from_stage,
            to_stage=to_stage,
            timestamp=ts,
        ),
        timestamp=ts,
        event_type=CANON_STAGE_TRANSITION,
        actor=actor,
        subject=task_id,
        authority_case=authority_case,
        payload={
            "from_stage": from_stage,
            "to_stage": to_stage,
            "no_go_snapshot": dict(no_go_snapshot),
            "origin": "shim-intent",
        },
    )
    return event_log.spool_fail_open(event, writer=CoordWriter.shim(name=actor), reason=reason)


# --- best-effort observability mirrors ---------------------------------------
def emit_evidence_appended(
    entry: object, *, event_log: CoordEventLog | None = None
) -> AppendReceipt | None:
    """Mirror an evidence-ledger append into the coord log (best-effort).

    No-op unless an ``event_log`` is injected or ``HAPAX_COORD_EVIDENCE_MIRROR``
    is set; never raises (a malformed entry is silently skipped) — the evidence
    JSONL append is the authoritative surface, this mirror is observability only.
    """
    if event_log is None and not os.environ.get(EVIDENCE_MIRROR_ENV):
        return None
    try:
        log = event_log or default_event_log()
        case_id = str(entry.case_id)  # type: ignore[attr-defined]
        evidence_id = str(entry.evidence_id)  # type: ignore[attr-defined]
        event = CoordEvent(
            event_id=evidence_appended_event_id(evidence_id=evidence_id),
            timestamp=_epoch_to_iso(getattr(entry, "timestamp_utc", None)),
            event_type=CANON_EVIDENCE_APPENDED,
            actor=str(getattr(entry, "producer", "") or "evidence-ledger"),
            subject=case_id,
            authority_case=case_id if case_id.startswith("CASE-") else None,
            payload={
                "evidence_id": evidence_id,
                "kind": getattr(entry, "kind", None),
                "valence": getattr(entry, "valence", None),
                "claim": getattr(entry, "claim", None),
                "risk_tier": getattr(entry, "risk_tier", None),
            },
        )
        return _best_effort_append(log, event)
    except Exception:
        return None


def emit_migration_annotated(
    *,
    task_id: str,
    stage: str,
    risk_tier: str,
    decision: str,
    seeded_fields: list[str] | None = None,
    event_log: CoordEventLog | None = None,
) -> AppendReceipt | None:
    """Mirror a migration stub annotation into the coord log (best-effort).

    No-op unless an ``event_log`` is injected; never raises.
    """
    if event_log is None:
        return None
    try:
        event = CoordEvent(
            event_id=migration_annotated_event_id(
                task_id=task_id, stage=stage, risk_tier=risk_tier, decision=decision
            ),
            timestamp=_now_iso(),
            event_type=CANON_MIGRATION_ANNOTATED,
            actor="case-migration",
            subject=task_id,
            payload={
                "stage": stage,
                "risk_tier": risk_tier,
                "decision": decision,
                "seeded_fields": list(seeded_fields or []),
            },
        )
        return _best_effort_append(event_log, event)
    except Exception:
        return None


def _best_effort_append(event_log: CoordEventLog, event: CoordEvent) -> AppendReceipt | None:
    try:
        return event_log.append(event, writer=CoordWriter.daemon())
    except DuplicateEventError:
        return AppendReceipt(
            event_id=event.event_id,
            appended=True,
            spooled=False,
            sequence=None,
            db_path=event_log.db_path,
            jsonl_path=event_log.jsonl_path,
        )
    except Exception:
        return None


def _epoch_to_iso(value: object) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _now_iso()


# --- the projection fold -----------------------------------------------------
@dataclass
class TaskState:
    """Folded coordination state for one cc-task (subject), latest-write-wins."""

    task_id: str
    stage: str | None = None
    authority_case: str | None = None
    no_go: dict[str, bool] = field(default_factory=dict)


@dataclass
class CoordProjection:
    """The cc-task/AuthorityCase projection derived by replaying the coord log."""

    tasks: dict[str, TaskState] = field(default_factory=dict)

    @classmethod
    def from_replay(cls, replay: ReplayResult) -> CoordProjection:
        projection = cls()
        for event in replay.events:
            projection._fold(event)
        return projection

    def _fold(self, event: CoordEvent) -> None:
        if event.event_type == CANON_STAGE_TRANSITION:
            state = self.tasks.setdefault(event.subject, TaskState(task_id=event.subject))
            to_stage = event.payload.get("to_stage")
            if to_stage is not None:
                state.stage = str(to_stage)
            if event.authority_case:
                state.authority_case = event.authority_case
            snapshot = event.payload.get("no_go_snapshot")
            if isinstance(snapshot, dict):
                state.no_go.update({str(k): bool(v) for k, v in snapshot.items()})
        elif event.event_type == CANON_AUTHZ_FLIP:
            state = self.tasks.setdefault(event.subject, TaskState(task_id=event.subject))
            field_name = event.payload.get("field")
            if field_name is not None:
                state.no_go[str(field_name)] = bool(event.payload.get("new"))
            if event.authority_case:
                state.authority_case = event.authority_case


# --- projection <-> vault drift ----------------------------------------------
@dataclass(frozen=True)
class StageDrift:
    """A divergence between the ledger projection and the vault frontmatter."""

    task_id: str
    ledger_stage: str | None
    vault_stage: str | None


def diff_projection_vs_vault(
    projection: CoordProjection, vault_stages: Mapping[str, str]
) -> list[StageDrift]:
    """Return per-task stage divergences between the ledger projection and vault."""
    drifts: list[StageDrift] = []
    for task_id in sorted(set(projection.tasks) | set(vault_stages)):
        ledger_stage = projection.tasks[task_id].stage if task_id in projection.tasks else None
        vault_stage = vault_stages.get(task_id)
        if ledger_stage != vault_stage:
            drifts.append(
                StageDrift(task_id=task_id, ledger_stage=ledger_stage, vault_stage=vault_stage)
            )
    return drifts


def load_vault_task_stages(vault_tasks: Path | None = None) -> dict[str, str]:
    """Read ``task_id``/``stage`` frontmatter for every cc-task note in the vault."""
    base = vault_tasks or DEFAULT_VAULT_TASKS
    stages: dict[str, str] = {}
    for sub in ("active", "closed"):
        directory = base / sub
        if not directory.is_dir():
            continue
        for note in directory.glob("*.md"):
            task_id, stage = _read_task_id_and_stage(note)
            if task_id and stage:
                stages[task_id] = stage
    return stages


def _read_task_id_and_stage(note: Path) -> tuple[str | None, str | None]:
    try:
        lines = note.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    if not lines or lines[0].strip() != "---":
        return None, None
    task_id: str | None = None
    stage: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("task_id:"):
            task_id = _scalar(line.split(":", 1)[1])
        elif line.startswith("stage:"):
            stage = _scalar(line.split(":", 1)[1])
    return task_id, stage


def _scalar(raw: str) -> str:
    return raw.strip().strip('"').strip("'")


__all__ = [
    "CANON_AUTHZ_FLIP",
    "CANON_EVIDENCE_APPENDED",
    "CANON_MIGRATION_ANNOTATED",
    "CANON_STAGE_TRANSITION",
    "EVIDENCE_MIRROR_ENV",
    "NO_GO_BOOLEANS",
    "CoordProjection",
    "StageDrift",
    "TaskState",
    "authorization_flip_event_id",
    "diff_projection_vs_vault",
    "emit_authorization_flip",
    "emit_evidence_appended",
    "emit_migration_annotated",
    "emit_stage_transition",
    "emit_stage_transition_intent",
    "evidence_appended_event_id",
    "load_vault_task_stages",
    "migration_annotated_event_id",
    "stage_transition_event_id",
]

# CoordProjection.from_replay is consumed by scripts/coord-drift-check — an
# extensionless CLI the unused-function scanner does not parse — so reference it
# here to mark it used (mirrors shared/coord_event_log.py's _DYNAMIC_ENTRYPOINTS).
_DYNAMIC_ENTRYPOINTS = (CoordProjection.from_replay,)
