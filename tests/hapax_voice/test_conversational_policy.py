"""Tests for conversational policy module.

Covers: interview-derived profile injection, environmental modulation,
guest/multi-principal policy, dignity floor, and edge cases.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import patch

from agents.hapax_voice.conversational_policy import (
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
        assert "Conversational style permitted" in policy

    def test_meeting_mode_hard_constraint(self):
        """Meeting mode is a HARD CONSTRAINT — no interruptions at all."""
        env = FakeEnv(activity_mode="meeting")
        policy = get_policy(env=env)
        assert "HARD CONSTRAINT" in policy
        assert "no interruptions" in policy.lower()

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
        assert "accessible to all listeners" in policy.lower()

    def test_long_session_conciseness(self):
        env = FakeEnv()
        session_start = time.monotonic() - (25 * 60)
        policy = get_policy(env=env, session_start=session_start)
        assert "Long session" in policy
        assert "Tighten responses" in policy

    def test_late_evening_lighter_tone(self):
        env = FakeEnv()
        with patch("agents.hapax_voice.conversational_policy.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 23
            policy = get_policy(env=env)
        assert "Late hours" in policy

    def test_no_env_still_produces_policy(self):
        policy = get_policy(env=None)
        assert "Conversational Policy" in policy
        assert "Environment" not in policy


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
        from agents.hapax_voice.conversational_policy import _format_block

        assert _format_block([]) == ""

    def test_multiple_sections_joined(self):
        env = FakeEnv(activity_mode="coding")
        policy = get_policy(env=env)
        assert "Baseline:" in policy
        assert "Socrates" in policy  # operator style
        assert "Environment:" in policy
