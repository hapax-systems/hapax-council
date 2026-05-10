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


def run_vale(path: Path, config: Path | None = None) -> list[LintFinding]:
    """Run Vale and parse JSON output into LintFindings."""
    import json

    cmd = ["vale", "--output=JSON"]
    if config:
        cmd.append(f"--config={config}")
    cmd.append(str(path))

    result = subprocess.run(cmd, capture_output=True, text=True)
    findings: list[LintFinding] = []

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
    findings.extend(run_vale(path, config=config))
    return findings
