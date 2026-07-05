"""CapabilityHarnessDescriptor — the authoritative 12-shape capability schema (the substrate).

This is the descriptor layer the capability framework was missing. The existing
``capability_adapter_protocol.py`` is the RUNTIME harness-adapter (describe/admit/launch/send — a FINAL
facade over the dispatch functions); the existing ``platform_capability_registry`` is the route/resource
registry. What was missing is the DESCRIPTOR — the schema every capability (all 12 shapes) must satisfy, so
the seven parallel capability vocabularies (platform-capability-registry, world-capability-registry,
capability-classification-inventory, grounding-providers, the MODELS dict, the publication-bus
surface_registry, the mcp-connector-tool-manifest) reconcile against ONE vocabulary — and the
``capability_surface_delta`` (``discover()``) that makes a missing/boutique capability surface a failing
check rather than a manual find.

Authoritative source: ``~/Documents/Personal/30-areas/hapax/capability-abstraction-and-harness-taxonomy-2026-06-30.md``
(declared the capability vocabulary SSOT 2026-07-03). The Minimum Capability Descriptor + the shape-specific
required facts below mirror that taxonomy's §"Minimum Capability Descriptor" + §"Shape Taxonomy".
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

__all__ = [
    "AuthorityCeiling",
    "CapabilityAction",
    "CapabilityDomain",
    "CapabilityHarnessDescriptor",
    "CapabilityShape",
    "CapabilitySurfaceDelta",
    "CostSource",
    "DeltaKind",
    "FreshnessState",
    "QuotaSource",
    "SHAPE_REQUIRED_FACTS",
    "descriptor_fingerprint",
    "discover",
    "validate_descriptor",
]


# ── the 12-shape vocabulary (the authoritative capability taxonomy) ───────────


class CapabilityShape(StrEnum):
    """The 12 capability shapes — the authoritative vocabulary (taxonomy SSOT)."""

    RAW_MODEL = "raw_model"
    HOSTED_MODEL = "hosted_model"
    MODEL_EFFORT_SLICE = "model_effort_slice"
    EXISTING_AGENT_HARNESS = "existing_agent_harness"
    REVIEW_SEAT = "review_seat"
    LOCAL_TOOL = "local_tool"
    PROVIDER_GATEWAY = "provider_gateway"
    PUBLIC_EGRESS = "public_egress"
    MONEY_RAIL = "money_rail"
    BACKGROUND_SERVICE = "background_service"
    ORCHESTRATOR = "orchestrator"
    CAPABILITY_AGGREGATOR = "capability_aggregator"


class CapabilityDomain(StrEnum):
    """The capability domain — the surface family a shape belongs to."""

    LLM_WORKER = "llm_worker"
    REVIEW = "review"
    CCTV = "cctv"
    PUBLICATION = "publication"
    PAYMENT = "payment"
    LOCAL_COMPUTE = "local_compute"
    DEVICE = "device"
    RESOURCE = "resource"
    ORCHESTRATION = "orchestration"


class CapabilityAction(StrEnum):
    """The actions a capability can perform (the action space)."""

    REASON = "reason"
    IMPLEMENT = "implement"
    REVIEW = "review"
    VERIFY = "verify"
    PUBLISH = "publish"
    RECEIVE = "receive"
    QUERY = "query"
    MUTATE = "mutate"
    ACTUATE = "actuate"
    OBSERVE = "observe"
    ORCHESTRATE = "orchestrate"
    GROUND = "ground"


class FreshnessState(StrEnum):
    """The freshness state of a capability's determinations."""

    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    ABSENT = "absent"
    DARK = "dark"
    HOLD = "hold"


class QuotaSource(StrEnum):
    LEDGER = "ledger"
    PROVIDER = "provider"
    MANUAL = "manual"
    NONE = "none"


class CostSource(StrEnum):
    LEDGER = "ledger"
    PROVIDER = "provider"
    ESTIMATE = "estimate"
    NONE = "none"


