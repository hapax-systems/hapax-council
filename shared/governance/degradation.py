"""Per-category degradation functions for consent-gated retrieval.

Produces natural language, not redaction markers. "Meeting with 3 people at 3pm"
instead of "[REDACTED] [REDACTED] meeting at 3pm".

Degradation levels:
    1 — Full access (all persons consented)
    2 — Abstraction (replace unconsented person IDs with counts/roles)
    3 — Existence only ("You have 3 events today" with no detail)
    4 — Suppress (return nothing)

Default is Level 2 (abstraction). Level 3/4 reserved for future use.
"""

from __future__ import annotations

import re


def degrade_calendar(content: str, unconsented: frozenset[str]) -> str:
    """Degrade calendar event text by abstracting unconsented person names.

    Input:  "- 2026-03-15T10:00: Team sync (with Alice, Bob, charlie@corp.com)"
    Output: "- 2026-03-15T10:00: Team sync (with 3 people)"
    (when all three are unconsented)
    """
    if not unconsented:
        return content

    result = content

    # Replace "(with Name1, Name2, ...)" blocks
    def _replace_with_block(match: re.Match) -> str:
        names_str = match.group(1)
        names = [n.strip() for n in names_str.split(",") if n.strip()]
        remaining = [n for n in names if not _matches_any(n, unconsented)]
        removed_count = len(names) - len(remaining)

        if removed_count == 0:
            return match.group(0)
        if not remaining:
            noun = "person" if removed_count == 1 else "people"
            return f"(with {removed_count} {noun})"
        noun = "other" if removed_count == 1 else "others"
        return f"(with {', '.join(remaining)} and {removed_count} {noun})"

    result = re.sub(r"\(with\s+([^)]+)\)", _replace_with_block, result)

    # Replace any remaining unconsented identifiers in the text
    result = _replace_identifiers(result, unconsented)

    return result


def degrade_email(content: str, unconsented: frozenset[str]) -> str:
    """Degrade email text by abstracting unconsented person identifiers.

    Input:  "From: alice@corp.com | Subject: Q2 Budget"
    Output: "From: [someone at corp.com] | Subject: Q2 Budget"
    """
    if not unconsented:
        return content

    result = content

    for person_id in unconsented:
        if "@" in person_id:
            domain = person_id.split("@", 1)[1]
            result = result.replace(person_id, f"[someone at {domain}]")
        else:
            result = _replace_name(result, person_id)

    return result


def degrade_document(content: str, unconsented: frozenset[str]) -> str:
    """Degrade document text by abstracting unconsented person identifiers.

    Input:  "Alice mentioned the budget was over target"
    Output: "Someone mentioned the budget was over target"
    """
    if not unconsented:
        return content

    result = content
    for person_id in unconsented:
        if "@" in person_id:
            domain = person_id.split("@", 1)[1]
            result = result.replace(person_id, f"[someone at {domain}]")
        else:
            result = _replace_name(result, person_id)

    return result


def degrade_default(content: str, unconsented: frozenset[str]) -> str:
    """Default degradation: replace unconsented person identifiers generically."""
    if not unconsented:
        return content

    result = content
    for person_id in unconsented:
        if "@" in person_id:
            domain = person_id.split("@", 1)[1]
            result = result.replace(person_id, f"[someone at {domain}]")
        else:
            result = _replace_name(result, person_id)

    return result


# ── Category dispatch ────────────────────────────────────────────────────────

DEGRADATION_FNS: dict[str, object] = {
    "calendar": degrade_calendar,
    "email": degrade_email,
    "document": degrade_document,
}


def degrade(content: str, unconsented: frozenset[str], category: str = "default") -> str:
    """Apply category-appropriate degradation to content.

    Args:
        content: The text to degrade.
        unconsented: Set of person identifiers that lack consent.
        category: Data category ("calendar", "email", "document", or "default").

    Returns:
        Content with unconsented person identifiers abstracted.
    """
    fn = DEGRADATION_FNS.get(category, degrade_default)
    return fn(content, unconsented)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _matches_any(name: str, identifiers: frozenset[str]) -> bool:
    """Check if a name matches any identifier (case-insensitive, email-aware)."""
    name_lower = name.strip().lower()
    for ident in identifiers:
        if ident.lower() == name_lower:
            return True
        # Match "Alice" against "alice@corp.com"
        if "@" in ident and ident.split("@")[0].lower() == name_lower:
            return True
    return False


def _replace_name(text: str, name: str) -> str:
    """Replace a person name with 'someone', preserving sentence case."""
    # Case-insensitive replacement with word boundaries
    pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)

    def _repl(match: re.Match) -> str:
        original = match.group(0)
        if original[0].isupper():
            return "Someone"
        return "someone"

    return pattern.sub(_repl, text)


def _replace_identifiers(text: str, unconsented: frozenset[str]) -> str:
    """Replace all unconsented identifiers in text."""
    result = text
    for person_id in unconsented:
        if "@" in person_id:
            domain = person_id.split("@", 1)[1]
            result = result.replace(person_id, f"[someone at {domain}]")
        else:
            result = _replace_name(result, person_id)
    return result
