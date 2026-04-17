"""FastAPI dependency + helpers for stream-mode-aware response redaction.

LRR Phase 6 §4.A. This module is the canonical site for per-endpoint
redaction rules that fire when the stream is publicly visible.

Pattern for a route:

    from logos.api.deps.stream_redaction import (
        band,
        is_publicly_visible,
        omit_if_public,
    )

    @router.get("/api/stimmung")
    def get_stimmung() -> dict:
        raw = _assemble_stimmung_snapshot()
        if is_publicly_visible():
            raw["dimensions"] = band_dimensions(raw.get("dimensions", {}))
        return raw

Common operations:

- ``is_publicly_visible()``: thin re-export of the fail-closed reader
  from ``shared.stream_mode``, so routes don't need two imports.
- ``band(value, thresholds, labels)``: reduce a continuous value to a
  categorical label (e.g. heart rate → "nominal" / "elevated" /
  "critical"). Used for biometric + stimmung dimensions.
- ``omit_if_public(response, path)``: drop a dotted-path key from a
  response dict when stream is publicly visible.
- ``redact_field_if_public(response, path, placeholder)``: replace the
  value at ``path`` with ``placeholder`` (default "[redacted]") when
  stream is publicly visible.
- ``pii_redact(text)``: run a PII regex sweep on free text and replace
  matches with "[redacted]". Used for goal next_action and briefing
  action_items where the value is a rendered sentence.

Routes that need whole-endpoint 403 when public should use the
``require_private_stream()`` dependency:

    @router.get("/api/management", dependencies=[Depends(require_private_stream)])
    def get_management(): ...

The module does NOT apply redaction to every route automatically. The
spec §4.A lists 17 specific endpoint/field combinations; per-route
explicit opt-in is the enforcement pattern. A linter check in CI
(deferred Phase 10 follow-up) will grep for endpoints that return
sensitive surfaces (stimmung, profile, perception, management) and
verify a redaction import is present.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from fastapi import HTTPException, status

from shared.stream_mode import is_publicly_visible as _is_publicly_visible


def is_publicly_visible() -> bool:
    """Thin re-export so route files have one import path."""
    return _is_publicly_visible()


def require_private_stream() -> None:
    """FastAPI dependency: 403 the request when stream-mode is publicly visible.

    Use on routes that have no safe public surface (e.g. /api/management,
    /api/chat/history). Routes that return a partially-redactable shape
    should NOT use this — use field-level redaction instead.
    """
    if is_publicly_visible():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="redacted_stream_mode_public",
        )


# ── Banding ─────────────────────────────────────────────────────────────────


def band(
    value: float | None,
    thresholds: Sequence[float],
    labels: Sequence[str],
) -> str | None:
    """Reduce a continuous value to a categorical label.

    ``thresholds`` must be sorted ascending and have ``len(labels) - 1``
    elements: value <= thresholds[0] → labels[0]; between thresholds[i]
    and thresholds[i+1] → labels[i+1]; above the last threshold →
    labels[-1].

    Returns ``None`` when ``value`` is ``None`` (preserves missing-signal
    semantics distinct from a band label).
    """
    if value is None:
        return None
    if len(thresholds) + 1 != len(labels):
        raise ValueError(
            f"band() requires len(labels) == len(thresholds) + 1, got "
            f"{len(labels)} labels for {len(thresholds)} thresholds"
        )
    for i, t in enumerate(thresholds):
        if value <= t:
            return labels[i]
    return labels[-1]


# Canonical band presets keyed off spec §4.A:


def band_heart_rate(bpm: float | None) -> str | None:
    return band(bpm, thresholds=(70.0, 110.0), labels=("nominal", "elevated", "critical"))


def band_hrv(hrv_ms: float | None) -> str | None:
    return band(hrv_ms, thresholds=(30.0,), labels=("reduced", "stable"))


def band_energy(value: float | None) -> str | None:
    return band(value, thresholds=(0.33, 0.66), labels=("low", "medium", "high"))


def band_coherence(value: float | None) -> str | None:
    return band(value, thresholds=(0.5,), labels=("variable", "coherent"))


def band_tension(value: float | None) -> str | None:
    return band(value, thresholds=(0.33, 0.66), labels=("relaxed", "engaged", "stressed"))


# ── Path-walking redaction ──────────────────────────────────────────────────


def _walk(obj: Any, parts: list[str], op: Callable[[dict, str], None]) -> None:
    """Apply ``op(container, last_key)`` at the dotted path ``parts`` in obj.

    Supports nested dicts. Silently no-ops if any intermediate key is
    missing or not a dict — over-redaction on a missing field is
    undesirable (could hide a regression).
    """
    if not parts:
        return
    head, *tail = parts
    if not isinstance(obj, dict):
        return
    if not tail:
        if head in obj:
            op(obj, head)
        return
    child = obj.get(head)
    if isinstance(child, dict):
        _walk(child, tail, op)


def omit_if_public(response: dict, path: str) -> dict:
    """Drop the dotted-path key from response when stream is publicly visible.

    Operates in-place AND returns the dict so callers can chain.
    Examples: ``omit_if_public(resp, "dimensions.skin_temperature_c")``.
    """
    if not is_publicly_visible():
        return response
    _walk(response, path.split("."), lambda c, k: c.pop(k, None))
    return response


def redact_field_if_public(
    response: dict,
    path: str,
    placeholder: str = "[redacted]",
) -> dict:
    """Replace value at dotted path with placeholder when publicly visible."""
    if not is_publicly_visible():
        return response
    _walk(response, path.split("."), lambda c, k: c.__setitem__(k, placeholder))
    return response


# ── PII redaction ────────────────────────────────────────────────────────────

# Conservative patterns — recall > precision is the right tradeoff for
# broadcast safety. False positives only cost readability; false negatives
# cost axiom violation.
_PII_PATTERNS: tuple[re.Pattern, ...] = (
    # Email
    re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    # Phone numbers (US-ish; broad). Country code is optional so plain
    # 3-3-4 strings like "555-123-4567" also match.
    re.compile(r"(?:\+?\d{1,2}[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}"),
    # SSN-shaped
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # Credit-card-shaped (16 digits grouped)
    re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
)


def pii_redact(text: str, placeholder: str = "[redacted]") -> str:
    """Replace PII-pattern matches with placeholder.

    Name redaction is NOT handled here — the spec says route-level name
    redaction goes through the consent registry (check whether person_id
    has an active broadcast contract; omit the whole message if not).
    Names embedded in free text are a Phase 7 persona/persona-aware
    scrubber concern.
    """
    out = text
    for pat in _PII_PATTERNS:
        out = pat.sub(placeholder, out)
    return out


# ── Registry-aware person-id redaction (LRR Phase 6 §4.A briefing/nudges) ───


def references_non_broadcast_person_id(text: str, registry: Any) -> bool:
    """True iff ``text`` mentions a registered person_id lacking an active
    broadcast-scope contract.

    Scans for every non-operator party name in the passed registry. A
    match is case-insensitive substring. If any matched person lacks a
    contract scoped to ``"broadcast"``, the text is considered non-safe
    for a public stream.

    Caller provides the registry (typically a ``ConsentRegistry`` from
    ``logos._governance``) so this module stays agnostic of the specific
    registry implementation — anything iterable over contracts-with-
    ``parties`` and with a ``contract_check(pid, "broadcast")`` method
    works.
    """
    if not text:
        return False
    lower = text.lower()
    seen: set[str] = set()
    for contract in registry:
        for party in getattr(contract, "parties", ()):
            if not party or party == "operator":
                continue
            if party in seen:
                continue
            seen.add(party)
            if party.lower() in lower and not registry.contract_check(party, "broadcast"):
                return True
    return False
