"""Industrial audio naming helpers.

The live PipeWire ``node.name`` strings remain compatibility handles until the
graph daemon owns deployment. This module defines the consultable SSOT naming
surface: stable, hierarchical names that describe role and responsibility
without ad-hoc ``hapax-*`` or incident-era nicknames.
"""

from __future__ import annotations

import re

INDUSTRIAL_AUDIO_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*){2,}$")
AD_HOC_AUDIO_NAME_TOKENS: frozenset[str] = frozenset(
    {
        "evilpet",
        "hapax",
        "ytube",
    }
)


def industrial_audio_name_violations(value: str | None) -> tuple[str, ...]:
    """Return naming-rule violations for a proposed industrial audio name."""

    text = (value or "").strip()
    if not text:
        return ("missing",)
    violations: list[str] = []
    if INDUSTRIAL_AUDIO_NAME_RE.fullmatch(text) is None:
        violations.append("not_hierarchical_lowercase_dot_name")
    compact = re.sub(r"[^a-z0-9]+", "", text.lower())
    for token in sorted(AD_HOC_AUDIO_NAME_TOKENS):
        if token in compact:
            violations.append(f"ad_hoc_token:{token}")
    return tuple(violations)


def validate_industrial_audio_name(value: str | None) -> str | None:
    """Validate an optional industrial name for Pydantic field validators."""

    if value is None:
        return None
    text = value.strip()
    violations = industrial_audio_name_violations(text)
    if violations:
        raise ValueError(f"invalid industrial audio name {text!r}: {', '.join(violations)}")
    return text


__all__ = [
    "AD_HOC_AUDIO_NAME_TOKENS",
    "INDUSTRIAL_AUDIO_NAME_RE",
    "industrial_audio_name_violations",
    "validate_industrial_audio_name",
]
