"""Publication hardening lint — structural checks beyond Vale's capabilities."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from shared.anti_personification_linter import lint_text as lint_anti_personification_text


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

GENERATED_TEXT_BANNED_TERMS: tuple[str, ...] = (
    "paradigm",
    "leverage",
    "leverages",
    "leveraging",
    "leveraged",
    "synergy",
    "synergies",
    "synergistic",
    "utilize",
    "utilizes",
    "utilizing",
    "utilization",
    "facilitate",
    "facilitates",
    "facilitating",
    "facilitation",
    "operationalize",
    "operationalizes",
    "operationalizing",
    "incentivize",
    "incentivizes",
    "incentivizing",
    "holistic",
    "holistically",
    "scalable",
    "best-in-class",
    "best in class",
    "cutting-edge",
    "cutting edge",
    "game-changer",
    "game changer",
    "move the needle",
    "low-hanging fruit",
    "deep dive",
    "circle back",
    "touch base",
    "at the end of the day",
    "going forward",
    "stakeholder alignment",
    "value proposition",
    "thought leader",
    "thought leadership",
    "disruptive",
    "innovative solution",
    "paradigm shift",
    "ecosystem",
    "empower",
    "empowers",
    "empowering",
    "democratize",
    "democratizes",
    "democratizing",
    "robust",
    "seamless",
    "seamlessly",
    "next-generation",
    "next generation",
    "world-class",
    "world class",
    "bleeding-edge",
    "bleeding edge",
    "best practice",
    "best practices",
    "mission-critical",
    "mission critical",
    "end-to-end",
    "turnkey",
    "actionable insights",
    "data-driven",
)

GENERATED_TEXT_BANNED_TERMS_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(re.escape(term).replace(r"\ ", r"\s+") for term in GENERATED_TEXT_BANNED_TERMS)
    + r")\b",
    re.IGNORECASE,
)

FORMAL_REGISTER_PATTERNS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        GENERATED_TEXT_BANNED_TERMS_PATTERN,
        "error",
        "Hapax.FormalRegister",
        "Use concrete publication prose instead of generic marketing or jargon terms.",
    ),
    (
        re.compile(r"[\U0001F300-\U0001FAFF]"),
        "error",
        "Hapax.FormalRegister",
        "Remove emoji from publication prose.",
    ),
    (
        re.compile(r"!{2,}"),
        "error",
        "Hapax.FormalRegister",
        "Use formal punctuation; repeated exclamation marks are not publication prose.",
    ),
    (
        re.compile(
            r"^\s*(so[\s,]|today\s+we['\u2019]?re|welcome\s+back|hey\s+"
            r"(everyone|everybody|friends|folks|guys|y['\u2019]?all)|what['\u2019]?s\s+up|"
            r"in\s+today['\u2019]?s\s+(video|stream|episode|broadcast))",
            re.IGNORECASE,
        ),
        "error",
        "Hapax.FormalRegister",
        "Use observer-facing research prose, not creator-opener language.",
    ),
    (
        re.compile(
            r"\b(subscribe|like\s+and\s+(follow|subscribe|share)|smash\s+"
            r"(that\s+)?(like|subscribe)|hit\s+the\s+bell|comment\s+"
            r"(below|down\s+below)|don['\u2019]?t\s+forget\s+to\s+"
            r"(like|subscribe|share))\b",
            re.IGNORECASE,
        ),
        "error",
        "Hapax.FormalRegister",
        "Remove creator-economy calls to action from research publication prose.",
    ),
    (
        re.compile(
            r"\b(amazing|incredible|absolutely\s+"
            r"(stunning|beautiful|amazing|incredible|phenomenal)|"
            r"mind[\s-]?blowing|game[\s-]?changer)\b",
            re.IGNORECASE,
        ),
        "error",
        "Hapax.FormalRegister",
        "Replace hollow affirmation with concrete evidence or omit it.",
    ),
)

SYSTEM_INNER_LIFE_PATTERNS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        re.compile(
            r"\b(?:Hapax|the system|this system|system|the agent|agent|"
            r"the publisher|publisher|the orchestrator|orchestrator|"
            r"the bus|bus)\s+(feels|thinks|believes|wants|cares|hopes|"
            r"fears|perceives|trusts|prefers|remembers|knows|understands|"
            r"intuits)\b",
            re.IGNORECASE,
        ),
        "error",
        "Hapax.NonAnthropomorphicRegister",
        "Use operational vocabulary; do not attribute inner life to Hapax or a system component.",
    ),
    (
        re.compile(r"\bHapax['\u2019]?s voice\b", re.IGNORECASE),
        "error",
        "Hapax.NonAnthropomorphicRegister",
        "Name the concrete TTS/audio surface instead of treating voice as a personality surface.",
    ),
    (
        re.compile(
            r"\b(your feelings|your show|your opinions|your affect|"
            r"your personality|alien mind|distributed mind|"
            r"operator-flavou?red|operator-colou?red)\b",
            re.IGNORECASE,
        ),
        "error",
        "Hapax.NonAnthropomorphicRegister",
        "Remove human-host, personality, or inner-life framing.",
    ),
)


def check_heading_hierarchy(path: Path) -> list[LintFinding]:
    """Flag heading level skips (e.g., h2 directly to h4)."""
    return check_heading_hierarchy_text(
        path.read_text(encoding="utf-8"),
        file_label=str(path),
    )


def check_heading_hierarchy_text(text: str, *, file_label: str = "<artifact>") -> list[LintFinding]:
    """Flag heading level skips in raw Markdown text."""
    findings: list[LintFinding] = []
    heading_re = re.compile(r"^(#{1,6})\s")
    prev_level = 0

    for lineno, line in enumerate(text.splitlines(), start=1):
        m = heading_re.match(line)
        if not m:
            continue
        level = len(m.group(1))
        if prev_level > 0 and level > prev_level + 1:
            findings.append(
                LintFinding(
                    file=file_label,
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
    return check_public_claim_overreach_text(
        path.read_text(encoding="utf-8"),
        file_label=str(path),
    )


def check_public_claim_overreach_text(
    text: str,
    *,
    file_label: str = "<artifact>",
) -> list[LintFinding]:
    """Flag public-claim phrases in raw text that exceeded audit-supported scope."""
    findings: list[LintFinding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, level, message in OVERCLAIM_PATTERNS:
            if not pattern.search(line):
                continue
            findings.append(
                LintFinding(
                    file=file_label,
                    line=lineno,
                    level=level,
                    rule="Hapax.PublicClaimOverreach",
                    message=message,
                )
            )
    return findings


def check_formal_register_text(
    text: str,
    *,
    file_label: str = "<artifact>",
) -> list[LintFinding]:
    """Flag generated-publication prose that violates formal register."""
    findings: list[LintFinding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, level, rule, message in FORMAL_REGISTER_PATTERNS:
            if not pattern.search(line):
                continue
            findings.append(
                LintFinding(
                    file=file_label,
                    line=lineno,
                    level=level,
                    rule=rule,
                    message=message,
                )
            )
    return findings


def check_non_anthropomorphic_register_text(
    text: str,
    *,
    file_label: str = "<artifact>",
) -> list[LintFinding]:
    """Flag inner-life or personality framing in publication prose."""
    findings: list[LintFinding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, level, rule, message in SYSTEM_INNER_LIFE_PATTERNS:
            if not pattern.search(line):
                continue
            findings.append(
                LintFinding(
                    file=file_label,
                    line=lineno,
                    level=level,
                    rule=rule,
                    message=message,
                )
            )

    for finding in lint_anti_personification_text(text, path=file_label):
        findings.append(
            LintFinding(
                file=file_label,
                line=finding.line,
                level="error",
                rule="Hapax.NonAnthropomorphicRegister",
                message=(
                    f"Anti-personification finding {finding.rule_id}: "
                    "describe operations, evidence, or readback instead."
                ),
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
    text = path.read_text(encoding="utf-8")
    findings.extend(check_formal_register_text(text, file_label=str(path)))
    findings.extend(check_non_anthropomorphic_register_text(text, file_label=str(path)))
    findings.extend(run_vale(path, config=config))
    return findings


def lint_text(text: str, *, file_label: str = "<artifact>") -> list[LintFinding]:
    """Run publication lint checks that do not require a file path."""
    findings: list[LintFinding] = []
    findings.extend(check_heading_hierarchy_text(text, file_label=file_label))
    findings.extend(check_public_claim_overreach_text(text, file_label=file_label))
    findings.extend(check_formal_register_text(text, file_label=file_label))
    findings.extend(check_non_anthropomorphic_register_text(text, file_label=file_label))
    return findings
