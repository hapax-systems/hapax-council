"""Publication allowlist — consent-contract gating for outbound autonomous posts.

Every autonomous network emit on an outbound surface (YouTube title /
description / tags / thumbnail / chapters / livechat, channel trailer /
sections, Bluesky / Discord / Mastodon, pinned comments) walks
``check(surface, state_kind, payload)`` before the network call.

Contracts live at ``axioms/contracts/publication/{surface}.yaml`` and declare
which state kinds may flow to that surface, what payload keys to redact
before emit, and per-surface rate-limit budgets (informational; daemon-side
enforcement at the API client layer).

**Default DENY**: absence of contract means no autonomous emit allowed for
that surface. Contract additions are operator-reviewed governance changes,
not implicit defaults.

Anchors the ``interpersonal_transparency`` axiom (weight 88): each contract
is an explicit declaration of what Hapax may expose publicly about itself or
its perceptual state.

Spec: cc-task ytb-002 (publication allowlist via consent contracts).
"""

from __future__ import annotations

import functools
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import yaml

log = logging.getLogger(__name__)

Decision = Literal["allow", "redact", "deny"]

_CONTRACTS_DIR = Path(__file__).parent.parent.parent / "axioms" / "contracts" / "publication"


@dataclass(frozen=True)
class PublicationContract:
    """Per-surface allowlist contract loaded from YAML.

    Schema mirrors ``axioms/contracts/publication/{surface}.yaml``. Immutable
    once parsed; caller-side mutation requires editing the YAML and reloading.
    """

    surface: str
    state_kinds: tuple[str, ...] = ()
    redactions: tuple[str, ...] = ()
    rate_limit_per_hour: int = 0
    rate_limit_per_day: int = 0
    cadence_hint: str = ""


@dataclass
class AllowlistResult:
    """Outcome of an allowlist check.

    ``payload`` is the (possibly redacted) content the caller should emit on
    REDACT, the original payload on ALLOW, or the original payload on DENY
    (caller skips the emit entirely on DENY).
    """

    decision: Decision
    payload: dict | str
    reason: str


try:
    from prometheus_client import Counter

    _DECISIONS = Counter(
        "hapax_broadcast_publication_allowlist_decisions_total",
        "Publication allowlist decisions by surface and outcome.",
        ["surface", "decision"],
    )

    def _record(surface: str, decision: Decision) -> None:
        _DECISIONS.labels(surface=surface, decision=decision).inc()

except ImportError:  # pragma: no cover

    def _record(surface: str, decision: Decision) -> None:
        log.debug("prometheus unavailable; surface=%s decision=%s", surface, decision)


def _parse_contract(surface: str, data: dict) -> PublicationContract:
    rate_limit = data.get("rate_limit") or {}
    return PublicationContract(
        surface=surface,
        state_kinds=tuple(data.get("state_kinds") or ()),
        redactions=tuple(data.get("redactions") or ()),
        rate_limit_per_hour=int(rate_limit.get("per_hour") or 0),
        rate_limit_per_day=int(rate_limit.get("per_day") or 0),
        cadence_hint=str(data.get("cadence_hint") or ""),
    )


def load_contract(surface: str, contracts_dir: Path | None = None) -> PublicationContract | None:
    """Load a single surface's contract from disk.

    Returns None if the file is absent or malformed (logged at WARN). Callers
    treat None as DENY by default.
    """
    directory = contracts_dir or _CONTRACTS_DIR
    path = directory / f"{surface}.yaml"
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        log.exception("Failed to load publication contract from %s", path)
        return None
    if not isinstance(data, dict):
        log.warning("publication contract %s: not a YAML mapping", path)
        return None
    return _parse_contract(surface, data)


def _pattern_matches(pattern: str, value: str) -> bool:
    """Match ``value`` against ``pattern``.

    Wildcard suffix ``.*`` or ``*`` matches any value with the corresponding
    prefix. Exact match otherwise. Empty patterns never match.
    """
    if not pattern:
        return False
    if pattern == value:
        return True
    if pattern.endswith(".*"):
        return value.startswith(pattern[:-1])
    if pattern.endswith("*"):
        return value.startswith(pattern[:-1])
    return False


# ── Redaction transform registry (AUDIT-22 Phase A + B + B-2) ───────────
#
# Named transforms operating on string content. Each transform takes a
# string + returns a string with sensitive substrings replaced by
# ``[REDACTED]``. Registered by name so contract ``redactions:`` entries
# can name them uniformly (``- operator_legal_name``,
# ``- email_address``).
#
# Phase A: registry + transforms + tests.
# Phase B: wire registry into ``_apply_redactions`` so string payloads
# get the named-transform pipeline applied per contract redactions list.
# Phase B-2: ``legal_name`` → ``operator_legal_name`` rename to align
# with contract entry naming + ``HAPAX_OPERATOR_NAME`` env semantics.
#
# Spec: v4 §3.4.2 AUDIT-22 acceptance — RedactionTransform registry
# (transforms registered by name: operator_legal_name, email_address,
# gps_coordinate, applied per `redactions:` field uniformly).

# RFC-5322-shaped email; intentionally a tighter matcher than the
# canonical regex (we want false negatives over false positives in the
# redaction context — better to miss a corner-case email than to
# accidentally redact a non-email).
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# Decimal-degree coordinate pair: ``lat, lon`` with optional sign and
# 1-3 decimal-degree places. Coordinates without a comma-separated
# pair (single decimals like "version 1.0") do not match.
_GPS_PATTERN = re.compile(r"-?\d{1,3}\.\d{2,}\s*,\s*-?\d{1,3}\.\d{2,}")