class AuthorityCeiling(StrEnum):
    """The maximum allowed effect of a capability invocation."""

    READ_ONLY = "read_only"
    REPO_MUTATION = "repo_mutation"
    PUBLIC_PUBLISH = "public_publish"
    RECEIVE_ONLY_MONEY = "receive_only_money"
    PROVISION = "provision"


# ── the Minimum Capability Descriptor (the authoritative schema) ──────────────


class CapabilityHarnessDescriptor(BaseModel):
    """The Minimum Capability Descriptor — every capability (all 12 shapes) must satisfy this schema.

    A capability is the smallest supply slice whose selection changes expected outcome, cost, authority,
    risk, or evidence. Identity is intrinsic (what is selected), not positional (where it runs now). See
    the taxonomy §"Minimum Capability Descriptor".
    """

    capability_id: str = Field(..., description="Stable capability identity.")
    display_name: str = Field(..., description="Human-readable name (must not duplicate metadata).")
    shape: CapabilityShape = Field(..., description="The capability taxonomy kind.")
    domain: CapabilityDomain = Field(..., description="The surface family.")
    actions: list[CapabilityAction] = Field(
        default_factory=list, description="The actions it can perform."
    )
    platform_id: str | None = Field(
        default=None, description="Harness/provider family (e.g. codex, claude)."
    )
    route_id: str | None = Field(
        default=None, description="Governed platform route (e.g. codex.headless.full)."
    )
    execution_harness_id: str | None = Field(
        default=None, description="The actual launcher/adapter (e.g. hapax-codex-headless)."
    )
    provider: str | None = Field(
        default=None, description="Upstream provider (e.g. OpenRouter, Anthropic)."
    )
    backend: str | None = Field(
        default=None, description="Backend (e.g. LiteLLM, TabbyAPI, local)."
    )
    model: str | None = Field(default=None, description="Model identifier.")
    effort: str | None = Field(default=None, description="Effort/context/thinking slice.")
    context_window: str | None = Field(default=None, description="Context window descriptor.")
    authority_ceiling: AuthorityCeiling = Field(
        default=AuthorityCeiling.READ_ONLY, description="Maximum allowed effect."
    )
    mutation_surfaces: list[str] = Field(
        default_factory=list, description="Surfaces this capability may mutate."
    )
    quality_floors: list[str] = Field(
        default_factory=list, description="Quality floors it satisfies."
    )
    privacy_posture: str = Field(default="unspecified", description="Privacy/retention posture.")
    public_claim_ceiling: str = Field(default="none", description="Maximum public-claim authority.")
    resource_pools: list[str] = Field(
        default_factory=list,
        description="Scarce resource accounts (e.g. openrouter-paid, youtube-quota).",
    )
    quota_source: QuotaSource = Field(default=QuotaSource.NONE)
    cost_source: CostSource = Field(default=CostSource.NONE)
    spend_authority_required: bool = Field(default=False)
    public_egress_authority_required: bool = Field(default=False)
    freshness_evidence: list[str] = Field(default_factory=list)
    observed_at: datetime | None = Field(
        default=None, description="When the determination was last measured."
    )
    stale_after: str = Field(
        default="24h", description="Duration after which the determination is stale."
    )
    freshness_state: FreshnessState = Field(default=FreshnessState.DARK)
    freshness_remediation_task: str | None = Field(
        default=None, description="The SDLC task that refreshes a stale determination."
    )
    new_capability_signal: str | None = Field(
        default=None, description="capability_surface_delta when observed surface is new/changed."
    )
    receipt_classes: list[str] = Field(default_factory=list)
    failure_classes: list[str] = Field(default_factory=list)
    kill_switches: list[str] = Field(default_factory=list)
    fallback_policy: str = Field(
        default="hold", description="Policy when the capability is unavailable."
    )
    owner_docs: list[str] = Field(default_factory=list)


# ── per-shape required facts (a load-bearing subset; full set in the taxonomy) ─


