"""Tests for shared.resource_state_producer — the first producer into the Reins representation
(task estate-resource-state-determinative-projection-20261004).

The honest missing-state classifications are the load-bearing contract: LOST (dead declared endpoint),
UNEXPLAINED (loaded model with no admitting row), and stale-not-live. Each is exercised on the real
code path, and the bundle is validated against the reins_context contract (projected through the real
reins_context module when it is importable).
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta

import pytest

from shared import resource_state_producer as rsp

NOW = datetime(2026, 10, 4, 6, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# --- classifiers (the mutation-verify targets) ------------------------------------------------------


def test_lost_classification_dead_declared_endpoint() -> None:
    vs, reasons = rsp.classify_declared_endpoint(declared=True, alive=False)
    assert vs == "absent"
    assert "LOST" in reasons


def test_declared_endpoint_alive_is_lit() -> None:
    vs, reasons = rsp.classify_declared_endpoint(declared=True, alive=True)
    assert vs == "lit"
    assert "LOST" not in reasons


def test_unexplained_loaded_model_without_admitting_row() -> None:
    vs, reasons = rsp.classify_loaded_model(loaded=True, admitting_row=None)
    assert vs == "hold"
    assert "UNEXPLAINED" in reasons


def test_loaded_model_with_admitting_row_is_lit() -> None:
    vs, reasons = rsp.classify_loaded_model(loaded=True, admitting_row="serving.spark-qwen")
    assert vs == "lit"
    assert "UNEXPLAINED" not in reasons


def test_stale_field_is_not_live() -> None:
    old = _iso(NOW - timedelta(hours=2))
    assert rsp.freshness_state(old, NOW, window_s=300) == "stale"
    # a fact built from a stale observation must not project as a live (`lit`) value
    f = rsp._fact("resource_vram", "host:x", now=NOW, observed_at=old, value={}, value_state="lit")
    assert f["freshness_state"] == "stale"
    assert f["state"]["value_state"] == "stale"


def test_absent_observation_is_absent_not_fabricated() -> None:
    assert rsp.freshness_state(None, NOW, window_s=300) == "absent"


# --- end-to-end bundle ------------------------------------------------------------------------------


def _observation() -> dict:
    return {
        "ts": _iso(NOW),
        "gpus": [
            "NVIDIA GeForce RTX 3090, 24576 MiB, 1 MiB",
            "NVIDIA GeForce RTX 5060 Ti, 16311 MiB, 2 MiB",
        ],
        "fleet_memory": {
            "spark-01df": {"total_mb": 124546, "avail_mb": 13692},  # loaded
            "podium": {"total_mb": 127938, "avail_mb": 94444},  # free
            "beelink1": None,  # dark
        },
        "local_endpoints": {"5000": False, "5001": False},  # LOST
    }


def test_build_bundle_classifies_lost_unexplained_dark() -> None:
    b = rsp.build_bundle(observation=_observation(), now=NOW)
    by_id = {f["fact_id"]: f for lst in b["facts"].values() for f in lst}
    # LOST: appendix 5000/5001
    lost = [f for f in by_id.values() if "LOST" in f["state"]["reason_codes"]]
    assert {
        "declared_endpoint:serving.appendix-5000",
        "declared_endpoint:serving.appendix-5001",
    } <= {f["fact_id"] for f in lost}
    assert all(f["state"]["value_state"] == "absent" for f in lost)
    # UNEXPLAINED: spark loaded, no admitting row
    unexpl = [f for f in by_id.values() if "UNEXPLAINED" in f["state"]["reason_codes"]]
    assert any("spark-01df" in f["subject_ref"] for f in unexpl)
    assert all(f["state"]["value_state"] == "hold" for f in unexpl)
    # DARK: beelink1 unreachable
    assert any(f["state"]["value_state"] == "dark" for f in by_id.values())
    # ERRATA: appendix serving is NAS-backed Docker
    assert (
        "NAS-backed Docker" in by_id["declared_endpoint:serving.appendix-5000"]["value"]["backing"]
    )


def test_admitting_row_resolves_unexplained() -> None:
    b = rsp.build_bundle(
        observation=_observation(),
        now=NOW,
        admitting_rows={"host:spark-01df:loaded": "serving.spark-qwen3-flash-next"},
    )
    spark = next(
        f
        for lst in b["facts"].values()
        for f in lst
        if f["subject_ref"] == "host:spark-01df:loaded"
    )
    assert spark["state"]["value_state"] == "lit"
    assert "UNEXPLAINED" not in spark["state"]["reason_codes"]


def test_errata_featherless_billing_low_confidence() -> None:
    surface = {
        "meta": {"generated_at": _iso(NOW)},
        "billing": [
            {
                "vendor": "Featherless",
                "entitlement": "featherless-request-pricing",
                "state": "live-payment-issue",
                "amount": "~200/mo",
            },
            {
                "vendor": "Anthropic",
                "entitlement": "anthropic-claude-max",
                "state": "live",
                "amount": "subscription",
            },
        ],
    }
    b = rsp.build_bundle(observation=_observation(), surface=surface, now=NOW)
    ents = {f["value"]["vendor"]: f for f in b["facts"]["remote_entitlement"]}
    assert ents["Featherless"]["confidence_word"] == "low"
    assert any("ERRATA" in r for r in ents["Featherless"]["state"]["reason_codes"])
    assert ents["Anthropic"]["confidence_word"] != "low"


def test_kimi_ledger_absent_is_honest() -> None:
    b = rsp.build_bundle(observation=_observation(), kimi_usage=None, now=NOW)
    usage = b["facts"]["usage"]
    assert len(usage) == 1
    assert usage[0]["state"]["value_state"] == "absent"
    assert "kimi_bench_ledger_absent" in usage[0]["state"]["reason_codes"]


def test_kimi_ledger_present_emits_usage_facts() -> None:
    b = rsp.build_bundle(
        observation=_observation(),
        now=NOW,
        kimi_usage=[{"ts": _iso(NOW), "model": "kimi-k3", "calls": 4, "tokens": 1200}],
    )
    usage = b["facts"]["usage"]
    assert any(
        u["value"].get("model") == "kimi-k3" and u["state"]["value_state"] == "lit" for u in usage
    )


# --- enforcement obligation + boundary delivery -----------------------------------------------------


def test_claim_must_cite_a_fresh_resource_fact() -> None:
    b = rsp.build_bundle(observation=_observation(), now=NOW)
    some_id = b["facts"]["resource_vram"][0]["fact_id"]
    assert rsp.claim_cites_fresh_resource_fact(f"podium is free, per {some_id}", b, now=NOW) is True
    assert rsp.claim_cites_fresh_resource_fact("podium is free", b, now=NOW) is False
    # a claim citing the fact well past its window is not satisfied
    later = NOW + timedelta(hours=5)
    assert (
        rsp.claim_cites_fresh_resource_fact(f"podium is free, per {some_id}", b, now=later) is False
    )


def test_boundary_summary_names_lost_and_unexplained() -> None:
    s = rsp.resource_summary_for_boundary(rsp.build_bundle(observation=_observation(), now=NOW))
    assert "LOST" in s and "UNEXPLAINED" in s and "Cite a fact id" in s


# --- integration against the real reins_context (skipped where reins is not importable, e.g. CI) ----


def _reins():
    p = os.path.expanduser("~/projects/reins/api")
    if p not in sys.path:
        sys.path.insert(0, p)
    try:
        import reins_context  # noqa: PLC0415

        return reins_context
    except Exception:  # noqa: BLE001
        return None


def test_bundle_projects_through_reins_contract() -> None:
    rc = _reins()
    if rc is None:
        pytest.skip("reins_context not importable in this environment")
    b = rsp.build_bundle(observation=_observation(), now=NOW)
    proj = rc.project(b, "operator_private")
    assert proj["bundle_state"] in ("lit", "partial", "dark", "stale", "hold", "refused")
    # internal resource facts are denied on the public/on-air channel (AIR default-deny holds)
    assert rc.project(b, "public_or_air")["fact_count"] == 0
    # a hold (UNEXPLAINED) fact projects a hold affordance, never a live row
    holds = [a for a in proj["affordances"] if any(e["state"] == "hold" for e in a["affordances"])]
    assert holds
