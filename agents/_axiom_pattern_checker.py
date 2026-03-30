"""shared/axiom_pattern_checker.py — Output pattern matching for axiom enforcement.

Checks LLM-generated text against output enforcement patterns defined in
axioms/enforcement-patterns.yaml. Sub-millisecond regex matching, no LLM calls.

Usage:
    from agents._axiom_pattern_checker import check_output, load_patterns

    violations = check_output("suggest feedback for Alex on communication")
    for v in violations:
        print(f"[{v.tier}] {v.pattern_id}: {v.matched_text}")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

PATTERNS_PATH = Path(__file__).resolve().parent.parent / "axioms" / "enforcement-patterns.yaml"


@dataclass(frozen=True)
class OutputPattern:
    id: str
    axiom_id: str
    implication_id: str
    tier: str  # "T0" | "T1" | "T2"
    regex: re.Pattern[str]
    description: str
    false_positive_notes: str


@dataclass
class PatternViolation:
    pattern_id: str
    axiom_id: str
    implication_id: str
    tier: str
    matched_text: str
    match_start: int
    match_end: int
    description: str


_cached_patterns: list[OutputPattern] | None = None


def load_patterns(*, path: Path = PATTERNS_PATH) -> list[OutputPattern]:
    """Load and compile output enforcement patterns (cached)."""
    global _cached_patterns
    if _cached_patterns is not None:
        return _cached_patterns

    if not path.exists():
        log.warning("Enforcement patterns not found: %s", path)
        return []

    try:
        data = yaml.safe_load(path.read_text())
    except Exception as e:
        log.error("Failed to load enforcement patterns: %s", e)
        return []

    patterns: list[OutputPattern] = []
    for entry in data.get("patterns", []):
        try:
            compiled = re.compile(entry["regex"], re.IGNORECASE)
        except re.error as e:
            log.error("Invalid regex in pattern %s: %s", entry.get("id", "?"), e)
            continue

        patterns.append(
            OutputPattern(
                id=entry["id"],
                axiom_id=entry.get("axiom_id", ""),
                implication_id=entry.get("implication_id", ""),
                tier=entry.get("tier", "T2"),
                regex=compiled,
                description=entry.get("description", ""),
                false_positive_notes=entry.get("false_positive_notes", ""),
            )
        )

    _cached_patterns = patterns
    log.debug("Loaded %d output enforcement patterns", len(patterns))
    return patterns


def check_output(
    text: str,
    *,
    tier_filter: str = "",
    axiom_filter: str = "",
) -> list[PatternViolation]:
    """Check text against output enforcement patterns.

    Args:
        text: LLM-generated output text to check.
        tier_filter: Only check patterns at this tier (e.g., "T0"). Empty for all.
        axiom_filter: Only check patterns for this axiom. Empty for all.

    Returns:
        List of violations found, sorted by tier (T0 first).
    """
    patterns = load_patterns()
    violations: list[PatternViolation] = []

    for pat in patterns:
        if tier_filter and pat.tier != tier_filter:
            continue
        if axiom_filter and pat.axiom_id != axiom_filter:
            continue

        for match in pat.regex.finditer(text):
            violations.append(
                PatternViolation(
                    pattern_id=pat.id,
                    axiom_id=pat.axiom_id,
                    implication_id=pat.implication_id,
                    tier=pat.tier,
                    matched_text=match.group(),
                    match_start=match.start(),
                    match_end=match.end(),
                    description=pat.description,
                )
            )

    # Sort by tier priority: T0 > T1 > T2
    tier_order = {"T0": 0, "T1": 1, "T2": 2}
    violations.sort(key=lambda v: tier_order.get(v.tier, 9))

    return violations


def reload_patterns() -> None:
    """Force reload of patterns (for testing or hot-reload)."""
    global _cached_patterns
    _cached_patterns = None
