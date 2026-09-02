from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from shared.estate_store_registry import (
    DEFAULT_REGISTRY_PATH,
    RegistryError,
    enumerate_stores,
    load_registry,
)


def test_registry_covers_every_declared_consumer_and_vendor_roots_are_flag_only() -> None:
    registry = load_registry()

    consumers = {consumer for store in registry.stores for consumer in store.consumers}
    assert consumers == {
        "assemble",
        "brief-dispatch",
        "census",
        "drift-sweep",
        "pillar-matcher",
        "task-intake",
    }
    vendor_ids = {store.id for store in registry.stores if store.store_class == "vendor-root"}
    assert vendor_ids == {
        "claude-code-project-stores",
        "claude-code-vendor-root",
        "codex-vendor-root",
        "gemini-vendor-root",
        "grok-vendor-root",
        "kimi-vendor-root",
        "opencode-vendor-root",
    }
    assert all(store.action == "flag-only" for store in registry.stores)


def test_registry_rejects_vendor_root_quarantine_even_if_general_policy_is_edited(
    tmp_path: Path,
) -> None:
    payload = yaml.safe_load(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    vendor = next(row for row in payload["stores"] if row["class"] == "vendor-root")
    vendor["action"] = "quarantine"
    mutated = tmp_path / "registry.yaml"
    mutated.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(RegistryError, match="non-reporting action|flag-only"):
        load_registry(mutated)


def test_grandfathered_rows_have_evidence_and_no_blessing_claim() -> None:
    registry = load_registry()

    grandfathered = [store for store in registry.stores if store.lifecycle == "grandfathered"]
    assert grandfathered
    assert all(store.discovery_evidence for store in grandfathered)
    assert all(not hasattr(store, "operator_blessing") for store in grandfathered)


def test_unknown_host_refuses_instead_of_assuming_a_peer() -> None:
    registry = load_registry()

    with pytest.raises(RegistryError, match="add its alias and peer binding"):
        registry.host_id("unregistered-host")


def test_consumer_enumeration_returns_only_declared_rows_with_resolved_paths(
    tmp_path: Path,
) -> None:
    registry = load_registry()

    stores = enumerate_stores(
        registry, consumer="assemble", host="appendix", home=tmp_path / "operator"
    )

    assert stores
    assert all("assemble" in store.consumers for store in stores)
    assert all("{home}" not in store.locator and "{vault}" not in store.locator for store in stores)
    assert all(store.id != "podium-minio" for store in stores)
