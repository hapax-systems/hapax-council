"""Synthetic CLI output and actionable refusal witnesses."""

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest
import yaml

from shared.governance import consent
from tests.shared.synthetic_custody import CONTRACT, OLD_CONTRACT, OLD_PRINCIPAL, PRINCIPAL


def load_script(name):
    path = Path(__file__).resolve().parents[2] / "scripts" / name
    loader = importlib.machinery.SourceFileLoader("synthetic_script", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.mark.parametrize("command", ["list", "revoke"])
def test_guest_commands_export_only_canonical_ids(
    command, synthetic_custody, monkeypatch, tmp_path, capsys
):
    module = load_script("hapax-guest-consent")
    directory = tmp_path / "contracts"
    directory.mkdir()
    (directory / "synthetic-contract.yaml").write_text(
        yaml.safe_dump(
            {"id": OLD_CONTRACT, "parties": ["operator", OLD_PRINCIPAL], "scope": ["world_render"]}
        )
    )
    monkeypatch.setenv("HAPAX_GUEST_CONSENT_DIR", str(directory))
    snapshot = consent.load_identity_snapshot()
    assert module.main([command, PRINCIPAL] if command == "revoke" else [command]) == 0
    output = capsys.readouterr()
    assert CONTRACT in output.out and PRINCIPAL in output.out
    assert not snapshot.contains_predecessor(output.out + output.err)


@pytest.mark.parametrize("active", [True, False])
def test_archive_consent_check_exports_canonical_contract(active, synthetic_custody, tmp_path):
    module = load_script("archive-purge.py")
    directory = tmp_path / "contracts"
    directory.mkdir()
    (directory / "synthetic-contract.yaml").write_text(
        yaml.safe_dump(
            {
                "id": OLD_CONTRACT,
                "parties": ["operator", OLD_PRINCIPAL],
                "scope": ["audio"],
                "revoked_at": None if active else "2026-01-01",
            }
        )
    )
    allowed, message = module._consent_revocation_check(OLD_PRINCIPAL, directory)
    assert allowed is not active
    assert PRINCIPAL in message
    if active:
        assert CONTRACT in message and "revoke it" in message
    assert not consent.load_identity_snapshot().contains_predecessor(message)


def test_guest_source_refusal_has_safe_cause_and_next_action(
    synthetic_custody, monkeypatch, tmp_path, capsys
):
    module = load_script("screwm-guest-source.py")

    def refused(*args, **kwargs):
        raise PermissionError(f"synthetic refusal {OLD_PRINCIPAL}")

    monkeypatch.setattr(module.ConsentRegistry, "load", refused)
    assert not module.consented(OLD_PRINCIPAL, tmp_path)
    output = capsys.readouterr()
    assert "consent_unavailable" in output.err
    assert "cause_class=PermissionError" in output.err
    assert "restore identity custody before retrying" in output.err
    assert OLD_PRINCIPAL not in output.err
