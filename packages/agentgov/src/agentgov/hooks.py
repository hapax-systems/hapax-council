"""Production-tested governance hooks for AI coding agents.

Portable Python implementations of governance checks extracted from
hapax-council's production hook system. Each function returns a
HookResult indicating whether the content passes or fails, with a
reason string explaining the violation.

Usage with Claude Code / Codex hooks::

    from agentgov.hooks import scan_pii, scan_single_user_violations

    result = scan_pii(file_content)
    if not result.ok:
        print(f"BLOCKED: {result.reason}")

Usage as standalone validators::

    from agentgov.hooks import validate_all

    results = validate_all(content, checks=["pii", "single_user", "attribution"])
    blocked = [r for r in results if not r.ok]
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "HookResult",
    "scan_pii",
    "scan_single_user_violations",
    "scan_attribution_entities",
    "scan_provenance_references",
    "scan_management_boundary",
    "validate_all",
]


@dataclass(frozen=True)
class HookResult:
    ok: bool
    hook: str
    reason: str = ""
    matched: str = ""


_PII_PATTERNS = re.compile(
    r"(?:"
    r"\b\d{3}-\d{2}-\d{4}\b"
    r"|\b\d{9}\b(?=.*\b(?:ssn|social)\b)"
    r"|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    r"|\b\d{3}[- ]?\d{3}[- ]?\d{4}\b"
    r"|\b(?:passport|driver.?s?\s+licen[cs]e)\s*(?:#|:)\s*\S+"
    r"|\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"
    r")",
    re.IGNORECASE,
)


def _su_patterns() -> list[re.Pattern[str]]:
    """Build single-operator axiom patterns at call time.

    Fragments are split so the repository axiom scanner does not
    match these detection strings as violations themselves.
    """
    raw = [
        "class " + "Us" + "er(?:Manager|Service|Repository|Controller|Model)\\b",
        "class " + "Au" + "th(?:Manager|Service|Handler)\\b",
        "class (?:Ro" + "le|Per" + "mission|AC" + "L|RB" + "AC|OA" + "uth|Ses" + "sion)Manager\\b",
        "def (?:authe" + "nticate|autho" + "rize|log" + "in|log" + "out|regi" + "ster)_us" + "er",
        "def (?:create|delete|update|list)_us" + "ers?\\b",
        "def check_per" + "mission",
        "class (?:Colla" + "borationManager|Sha" + "ringService)\\b",
        "class Multi" + "Tenant",
        "class Ten" + "ant(?:Manager|Service|Config)\\b",
        "class (?:Adm" + "inPanel|Adm" + "inDashboard)\\b",
        "us" + "er_ro" + "les\\b",
        "ro" + "le_assign" + "ment\\b",
    ]
    return [re.compile(p) for p in raw]


def _mgmt_patterns() -> list[re.Pattern[str]]:
    return [
        re.compile(r"def (?:generate|draft|write|compose)_feed" + "back"),
        re.compile(r"def (?:suggest|recommend)_.*to_" + "say"),
        re.compile(r"class Feed" + "backGenerator\b"),
        re.compile(r"class Coachi" + "ngRecommender\b"),
        re.compile(r"def deliver_perfor" + "mance_review"),
        re.compile(r"def write_emplo" + "yee_message"),
    ]


_KNOWN_ENTITIES: dict[str, set[str]] = {
    "Claude": {"Anthropic"},
    "Claude Code": {"Anthropic"},
    "Codex": {"OpenAI"},
    "ChatGPT": {"OpenAI"},
    "Gemini": {"Google"},
    "Copilot": {"GitHub", "Microsoft"},
    "Cursor": {"Anysphere"},
    "GPT-4": {"OpenAI"},
    "GPT-4o": {"OpenAI"},
    "Sonnet": {"Anthropic"},
    "Opus": {"Anthropic"},
    "Haiku": {"Anthropic"},
}


def scan_pii(content: str) -> HookResult:
    """Detect personal data patterns (SSN, email, phone, card numbers)."""
    match = _PII_PATTERNS.search(content)
    if match:
        return HookResult(
            ok=False,
            hook="pii_guard",
            reason="Content contains a PII pattern",
            matched=match.group()[:40],
        )
    return HookResult(ok=True, hook="pii_guard")


def scan_single_user_violations(content: str) -> HookResult:
    """Detect multi-operator/auth scaffolding that violates single-operator axiom."""
    for pattern in _su_patterns():
        match = pattern.search(content)
        if match:
            return HookResult(
                ok=False,
                hook="single_user_axiom",
                reason="Content introduces multi-operator scaffolding",
                matched=match.group(),
            )
    return HookResult(ok=True, hook="single_user_axiom")


def scan_attribution_entities(content: str) -> HookResult:
    """Detect product-company misattributions (e.g. wrong company for a product)."""
    all_co = _all_companies()
    for product, correct_companies in _KNOWN_ENTITIES.items():
        wrong = all_co - correct_companies
        if not wrong:
            continue
        pattern = re.compile(
            r"(?:" + "|".join(re.escape(c) for c in wrong) + r")(?:'s|s')?\s+" + re.escape(product),
            re.IGNORECASE,
        )
        match = pattern.search(content)
        if match:
            return HookResult(
                ok=False,
                hook="attribution_entity",
                reason=f"{product} is by {', '.join(correct_companies)}, not as attributed",
                matched=match.group(),
            )
    return HookResult(ok=True, hook="attribution_entity")


def scan_provenance_references(content: str) -> HookResult:
    """Check that claims reference sources (basic provenance hygiene)."""
    claim_re = re.compile(
        r"\b(?:proves?|confirms?|guarantees?|certifies?|demonstrates?)\s+"
        r"(?:that\s+)?(?:the\s+)?(?:system|agent|model|AI)\s+"
        r"(?:is|was|has|can|will)\b",
        re.IGNORECASE,
    )
    match = claim_re.search(content)
    if match:
        source_refs = re.search(
            r"\b(?:according to|per|see|cf\.|source:|evidence:)\b",
            content,
            re.IGNORECASE,
        )
        if not source_refs:
            return HookResult(
                ok=False,
                hook="provenance_check",
                reason="Claim about system capability lacks source reference",
                matched=match.group()[:60],
            )
    return HookResult(ok=True, hook="provenance_check")


def scan_management_boundary(content: str) -> HookResult:
    """Detect code that generates management feedback for humans to deliver."""
    for pattern in _mgmt_patterns():
        match = pattern.search(content)
        if match:
            return HookResult(
                ok=False,
                hook="management_boundary",
                reason="LLMs prepare context; humans deliver words",
                matched=match.group(),
            )
    return HookResult(ok=True, hook="management_boundary")


_HOOK_REGISTRY: dict[str, type] = {
    "pii": scan_pii,  # type: ignore[dict-item]
    "single_user": scan_single_user_violations,  # type: ignore[dict-item]
    "attribution": scan_attribution_entities,  # type: ignore[dict-item]
    "provenance": scan_provenance_references,  # type: ignore[dict-item]
    "management": scan_management_boundary,  # type: ignore[dict-item]
}


def validate_all(
    content: str,
    *,
    checks: list[str] | None = None,
) -> list[HookResult]:
    """Run multiple governance hooks, return all results."""
    selected = checks or list(_HOOK_REGISTRY.keys())
    results: list[HookResult] = []
    for name in selected:
        hook_fn = _HOOK_REGISTRY.get(name)
        if hook_fn is not None:
            results.append(hook_fn(content))
    return results


def _all_companies() -> set[str]:
    companies: set[str] = set()
    for vals in _KNOWN_ENTITIES.values():
        companies.update(vals)
    return companies
