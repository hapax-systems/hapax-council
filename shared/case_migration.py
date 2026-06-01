"""CC-task to AuthorityCase migration logic.

Reads cc-task YAML frontmatter, classifies risk tier, maps status to
AuthorityCase stage, and generates stub case_id annotations for the
legacy intake converter.

ISAP: SLICE-007-MIGRATION-CLOSURE (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from shared.coord_event_log import CoordEvent, CoordWriter, DuplicateEventError, default_event_log

TransitionStage = Literal["S0", "S1", "S6", "S7", "S11"]
RiskTier = Literal["T0", "T1", "T2", "T3"]
MigrationDecision = Literal[
    "adopted",
    "adopted_with_limits",
    "quarantined",
    "retired",
    "unresolved",
]

_T3_TAGS = frozenset(
    {
        "governance",
        "axiom",
        "consent",
        "constitutional",
        "public",
        "publication",
        "monetization",
        "research-claim",
    }
)
_T2_TAGS = frozenset(
    {
        "compositor",
        "audio",
        "voice",
        "biometric",
        "privacy",
        "egress",
        "management-safety",
        "qdrant",
        "obsidian",
        "ari",
        "provider",
        "selected-release",
        "dashboard",
    }
)
_T1_TAGS = frozenset(
    {
        "interface",
        "service",
        "daemon",
        "schema",
        "cross-repo",
        "contract",
        "api",
    }
)

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)


class CcTask(BaseModel):
    """Parsed cc-task frontmatter."""

    task_id: str
    title: str = ""
    status: str = "offered"
    assigned_to: str | None = ""
    priority: str | None = ""
    wsjf: float | None = None
    depends_on: list[str] = Field(default_factory=list)
    blocks: list[str] = Field(default_factory=list)
    branch: str | None = None
    pr: int | str | None = None
    blocked_reason: str | None = None
    train: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_path: Path | None = None

    model_config = {"extra": "allow"}


class MigrationStub(BaseModel):
    """AuthorityCase annotation to add to a cc-task file."""

    case_id: str
    authority_case_stage: TransitionStage
    risk_tier: RiskTier
    migration_decision: MigrationDecision
    migration_reason: str = ""
    source_mutation_authorized: bool = False
    docs_mutation_authorized: bool = False
    vault_mutation_authorized: bool = False
    implementation_authorized: bool = False
    release_authorized: bool = False
    public_current: bool = False


def parse_cc_task(path: Path) -> CcTask | None:
    """Parse a cc-task markdown file, returning None if unparseable."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("type") != "cc-task":
        return None
    if "task_id" not in data:
        return None
    data["source_path"] = path
    try:
        return CcTask(**data)
    except Exception:
        return None


def classify_risk_tier(task: CcTask) -> RiskTier:
    """Classify risk tier from tags. Unknown signals default upward."""
    tags = frozenset(t.lower().replace("_", "-") for t in task.tags)
    if tags & _T3_TAGS:
        return "T3"
    if tags & _T2_TAGS:
        return "T2"
    if tags & _T1_TAGS:
        return "T1"
    prio = (task.priority or "").lower()
    if prio in ("p0", "critical"):
        return "T2"
    return "T0"


def map_stage(task: CcTask) -> TransitionStage:
    """Map cc-task status + implementation state to AuthorityCase stage."""
    status = task.status.lower().replace(" ", "_")
    if status in ("completed", "withdrawn"):
        return "S11"
    if status == "pr_open":
        return "S7"
    if status == "in_progress":
        return "S6"
    if status == "claimed":
        return "S6" if task.branch else "S1"
    return "S0"


def map_decision(task: CcTask) -> MigrationDecision:
    """Determine migration decision from task state."""
    status = task.status.lower().replace(" ", "_")
    if status == "withdrawn":
        return "retired"
    if status == "completed":
        return "adopted"
    if status == "blocked":
        return "quarantined"
    if status in ("in_progress", "pr_open", "claimed") and task.branch:
        return "adopted_with_limits"
    if status == "offered":
        return "unresolved"
    return "unresolved"


def generate_case_id(task: CcTask) -> str:
    """Generate a deterministic case_id from the task_id."""
    slug = task.task_id.replace("_", "-")
    return f"CASE-LEGACY-{slug}"


def generate_stub(task: CcTask) -> MigrationStub:
    """Generate a full migration stub for a cc-task."""
    stage = map_stage(task)
    decision = map_decision(task)
    tier = classify_risk_tier(task)

    reasons = {
        "adopted": "Completed pre-methodology; adopted as historical.",
        "adopted_with_limits": "Active implementation; adopted pending verification.",
        "quarantined": f"Blocked: {task.blocked_reason or 'unspecified'}.",
        "retired": "Withdrawn pre-methodology.",
        "unresolved": "Offered but not started; awaits AuthorityCase planning.",
    }

    return MigrationStub(
        case_id=generate_case_id(task),
        authority_case_stage=stage,
        risk_tier=tier,
        migration_decision=decision,
        migration_reason=reasons.get(decision, ""),
    )


