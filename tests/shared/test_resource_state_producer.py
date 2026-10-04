"""Tests for shared.resource_state_producer — the first producer into the Reins representation
(task estate-resource-state-determinative-projection-20261004; review #5027 fix-first round).

The load-bearing contract is honest missing-state: LOST (dead declared endpoint), UNEXPLAINED (a
loaded model — from /v1/models, NEVER a RAM-occupancy heuristic — with no admitting row), and
stale-not-live. The AIR default-deny contract ("public_or_air -> 0 facts") is witnessed in CI against
a vendored copy of reins_context, with a drift guard against the governed reins when it is importable.
Both shipped scripts are exercised.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared import resource_state_producer as rsp

REPO = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 4, 6, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VENDORED_REINS = _load_module(
    REPO / "tests" / "fixtures" / "reins_context_vendored.py", "reins_context_vendored"
)


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
            "spark-01df": {
                "total_mb": 124546,
                "avail_mb": 13692,
            },  # low free RAM — must NOT become a "loaded" claim
            "podium": {"total_mb": 127938, "avail_mb": 94444},
            "beelink1": None,  # dark
        },
        "local_endpoints": {"5000": False, "5001": False, "11434": True},
        "loaded_models": {
            "5000": [],
            "5001": [],
            "11434": ["nomic-embed-text:latest"],
        },  # /v1/models ids
        "serving_procs": ["4242 ollama serve"],
    }


def _loaded_subject() -> str:
    return "host:appendix:11434/nomic-embed-text:latest"


def test_loaded_comes_from_v1_models_never_ram_occupancy() -> None:
    """Review #5027 finding 1: 'loaded' must come from observed /v1/models ids, never a RAM-occupancy
    heuristic. spark-01df has low free RAM but no /v1/models probe, so it must NOT be a loaded claim."""
    b = rsp.build_bundle(observation=_observation(), now=NOW)
    loaded = b["facts"]["loaded_model"]
    subjects = {f["subject_ref"] for f in loaded}
    assert _loaded_subject() in subjects  # the real /v1/models id is a loaded fact
    # no loaded_model fact is derived from RAM occupancy of a host without a /v1/models probe
    assert not any("spark" in s or "podium" in s or "gx10" in s for s in subjects)
    assert all(f["provenance"]["source"].startswith("/v1/models") for f in loaded)


def test_build_bundle_classifies_lost_unexplained_dark() -> None:
    b = rsp.build_bundle(observation=_observation(), now=NOW)
    by_id = {f["fact_id"]: f for lst in b["facts"].values() for f in lst}
    lost = [f for f in by_id.values() if "LOST" in f["state"]["reason_codes"]]
    assert {
        "declared_endpoint:serving.appendix-5000",
        "declared_endpoint:serving.appendix-5001",
    } <= {f["fact_id"] for f in lost}
    assert all(f["state"]["value_state"] == "absent" for f in lost)
    unexpl = [f for f in by_id.values() if "UNEXPLAINED" in f["state"]["reason_codes"]]
    assert any(f["subject_ref"] == _loaded_subject() for f in unexpl)
    assert all(f["state"]["value_state"] == "hold" for f in unexpl)
    assert any(f["state"]["value_state"] == "dark" for f in by_id.values())
    assert (
        "NAS-backed Docker" in by_id["declared_endpoint:serving.appendix-5000"]["value"]["backing"]
    )


def test_admitting_row_resolves_unexplained() -> None:
    b = rsp.build_bundle(
        observation=_observation(),
        now=NOW,
        admitting_rows={_loaded_subject(): "serving.ollama-embeddings"},
    )
    m = next(f for f in b["facts"]["loaded_model"] if f["subject_ref"] == _loaded_subject())
    assert m["state"]["value_state"] == "lit"
    assert "UNEXPLAINED" not in m["state"]["reason_codes"]


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
    assert any(
        u["value"].get("model") == "kimi-k3" and u["state"]["value_state"] == "lit"
        for u in b["facts"]["usage"]
    )


# --- enforcement obligation + boundary delivery -----------------------------------------------------


def test_claim_must_cite_a_fresh_resource_fact() -> None:
    b = rsp.build_bundle(observation=_observation(), now=NOW)
    some_id = b["facts"]["resource_vram"][0]["fact_id"]
    assert rsp.claim_cites_fresh_resource_fact(f"podium is free, per {some_id}", b, now=NOW) is True
    assert rsp.claim_cites_fresh_resource_fact("podium is free", b, now=NOW) is False
    assert (
        rsp.claim_cites_fresh_resource_fact(
            f"podium is free, per {some_id}", b, now=NOW + timedelta(hours=5)
        )
        is False
    )


def test_boundary_summary_names_lost_and_unexplained() -> None:
    s = rsp.resource_summary_for_boundary(rsp.build_bundle(observation=_observation(), now=NOW))
    assert "LOST" in s and "UNEXPLAINED" in s and "Cite a fact id" in s


# --- the reins contract, witnessed in CI against the vendored fixture (review #5027 finding 6) -------


def test_air_default_deny_public_or_air_is_zero() -> None:
    """Witnessed in CI (no skip): internal resource facts are DENIED on the public/on-air channel, so
    they can never leak through a derived channel. AIR default-deny is the contract."""
    b = rsp.build_bundle(observation=_observation(), now=NOW)
    assert VENDORED_REINS.project(b, "public_or_air")["fact_count"] == 0
    op = VENDORED_REINS.project(b, "operator_private")
    assert op["fact_count"] > 0
    # an UNEXPLAINED (hold) fact projects a hold affordance, never a live row
    assert any(any(e["state"] == "hold" for e in a["affordances"]) for a in op["affordances"])


def test_a_fact_missing_its_air_decision_is_dropped() -> None:
    """Defense in depth: a fact with no air decision for an audience is denied (dropped), not allowed."""
    bundle = {
        "facts": {"x": [{"fact_id": "x:1", "subject_ref": "x:1", "air": {}}]},
        "evaluation": {"bundle_state": "partial"},
    }
    assert VENDORED_REINS.project(bundle, "operator_private")["fact_count"] == 0


def test_vendored_reins_does_not_drift_from_governed() -> None:
    """Drift guard: when the governed reins is importable (HAPAX_REINS_ROOT), its projection of our
    bundle must match the vendored fixture's, so the vendored copy cannot silently diverge."""
    root = os.environ.get("HAPAX_REINS_ROOT", "").strip()
    if not root:
        pytest.skip("HAPAX_REINS_ROOT unset; vendored fixture carries the CI contract")
    if os.path.expanduser(root) not in sys.path:
        sys.path.insert(0, os.path.expanduser(root))
    try:
        import reins_context as governed  # noqa: PLC0415
    except ImportError:
        pytest.skip("governed reins_context not importable at HAPAX_REINS_ROOT")
    b = rsp.build_bundle(observation=_observation(), now=NOW)
    for aud in VENDORED_REINS.AUDIENCES:
        assert (
            governed.project(b, aud)["fact_count"] == VENDORED_REINS.project(b, aud)["fact_count"]
        )


