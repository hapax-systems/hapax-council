"""Regression test: lapsed Patreon patron cannot receive gated access.

Guards against future code that might read PledgeEvent.patron_status to
grant access. The constitutional refusal policy (leverage-patreon.md)
prohibits access control based on Patreon membership state.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

AUTHORIZATION_MODULES = [
    "shared/governance",
    "agents/publication_bus/surface_registry.py",
    "agents/hapax_daimonion/engine_gate.py",
    "agents/hapax_daimonion/voice_path.py",
    "logos/api/routes",
]

FORBIDDEN_PATTERNS_IN_AUTH = [
    "patron_status",
    "active_patron",
    "is_patron",
    "patreon_tier",
    "pledge_active",
    "entitled_amount",
]


class TestLapsedPatronNoAccess:
    """A user whose Patreon state is 'lapsed' cannot receive access."""

    def test_pledge_event_has_no_access_grant_fields(self):
        from shared.patreon_receive_only_rail import PledgeEvent

        field_names = set(PledgeEvent.model_fields.keys())
        access_fields = {
            "access_token",
            "tier_id",
            "perk_entitlements",
            "role_grants",
            "access_level",
        }
        intersection = field_names & access_fields
        assert not intersection, f"PledgeEvent has access-granting fields: {intersection}"

    def test_no_patron_status_in_authorization_modules(self):
        for mod_path in AUTHORIZATION_MODULES:
            full = REPO_ROOT / mod_path
            if full.is_file():
                sources = [full]
            elif full.is_dir():
                sources = list(full.rglob("*.py"))
            else:
                continue
            for src in sources:
                content = src.read_text()
                for pattern in FORBIDDEN_PATTERNS_IN_AUTH:
                    assert pattern not in content, (
                        f"Authorization module {src.relative_to(REPO_ROOT)} "
                        f"contains '{pattern}' — refusal policy prohibits "
                        f"access control based on Patreon membership state"
                    )

    def test_no_pledge_event_import_in_auth_modules(self):
        for mod_path in AUTHORIZATION_MODULES:
            full = REPO_ROOT / mod_path
            if full.is_file():
                sources = [full]
            elif full.is_dir():
                sources = list(full.rglob("*.py"))
            else:
                continue
            for src in sources:
                tree = ast.parse(src.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        if node.module and "patreon" in node.module:
                            for alias in node.names:
                                assert alias.name != "PledgeEvent", (
                                    f"{src.relative_to(REPO_ROOT)} imports PledgeEvent — "
                                    f"refusal policy prohibits access gating on Patreon state"
                                )

    def test_refusal_policy_still_refuses(self):
        brief = (REPO_ROOT / "docs" / "refusal-briefs" / "leverage-patreon.md").read_text()
        assert "REFUSED" in brief
        assert "NO supporter obligations, perks, tiers, or access control" in brief

    def test_receive_only_rail_has_no_access_grant_logic(self):
        rail_src = (REPO_ROOT / "shared" / "patreon_receive_only_rail.py").read_text()
        for pattern in ["grant_access", "authorize_patron", "unlock_feature", "access_level"]:
            assert pattern not in rail_src, (
                f"Receive-only rail contains '{pattern}' — violates receive-only invariant"
            )
