"""Tests for the `is_not:` anti-personification scope fields on roles.

Anti-personification linter Stage 3 (design doc
`docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md` §4,
research dossier §8.3). Every institutional and relational role in
`axioms/roles/registry.yaml` MUST declare a non-empty ``is_not:`` list —
the declarative negation surface. Structural roles may omit (species-type,
axiom-anchored, abstract).

If this file regresses, a role has lost its anti-personification scope
clause and posture/persona drift is no longer pinned down at the registry
layer. Fix the registry, not the test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REGISTRY_PATH = Path(__file__).parent.parent.parent / "axioms" / "roles" / "registry.yaml"

# Layers that MUST declare an is_not: list.
REQUIRES_IS_NOT = {"institutional", "relational"}


@pytest.fixture(scope="module")
def registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text())


class TestIsNotFields:
    def test_every_non_structural_role_has_is_not(self, registry):
        """Institutional and relational roles must all carry an ``is_not:``
        list. Regression on this test means a role has lost its anti-
        personification scope clause."""
        missing: list[str] = []
        for role in registry["roles"]:
            if role["layer"] not in REQUIRES_IS_NOT:
                continue
            if "is_not" not in role:
                missing.append(role["id"])
                continue
            value = role["is_not"]
            if not isinstance(value, list) or len(value) == 0:
                missing.append(role["id"])
        assert missing == [], (
            f"Institutional/relational roles MUST declare is_not: {missing}. "
            "See docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md §4."
        )

    def test_is_not_entries_are_non_empty_strings(self, registry):
        """Each entry in any ``is_not:`` list must be a non-empty string."""
        for role in registry["roles"]:
            entries = role.get("is_not") or []
            for entry in entries:
                assert isinstance(entry, str), (
                    f"role {role['id']} has non-string is_not entry: {entry!r}"
                )
                assert entry.strip(), f"role {role['id']} has blank is_not entry"

    def test_is_not_entries_are_kebab_case(self, registry):
        """Entries must be lowercase kebab-case — no spaces, no upper-case.
        This keeps the negation surface grep-able and prevents prose drift."""
        for role in registry["roles"]:
            for entry in role.get("is_not") or []:
                assert entry == entry.lower(), (
                    f"role {role['id']} is_not entry not lowercase: {entry!r}"
                )
                assert " " not in entry, f"role {role['id']} is_not entry contains space: {entry!r}"

    def test_is_not_entries_are_unique_within_role(self, registry):
        """A role's is_not: list should not repeat itself."""
        for role in registry["roles"]:
            entries = role.get("is_not") or []
            assert len(entries) == len(set(entries)), (
                f"role {role['id']} has duplicate is_not entries: {entries}"
            )

    def test_structural_roles_need_not_declare_is_not(self, registry):
        """Structural roles (species-type, axiom-anchored) are abstract
        architectural positions — they are NOT institutional persona-
        adjacent positions and so are not obligated to declare a negation
        surface. This test documents the exemption without forbidding it:
        a structural role MAY carry is_not:, but is not required to."""
        structural = [r for r in registry["roles"] if r["layer"] == "structural"]
        assert len(structural) >= 1, "expected at least one structural role"
        # No assertion on presence/absence of is_not: — documenting optionality.
        for role in structural:
            if "is_not" in role:
                assert isinstance(role["is_not"], list)


class TestIsNotCoverage:
    """Pin explicit coverage for the six non-structural roles so a silent
    deletion regresses loudly."""

    EXPECTED_ROLES_WITH_IS_NOT = {
        # institutional (4)
        "executive-function-assistant",
        "livestream-host",
        "research-participant",
        "household-inhabitant",
        # relational (2)
        "partner-in-conversation",
        "addressee-facing",
    }

    def test_expected_roles_all_present(self, registry):
        ids_with_is_not = {r["id"] for r in registry["roles"] if r.get("is_not")}
        missing = self.EXPECTED_ROLES_WITH_IS_NOT - ids_with_is_not
        assert not missing, (
            f"Expected roles lost is_not: {missing}. "
            "Anti-personification scope regressed — restore the is_not list "
            "or amend EXPECTED_ROLES_WITH_IS_NOT with a governance rationale."
        )
