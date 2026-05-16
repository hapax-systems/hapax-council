"""Cross-registry correspondence and receive-only boundary tests for Patreon.

Verifies that the refusal brief, surface registries, and receive-only rail
are consistent and the receive-only exception boundary is enforced.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestCrossRegistryCorrespondence:
    """Verify refusal brief and surface registries don't contradict."""

    def test_refusal_brief_contains_receive_only_exception(self):
        brief = (REPO_ROOT / "docs" / "refusal-briefs" / "leverage-patreon.md").read_text()
        assert "Receive-Only Exception" in brief

    def test_refusal_brief_still_refuses_account(self):
        brief = (REPO_ROOT / "docs" / "refusal-briefs" / "leverage-patreon.md").read_text()
        assert "REFUSED" in brief
        assert "account creation" in brief.lower()

    def test_surface_registry_has_patreon_receiver_full_auto(self):
        from agents.publication_bus.surface_registry import SURFACE_REGISTRY, AutomationStatus

        entry = SURFACE_REGISTRY.get("patreon-receiver")
        assert entry is not None, "patreon-receiver missing from surface registry"
        assert entry.automation_status == AutomationStatus.FULL_AUTO

    def test_refusal_registry_has_patreon_account(self):
        import yaml

        registry = yaml.safe_load(
            (REPO_ROOT / "docs" / "refusal-briefs" / "_registry.yaml").read_text()
        )
        assert "patreon-account" in registry["refusals"]
        entry = registry["refusals"]["patreon-account"]
        assert entry["receive_only_exception"] == "patreon-receiver"


class TestReceiveOnlyBoundary:
    """Prove the receive-only rail respects its constraints."""

    def test_no_patreon_sdk_imports(self):
        rail_path = REPO_ROOT / "shared" / "patreon_receive_only_rail.py"
        tree = ast.parse(rail_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "patreon" not in alias.name.lower(), f"SDK import: {alias.name}"
            if isinstance(node, ast.ImportFrom):
                if node.module and "patreon" in node.module.lower():
                    raise AssertionError(f"SDK import from: {node.module}")

    def test_no_outbound_http_in_rail(self):
        rail_src = (REPO_ROOT / "shared" / "patreon_receive_only_rail.py").read_text()
        for forbidden in ["requests.get", "requests.post", "httpx", "aiohttp", "urllib.request"]:
            assert forbidden not in rail_src, f"Outbound HTTP found: {forbidden}"

    def test_no_pii_fields_in_output_model(self):
        from shared.patreon_receive_only_rail import PledgeEvent

        field_names = (
            set(PledgeEvent.__dataclass_fields__.keys())
            if hasattr(PledgeEvent, "__dataclass_fields__")
            else set(PledgeEvent.model_fields.keys())
        )
        for pii in ["email", "full_name", "billing_address", "last_charge_date"]:
            assert pii not in field_names, f"PII field '{pii}' found in PledgeEvent output model"

    def test_publisher_has_no_perk_side_effects(self):
        pub_src = (REPO_ROOT / "agents" / "publication_bus" / "patreon_publisher.py").read_text()
        for forbidden in ["perk_delivery", "role_sync", "discord_role", "early_access_gate"]:
            assert forbidden not in pub_src.lower(), f"Perk-related code found: {forbidden}"
