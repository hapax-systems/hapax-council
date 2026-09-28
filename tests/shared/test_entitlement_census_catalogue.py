"""The shipped catalogue is a complete, parseable declaration, never a credential store."""

from pathlib import Path

from shared.entitlement_census import ENTITLEMENT_CENSUS_CONFIG, load_census_config


def test_shipped_catalogue_loads_and_names_cognition_pools():
    config = load_census_config(ENTITLEMENT_CENSUS_CONFIG)
    providers = {entry.provider for entry in config.entitlements}
    assert {
        "anthropic",
        "openai",
        "moonshot",
        "z.ai",
        "sakana",
        "verboo",
        "featherless",
    } <= providers
    assert {host.host_id for host in config.hosts} >= {"appendix", "podium"}
    assert all(entry.cost_class is not None for entry in config.entitlements)


def test_catalogue_contains_names_and_paths_not_secret_values():
    text = Path(ENTITLEMENT_CENSUS_CONFIG).read_text()
    key_type = "PRIVATE" + " KEY"
    marker = "BEGIN " + key_type
    assert "api_key_value" not in text and marker not in text
    config = load_census_config(ENTITLEMENT_CENSUS_CONFIG)
    assert all("/" not in name for entry in config.entitlements for name in entry.credential_names)


def test_vendor_cache_reader_carries_timestamp_and_safe_fields_only():
    import json

    from shared.entitlement_census import read_vendor_cache

    payload = {
        "payload": json.dumps(
            {
                "fetched_at": "2026-09-28T00:00:00Z",
                "settings": {"subscription_tier_display": "SuperGrok", "token": "must-not-project"},
            }
        )
    }
    row = read_vendor_cache("grok_settings_cache", lambda _: json.dumps(payload).encode())
    assert row.fetched_at is not None and row.facts == {"tier": "SuperGrok"}
    assert "must-not-project" not in repr(row)
