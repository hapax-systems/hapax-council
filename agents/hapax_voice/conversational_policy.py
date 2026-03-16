"""Conversational policy — dynamic style directives for the voice LLM.

Decides HOW to speak based on operator profile, environment, and social context.
Sits between the dignity floor (universal) and the system prompt assembly (persona.py).

Architecture:
  Dignity Floor (hardcoded) → Conversational Policy (this) → System Prompt → Governance

The policy block is a plain-text string injected into the system prompt.
No ML, no bandit — deterministic rules from profile + environment.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_voice.perception import EnvironmentState

log = logging.getLogger(__name__)

_DIGEST_PATH = Path("profiles/operator-digest.json")

# ── Dignity Floor (universal, hardcoded) ─────────────────────────────────────
# Grice's maxims + face theory + benevolence — always active regardless of profile.

_DIGNITY_FLOOR = (
    "Always: be truthful (quality), relevant (relation), clear (manner), "
    "and appropriately brief (quantity). Respect the listener's autonomy "
    "and competence. Never condescend, mock, or be passive-aggressive."
)


# ── Profile Loading ──────────────────────────────────────────────────────────


def _load_communication_style() -> str | None:
    """Load communication_style summary from operator digest. Returns None on failure."""
    try:
        data = json.loads(_DIGEST_PATH.read_text())
        return data["dimensions"]["communication_style"]["summary"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        log.debug("Could not load communication_style from digest")
        return None


# ── Environmental Modulation ─────────────────────────────────────────────────

# Activity mode → style modulation
_ACTIVITY_MODULATIONS: dict[str, str] = {
    "coding": (
        "Maximum brevity. Technical register. Answer the question, nothing more. "
        "No pleasantries, no preamble."
    ),
    "production": (
        "Minimal interruption style. Short confirmations. "
        "Only speak substantively if directly asked."
    ),
    "meeting": ("Whisper-brief. One sentence max. The operator is in a meeting."),
    "idle": (
        "Conversational style permitted. Exploratory, relaxed pacing. "
        "May elaborate if the topic warrants it."
    ),
}

# Session duration thresholds (seconds)
_LONG_SESSION_S = 20 * 60  # 20 minutes

# Time-of-day heuristics (hour ranges)
_LATE_EVENING_START = 22
_EARLY_MORNING_END = 6


def _modulate_for_environment(
    env: EnvironmentState | None,
    session_start: float | None = None,
) -> list[str]:
    """Produce environment-driven style modulations. Pure function."""
    rules: list[str] = []

    if env is None:
        return rules

    # Activity mode
    activity = env.activity_mode
    if activity in _ACTIVITY_MODULATIONS:
        rules.append(_ACTIVITY_MODULATIONS[activity])

    # Multi-face → formal register
    if env.face_count > 1:
        rules.append(
            "Guest detected. Use formal register. Avoid personal content. "
            "Keep responses accessible to all listeners."
        )

    # Session duration → fatigue awareness
    if session_start is not None:
        import time

        elapsed = time.monotonic() - session_start
        if elapsed > _LONG_SESSION_S:
            rules.append("Long session. Reduce response length. Be extra concise.")

    # Time-of-day heuristic
    hour = datetime.now().hour
    if hour >= _LATE_EVENING_START or hour < _EARLY_MORNING_END:
        rules.append("Late hours. Lighter tone, shorter responses, no cognitive demands.")

    return rules


# ── Guest/Multi-Principal Policy ─────────────────────────────────────────────


def _guest_policy(consent_phase: str) -> str:
    """Policy for guest and multi-principal scenarios.

    consent_phase values from EnvironmentState:
      "no_guest"          → operator alone
      "pending_consent"   → guest detected, consent not yet granted
      "consented"         → guest with active consent contract
      "guest_mode"        → guest is primary speaker (operator absent/delegated)
    """
    if consent_phase == "consented":
        return (
            "Operator + consented guest. Moderate formality. "
            "Avoid work-sensitive content. Keep responses accessible to both. "
            "Use operator's preferred communication style but soften technical jargon."
        )
    if consent_phase == "pending_consent":
        return (
            "Unconsented guest present. Dignity floor only. "
            "Clear, respectful, minimal. No personal data. No operator-specific references."
        )
    if consent_phase == "guest_mode":
        return (
            "Guest mode. Dignity floor + friendliness. "
            "No personal data, no system information. General conversation only."
        )
    # no_guest → no guest policy needed
    return ""


# ── Public API ───────────────────────────────────────────────────────────────


def get_policy(
    env: EnvironmentState | None = None,
    guest_mode: bool = False,
    session_start: float | None = None,
) -> str:
    """Compute the conversational policy block for system prompt injection.

    Returns a formatted string ready for insertion into the system prompt.
    Empty string if no policy can be computed (graceful degradation).
    """
    sections: list[str] = []

    # 1. Dignity floor — always present
    sections.append(f"Baseline: {_DIGNITY_FLOOR}")

    # 2. Guest/multi-principal policy (overrides profile-driven style)
    if guest_mode:
        sections.append(_guest_policy("guest_mode"))
        # In guest mode, skip profile-driven style entirely
        return _format_block(sections)

    consent_phase = getattr(env, "consent_phase", "no_guest") if env else "no_guest"
    guest_rule = _guest_policy(consent_phase)
    if guest_rule:
        sections.append(guest_rule)
        # With unconsented guest, dignity floor is primary — skip profile style
        if consent_phase == "pending_consent":
            return _format_block(sections)

    # 3. Profile-driven style (operator's communication preferences)
    comm_style = _load_communication_style()
    if comm_style:
        sections.append(f"Operator style: {comm_style}")

    # 4. Environmental modulation
    env_rules = _modulate_for_environment(env, session_start)
    if env_rules:
        sections.append("Environment:\n" + "\n".join(f"- {r}" for r in env_rules))

    return _format_block(sections)


def _format_block(sections: list[str]) -> str:
    """Format policy sections into a system prompt block."""
    if not sections:
        return ""
    body = "\n\n".join(sections)
    return f"\n\n## Conversational Policy\n{body}"