SHAPE_REQUIRED_FACTS: dict[CapabilityShape, tuple[str, ...]] = {
    CapabilityShape.RAW_MODEL: ("backend", "model"),
    CapabilityShape.HOSTED_MODEL: ("provider", "model", "spend_authority_required"),
    CapabilityShape.MODEL_EFFORT_SLICE: ("model", "effort", "platform_id"),
    CapabilityShape.EXISTING_AGENT_HARNESS: ("platform_id", "execution_harness_id"),
    CapabilityShape.REVIEW_SEAT: ("actions", "platform_id"),
    CapabilityShape.LOCAL_TOOL: ("execution_harness_id", "mutation_surfaces"),
    CapabilityShape.PROVIDER_GATEWAY: ("provider", "backend"),
    CapabilityShape.PUBLIC_EGRESS: ("public_egress_authority_required", "mutation_surfaces"),
    CapabilityShape.MONEY_RAIL: (
        "resource_pools",
        "authority_ceiling",
    ),
    CapabilityShape.BACKGROUND_SERVICE: ("execution_harness_id",),
    CapabilityShape.ORCHESTRATOR: ("actions",),
    CapabilityShape.CAPABILITY_AGGREGATOR: ("actions",),
}

_EXPLICIT_REQUIRED_DEFAULT_FACTS = frozenset(
    {
        "authority_ceiling",
        "spend_authority_required",
        "public_egress_authority_required",
    }
)


def _explicit_fields(descriptor: CapabilityHarnessDescriptor) -> set[str]:
    fields = getattr(
        descriptor,
        "model_fields_set",
        getattr(descriptor, "__pydantic_fields_set__", set()),
    )
    return set(fields)


def _fact_absent(descriptor: CapabilityHarnessDescriptor, fact: str) -> bool:
    """True if a required fact is absent (None, empty list, or empty string)."""
    if fact in _EXPLICIT_REQUIRED_DEFAULT_FACTS and fact not in _explicit_fields(descriptor):
        return True
    value = getattr(descriptor, fact, None)
    return value is None or (isinstance(value, list | str) and len(value) == 0)


def validate_descriptor(descriptor: CapabilityHarnessDescriptor) -> list[str]:
    """Return the shape-specific required facts that are ABSENT (empty == valid).

    Each capability shape carries required facts (taxonomy §"Shape Taxonomy"). A descriptor missing a
    required fact for its shape is incomplete — surfaced here, never silently accepted. The full
    required-facts sets live in the taxonomy; this encodes the load-bearing subset.
    """
    required = SHAPE_REQUIRED_FACTS.get(descriptor.shape, ())
    return [fact for fact in required if _fact_absent(descriptor, fact)]


# ── the capability_surface_delta (discover) ──────────────────────────────────


class DeltaKind(StrEnum):
    """The kind of surface delta discover() emits."""

    NEW = "new"
    CHANGED = "changed"
    MISSING = "missing"


class CapabilitySurfaceDelta(BaseModel):
    """The deterministic delta between observed capability surfaces and registered descriptors.

    This is the taxonomy's ``discover()`` output (§"Minimum Harness Contract" line 221): compare observed
    surfaces to registered descriptors and emit deterministic ``capability_surface_delta`` events for new
    or changed capabilities. A non-empty delta is the failing check that makes a boutique/missing surface
    visible rather than silent.
    """

    new_capability_ids: list[str] = Field(
        default_factory=list, description="Observed surfaces with no registered descriptor."
    )
    changed_capability_ids: list[str] = Field(
        default_factory=list, description="Registered descriptors whose fingerprint changed."
    )
    missing_capability_ids: list[str] = Field(
        default_factory=list, description="Registered descriptors not seen in the observed set."
    )

    @property
    def is_empty(self) -> bool:
        return not (
            self.new_capability_ids or self.changed_capability_ids or self.missing_capability_ids
        )

    def kinds(self) -> list[tuple[str, DeltaKind]]:
        """Flatten the delta into (capability_id, kind) pairs for emission as events."""
        out: list[tuple[str, DeltaKind]] = []
        out.extend((cid, DeltaKind.NEW) for cid in self.new_capability_ids)
        out.extend((cid, DeltaKind.CHANGED) for cid in self.changed_capability_ids)
        out.extend((cid, DeltaKind.MISSING) for cid in self.missing_capability_ids)
        return out


