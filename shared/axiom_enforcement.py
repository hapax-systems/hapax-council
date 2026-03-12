"""Framework-agnostic axiom enforcement with hot/cold split.

Provides two enforcement paths:
  - check_fast: inline, no I/O, <1ms — for hot-path governance (VetoChain predicates)
  - check_full: deferred, Qdrant + YAML — for comprehensive compliance checks

Neither depends on pydantic-ai. The existing axiom_tools.py becomes a thin
Pydantic AI wrapper over these functions.

Usage:
    from shared.axiom_enforcement import check_fast, check_full, ComplianceResult

    # Hot path — in a VetoChain predicate
    result = check_fast("adding user roles", rules=cached_rules)

    # Cold path — full compliance check
    result = check_full("adding user roles", axiom_id="single_user")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComplianceRule:
    """A single compliance rule for fast-path checking.

    Pre-compiled from axiom implications at startup. No I/O at evaluation time.
    """

    axiom_id: str
    implication_id: str
    tier: str
    pattern: re.Pattern[str]
    description: str


@dataclass(frozen=True)
class ComplianceResult:
    """Result of a compliance check (fast or full)."""

    compliant: bool
    violations: tuple[str, ...] = ()
    axiom_ids: tuple[str, ...] = ()
    checked_rules: int = 0
    path: str = ""  # "fast" or "full"


def compile_rules(implications: list) -> list[ComplianceRule]:
    """Compile Implication objects into ComplianceRules for fast-path evaluation.

    Args:
        implications: list of axiom_registry.Implication objects.
    """
    rules: list[ComplianceRule] = []
    for impl in implications:
        if impl.tier != "T0" or impl.enforcement != "block":
            continue
        # Use implication text as a literal match pattern
        try:
            pattern = re.compile(re.escape(impl.id), re.IGNORECASE)
        except re.error:
            log.warning("Invalid pattern for implication %s, skipping", impl.id)
            continue
        rules.append(
            ComplianceRule(
                axiom_id=impl.axiom_id,
                implication_id=impl.id,
                tier=impl.tier,
                pattern=pattern,
                description=impl.text,
            )
        )
    return rules


def check_fast(situation: str, *, rules: list[ComplianceRule]) -> ComplianceResult:
    """Hot-path compliance check: inline, no I/O, <1ms.

    Evaluates pre-compiled rules against a situation description.
    Suitable for use as a VetoChain predicate.

    Args:
        situation: Description of the action being evaluated.
        rules: Pre-compiled ComplianceRules (from compile_rules()).
    """
    violations: list[str] = []
    axiom_ids: list[str] = []
    for rule in rules:
        if rule.pattern.search(situation):
            violations.append(f"[{rule.tier}] {rule.implication_id}: {rule.description}")
            if rule.axiom_id not in axiom_ids:
                axiom_ids.append(rule.axiom_id)
    return ComplianceResult(
        compliant=len(violations) == 0,
        violations=tuple(violations),
        axiom_ids=tuple(axiom_ids),
        checked_rules=len(rules),
        path="fast",
    )


def check_full(
    situation: str,
    *,
    axiom_id: str = "",
    domain: str = "",
    axioms_path: Path | None = None,
) -> ComplianceResult:
    """Cold-path compliance check: Qdrant precedents + YAML implications.

    Full compliance evaluation with I/O. Not suitable for hot-path.

    Args:
        situation: Description of the action being evaluated.
        axiom_id: Check a specific axiom. Empty for all.
        domain: Include domain axioms. Constitutional always included.
        axioms_path: Override axioms directory path.
    """
    from shared.axiom_registry import load_axioms, load_implications

    kwargs: dict = {}
    if axioms_path:
        kwargs["path"] = axioms_path

    if domain:
        axioms = load_axioms(scope="constitutional", **kwargs) + load_axioms(
            domain=domain, **kwargs
        )
    else:
        axioms = load_axioms(**kwargs)

    if axiom_id:
        axioms = [a for a in axioms if a.id == axiom_id]

    if not axioms:
        return ComplianceResult(compliant=True, checked_rules=0, path="full")

    # Compile all T0 implications into rules
    all_implications = []
    for axiom in axioms:
        all_implications.extend(load_implications(axiom.id, **kwargs))

    rules = compile_rules(all_implications)

    # Run fast check with compiled rules
    fast_result = check_fast(situation, rules=rules)

    # Also check precedent store if available
    precedent_violations: list[str] = []
    precedent_axioms: list[str] = []
    try:
        from shared.axiom_precedents import PrecedentStore

        store = PrecedentStore()
        for axiom in axioms:
            precedents = store.search(axiom.id, situation, limit=3)
            for p in precedents:
                if p.decision == "violation":
                    precedent_violations.append(
                        f"Precedent {p.id}: {p.situation} -> {p.decision}"
                    )
                    if p.axiom_id not in precedent_axioms:
                        precedent_axioms.append(p.axiom_id)
    except Exception as e:
        log.debug("Precedent store unavailable for full check: %s", e)

    all_violations = list(fast_result.violations) + precedent_violations
    all_axiom_ids = list(fast_result.axiom_ids) + [
        a for a in precedent_axioms if a not in fast_result.axiom_ids
    ]

    return ComplianceResult(
        compliant=len(all_violations) == 0,
        violations=tuple(all_violations),
        axiom_ids=tuple(all_axiom_ids),
        checked_rules=fast_result.checked_rules,
        path="full",
    )
