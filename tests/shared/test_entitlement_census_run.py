"""A census run retains declared rows and stops probing at the configured budget."""

import json
from datetime import UTC, datetime

from shared.entitlement_census import (
    CensusConfig,
    EntitlementState,
    HostHoldings,
    attach_history,
    render_view,
    run_census,
)

NOW = datetime(2026, 9, 28, tzinfo=UTC)


def _config(*, terms=False, metal=None):
    return CensusConfig.model_validate(
        {
            "schema": "hapax.entitlement_census.v1",
            "hosts": [{"host_id": "appendix", "transport": "local"}],
            "entitlements": [
                {
                    "entitlement_id": "sample",
                    "provider": "sample",
                    "kind": "cognition",
                    "cost_class": "subscription",
                    "credential_names": ["sample-key"],
                    "terms_restricted": terms,
                    **(
                        {}
                        if terms
                        else {
                            "readbacks": [
                                {"readback_id": "kimi_usages", "credential_name": "sample-key"}
                            ]
                        }
                    ),
                }
            ],
            "metal": metal or {},
        }
    )


def _run(config, holdings, *, home_files=None, **kwargs):
    return run_census(
        config,
        now=NOW,
        holdings=holdings,
        registry={},
        inventory_dispositions={},
        ledger=None,
        prior_view=None,
        resolve_secret=lambda _: "fixture-secret-value",
        http_get=lambda *_: (_ for _ in ()).throw(AssertionError("network probe forbidden")),
        read_home_file=lambda path: (home_files or {}).get(path),
        **kwargs,
    )


def test_every_declared_row_survives_absent_evidence():
    result = _run(_config(), [HostHoldings(host_id="appendix", reachable=True, observed_at=NOW)])
    assert [row.entitlement_id for row in result.rows] == ["sample"]
    assert result.rows[0].state is EntitlementState.UNOBSERVED
    assert result.potential["dispatch_reads"] is False
    assert result.rows[0].utilization == {
        "basis": "none",
        "monthly_cost_usd": None,
        "underuse": None,
        "reason": "no utilization reading",
    }


def test_spent_deadline_skips_secret_resolution_and_network():
    held = HostHoldings(
        host_id="appendix", reachable=True, observed_at=NOW, filestore_names=("sample-key",)
    )
    result = _run(_config(), [held], deadline=0, clock=lambda: 1)
    assert result.rows[0].state is EntitlementState.HELD
    assert result.rows[0].readbacks[0]["outcome"] == "unobserved"
    assert result.measurements == []


def test_terms_restricted_provider_is_never_probed():
    held = HostHoldings(
        host_id="appendix", reachable=True, observed_at=NOW, filestore_names=("sample-key",)
    )
    result = _run(_config(terms=True), [held])
    assert result.rows[0].state is EntitlementState.TERMS_RESTRICTED
    assert not result.rows[0].readbacks


def test_hardware_candidate_requires_enumeration_to_be_available():
    fact = {
        "host_id": "appendix",
        "device": "external GPU",
        "memory_gb": 32,
        "availability": "unavailable",
        "enumerate_gpu": "RTX 5090",
        "source": "fixture",
        "recorded_at": "2026-09-28T00:00:00Z",
        "expires_at": "2026-10-28T00:00:00Z",
    }
    config = _config(metal={"hardware": [fact]})
    held = [HostHoldings(host_id="appendix", reachable=True, observed_at=NOW)]
    before = _run(config, held)
    assert before.potential["hardware"][0]["availability"] == "unavailable"
    after = _run(config, held, gpu_probe=lambda _: (True, ["RTX 5090"]))
    assert after.potential["hardware"][0]["availability"] == "enumerated"


def test_projection_names_paid_unjudged_and_absent_trend():
    config = _config()
    paid = config.entitlements[0].model_copy(update={"monthly_cost_usd": 90.0})
    config = config.model_copy(update={"entitlements": (paid,)})
    result = _run(config, [HostHoldings(host_id="appendix", reachable=True, observed_at=NOW)])
    view = render_view(result, now=NOW)
    assert view["paid_unjudged"][0]["entitlement_id"] == "sample"
    assert view["underuse"] == [] and view["utilization_unjudged"] == 1
    assert view["trend"]["points"] == 0
    attach_history(result, now=NOW, prior=[], demand={"queued": {"queued": 1}}, witness={})
    view = render_view(result, now=NOW)
    assert view["trend"]["points"] == 1
    assert view["trend"]["availability"]["direction"] == "insufficient_history"


def test_vendor_cache_past_its_bound_is_stale_not_live():
    config = _config()
    decl = config.entitlements[0].model_copy(update={"vendor_cache": "grok_settings_cache"})
    config = config.model_copy(update={"entitlements": (decl,)})
    cache = {
        "payload": json.dumps(
            {
                "fetched_at": "2026-09-20T00:00:00Z",
                "settings": {"subscription_tier_display": "tier"},
            }
        )
    }
    run = _run(
        config,
        [HostHoldings(host_id="appendix", reachable=True, observed_at=NOW)],
        home_files={".grok/settings_cache.json": json.dumps(cache).encode()},
    )
    row = run.rows[0]
    assert row.state is EntitlementState.STALE
    assert any("past its" in reason for reason in row.reasons)
    assert row.fresh_until is not None and row.fresh_until < NOW
