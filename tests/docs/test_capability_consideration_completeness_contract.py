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

As checked on 2026-10-01, fast_mode@quota_ledger is the remaining structural gap.
Declared routes keep fast mode off; the Codex and Claude review invocation adapters
reject fast mode, and SpendReceipt has no fast-mode observation. The short waiver
below records that bounded gap. When metering lands, the detector flips to MODELED
and the matching waiver MUST be removed (``test_waivers_name_real_absences``).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
for p in (REPO_ROOT, SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import executor_contract as ec  # noqa: E402

from shared.dispatcher_policy import DIMENSION_WEIGHTS  # noqa: E402
from shared.platform_capability_registry import (  # noqa: E402
    FastMode,
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
# The 2026-09-30 expiry failed merge-group job 110214982638; retain that witness.
# The 2026-10-04 re-bound (#4984) also lapsed before merging; the 2026-10-07 bound (#5025)
# was the second short, re-verified extension.
# The 2026-10-07 expiry failed merge-group CI run 37848439089 (1 failed, 10902 passed);
# retain that witness. This 2026-10-13 bound is the third, re-verified on main bc068207b,
# not a bare date bump (see reason below).
# This task's parent brief permits a short extension only for a genuine metering gap.
# Less than 72 hours gives the coordinator a bounded reconciliation window, not a
# new build horizon or permission to launch fast mode without observed metering.
_EXP = "2026-10-13T05:45:00Z"
_WAIVER_TASK = "capability-fast-mode-waiver-rebound-20261010"

WAIVERS: tuple[dict[str, str], ...] = (
    # effort — NOW fully modeled: registry (ExecutionDescriptor.effort), dispatcher (effort_fit +
    # TaskDemand.effort_demand) AND the spend ledger (SpendReceipt.effort). No waiver.
    # context_mode — NOW fully modeled (registry + dispatcher scoring/demand). No waiver.
    # model_id — NOW fully modeled: registry (ExecutionDescriptor.model_id: ModelId) AND the spend
    # ledger (SpendReceipt.model_id, the structured replacement for free-text model_or_engine). No waiver.
    # fast_mode — declared in the registry, off on every route; not metered in SpendReceipt.
    {
        "axis": "fast_mode",
        "site": "quota_ledger",
        "expires_at": _EXP,
        "tracking_ref": _WAIVER_TASK,
        "reviewed_at": "2026-10-10T05:45:55Z",
        "owner": "dev1-seat",
        "reason": (
            "2026-10-10 live source re-check (all 16 registry routes fast_mode=off; "
            "codex_execution_args and claude_execution_binding raise ExecutionIdentityError on any "
            "non-off descriptor; no SpendReceipt producer observes fast_mode). There is no governed "
            "path that incurs fast-mode spend, so there is no producer to meter yet: metering lands "
            "atomically with the first governed fast route. Not a bare re-extension — the structural "
            "gate (test_fast_mode_waiver_requires_disabled_routes) fails the instant any route enables "
            "fast; this bound only keeps the debt from going silent. Reconcile within 72 hours."
        ),
        "closure_criterion": (
            "Before enabling a governed fast route, carry observed fast-mode identity through "
            "the spend producer into SpendReceipt and its consumer, reject missing identity "
            "without a silent default, prove actual metering, and remove this waiver. "
            "Coordinator owns scope reconciliation before expiry; no automatic renewal."
        ),
    },
    # quantization — NOW modeled at the spend ledger (SpendReceipt.quantization) as well as the
    # registry (ExecutionDescriptor.quantization). Fully modeled; no waiver.
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


def test_fast_mode_extension_is_bounded_and_owned() -> None:
    """A renewed exception needs current ownership and at most 72 hours to reconcile."""
    for w in WAIVERS:
        if (w["axis"], w["site"]) != ("fast_mode", "quota_ledger"):
            continue
        reviewed = datetime.fromisoformat(w["reviewed_at"].replace("Z", "+00:00"))
        expiry = datetime.fromisoformat(w["expires_at"].replace("Z", "+00:00"))
        assert reviewed <= datetime.now(UTC), "waiver review must already have happened"
        assert timedelta(0) < expiry - reviewed <= timedelta(hours=72), (
            "fast-mode extension exceeds its 72-hour reconciliation window"
        )
        assert w["tracking_ref"] == "capability-fast-mode-waiver-rebound-20261010"
        assert w["owner"] == "dev1-seat"
        assert w["reason"].strip()
        assert w["closure_criterion"].strip()


def test_fast_mode_waiver_requires_disabled_routes() -> None:
    """Enabling a declared fast route requires metering, even before this waiver expires."""
    if ("fast_mode", "quota_ledger") not in _waived_pairs():
        return
    enabled = [
        route.route_id
        for route in load_platform_capability_registry().routes
        if route.execution_descriptor.fast_mode != "off"
    ]
    assert not enabled, f"fast-mode routes require actual quota-ledger metering: {enabled}"


def test_enabled_fast_route_cannot_hide_behind_waiver(monkeypatch) -> None:
    registry = load_platform_capability_registry()
    route = registry.routes[0]
    enabled = route.model_copy(
        update={
            "execution_descriptor": route.execution_descriptor.model_copy(
                update={"fast_mode": FastMode.FAST}
            )
        }
    )
    monkeypatch.setattr(
        sys.modules[__name__],
        "load_platform_capability_registry",
        lambda: registry.model_copy(update={"routes": (enabled, *registry.routes[1:])}),
    )
    with pytest.raises(AssertionError, match="require actual quota-ledger metering"):
        test_fast_mode_waiver_requires_disabled_routes()


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_waiver_expiry_boundary_remains_fail_closed(monkeypatch, offset) -> None:
    expiry = datetime.fromisoformat(WAIVERS[0]["expires_at"].replace("Z", "+00:00"))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return expiry + timedelta(microseconds=offset)

    monkeypatch.setattr(sys.modules[__name__], "datetime", Clock)
    if offset < 0:
        test_waiver_hygiene()
    else:
        with pytest.raises(AssertionError, match="EXPIRED waiver"):
            test_waiver_hygiene()


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
    # The detector fires on now-modeled live axes — effort_fit in DIMENSION_WEIGHTS and the
    # SpendReceipt now carries effort / model_id / quantization — and stays silent on the one
    # genuine remaining gap (fast_mode is still absent from the spend ledger). Recheck:
    #   uv run pytest tests/docs/test_capability_consideration_completeness_contract.py
    assert _is_modeled("effort", universes["dispatcher_scoring"])
    assert _is_modeled("effort", universes["quota_ledger"])
    assert _is_modeled("model_id", universes["quota_ledger"])
    assert _is_modeled("quantization", universes["quota_ledger"])
    assert not _is_modeled("fast_mode", universes["quota_ledger"])
    # detector discrimination pinned against SYNTHETIC universes — immune to a sibling slice
    # mutating the live field sets, so the gap findings above can never be a vacuous pass.
    assert _is_modeled("effort", {"effort_fit", "grounding"})
    assert not _is_modeled("effort", {"grounding", "architecture"})
    assert _is_modeled("quantization", {"quantization"})
    assert not _is_modeled("quantization", {"model_or_engine", "cost_usd"})


def test_route_ids_stay_three_segment() -> None:
    """Anti-explosion invariant: capability knobs (effort/context/fast) must live in a
    descriptor keyed BY route_id, never folded into route_id — so route_id stays the
    3-segment platform.mode.profile key (no claude.headless.opus.xhigh.1m.fast blowup)."""
    registry = load_platform_capability_registry()
    bad = [rid for rid in registry.route_map() if rid.count(".") != 2]
    assert not bad, (
        f"route_ids must be exactly 3 dot-segments (knobs belong in the descriptor): {bad}"
    )
