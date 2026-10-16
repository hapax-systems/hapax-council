"""Pin: each held census cognition provider is routed or omitted with a reason.

Declaration is not admission. A route, if one is ever added, stays blocked until a
receipt exists. Records-only and vendor-cache holds are not marked fresh. Sakana
Fugu is a remote subscription model provider, not local compute.

Estate prior art this pin adopts, rather than a new schema: omitted capability
shapes (demand_eligible false), entitlement_capability name classes, the Grok
draft row and the Qwen provisional routes left unmerged, and the Fugu dispatch
hold until a promote receipt. Outward: an inventory row is not an allowlist
(SBOM vs policy; discovery vs an approved configuration; declared vs admitted),
and unknown is not recorded as known-empty (SPDX NOASSERTION vs NONE).
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"

# Census R2 §7 names these ten. MiMo and Perplexity each cover two census rows.
HELD: tuple[dict[str, Any], ...] = (
    {
        "provider": "Sakana Fugu",
        "shape_id": "model_provider.sakana_fugu_subscription",
        "shape_class": "model_provider",
        "freshness_state": "fresh",
        "reasons": (
            "remote_subscription_not_local_compute",
            "route_receipt_absent",
            "quota_ledger_row_absent",
        ),
        "forbidden_shape_ids": ("local_compute.ornith_fugu_sakana_surface",),
    },
    {
        "provider": "xAI Grok",
        "shape_id": "model_provider.xai_supergrok_heavy",
        "shape_class": "model_provider",
        "freshness_state": "stale",
        "reasons": (
            "vendor_cache_precedes_census_window",
            "usage_not_exposed",
            "route_receipt_absent",
            "quota_ledger_row_absent",
            "drafted_route_not_admitted",
        ),
    },
    {
        "provider": "Meta Muse",
        "shape_id": "model_provider.meta_muse",
        "shape_class": "model_provider",
        "freshness_state": "asserted_only",
        "reasons": (
            "native_record_only",
            "plan_price_not_read_back",
            "usage_not_exposed",
            "route_receipt_absent",
            "quota_ledger_row_absent",
        ),
    },
    {
        "provider": "Featherless",
        "shape_id": "model_provider.featherless_request_pricing",
        "shape_class": "model_provider",
        "freshness_state": "fresh",
        "reasons": (
            "usage_balance_not_exposed",
            "route_receipt_absent",
            "quota_ledger_row_absent",
        ),
    },
    {
        "provider": "Verboo",
        "shape_id": "model_provider.verboo_code_ultra",
        "shape_class": "model_provider",
        "freshness_state": "fresh",
        "reasons": (
            "plan_recorded_not_live",
            "verboo_code_client_not_installed",
            "route_receipt_absent",
            "quota_ledger_row_absent",
        ),
    },
    {
        "provider": "Hugging Face",
        "shape_id": "model_provider.huggingface_pro",
        "shape_class": "model_provider",
        "freshness_state": "fresh",
        "reasons": (
            "inference_credits_not_exposed",
            "route_receipt_absent",
            "quota_ledger_row_absent",
        ),
    },
    {
        "provider": "Cohere",
        "shape_id": "model_provider.cohere",
        "shape_class": "model_provider",
        "freshness_state": "fresh",
        "reasons": (
            "tier_unobserved",
            "harness_not_found",
            "route_receipt_absent",
            "quota_ledger_row_absent",
        ),
    },
    {
        "provider": "Xiaomi MiMo",
        "shape_id": "model_provider.xiaomi_mimo",
        "shape_class": "model_provider",
        "freshness_state": "asserted_only",
        "reasons": (
            "records_only",
            "pro_gui_usage_recorded_capped",
            "token_plan_usage_unobserved",
            "credential_outside_filestore",
            "route_receipt_absent",
            "quota_ledger_row_absent",
        ),
    },
    {
        "provider": "Qwen Cloud",
        "shape_id": "model_provider.qwen_cloud_coding_plan",
        "shape_class": "model_provider",
        "freshness_state": "asserted_only",
        "reasons": (
            "records_only",
            "terms_restricted_not_probed",
            "harness_recorded_unusable",
            "route_receipt_absent",
            "quota_ledger_row_absent",
        ),
    },
    {
        "provider": "Perplexity",
        "shape_id": "model_provider.perplexity",
        "shape_class": "model_provider",
        "freshness_state": "asserted_only",
        "reasons": (
            "records_only",
            "max_gui_current_state_unobserved",
            "api_credits_recorded_not_live",
            "sonar_supported_only_until_2026_09_27",
            "route_receipt_absent",
            "quota_ledger_row_absent",
        ),
    },
)

_SECRET_MARKERS = ("bearer ", "sk-", "vbk_", "fish_")


def _load(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or REGISTRY).read_text(encoding="utf-8"))


def declaration_gaps(registry: dict[str, Any]) -> list[str]:
    """Return human-readable gaps. Empty means the census ten are declared."""

    shapes = {shape["shape_id"]: shape for shape in registry["omitted_capability_shapes"]}
    routes = {route["route_id"]: route for route in registry["routes"]}
    gaps: list[str] = []
    for row in HELD:
        shape_id = row["shape_id"]
        shape = shapes.get(shape_id)
        route = routes.get(shape_id)
        if shape is None and route is None:
            gaps.append(f"{row['provider']}: neither routed nor omitted")
        if route is not None:
            if route.get("route_state") != "blocked" or not route.get("blocked_reasons"):
                gaps.append(f"{row['provider']}: route is admitted or has no blocked_reasons")
        if shape is not None:
            if shape.get("demand_eligible"):
                gaps.append(f"{shape_id}: demand_eligible")
            if shape.get("route_ids"):
                gaps.append(f"{shape_id}: carries route_ids")
            if shape.get("shape_class") != row["shape_class"]:
                gaps.append(f"{shape_id}: shape_class {shape.get('shape_class')}")
            if shape.get("freshness_state") != row["freshness_state"]:
                gaps.append(
                    f"{shape_id}: freshness {shape.get('freshness_state')} "
                    f"!= {row['freshness_state']}"
                )
            if not shape.get("blocked_reasons"):
                gaps.append(f"{shape_id}: omitted without a reason")
            missing = [
                reason for reason in row["reasons"] if reason not in shape["blocked_reasons"]
            ]
            if missing:
                gaps.append(f"{shape_id}: missing reasons {missing}")
        for forbidden in row.get("forbidden_shape_ids", ()):
            if forbidden in shapes or forbidden in routes:
                gaps.append(f"{row['provider']}: forbidden id still present: {forbidden}")
    return gaps


def test_held_census_providers_are_declared_with_reasons() -> None:
    gaps = declaration_gaps(_load())
    assert gaps == [], gaps


def test_sakana_fugu_is_not_filed_as_local_compute() -> None:
    registry = _load()
    ids = {shape["shape_id"] for shape in registry["omitted_capability_shapes"]}
    assert "local_compute.ornith_fugu_sakana_surface" not in ids
    shape = next(
        shape
        for shape in registry["omitted_capability_shapes"]
        if shape["shape_id"] == "model_provider.sakana_fugu_subscription"
    )
    assert shape["shape_class"] == "model_provider"
    assert "remote_subscription_not_local_compute" in shape["blocked_reasons"]


def test_declarations_do_not_carry_secret_markers_or_home_paths() -> None:
    registry = _load()
    held_ids = {row["shape_id"] for row in HELD}
    blobs = [
        json.dumps(shape)
        for shape in registry["omitted_capability_shapes"]
        if shape["shape_id"] in held_ids
    ]
    text = "\n".join(blobs).lower()
    for marker in _SECRET_MARKERS:
        assert marker not in text
    assert "/home/" not in text


@pytest.mark.parametrize(
    "mutate",
    [
        "drop_shape",
        "empty_reasons",
        "mark_records_fresh",
        "refile_fugu_as_local_compute",
        "admit_route",
    ],
)
def test_unsafe_declaration_cases_fail(mutate: str) -> None:
    registry = deepcopy(_load())
    shapes = registry["omitted_capability_shapes"]
    if mutate == "drop_shape":
        registry["omitted_capability_shapes"] = [
            shape for shape in shapes if shape["shape_id"] != "model_provider.cohere"
        ]
    elif mutate == "empty_reasons":
        next(shape for shape in shapes if shape["shape_id"] == "model_provider.cohere")[
            "blocked_reasons"
        ] = []
    elif mutate == "mark_records_fresh":
        qwen = next(
            shape
            for shape in shapes
            if shape["shape_id"] == "model_provider.qwen_cloud_coding_plan"
        )
        qwen["freshness_state"] = "fresh"
    elif mutate == "refile_fugu_as_local_compute":
        sakana = next(
            shape
            for shape in shapes
            if shape["shape_id"] == "model_provider.sakana_fugu_subscription"
        )
        sakana["shape_id"] = "local_compute.ornith_fugu_sakana_surface"
        sakana["shape_class"] = "local_compute"
    elif mutate == "admit_route":
        registry["routes"].append(
            {
                "route_id": "model_provider.sakana_fugu_subscription",
                "route_state": "active",
                "blocked_reasons": [],
            }
        )
        registry["omitted_capability_shapes"] = [
            shape
            for shape in shapes
            if shape["shape_id"] != "model_provider.sakana_fugu_subscription"
        ]
    else:
        raise AssertionError(mutate)
    assert declaration_gaps(registry), mutate
