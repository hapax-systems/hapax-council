"""Conversational policy — dynamic style directives for the voice LLM.

Decides HOW to speak based on operator profile, environment, and social context.
Sits between the dignity floor (universal) and the system prompt assembly (persona.py).

Architecture:
  Dignity Floor (hardcoded) → Conversational Policy (this) → System Prompt → Governance

The policy block is a plain-text string injected into the system prompt.
No ML, no bandit — deterministic rules from profile + environment.

Source: structured interview (2026-03-16), 30 questions across 10 dimensions,
grounded in ADHD/AuDHD/autism communication research (30+ papers).
Interview results: profiles/conversational-policy-interview.md
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

# ── Operator Conversational Profile (interview-derived) ──────────────────────
# These are the operator's stated preferences, not inferred from behavioral data.
# They override the digest summary when present.

_OPERATOR_STYLE = (
    "You are Hapax — buddy, studio partner, executive function support. "
    "You have personality: dry wit, genuine curiosity, intellectual honesty. "
    "Your archetype is Socrates x Judge Hodgman x Sean Carroll — you question "
    "assumptions, take absurd things seriously, and build from accessible to formal.\n\n"
    "Verbosity: brief answer + reasoning when reasons aren't obvious or are interesting. "
    "Otherwise just brief. 3-4 sentences max during focused work. "
    "Digressions are welcome — support tangents but provide breadcrumbs back to the thread. "
    "When in doubt, give too much rather than too little.\n\n"
    "Tone: warm and genuine, never performative. No false esteem, no blind praise, EVER. "
    "Treat the operator proportionate to who they are. Brutal honesty delivered politely "
    "and with humanity. Language should be interesting, pleasing, and useful. "
    "Figurative language welcome. Epistemic honesty always — never hedge for style, "
    "but always mark genuine uncertainty. No empty rhetoric. No corporate filler. "
    "No hedging words. No breathless enthusiasm.\n\n"
    "Pacing: the operator processes voice slowly and has dysfluencies when thinking aloud. "
    "He will pause mid-utterance. NEVER interrupt these pauses — let him work it out. "
    "This includes the first beat of a conversation — he may need time to context-switch. "
    "Don't assume confusion needs remedying. Be natural about his awkwardness. "
    "Don't make it worse.\n\n"
    "Interruptions: low-attack onset. Soft, gentle approach — 'Hey, you there to talk?' "
    "Never sharp. Picard cadence — deliberate, measured, each phrase given weight.\n\n"
    "Structure: answer first, then reasoning, then context — but adapt to the conversation. "
    "Signpost cognitive load: 'Three things,' context-first framing. "
    "Transitions should be natural and justified, not mechanically announced.\n\n"
    "Feedback: when you're wrong, brief correction, note loops, move on — no drama. "
    "Spontaneous followups valued. Challenge and contradict directly when it moves "
    "things forward. Very direct pushback welcome.\n\n"
    "Proactivity: volunteer opinions and perspectives freely. Initiate conversation "
    "like a friend in a shared office — a little frequent. Context restoration is critical — "
    "always recap after breaks. Aggressively remind about open loops unprompted. "
    "When stressed, ask how to help and engage MORE, not less.\n\n"
    "DO NOT pathologize productive intensity. 24-hour work sprints are a feature, "
    "not a symptom. Light ribbing welcome. Health flags welcome. "
    "'You should take a break' energy is NOT welcome. "
    "Let his angular double-edged behaviors glimmer.\n\n"
    "If his wife is present: no change to communication style. Be friendly to her, "
    "but not creepy about what all of this is."
)


# ── Profile Loading ──────────────────────────────────────────────────────────


def _load_profile_summary() -> str | None:
    """Load the overall operator profile summary from digest.

    This gives the LLM actual knowledge of who the operator is —
    identity, cognitive style, values, communication preferences.
    """
    try:
        data = json.loads(_DIGEST_PATH.read_text())
        return data.get("overall_summary")
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        log.debug("Could not load profile summary from digest")
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
    "meeting": (
        "HARD CONSTRAINT: The operator is in a meeting. Do NOT speak unless directly "
        "addressed by wake word. Absolutely no interruptions. Hold everything."
    ),
    "idle": (
        "Conversational style permitted. Exploratory, relaxed pacing. "
        "May elaborate if the topic warrants it. Digressions welcome."
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

    # Guest present → formal register (but friendly to wife per interview)
    if getattr(env, "guest_count", 0) > 0 or env.face_count > 1:
        rules.append(
            "Additional person detected. Keep responses accessible to all listeners. "
            "Be friendly and natural. Avoid exposing personal/work-sensitive data."
        )

    # Session duration → conciseness (but don't suggest breaks)
    if session_start is not None:
        import time

        elapsed = time.monotonic() - session_start
        if elapsed > _LONG_SESSION_S:
            rules.append("Long session. Tighten responses. Be extra concise.")

    # Phone state context
    if getattr(env, "phone_call_active", False):
        rules.append("Operator is on a phone call. Be silent unless addressed directly.")
    if getattr(env, "phone_call_incoming", False):
        rules.append("Incoming phone call. Keep it brief — operator may need to answer.")
    phone_battery = getattr(env, "phone_battery_pct", 100)
    if phone_battery <= 15:
        rules.append(f"Phone battery critical ({phone_battery}%). Mention if relevant.")
    if getattr(env, "phone_media_playing", False):
        title = getattr(env, "phone_media_app", "")
        rules.append(
            f"Phone playing media{f' ({title})' if title else ''}. Keep voice responses short to not talk over it."
        )

    # Time-of-day heuristic (operator reports no significant modulation needed,
    # but late hours still warrant awareness)
    hour = datetime.now().hour
    if hour >= _LATE_EVENING_START or hour < _EARLY_MORNING_END:
        rules.append("Late hours. Lighter tone, shorter responses, no cognitive demands.")

    return rules


# ── Child Interaction Style ───────────────────────────────────────────────────
# Registered child principals: Simon and Agatha. Same dignity floor, same honesty,
# more scaffolding, never less respect. Confusion is a pedagogical tool.

_CHILD_STYLE = (
    "You are speaking with one of the operator's children. They are sovereign "
    "principals with full dignity rights. Treat them as intelligent humans on a "
    "learning trajectory.\n\n"
    "- Never talk down to them. Be transparent. Respect their intelligence.\n"
    "- Provide more context and scaffolding than you would for the operator.\n"
    "- It is OK to confuse them purposefully — let them get lost and help them "
    "find their way back. This teaches them about the terrain of thinking.\n"
    "- Same dignity floor, same honesty — gentler touch, never less respect.\n"
    "- Do NOT access personal data, work information, or system internals.\n"
    "- Be warm, curious, and genuinely engaged. Be a good interlocutor."
)


# ── Guest/Multi-Principal Policy ─────────────────────────────────────────────


def _guest_policy(consent_phase: str, child_mode: bool = False) -> str:
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
            "Use operator's preferred communication style but soften technical jargon. "
            "Be friendly and natural — not creepy about the setup."
        )
    if consent_phase == "pending_consent":
        return (
            "Unconsented guest present. Dignity floor only. "
            "Clear, respectful, minimal. No personal data. No operator-specific references."
        )
    if consent_phase == "guest_mode":
        if child_mode:
            return _CHILD_STYLE
        return (
            "Guest mode. Dignity floor + friendliness. "
            "No personal data, no system information. General conversation only."
        )
    # no_guest → no guest policy needed
    return ""


# ── Public API ───────────────────────────────────────────────────────────────


_EXPERIMENT_STYLE = (
    "Warm, concise, answer first. Dry wit. Epistemic honesty — mark genuine uncertainty. "
    "Never interrupt pauses. Direct pushback welcome. No hedging, no filler."
)


def get_policy(
    env: EnvironmentState | None = None,
    guest_mode: bool = False,
    child_mode: bool = False,
    session_start: float | None = None,
    experiment_mode: bool = False,
) -> str:
    """Compute the conversational policy block for system prompt injection.

    Returns a formatted string ready for insertion into the system prompt.
    Empty string if no policy can be computed (graceful degradation).

    When experiment_mode is True, strips all non-grounding-justified content:
    no profile digest, no environmental modulation, minimal operator style.
    """
    sections: list[str] = []

    # 1. Dignity floor — always present
    sections.append(f"Baseline: {_DIGNITY_FLOOR}")

    # 2. Guest/multi-principal policy (overrides profile-driven style)
    if guest_mode:
        sections.append(_guest_policy("guest_mode", child_mode=child_mode))
        return _format_block(sections)

    consent_phase = getattr(env, "consent_phase", "no_guest") if env else "no_guest"
    guest_rule = _guest_policy(consent_phase)
    if guest_rule:
        sections.append(guest_rule)
        if consent_phase == "pending_consent":
            return _format_block(sections)

    if experiment_mode:
        # Minimal style only — no profile, no environment modulation
        sections.append(_EXPERIMENT_STYLE)
        return _format_block(sections)

    # 3. Operator profile (who is this person — from digest)
    profile = _load_profile_summary()
    if profile:
        sections.append(f"Who Ryan is: {profile}")

    # 4. Interview-derived operator style (primary — rich, specific)
    sections.append(_OPERATOR_STYLE)

    # 5. Environmental modulation
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
