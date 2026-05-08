"""Evidence ledger, trace graph, and receipt envelopes for Authority-Case SDLC.

Append-only evidence ledger with per-tier completeness enforcement.
Trace graph links requirements/axioms to PRs/tests/readbacks/runtime.

ISAP: SLICE-005-EVIDENCE-TRACE (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

LEDGER_DIR = Path.home() / ".cache" / "hapax" / "evidence-ledger"

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


# T0-T3 minimum evidence requirements per the methodology addendum
TIER_REQUIREMENTS: dict[RiskTier, set[EvidenceKind]] = {
    "T0": {"test", "ci"},
    "T1": {"test", "ci", "readback"},
    "T2": {"test", "ci", "readback", "review", "axiom_scan"},
    "T3": {"test", "ci", "readback", "review", "axiom_scan", "assurance_argument"},
}


class EvidenceLedger:
    """Append-only file-backed evidence ledger."""

    def __init__(self, ledger_dir: Path | None = None) -> None:
        self._dir = ledger_dir or LEDGER_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def _case_file(self, case_id: str) -> Path:
        safe = case_id.replace("/", "_").replace(" ", "_")
        return self._dir / f"{safe}.jsonl"

    def append(self, entry: EvidenceEntry) -> None:
        path = self._case_file(entry.case_id)
        with path.open("a") as f:
            f.write(entry.model_dump_json() + "\n")

    def entries_for_case(self, case_id: str) -> list[EvidenceEntry]:
        path = self._case_file(case_id)
        if not path.exists():
            return []
        entries = []
        for line in path.read_text().splitlines():
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
        with path.open("a") as f:
            f.write(receipt.model_dump_json() + "\n")

    def receipts_for_case(self, case_id: str) -> list[ReceiptEnvelope]:
        path = self._dir / "receipts.jsonl"
        if not path.exists():
            return []
        receipts = []
        for line in path.read_text().splitlines():
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

    def __init__(self, ledger_dir: Path | None = None) -> None:
        self._dir = ledger_dir or LEDGER_DIR
        self._path = self._dir / "trace-graph.jsonl"
        self._dir.mkdir(parents=True, exist_ok=True)

    def add_link(self, link: TraceLink) -> None:
        with self._path.open("a") as f:
            f.write(link.model_dump_json() + "\n")

    def all_links(self) -> list[TraceLink]:
        if not self._path.exists():
            return []
        links = []
        for line in self._path.read_text().splitlines():
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