REDACTION_MARKER: Final[str] = "[REDACTED]"


class RedactionTransformNotFound(KeyError):
    """Raised when ``apply_named_transform`` is called with a name not in
    :data:`REDACTION_TRANSFORMS`. Subclasses :class:`KeyError` so callers
    that already except KeyError around registry lookups inherit the
    fail-closed default."""


def _operator_legal_name_transform(content: str) -> str:
    """Redact ``HAPAX_OPERATOR_NAME`` env-supplied legal name (case-
    insensitive substring). Empty / unset env disables the transform —
    an empty pattern would match every string trivially."""
    pattern = os.environ.get("HAPAX_OPERATOR_NAME", "")
    if not pattern:
        return content
    return re.sub(re.escape(pattern), REDACTION_MARKER, content, flags=re.IGNORECASE)


def _email_address_transform(content: str) -> str:
    """Redact RFC-5322-shaped email addresses."""
    return _EMAIL_PATTERN.sub(REDACTION_MARKER, content)


def _gps_coordinate_transform(content: str) -> str:
    """Redact decimal-degree coordinate pairs (``lat, lon``)."""
    return _GPS_PATTERN.sub(REDACTION_MARKER, content)


REDACTION_TRANSFORMS: Final[dict[str, Callable[[str], str]]] = {
    "operator_legal_name": _operator_legal_name_transform,
    "email_address": _email_address_transform,
    "gps_coordinate": _gps_coordinate_transform,
}


def apply_named_transform(name: str, content: str) -> str:
    """Look up a named transform and apply it to ``content``.

    Raises :class:`RedactionTransformNotFound` for unknown names — the
    fail-closed default keeps unrecognized transform names from
    silently no-op'ing in production. Phase B's contract-side
    validator (the linter component of AUDIT-22) flags unknown names
    at contract load time so production never reaches this raise on
    a known-deployed contract.
    """
    transform = REDACTION_TRANSFORMS.get(name)
    if transform is None:
        raise RedactionTransformNotFound(f"unknown redaction transform: {name!r}")
    return transform(content)


def _apply_redactions(payload: dict | str, redactions: tuple[str, ...]) -> tuple[dict | str, bool]:
    """Apply contract redactions to ``payload``.

    Two payload shapes:

    * **dict**: drop any key whose name matches a redaction pattern
      (existing behavior; wildcard matching via :func:`_pattern_matches`).
      Redaction entries that name a registered transform (eg.
      ``operator_legal_name``) are skipped on dict payloads — the
      transform operates on string content, not on dict keys.
    * **string** (AUDIT-22 Phase B): for each redaction entry that
      names a :data:`REDACTION_TRANSFORMS` entry, apply the transform
      to the string content. Entries that aren't registered transforms
      are no-ops on string content (they're dict-key patterns, which
      don't apply to strings).
    """
    if not redactions:
        return payload, False
    if isinstance(payload, str):
        result = payload
        changed = False
        for r in redactions:
            if r in REDACTION_TRANSFORMS:
                new_result = apply_named_transform(r, result)
                if new_result != result:
                    changed = True
                    result = new_result
        return result, changed
    if not isinstance(payload, dict):
        return payload, False
    out = dict(payload)
    changed = False
    for key in list(out.keys()):
        if any(_pattern_matches(r, key) for r in redactions):
            del out[key]
            changed = True
    return out, changed


def check(
    surface: str,
    state_kind: str,
    payload: dict | str,
    *,
    contract: PublicationContract | None = None,
    contracts_dir: Path | None = None,
) -> AllowlistResult:
    """Walk the per-surface allowlist for (surface × state_kind × payload).

    Default DENY when no contract exists for ``surface``. Wildcard matching
    on ``state_kinds``: ``chronicle.*`` matches ``chronicle.high_salience``.
    Redactions drop payload keys matching the same wildcard syntax.

    ``contract`` and ``contracts_dir`` are test/override hooks; production
    callers pass neither and the function loads from
    ``axioms/contracts/publication/``.
    """
    if contract is None:
        contract = load_contract(surface, contracts_dir)
    if contract is None:
        _record(surface, "deny")
        return AllowlistResult(
            decision="deny",
            payload=payload,
            reason=f"no contract for surface '{surface}' (default DENY)",
        )

    if not any(_pattern_matches(k, state_kind) for k in contract.state_kinds):
        _record(surface, "deny")
        return AllowlistResult(
            decision="deny",
            payload=payload,
            reason=(f"state_kind '{state_kind}' not in allowed {list(contract.state_kinds)}"),
        )

    redacted, changed = _apply_redactions(payload, contract.redactions)
    if changed:
        _record(surface, "redact")
        return AllowlistResult(
            decision="redact",
            payload=redacted,
            reason=f"applied redactions {list(contract.redactions)}",
        )

    _record(surface, "allow")
    return AllowlistResult(decision="allow", payload=payload, reason="allowed")


def gated(
    surface: str,
    state_kind: str,
    *,
    contracts_dir: Path | None = None,
) -> Callable:
    """Decorator: gate a publish function by walking ``check()`` first.

    The decorated function is invoked with the (possibly redacted) payload on
    ALLOW or REDACT, and skipped (returning None) on DENY.

        @gated("youtube-title", "chronicle.high_salience")
        def publish_title(payload: dict) -> None:
            client.execute(...)
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(payload: dict | str, *args, **kwargs):
            result = check(surface, state_kind, payload, contracts_dir=contracts_dir)
            if result.decision == "deny":
                log.info("DENY %s × %s: %s", surface, state_kind, result.reason)
                return None
            return fn(result.payload, *args, **kwargs)

        return wrapper

    return decorator
