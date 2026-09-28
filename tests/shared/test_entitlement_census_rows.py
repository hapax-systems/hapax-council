"""Joined rows preserve absence, host blindness, and rejected credential evidence."""

from datetime import UTC, datetime

from shared.entitlement_census import (
    CensusConfig,
    EntitlementState,
    HostHoldings,
    HttpResponse,
    ReadbackRef,
    _decl_row,
    _outcome,
    _prior_rows,
    _serving_row,
    _unidentified_rows,
)

NOW = datetime(2026, 9, 28, tzinfo=UTC)


def _config():
    return CensusConfig.model_validate(
        {
            "schema": "hapax.entitlement_census.v1",
            "hosts": [{"host_id": "appendix", "transport": "local"}],
            "entitlements": [
                {
                    "entitlement_id": "kimi",
                    "provider": "moonshot",
                    "kind": "cognition",
                    "cost_class": "subscription",
                    "credential_names": ["kimi-api-key"],
                    "readbacks": [
                        {"readback_id": "kimi_usages", "credential_name": "kimi-api-key"}
                    ],
                }
            ],
        }
    )


def _row(config, holdings, prior=None, readbacks=None):
    return _decl_row(
        config.entitlements[0],
        now=NOW,
        config=config,
        holdings=holdings,
        readbacks=readbacks or {},
        cache=None,
        registry={},
        inventory_dispositions={},
        ledger=None,
        prior=prior,
    )


def test_vanished_row_is_retained_with_last_seen():
    config = _config()
    prior = _prior_rows(
        {
            "rows": [
                {
                    "entitlement_id": "kimi",
                    "provider": "moonshot",
                    "kind": "cognition",
                    "entitlement_shape": "cognition_provider",
                    "hosts": ["appendix"],
                    "last_seen": "2026-09-27T00:00:00Z",
                }
            ]
        }
    )["kimi"]
    reachable = HostHoldings(host_id="appendix", reachable=True, observed_at=NOW)
    row = _row(config, [reachable], prior)
    assert row.state is EntitlementState.ABSENT
    assert row.last_seen == datetime(2026, 9, 27, tzinfo=UTC)
    blind = HostHoldings(
        host_id="appendix", reachable=False, observed_at=None, error="ssh_exit_255"
    )
    row = _row(config, [blind], prior)
    assert row.state is EntitlementState.UNOBSERVED and row.last_seen is not None


def test_rejected_key_is_dead_and_403_is_unobserved():
    config = _config()
    held = HostHoldings(
        host_id="appendix", reachable=True, observed_at=NOW, filestore_names=("kimi-api-key",)
    )
    ref = ReadbackRef(readback_id="kimi_usages", credential_name="kimi-api-key")
    for status, expected in [(401, EntitlementState.DEAD), (403, EntitlementState.HELD)]:
        result = _outcome(ref.readback_id, HttpResponse(status, b"", None), "kimi_usages", now=NOW)
        row = _row(config, [held], readbacks={(ref.readback_id, ref.secret): result})
        assert row.state is expected


def test_unidentified_names_are_retained_as_unknown_cost():
    config = _config()
    held = HostHoldings(
        host_id="appendix",
        reachable=True,
        observed_at=NOW,
        filestore_names=("kimi-api-key", "mastadon-access-token"),
    )
    rows, _ = _unidentified_rows(config, now=NOW, holdings=[held], priors={})
    assert any(row.cost_class.value == "unobserved" for row in rows)


def test_spent_budget_makes_serving_row_unobserved_without_probe():
    from shared.entitlement_census import ServingEndpoint

    endpoint = ServingEndpoint(
        endpoint_id="fixture",
        host_id="appendix",
        base_url="http://fixture",
        models_path="/v1/models",
    )
    row = _serving_row(
        endpoint,
        now=NOW,
        http_get=lambda *_: (_ for _ in ()).throw(AssertionError("probe forbidden after deadline")),
        registry={},
        inventory_dispositions={},
        prior=None,
        remaining=0,
    )
    assert row.state is EntitlementState.UNOBSERVED
