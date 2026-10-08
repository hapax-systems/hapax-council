"""Stacked on #5027 (task estate-resource-state-scripts-contract-tests-20261004): the reins
AIR-projection contract tests and the shipped-script tests, split out of
test_resource_state_producer.py to keep the producer PR under the review size cap.

The AIR contract (public_or_air -> 0 facts; default-deny) is witnessed in CI against a vendored copy
of reins_context (review #5027 finding 6), with a drift guard vs the governed reins. Both shipped
scripts are exercised (review #5027 finding 7). These run in CI once this stack rebases onto main
after #5027 merges.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

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


def _observation(host: str = "appendix") -> dict:
    return {
        "ts": _iso(NOW),
        "host": host,
        "gpus_percard": [
            "0, NVIDIA GeForce RTX 3090, 24576 MiB, 1 MiB, 24175 MiB, 0 %",
            "1, NVIDIA GeForce RTX 5060 Ti, 16311 MiB, 2 MiB, 15941 MiB, 0 %",
        ],
        "gpus": [
            "NVIDIA GeForce RTX 3090, 24576 MiB, 1 MiB",
            "NVIDIA GeForce RTX 5060 Ti, 16311 MiB, 2 MiB",
        ],
        "fleet_memory": {
            "spark-01df": {"total_mb": 124546, "avail_mb": 13692},
            "podium": {"total_mb": 127938, "avail_mb": 94444},
            "beelink1": None,
        },
        "local_endpoints": {"5000": False, "5001": False, "11434": True},
        "loaded_models": {"5000": [], "5001": [], "11434": ["nomic-embed-text:latest"]},
        "serving_procs": ["4242 ollama serve"],
    }


# --- fix-witness tests for the #5027 re-round majors (code in #5027; witnessed here) ----------------


def test_per_card_free_and_util_are_projected() -> None:
    """Major 1: per-card FREE vram and util reach the facts (the operator's never-correct-me item),
    not just total/used; the back-compat 3-col path would have dropped them."""
    b = rsp.build_bundle(observation=_observation(), now=NOW)
    cards = [f for f in b["facts"]["resource_vram"] if "card:" in f["subject_ref"]]
    assert cards, "per-card facts must be emitted from gpus_percard"
    c0 = next(f for f in cards if f["subject_ref"].endswith("card:0"))
    assert c0["value"]["free"] == "24175 MiB"
    assert c0["value"]["util"] == "0 %"
    assert c0["state"]["value_state"] == "lit"


def test_gpus_and_endpoints_attributed_to_observed_host() -> None:
    """Major 4: local GPUs/endpoints/loaded-models carry the observer's actual host, never 'appendix'."""
    b = rsp.build_bundle(observation=_observation(host="evo-x2"), now=NOW)
    subjects = [f["subject_ref"] for lst in b["facts"].values() for f in lst]
    assert any(s == "host:evo-x2/card:0" for s in subjects)
    assert any(s == "serving.evo-x2-5000" for s in subjects)
    assert not any("appendix" in s for s in subjects)


def test_surface_absent_emits_honest_absent_fact() -> None:
    """Major 3: a missing entitlement surface yields an honest absent fact, not a silent drop."""
    b = rsp.build_bundle(observation=_observation(), surface=None, now=NOW)
    ent = b["facts"]["remote_entitlement"]
    assert len(ent) == 1
    assert ent[0]["state"]["value_state"] == "absent"
    assert "entitlement_surface_absent" in ent[0]["state"]["reason_codes"]


def test_declared_endpoint_restricted_to_declared_ports() -> None:
    """A probed-but-not-declared port (11434 ollama) is NOT reported as a declared endpoint/LOST."""
    b = rsp.build_bundle(observation=_observation(), now=NOW)
    declared = {f["subject_ref"] for f in b["facts"]["declared_endpoint"]}
    assert declared == {"serving.appendix-5000", "serving.appendix-5001"}
    assert not any("11434" in s for s in declared)


def test_backcompat_gpus_branch_is_partial_without_free_util() -> None:
    """claude #5027:147: the 3-col `gpus` back-compat path (taken only when gpus_percard is absent) must
    emit a value_state 'partial' VRAM fact with free/util None and the back-compat reason code — it must
    never fabricate a free/util it did not observe. Mutation-verified against the producer (row log)."""
    obs = _observation()
    obs.pop("gpus_percard")  # force the back-compat branch
    b = rsp.build_bundle(observation=obs, now=NOW)
    gpu_cards = [
        f
        for f in b["facts"]["resource_vram"]
        if str(f["value"].get("card", "")).startswith("NVIDIA")
    ]
    assert gpu_cards, "the 3-col gpus line must still yield per-card facts"
    c = gpu_cards[0]
    assert c["state"]["value_state"] == "partial"
    assert c["value"]["free"] is None and c["value"]["util"] is None
    assert "per_card_free_util_absent_backcompat_gpus" in c["state"]["reason_codes"]


# --- the reins contract, witnessed in CI against the vendored fixture (review #5027 finding 6) -------


def test_air_default_deny_public_or_air_is_zero() -> None:
    """Witnessed in CI (no skip): internal resource facts are DENIED on the public/on-air channel, so
    they can never leak through a derived channel. AIR default-deny is the contract."""
    b = rsp.build_bundle(observation=_observation(), now=NOW)
    assert VENDORED_REINS.project(b, "public_or_air")["fact_count"] == 0
    op = VENDORED_REINS.project(b, "operator_private")
    assert op["fact_count"] > 0
    assert any(any(e["state"] == "hold" for e in a["affordances"]) for a in op["affordances"])


def test_a_fact_missing_its_air_decision_is_dropped() -> None:
    """Defense in depth: a fact with no air decision for an audience is denied (dropped), not allowed."""
    bundle = {
        "facts": {"x": [{"fact_id": "x:1", "subject_ref": "x:1", "air": {}}]},
        "evaluation": {"bundle_state": "partial"},
    }
    assert VENDORED_REINS.project(bundle, "operator_private")["fact_count"] == 0


# The reins commit + source sha256 the vendored fixture was re-vendored from (seat #5029 delta round).
# These MUST match the header of tests/fixtures/reins_context_vendored.py.
_PINNED_REINS_COMMIT = "ff2b1a227d269cb2c04f8c0e6d5bc59303eea130"  # pragma: allowlist secret
_PINNED_REINS_SHA256 = (
    "d5e9e9dd2974d08d1dd732fae3e26ba70df766fee7dbe4f7d61ab34809f9879a"  # pragma: allowlist secret
)


def _drift_probe_bundle() -> dict:
    """A bundle that exercises every projection behaviour the drift guard must pin — not just counts:
    allow/redact/deny per audience, redactable body fields (so sealed/redacted fields are compared), and
    hold/refused value_states with reason codes."""
    b = rsp.build_bundle(observation=_observation(), now=NOW)
    b["facts"]["probe"] = [
        {
            "fact_id": "probe:redact",
            "subject_ref": "probe:redact",
            "freshness_state": "fresh",
            "confidence_word": "high",
            "air": {
                "operator_private": "allow",
                "yard_context": "redact",
                "hapax_substrate": "deny",
                "public_or_air": "deny",
            },
            "state": {"value_state": "lit", "reason_codes": ["probe_redact"]},
            "summary_ref": "SENSITIVE-SUMMARY",
            "labels": ["secret"],
            "affordance_inputs": {"can_explain": True, "can_yank_operator_private": True},
        },
        {
            "fact_id": "probe:refused",
            "subject_ref": "probe:refused",
            "freshness_state": "stale",
            "confidence_word": "low",
            "air": {
                "operator_private": "allow",
                "yard_context": "allow",
                "hapax_substrate": "allow",
                "public_or_air": "deny",
            },
            "state": {"value_state": "refused", "reason_codes": ["spine_refused"]},
            "affordance_inputs": {},
        },
    ]
    return b


def test_vendored_reins_matches_governed_full_projection() -> None:
    """Require the declared governed carrier and compare its exact file and full projections.

    Missing/unreadable bindings fail: vendored AIR tests alone are not governed parity.
    Import the hashed path directly so sys.path or a cached module cannot replace it.
    """
    root = os.environ.get("HAPAX_REINS_ROOT", "").strip()
    if not root:
        pytest.fail("HAPAX_REINS_ROOT required: bind the governed reins api directory for parity")
    root_path = Path(root).expanduser().resolve()
    governed_file = root_path / "reins_context.py"
    if not governed_file.is_file():
        pytest.fail(
            f"governed reins_context.py unavailable at {root_path}; repair the declared binding"
        )
    actual_sha = hashlib.sha256(governed_file.read_bytes()).hexdigest()
    assert actual_sha == _PINNED_REINS_SHA256, (
        f"governed reins_context.py has drifted from the pin: {actual_sha} != {_PINNED_REINS_SHA256}. "
        "Re-vendor tests/fixtures/reins_context_vendored.py and update the pin + the parent predicate."
    )
    # The COMMIT pin must resolve to a real reins commit, and reins_context.py AT that commit must hash to
    # the pinned sha — so the commit cannot be a hand-typed value that merely looks like a sha (seat #5029
    # delta round: a 42-char commit was typed by hand and never resolved). Only when root is a git tree.
    toplevel = subprocess.run(
        ["git", "-C", str(root_path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if toplevel.returncode == 0:
        repo_root = Path(toplevel.stdout.strip())
        rel = (root_path / "reins_context.py").resolve().relative_to(repo_root.resolve())
        resolved = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "rev-parse",
                "--verify",
                f"{_PINNED_REINS_COMMIT}^{{commit}}",
            ],
            capture_output=True,
            text=True,
        )
        assert resolved.returncode == 0, (
            f"pinned reins commit {_PINNED_REINS_COMMIT} does not resolve in {repo_root} "
            f"(len {len(_PINNED_REINS_COMMIT)}): {resolved.stderr.strip()}"
        )
        blob = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"{_PINNED_REINS_COMMIT}:{rel.as_posix()}"],
            capture_output=True,
        )
        assert blob.returncode == 0, (
            f"cannot read {rel} at {_PINNED_REINS_COMMIT}: {blob.stderr.decode()[:200]}"
        )
        blob_sha = hashlib.sha256(blob.stdout).hexdigest()
        assert blob_sha == _PINNED_REINS_SHA256, (
            f"reins_context.py at pinned commit {_PINNED_REINS_COMMIT} hashes {blob_sha}, not the pinned "
            f"{_PINNED_REINS_SHA256}"
        )
    governed = _load_module(governed_file, "resource_parity_governed_reins")
    b = _drift_probe_bundle()
    for aud in VENDORED_REINS.AUDIENCES:
        assert governed.project(b, aud) == VENDORED_REINS.project(b, aud), (
            f"FULL projection drift on audience {aud!r} (fields/redaction/reason-codes/sealed/affordances)"
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
    """Exercise the real observer with empty, isolated probe responses; no estate scan."""
    rec = _observer_fixture(tmp_path, {"data": []})
    for key in ("ts", "loaded_models", "local_endpoints", "serving_procs", "fleet_memory", "gpus"):
        assert key in rec


@pytest.mark.parametrize("root", ["", "/nonexistent/resource-parity-root"])
def test_governed_parity_missing_binding_fails_instead_of_skipping(monkeypatch, root) -> None:
    monkeypatch.setenv("HAPAX_REINS_ROOT", root)
    try:
        with pytest.raises(pytest.fail.Exception):
            test_vendored_reins_matches_governed_full_projection()
    except pytest.skip.Exception:
        pytest.fail("missing governed binding was skipped instead of failed")


def test_governed_parity_loads_the_hashed_file_not_a_cached_module(monkeypatch) -> None:
    import types

    monkeypatch.setitem(sys.modules, "reins_context", types.SimpleNamespace(project=lambda *_: {}))
    test_vendored_reins_matches_governed_full_projection()


def test_governed_parity_rejects_hash_drift_before_import(tmp_path, monkeypatch) -> None:
    (tmp_path / "reins_context.py").write_text(
        "raise RuntimeError('must not import drifted file')\n"
    )
    monkeypatch.setenv("HAPAX_REINS_ROOT", str(tmp_path))
    with pytest.raises(AssertionError, match="has drifted from the pin"):
        test_vendored_reins_matches_governed_full_projection()


def test_governed_parity_compares_full_projection(monkeypatch) -> None:
    original = VENDORED_REINS.project

    def changed_reason(*args):
        result = original(*args)
        result["changed_reason"] = "fixture drift beyond counts"
        return result

    monkeypatch.setattr(VENDORED_REINS, "project", changed_reason)
    with pytest.raises(AssertionError, match="FULL projection drift"):
        test_vendored_reins_matches_governed_full_projection()


def _observer_fixture(tmp_path: Path, body: dict) -> dict:
    """Run the shipped shell/Python script with every external probe replaced by a local fixture."""
    probes = tmp_path / "bin"
    probes.mkdir()
    response = tmp_path / "models.json"
    response.write_text(json.dumps(body))
    for name in ("ssh", "timeout", "tmux", "pgrep", "nvidia-smi", "hostname", "curl"):
        path = probes / name
        command = (
            'cat "$MODEL_RESPONSE"'
            if name == "curl"
            else ("echo fixture-host" if name == "hostname" else "exit 0")
        )
        path.write_text("#!/bin/sh\n" + command + "\n")
        path.chmod(0o755)
    obs = tmp_path / "cap.jsonl"
    run = _run(
        ["bash", str(REPO / "scripts/hapax-capacity-observer")],
        {
            "PATH": str(probes) + os.pathsep + os.environ["PATH"],
            "HOME": str(tmp_path),
            "MODEL_RESPONSE": str(response),
            "HAPAX_CAPACITY_OBS": str(obs),
        },
    )
    assert run.returncode == 0, run.stderr
    return json.loads(obs.read_text())


def test_observer_metadata_reaches_the_real_reader_projection(tmp_path: Path) -> None:
    rec = _observer_fixture(
        tmp_path,
        {
            "data": [
                {
                    "id": "embedding",
                    "owned_by": "llamacpp",
                    "meta": {"n_ctx": 1024, "n_ctx_train": 2048, "ftype": "F16"},
                    "private_unrelated_field": "MUST-NOT-CARRY",
                }
            ]
        },
    )
    assert "MUST-NOT-CARRY" not in json.dumps(rec)
    assert rec["model_metadata"]["8000"]["data"][0]["meta"]["n_ctx"] == 1024
    run = _run(
        [sys.executable, str(REPO / "scripts/hapax-resources"), "--json"],
        {
            "HAPAX_CAPACITY_OBS": str(tmp_path / "cap.jsonl"),
            "HAPAX_REINS_ROOT": os.environ["HAPAX_REINS_ROOT"],
            "HAPAX_ENTITLEMENT_SURFACE": str(tmp_path / "absent"),
            "HAPAX_KIMI_BENCH_LEDGER": str(tmp_path / "absent"),
        },
    )
    assert run.returncode == 0, run.stderr
    projection = json.loads(run.stdout)
    context = next(
        f
        for f in projection["facts"]
        if f["subject_ref"] == "host:fixture-host:8000/embedding/field:context_tokens"
    )
    assert context["value"]["value"] == 1024
    assert context["state"]["value_state"] == "lit"
    assert context["provenance"]["observed_at"] == rec["model_metadata"]["8000"]["observed_at"]
    assert projection["audience"] == "operator_private"


@pytest.mark.parametrize("body", [{"error": "not a model list"}, {"data": "bad"}])
def test_observer_unsupported_model_listing_cannot_be_alive(tmp_path: Path, body) -> None:
    rec = _observer_fixture(tmp_path, body)
    assert not any(rec["local_endpoints"].values())
    assert all(not ids for ids in rec["loaded_models"].values())


def test_observer_composite_metadata_is_refused_without_carrying_bodies(tmp_path: Path) -> None:
    rec = _observer_fixture(
        tmp_path, {"data": [{"id": "m", "meta": {"n_ctx": {"private": "MUST-NOT-CARRY"}}}]}
    )
    assert "MUST-NOT-CARRY" not in json.dumps(rec)
    bundle = rsp.build_bundle(observation=rec)
    context = next(
        f for f in bundle["facts"]["loaded_model"] if f["value"].get("field") == "context_tokens"
    )
    assert context["state"]["value_state"] == "refused"


@pytest.mark.parametrize("job_name", ["test", "test-full-shard"])
def test_ci_materializes_the_governed_parity_binding_in_both_pytest_jobs(job_name) -> None:
    workflow = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"][job_name]
    assert job.get("env", {}).get("HAPAX_REINS_ROOT") == "${{ github.workspace }}/.ci-reins/api"
    steps = job["steps"]
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
    governed = next(s for s in steps if s.get("name") == "Check out governed Reins parity source")
    assert governed["uses"] == checkout["uses"]
    assert governed.get("if") == checkout.get("if")
    assert governed["with"] == {
        "repository": "hapax-systems/reins",
        "ref": _PINNED_REINS_COMMIT,
        "path": ".ci-reins",
        "persist-credentials": False,
    }
    assert steps.index(checkout) < steps.index(governed)
