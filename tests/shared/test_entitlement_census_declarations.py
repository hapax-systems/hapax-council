"""The producer's declaration boundary before any host or provider I/O."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.entitlement_census import (
    READBACKS,
    CensusConfig,
    CensusConfigError,
    load_census_config,
    load_registry,
)


def _payload(**entitlement):
    return {
        "schema": "hapax.entitlement_census.v1",
        "hosts": [{"host_id": "appendix", "transport": "local"}],
        "entitlements": [
            {
                "entitlement_id": "sample",
                "provider": "sample",
                "kind": "cognition",
                "cost_class": "subscription",
                **entitlement,
            }
        ],
    }


def test_readbacks_are_fixed_spend_free_get_targets():
    assert READBACKS
    for readback in READBACKS.values():
        assert readback.url.startswith("https://")
        assert not any(word in readback.url.lower() for word in ("completion", "chat/", "generate"))
    with pytest.raises(ValidationError, match="allow-list"):
        CensusConfig.model_validate(
            _payload(readbacks=[{"readback_id": "chat", "credential_name": "name"}])
        )
    with pytest.raises(ValidationError):
        CensusConfig.model_validate(
            _payload(
                readbacks=[
                    {"readback_id": "kimi_usages", "credential_name": "name", "method": "POST"}
                ]
            )
        )


def test_cost_class_and_unique_ids_are_required():
    payload = _payload()
    del payload["entitlements"][0]["cost_class"]
    with pytest.raises(ValidationError, match="cost_class"):
        CensusConfig.model_validate(payload)
    payload = _payload()
    payload["entitlements"].append(payload["entitlements"][0].copy())
    with pytest.raises(ValidationError, match="duplicate entitlement_id"):
        CensusConfig.model_validate(payload)
    assert CensusConfig.model_validate(_payload()).entitlements[0].entitlement_id == "sample"


@pytest.mark.parametrize("section", ["hardware", "trial_records"])
def test_potential_dates_must_be_timezone_aware(section):
    payload = _payload()
    item = {"recorded_at": "2026-09-28T00:00:00Z", "expires_at": "2026-10-28T00:00:00"}
    if section == "hardware":
        item.update(
            host_id="appendix",
            device="GPU",
            memory_gb=32,
            availability="available",
            source="fixture",
        )
    else:
        item.update(model="candidate", stage="candidate_to_experiment", evidence="fixture")
    payload["metal"] = {section: [item]}
    with pytest.raises(ValidationError, match="timezone"):
        CensusConfig.model_validate(payload)


def test_terms_restriction_cannot_name_readback():
    with pytest.raises(ValidationError, match="terms-restricted"):
        CensusConfig.model_validate(
            _payload(
                terms_restricted=True,
                readbacks=[{"readback_id": "kimi_usages", "credential_name": "name"}],
            )
        )


@pytest.mark.parametrize("text", [None, "[1]", "{", '{"routes": null}'])
def test_registry_read_fails_closed(tmp_path: Path, text: str | None):
    path = tmp_path / "registry.json"
    if text is not None:
        path.write_text(text)
    with pytest.raises(CensusConfigError, match="Next action|next action"):
        load_registry(path)
    path.write_text(json.dumps({}))
    assert load_registry(path) == {}


def test_shipped_declaration_loader_fails_closed(tmp_path: Path):
    path = tmp_path / "declaration.json"
    with pytest.raises(CensusConfigError, match="next action"):
        load_census_config(path)
    path.write_text(json.dumps(_payload()))
    assert load_census_config(path).entitlements[0].entitlement_id == "sample"


def test_vendor_cache_declaration_validates_before_cache_reader_is_installed(tmp_path: Path):
    path = tmp_path / "declaration.json"
    path.write_text(json.dumps(_payload(vendor_cache="vibe_whoami_cache")))
    assert load_census_config(path).entitlements[0].vendor_cache == "vibe_whoami_cache"

    path.write_text(json.dumps(_payload(vendor_cache="unknown_cache")))
    with pytest.raises(CensusConfigError, match="unknown vendor cache"):
        load_census_config(path)
