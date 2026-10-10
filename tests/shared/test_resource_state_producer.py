"""Core tests for shared.resource_state_producer — the first producer into the Reins representation
(task estate-resource-state-determinative-projection-20261004; review #5027 fix-first round).

The load-bearing contract is honest missing-state: LOST (dead declared endpoint), UNEXPLAINED (a
loaded model — from /v1/models, NEVER a RAM-occupancy heuristic — with no admitting row), and
stale-not-live. The reins AIR-projection contract tests (public_or_air -> 0) and the shipped-script
tests live in the stacked PR (`estate-resource-state-scripts-contract-tests-20261004`) to keep this
producer PR under the review size cap; both bodies cross-reference.
"""

from __future__ import annotations

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
    f = rsp._fact("resource_vram", "host:x", now=NOW, observed_at=old, value={}, value_state="lit")
    assert f["freshness_state"] == "stale"
    assert f["state"]["value_state"] == "stale"


def test_absent_observation_is_absent_not_fabricated() -> None:
    assert rsp.freshness_state(None, NOW, window_s=300) == "absent"


# --- end-to-end bundle ------------------------------------------------------------------------------


def _observation() -> dict:
    return {
        "ts": _iso(NOW),
        "host": "appendix",
        "gpus_percard": [
            "0, NVIDIA GeForce RTX 3090, 24576 MiB, 1 MiB, 24175 MiB, 0 %",
            "1, NVIDIA GeForce RTX 5060 Ti, 16311 MiB, 2 MiB, 15941 MiB, 0 %",
        ],
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
    assert _loaded_subject() in subjects
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


def _metadata_observation() -> dict:
    obs = _observation()
    obs["model_metadata"] = {
        "11434": {
            "observed_at": _iso(NOW),
            "data": [
                {
                    "id": "nomic-embed-text:latest",
                    "owned_by": "llamacpp",
                    "meta": {
                        "n_ctx": 1024,
                        "n_ctx_train": 2048,
                        "ftype": "F16",
                        "n_embd": 768,
                        "n_params": 136727040,
                        "size": 273533952,
                    },
                }
            ],
        }
    }
    # Configuration is not evidence of per-sequence effective context or model identity.
    obs["serving_procs"] = ["42 llama-server --ctx-size 8192 --model other-Q4.gguf"]
    return obs


def _metadata_facts(obs: dict) -> dict:
    bundle = rsp.build_bundle(observation=obs, now=NOW)
    return {
        f["value"]["field"]: f for f in bundle["facts"]["loaded_model"] if "field" in f["value"]
    }


@pytest.mark.parametrize("age", [0, 300, 301, 901, -1])
@pytest.mark.parametrize("suffix", ["", "/unknown"])
def test_metadata_citation_uses_exact_field_and_own_window(age, suffix) -> None:
    obs = _metadata_observation()
    obs["model_metadata"]["11434"]["observed_at"] = _iso(NOW - timedelta(seconds=age))
    bundle = rsp.build_bundle(observation=obs, now=NOW)
    field = next(
        f for f in bundle["facts"]["loaded_model"] if f["value"].get("field") == "context_tokens"
    )
    # The enclosing model is fresh: it cannot stand in for this field or an unknown child.
    claim = f"Context from `{field['fact_id']}{suffix}`"
    assert rsp.claim_cites_fresh_resource_fact(claim, bundle, now=NOW, window_s=600) is (
        not suffix and 0 <= age <= 300
    )


def test_model_metadata_preserves_effective_context_and_quant_without_process_inference() -> None:
    facts = _metadata_facts(_metadata_observation())
    expected = {
        "context_tokens": 1024,
        "training_context_tokens": 2048,
        "quantization": "F16",
        "serving_owner": "llamacpp",
        "embedding_dimensions": 768,
        "parameter_count": 136727040,
        "model_bytes": 273533952,
    }
    assert {k: f["value"]["value"] for k, f in facts.items()} == expected
    for f in facts.values():
        assert f["state"]["value_state"] == "lit"
        assert f["provenance"]["observed_at"] == _iso(NOW)
        assert f["air"]["public_or_air"] == "deny"
    assert facts["context_tokens"]["provenance"]["source"] == "/v1/models data[].meta.n_ctx"


def test_model_metadata_missing_is_absent_never_inferred_from_name_or_process() -> None:
    facts = _metadata_facts(_observation())
    assert len(facts) == 7
    assert all(f["state"]["value_state"] == "absent" for f in facts.values())
    assert all(f["value"]["value"] is None for f in facts.values())
    assert all(f["freshness_state"] == "absent" for f in facts.values())


@pytest.mark.parametrize("stamp", [None, "invalid", "2026-10-04T06:00:00", "2026-10-04T06:00:01Z"])
def test_model_metadata_requires_its_own_valid_observation_time(stamp) -> None:
    obs = _metadata_observation()
    obs["model_metadata"]["11434"]["observed_at"] = stamp
    fact = _metadata_facts(obs)["context_tokens"]
    assert fact["state"]["value_state"] == "hold"
    assert fact["freshness_state"] == "absent"


def test_model_metadata_stales_at_its_window_even_with_fresh_outer_snapshot() -> None:
    obs = _metadata_observation()
    obs["model_metadata"]["11434"]["observed_at"] = _iso(NOW - timedelta(seconds=301))
    fact = _metadata_facts(obs)["context_tokens"]
    assert fact["freshness_state"] == "stale"
    assert fact["state"]["value_state"] == "stale"


def test_model_metadata_conflicting_context_is_held_and_training_context_is_separate() -> None:
    obs = _metadata_observation()
    obs["model_metadata"]["11434"]["data"][0]["max_model_len"] = 8192
    fact = _metadata_facts(obs)["context_tokens"]
    assert fact["state"]["value_state"] == "hold"
    assert "conflicting_model_metadata" in fact["state"]["reason_codes"]
    assert fact["value"]["value"] is None
    assert _metadata_facts(obs)["training_context_tokens"]["value"]["value"] == 2048


@pytest.mark.parametrize("bad", [True, -1, 0, "1024", {}, []])
def test_model_metadata_unsupported_value_is_refused(bad) -> None:
    obs = _metadata_observation()
    obs["model_metadata"]["11434"]["data"][0]["meta"]["n_ctx"] = bad
    fact = _metadata_facts(obs)["context_tokens"]
    assert fact["state"]["value_state"] == "refused"
    assert "unsupported_model_metadata" in fact["state"]["reason_codes"]
    assert fact["value"]["value"] is None


def test_model_metadata_join_is_by_endpoint_and_exact_model() -> None:
    obs = _metadata_observation()
    obs["model_metadata"]["11434"]["data"][0]["id"] = "another-model"
    assert _metadata_facts(obs)["context_tokens"]["state"]["value_state"] == "absent"

    obs = _metadata_observation()
    obs["model_metadata"]["8000"] = obs["model_metadata"].pop("11434")
    assert _metadata_facts(obs)["context_tokens"]["state"]["value_state"] == "absent"


def test_model_metadata_duplicate_rows_do_not_choose_one_conflicting_value() -> None:
    from copy import deepcopy

    obs = _metadata_observation()
    data = obs["model_metadata"]["11434"]["data"]
    data.append(deepcopy(data[0]))
    assert _metadata_facts(obs)["context_tokens"]["value"]["value"] == 1024
    data[1]["meta"]["n_ctx"] = 8192
    fact = _metadata_facts(obs)["context_tokens"]
    assert fact["state"]["value_state"] == "hold"
    assert fact["value"]["value"] is None


@pytest.mark.parametrize("metadata", [["invalid"], {"11434": {"data": "invalid"}}])
def test_model_metadata_malformed_envelope_is_refused(metadata) -> None:
    obs = _metadata_observation()
    obs["model_metadata"] = metadata
    assert _metadata_facts(obs)["context_tokens"]["state"]["value_state"] == "refused"


def test_unsupported_endpoint_response_is_refused_not_lost() -> None:
    obs = _observation()
    obs["local_endpoints"]["5000"] = None
    b = rsp.build_bundle(observation=obs, now=NOW)
    endpoint = next(f for f in b["facts"]["declared_endpoint"] if f["value"]["port"] == "5000")
    assert endpoint["state"] == {
        "value_state": "refused",
        "reason_codes": ["unsupported_endpoint_response"],
    }
