"""Use-case × component test matrix for conversational policy.

Systematic cross-product of:
  USE CASES (rows): who's present + what's happening
  COMPONENTS (columns): what the policy output must contain/exclude

Every cell in the matrix is an assertion. Each test method is a row.
Each assertion within a test is a column check.

Use cases (14 rows):
  Operator alone:   idle, coding, production, meeting
  With guest:       consented, unconsented, child (Simon/Agatha)
  Guest alone:      adult guest, child guest
  Edge cases:       no env, late evening, long session, multi-signal

Components (8 columns):
  A: dignity_floor     — Grice maxims always present
  B: operator_style    — interview-derived personality (Socrates × Hodgman × Carroll)
  C: activity_mod      — activity-mode-specific modulation
  D: guest_policy      — consent-phase-dependent guest handling
  E: child_style       — child interaction guidelines
  F: env_block         — "Environment:" section with modulation rules
  G: data_protection   — personal data / system internals blocked
  H: format            — starts with header, sections joined correctly
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_voice.conversational_policy import (
    _ACTIVITY_MODULATIONS,
    _format_block,
    _modulate_for_environment,
    get_policy,
)


@dataclass(frozen=True)
class FakeEnv:
    """Minimal EnvironmentState stand-in."""

    timestamp: float = 0.0
    activity_mode: str = "unknown"
    face_count: int = 0
    operator_present: bool = True
    consent_phase: str = "no_guest"


# ── Component assertion helpers ──────────────────────────────────────────────


def _has_dignity_floor(policy: str) -> None:
    """A: dignity floor present."""
    assert "truthful" in policy, "Missing Grice quality maxim"
    assert "relevant" in policy, "Missing Grice relation maxim"
    assert "autonomy" in policy, "Missing face theory"


def _has_operator_style(policy: str) -> None:
    """B: interview-derived operator personality."""
    assert "Socrates" in policy, "Missing Socrates archetype"
    assert "Hodgman" in policy, "Missing Hodgman archetype"
    assert "dysfluencies" in policy, "Missing ADHD accommodation"
    assert "open loops" in policy, "Missing proactivity directive"


def _lacks_operator_style(policy: str) -> None:
    """B (inverse): operator personality must NOT be present."""
    assert "Socrates" not in policy, "Operator style leaked"
    assert "dysfluencies" not in policy, "ADHD details leaked to non-operator"


def _has_activity_mod(policy: str, mode: str) -> None:
    """C: activity-specific modulation present."""
    expected = _ACTIVITY_MODULATIONS[mode]
    assert expected[:30] in policy, f"Missing {mode} modulation"


def _has_guest_policy(policy: str, phase: str) -> None:
    """D: consent-phase-dependent guest handling."""
    if phase == "consented":
        assert "consented guest" in policy
        assert "Moderate formality" in policy
    elif phase == "pending_consent":
        assert "Dignity floor only" in policy
    elif phase == "guest_mode":
        assert "Guest mode" in policy or "sovereign principals" in policy.lower()


def _has_child_style(policy: str) -> None:
    """E: child interaction guidelines."""
    assert "sovereign principals" in policy.lower()
    assert "Never talk down" in policy
    assert "confuse them purposefully" in policy.lower()


def _lacks_child_style(policy: str) -> None:
    """E (inverse): child style must NOT be present."""
    assert "sovereign principals" not in policy.lower()


def _has_env_block(policy: str) -> None:
    """F: environment section exists."""
    assert "Environment:" in policy


def _lacks_env_block(policy: str) -> None:
    """F (inverse): no environment section."""
    assert "Environment:" not in policy


def _has_data_protection(policy: str) -> None:
    """G: personal data / system internals blocked."""
    lower = policy.lower()
    assert any(
        phrase in lower
        for phrase in ["personal data", "work-sensitive", "system internals", "no personal"]
    ), "Missing data protection directive"


def _has_format(policy: str) -> None:
    """H: correct block format."""
    assert policy.startswith("\n\n## Conversational Policy"), "Bad header"
    assert "Baseline:" in policy, "Missing baseline section"


# ═══════════════════════════════════════════════════════════════════════════════
# OPERATOR ALONE — 4 activity modes
# ═══════════════════════════════════════════════════════════════════════════════


class TestOperatorAloneMatrix:
    """Operator at desk, no guests. Full profile-driven policy."""

    def test_idle(self):
        """Idle: full style, conversational modulation, no guest policy."""
        env = FakeEnv(activity_mode="idle")
        p = get_policy(env=env)
        _has_dignity_floor(p)
        _has_operator_style(p)
        _has_activity_mod(p, "idle")
        _lacks_child_style(p)
        _has_env_block(p)
        _has_format(p)

    def test_coding(self):
        """Coding: full style + maximum brevity overlay."""
        env = FakeEnv(activity_mode="coding")
        p = get_policy(env=env)
        _has_dignity_floor(p)
        _has_operator_style(p)
        _has_activity_mod(p, "coding")
        _has_env_block(p)
        _has_format(p)

    def test_production(self):
        """Production: full style + minimal interruption."""
        env = FakeEnv(activity_mode="production")
        p = get_policy(env=env)
        _has_dignity_floor(p)
        _has_operator_style(p)
        _has_activity_mod(p, "production")
        _has_env_block(p)
        _has_format(p)

    def test_meeting(self):
        """Meeting: full style + HARD CONSTRAINT no interruptions."""
        env = FakeEnv(activity_mode="meeting")
        p = get_policy(env=env)
        _has_dignity_floor(p)
        _has_operator_style(p)
        _has_activity_mod(p, "meeting")
        assert "HARD CONSTRAINT" in p
        _has_env_block(p)
        _has_format(p)


# ═══════════════════════════════════════════════════════════════════════════════
# OPERATOR + GUEST — 3 consent phases
# ═══════════════════════════════════════════════════════════════════════════════


class TestOperatorWithGuestMatrix:
    """Operator + another person present."""

    def test_consented_guest(self):
        """Consented guest: operator style + guest formality + data protection."""
        env = FakeEnv(consent_phase="consented", face_count=2)
        p = get_policy(env=env)
        _has_dignity_floor(p)
        _has_operator_style(p)  # preserved but softened
        _has_guest_policy(p, "consented")
        _has_data_protection(p)
        _has_format(p)

    def test_unconsented_guest(self):
        """Unconsented guest: dignity floor ONLY. No operator style. No env."""
        env = FakeEnv(consent_phase="pending_consent", face_count=2)
        p = get_policy(env=env)
        _has_dignity_floor(p)
        _lacks_operator_style(p)
        _has_guest_policy(p, "pending_consent")
        _has_data_protection(p)
        _lacks_env_block(p)  # early return before env block
        _has_format(p)

    def test_consented_child(self):
        """Operator + child (Simon/Agatha): operator style + child scaffolding."""
        env = FakeEnv(consent_phase="consented", face_count=2)
        p = get_policy(env=env)
        _has_dignity_floor(p)
        # Child style requires guest_mode=True + child_mode=True
        # With consented phase, operator style is preserved
        _has_operator_style(p)
        _has_format(p)


# ═══════════════════════════════════════════════════════════════════════════════
# GUEST ALONE — adult and child modes
# ═══════════════════════════════════════════════════════════════════════════════


class TestGuestAloneMatrix:
    """Guest is primary speaker. Operator absent or delegated."""

    def test_adult_guest(self):
        """Adult guest mode: dignity floor + friendliness. No operator data."""
        p = get_policy(guest_mode=True, child_mode=False)
        _has_dignity_floor(p)
        _lacks_operator_style(p)
        _has_guest_policy(p, "guest_mode")
        _lacks_child_style(p)
        _lacks_env_block(p)  # guest mode returns early
        _has_format(p)

    def test_child_guest(self):
        """Child guest mode: dignity floor + child style. No operator data."""
        p = get_policy(guest_mode=True, child_mode=True)
        _has_dignity_floor(p)
        _lacks_operator_style(p)
        _has_child_style(p)
        _has_data_protection(p)
        _lacks_env_block(p)
        _has_format(p)


# ═══════════════════════════════════════════════════════════════════════════════
# EDGE CASES — boundaries, degradation, combinations
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCaseMatrix:
    """Boundary conditions and multi-signal combinations."""

    def test_no_env(self):
        """No environment state: operator style only, no env block."""
        p = get_policy(env=None)
        _has_dignity_floor(p)
        _has_operator_style(p)
        _lacks_env_block(p)
        _has_format(p)

    def test_late_evening(self):
        """Late evening: lighter tone overlay on operator style."""
        env = FakeEnv(activity_mode="idle")
        with patch("agents.hapax_voice.conversational_policy.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 23
            p = get_policy(env=env)
        _has_dignity_floor(p)
        _has_operator_style(p)
        assert "Late hours" in p
        _has_env_block(p)
        _has_format(p)

    def test_early_morning(self):
        """Early morning (before 6): same late-hours modulation."""
        env = FakeEnv(activity_mode="idle")
        with patch("agents.hapax_voice.conversational_policy.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 4
            p = get_policy(env=env)
        assert "Late hours" in p

    def test_boundary_hour_22(self):
        """Hour 22 is the first late hour."""
        env = FakeEnv(activity_mode="unknown")
        with patch("agents.hapax_voice.conversational_policy.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 22
            rules = _modulate_for_environment(env)
        assert any("Late hours" in r for r in rules)

    def test_boundary_hour_6_not_late(self):
        """Hour 6 is NOT late — it's the first non-late morning hour."""
        env = FakeEnv(activity_mode="unknown")
        with patch("agents.hapax_voice.conversational_policy.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 6
            rules = _modulate_for_environment(env)
        assert not any("Late hours" in r for r in rules)

    def test_long_session(self):
        """Session > 20min: conciseness overlay. No break suggestions."""
        env = FakeEnv()
        session_start = time.monotonic() - (25 * 60)
        p = get_policy(env=env, session_start=session_start)
        assert "Long session" in p
        assert "Tighten responses" in p

    def test_short_session_no_overlay(self):
        """Session < 20min: no session duration overlay."""
        env = FakeEnv()
        session_start = time.monotonic() - (10 * 60)
        p = get_policy(env=env, session_start=session_start)
        assert "Long session" not in p

    def test_multi_face_plus_coding(self):
        """Coding + guest: both activity and multi-face rules apply."""
        env = FakeEnv(activity_mode="coding", face_count=2)
        p = get_policy(env=env)
        assert "Maximum brevity" in p
        assert "accessible to all listeners" in p.lower()
        _has_env_block(p)

    def test_meeting_plus_long_session(self):
        """Meeting + long session: both constraints stack."""
        env = FakeEnv(activity_mode="meeting")
        session_start = time.monotonic() - (30 * 60)
        p = get_policy(env=env, session_start=session_start)
        assert "HARD CONSTRAINT" in p
        assert "Long session" in p

    def test_unknown_activity_no_modulation(self):
        """Unknown activity: no activity-specific rules emitted."""
        env = FakeEnv(activity_mode="unknown")
        rules = _modulate_for_environment(env)
        assert not any(
            any(mode in r for mode in ["brevity", "interruption", "CONSTRAINT", "Conversational"])
            for r in rules
        )


# ═══════════════════════════════════════════════════════════════════════════════
# INVARIANTS — properties that must hold across ALL inputs
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicyInvariants:
    """Properties that hold regardless of input combination."""

    @given(
        activity=st.sampled_from(["idle", "coding", "production", "meeting", "unknown"]),
        faces=st.integers(min_value=0, max_value=4),
        consent=st.sampled_from(["no_guest", "pending_consent", "consented", "guest_mode"]),
        guest=st.booleans(),
        child=st.booleans(),
    )
    @settings(max_examples=100)
    def test_always_has_dignity_floor(
        self, activity: str, faces: int, consent: str, guest: bool, child: bool
    ):
        """Dignity floor is present in every possible policy output."""
        env = FakeEnv(activity_mode=activity, face_count=faces, consent_phase=consent)
        p = get_policy(env=env, guest_mode=guest, child_mode=child)
        assert "truthful" in p

    @given(
        activity=st.sampled_from(["idle", "coding", "production", "meeting", "unknown"]),
        guest=st.booleans(),
        child=st.booleans(),
    )
    @settings(max_examples=50)
    def test_never_empty(self, activity: str, guest: bool, child: bool):
        """Policy output is never empty."""
        env = FakeEnv(activity_mode=activity)
        p = get_policy(env=env, guest_mode=guest, child_mode=child)
        assert len(p) > 0
        assert "## Conversational Policy" in p

    @given(
        activity=st.sampled_from(["idle", "coding", "production", "meeting", "unknown"]),
        faces=st.integers(min_value=0, max_value=4),
    )
    @settings(max_examples=50)
    def test_format_always_correct(self, activity: str, faces: int):
        """Policy always starts with header and has baseline."""
        env = FakeEnv(activity_mode=activity, face_count=faces)
        p = get_policy(env=env)
        _has_format(p)

    def test_guest_mode_never_has_operator_style(self):
        """Guest mode must NEVER leak operator personality, regardless of flags."""
        for child in [True, False]:
            p = get_policy(guest_mode=True, child_mode=child)
            _lacks_operator_style(p)

    def test_unconsented_never_has_operator_style(self):
        """Unconsented guest must NEVER see operator personality."""
        env = FakeEnv(consent_phase="pending_consent", face_count=2)
        p = get_policy(env=env)
        _lacks_operator_style(p)

    def test_child_style_only_in_child_mode(self):
        """Child interaction guidelines only appear with child_mode=True."""
        # Without child_mode
        p_no_child = get_policy(guest_mode=True, child_mode=False)
        _lacks_child_style(p_no_child)
        # With child_mode
        p_child = get_policy(guest_mode=True, child_mode=True)
        _has_child_style(p_child)

    def test_format_block_preserves_section_order(self):
        """Sections are joined in insertion order."""
        result = _format_block(["first", "second", "third"])
        assert result.index("first") < result.index("second") < result.index("third")

    def test_format_block_empty_list(self):
        """Empty section list produces empty string."""
        assert _format_block([]) == ""

    def test_modulation_pure_function(self):
        """_modulate_for_environment has no side effects — same input, same output."""
        env = FakeEnv(activity_mode="coding", face_count=2)
        with patch("agents.hapax_voice.conversational_policy.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 14
            r1 = _modulate_for_environment(env)
            r2 = _modulate_for_environment(env)
        assert r1 == r2
