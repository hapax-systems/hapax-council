"""Tests for conversational policy module.

Covers: interview-derived profile injection, environmental modulation,
guest/multi-principal policy, dignity floor, and edge cases.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import patch

from agents.hapax_daimonion.conversational_policy import (
    _modulate_for_environment,
    get_policy,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FakeEnv:
    """Minimal EnvironmentState stand-in for policy tests."""

    timestamp: float = 0.0
    activity_mode: str = "unknown"
    face_count: int = 0
    operator_present: bool = True
    consent_phase: str = "no_guest"


# ── Operator Style (interview-derived) ───────────────────────────────────────


class TestOperatorStyle:
    def test_dignity_floor_always_present(self):
        policy = get_policy()
        assert "Conversational Policy" in policy
        assert "truthful" in policy  # Grice quality maxim

    def test_interview_personality_archetype(self):
        policy = get_policy()
        assert "Socrates" in policy
        assert "Hodgman" in policy
        assert "Sean Carroll" in policy

    def test_dysfluency_guidance(self):
        """Critical ADHD accommodation: never interrupt pauses."""
        policy = get_policy()
        assert "NEVER interrupt" in policy
        assert "dysfluencies" in policy

    def test_no_false_esteem(self):
        policy = get_policy()
        assert "No false esteem" in policy
        assert "blind praise" in policy

    def test_proactivity_directives(self):
        policy = get_policy()
        assert "open loops" in policy
        assert "Context restoration" in policy

    def test_productive_intensity_not_pathologized(self):
        policy = get_policy()
        assert "DO NOT pathologize" in policy
        assert "angular double-edged behaviors" in policy

    def test_low_attack_interruptions(self):
        policy = get_policy()
        assert "low-attack" in policy

    def test_epistemic_honesty(self):
        policy = get_policy()
        assert "Epistemic honesty" in policy

    def test_no_empty_rhetoric(self):
        policy = get_policy()
        assert "No empty rhetoric" in policy


# ── Environmental Modulation ────────────────────────────────────────────────


class TestEnvironmentalModulation:
    def test_coding_mode_maximum_brevity(self):
        env = FakeEnv(activity_mode="coding")
        policy = get_policy(env=env)
        assert "Maximum brevity" in policy

    def test_idle_mode_conversational(self):
        env = FakeEnv(activity_mode="idle")
        policy = get_policy(env=env)
        assert "Conversational" in policy

    def test_meeting_mode_silent(self):
        """Meeting mode: SILENT unless wake-word addressed."""
        env = FakeEnv(activity_mode="meeting")
        policy = get_policy(env=env)
        assert "SILENT" in policy
        assert "HARD CONSTRAINT" in policy
        assert "Zero interruptions" in policy

    def test_production_mode_minimal(self):
        env = FakeEnv(activity_mode="production")
        policy = get_policy(env=env)
        assert "Minimal interruption" in policy

    def test_unknown_mode_no_activity_rule(self):
        env = FakeEnv(activity_mode="unknown")
        rules = _modulate_for_environment(env)
        assert not any("brevity" in r.lower() for r in rules)

    def test_multi_face_accessible(self):
        env = FakeEnv(face_count=2)
        policy = get_policy(env=env)
        assert "Guest present" in policy

    def test_long_session_conciseness(self):
        env = FakeEnv()
        session_start = time.monotonic() - (25 * 60)
        policy = get_policy(env=env, session_start=session_start)
        assert "Long session" in policy
        assert "Extra concise" in policy

    def test_late_evening_lighter_tone(self):
        env = FakeEnv()
        with patch("agents.hapax_daimonion.conversational_policy.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 23
            policy = get_policy(env=env)
        assert "Late hours" in policy

    def test_no_env_still_produces_policy(self):
        policy = get_policy(env=None)
        assert "Conversational Policy" in policy
        assert "Environment" not in policy


# ── Compressed Modulation Directives ────────────────────────────────────────


class TestCompressedModulation:
    def test_coding_mode_is_terse(self):
        env = FakeEnv(activity_mode="coding", face_count=1)
        rules = _modulate_for_environment(env)
        activity_rules = [r for r in rules if "coding" in r.lower()]
        assert len(activity_rules) == 1
        assert len(activity_rules[0]) < 80  # Compressed

    def test_meeting_mode_is_terse(self):
        env = FakeEnv(activity_mode="meeting", face_count=1)
        rules = _modulate_for_environment(env)
        activity_rules = [r for r in rules if "meeting" in r.lower()]
        assert len(activity_rules) == 1
        assert len(activity_rules[0]) < 85  # 80 chars with HARD CONSTRAINT prefix


# ── Guest/Multi-Principal Policy ────────────────────────────────────────────


class TestGuestPolicy:
    def test_guest_mode_dignity_floor_only(self):
        policy = get_policy(guest_mode=True)
        assert "Guest mode" in policy
        assert "Dignity floor" in policy
        # Should NOT contain operator style
        assert "Socrates" not in policy

    def test_consented_guest_moderate_formality(self):
        env = FakeEnv(consent_phase="consented", face_count=2)
        policy = get_policy(env=env)
        assert "consented guest" in policy
        assert "Moderate formality" in policy
        # Should still have operator style
        assert "Socrates" in policy

    def test_consented_guest_not_creepy(self):
        """Interview: 'be friendly but not creepy about the setup.'"""
        env = FakeEnv(consent_phase="consented", face_count=2)
        policy = get_policy(env=env)
        assert "not creepy" in policy.lower()

    def test_unconsented_guest_minimal(self):
        env = FakeEnv(consent_phase="pending_consent", face_count=2)
        policy = get_policy(env=env)
        assert "Dignity floor only" in policy
        # Should NOT have operator style
        assert "Socrates" not in policy

    def test_no_guest_full_profile(self):
        env = FakeEnv(consent_phase="no_guest")
        policy = get_policy(env=env)
        assert "Socrates" in policy  # full operator style present

    def test_operator_alone_no_guest_rules(self):
        env = FakeEnv(consent_phase="no_guest", face_count=1)
        policy = get_policy(env=env)
        # No guest-specific policy text (but "guest" may appear in operator style
        # e.g. "not creepy" — so we check for the specific guest policy markers)
        assert "Dignity floor only" not in policy
        assert "Guest mode" not in policy
        assert "consented guest" not in policy


# ── Integration: Policy Block Format ─────────────────────────────────────────


class TestPolicyFormat:
    def test_starts_with_header(self):
        policy = get_policy()
        assert policy.startswith("\n\n## Conversational Policy")

    def test_empty_sections_produce_empty_string(self):
        from agents.hapax_daimonion.conversational_policy import _format_block

        assert _format_block([]) == ""

    def test_multiple_sections_joined(self):
        env = FakeEnv(activity_mode="coding")
        policy = get_policy(env=env)
        assert "Baseline:" in policy
        assert "Socrates" in policy  # operator style
        assert "Environment:" in policy


# ── Child Interaction Policy ─────────────────────────────────────────────────


class TestChildPolicy:
    def test_child_mode_activates_child_style(self):
        """Child mode produces child-specific interaction guidance."""
        policy = get_policy(guest_mode=True, child_mode=True)
        assert "sovereign principals" in policy.lower()
        assert "intelligent humans" in policy.lower()

    def test_child_mode_respects_intelligence(self):
        """Child policy never talks down."""
        policy = get_policy(guest_mode=True, child_mode=True)
        assert "Never talk down" in policy
        assert "Respect their intelligence" in policy

    def test_child_mode_allows_productive_confusion(self):
        """Confusion is a pedagogical tool, not a failure state."""
        policy = get_policy(guest_mode=True, child_mode=True)
        assert "confuse them purposefully" in policy.lower()

    def test_child_mode_no_personal_data(self):
        """Children should not see personal data or system internals."""
        policy = get_policy(guest_mode=True, child_mode=True)
        assert "personal data" in policy.lower()

    def test_child_mode_has_dignity_floor(self):
        """Dignity floor still applies to children."""
        policy = get_policy(guest_mode=True, child_mode=True)
        assert "truthful" in policy

    def test_child_mode_no_operator_style(self):
        """Child mode should not include operator-specific style."""
        policy = get_policy(guest_mode=True, child_mode=True)
        assert "Socrates" not in policy

    def test_non_child_guest_mode_unchanged(self):
        """Regular guest mode (not child) still works as before."""
        policy = get_policy(guest_mode=True, child_mode=False)
        assert "Guest mode" in policy
        assert "sovereign principals" not in policy.lower()


# ── Registered Child Principals (Consent) ────────────────────────────────────


class TestChildConsent:
    def test_registered_children(self):
        """Simon and Agatha are registered child principals."""
        from shared.governance.consent import REGISTERED_CHILD_PRINCIPALS

        assert "simon" in REGISTERED_CHILD_PRINCIPALS
        assert "agatha" in REGISTERED_CHILD_PRINCIPALS

    def test_only_two_registered(self):
        """No other children should be registered."""
        from shared.governance.consent import REGISTERED_CHILD_PRINCIPALS

        assert len(REGISTERED_CHILD_PRINCIPALS) == 2

    def test_contracts_exist_on_disk(self):
        """Consent contracts for Simon and Agatha exist as YAML files."""
        from pathlib import Path

        contracts_dir = Path("axioms/contracts")
        assert (contracts_dir / "contract-simon.yaml").exists()
        assert (contracts_dir / "contract-agatha.yaml").exists()

    def test_contracts_loadable(self):
        """Contracts can be loaded by the ConsentRegistry."""
        from shared.governance.consent import load_contracts

        registry = load_contracts()
        simon = registry.get_contract_for("simon")
        agatha = registry.get_contract_for("agatha")
        assert simon is not None
        assert agatha is not None
        assert simon.active
        assert agatha.active

    def test_children_have_full_perception_scope(self):
        """Children have audio, presence, transcription, video scope."""
        from shared.governance.consent import load_contracts

        registry = load_contracts()
        simon = registry.get_contract_for("simon")
        assert simon is not None
        assert "audio" in simon.scope
        assert "presence" in simon.scope
        assert "transcription" in simon.scope
        assert "video" in simon.scope
