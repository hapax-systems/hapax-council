"""Schema validation for the sister epic config scaffolding files.

Pins the structure of config/sister-epic/*.yaml so an operator edit
can't accidentally drop a required key. The test asserts the schema
shape — NOT the values, which are operator-owned.

Sister-epic-scaffold-refusal-reconcile (cc-task closed 2026-05-01) added
the ``TestRefusalSupersession`` class below: assertion-level guards that
prevent the patreon-tiers + discord-channels scaffolds from regressing
out of ``superseded_refusal`` state, plus a positive pin that the
visual-signature scaffold remains active (per task acceptance criterion
"Preserve any non-conflicting visual/signature work only if still useful").
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SISTER_EPIC_DIR = REPO_ROOT / "config" / "sister-epic"
EXPECTED_SUPERSEDED_BY = "config/support-surface-registry.json"


def _load(name: str) -> dict:
    return yaml.safe_load((SISTER_EPIC_DIR / name).read_text(encoding="utf-8"))


class TestDiscordChannels:
    def test_file_exists(self) -> None:
        assert (SISTER_EPIC_DIR / "discord-channels.yaml").is_file()

    def test_schema_top_level(self) -> None:
        d = _load("discord-channels.yaml")
        assert d["version"] == 1
        assert d["schema_owner"] == "operator"
        assert d["operator_action_required"] is False
        assert d["status"] == "superseded_refusal"
        assert d["activation_allowed"] is False
        assert d["superseded_by"] == "config/support-surface-registry.json"
        assert "server" in d
        assert "categories" in d
        assert "moderation" in d

    def test_community_channels_are_superseded(self) -> None:
        d = _load("discord-channels.yaml")
        assert isinstance(d["categories"], list)
        assert d["categories"] == []
        assert d["server"]["activation_allowed"] is False
        assert d["server"]["allowed_use"] == "none_for_support"

    def test_moderation_surface_is_refused(self) -> None:
        d = _load("discord-channels.yaml")
        mod = d["moderation"]
        assert mod["enabled"] is False
        assert mod["operator_action_required"] is False
        assert "multi-user support surface" in mod["reason"]

    def test_publication_bus_boundary_is_not_support_surface(self) -> None:
        d = _load("discord-channels.yaml")
        boundary = d["publication_bus_boundary"]
        assert boundary["support_surface_allowed"] is False
        assert boundary["one_way_publication_bus_may_be_evaluated_elsewhere"] is True
        assert boundary["required_contract"].endswith("cross-surface-event-contract-design.md")


class TestPatreonTiers:
    def test_file_exists(self) -> None:
        assert (SISTER_EPIC_DIR / "patreon-tiers.yaml").is_file()

    def test_tiers_are_superseded_refusal(self) -> None:
        d = _load("patreon-tiers.yaml")
        assert d["operator_action_required"] is False
        assert d["status"] == "superseded_refusal"
        assert d["activation_allowed"] is False
        assert d["superseded_by"] == "config/support-surface-registry.json"
        assert d["tiers"] == []

    def test_replacement_surfaces_are_no_perk_support_rails(self) -> None:
        d = _load("patreon-tiers.yaml")
        assert d["replacement_surface_ids"] == [
            "liberapay_recurring",
            "lightning_invoice_receive",
            "nostr_zaps",
        ]

    def test_constraint_flags_refuse_perk_ladder(self) -> None:
        d = _load("patreon-tiers.yaml")
        constraints = d["constraints"]
        assert constraints["no_patreon_account"] is True
        assert constraints["no_tiers"] is True
        assert constraints["no_perks"] is True
        assert constraints["no_role_sync"] is True
        assert constraints["no_private_posts"] is True
        assert constraints["no_name_acknowledgments"] is True
        assert constraints["no_leaderboards"] is True
        assert constraints["no_supporter_identity_public_state"] is True
        assert constraints["work_continues_regardless"] is True


class TestVisualSignature:
    def test_file_exists(self) -> None:
        assert (SISTER_EPIC_DIR / "visual-signature.yaml").is_file()

    def test_top_level_schema(self) -> None:
        d = _load("visual-signature.yaml")
        assert d["version"] == 1
        assert d["schema_owner"] == "operator"
        assert "fonts" in d
        assert "palettes" in d
        assert "visual_constants" in d
        assert "logo" in d
        assert "usage_rules" in d

    def test_palette_has_both_modes(self) -> None:
        """Research (Solarized) + R&D (Gruvbox) palettes are both required."""
        d = _load("visual-signature.yaml")
        assert "research" in d["palettes"]
        assert "rnd" in d["palettes"]

    def test_visual_constants_inherit_council(self) -> None:
        """Sierpinski, token_pole, reverie are the three council-canonical constants."""
        d = _load("visual-signature.yaml")
        vc = d["visual_constants"]
        for key in ("sierpinski_triangle", "token_pole", "reverie"):
            assert key in vc
            assert vc[key]["enabled"] is True

    def test_usage_rules_include_contrast(self) -> None:
        d = _load("visual-signature.yaml")
        rules = d["usage_rules"]
        assert rules["min_contrast_ratio"] >= 4.5  # WCAG AA minimum

    def test_dont_recolor_visual_constants_rule(self) -> None:
        d = _load("visual-signature.yaml")
        assert d["usage_rules"]["do_not_recolor_visual_constants"] is True


class TestRefusalSupersession:
    """Lock the sister-epic refused-scaffold reconciliation in.

    The patreon-tiers + discord-channels scaffolds were originally written
    as if they would activate. Operator later refused both Patreon and the
    Discord community surface (`leverage-REFUSED-patreon-sponsorship` +
    `leverage-REFUSED-discord-community`). The configs were kept as
    ``superseded_refusal`` artifacts pointing at the support-surface
    registry. These pins prevent accidental regression: re-activation must
    be a deliberate axiom-level decision, not a one-line yaml edit that
    silently flips ``activation_allowed`` back to true.
    """

    REFUSED_SCAFFOLDS = ("patreon-tiers.yaml", "discord-channels.yaml")

    def test_refused_scaffolds_are_marked_superseded_refusal(self) -> None:
        for name in self.REFUSED_SCAFFOLDS:
            d = _load(name)
            assert d["status"] == "superseded_refusal", (
                f"{name} status drifted from superseded_refusal to {d['status']!r}; "
                "re-activation requires the corresponding refusal-brief to be "
                "withdrawn first"
            )
            assert d["activation_allowed"] is False, (
                f"{name} activation_allowed flipped to True; the surface is REFUSED"
            )
            assert d["operator_action_required"] is False, (
                f"{name} operator_action_required flipped to True; refused scaffolds "
                "must not pull operator attention"
            )

    def test_refused_scaffolds_point_at_canonical_successor(self) -> None:
        for name in self.REFUSED_SCAFFOLDS:
            d = _load(name)
            assert d["superseded_by"] == EXPECTED_SUPERSEDED_BY, (
                f"{name} superseded_by drifted to {d['superseded_by']!r}; the "
                "canonical successor is the support-surface registry"
            )
            successor_path = REPO_ROOT / EXPECTED_SUPERSEDED_BY
            assert successor_path.is_file(), (
                f"{name} points at {EXPECTED_SUPERSEDED_BY} but that file is missing; "
                "the supersession reference is dangling"
            )

    def test_refused_scaffolds_have_resolvable_refusal_refs(self) -> None:
        """Every refusal_ref must resolve to an actual file on disk."""
        for name in self.REFUSED_SCAFFOLDS:
            d = _load(name)
            refusal_refs = d.get("refusal_refs", [])
            assert refusal_refs, f"{name} has no refusal_refs to back the supersession"
            for ref in refusal_refs:
                ref_path = REPO_ROOT / ref
                assert ref_path.is_file(), (
                    f"{name} refusal_ref {ref!r} does not resolve to a file; "
                    "either the brief was moved/deleted or the ref is mistyped"
                )

    def test_visual_signature_is_NOT_superseded(self) -> None:
        """Visual signature is preserved per the reconcile cc-task: it is a
        non-conflicting useful scaffold (operator visual identity for sister-epic
        artifacts) that survives the Patreon/Discord refusal."""
        d = _load("visual-signature.yaml")
        assert d.get("status") != "superseded_refusal", (
            "visual-signature.yaml must NOT be marked superseded_refusal — it is "
            "a preserved scaffold for the operator's sister-epic visual identity, "
            "non-conflicting with the Patreon/Discord refusals"
        )
        assert d["operator_action_required"] is True, (
            "visual-signature.yaml is operator-fillable scaffolding; the "
            "operator_action_required flag signals the TODOs are awaiting the "
            "operator's value choices, not a defect"
        )
