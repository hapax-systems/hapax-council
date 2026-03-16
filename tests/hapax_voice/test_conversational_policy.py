"""Tests for conversational policy module.

Covers: profile injection, environmental modulation, guest/multi-principal
policy, dignity floor, and edge cases.
"""

from __future__ import annotations

import json
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


_SAMPLE_DIGEST = {
    "dimensions": {
        "communication_style": {
            "summary": "Terse, direct, action-oriented. Prefers concise responses.",
            "fact_count": 10,
            "avg_confidence": 0.9,
        }
    }
}


def _patch_digest(digest: dict | None = _SAMPLE_DIGEST):
    """Patch digest file reading."""
    if digest is None:
        return patch(
            "agents.hapax_voice.conversational_policy._DIGEST_PATH",
            **{"read_text.side_effect": FileNotFoundError},
        )
    content = json.dumps(digest)
    mock_path = type("P", (), {"read_text": lambda self: content})()
    return patch("agents.hapax_voice.conversational_policy._DIGEST_PATH", mock_path)


# ── Batch 1: Profile Injection ───────────────────────────────────────────────


class TestProfileInjection:
    def test_dignity_floor_always_present(self):
        with _patch_digest():
            policy = get_policy()
        assert "Conversational Policy" in policy
        assert "truthful" in policy  # Grice quality maxim

    def test_communication_style_injected(self):
        with _patch_digest():
            policy = get_policy()
        assert "Terse, direct, action-oriented" in policy

    def test_graceful_without_digest(self):
        with _patch_digest(None):
            policy = get_policy()
        # Still produces a policy (dignity floor at minimum)
        assert "Conversational Policy" in policy
        assert "truthful" in policy
        # No style injection
        assert "Terse" not in policy

    def test_empty_communication_style(self):
        digest = {"dimensions": {"communication_style": {}}}
        with _patch_digest(digest):
            policy = get_policy()
        assert "Conversational Policy" in policy
        assert "Operator style" not in policy


# ── Batch 2: Environmental Modulation ────────────────────────────────────────


class TestEnvironmentalModulation:
    def test_coding_mode_maximum_brevity(self):
        env = FakeEnv(activity_mode="coding")
        with _patch_digest():
            policy = get_policy(env=env)
        assert "Maximum brevity" in policy

    def test_idle_mode_conversational(self):
        env = FakeEnv(activity_mode="idle")
        with _patch_digest():
            policy = get_policy(env=env)
        assert "Conversational style permitted" in policy

    def test_meeting_mode_whisper(self):
        env = FakeEnv(activity_mode="meeting")
        with _patch_digest():
            policy = get_policy(env=env)
        assert "One sentence max" in policy

    def test_production_mode_minimal(self):
        env = FakeEnv(activity_mode="production")
        with _patch_digest():
            policy = get_policy(env=env)
        assert "Minimal interruption" in policy

    def test_unknown_mode_no_activity_rule(self):
        env = FakeEnv(activity_mode="unknown")
        rules = _modulate_for_environment(env)
        assert not any("brevity" in r.lower() for r in rules)

    def test_multi_face_formal_register(self):
        env = FakeEnv(face_count=2)
        with _patch_digest():
            policy = get_policy(env=env)
        assert "formal register" in policy.lower()

    def test_long_session_brevity(self):
        import time

        env = FakeEnv()
        # Simulate session started 25 minutes ago
        session_start = time.monotonic() - (25 * 60)
        with _patch_digest():
            policy = get_policy(env=env, session_start=session_start)
        assert "Long session" in policy

    def test_late_evening_lighter_tone(self):
        env = FakeEnv()
        with _patch_digest(), patch("agents.hapax_voice.conversational_policy.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 23
            policy = get_policy(env=env)
        assert "Late hours" in policy

    def test_no_env_still_produces_policy(self):
        with _patch_digest():
            policy = get_policy(env=None)
        assert "Conversational Policy" in policy
        assert "Environment" not in policy


# ── Batch 3: Guest/Multi-Principal Policy ────────────────────────────────────


class TestGuestPolicy:
    def test_guest_mode_dignity_floor_only(self):
        with _patch_digest():
            policy = get_policy(guest_mode=True)
        assert "Guest mode" in policy
        assert "Dignity floor" in policy
        # Should NOT contain operator style
        assert "Operator style" not in policy

    def test_consented_guest_moderate_formality(self):
        env = FakeEnv(consent_phase="consented", face_count=2)
        with _patch_digest():
            policy = get_policy(env=env)
        assert "consented guest" in policy
        assert "Moderate formality" in policy
        # Should still have operator style (softened)
        assert "Operator style" in policy

    def test_unconsented_guest_minimal(self):
        env = FakeEnv(consent_phase="pending_consent", face_count=2)
        with _patch_digest():
            policy = get_policy(env=env)
        assert "Dignity floor only" in policy
        # Should NOT have operator style
        assert "Operator style" not in policy

    def test_no_guest_full_profile(self):
        env = FakeEnv(consent_phase="no_guest")
        with _patch_digest():
            policy = get_policy(env=env)
        assert "Operator style" in policy
        assert "Guest" not in policy.split("## Conversational Policy")[1].split("\n\n")[0]

    def test_operator_alone_no_guest_rules(self):
        env = FakeEnv(consent_phase="no_guest", face_count=1)
        with _patch_digest():
            policy = get_policy(env=env)
        # No guest-related text in the policy
        assert "guest" not in policy.lower().replace("no_guest", "")


# ── Integration: Policy Block Format ─────────────────────────────────────────


class TestPolicyFormat:
    def test_starts_with_header(self):
        with _patch_digest():
            policy = get_policy()
        assert policy.startswith("\n\n## Conversational Policy")

    def test_empty_sections_produce_empty_string(self):
        """If _format_block gets no sections, returns empty."""
        from agents.hapax_voice.conversational_policy import _format_block

        assert _format_block([]) == ""

    def test_multiple_sections_joined(self):
        with _patch_digest():
            env = FakeEnv(activity_mode="coding")
            policy = get_policy(env=env)
        # Should have baseline, operator style, and environment
        assert "Baseline:" in policy
        assert "Operator style:" in policy
        assert "Environment:" in policy
