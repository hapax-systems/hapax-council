"""Capability catalogue resolution and inert dispatch-intake projection.

The platform capability registry is a catalogue plus typed, time-bounded evidence.
Catalogue membership never proves that a capability is currently available.  Current
availability is projected only from ``check_registry_freshness`` over a validated
``PlatformCapabilityRegistry``.  This module does not launch workers, admit actions,
write ledgers, or infer authority from human-readable dispatcher output.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

from shared.methodology_dispatch_carrier import (
    DISPATCH_CORRELATION_SCHEMA,
    METHODOLOGY_DISPATCH_CARRIER_HASH_BASIS,
    METHODOLOGY_DISPATCH_CARRIER_SCHEMA,
    MethodologyDispatchCarrierError,
    build_dispatch_support_fact,
    canonical_dispatch_carrier_bytes,
    seal_methodology_dispatch_carrier,
    validate_methodology_dispatch_carrier,
)
from shared.platform_capability_registry import (
    PLATFORM_CAPABILITY_REGISTRY,
    PlatformCapabilityRegistry,
    PlatformCapabilityRegistryError,
    check_registry_freshness,
    load_platform_capability_registry,
)

DEFAULT_REGISTRY_PATH = PLATFORM_CAPABILITY_REGISTRY

# Friendly names are catalogue aliases only.  Neither this table nor a route's
# presence in ``required_route_ids`` is supply, availability, admission, or authority.
CAPABILITY_ALIASES: dict[str, str] = {
    "codex": "codex.headless.full",
    "codex-spark": "codex.headless.spark",
    "claude": "claude.headless.full",
    "claude-opus": "claude.headless.opus",
    "claude-sonnet": "claude.headless.sonnet",
    "claude-haiku": "claude.headless.haiku",
    "claude-interactive": "claude.interactive.full",
    "claude-review": "claude.review.opus",
    "api": "api.headless.provider_gateway",
    "api-frontier": "api.headless.api_frontier",
    "openrouter": "api.headless.openrouter",
    "openrouter-frontier": "api.headless.openrouter",
    "vibe": "vibe.headless.full",
    "agy": "agy.review.direct",
    "agy-review": "agy.review.direct",
    "glmcp-review": "glmcp.review.direct",
    "local-worker": "local_tool.local.worker",
}

# Known names with no current catalogue route.  They are explicit holds, not aliases
# and not supply inferred from an installed binary, wrapper, or operator prose.
UNROUTED_POINTERS: dict[str, str] = {
    "antigrav": "Antigrav is deprecated and excised; no dispatch route exists.",
    "antigravity": "Antigrav is deprecated and excised; no dispatch route exists.",
    "antigrav.interactive.full": "Antigrav is deprecated and excised; no route exists.",
    "gemini-cli": "Gemini CLI is retired; engines behind another harness are not routes.",
    "fugu": "No governed route is catalogued; descriptor and measured supply are required.",
    "fugu-ultra": "No governed route is catalogued; descriptor and measured supply are required.",
    "gemini": "Gemini is an engine label, not a catalogued capability route.",
    "sakana": "No governed Sakana/Fugu route is catalogued.",
    "glmcp": "The review route is not a worker route; measured worker supply is absent.",
    "glm": "The review route is not a worker route; measured worker supply is absent.",
}

DISPATCH_CARRIER_SCHEMA = METHODOLOGY_DISPATCH_CARRIER_SCHEMA
DISPATCH_CARRIER_HASH_BASIS = METHODOLOGY_DISPATCH_CARRIER_HASH_BASIS


class CapabilityState(StrEnum):
    """Epistemically distinct capability states."""

    CATALOGUED = "catalogued"
    AVAILABLE = "available"
    HELD = "held"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CapabilityResolution:
    capability: str
    state: CapabilityState
    reason: str
    route_id: str | None = None
    platform: str | None = None
    mode: str | None = None
    profile: str | None = None
    checked_at: str | None = None
    evidence_refs: tuple[str, ...] = ()
    blocker_reasons: tuple[str, ...] = ()

    @property
    def catalogued(self) -> bool:
        return self.route_id is not None

    @property
    def available(self) -> bool:
        return self.state is CapabilityState.AVAILABLE


@dataclass(frozen=True)
class CapabilityUtilizationStatus:
    """Truthful status until a canonical lifecycle/outcome projection is bound."""

    state: CapabilityState = CapabilityState.UNKNOWN
    reason: str = (
        "canonical lifecycle outcome/currentness projection is not bound; legacy "
        "methodology JSONL is support-only and cannot prove ACTIVE or LATENT supply"
    )
    legacy_source_authority: str = "support_only_not_consumed"


def default_dispatch_ledger() -> None:
    """Retired import-compatible symbol; no legacy ledger path is authoritative.

    Gate-0A callers that still accept the former positional argument already ignore
    it and hold.  Returning ``None`` makes accidental reuse fail visibly instead of
    reviving a lifetime JSONL file as currentness evidence.
    """

    return None


def split_route_id(route_id: str) -> tuple[str, str, str] | None:
    """Split ``platform.mode.profile`` while retaining dots inside the profile."""

    parts = route_id.split(".", 2)
    if len(parts) != 3 or not all(parts):
        return None
    return parts[0], parts[1], parts[2]


def load_capability_registry(
    path: Path = DEFAULT_REGISTRY_PATH,
    *,
    receipt_dir: Path | None = None,
    now: datetime | None = None,
) -> PlatformCapabilityRegistry:
    """Load the typed registry and its canonical receipt overlays."""

    return load_platform_capability_registry(path, receipt_dir=receipt_dir, now=now)


def registry_error(path: Path = DEFAULT_REGISTRY_PATH) -> str | None:
    """Return a typed registry-load error, if any."""

    try:
        load_capability_registry(path)
    except PlatformCapabilityRegistryError as exc:
        return str(exc)
    return None


def catalogued_route_ids(registry: PlatformCapabilityRegistry) -> frozenset[str]:
    """Return catalogue membership, explicitly not current availability."""

    return frozenset(registry.required_route_ids)


def catalogued_aliases(route_ids: Iterable[str]) -> dict[str, str]:
    """Return aliases whose targets exist in the supplied static catalogue."""

    catalogued = frozenset(route_ids)
    return {
        alias: route_id for alias, route_id in CAPABILITY_ALIASES.items() if route_id in catalogued
    }


def resolve_catalogued_capability(
    name: str,
    *,
    route_ids: Iterable[str],
) -> CapabilityResolution:
    """Resolve a name against static catalogue membership without claiming supply."""

    catalogued = frozenset(route_ids)
    key = name.strip().lower()
    route_id = CAPABILITY_ALIASES.get(key, key if key in catalogued else None)
    if route_id is None:
        if key in UNROUTED_POINTERS:
            return CapabilityResolution(
                capability=name,
                state=CapabilityState.HELD,
                reason=UNROUTED_POINTERS[key],
            )
        known = ", ".join(sorted(CAPABILITY_ALIASES))
        return CapabilityResolution(
            capability=name,
            state=CapabilityState.UNKNOWN,
            reason=f"unknown capability {name!r}; catalogued aliases: {known}",
        )

    if route_id not in catalogued:
        return CapabilityResolution(
            capability=name,
            state=CapabilityState.HELD,
            reason=(
                f"alias maps to {route_id!r}, which is absent from the typed registry catalogue"
            ),
        )

    parts = split_route_id(route_id)
    if parts is None:
        return CapabilityResolution(
            capability=name,
            state=CapabilityState.HELD,
            reason=f"malformed catalogued route_id {route_id!r}",
            route_id=route_id,
        )
    platform, mode, profile = parts
    return CapabilityResolution(
        capability=name,
        state=CapabilityState.CATALOGUED,
        reason="catalogue membership only; current availability has not been evaluated",
        route_id=route_id,
        platform=platform,
        mode=mode,
        profile=profile,
    )


def resolve_capability(
    name: str,
    *,
    registry: PlatformCapabilityRegistry,
    now: datetime | None = None,
) -> CapabilityResolution:
    """Resolve current state exclusively from the typed registry freshness check."""

    base = resolve_catalogued_capability(name, route_ids=registry.required_route_ids)
    if base.route_id is None:
        return base

    result = check_registry_freshness(registry, route_ids=[base.route_id], now=now)
    check = result.routes[0]
    checked_at = result.checked_at.isoformat().replace("+00:00", "Z")
    if not check.supported:
        return CapabilityResolution(
            **{
                **base.__dict__,
                "state": CapabilityState.UNKNOWN,
                "reason": "; ".join(check.errors),
                "checked_at": checked_at,
            }
        )

    blockers = tuple(dict.fromkeys((*check.blocked_reasons, *check.errors)))
    if not check.ok:
        return CapabilityResolution(
            capability=base.capability,
            state=CapabilityState.HELD,
            reason="; ".join(check.errors) or "typed registry policy held the route",
            route_id=base.route_id,
            platform=base.platform,
            mode=base.mode,
            profile=base.profile,
            checked_at=checked_at,
            evidence_refs=check.evidence_refs,
            blocker_reasons=blockers,
        )

    return CapabilityResolution(
        capability=base.capability,
        state=CapabilityState.AVAILABLE,
        reason="typed registry freshness, availability, and policy evidence passed",
        route_id=base.route_id,
        platform=base.platform,
        mode=base.mode,
        profile=base.profile,
        checked_at=checked_at,
        evidence_refs=check.evidence_refs,
    )


def utilization_status() -> CapabilityUtilizationStatus:
    """Refuse false lifetime utilization inference from the legacy JSONL ledger."""

    return CapabilityUtilizationStatus()


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _carrier_hash_basis(carrier: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in carrier.items() if key not in {"carrier_ref", "carrier_hash"}
    }


def dispatch_carrier_hash(carrier: Mapping[str, Any]) -> str:
    basis = _carrier_hash_basis(carrier)
    return sha256(canonical_dispatch_carrier_bytes(basis)).hexdigest()


def verify_dispatch_carrier(carrier: Mapping[str, Any]) -> bool:
    """Verify exact content addressing and the Gate-0A negative-state invariants."""

    try:
        validate_methodology_dispatch_carrier(carrier)
    except MethodologyDispatchCarrierError:
        return False
    return True


def build_dispatch_carrier(
    *,
    resolution: CapabilityResolution,
    task_id: str,
    lane: str,
    requested_operation: str,
    mq_message_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Build a pure, content-addressed intake carrier; never admit or materialize it."""

    if resolution.route_id is None:
        raise ValueError("a dispatch carrier requires a catalogued route")
    if requested_operation not in {"validate", "launch"}:
        raise ValueError("requested_operation must be 'validate' or 'launch'")

    freshness_state = "current" if resolution.checked_at else "unknown"
    support = [
        build_dispatch_support_fact(
            kind="evidence",
            code="capability.name",
            value=resolution.capability,
            freshness_state=freshness_state,
        ),
        build_dispatch_support_fact(
            kind="candidate",
            code="capability.state",
            value=resolution.state.value,
            observed_at=resolution.checked_at,
            freshness_state=freshness_state,
        ),
        build_dispatch_support_fact(
            kind="evidence",
            code="capability.route_id",
            value=resolution.route_id,
            freshness_state=freshness_state,
        ),
        build_dispatch_support_fact(
            kind="evidence",
            code="capability.checked_at",
            value=resolution.checked_at,
            observed_at=resolution.checked_at,
            freshness_state=freshness_state,
        ),
        build_dispatch_support_fact(
            kind="evidence",
            code="capability.evidence_refs",
            value=list(resolution.evidence_refs),
            observed_at=resolution.checked_at,
            freshness_state=freshness_state,
        ),
        build_dispatch_support_fact(
            kind="diagnostic",
            code="capability.blocker_reasons",
            value=list(resolution.blocker_reasons),
            observed_at=resolution.checked_at,
            freshness_state=freshness_state,
        ),
        build_dispatch_support_fact(
            kind="diagnostic",
            code="capability.reason",
            value=resolution.reason,
            observed_at=resolution.checked_at,
            freshness_state=freshness_state,
        ),
        build_dispatch_support_fact(
            kind="diagnostic",
            code="task.validation_state",
            value="not_evaluated",
        ),
    ]
    carrier: dict[str, object] = {
        "event": "methodology_dispatch",
        "lane": lane,
        "launched": False,
        "may_authorize": False,
        "mode": resolution.mode,
        "platform": resolution.platform,
        "profile": resolution.profile,
        "receipt_is_admission": False,
        "requested_operation": requested_operation,
        "correlation": {
            "schema": DISPATCH_CORRELATION_SCHEMA,
            "mq_message_id": mq_message_id,
            "idempotency_key": idempotency_key,
        },
        "support": support,
        "task_id": task_id,
        "effect_state": "held_not_admitted",
        "materialization_state": "not_materialized",
    }
    return seal_methodology_dispatch_carrier(carrier)
