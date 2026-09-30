"""Direct pins for the shared registry's custody-backed lookup surface."""

from __future__ import annotations

from pathlib import Path

from shared.governance.consent import ConsentContract, ConsentRegistry, load_contracts


def test_registry_lookup_keeps_canonical_contract_and_category(tmp_path: Path):
    registry = ConsentRegistry(
        _contracts={
            "synthetic-successor-contract": ConsentContract(
                "synthetic-successor-contract",
                ("operator", "synthetic-successor-subject"),
                frozenset({"audio"}),
            )
        }
    )

    assert registry.get("synthetic-predecessor-contract") is not None
    assert registry.contract_check("synthetic-predecessor-subject", "audio") is True
    assert registry.subject_data_categories("synthetic-predecessor-subject") == frozenset({"audio"})


def test_registry_load_uses_the_declared_contract_directory(tmp_path: Path):
    (tmp_path / "synthetic-contract.yaml").write_text(
        "id: synthetic-contract\nparties: [operator, synthetic-successor-subject]\n"
        "scope: [audio]\n",
        encoding="utf-8",
    )

    registry = load_contracts(tmp_path)

    assert registry.contract_check("synthetic-successor-subject", "audio") is True
