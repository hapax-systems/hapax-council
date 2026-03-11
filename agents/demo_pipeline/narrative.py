"""Narrative framework selection and duration-driven planning constraints."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

STYLE_PATH = Path(__file__).resolve().parent.parent.parent / "profiles" / "presenter-style.yaml"
VOICE_EXAMPLES_PATH = (
    Path(__file__).resolve().parent.parent.parent / "profiles" / "voice-examples.yaml"
)
VOICE_PROFILE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "profiles" / "voice-profile.yaml"
)


# ── Narrative Frameworks ──────────────────────────────────────────────────────

FRAMEWORKS: dict[str, dict] = {
    "problem-solution-benefit": {
        "name": "Problem → Solution → Benefit",
        "when": "Leadership audiences, architecture reviews, executive briefings",
        "structure": [
            "Open by framing a challenge the audience recognizes or feels",
            "Show how the system addresses that challenge — specific, concrete",
            "Close with measurable impact: numbers, time saved, risk reduced",
        ],
        "section_flow": "problem → approach → implementation → results → next steps",
        "transitions": "Each section answers 'so what?' from the previous one",
    },
    "guided-tour": {
        "name": "Guided Tour",
        "when": "Family, team members, anyone seeing the system for the first time",
        "structure": [
            "Scene 1 must orient the viewer: SHOW a concrete capability (screenshot or screencast), not an architecture diagram. Answer 'what does this thing actually do?'",
            "Walk through capabilities in order of impact (most impressive or relatable first)",
            "Save architecture/how-it-works for the middle, after the viewer understands what the system does",
            "End with what it means for the viewer — personal relevance",
        ],
        "section_flow": "concrete demo → capability 1 → capability 2 → ... → 'what this means'",
        "transitions": "Natural flow: 'That handles X. The next piece is Y.'",
    },
    "design-rationale": {
        "name": "Design Rationale",
        "when": "Technical peers, architecture discussions, code reviews",
        "structure": [
            "Start with what exists — the system as built",
            "For each component: what it does, then WHY it's built this way",
            "Include trade-offs considered and alternatives rejected",
            "End with what you'd change or what's next",
        ],
        "section_flow": "current state → component deep-dives → trade-offs → future direction",
        "transitions": "Design-decision driven: 'The reason for X is...'",
    },
    "operational-cadence": {
        "name": "Operational Cadence",
        "when": "Team members, leadership interested in day-to-day operations",
        "structure": [
            "Frame around time: what happens every 15 minutes, daily, weekly",
            "Show the automation rhythm — timers, agents, notifications",
            "Demonstrate how issues surface and get handled",
            "End with toil reduction — what the operator doesn't have to do",
        ],
        "section_flow": "timing overview → automated cycles → issue handling → toil metrics",
        "transitions": "Time-based: 'Every 15 minutes...', 'Each morning at 7...'",
    },
}

# Map audience archetypes to their default narrative framework
AUDIENCE_FRAMEWORK: dict[str, str] = {
    "family": "guided-tour",
    "technical-peer": "design-rationale",
    "leadership": "problem-solution-benefit",
    "team-member": "operational-cadence",
}

# Duration → planning constraints
DURATION_TIERS: list[dict] = [
    {
        "max_seconds": 180,
        "scenes": (3, 5),
        "words_per_scene": (100, 150),
        "depth": "concise but complete narration",
    },
    {
        "max_seconds": 420,
        "scenes": (6, 9),
        "words_per_scene": (100, 160),
        "depth": "key points with context",
    },
    {
        "max_seconds": 600,
        "scenes": (10, 14),
        "words_per_scene": (100, 160),
        "depth": "focused explanations, one concept per scene",
    },
    {
        "max_seconds": 900,
        "scenes": (12, 16),
        "words_per_scene": (120, 180),
        "depth": "detailed explanations",
    },
    {
        "max_seconds": 1200,
        "scenes": (14, 18),
        "words_per_scene": (140, 200),
        "depth": "full rationale with trade-offs and design decisions",
    },
]


def load_style_guide(path: Path | None = None) -> dict:
    """Load the presenter style guide from YAML."""
    p = path or STYLE_PATH
    if not p.exists():
        log.warning("Style guide not found at %s — using empty style", p)
        return {}
    return yaml.safe_load(p.read_text())


def select_framework(audience: str) -> dict:
    """Select narrative framework based on audience archetype."""
    key = AUDIENCE_FRAMEWORK.get(audience, "design-rationale")
    return FRAMEWORKS[key]


def get_duration_constraints(target_seconds: int) -> dict:
    """Get planning constraints for a target duration."""
    for tier in DURATION_TIERS:
        if target_seconds <= tier["max_seconds"]:
            return tier
    return DURATION_TIERS[-1]  # longest tier


def format_planning_context(
    style_guide: dict,
    framework: dict,
    duration_constraints: dict,
    target_seconds: int,
) -> str:
    """Format style guide, narrative framework, and duration constraints into LLM prompt text."""
    lines: list[str] = []

    # Style guide
    lines.append("## Presenter Style Guide")
    lines.append(f"Voice: {style_guide.get('voice', 'first-person')}")
    lines.append(f"Cadence: {style_guide.get('cadence', 'state-explain-show')}")
    lines.append(f"Opening: {style_guide.get('opening', '')}")
    lines.append(f"Closing: {style_guide.get('closing', '')}")
    if style_guide.get("avoid"):
        lines.append("AVOID: " + "; ".join(style_guide["avoid"]))
    if style_guide.get("embrace"):
        lines.append("EMBRACE: " + "; ".join(style_guide["embrace"]))
    lines.append("")

    # Narrative framework
    lines.append(f"## Narrative Framework: {framework['name']}")
    lines.append(f"Flow: {framework['section_flow']}")
    lines.append(f"Transitions: {framework['transitions']}")
    for i, step in enumerate(framework["structure"], 1):
        lines.append(f"  {i}. {step}")
    lines.append("")

    # Duration constraints
    minutes = target_seconds / 60
    scene_min, scene_max = duration_constraints["scenes"]
    words_min, words_max = duration_constraints["words_per_scene"]
    lines.append(f"## Duration Constraints: {minutes:.0f} minutes")
    lines.append(f"Scene count: {scene_min}-{scene_max} scenes")
    lines.append(
        f"Narration per scene: {words_min}-{words_max} words (~{words_min // 2.5:.0f}-{words_max // 2.5:.0f} seconds of speech)"
    )
    lines.append(f"Depth: {duration_constraints['depth']}")
    total_words = int(target_seconds * 2.5)
    lines.append(
        f"Total narration budget: ~{total_words} words across all scenes (at 150 words/minute)"
    )
    lines.append(
        f"CRITICAL: Each scene narration MUST be {words_min}-{words_max} words. Short narrations will fail evaluation."
    )
    lines.append("")

    return "\n".join(lines)


def load_voice_examples(path: Path | None = None) -> dict:
    """Load gold-standard voice examples from YAML."""
    p = path or VOICE_EXAMPLES_PATH
    if not p.exists():
        log.warning("Voice examples not found at %s — using empty examples", p)
        return {}
    return yaml.safe_load(p.read_text())


def load_voice_profile(path: Path | None = None) -> dict:
    """Load positive-only voice profile from YAML."""
    p = path or VOICE_PROFILE_PATH
    if not p.exists():
        log.warning("Voice profile not found at %s — using empty profile", p)
        return {}
    return yaml.safe_load(p.read_text())