def scan_tasks(task_dir: Path) -> list[CcTask]:
    """Scan a directory for cc-task markdown files."""
    tasks = []
    for p in sorted(task_dir.glob("*.md")):
        task = parse_cc_task(p)
        if task is not None:
            tasks.append(task)
    return tasks


def annotate_task_file(path: Path, stub: MigrationStub) -> str:
    """Return the task file content with case_id fields injected into frontmatter.

    Does NOT write to disk — caller decides whether to write.
    """
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"No frontmatter in {path}")

    fm_text = m.group(1)
    data = yaml.safe_load(fm_text)
    if not isinstance(data, dict):
        raise ValueError(f"Frontmatter is not a dict in {path}")

    data["case_id"] = stub.case_id
    data["authority_case_stage"] = stub.authority_case_stage
    data["risk_tier"] = stub.risk_tier
    data["migration_decision"] = stub.migration_decision
    data["migration_reason"] = stub.migration_reason

    new_fm = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{new_fm}---\n{text[m.end() :]}"


# === Coord migration capability + ledger backfill ============================
# Seeding the coord SSOT log from the legacy per-worktree authority-case ledgers
# is a mass mutation the standard gate would block. It runs under a one-time,
# operator-minted, auto-expiring capability scoped to the migration namespace
# (master design §4.3, NEW-6).

#: Namespace a migration capability must carry to authorize a coord backfill.
MIGRATION_NAMESPACE = "coord-reform-migration"


@dataclass(frozen=True)
class MigrationCapability:
    """A scoped, auto-expiring capability authorizing a coord-log backfill."""

    token: str
    grantor: str
    namespace: str
    issued_at: float
    expires_at: float

    def is_expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at

    def assert_valid(self, *, namespace: str, now: float | None = None) -> None:
        """Raise ValueError unless this capability is in-namespace and unexpired."""
        if self.namespace != namespace:
            raise ValueError(
                f"migration capability namespace {self.namespace!r} != required {namespace!r}"
            )
        if self.is_expired(now):
            raise ValueError("migration capability expired")


def mint_capability(
    *, grantor: str, namespace: str = MIGRATION_NAMESPACE, ttl_seconds: float = 3600.0
) -> MigrationCapability:
    """Mint a one-time backfill capability (default 1h TTL)."""
    issued = time.time()
    token = hashlib.blake2b(
        f"{grantor}\x1f{namespace}\x1f{issued}".encode(), digest_size=16
    ).hexdigest()
    return MigrationCapability(
        token=token,
        grantor=grantor,
        namespace=namespace,
        issued_at=issued,
        expires_at=issued + ttl_seconds,
    )


def backfill_from_ledger(
    ledger_path: Path,
    *,
    capability: MigrationCapability,
    event_log: CoordEventLog | None = None,
) -> int:
    """Append every legacy ledger row into the coord SSOT log under ``capability``.

    Each JSONL row becomes one ``legacy.<kind>`` :class:`CoordEvent`. The event id
    is a digest of the row content (path-independent), so identical rows that
    accumulated across several per-worktree ledgers collapse to one event and a
    re-run is idempotent. Returns the count of newly appended events.
    """
    capability.assert_valid(namespace=MIGRATION_NAMESPACE)
    if not ledger_path.exists():
        return 0
    log = event_log or default_event_log()
    appended = 0
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        try:
            log.append(_legacy_row_to_event(row), writer=CoordWriter.daemon())
            appended += 1
        except DuplicateEventError:
            continue  # idempotent: row already migrated
    return appended


def _legacy_row_to_event(row: dict) -> CoordEvent:
    kind = str(row.get("kind") or "event")
    subject = str(
        row.get("task_id") or row.get("case_id") or row.get("authority_case") or "unknown"
    )
    authority_case = row.get("authority_case")
    return CoordEvent(
        event_id=f"legacy-{_row_digest(row)}",
        timestamp=str(row.get("ts") or row.get("timestamp") or _now_iso()),
        event_type=f"legacy.{kind}",
        actor=str(row.get("role") or row.get("actor") or "migration"),
        subject=subject,
        authority_case=authority_case if isinstance(authority_case, str) else None,
        payload={"kind": kind, "row": row},
    )


def _row_digest(row: dict) -> str:
    canonical = json.dumps(row, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.blake2b(canonical.encode("utf-8"), digest_size=8).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# Consumed by scripts/coord-migrate-ledgers — an extensionless CLI the
# unused-function scanner does not parse — so reference them here to mark them
# used (mirrors shared/coord_event_log.py's _DYNAMIC_ENTRYPOINTS pattern).
_DYNAMIC_ENTRYPOINTS = (mint_capability, backfill_from_ledger)
