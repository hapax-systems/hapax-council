"""Mode D: retroactive audit sweep over a research-artifact corpus.

Discovers markdown files in scope, extracts claim-bearing sentences, runs each
claim through disconfirmation, and emits an ``AuditSweepReport`` with totals.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agents.deliberative_council.models import CouncilConfig
from agents.deliberative_council.modes.disconfirmation import (
    DisconfirmationReceipt,
    DisconfirmationVerdict,
    disconfirm,
)

_log = logging.getLogger(__name__)

__all__ = [
    "CLAIM_VERBS",
    "AuditClaim",
    "AuditFileReport",
    "AuditSweepReport",
    "discover_artifacts",
    "extract_claims",
    "run_audit_sweep",
]


# Claim trigger verbs are matched as inflected forms (suffixes added at
# match-time). The S3.5 methodology doc identifies these as the canonical
# epistemic-claim signals.
CLAIM_VERBS: tuple[str, ...] = (
    "demonstrates",
    "demonstrate",
    "demonstrated",
    "establishes",
    "establish",
    "established",
    "proves",
    "prove",
    "proved",
    "proven",
    "shows",
    "show",
    "shown",
    "confirms",
    "confirm",
    "confirmed",
    "validates",
    "validate",
    "validated",
)

# Sentence splitter: terminator followed by whitespace or end-of-text. This is
# intentionally simple; markdown corpora rarely need a full NLP tokenizer here.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

# Word-boundary verb pattern. Built once at import.
_VERB_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(v) for v in CLAIM_VERBS) + r")\b",
    re.IGNORECASE,
)


class AuditClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_path: str
    line_number: int
    text: str
    verb: str


class AuditFileReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_path: str
    claims_found: int
    receipts: tuple[DisconfirmationReceipt, ...] = ()
    errors: tuple[str, ...] = ()


class AuditSweepReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: str
    files_scanned: int
    files_with_claims: int
    total_claims: int
    survived: int
    contested: int
    refuted: int
    insufficient: int
    file_reports: tuple[AuditFileReport, ...] = ()
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def discover_artifacts(scope: Path) -> list[Path]:
    """Return all markdown files under ``scope``, sorted for determinism.

    A non-directory ``scope`` containing a markdown file returns ``[scope]``.
    """
    if scope.is_file():
        return [scope] if scope.suffix == ".md" else []
    if not scope.is_dir():
        return []
    return sorted(p for p in scope.rglob("*.md") if p.is_file())


def _strip_markdown(line: str) -> str:
    """Strip leading list/heading markers so sentences read as prose."""
    return re.sub(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s*)", "", line)


def extract_claims(path: Path) -> list[AuditClaim]:
    """Extract claim-bearing sentences from a markdown file.

    A claim is any sentence that contains one of the configured claim verbs as
    a whole word. Frontmatter, fenced code blocks, and inline-code spans are
    skipped so we don't audit example text or YAML keys.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _log.warning("audit: could not read %s: %s", path, exc)
        return []

    lines = raw.splitlines()
    in_fence = False
    in_frontmatter = False
    if lines and lines[0].strip() == "---":
        in_frontmatter = True

    claims: list[AuditClaim] = []
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if in_frontmatter:
            if i > 1 and stripped == "---":
                in_frontmatter = False
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        # Strip inline code so verbs inside backticks don't trigger.
        clean = re.sub(r"`[^`]*`", "", _strip_markdown(line))
        if not clean.strip():
            continue

        for sentence in _SENT_SPLIT.split(clean.strip()):
            sentence = sentence.strip()
            if not sentence:
                continue
            m = _VERB_PATTERN.search(sentence)
            if m is None:
                continue
            claims.append(
                AuditClaim(
                    source_path=str(path),
                    line_number=i,
                    text=sentence,
                    verb=m.group(1).lower(),
                )
            )
    return claims


def _tally(receipts: list[DisconfirmationReceipt]) -> dict[str, int]:
    tallies = {"survived": 0, "contested": 0, "refuted": 0, "insufficient": 0}
    for r in receipts:
        if r.verdict == DisconfirmationVerdict.SURVIVED:
            tallies["survived"] += 1
        elif r.verdict == DisconfirmationVerdict.CONTESTED:
            tallies["contested"] += 1
        elif r.verdict == DisconfirmationVerdict.REFUTED:
            tallies["refuted"] += 1
        elif r.verdict == DisconfirmationVerdict.INSUFFICIENT_EVIDENCE:
            tallies["insufficient"] += 1
    return tallies


ReceiptMaker = Callable[[AuditClaim], Awaitable[DisconfirmationReceipt]]


def _default_receipt_maker(config: CouncilConfig | None) -> ReceiptMaker:
    async def _make(claim: AuditClaim) -> DisconfirmationReceipt:
        return await disconfirm(
            claim=claim.text,
            source_refs=(claim.source_path,),
            config=config,
        )

    return _make


async def run_audit_sweep(
    scope: Path,
    *,
    config: CouncilConfig | None = None,
    concurrency: int = 2,
    receipt_maker: ReceiptMaker | None = None,
    claim_limit_per_file: int | None = None,
) -> AuditSweepReport:
    """Sweep ``scope`` for markdown artifacts; disconfirm each extracted claim.

    ``receipt_maker`` is injectable so tests (and deterministic runs) can avoid
    invoking real provider calls. ``claim_limit_per_file`` caps the number of
    claims audited per file when set — useful for bounded runtime observation.
    """
    artifacts = discover_artifacts(scope)
    maker = receipt_maker or _default_receipt_maker(config)
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _audit_claim(c: AuditClaim) -> DisconfirmationReceipt | str:
        async with sem:
            try:
                return await maker(c)
            except Exception as exc:  # noqa: BLE001 — boundary, recorded as error
                _log.error("audit: disconfirm failed for %s: %s", c.source_path, exc)
                return f"{c.source_path}:{c.line_number} {type(exc).__name__}: {exc}"

    file_reports: list[AuditFileReport] = []
    all_receipts: list[DisconfirmationReceipt] = []

    for artifact in artifacts:
        claims = extract_claims(artifact)
        if claim_limit_per_file is not None and claim_limit_per_file >= 0:
            claims = claims[:claim_limit_per_file]
        if not claims:
            file_reports.append(AuditFileReport(source_path=str(artifact), claims_found=0))
            continue

        results = await asyncio.gather(*(_audit_claim(c) for c in claims))
        receipts = tuple(r for r in results if isinstance(r, DisconfirmationReceipt))
        errors = tuple(r for r in results if isinstance(r, str))
        file_reports.append(
            AuditFileReport(
                source_path=str(artifact),
                claims_found=len(claims),
                receipts=receipts,
                errors=errors,
            )
        )
        all_receipts.extend(receipts)

    tallies = _tally(all_receipts)
    return AuditSweepReport(
        scope=str(scope),
        files_scanned=len(artifacts),
        files_with_claims=sum(1 for fr in file_reports if fr.claims_found > 0),
        total_claims=sum(fr.claims_found for fr in file_reports),
        survived=tallies["survived"],
        contested=tallies["contested"],
        refuted=tallies["refuted"],
        insufficient=tallies["insufficient"],
        file_reports=tuple(file_reports),
    )


def report_to_json(report: AuditSweepReport) -> dict[str, Any]:
    """Serialize a sweep report to a JSON-friendly dict."""
    return report.model_dump(mode="json")
