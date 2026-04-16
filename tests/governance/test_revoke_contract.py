"""Tests for ConsentRegistry.revoke_contract (LRR Phase 6 §7)."""

from __future__ import annotations

import pytest

from shared.governance.consent import ConsentRegistry


def _write_contract(directory, contract_id="test-subject"):
    (directory / f"{contract_id}.yaml").write_text(
        f"""\
id: {contract_id}
parties:
  - operator
  - {contract_id}
scope:
  - audio
direction: one_way
visibility_mechanism: on_request
created_at: "2026-04-16T00:00:00"
principal_class: adult
"""
    )


@pytest.fixture
def loaded_registry(tmp_path):
    _write_contract(tmp_path)
    registry = ConsentRegistry()
    registry.load(tmp_path)
    return registry, tmp_path


class TestRevokeContract:
    def test_revoke_marks_contract_inactive_in_memory(self, loaded_registry):
        registry, contracts_dir = loaded_registry
        assert registry.contract_check("test-subject", "audio") is True
        registry.revoke_contract("test-subject", contracts_dir=contracts_dir)
        assert registry.contract_check("test-subject", "audio") is False

    def test_revoke_moves_yaml_to_revoked_dir(self, loaded_registry):
        registry, contracts_dir = loaded_registry
        assert (contracts_dir / "test-subject.yaml").exists()
        registry.revoke_contract("test-subject", contracts_dir=contracts_dir)
        assert not (contracts_dir / "test-subject.yaml").exists()
        revoked_dir = contracts_dir / "revoked"
        assert revoked_dir.exists()
        assert any(p.name.endswith("test-subject.yaml") for p in revoked_dir.iterdir())

    def test_revoke_returns_elapsed_seconds(self, loaded_registry):
        registry, contracts_dir = loaded_registry
        elapsed = registry.revoke_contract("test-subject", contracts_dir=contracts_dir)
        assert isinstance(elapsed, float)
        # Real revoke finishes in single-digit milliseconds
        assert 0.0 <= elapsed < 1.0

    def test_revoke_nonexistent_raises_keyerror(self, loaded_registry):
        registry, contracts_dir = loaded_registry
        with pytest.raises(KeyError, match="nonexistent-id"):
            registry.revoke_contract("nonexistent-id", contracts_dir=contracts_dir)

    def test_revoke_missing_yaml_still_updates_memory(self, loaded_registry):
        registry, contracts_dir = loaded_registry
        # Operator manually deletes the YAML before Python revokes; in-memory
        # revocation should still apply (don't leave a half-revoked state).
        (contracts_dir / "test-subject.yaml").unlink()
        registry.revoke_contract("test-subject", contracts_dir=contracts_dir)
        assert registry.contract_check("test-subject", "audio") is False

    def test_revoke_preserves_audit_fields(self, loaded_registry):
        registry, contracts_dir = loaded_registry
        registry.revoke_contract("test-subject", contracts_dir=contracts_dir)
        c = registry.get("test-subject")
        assert c is not None
        assert c.active is False
        assert c.revoked_at is not None
        assert c.parties == ("operator", "test-subject")
        assert "audio" in c.scope

    def test_revoke_twice_on_same_day_no_collision(self, tmp_path):
        # Create two contracts with the same base ID to exercise the
        # collision-avoidance in the revoked/ filename.
        _write_contract(tmp_path, "twin")
        registry = ConsentRegistry()
        registry.load(tmp_path)
        registry.revoke_contract("twin", contracts_dir=tmp_path)

        _write_contract(tmp_path, "twin")
        registry2 = ConsentRegistry()
        registry2.load(tmp_path)
        registry2.revoke_contract("twin", contracts_dir=tmp_path)

        revoked = list((tmp_path / "revoked").iterdir())
        assert len(revoked) == 2


class TestDrillMeetsBudget:
    def test_full_drill_well_under_5_seconds(self, tmp_path):
        """§7 success criterion: full cascade < 5s end-to-end."""
        import importlib.util
        import time
        from pathlib import Path

        drill_path = (
            Path(__file__).resolve().parent.parent.parent
            / "scripts"
            / "drill-consent-revocation.py"
        )
        assert drill_path.exists(), f"drill script not found at {drill_path}"

        spec = importlib.util.spec_from_file_location("_drill", drill_path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        t = time.monotonic()
        report = mod.run_drill(tmp_path)
        wall = time.monotonic() - t

        assert report["pass"] is True, report.get("failure_reason", "no reason field")
        assert report["total_elapsed_s"] < 5.0
        assert wall < 5.0
