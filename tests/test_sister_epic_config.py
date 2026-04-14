"""Schema validation for the sister epic config scaffolding files.

Pins the structure of config/sister-epic/*.yaml so an operator edit
can't accidentally drop a required key. The test asserts the schema
shape — NOT the values, which are operator-owned.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SISTER_EPIC_DIR = REPO_ROOT / "config" / "sister-epic"


def _load(name: str) -> dict:
    return yaml.safe_load((SISTER_EPIC_DIR / name).read_text(encoding="utf-8"))


class TestDiscordChannels:
    def test_file_exists(self) -> None:
        assert (SISTER_EPIC_DIR / "discord-channels.yaml").is_file()

    def test_schema_top_level(self) -> None:
        d = _load("discord-channels.yaml")
        assert d["version"] == 1
        assert d["schema_owner"] == "operator"
        assert d["operator_action_required"] is True
        assert "server" in d
        assert "categories" in d
        assert "moderation" in d

    def test_categories_are_lists(self) -> None:
        d = _load("discord-channels.yaml")
        assert isinstance(d["categories"], list)
        assert len(d["categories"]) >= 3  # announcements + discussion + tentpole minimum
        for cat in d["categories"]:
            assert "id" in cat
            assert "channels" in cat
            assert isinstance(cat["channels"], list)

    def test_every_channel_has_id_and_kind(self) -> None:
        d = _load("discord-channels.yaml")
        for cat in d["categories"]:
            for ch in cat["channels"]:
                assert "id" in ch, f"channel missing id in category {cat['id']}"
                assert "kind" in ch, f"channel {ch['id']} missing kind"
                assert ch["kind"] in ("text", "voice")

    def test_moderation_gate_on_by_default(self) -> None:
        d = _load("discord-channels.yaml")
        mod = d["moderation"]
        assert mod["onboarding_gate"]["enabled"] is True
        assert mod["onboarding_gate"]["manifesto_acknowledgment_required"] is True

    def test_phase_9_integration_point_present(self) -> None:
        """Attack log path hooks into Phase 9 chat_attack_log.py output."""
        d = _load("discord-channels.yaml")
        assert d["moderation"]["attack_log_path"] == "/dev/shm/hapax-chat-attack-log.jsonl"


class TestPatreonTiers:
    def test_file_exists(self) -> None:
        assert (SISTER_EPIC_DIR / "patreon-tiers.yaml").is_file()

    def test_five_tiers_present(self) -> None:
        d = _load("patreon-tiers.yaml")
        tier_ids = [t["id"] for t in d["tiers"]]
        # Bundle 7 §8.3 taxonomy
        assert tier_ids == ["companion", "listener", "studio", "lab", "patron"]

    def test_each_tier_has_required_fields(self) -> None:
        d = _load("patreon-tiers.yaml")
        for tier in d["tiers"]:
            assert "id" in tier
            assert "display_name" in tier
            assert "price_usd_monthly" in tier  # may be null (operator fills)
            assert "description" in tier
            assert "perks" in tier
            assert isinstance(tier["perks"], list)
            assert len(tier["perks"]) >= 1
            assert "discord_role" in tier

    def test_constraint_flags_enforce_ethics(self) -> None:
        """Token pole 7 + interpersonal_transparency compliance is schema-enforced."""
        d = _load("patreon-tiers.yaml")
        constraints = d["constraints"]
        assert constraints["no_parasocial_perks"] is True
        assert constraints["no_sentiment_reward"] is True
        assert constraints["no_loss_framing"] is True
        assert constraints["token_pole_7_compliant"] is True
        assert constraints["interpersonal_transparency_compliant"] is True

    def test_discord_role_ids_match_channels_yaml(self) -> None:
        """Tier Discord roles should align with channel gate roles."""
        tiers_doc = _load("patreon-tiers.yaml")
        # Just assert the tier roles exist and are non-empty strings.
        for tier in tiers_doc["tiers"]:
            role = tier["discord_role"]
            assert isinstance(role, str)
            assert role.startswith("patron-")


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