# --- both shipped scripts (review #5027 finding 7) --------------------------------------------------


def _run(args: list[str], env: dict) -> subprocess.CompletedProcess[str]:
    base = {"PATH": os.environ["PATH"]}
    base.update(env)
    return subprocess.run(args, capture_output=True, text=True, env=base, timeout=60)


def _write_observation(tmp_path: Path) -> Path:
    obs = tmp_path / "obs.jsonl"
    obs.write_text(json.dumps(_observation()) + "\n", encoding="utf-8")
    return obs


def test_script_hapax_resources_boundary_summary(tmp_path: Path) -> None:
    obs = _write_observation(tmp_path)
    r = _run(
        [sys.executable, str(REPO / "scripts" / "hapax-resources")],
        {"HAPAX_CAPACITY_OBS": str(obs)},
    )
    assert r.returncode == 0, r.stderr
    assert "resource-state" in r.stdout and "Cite a fact id" in r.stdout


def test_script_hapax_resources_json_fails_loud_without_governed_reins(tmp_path: Path) -> None:
    """Review #5027 findings 4, 5: with no governed reins, --json must fail loud (a refused state with a
    next action, exit 3) — never the raw bundle, never the mutable dev tree."""
    obs = _write_observation(tmp_path)
    r = _run(
        [sys.executable, str(REPO / "scripts" / "hapax-resources"), "--json"],
        {"HAPAX_CAPACITY_OBS": str(obs), "HAPAX_REINS_ROOT": ""},
    )
    assert r.returncode == 3, r.stderr
    payload = json.loads(r.stdout)
    assert payload["value_state"] == "refused"
    assert "HAPAX_REINS_ROOT" in payload["next_action"]


def test_script_hapax_resources_json_projects_through_governed_reins(tmp_path: Path) -> None:
    """With HAPAX_REINS_ROOT pointing at a governed reins_context, --json projects (operator channel)."""
    reins_dir = tmp_path / "reins_api"
    reins_dir.mkdir()
    (reins_dir / "reins_context.py").write_text(
        (REPO / "tests" / "fixtures" / "reins_context_vendored.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    obs = _write_observation(tmp_path)
    r = _run(
        [sys.executable, str(REPO / "scripts" / "hapax-resources"), "--json"],
        {"HAPAX_CAPACITY_OBS": str(obs), "HAPAX_REINS_ROOT": str(reins_dir)},
    )
    assert r.returncode == 0, r.stderr
    proj = json.loads(r.stdout)
    assert proj["audience"] == "operator_private"
    assert proj["fact_count"] > 0


def test_script_hapax_capacity_observer_appends_valid_json(tmp_path: Path) -> None:
    """The observer runs read-only and appends one valid JSON observation with the producer's input
    keys, even where probes find nothing (no GPU/ssh/tmux in CI)."""
    obs = tmp_path / "cap.jsonl"
    r = _run(
        ["bash", str(REPO / "scripts" / "hapax-capacity-observer")],
        {"HAPAX_CAPACITY_OBS": str(obs)},
    )
    assert r.returncode == 0, r.stderr
    lines = [line for line in obs.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    for key in ("ts", "loaded_models", "local_endpoints", "serving_procs", "fleet_memory", "gpus"):
        assert key in rec
