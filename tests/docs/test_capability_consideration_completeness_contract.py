"""Capability-consideration COMPLETENESS gate (REQ-20260619-capability-adapter-unification, P4).

Operator principle (2026-06-19): a *capability* is the FULL descriptor —
``platform x surface x model x effort x context-mode x fast-mode x quantization x
capacity-pool`` — not just the platform. Every capability must be considered WHERE
ANY capability is considered.

This gate makes "considered where any is considered" CHECKABLE and fail-closed.
For each operator-selectable capability axis and each governed consideration site
where that axis is APPLICABLE, the axis must either be STRUCTURALLY MODELED at that
site (verified by live introspection of the real models/constants — never text
scraping) OR be covered by an explicit, dated, future-expiry WAIVER that names the
cc-task closing it. An axis present at one applicable site but silently absent at
another is the exact defect this gate forbids: intentional gaps are *visible
expiring debt*, never silent absence.

Today (origin/main) reasoning-effort, context-mode (1M), fast-mode, structured
model-identity, and quantization are absent from the governed routing/metering
plane (they live only at launch time — e.g. ``hapax-claude``/``hapax-claude-headless``
defaults, and the smuggled ``model_or_engine="gpt-5.5-xhigh"``). Each absence is a
dated waiver pointing at the cc-task that promotes it. As those tasks land, the
detector flips to MODELED and the matching waiver MUST be removed (``test_waivers_name_real_absences``),
which then forces the axis to be considered at *every* applicable site — the
forcing function.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
for p in (REPO_ROOT, SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import executor_contract as ec  # noqa: E402

from shared.dispatcher_policy import DIMENSION_WEIGHTS  # noqa: E402
from shared.platform_capability_registry import (  # noqa: E402
    PlatformCapabilityRoute,
    load_platform_capability_registry,
)
from shared.quota_spend_ledger import SpendReceipt  # noqa: E402
from shared.route_metadata_schema import TaskDemand  # noqa: E402

# ----------------------------------------------------------------------------------
# Canonical capability axes and the tokens that signal each one is MODELED at a site.
# Detection is structural: a site models an axis iff a field/key name carries the
# axis token. model_id means a STRUCTURED dated identity (model_id / model_fingerprint),
# NOT the coarse free-text model_or_engine (which is exactly the smuggle this closes).
# ----------------------------------------------------------------------------------
AXIS_TOKENS: dict[str, tuple[str, ...]] = {
    "effort": ("effort",),
    "context_mode": ("context_mode",),
    "fast_mode": ("fast_mode", "fast"),
    "model_id": ("model_id", "model_fingerprint"),
    "quantization": ("quant",),
    "capacity_pool": ("capacity_pool", "capacity"),
}


def _registry_field_universe() -> set[str]:
    names = set(PlatformCapabilityRoute.model_fields)
    # future-proof: when the ExecutionDescriptor sub-object lands (P4 step 2), its
    # fields count as registry consideration too.
    desc = PlatformCapabilityRoute.model_fields.get("execution_descriptor")
    if desc is not None:
        try:  # pragma: no cover - exercised once the descriptor exists
            names |= set(desc.annotation.model_fields)  # type: ignore[union-attr]
        except (AttributeError, TypeError):
            pass
    return names


def _site_field_universes() -> dict[str, set[str]]:
    """The structurally-introspectable governed consideration sites."""
    return {
        "registry": _registry_field_universe(),
        "dispatcher_scoring": set(DIMENSION_WEIGHTS),
        "dispatcher_demand": set(TaskDemand.model_fields),
        "quota_ledger": set(SpendReceipt.model_fields),
        "executor": set(ec.ExecutorCapabilities.model_fields),
    }


def _is_modeled(axis: str, field_universe: set[str]) -> bool:
    tokens = AXIS_TOKENS[axis]
    return any(any(tok in name for tok in tokens) for name in field_universe)


# ----------------------------------------------------------------------------------
# APPLICABILITY: the (axis, site) pairs that MUST be modeled-or-waived. These are the
# operator-selectable cost/quality axes on the routing+metering plane. (platform /
# surface / capacity-pool are already first-class and are covered by positive controls.)
# ----------------------------------------------------------------------------------
APPLICABLE: dict[str, frozenset[str]] = {
    "effort": frozenset({"registry", "dispatcher_scoring", "dispatcher_demand", "quota_ledger"}),
    "context_mode": frozenset({"registry", "dispatcher_scoring", "dispatcher_demand"}),
    "model_id": frozenset({"registry", "quota_ledger"}),
    "fast_mode": frozenset({"registry", "quota_ledger"}),
    "quantization": frozenset({"registry", "quota_ledger"}),
}

# ----------------------------------------------------------------------------------
# WAIVERS: every (axis, site) absence that is intentionally deferred, as dated debt.
# Each names the cc-task that closes it. expires_at MUST be in the future at test time.
# As a closing task lands and the detector flips to MODELED, the matching waiver fails
# test_waivers_name_real_absences and must be removed — forcing full consideration.
# ----------------------------------------------------------------------------------
_EXP = "2026-09-30T00:00:00Z"  # P4 build horizon; bump only with a tracked extension
_DESCRIPTOR_TASK = "capability-execution-descriptor-enums-20260619"
_BACKFILL_TASK = "capability-route-descriptor-backfill-20260619"
_LOCAL_TASK = "capability-haiku-localtool-routes-20260619"
_WAIVER_TASK = "capability-consideration-waivers-20260619"
_RECEIPT_TASK = "capability-receipt-drift-20260619"

WAIVERS: tuple[dict[str, str], ...] = (
    # effort — NOW modeled at registry (ExecutionDescriptor.effort, backfilled); the
    # remaining gaps are the dispatcher scoring/demand dims and the spend ledger.
    {
        "axis": "effort",
        "site": "dispatcher_scoring",
        "expires_at": _EXP,
        "tracking_ref": _DESCRIPTOR_TASK,
        "reason": "no effort_fit dimension in DIMENSION_WEIGHTS; add conditional effort_fit",
    },
    {
        "axis": "effort",
        "site": "dispatcher_demand",
        "expires_at": _EXP,
        "tracking_ref": _DESCRIPTOR_TASK,
        "reason": "TaskDemand has no effort_demand; mirror the scored supply axis",
    },
    {
        "axis": "effort",
        "site": "quota_ledger",
        "expires_at": _EXP,
        "tracking_ref": _RECEIPT_TASK,
        "reason": "SpendReceipt key omits effort; effort changes token spend and must be metered",
    },
    # context_mode (1M vs standard) — NOW modeled at registry (ExecutionDescriptor.context_mode);
    # the dispatcher scoring/demand fit dims are the remaining gaps.
    {
        "axis": "context_mode",
        "site": "dispatcher_scoring",
        "expires_at": _EXP,
        "tracking_ref": _DESCRIPTOR_TASK,
        "reason": "no context_mode_fit; add conditional dimension so extended_1m is satisfiable only by an extended_1m leaf",
    },
    {
        "axis": "context_mode",
        "site": "dispatcher_demand",
        "expires_at": _EXP,
        "tracking_ref": _DESCRIPTOR_TASK,
        "reason": "TaskDemand has no context_mode_demand",
    },
    # model_id (structured, dated) — NOW modeled at registry (ExecutionDescriptor.model_id: ModelId),
    # which splits the gpt-5.5-xhigh smuggle; the spend ledger still keys on free-text model_or_engine.
    {
        "axis": "model_id",
        "site": "quota_ledger",
        "expires_at": _EXP,
        "tracking_ref": _RECEIPT_TASK,
        "reason": "SpendReceipt carries free-text model_or_engine; key on structured model_id",
    },
    # fast_mode — NOW modeled at registry (ExecutionDescriptor.fast_mode); still a client-side
    # harness flag with no governed launch path, so the spend-ledger metering stays deferred.
    {
        "axis": "fast_mode",
        "site": "quota_ledger",
        "expires_at": _EXP,
        "tracking_ref": _WAIVER_TASK,
        "reason": "fast-mode shifts latency/billing; meter once a governed /fast hook exists",
    },
    # quantization (local EXL3 4.0/5.0bpw) — NOW modeled at registry (ExecutionDescriptor.quantization);
    # separate exl3 spend metering still lands with the local_tool route.
    {
        "axis": "quantization",
        "site": "quota_ledger",
        "expires_at": _EXP,
        "tracking_ref": _LOCAL_TASK,
        "reason": "separate exl3_4.0bpw vs 5.0bpw spend once local_tool.local.worker exists",
    },
)

MAX_WAIVERS = 20  # bound: intentional asymmetry must shrink, not accrete


def _waived_pairs() -> set[tuple[str, str]]:
    return {(w["axis"], w["site"]) for w in WAIVERS}


# ----------------------------------------------------------------------------------
# GATES
# ----------------------------------------------------------------------------------
def test_no_silent_absence() -> None:
    """Every applicable (axis, site) is MODELED or covered by a waiver — never silently absent."""
    universes = _site_field_universes()
    silent: list[str] = []
    waived = _waived_pairs()
    for axis, sites in APPLICABLE.items():
        for site in sites:
            if _is_modeled(axis, universes[site]):
                continue
            if (axis, site) not in waived:
                silent.append(f"{axis}@{site}")
    assert not silent, (
        "capability axes silently absent at an applicable governed site (model them, "
        f"or add a dated waiver naming the closing cc-task): {sorted(silent)}"
    )


def test_waivers_name_real_absences() -> None:
    """A waiver must cover a GENUINE absence. When an axis lands at a site the detector
    flips to MODELED and its waiver fails here — forcing the stale waiver to be removed
    (this is how 'considered where any is considered' is actually enforced over time)."""
    universes = _site_field_universes()
    stale: list[str] = []
    for w in WAIVERS:
        if _is_modeled(w["axis"], universes[w["site"]]):
            stale.append(
                f"{w['axis']}@{w['site']} (now MODELED — remove waiver -> {w['tracking_ref']})"
            )
    assert not stale, f"waivers covering already-modeled pairs (remove them): {stale}"


def test_waiver_hygiene() -> None:
    """Every waiver is dated debt: future expiry + a tracking_ref + a reason; count bounded."""
    now = datetime.now(UTC)
    assert len(WAIVERS) <= MAX_WAIVERS, (
        f"too many waivers ({len(WAIVERS)} > {MAX_WAIVERS}) — asymmetry must shrink"
    )
    for w in WAIVERS:
        assert set(w) >= {"axis", "site", "expires_at", "tracking_ref", "reason"}, (
            f"malformed waiver: {w}"
        )
        assert w["axis"] in AXIS_TOKENS, f"unknown axis in waiver: {w['axis']}"
        assert w["site"] in _site_field_universes(), f"unknown site in waiver: {w['site']}"
        assert (w["axis"], w["site"]) in {(a, s) for a, ss in APPLICABLE.items() for s in ss}, (
            f"waiver for non-applicable pair: {w['axis']}@{w['site']}"
        )
        expiry = datetime.fromisoformat(w["expires_at"].replace("Z", "+00:00"))
        assert expiry > now, (
            f"EXPIRED waiver (intentional debt came due): {w['axis']}@{w['site']} {w['expires_at']}"
        )
        assert w["tracking_ref"].strip(), f"waiver missing tracking_ref: {w}"


def test_capacity_pool_positive_control() -> None:
    """Proof the structural detector actually FIRES on a modeled axis — so the absence
    findings above are trustworthy, not a vacuously-passing detector. capacity_pool is
    the one non-profile axis modeled end-to-end (registry + spend ledger)."""
    universes = _site_field_universes()
    assert _is_modeled("capacity_pool", universes["registry"]), (
        "detector failed on a known-modeled axis"
    )
    assert _is_modeled("capacity_pool", universes["quota_ledger"]), (
        "detector failed on the spend-ledger key"
    )
    # and confirm the gap axes are genuinely undetected today (the asymmetry the gate guards).
    # Post-backfill the registry-site axes are all modeled, so the remaining genuine gaps are
    # on the dispatcher scoring plane and the spend ledger.
    assert not _is_modeled("effort", universes["dispatcher_scoring"])
    assert not _is_modeled("quantization", universes["quota_ledger"])


def test_route_ids_stay_three_segment() -> None:
    """Anti-explosion invariant: capability knobs (effort/context/fast) must live in a
    descriptor keyed BY route_id, never folded into route_id — so route_id stays the
    3-segment platform.mode.profile key (no claude.headless.opus.xhigh.1m.fast blowup)."""
    registry = load_platform_capability_registry()
    bad = [rid for rid in registry.route_map() if rid.count(".") != 2]
    assert not bad, (
        f"route_ids must be exactly 3 dot-segments (knobs belong in the descriptor): {bad}"
    )
