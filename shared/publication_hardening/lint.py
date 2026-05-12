"""Publication hardening lint — structural checks beyond Vale's capabilities."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LintFinding:
    file: str
    line: int
    level: str  # "error" | "warning"
    rule: str
    message: str


OVERCLAIM_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"\bevery file write\b", re.IGNORECASE),
        "error",
        "Scope file-write coverage to governed paths and supporting receipts.",
    ),
    (
        re.compile(r"\bevery commit\b", re.IGNORECASE),
        "error",
        "Scope commit coverage to governed paths and supporting receipts.",
    ),
    (
        re.compile(r"\bevery deployment decision\b", re.IGNORECASE),
        "error",
        "Scope deployment coverage to governed paths and supporting receipts.",
    ),
    (
        re.compile(r"\bphysically cannot\b", re.IGNORECASE),
        "error",
        "Replace physical impossibility language with governed-path blocking language.",
    ),
    (
        re.compile(r"\bno test results,\s*no push\b", re.IGNORECASE),
        "error",
        "Replace slogan form with scoped push-gate evidence language.",
    ),
    (
        re.compile(r"\bconstitutionally incapable\b", re.IGNORECASE),
        "error",
        "Avoid absolute incapability claims; scope to mechanical gates on governed paths.",
    ),
    (
        re.compile(r"\ball code, infrastructure, and governance mechanisms\b", re.IGNORECASE),
        "error",
        "Avoid all-surface production claims unless each surface has a current receipt.",
    ),
    (
        re.compile(r"\bexistence proof\b", re.IGNORECASE),
        "warning",
        "Existence-proof claims need an audit receipt and may need hypothesis framing.",
    ),
    (
        re.compile(r"\bunbounded\b", re.IGNORECASE),
        "warning",
        "Unbounded value/resource language needs a claim ceiling or citation.",
    ),
    (
        re.compile(r"\bShapley Values? for Output Tokens\b", re.IGNORECASE),
        "warning",
        "Token Capital Shapley framing is audit-quarantined until repaired.",
    ),
)


def check_heading_hierarchy(path: Path) -> list[LintFinding]:
    """Flag heading level skips (e.g., h2 directly to h4)."""
    findings: list[LintFinding] = []
    heading_re = re.compile(r"^(#{1,6})\s")
    prev_level = 0

    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        m = heading_re.match(line)
        if not m:
            continue
        level = len(m.group(1))
        if prev_level > 0 and level > prev_level + 1:
            findings.append(
                LintFinding(
                    file=str(path),
                    line=lineno,
                    level="error",
                    rule="Hapax.HeadingHierarchy",
                    message=(f"Heading skips from h{prev_level} to h{level}. Don't skip levels."),
                )
            )
        prev_level = level

    return findings


def check_public_claim_overreach(path: Path) -> list[LintFinding]:
    """Flag public-claim phrases that exceeded audit-supported scope."""
    findings: list[LintFinding] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for pattern, level, message in OVERCLAIM_PATTERNS:
            if not pattern.search(line):
                continue
            findings.append(
                LintFinding(
                    file=str(path),
                    line=lineno,
                    level=level,
                    rule="Hapax.PublicClaimOverreach",
                    message=message,
                )
            )
    return findings


def run_vale(path: Path, config: Path | None = None) -> list[LintFinding]:
    """Run Vale and parse JSON output into LintFindings."""
    import json

    cmd = ["vale", "--output=JSON"]
    if config:
        cmd.append(f"--config={config}")
    cmd.append(str(path))

    findings: list[LintFinding] = []
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return findings

    if not result.stdout.strip():
        return findings

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return findings

    for file_path, alerts in data.items():
        for alert in alerts:
            severity = alert.get("Severity", "warning").lower()
            findings.append(
                LintFinding(
                    file=file_path,
                    line=alert.get("Line", 0),
                    level=severity if severity in ("error", "warning") else "warning",
                    rule=alert.get("Check", "unknown"),
                    message=alert.get("Message", ""),
                )
            )

    return findings


def lint_file(path: Path, config: Path | None = None) -> list[LintFinding]:
    """Run all lint checks on a single file."""
    findings: list[LintFinding] = []
    findings.extend(check_heading_hierarchy(path))
    findings.extend(check_public_claim_overreach(path))
    findings.extend(run_vale(path, config=config))
    return findings
