"""The census emits only existing typed surface deltas with stable identity."""

from datetime import UTC, datetime

from shared.capability_surface_delta import DeltaKind
from shared.entitlement_census import (
    CensusConfig,
    CensusRun,
    HostHoldings,
    HttpResponse,
    SecretRegister,
    _decl_row,
    _outcome,
    census_surface_deltas,
    delta_file,
)

NOW = datetime(2026, 9, 28, tzinfo=UTC)


def _case(*, route=None, dead=False):
    payload = {
        "schema": "hapax.entitlement_census.v1",
        "hosts": [{"host_id": "appendix", "transport": "local"}],
        "entitlements": [
            {
                "entitlement_id": "sample",
                "provider": "sample",
                "kind": "cognition",
                "cost_class": "payg",
                "credential_names": ["sample-key"],
                "readbacks": [{"readback_id": "openai_models", "credential_name": "sample-key"}],
                "registry_route_ids": [route] if route else [],
            }
        ],
    }
    config = CensusConfig.model_validate(payload)
    registry = (
        {"routes": [{"route_id": route, "platform": "sample", "route_state": "active"}]}
        if route
        else {}
    )
    holdings = [
        HostHoldings(
            host_id="appendix", reachable=True, observed_at=NOW, filestore_names=("sample-key",)
        )
    ]
    results = {}
    if dead:
        results[("openai_models", "sample-key")] = _outcome(
            "openai_models", HttpResponse(401, b"", None), "status_only", now=NOW
        )
    row = _decl_row(
        config.entitlements[0],
        now=NOW,
        config=config,
        holdings=holdings,
        readbacks=results,
        cache=None,
        registry=registry,
        ledger=None,
        prior=None,
    )
    return config, registry, holdings, row


def test_held_undeclared_and_declared_dead_have_typed_deltas():
    config, registry, _, row = _case()
    _, deltas = census_surface_deltas(config, [row], registry, now=NOW)
    assert [(d.surface_id, d.delta_kind) for d in deltas] == [
        ("entitlement.sample", DeltaKind.NEW_CAPABILITY)
    ]
    config, registry, _, row = _case(route="sample.route", dead=True)
    _, deltas = census_surface_deltas(config, [row], registry, now=NOW)
    assert [(d.surface_id, d.delta_kind) for d in deltas] == [
        ("sample.route", DeltaKind.ABSENT_DETERMINATION)
    ]


def test_delta_identity_is_stable_across_runs_and_file_uses_existing_schema():
    config, registry, holdings, row = _case()
    descriptors, deltas = census_surface_deltas(config, [row], registry, now=NOW)
    later_descriptors, later = census_surface_deltas(
        config, [row], registry, now=NOW.replace(hour=21)
    )
    assert [d.delta_id for d in deltas] == [d.delta_id for d in later]
    run = CensusRun(
        now=NOW,
        config=config,
        rows=[row],
        holdings=holdings,
        unclassified={},
        potential={},
        descriptors=descriptors,
        deltas=deltas,
        measurements=[],
        secrets=SecretRegister(),
    )
    artifact = delta_file(run)
    assert artifact is not None and artifact.deltas[0].delta_id == deltas[0].delta_id
