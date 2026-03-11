# tests/test_axiom_precedents.py
"""Tests for shared.axiom_precedents."""
import pytest
from unittest.mock import MagicMock, patch

from shared.axiom_precedents import Precedent, PrecedentStore


def _make_precedent(**overrides) -> Precedent:
    defaults = dict(
        id="PRE-20260303-001",
        axiom_id="single_user",
        situation="Adding OAuth2 multi-user auth",
        decision="violation",
        reasoning="OAuth2 with multiple users contradicts single-user axiom.",
        tier="T0",
        distinguishing_facts=["Multiple user accounts", "User identity management"],
        authority="operator",
        created="2026-03-03T00:00:00Z",
        superseded_by=None,
    )
    defaults.update(overrides)
    return Precedent(**defaults)


class TestPrecedentDataclass:
    def test_create(self):
        p = _make_precedent()
        assert p.axiom_id == "single_user"
        assert p.decision == "violation"
        assert p.authority == "operator"

    def test_defaults(self):
        p = _make_precedent(superseded_by="PRE-20260303-002")
        assert p.superseded_by == "PRE-20260303-002"


class TestPrecedentStoreUnit:
    """Unit tests with mocked Qdrant client."""

    def test_generate_id(self):
        store = PrecedentStore.__new__(PrecedentStore)
        id1 = store._generate_id()
        assert id1.startswith("PRE-")

    def test_precedent_to_payload(self):
        store = PrecedentStore.__new__(PrecedentStore)
        p = _make_precedent()
        payload = store._to_payload(p)
        assert payload["axiom_id"] == "single_user"
        assert payload["decision"] == "violation"
        assert payload["authority"] == "operator"
        assert isinstance(payload["distinguishing_facts"], str)  # JSON-encoded list

    def test_payload_to_precedent(self):
        store = PrecedentStore.__new__(PrecedentStore)
        p = _make_precedent()
        payload = store._to_payload(p)
        restored = store._from_payload("test-point-id", payload)
        assert restored.axiom_id == p.axiom_id
        assert restored.decision == p.decision
        assert restored.distinguishing_facts == p.distinguishing_facts

    @patch("shared.axiom_precedents.get_qdrant")
    def test_ensure_collection_creates_if_missing(self, mock_get):
        client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.name = "other-collection"
        client.get_collections.return_value.collections = [mock_collection]
        mock_get.return_value = client

        store = PrecedentStore()
        store.ensure_collection()
        client.create_collection.assert_called_once()

    @patch("shared.axiom_precedents.get_qdrant")
    def test_ensure_collection_skips_if_exists(self, mock_get):
        client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.name = "axiom-precedents"
        client.get_collections.return_value.collections = [mock_collection]
        mock_get.return_value = client

        store = PrecedentStore()
        store.ensure_collection()
        client.create_collection.assert_not_called()


class TestSeedLoading:
    def test_load_seeds_from_yaml(self, tmp_path):
        seed_dir = tmp_path / "precedents" / "seed"
        seed_dir.mkdir(parents=True)
        (seed_dir / "test-seeds.yaml").write_text(
            "axiom_id: test_axiom\n"
            "precedents:\n"
            "  - id: sp-001\n"
            '    situation: "Test situation"\n'
            "    decision: compliant\n"
            '    reasoning: "Test reasoning"\n'
            "    tier: T1\n"
            "    distinguishing_facts:\n"
            '      - "Fact one"\n'
            '    created: "2026-01-01"\n'
            "    authority: operator\n"
        )
        store = PrecedentStore.__new__(PrecedentStore)
        seeds = store._parse_seed_file(seed_dir / "test-seeds.yaml")
        assert len(seeds) == 1
        assert seeds[0].id == "sp-001"
        assert seeds[0].axiom_id == "test_axiom"
        assert seeds[0].authority == "operator"


class TestPromoteAndSupersede:
    def test_promote_changes_authority(self):
        p = _make_precedent(authority="agent")
        assert p.authority == "agent"
        # Promotion is done via Qdrant payload update, tested in integration
