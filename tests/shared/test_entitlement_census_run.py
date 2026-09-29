"""A census run retains declared rows and stops probing at the configured budget."""

from datetime import UTC, datetime

from shared.entitlement_census import CensusConfig, EntitlementState, HostHoldings, run_census

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


def _run(config, holdings, **kwargs):
    return run_census(
        config,
        now=NOW,
        holdings=holdings,
        registry={},
        ledger=None,
        prior_view=None,
        resolve_secret=lambda _: "fixture-secret-value",
        http_get=lambda *_: (_ for _ in ()).throw(AssertionError("network probe forbidden")),
        read_home_file=lambda _: None,
        **kwargs,
    )


def test_every_declared_row_survives_absent_evidence():
    result = _run(_config(), [HostHoldings(host_id="appendix", reachable=True, observed_at=NOW)])
    assert [row.entitlement_id for row in result.rows] == ["sample"]
    assert result.rows[0].state is EntitlementState.UNOBSERVED
    assert result.potential["dispatch_reads"] is False


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
