"""Evidence ledger, trace graph, and receipt envelopes for Authority-Case SDLC.

Append-only evidence ledger with per-tier completeness enforcement.
Trace graph links requirements/axioms to PRs/tests/readbacks/runtime.

ISAP: SLICE-005-EVIDENCE-TRACE (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, ValidationError

if TYPE_CHECKING:
    from shared.coord_event_log import CoordEventLog

LEDGER_DIR = Path.home() / ".cache" / "hapax" / "evidence-ledger"
DEFAULT_LEDGER_MAX_BYTES = 16 * 1024 * 1024
DEFAULT_LEDGER_KEEP_GENERATIONS = 4

RiskTier = Literal["T0", "T1", "T2", "T3"]
EvidenceKind = Literal[
    "test",
    "ci",
    "review",
    "receipt",
    "readback",
    "screenshot",
    "log",
    "runtime_observation",
    "manual_inspection",
    "axiom_scan",
    "assurance_argument",
]
EvidenceValence = Literal["positive", "negative", "context", "defeater"]
TransitionStage = Literal["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11"]
LegibilityEvidenceKind = Literal[
    "command",
    "public_url",
    "package_registry",
    "local_api",
    "systemd_inventory",
    "operator_decision",
    "external_determination",
    "collection_failure",
]
LegibilityPrivacyClass = Literal[
    "public",
    "public_registry",
    "local_private",
    "operator_private",
    "employer_private",
    "redacted_cross_boundary",
]
LegibilityConfidence = Literal["high", "medium", "low"]
LegibilityFailureBehavior = Literal["fail_closed", "record_failure"]
LegibilityEvidenceStatus = Literal["ok", "failed"]
AudienceId = Literal[
    "operator",
    "worker_lane",
    "enterprise_testbed",
    "public_adopter",
    "paid_buyer",
    "security_legal_reviewer",
    "intellectual_audience",
]
ClaimKind = Literal[
    "current_state",
    "capability",
    "architecture",
    "license",
    "adoption",
    "risk",
    "roadmap",
    "boundary",
]
ClaimStatus = Literal[
    "proposed",
    "approved_internal",
    "approved_public",
    "rejected",
    "expired",
]
ClaimEvidenceStatus = Literal["fresh", "stale", "missing", "contradictory"]
DeterminationExchangePacketType = Literal["determination", "observation"]
DeterminationExchangeSystem = Literal["hapax", "alliant_sandbox", "external_enterprise"]
DeterminationExchangeAuthorityLevel = Literal[
    "informational",
    "planning_authority",
    "implementation_authority",
]
DeterminationExchangeImportMode = Literal["none", "external_evidence", "implementation_authority"]
DeterminationExchangeReviewVerdict = Literal[
    "approved",
    "rejected",
    "needs_counsel",
    "expired",
    "needs_alliant_review",
]


class EvidenceEntry(BaseModel):
    """A single piece of evidence in the ledger."""

    evidence_id: str
    case_id: str
    kind: EvidenceKind
    valence: EvidenceValence = "positive"
    claim: str = Field(description="What this evidence supports or defeats")
    path_or_url: str = ""
    commit: str = ""
    timestamp_utc: float = Field(default_factory=time.time)
    producer: str = Field(description="Session/script that produced this")
    freshness_ttl_s: float = Field(
        default=86400.0, description="Evidence considered stale after this many seconds"
    )
    risk_tier: RiskTier = "T0"
    traces_to: list[str] = Field(
        default_factory=list,
        description="REQ-*, NEED-*, HAZ-*, V-* IDs this evidence traces to",
    )
    limitations: str = ""

    def is_fresh(self, now: float | None = None) -> bool:
        ts = now if now is not None else time.time()
        return (ts - self.timestamp_utc) <= self.freshness_ttl_s


class ReceiptEnvelope(BaseModel):
    """Structured receipt wrapping a verification or readback result."""

    receipt_id: str
    case_id: str
    stage: TransitionStage
    action: str = Field(description="What was done: test, deploy, readback, etc.")
    outcome: Literal["pass", "fail", "inconclusive", "skipped"]
    evidence_ids: list[str] = Field(default_factory=list, description="EvidenceEntry IDs produced")
    timestamp_utc: float = Field(default_factory=time.time)
    producer: str = ""
    artifact_hash: str = ""
    notes: str = ""


class TraceLink(BaseModel):
    """A single link in the trace graph: requirement → evidence."""

    source_id: str = Field(description="REQ-*, NEED-*, HAZ-*, AXIOM-*")
    target_id: str = Field(description="EVD-*, V-*, PR-*, TEST-*")
    link_type: Literal["satisfies", "verifies", "mitigates", "defeats", "traces_to"] = "traces_to"
    case_id: str = ""


def _generation_path(path: Path, generation: int) -> Path:
    return path.with_name(f"{path.name}.{generation}")


def _retained_jsonl_paths(path: Path, keep_generations: int) -> list[Path]:
    return [
        *(_generation_path(path, generation) for generation in range(keep_generations, 0, -1)),
        path,
    ]


def _maybe_rotate_jsonl(path: Path, *, max_bytes: int, keep_generations: int) -> None:
    if max_bytes <= 0 or keep_generations <= 0:
        return
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return
    if size < max_bytes:
        return

    _generation_path(path, keep_generations).unlink(missing_ok=True)
    for generation in range(keep_generations - 1, 0, -1):
        source = _generation_path(path, generation)
        if source.exists():
            source.replace(_generation_path(path, generation + 1))
    path.replace(_generation_path(path, 1))


def _append_rotated_jsonl(
    path: Path,
    line: str,
    *,
    max_bytes: int,
    keep_generations: int,
) -> None:
    _maybe_rotate_jsonl(path, max_bytes=max_bytes, keep_generations=keep_generations)
    # jsonl-rotation: exempt(domain rotation; readers scan retained generations)
    with path.open("a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def _read_retained_jsonl_lines(path: Path, *, keep_generations: int) -> list[str]:
    lines: list[str] = []
    for retained_path in _retained_jsonl_paths(path, keep_generations):
        try:
            lines.extend(retained_path.read_text(encoding="utf-8").splitlines())
        except FileNotFoundError:
            continue
    return lines


# T0-T3 minimum evidence requirements per the methodology addendum
TIER_REQUIREMENTS: dict[RiskTier, set[EvidenceKind]] = {
    "T0": {"test", "ci"},
    "T1": {"test", "ci", "readback"},
    "T2": {"test", "ci", "readback", "review", "axiom_scan"},
    "T3": {"test", "ci", "readback", "review", "axiom_scan", "assurance_argument"},
}


class EvidenceLedger:
    """Append-only file-backed evidence ledger.

    The per-case JSONL files remain the authoritative tier-compliance read
    surface. When a coordination ``event_log`` is injected (or
    ``HAPAX_COORD_EVIDENCE_MIRROR=1``), each append is ALSO mirrored as a
    best-effort ``evidence.appended`` event into the coord SSOT log for
    observability — off by default, never raises, load-bearing for no invariant
    (coordination reform Phase 4).
    """

    def __init__(
        self,
        ledger_dir: Path | None = None,
        *,
        event_log: CoordEventLog | None = None,
        max_bytes: int = DEFAULT_LEDGER_MAX_BYTES,
        keep_generations: int = DEFAULT_LEDGER_KEEP_GENERATIONS,
    ) -> None:
        self._dir = ledger_dir or LEDGER_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._event_log = event_log
        self._max_bytes = max_bytes
        self._keep_generations = keep_generations

    def _case_file(self, case_id: str) -> Path:
        safe = case_id.replace("/", "_").replace(" ", "_")
        return self._dir / f"{safe}.jsonl"

    def append(self, entry: EvidenceEntry) -> None:
        path = self._case_file(entry.case_id)
        # jsonl-rotation: exempt(domain rotation; entries_for_case scans retained generations)
        _append_rotated_jsonl(
            path,
            entry.model_dump_json(),
            max_bytes=self._max_bytes,
            keep_generations=self._keep_generations,
        )
        # Best-effort, off-by-default observability mirror into the coord SSOT log.
        # Lazy import avoids a module-level cycle (coord_projection type-checks
        # against EvidenceEntry). No-op unless an event_log is injected or
        # HAPAX_COORD_EVIDENCE_MIRROR=1; never raises.
        try:
            from shared.coord_projection import emit_evidence_appended

            emit_evidence_appended(entry, event_log=self._event_log)
        except Exception:  # noqa: BLE001 — the mirror must never break an append.
            pass

    def entries_for_case(self, case_id: str) -> list[EvidenceEntry]:
        path = self._case_file(case_id)
        entries = []
        for line in _read_retained_jsonl_lines(path, keep_generations=self._keep_generations):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(EvidenceEntry.model_validate_json(line))
            except Exception:
                continue
        return entries

    def fresh_entries(self, case_id: str, now: float | None = None) -> list[EvidenceEntry]:
        return [e for e in self.entries_for_case(case_id) if e.is_fresh(now)]

    def stale_entries(self, case_id: str, now: float | None = None) -> list[EvidenceEntry]:
        return [e for e in self.entries_for_case(case_id) if not e.is_fresh(now)]

    def append_receipt(self, receipt: ReceiptEnvelope) -> None:
        path = self._dir / "receipts.jsonl"
        # jsonl-rotation: exempt(domain rotation; receipts_for_case scans retained generations)
        _append_rotated_jsonl(
            path,
            receipt.model_dump_json(),
            max_bytes=self._max_bytes,
            keep_generations=self._keep_generations,
        )

    def receipts_for_case(self, case_id: str) -> list[ReceiptEnvelope]:
        path = self._dir / "receipts.jsonl"
        receipts = []
        for line in _read_retained_jsonl_lines(path, keep_generations=self._keep_generations):
            line = line.strip()
            if not line:
                continue
            try:
                r = ReceiptEnvelope.model_validate_json(line)
                if r.case_id == case_id:
                    receipts.append(r)
            except Exception:
                continue
        return receipts


class TraceGraph:
    """Trace graph linking requirements to evidence."""

    def __init__(
        self,
        ledger_dir: Path | None = None,
        *,
        max_bytes: int = DEFAULT_LEDGER_MAX_BYTES,
        keep_generations: int = DEFAULT_LEDGER_KEEP_GENERATIONS,
    ) -> None:
        self._dir = ledger_dir or LEDGER_DIR
        self._path = self._dir / "trace-graph.jsonl"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._keep_generations = keep_generations

    def add_link(self, link: TraceLink) -> None:
        # jsonl-rotation: exempt(domain rotation; all_links scans retained generations)
        _append_rotated_jsonl(
            self._path,
            link.model_dump_json(),
            max_bytes=self._max_bytes,
            keep_generations=self._keep_generations,
        )

    def all_links(self) -> list[TraceLink]:
        links = []
        for line in _read_retained_jsonl_lines(self._path, keep_generations=self._keep_generations):
            line = line.strip()
            if not line:
                continue
            try:
                links.append(TraceLink.model_validate_json(line))
            except Exception:
                continue
        return links

    def links_from(self, source_id: str) -> list[TraceLink]:
        return [lk for lk in self.all_links() if lk.source_id == source_id]

    def links_to(self, target_id: str) -> list[TraceLink]:
        return [lk for lk in self.all_links() if lk.target_id == target_id]

    def unlinked_requirements(self, requirement_ids: list[str]) -> list[str]:
        linked = {lk.source_id for lk in self.all_links()}
        return [r for r in requirement_ids if r not in linked]


class TierComplianceResult(BaseModel):
    """Result of checking evidence completeness against a risk tier."""

    case_id: str
    risk_tier: RiskTier
    required_kinds: set[EvidenceKind]
    present_kinds: set[EvidenceKind]
    missing_kinds: set[EvidenceKind]
    stale_count: int = 0
    compliant: bool


def check_tier_compliance(
    case_id: str,
    risk_tier: RiskTier,
    ledger: EvidenceLedger | None = None,
    now: float | None = None,
) -> TierComplianceResult:
    """Validate that a case has the minimum evidence for its risk tier."""
    led = ledger or EvidenceLedger()
    required = TIER_REQUIREMENTS.get(risk_tier, set())
    entries = led.entries_for_case(case_id)
    fresh = [e for e in entries if e.is_fresh(now)]
    stale = [e for e in entries if not e.is_fresh(now)]
    present: set[EvidenceKind] = {e.kind for e in fresh}
    missing = required - present
    return TierComplianceResult(
        case_id=case_id,
        risk_tier=risk_tier,
        required_kinds=required,
        present_kinds=present,
        missing_kinds=missing,
        stale_count=len(stale),
        compliant=len(missing) == 0,
    )


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bounded(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 15].rstrip() + "...[truncated]"


_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|credential)\b\s*([:=])\s*([^\s,;]+)"
)
_PRIVATE_SENTINEL_RE = re.compile(r"PRIVATE_SENTINEL_DO_NOT_PUBLISH_[A-Za-z0-9_:-]+")


def redact_secret_text(text: str) -> tuple[str, bool]:
    """Redact obvious secret-bearing text before writing evidence receipts."""

    redacted = _SECRET_ASSIGNMENT_RE.sub(r"\1\2[REDACTED]", text)
    redacted = _PRIVATE_SENTINEL_RE.sub("PRIVATE_SENTINEL_[REDACTED]", redacted)
    return redacted, redacted != text


def _evidence_id(kind: str, source: str, collected_at: str) -> str:
    import hashlib

    digest = hashlib.sha256(f"{kind}\0{source}\0{collected_at}".encode()).hexdigest()[:10]
    stamp = collected_at.replace("-", "").replace(":", "").removesuffix("Z")
    return f"EV-{stamp}-{digest}"


class LegibilityEvidenceRecord(BaseModel):
    """A current-state receipt for legibility and canonical-claim gates."""

    evidence_id: str
    kind: LegibilityEvidenceKind
    collected_at: str = Field(default_factory=_now_iso)
    collected_at_epoch: float = Field(default_factory=time.time)
    collector: str = "hapax-evidence"
    source_command: str = ""
    source_url: str = ""
    repo: str = ""
    path: str = ""
    value_summary: str = ""
    raw_artifact_ref: str = ""
    confidence: LegibilityConfidence = "high"
    freshness_ttl_s: float = 3600.0
    privacy_class: LegibilityPrivacyClass = "local_private"
    public_safe: bool = False
    redaction_notes: str = ""
    failure_behavior: LegibilityFailureBehavior = "fail_closed"
    derived_from: list[str] = Field(default_factory=list)
    status: LegibilityEvidenceStatus = "ok"
    error: str = ""

    def is_fresh(self, now: float | None = None) -> bool:
        ts = now if now is not None else time.time()
        return (ts - self.collected_at_epoch) <= self.freshness_ttl_s

    def to_evidence_entry(
        self,
        *,
        case_id: str,
        producer: str | None = None,
        risk_tier: RiskTier = "T1",
        traces_to: list[str] | None = None,
    ) -> EvidenceEntry:
        valence: EvidenceValence = "positive" if self.status == "ok" else "defeater"
        claim = self.value_summary if self.status == "ok" else self.error or self.value_summary
        path_or_url = self.source_url or self.path or self.source_command
        return EvidenceEntry(
            evidence_id=self.evidence_id,
            case_id=case_id,
            kind="runtime_observation",
            valence=valence,
            claim=claim,
            path_or_url=path_or_url,
            timestamp_utc=self.collected_at_epoch,
            producer=producer or self.collector,
            freshness_ttl_s=self.freshness_ttl_s,
            risk_tier=risk_tier,
            traces_to=traces_to or [],
            limitations=(
                f"legibility_kind={self.kind}; privacy_class={self.privacy_class}; "
                f"public_safe={self.public_safe}; redaction={self.redaction_notes or 'none'}"
            ),
        )


class LegibilityEvidenceRegistry:
    """Append-only JSONL registry for legibility EvidenceRecord receipts."""

    def __init__(
        self,
        ledger_dir: Path | None = None,
        *,
        max_bytes: int = DEFAULT_LEDGER_MAX_BYTES,
        keep_generations: int = DEFAULT_LEDGER_KEEP_GENERATIONS,
    ) -> None:
        self._dir = ledger_dir or LEDGER_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "legibility-records.jsonl"
        self._max_bytes = max_bytes
        self._keep_generations = keep_generations

    def append(
        self,
        record: LegibilityEvidenceRecord,
        *,
        mirror_case_id: str | None = None,
        traces_to: list[str] | None = None,
    ) -> None:
        # jsonl-rotation: exempt(domain rotation; all_records scans retained generations)
        _append_rotated_jsonl(
            self._path,
            record.model_dump_json(),
            max_bytes=self._max_bytes,
            keep_generations=self._keep_generations,
        )
        if mirror_case_id:
            EvidenceLedger(
                self._dir,
                max_bytes=self._max_bytes,
                keep_generations=self._keep_generations,
            ).append(record.to_evidence_entry(case_id=mirror_case_id, traces_to=traces_to))

    def all_records(self) -> list[LegibilityEvidenceRecord]:
        records: list[LegibilityEvidenceRecord] = []
        for line in _read_retained_jsonl_lines(self._path, keep_generations=self._keep_generations):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(LegibilityEvidenceRecord.model_validate_json(line))
            except Exception:
                continue
        return records

    def fresh_records(self, now: float | None = None) -> list[LegibilityEvidenceRecord]:
        return [record for record in self.all_records() if record.is_fresh(now)]

    def stale_records(self, now: float | None = None) -> list[LegibilityEvidenceRecord]:
        return [record for record in self.all_records() if not record.is_fresh(now)]


class ClaimRecord(BaseModel):
    """A bounded claim that can be rendered only for compatible audiences."""

    claim_id: str
    text: str
    claim_kind: ClaimKind
    audience_scope: list[AudienceId] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    freshness_policy: str = ""
    allowed_surfaces: list[str] = Field(default_factory=list)
    prohibited_surfaces: list[str] = Field(default_factory=list)
    allowed_wording: str = ""
    forbidden_wording: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    owner: str = "operator"
    status: ClaimStatus = "proposed"


class AudienceProfile(BaseModel):
    """Audience-specific claim posture and inference boundary."""

    audience_id: AudienceId
    name: str
    current_knowledge: str = ""
    primary_questions: list[str] = Field(default_factory=list)
    needed_decisions: list[str] = Field(default_factory=list)
    allowed_claim_classes: list[ClaimKind] = Field(default_factory=list)
    forbidden_inferences: list[str] = Field(default_factory=list)
    required_evidence_bundle: list[str] = Field(default_factory=list)
    primary_surfaces: list[str] = Field(default_factory=list)
    public_surface: bool = False
    enterprise_context: bool = False
    allow_private_evidence: bool = False
    allow_public_claims: bool = False


class ClaimValidationResult(BaseModel):
    """Fail-closed verdict for rendering a claim to its requested audiences."""

    claim_id: str
    allowed: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_status: ClaimEvidenceStatus
    evidence_ids: list[str] = Field(default_factory=list)
    audience_ids: list[str] = Field(default_factory=list)


class DeterminationExchangePacket(BaseModel):
    """Sanitized, manual cross-system determination/observation packet."""

    packet_id: str
    packet_type: DeterminationExchangePacketType
    schema_version: int = 1
    from_system: DeterminationExchangeSystem
    to_system: DeterminationExchangeSystem
    created_at: str = Field(default_factory=_now_iso)
    reviewer: str
    reviewed_at: str
    review_verdict: DeterminationExchangeReviewVerdict
    purpose: str
    authority_case: str
    authority_level: DeterminationExchangeAuthorityLevel = "informational"
    privacy_class: Literal["redacted_cross_boundary"] = "redacted_cross_boundary"
    import_as: DeterminationExchangeImportMode = "none"
    claim_refs: list[str] = Field(default_factory=list)
    evidence_summaries: list[str] = Field(default_factory=list)
    request_refs: list[str] = Field(default_factory=list)
    task_refs: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    prohibited_actions: list[str] = Field(default_factory=list)
    contains_raw_source: bool = False
    contains_raw_logs: bool = False
    contains_secrets: bool = False
    contains_employer_confidential_data: bool = False
    contains_private_runtime_state: bool = False
    contains_personal_data: bool = False
    public_safe: bool = False
    synthetic_example: bool = False
    shares_api: bool = False
    shares_database: bool = False
    shares_token: bool = False
    unattended_sync: bool = False
    live_bridge: bool = False
    summary: str


class DeterminationExchangeValidationResult(BaseModel):
    """Fail-closed verdict for a determination exchange packet."""

    packet_id: str = ""
    allowed: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    packet_type: str = ""
    import_as: str = ""


_DETERMINATION_REDACTION_FLAGS = {
    "contains_raw_source": "raw_source_present",
    "contains_raw_logs": "raw_logs_present",
    "contains_secrets": "secrets_present",
    "contains_employer_confidential_data": "employer_confidential_data_present",
    "contains_private_runtime_state": "private_runtime_state_present",
    "contains_personal_data": "personal_data_present",
}
_DETERMINATION_BRIDGE_FLAGS = {
    "shares_api": "live_bridge_shared_api",
    "shares_database": "live_bridge_shared_database",
    "shares_token": "live_bridge_shared_token",
    "unattended_sync": "live_bridge_unattended_sync",
    "live_bridge": "live_bridge_enabled",
}


def _schema_error_blockers(exc: ValidationError) -> list[str]:
    blockers: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", ())) or "packet"
        blockers.append(f"schema_error:{loc}:{error.get('msg', 'invalid')}")
    return blockers


def _packet_text_for_sensitive_scan(packet: DeterminationExchangePacket) -> str:
    return " ".join(
        [
            packet.purpose,
            packet.summary,
            " ".join(packet.evidence_summaries),
            " ".join(packet.allowed_actions),
            " ".join(packet.prohibited_actions),
        ]
    )


_DETERMINATION_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_sentinel", re.compile(r"PRIVATE_SENTINEL_DO_NOT_PUBLISH_", re.IGNORECASE)),
    ("secret_assignment", _SECRET_ASSIGNMENT_RE),
    ("private_key", re.compile(r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY", re.IGNORECASE)),
    (
        "employer_ticket_or_customer_detail",
        re.compile(
            r"\b(ticket|incident|customer|employee)\b.{0,60}\b[A-Z]{2,}-\d+\b",
            re.IGNORECASE,
        ),
    ),
)


def validate_determination_exchange_packet(
    packet: DeterminationExchangePacket | Mapping[str, object],
) -> DeterminationExchangeValidationResult:
    """Validate a manual cross-boundary packet without creating a bridge.

    Packets are informational by default. Alliant-origin packets may enter
    Hapax only as ``external_evidence``; raw source/logs/secrets/private runtime
    state, employer confidential material, and live integration flags all
    fail closed.
    """

    raw_packet_id = ""
    if isinstance(packet, Mapping):
        raw_packet_id = str(packet.get("packet_id", ""))
    try:
        model = (
            packet
            if isinstance(packet, DeterminationExchangePacket)
            else DeterminationExchangePacket.model_validate(packet)
        )
    except ValidationError as exc:
        return DeterminationExchangeValidationResult(
            packet_id=raw_packet_id,
            allowed=False,
            blockers=_schema_error_blockers(exc),
        )

    blockers: list[str] = []
    warnings: list[str] = []
    if model.schema_version != 1:
        blockers.append(f"unsupported_schema_version:{model.schema_version}")
    if not model.reviewer.strip():
        blockers.append("missing_reviewer")
    if not model.reviewed_at.strip():
        blockers.append("missing_reviewed_at")
    if model.review_verdict != "approved":
        blockers.append(f"review_verdict_not_approved:{model.review_verdict}")
    if not model.allowed_actions:
        blockers.append("missing_allowed_actions")
    if not model.prohibited_actions:
        blockers.append("missing_prohibited_actions")
    if model.privacy_class != "redacted_cross_boundary":
        blockers.append(f"invalid_privacy_class:{model.privacy_class}")
    for field_name, blocker in _DETERMINATION_REDACTION_FLAGS.items():
        if bool(getattr(model, field_name)):
            blockers.append(blocker)
    for field_name, blocker in _DETERMINATION_BRIDGE_FLAGS.items():
        if bool(getattr(model, field_name)):
            blockers.append(blocker)
    for blocker, pattern in _DETERMINATION_SENSITIVE_PATTERNS:
        if pattern.search(_packet_text_for_sensitive_scan(model)):
            blockers.append(f"sensitive_text:{blocker}")

    if model.synthetic_example and not model.public_safe:
        blockers.append("synthetic_example_not_public_safe")
    if model.from_system == "alliant_sandbox" and model.to_system == "hapax":
        if model.import_as != "external_evidence":
            blockers.append("alliant_origin_must_import_as_external_evidence")
        if model.authority_level != "informational":
            blockers.append("alliant_origin_must_be_informational")
        if "import_as_external_evidence" not in model.allowed_actions:
            blockers.append("alliant_origin_missing_external_evidence_action")
    if model.authority_level == "implementation_authority" and model.from_system != "hapax":
        blockers.append("external_system_cannot_grant_implementation_authority")

    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    return DeterminationExchangeValidationResult(
        packet_id=model.packet_id,
        allowed=not blockers,
        blockers=blockers,
        warnings=warnings,
        packet_type=model.packet_type,
        import_as=model.import_as,
    )


def determination_exchange_packet_to_external_evidence(
    packet: DeterminationExchangePacket,
    *,
    freshness_ttl_s: float = 86400.0,
) -> LegibilityEvidenceRecord:
    """Convert an approved Alliant-origin packet into external evidence only."""

    result = validate_determination_exchange_packet(packet)
    if not result.allowed:
        raise ValueError("; ".join(result.blockers))
    if packet.from_system != "alliant_sandbox" or packet.to_system != "hapax":
        raise ValueError("only Alliant-origin inbound packets convert to external evidence")
    if packet.import_as != "external_evidence":
        raise ValueError("packet import mode is not external_evidence")
    return _record(
        kind="external_determination",
        value_summary=f"{packet.packet_id}: {packet.summary}",
        privacy_class="redacted_cross_boundary",
        public_safe=packet.public_safe,
        freshness_ttl_s=freshness_ttl_s,
        collector="hapax-determination-exchange",
        failure_behavior="fail_closed",
    ).model_copy(update={"derived_from": [packet.packet_id]})


def synthetic_outbound_determination_packet() -> DeterminationExchangePacket:
    """Return a public-safe Hapax-to-enterprise example packet."""

    return DeterminationExchangePacket(
        packet_id="DXP-SYNTH-OUTBOUND-1",
        packet_type="determination",
        from_system="hapax",
        to_system="alliant_sandbox",
        reviewer="operator",
        reviewed_at="2026-06-11T00:00:00Z",
        review_verdict="approved",
        purpose="Synthetic pilot-scope determination exchange example.",
        authority_case="CASE-HAPAX-LEGIBILITY-IMPLEMENTATION-20260611",
        authority_level="informational",
        import_as="none",
        evidence_summaries=["Synthetic public-safe summary; no raw artifacts."],
        allowed_actions=["review", "map_to_local_sdlc"],
        prohibited_actions=[
            "publish_without_operator_review",
            "treat_as_employer_approval",
            "ingest_raw_private_artifacts",
        ],
        public_safe=True,
        synthetic_example=True,
        summary="Synthetic determination: review a portable governance idea without importing private runtime state.",
    )


def synthetic_inbound_observation_packet() -> DeterminationExchangePacket:
    """Return a public-safe enterprise-to-Hapax sanitized observation example."""

    return DeterminationExchangePacket(
        packet_id="DXP-SYNTH-INBOUND-1",
        packet_type="observation",
        from_system="alliant_sandbox",
        to_system="hapax",
        reviewer="operator",
        reviewed_at="2026-06-11T00:00:00Z",
        review_verdict="approved",
        purpose="Synthetic sanitized observation import example.",
        authority_case="CASE-HAPAX-LEGIBILITY-IMPLEMENTATION-20260611",
        authority_level="informational",
        import_as="external_evidence",
        evidence_summaries=["Synthetic observation: teams need concise evidence packets."],
        allowed_actions=["import_as_external_evidence", "inform_generic_public_tooling"],
        prohibited_actions=[
            "reconstruct_enterprise_workflow",
            "claim_employer_approval",
            "publish_as_current_state",
        ],
        public_safe=True,
        synthetic_example=True,
        summary="Synthetic observation: generic adoption workflows benefit from explicit evidence packets.",
    )


def default_audience_profiles() -> dict[AudienceId, AudienceProfile]:
    """Return the initial legibility audience registry."""

    return {
        "operator": AudienceProfile(
            audience_id="operator",
            name="Operator truth/control surface",
            current_knowledge="Full local context and authority over Hapax boundaries.",
            primary_questions=["What is true now?", "What changed?", "What is safe to publish?"],
            needed_decisions=["continue", "repair", "publish_or_hold"],
            allowed_claim_classes=[
                "current_state",
                "capability",
                "architecture",
                "license",
                "adoption",
                "risk",
                "roadmap",
                "boundary",
            ],
            required_evidence_bundle=["fresh evidence for current-state claims"],
            primary_surfaces=["internal_snapshot", "operator_dashboard"],
            allow_private_evidence=True,
        ),
        "worker_lane": AudienceProfile(
            audience_id="worker_lane",
            name="Governed worker lane",
            current_knowledge="Receives task-scoped context and must not infer outside evidence.",
            primary_questions=["What can I change?", "What evidence is authoritative?"],
            needed_decisions=["implement", "block", "request_review"],
            allowed_claim_classes=[
                "current_state",
                "capability",
                "architecture",
                "risk",
                "roadmap",
            ],
            forbidden_inferences=["operator intent beyond task", "private state transferability"],
            required_evidence_bundle=["task authority", "fresh local evidence"],
            primary_surfaces=["cc_task", "dispatch_packet"],
            allow_private_evidence=True,
        ),
        "enterprise_testbed": AudienceProfile(
            audience_id="enterprise_testbed",
            name="Trusted workplace testbed",
            current_knowledge=(
                "Knows the operator and workplace need; does not know private Hapax internals."
            ),
            primary_questions=[
                "What can safely be piloted?",
                "What must not cross the boundary?",
                "What support does the operator provide?",
            ],
            needed_decisions=["pilot_or_not", "scope_boundary", "support_model"],
            allowed_claim_classes=[
                "adoption",
                "license",
                "boundary",
                "roadmap",
                "risk",
                "capability",
            ],
            forbidden_inferences=[
                "employer endorsement",
                "production readiness without pilot evidence",
                "transferability of private Hapax runtime state",
            ],
            required_evidence_bundle=[
                "license/provenance",
                "security posture",
                "redaction boundary",
                "support expectation",
            ],
            primary_surfaces=["enterprise_pilot_packet", "determination_exchange_packet"],
            enterprise_context=True,
            allow_public_claims=False,
        ),
        "public_adopter": AudienceProfile(
            audience_id="public_adopter",
            name="Free/open adopter",
            current_knowledge="Has no private Hapax runtime context.",
            primary_questions=["What can I use?", "What license applies?", "What is unsupported?"],
            needed_decisions=["adopt", "fork", "ignore"],
            allowed_claim_classes=["capability", "architecture", "license", "risk", "roadmap"],
            forbidden_inferences=["private runtime equivalence", "operator support entitlement"],
            required_evidence_bundle=["public-safe evidence", "license/provenance"],
            primary_surfaces=["repo_readme", "public_homepage"],
            public_surface=True,
            allow_public_claims=True,
        ),
        "paid_buyer": AudienceProfile(
            audience_id="paid_buyer",
            name="Paid buyer or support customer",
            current_knowledge="Needs commercial support boundaries without private runtime leakage.",
            primary_questions=[
                "What is included?",
                "What evidence supports it?",
                "What are the risks?",
            ],
            needed_decisions=["buy", "defer", "request_support_scope"],
            allowed_claim_classes=["capability", "license", "risk", "roadmap", "boundary"],
            forbidden_inferences=["guaranteed outcome", "private runtime equivalence"],
            required_evidence_bundle=[
                "public-safe evidence",
                "support boundary",
                "risk disclosure",
            ],
            primary_surfaces=["sales_packet", "support_scope"],
            public_surface=True,
            allow_public_claims=True,
        ),
        "security_legal_reviewer": AudienceProfile(
            audience_id="security_legal_reviewer",
            name="Security and legal reviewer",
            current_knowledge="Reviews provenance, privacy, boundary, and supply-chain posture.",
            primary_questions=[
                "What data crosses?",
                "What license applies?",
                "What can be audited?",
            ],
            needed_decisions=["approve", "reject", "request_controls"],
            allowed_claim_classes=["architecture", "license", "risk", "boundary"],
            forbidden_inferences=["unreviewed compliance", "undisclosed data transfer"],
            required_evidence_bundle=[
                "license/provenance",
                "privacy boundary",
                "supply-chain posture",
            ],
            primary_surfaces=["security_legal_packet"],
            allow_public_claims=True,
        ),
        "intellectual_audience": AudienceProfile(
            audience_id="intellectual_audience",
            name="Intellectual and theory audience",
            current_knowledge="Interested in ideas and research posture, not private operations.",
            primary_questions=["What is the idea?", "What is evidenced?", "What is speculative?"],
            needed_decisions=["read", "cite", "discuss"],
            allowed_claim_classes=["architecture", "risk", "roadmap", "capability"],
            forbidden_inferences=["private state disclosure", "anthropomorphic overclaim"],
            required_evidence_bundle=["public-safe evidence", "scope caveats"],
            primary_surfaces=["audience_essay", "public_homepage"],
            public_surface=True,
            allow_public_claims=True,
        ),
    }


_PUBLIC_EVIDENCE_PRIVACY_CLASSES = {"public", "public_registry"}
_PUBLIC_SURFACE_TOKENS = ("public", "sales", "repo_readme", "homepage", "audience")
_ENTERPRISE_SURFACE_TOKENS = ("enterprise", "testbed", "alliant", "pilot", "determination")
_ENTERPRISE_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "employer_endorsement",
        re.compile(
            r"\b(alliant|employer|workplace)\b.{0,80}\b"
            r"(endorses|approved|approves|adopted|certified|sponsors|official)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "production_readiness_without_pilot_evidence",
        re.compile(r"\b(production[- ]ready|ready for production|prod[- ]ready)\b", re.IGNORECASE),
    ),
    (
        "private_runtime_transferability",
        re.compile(
            r"\b(private hapax runtime|raw private logs|operator-private|"
            r"local runtime state|secrets?|employer confidential|customer data)\b",
            re.IGNORECASE,
        ),
    ),
)


def _claim_targets_public_surface(
    claim: ClaimRecord,
    audiences: Sequence[AudienceProfile],
) -> bool:
    if claim.status == "approved_public":
        return True
    if any(profile.public_surface for profile in audiences):
        return True
    surfaces = [*claim.allowed_surfaces, *claim.prohibited_surfaces]
    return any(token in surface.lower() for surface in surfaces for token in _PUBLIC_SURFACE_TOKENS)


def _claim_targets_enterprise_context(
    claim: ClaimRecord,
    audiences: Sequence[AudienceProfile],
) -> bool:
    if any(profile.enterprise_context for profile in audiences):
        return True
    surfaces = [*claim.allowed_surfaces, *claim.prohibited_surfaces]
    return any(
        token in surface.lower() for surface in surfaces for token in _ENTERPRISE_SURFACE_TOKENS
    )


def _claim_text_for_scan(claim: ClaimRecord) -> str:
    return " ".join(
        part
        for part in [
            claim.text,
            claim.allowed_wording,
            " ".join(claim.forbidden_wording),
            " ".join(claim.risk_flags),
        ]
        if part
    )


def _evidence_status(
    *,
    evidence_ref_count: int,
    missing_refs: Sequence[str],
    stale_records: Sequence[LegibilityEvidenceRecord],
    failed_records: Sequence[LegibilityEvidenceRecord],
) -> ClaimEvidenceStatus:
    if evidence_ref_count == 0 or missing_refs:
        return "missing"
    if failed_records:
        return "contradictory"
    if stale_records:
        return "stale"
    return "fresh"


def validate_claim_for_audiences(
    claim: ClaimRecord,
    evidence_records: Sequence[LegibilityEvidenceRecord],
    *,
    audience_profiles: dict[AudienceId, AudienceProfile] | None = None,
    now: float | None = None,
) -> ClaimValidationResult:
    """Validate that a claim may be rendered to its requested audiences.

    The validator is intentionally conservative: unknown audiences, missing
    current-state evidence, stale current-state evidence, failed evidence,
    public claims backed by non-public-safe evidence, and enterprise/testbed
    overclaims all block.
    """

    profiles = audience_profiles or default_audience_profiles()
    blockers: list[str] = []
    warnings: list[str] = []
    audiences: list[AudienceProfile] = []
    for audience_id in claim.audience_scope:
        profile = profiles.get(audience_id)
        if profile is None:
            blockers.append(f"unknown_audience:{audience_id}")
            continue
        audiences.append(profile)
        if claim.claim_kind not in profile.allowed_claim_classes:
            blockers.append(f"claim_kind_not_allowed:{audience_id}:{claim.claim_kind}")

    records_by_id = {record.evidence_id: record for record in evidence_records}
    missing_refs = [ref for ref in claim.evidence_refs if ref not in records_by_id]
    records = [records_by_id[ref] for ref in claim.evidence_refs if ref in records_by_id]
    stale_records = [record for record in records if not record.is_fresh(now)]
    failed_records = [record for record in records if record.status != "ok"]

    if not claim.evidence_refs:
        blockers.append("missing_evidence")
    blockers.extend(f"missing_evidence:{ref}" for ref in missing_refs)

    if claim.claim_kind == "current_state":
        blockers.extend(
            f"stale_current_state_evidence:{record.evidence_id}" for record in stale_records
        )
    elif stale_records:
        warnings.extend(f"stale_evidence:{record.evidence_id}" for record in stale_records)

    blockers.extend(f"failed_evidence:{record.evidence_id}" for record in failed_records)

    public_target = _claim_targets_public_surface(claim, audiences)
    if public_target and claim.status != "approved_public":
        blockers.append("public_claim_not_approved")
    if public_target:
        for record in records:
            if (
                not record.public_safe
                or record.privacy_class not in _PUBLIC_EVIDENCE_PRIVACY_CLASSES
            ):
                blockers.append(f"public_claim_without_public_safe_evidence:{record.evidence_id}")

    if _claim_targets_enterprise_context(claim, audiences):
        scan_text = _claim_text_for_scan(claim)
        for inference_name, pattern in _ENTERPRISE_FORBIDDEN_PATTERNS:
            if pattern.search(scan_text):
                blockers.append(f"enterprise_forbidden_inference:{inference_name}")

    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    return ClaimValidationResult(
        claim_id=claim.claim_id,
        allowed=not blockers,
        blockers=blockers,
        warnings=warnings,
        evidence_status=_evidence_status(
            evidence_ref_count=len(claim.evidence_refs),
            missing_refs=missing_refs,
            stale_records=stale_records,
            failed_records=failed_records,
        ),
        evidence_ids=[record.evidence_id for record in records],
        audience_ids=[profile.audience_id for profile in audiences],
    )


def _record(
    *,
    kind: LegibilityEvidenceKind,
    source_command: str = "",
    source_url: str = "",
    value_summary: str,
    privacy_class: LegibilityPrivacyClass,
    public_safe: bool,
    status: LegibilityEvidenceStatus = "ok",
    error: str = "",
    freshness_ttl_s: float = 3600.0,
    confidence: LegibilityConfidence = "high",
    collector: str = "hapax-evidence",
    repo: str = "",
    path: str = "",
    failure_behavior: LegibilityFailureBehavior = "fail_closed",
) -> LegibilityEvidenceRecord:
    collected_at = _now_iso()
    source = source_url or source_command or path or value_summary
    summary, summary_redacted = redact_secret_text(_bounded(value_summary))
    err, error_redacted = redact_secret_text(_bounded(error))
    redaction_notes = "secret-like text redacted" if summary_redacted or error_redacted else ""
    return LegibilityEvidenceRecord(
        evidence_id=_evidence_id(kind, source, collected_at),
        kind=kind,
        collected_at=collected_at,
        collector=collector,
        source_command=source_command,
        source_url=source_url,
        repo=repo,
        path=path,
        value_summary=summary,
        confidence=confidence,
        freshness_ttl_s=freshness_ttl_s,
        privacy_class=privacy_class,
        public_safe=public_safe,
        redaction_notes=redaction_notes,
        failure_behavior=failure_behavior,
        status=status,
        error=err,
    )


def collect_command_evidence(
    command: Sequence[str] | str,
    *,
    cwd: str | Path | None = None,
    timeout_s: float = 10.0,
    privacy_class: LegibilityPrivacyClass = "local_private",
    public_safe: bool = False,
    freshness_ttl_s: float = 3600.0,
    collector: str = "hapax-evidence",
) -> LegibilityEvidenceRecord:
    argv = shlex.split(command) if isinstance(command, str) else list(command)
    source_command = " ".join(shlex.quote(part) for part in argv)
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _record(
            kind="collection_failure",
            source_command=source_command,
            value_summary=f"command collection failed: {type(exc).__name__}",
            privacy_class=privacy_class,
            public_safe=public_safe,
            status="failed",
            error=str(exc),
            freshness_ttl_s=freshness_ttl_s,
            collector=collector,
        )
    output = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    summary = f"exit={result.returncode}"
    if output:
        summary += f" stdout={output}"
    if stderr:
        summary += f" stderr={stderr}"
    return _record(
        kind="command" if result.returncode == 0 else "collection_failure",
        source_command=source_command,
        value_summary=summary,
        privacy_class=privacy_class,
        public_safe=public_safe,
        status="ok" if result.returncode == 0 else "failed",
        error=stderr if result.returncode else "",
        freshness_ttl_s=freshness_ttl_s,
        collector=collector,
        path=str(cwd or ""),
    )


UrlOpener = Callable[..., object]


def _read_url(
    url: str,
    *,
    timeout_s: float,
    opener: UrlOpener | None = None,
) -> tuple[int, str, str]:
    request = Request(url, headers={"User-Agent": "hapax-evidence/0"})
    open_fn = opener or urlopen
    with open_fn(request, timeout=timeout_s) as response:  # type: ignore[attr-defined]
        status = int(getattr(response, "status", 200))
        headers = getattr(response, "headers", {})
        content_type = ""
        if hasattr(headers, "get"):
            content_type = headers.get("content-type", "") or headers.get("Content-Type", "")
        body = response.read(200_000).decode("utf-8", errors="replace")
        return status, content_type, body


def _html_title(body: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def collect_public_url_evidence(
    url: str,
    *,
    timeout_s: float = 10.0,
    freshness_ttl_s: float = 3600.0,
    opener: UrlOpener | None = None,
) -> LegibilityEvidenceRecord:
    try:
        status, content_type, body = _read_url(url, timeout_s=timeout_s, opener=opener)
    except HTTPError as exc:
        return _record(
            kind="collection_failure",
            source_url=url,
            value_summary=f"public URL failed: HTTP {exc.code}",
            privacy_class="public",
            public_safe=True,
            status="failed",
            error=str(exc),
            freshness_ttl_s=freshness_ttl_s,
        )
    except (URLError, OSError, TimeoutError) as exc:
        return _record(
            kind="collection_failure",
            source_url=url,
            value_summary=f"public URL failed: {type(exc).__name__}",
            privacy_class="public",
            public_safe=True,
            status="failed",
            error=str(exc),
            freshness_ttl_s=freshness_ttl_s,
        )
    title = _html_title(body)
    summary = f"status={status} content_type={content_type or 'unknown'}"
    if title:
        summary += f" title={title}"
    elif body and ("json" in content_type.lower() or content_type.lower().startswith("text/")):
        body_excerpt = re.sub(r"\s+", " ", body).strip()
        summary += f" body={_bounded(body_excerpt, 500)}"
    return _record(
        kind="public_url" if 200 <= status < 400 else "collection_failure",
        source_url=url,
        value_summary=summary,
        privacy_class="public",
        public_safe=True,
        status="ok" if 200 <= status < 400 else "failed",
        error="" if 200 <= status < 400 else f"HTTP {status}",
        freshness_ttl_s=freshness_ttl_s,
    )


def collect_package_registry_evidence(
    package_name: str,
    *,
    registry_url_template: str = "https://pypi.org/pypi/{package}/json",
    timeout_s: float = 10.0,
    freshness_ttl_s: float = 3600.0,
    opener: UrlOpener | None = None,
) -> LegibilityEvidenceRecord:
    url = registry_url_template.format(package=package_name)
    try:
        status, content_type, body = _read_url(url, timeout_s=timeout_s, opener=opener)
        data = json.loads(body)
        version = data.get("info", {}).get("version", "unknown")
    except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        return _record(
            kind="collection_failure",
            source_url=url,
            value_summary=f"package registry failed for {package_name}: {type(exc).__name__}",
            privacy_class="public_registry",
            public_safe=True,
            status="failed",
            error=str(exc),
            freshness_ttl_s=freshness_ttl_s,
        )
    summary = f"package={package_name} status={status} content_type={content_type or 'unknown'} version={version}"
    return _record(
        kind="package_registry",
        source_url=url,
        value_summary=summary,
        privacy_class="public_registry",
        public_safe=True,
        status="ok",
        freshness_ttl_s=freshness_ttl_s,
    )


def collect_local_api_evidence(
    url: str,
    *,
    timeout_s: float = 5.0,
    freshness_ttl_s: float = 300.0,
    opener: UrlOpener | None = None,
) -> LegibilityEvidenceRecord:
    record = collect_public_url_evidence(
        url,
        timeout_s=timeout_s,
        freshness_ttl_s=freshness_ttl_s,
        opener=opener,
    )
    return record.model_copy(
        update={
            "kind": "local_api" if record.status == "ok" else "collection_failure",
            "privacy_class": "local_private",
            "public_safe": False,
        }
    )


def collect_systemd_inventory_evidence(
    *,
    user: bool = True,
    timeout_s: float = 10.0,
    freshness_ttl_s: float = 3600.0,
) -> LegibilityEvidenceRecord:
    base_command = ["systemctl"]
    if user:
        base_command.append("--user")
    commands = {
        "service_unit_files": [*base_command, "list-unit-files", "--type=service", "--no-legend"],
        "timer_unit_files": [*base_command, "list-unit-files", "--type=timer", "--no-legend"],
        "active_timers": [*base_command, "list-timers", "--all", "--no-legend"],
    }
    outputs: dict[str, str] = {}
    source_command = " ; ".join(
        " ".join(shlex.quote(part) for part in command) for command in commands.values()
    )
    for name, command in commands.items():
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _record(
                kind="collection_failure",
                source_command=source_command,
                value_summary=f"systemd inventory failed at {name}: {type(exc).__name__}",
                privacy_class="local_private",
                public_safe=False,
                status="failed",
                error=str(exc),
                freshness_ttl_s=freshness_ttl_s,
            )
        if result.returncode != 0:
            return _record(
                kind="collection_failure",
                source_command=source_command,
                value_summary=f"systemd inventory failed at {name}: exit={result.returncode}",
                privacy_class="local_private",
                public_safe=False,
                status="failed",
                error=(result.stderr or "").strip(),
                freshness_ttl_s=freshness_ttl_s,
            )
        outputs[name] = result.stdout or ""
    service_count = len(re.findall(r"\.service\b", outputs["service_unit_files"]))
    timer_unit_count = len(re.findall(r"\.timer\b", outputs["timer_unit_files"]))
    active_timer_count = len(
        [line for line in outputs["active_timers"].splitlines() if line.strip()]
    )
    return _record(
        kind="systemd_inventory",
        source_command=source_command,
        value_summary=(
            f"user={user} service_unit_file_count={service_count} "
            f"timer_unit_file_count={timer_unit_count} active_timer_count={active_timer_count}"
        ),
        privacy_class="local_private",
        public_safe=False,
        freshness_ttl_s=freshness_ttl_s,
    )
