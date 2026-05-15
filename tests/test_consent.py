"""Tests for consent contract management (interpersonal_transparency axiom)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.governance.consent import ConsentContract, ConsentRegistry, load_contracts


class TestConsentContract(unittest.TestCase):
    def test_frozen(self):
        c = ConsentContract(id="test", parties=("operator", "alice"), scope=frozenset({"location"}))
        with self.assertRaises(AttributeError):
            c.id = "other"  # type: ignore[misc]

    def test_active_when_not_revoked(self):
        c = ConsentContract(id="test", parties=("operator", "alice"), scope=frozenset({"location"}))
        self.assertTrue(c.active)

    def test_inactive_when_revoked(self):
        c = ConsentContract(
            id="test",
            parties=("operator", "alice"),
            scope=frozenset({"location"}),
            revoked_at="2026-03-13T12:00:00",
        )
        self.assertFalse(c.active)


class TestConsentRegistryContractCheck(unittest.TestCase):
    def _registry_with_contract(self) -> ConsentRegistry:
        reg = ConsentRegistry()
        reg._contracts["c1"] = ConsentContract(
            id="c1",
            parties=("operator", "alice"),
            scope=frozenset({"coarse_location", "presence"}),
        )
        return reg

    def test_permitted_data_category(self):
        reg = self._registry_with_contract()
        self.assertTrue(reg.contract_check("alice", "coarse_location"))

    def test_unpermitted_data_category(self):
        reg = self._registry_with_contract()
        self.assertFalse(reg.contract_check("alice", "biometrics"))

    def test_unknown_person(self):
        reg = self._registry_with_contract()
        self.assertFalse(reg.contract_check("bob", "coarse_location"))

    def test_revoked_contract_blocks(self):
        reg = ConsentRegistry()
        reg._contracts["c1"] = ConsentContract(
            id="c1",
            parties=("operator", "alice"),
            scope=frozenset({"coarse_location"}),
            revoked_at="2026-03-13T12:00:00",
        )
        self.assertFalse(reg.contract_check("alice", "coarse_location"))

    def test_empty_registry_blocks(self):
        reg = ConsentRegistry()
        self.assertFalse(reg.contract_check("alice", "anything"))

    def test_operator_party_also_matches(self):
        reg = self._registry_with_contract()
        self.assertTrue(reg.contract_check("operator", "coarse_location"))


class TestConsentRegistryGetContract(unittest.TestCase):
    def test_returns_active_contract(self):
        reg = ConsentRegistry()
        reg._contracts["c1"] = ConsentContract(
            id="c1", parties=("operator", "alice"), scope=frozenset({"location"})
        )
        c = reg.get_contract_for("alice")
        self.assertIsNotNone(c)
        self.assertEqual(c.id, "c1")

    def test_returns_none_for_unknown(self):
        reg = ConsentRegistry()
        self.assertIsNone(reg.get_contract_for("bob"))

    def test_returns_none_for_revoked(self):
        reg = ConsentRegistry()
        reg._contracts["c1"] = ConsentContract(
            id="c1",
            parties=("operator", "alice"),
            scope=frozenset({"location"}),
            revoked_at="2026-03-13",
        )
        self.assertIsNone(reg.get_contract_for("alice"))


class TestConsentRegistrySubjectData(unittest.TestCase):
    def test_returns_permitted_categories(self):
        reg = ConsentRegistry()
        reg._contracts["c1"] = ConsentContract(
            id="c1",
            parties=("operator", "alice"),
            scope=frozenset({"coarse_location", "presence"}),
        )
        cats = reg.subject_data_categories("alice")
        self.assertEqual(cats, frozenset({"coarse_location", "presence"}))

    def test_empty_for_unknown(self):
        reg = ConsentRegistry()
        self.assertEqual(reg.subject_data_categories("bob"), frozenset())


class TestConsentRegistryPurge(unittest.TestCase):
    def test_purge_revokes_contract(self):
        reg = ConsentRegistry()
        reg._contracts["c1"] = ConsentContract(
            id="c1", parties=("operator", "alice"), scope=frozenset({"location"})
        )
        revoked = reg.purge_subject("alice")
        self.assertEqual(revoked, ["c1"])
        self.assertFalse(reg._contracts["c1"].active)

    def test_purge_retains_record_for_audit(self):
        reg = ConsentRegistry()
        reg._contracts["c1"] = ConsentContract(
            id="c1", parties=("operator", "alice"), scope=frozenset({"location"})
        )
        reg.purge_subject("alice")
        # Contract record still exists (for audit trail per it-audit-001)
        self.assertIn("c1", reg._contracts)
        self.assertIsNotNone(reg._contracts["c1"].revoked_at)

    def test_purge_unknown_returns_empty(self):
        reg = ConsentRegistry()
        self.assertEqual(reg.purge_subject("bob"), [])

    def test_purge_already_revoked_no_double_revoke(self):
        reg = ConsentRegistry()
        reg._contracts["c1"] = ConsentContract(
            id="c1",
            parties=("operator", "alice"),
            scope=frozenset({"location"}),
            revoked_at="2026-03-13",
        )
        revoked = reg.purge_subject("alice")
        self.assertEqual(revoked, [])


class TestConsentRegistryActiveContracts(unittest.TestCase):
    def test_lists_only_active(self):
        reg = ConsentRegistry()
        reg._contracts["c1"] = ConsentContract(
            id="c1", parties=("operator", "alice"), scope=frozenset({"location"})
        )
        reg._contracts["c2"] = ConsentContract(
            id="c2",
            parties=("operator", "bob"),
            scope=frozenset({"location"}),
            revoked_at="2026-03-13",
        )
        active = reg.active_contracts
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].id, "c1")


class TestConsentRegistryLoad(unittest.TestCase):
    def test_load_from_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_contract.yaml"
            path.write_text(
                "id: test\n"
                "parties:\n"
                "  - operator\n"
                "  - alice\n"
                "scope:\n"
                "  - coarse_location\n"
                "  - presence\n"
                "direction: one_way\n"
                "visibility_mechanism: web_dashboard\n"
                "created_at: '2026-03-13'\n"
            )
            reg = load_contracts(Path(tmpdir))
            self.assertEqual(len(reg.active_contracts), 1)
            c = reg.active_contracts[0]
            self.assertEqual(c.id, "test")
            self.assertEqual(c.parties, ("operator", "alice"))
            self.assertEqual(c.scope, frozenset({"coarse_location", "presence"}))

    def test_load_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = load_contracts(Path(tmpdir))
            self.assertEqual(len(reg.active_contracts), 0)

    def test_load_nonexistent_dir(self):
        reg = load_contracts(Path("/nonexistent/path"))
        self.assertEqual(len(reg.active_contracts), 0)

    def test_load_malformed_yaml_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.yaml"
            path.write_text("id: bad\nparties: [only_one]\n")
            reg = load_contracts(Path(tmpdir))
            self.assertEqual(len(reg.active_contracts), 0)

    def test_load_malformed_yaml_strict_raises(self):
        from shared.governance.consent import ConsentContractLoadError

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.yaml"
            path.write_text("id: bad\nparties: [only_one]\n")
            with self.assertRaises(ConsentContractLoadError):
                load_contracts(Path(tmpdir), strict=True)

    def test_load_revoked_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "revoked.yaml"
            path.write_text(
                "id: revoked\n"
                "parties:\n"
                "  - operator\n"
                "  - bob\n"
                "scope:\n"
                "  - location\n"
                "revoked_at: '2026-03-13T12:00:00'\n"
            )
            reg = load_contracts(Path(tmpdir))
            self.assertEqual(len(reg.active_contracts), 0)
            # But the record is loaded for audit
            self.assertIsNotNone(reg.get_contract_for("bob") is None)


if __name__ == "__main__":
    unittest.main()
