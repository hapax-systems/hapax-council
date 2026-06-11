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
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from shared.coord_event_log import CoordEventLog

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
LegibilityEvidenceKind = Literal[
    "command",
    "public_url",
    "package_registry",
    "local_api",
    "systemd_inventory",
    "operator_decision",
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
    ) -> None:
        self._dir = ledger_dir or LEDGER_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._event_log = event_log

    def _case_file(self, case_id: str) -> Path:
        safe = case_id.replace("/", "_").replace(" ", "_")
        return self._dir / f"{safe}.jsonl"

    def append(self, entry: EvidenceEntry) -> None:
        path = self._case_file(entry.case_id)
        with path.open("a") as f:
            f.write(entry.model_dump_json() + "\n")
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

    def __init__(self, ledger_dir: Path | None = None) -> None:
        self._dir = ledger_dir or LEDGER_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "legibility-records.jsonl"

    def append(
        self,
        record: LegibilityEvidenceRecord,
        *,
        mirror_case_id: str | None = None,
        traces_to: list[str] | None = None,
    ) -> None:
        with self._path.open("a") as f:
            f.write(record.model_dump_json() + "\n")
        if mirror_case_id:
            EvidenceLedger(self._dir).append(
                record.to_evidence_entry(case_id=mirror_case_id, traces_to=traces_to)
            )

    def all_records(self) -> list[LegibilityEvidenceRecord]:
        if not self._path.exists():
            return []
        records: list[LegibilityEvidenceRecord] = []
        for line in self._path.read_text().splitlines():
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
