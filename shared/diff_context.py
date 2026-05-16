"""Structured diff context for deterministic axiom predicate evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DiffContext:
    """Parsed representation of a PR diff for predicate evaluation."""

    changed_files: tuple[str, ...]
    added_lines: tuple[str, ...]
    removed_lines: tuple[str, ...]
    pr_title: str = ""

    @classmethod
    def from_diff(cls, diff: str, changed_files: list[str], pr_title: str = "") -> DiffContext:
        added: list[str] = []
        removed: list[str] = []
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                removed.append(line[1:])
        return cls(
            changed_files=tuple(changed_files),
            added_lines=tuple(added),
            removed_lines=tuple(removed),
            pr_title=pr_title,
        )


# Multi-user vocabulary patterns (case-insensitive).
_MULTI_USER_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in [
        r"(?<![a-z])user_?id(?![a-z])",
        r"(?<![a-z])tenant_?id(?![a-z])",
        r"(?<![a-z])multi[_\-]?tenant",
        r"(?<![a-z])per[_\-]?user",
        r"(?<![a-z])role[_\-]?based",
        r"(?<![a-z])rbac(?![a-z])",
        r"(?<![a-z])access[_\-]?control[_\-]?list",
        r"(?<![a-z])user[_\-]?management",
        r"(?<![a-z])authenticat(?:ion|e|ed|ing)",
        r"(?<![a-z])authorizat(?:ion|e|ed|ing)",
        r"(?<![a-z])login[_\-]?required",
        r"(?<![a-z])sign[_\-]?up(?![a-z])",
        r"(?<![a-z])regist(?:er|ration)",
        r"(?<![a-z])user[_\-]?permission",
        r"(?<![a-z])user[_\-]?role",
        r"(?<![a-z])session[_\-]?user",
        r"(?<![a-z])current[_\-]?user",
        r"(?<![a-z])user[_\-]?context",
    ]
)

# Protected module import patterns.
_PROTECTED_IMPORT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in [
        r"^from\s+shared\.axiom_enforcement\b",
        r"^from\s+shared\.axiom_registry\b",
        r"^from\s+shared\.governance\b",
        r"^import\s+shared\.axiom_enforcement\b",
        r"^import\s+shared\.axiom_registry\b",
        r"^import\s+shared\.governance\b",
    ]
)


@dataclass
class PredicateResult:
    """Result of a single predicate check."""

    predicate_id: str
    axiom_id: str
    implication_id: str
    tier: str
    passed: bool
    matches: tuple[str, ...] = ()
    description: str = ""


def check_multi_user_vocabulary(ctx: DiffContext) -> PredicateResult:
    """T0: Detect multi-user vocabulary in added lines (su-auth-001, su-feature-001, su-admin-001)."""
    matches: list[str] = []
    for line in ctx.added_lines:
        for pat in _MULTI_USER_PATTERNS:
            m = pat.search(line)
            if m:
                matches.append(m.group(0))
    return PredicateResult(
        predicate_id="multi-user-vocabulary",
        axiom_id="single_user",
        implication_id="su-auth-001",
        tier="T0",
        passed=len(matches) == 0,
        matches=tuple(matches),
        description="Added lines contain multi-user vocabulary",
    )


def check_protected_module_deps(ctx: DiffContext) -> PredicateResult:
    """T0: Detect new imports of protected governance modules in non-governance files."""
    matches: list[str] = []
    governance_dirs = (
        "shared/governance/",
        "shared/axiom_",
        "agents/_axiom_",
        "agents/_governance",
    )
    is_governance_change = any(f.startswith(governance_dirs) for f in ctx.changed_files)
    if not is_governance_change:
        for line in ctx.added_lines:
            stripped = line.strip()
            for pat in _PROTECTED_IMPORT_PATTERNS:
                if pat.match(stripped):
                    matches.append(stripped)
    return PredicateResult(
        predicate_id="protected-module-deps",
        axiom_id="single_user",
        implication_id="su-security-001",
        tier="T0",
        passed=len(matches) == 0,
        matches=tuple(matches),
        description="Non-governance files importing protected governance modules",
    )


def check_multi_tenant_security(ctx: DiffContext) -> PredicateResult:
    """T0: Detect rate-limiting-per-user or multi-tenant security patterns (su-security-001)."""
    rate_limit_pat = re.compile(
        r"(?<![a-z])rate[_\-]?limit.*(?:user|tenant|per[_\-]?user)", re.IGNORECASE
    )
    tenant_isolation_pat = re.compile(
        r"(?<![a-z])tenant[_\-]?isolat(?:ion|e|ed|ing)", re.IGNORECASE
    )
    matches: list[str] = []
    for line in ctx.added_lines:
        for pat in (rate_limit_pat, tenant_isolation_pat):
            m = pat.search(line)
            if m:
                matches.append(m.group(0))
    return PredicateResult(
        predicate_id="multi-tenant-security",
        axiom_id="single_user",
        implication_id="su-security-001",
        tier="T0",
        passed=len(matches) == 0,
        matches=tuple(matches),
        description="Added lines contain multi-tenant security patterns",
    )


# All T0/T1 predicates, in evaluation order.
T0_PREDICATES = (
    check_multi_user_vocabulary,
    check_protected_module_deps,
    check_multi_tenant_security,
)


def evaluate_deterministic(ctx: DiffContext) -> list[PredicateResult]:
    """Run all deterministic predicates. Returns list of results (pass or fail)."""
    return [pred(ctx) for pred in T0_PREDICATES]
