"""Tests for ``agents.payment_processors.x402.license_registry``.

Pin the YAML loader's strict validation, the registry's exhaustiveness
contract (every :class:`LicenseClass` member has a row), and the
``apply_to_accept`` helper's idempotence + non-overwriting behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.payment_processors.x402.license_registry import (
    DEFAULT_CONFIG_PATH,
    EXTRA_KEY,
    LICENSE_CLASS_REGISTRY,
    LicenseClass,
    LicenseRegistryError,
    apply_to_accept,
    load_registry,
)
from agents.payment_processors.x402.models import Accept


def _accept(**overrides) -> Accept:  # type: ignore[no-untyped-def]
    base = {
        "scheme": "exact",
        "network": "eip155:8453",
        "amount": "1",
        "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        "payTo": "0xRecipient",
        "maxTimeoutSeconds": 60,
        "extra": {},
    }
    base.update(overrides)
    return Accept.model_validate(base)


# ── Default registry (loaded from config/x402-license-classes.yaml) ─


class TestDefaultRegistry:
    def test_loads_at_import_time(self) -> None:
        assert LicenseClass.COMMERCIAL in LICENSE_CLASS_REGISTRY
        assert LicenseClass.RESEARCH in LICENSE_CLASS_REGISTRY
        assert LicenseClass.REVIEW in LICENSE_CLASS_REGISTRY

    def test_default_config_path_resolves_to_repo_config(self) -> None:
        assert DEFAULT_CONFIG_PATH.is_file()
        assert DEFAULT_CONFIG_PATH.name == "x402-license-classes.yaml"

    def test_every_entry_has_required_fields(self) -> None:
        for entry in LICENSE_CLASS_REGISTRY.values():
            assert entry.class_id in LicenseClass
            assert entry.default_amount.isdigit()
            assert entry.default_asset.startswith("0x") or len(entry.default_asset) > 0
            assert entry.default_network.startswith("eip155:")
            assert entry.description

    def test_commercial_amount_higher_than_research(self) -> None:
        commercial = int(LICENSE_CLASS_REGISTRY[LicenseClass.COMMERCIAL].default_amount)
        research = int(LICENSE_CLASS_REGISTRY[LicenseClass.RESEARCH].default_amount)
        review = int(LICENSE_CLASS_REGISTRY[LicenseClass.REVIEW].default_amount)
        assert commercial >= research >= review


# ── load_registry validation ─────────────────────────────────────────


class TestLoadRegistry:
    def _write_yaml(self, tmp_path: Path, content: str) -> Path:
        target = tmp_path / "x402-license-classes.yaml"
        target.write_text(content, encoding="utf-8")
        return target

    def test_raises_when_file_missing(self, tmp_path: Path) -> None:
        with pytest.raises(LicenseRegistryError, match="missing"):
            load_registry(tmp_path / "nope.yaml")

    def test_raises_when_top_level_not_mapping(self, tmp_path: Path) -> None:
        path = self._write_yaml(tmp_path, "- just a list\n- of\n- strings\n")
        with pytest.raises(LicenseRegistryError, match="classes"):
            load_registry(path)

    def test_raises_when_classes_empty(self, tmp_path: Path) -> None:
        path = self._write_yaml(tmp_path, "classes: []\n")
        with pytest.raises(LicenseRegistryError, match="non-empty list"):
            load_registry(path)

    def test_raises_when_class_id_unknown(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "classes:\n  - id: vandal\n    default_amount: '0'\n    default_asset: '0xX'\n    default_network: 'eip155:8453'\n",
        )
        with pytest.raises(LicenseRegistryError, match="unknown or missing"):
            load_registry(path)

    def test_raises_when_amount_not_integer_string(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "classes:\n  - id: commercial\n    default_amount: 'oops'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n  - id: research\n    default_amount: '1'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n  - id: review\n    default_amount: '0'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n",
        )
        with pytest.raises(LicenseRegistryError, match="integer string"):
            load_registry(path)

    def test_raises_when_network_not_caip(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "classes:\n  - id: commercial\n    default_amount: '1'\n    default_asset: '0xA'\n    default_network: 'solana:101'\n  - id: research\n    default_amount: '1'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n  - id: review\n    default_amount: '0'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n",
        )
        with pytest.raises(LicenseRegistryError, match="CAIP"):
            load_registry(path)

    def test_raises_when_asset_empty(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "classes:\n  - id: commercial\n    default_amount: '1'\n    default_asset: ''\n    default_network: 'eip155:8453'\n  - id: research\n    default_amount: '1'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n  - id: review\n    default_amount: '0'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n",
        )
        with pytest.raises(LicenseRegistryError, match="non-empty"):
            load_registry(path)

    def test_raises_when_classes_incomplete(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "classes:\n  - id: commercial\n    default_amount: '1'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n  - id: research\n    default_amount: '1'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n",
        )
        with pytest.raises(LicenseRegistryError, match="missing classes"):
            load_registry(path)

    def test_raises_when_duplicate_class(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "classes:\n  - id: commercial\n    default_amount: '1'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n  - id: commercial\n    default_amount: '2'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n  - id: research\n    default_amount: '1'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n  - id: review\n    default_amount: '0'\n    default_asset: '0xA'\n    default_network: 'eip155:8453'\n",
        )
        with pytest.raises(LicenseRegistryError, match="duplicate"):
            load_registry(path)


# ── LicenseClassEntry frozen ─────────────────────────────────────────


class TestLicenseClassEntryFrozen:
    def test_cannot_mutate_at_runtime(self) -> None:
        entry = LICENSE_CLASS_REGISTRY[LicenseClass.COMMERCIAL]
        with pytest.raises(Exception):  # FrozenInstanceError
            entry.default_amount = "999"  # type: ignore[misc]


# ── apply_to_accept ──────────────────────────────────────────────────


class TestApplyToAccept:
    def test_injects_extra_class_id(self) -> None:
        a = _accept()
        out = apply_to_accept(a, LicenseClass.COMMERCIAL)
        assert out.extra[EXTRA_KEY] == "commercial"

    def test_preserves_caller_extra_entries(self) -> None:
        a = _accept(extra={"name": "USDC", "version": "2"})
        out = apply_to_accept(a, LicenseClass.RESEARCH)
        assert out.extra["name"] == "USDC"
        assert out.extra["version"] == "2"
        assert out.extra[EXTRA_KEY] == "research"

    def test_does_not_mutate_input(self) -> None:
        a = _accept(extra={"name": "USDC"})
        apply_to_accept(a, LicenseClass.COMMERCIAL)
        assert EXTRA_KEY not in a.extra
        assert a.extra == {"name": "USDC"}

    def test_idempotent_same_class(self) -> None:
        a = _accept()
        once = apply_to_accept(a, LicenseClass.RESEARCH)
        twice = apply_to_accept(once, LicenseClass.RESEARCH)
        assert once == twice

    def test_class_change_replaces_id(self) -> None:
        a = _accept()
        commercial = apply_to_accept(a, LicenseClass.COMMERCIAL)
        switched = apply_to_accept(commercial, LicenseClass.RESEARCH)
        assert switched.extra[EXTRA_KEY] == "research"

    def test_caller_amount_not_overwritten(self) -> None:
        a = _accept(amount="50000")
        out = apply_to_accept(a, LicenseClass.COMMERCIAL)
        assert out.amount == "50000"

    def test_returned_accept_validates(self) -> None:
        a = _accept()
        out = apply_to_accept(a, LicenseClass.REVIEW)
        Accept.model_validate_json(out.model_dump_json())