def descriptor_fingerprint(descriptor: CapabilityHarnessDescriptor) -> str:
    """A stable SHA-256 fingerprint of the descriptor's identity-shaping fields.

    Two descriptors with the same fingerprint are the same capability surface (no material change). A
    fingerprint change is a ``changed`` delta. The fingerprint covers identity + shape + authority +
    resource + freshness — the fields whose change is material to routing/calculus — NOT display_name or
    owner_docs (cosmetic).
    """
    material = {
        "capability_id": descriptor.capability_id,
        "shape": descriptor.shape.value,
        "domain": descriptor.domain.value,
        "actions": sorted(a.value for a in descriptor.actions),
        "platform_id": descriptor.platform_id,
        "route_id": descriptor.route_id,
        "execution_harness_id": descriptor.execution_harness_id,
        "provider": descriptor.provider,
        "backend": descriptor.backend,
        "model": descriptor.model,
        "effort": descriptor.effort,
        "context_window": descriptor.context_window,
        "authority_ceiling": descriptor.authority_ceiling.value,
        "mutation_surfaces": sorted(descriptor.mutation_surfaces),
        "quality_floors": sorted(descriptor.quality_floors),
        "privacy_posture": descriptor.privacy_posture,
        "public_claim_ceiling": descriptor.public_claim_ceiling,
        "resource_pools": sorted(descriptor.resource_pools),
        "quota_source": descriptor.quota_source.value,
        "cost_source": descriptor.cost_source.value,
        "spend_authority_required": descriptor.spend_authority_required,
        "public_egress_authority_required": descriptor.public_egress_authority_required,
        "freshness_evidence": sorted(descriptor.freshness_evidence),
        "observed_at": descriptor.observed_at,
        "stale_after": descriptor.stale_after,
        "freshness_state": descriptor.freshness_state.value,
        "freshness_remediation_task": descriptor.freshness_remediation_task,
        "new_capability_signal": descriptor.new_capability_signal,
        "receipt_classes": sorted(descriptor.receipt_classes),
        "failure_classes": sorted(descriptor.failure_classes),
        "kill_switches": sorted(descriptor.kill_switches),
        "fallback_policy": descriptor.fallback_policy,
    }
    blob = json.dumps(material, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def discover(
    observed: Sequence[CapabilityHarnessDescriptor],
    registered: dict[str, str],
) -> CapabilitySurfaceDelta:
    """Compare observed capability descriptors to the registered fingerprint map.

    ``registered`` maps ``capability_id -> last-known fingerprint``. Emits the deterministic
    ``CapabilitySurfaceDelta``: NEW (observed with no registered descriptor), CHANGED (registered
    descriptor whose fingerprint differs), MISSING (registered descriptor not seen in the observed set).
    A non-empty delta is the failing check.
    """
    counts = Counter(d.capability_id for d in observed)
    duplicates = sorted(cid for cid, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(
            "duplicate capability_id(s) in observed descriptors: " + ", ".join(duplicates)
        )
    observed_fp: dict[str, str] = {d.capability_id: descriptor_fingerprint(d) for d in observed}
    new_ids = [cid for cid in observed_fp if cid not in registered]
    changed_ids = [
        cid for cid, fp in observed_fp.items() if cid in registered and registered[cid] != fp
    ]
    missing_ids = [cid for cid in registered if cid not in observed_fp]
    return CapabilitySurfaceDelta(
        new_capability_ids=sorted(new_ids),
        changed_capability_ids=sorted(changed_ids),
        missing_capability_ids=sorted(missing_ids),
    )


def now_utc() -> datetime:
    """UTC now (separated for testability; the descriptor's observed_at default)."""
    return datetime.now(UTC)
