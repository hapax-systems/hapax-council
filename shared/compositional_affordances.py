"""Compositional capability catalog — what the director's impingements recruit.

Spec: `docs/superpowers/specs/2026-04-17-volitional-grounded-director-design.md` §3.3.

The director emits `CompositionalImpingement`s whose `intent_family` tag
lives in one of these families:

- camera.hero        — foreground a specific camera role for a context
- preset.bias        — bias preset selection toward a stylistic family
- overlay.emphasis   — foreground or dim a specific overlay Cairo source
- youtube.direction  — direct the YouTube queue (cut-to, advance, cut-away)
- attention.winner   — dispatch the attention-bid winner
- stream_mode.transition — axiom-gated stream-mode shift

The AffordancePipeline cosine-matches the impingement's `narrative` against
these capability descriptions (already embedded in Qdrant) and recruits
one. The `CompositionalConsumer` then dispatches on the recruited `name`.

No activation-handler class lives here — these are data records. The
dispatcher is `agents/studio_compositor/compositional_consumer.py`.

Run the seeding script after adding entries here:
    uv run scripts/seed-compositional-affordances.py
"""

from __future__ import annotations

from shared.affordance import CapabilityRecord, OperationalProperties

_DAEMON = "studio_compositor"


def _record(name: str, description: str, *, medium: str = "visual") -> CapabilityRecord:
    return CapabilityRecord(
        name=name,
        description=description,
        daemon=_DAEMON,
        operational=OperationalProperties(
            latency_class="fast",
            medium=medium,
            # Most compositional moves are axiom-safe (they act on
            # operator-self or abstract chrome). The per-capability
            # consent_required override applies where it matters
            # (e.g. camera.hero on rooms with possible guest presence).
            consent_required=False,
        ),
    )


# ── Camera hero affordances ───────────────────────────────────────────────
# Foregrounds a specific camera role when the impingement's narrative
# matches the context class. Camera-role taxonomy follows the physical
# studio inventory (memory `project_studio_cameras.md`).

_CAMERA_HERO: list[CapabilityRecord] = [
    _record(
        "cam.hero.overhead.hardware-active",
        "shows the overhead hardware workspace when the turntable, MPC pads, or mixer are where attention belongs",
    ),
    _record(
        "cam.hero.overhead.vinyl-spinning",
        "shows the overhead turntable when a record is playing and the music is the subject",
    ),
    _record(
        "cam.hero.synths-brio.beatmaking",
        "shows the synthesizer bank when beat-making or pattern programming is underway",
    ),
    _record(
        "cam.hero.operator-brio.conversing",
        "shows the operator's face and desk when chat engagement or conversation is the move",
    ),
    _record(
        "cam.hero.operator-brio.reacting",
        "shows the operator reacting to the content in the triangle display",
    ),
    _record(
        "cam.hero.desk-c920.writing-reading",
        "shows the desk surface when focused textual work, reading, or notetaking is happening",
    ),
    _record(
        "cam.hero.desk-c920.coding",
        "shows the desk and keyboard when code is being written",
    ),
    _record(
        "cam.hero.room-c920.ambient",
        "shows the broader room when no specific zone claims attention and an ambient overview is appropriate",
    ),
    _record(
        "cam.hero.room-brio.idle",
        "shows the room for an idle or still moment when the operator is away or at rest",
    ),
]

# ── Preset-family affordances ──────────────────────────────────────────────
# Each family corresponds to a stylistic class of effect presets. The
# compositional_consumer's preset_family_selector picks a specific preset
# within the recruited family.

_PRESET_FAMILY: list[CapabilityRecord] = [
    _record(
        "fx.family.audio-reactive",
        "sound-following visuals that modulate with beat, energy, and spectrum when music is the center of attention",
    ),
    _record(
        "fx.family.calm-textural",
        "slow field-like visuals for chill, reflective, or studying contexts without strong rhythmic drive",
    ),
    _record(
        "fx.family.glitch-dense",
        "high-entropy glitch and dense procedural fields for intense, seeking, or curious stances",
    ),
    _record(
        "fx.family.warm-minimal",
        "warm minimal fields that sit quietly as a backdrop for conversation or focused work",
    ),
]

# ── Overlay emphasis affordances ───────────────────────────────────────────
# Adjusts the alpha / z-order of a specific Cairo source. Writes to
# /dev/shm/hapax-compositor/overlay-alpha-overrides.json.

_OVERLAY_EMPHASIS: list[CapabilityRecord] = [
    _record(
        "overlay.foreground.album",
        "foregrounds the album-cover overlay when the music is the subject of attention",
    ),
    _record(
        "overlay.foreground.captions",
        "foregrounds the captions strip when narration is happening and viewers need to read what is spoken",
    ),
    _record(
        "overlay.foreground.chat-legend",
        "foregrounds the chat-keyword legend when new viewers arrive and need participation vocabulary",
    ),
    _record(
        "overlay.foreground.activity-header",
        "foregrounds the activity header when the directorial activity itself is the legible subject",
    ),
    _record(
        "overlay.foreground.grounding-ticker",
        "foregrounds the grounding-provenance ticker when the research instrument's legibility matters",
    ),
    _record(
        "overlay.dim.all-chrome",
        "dims all chrome overlays for a reverent, minimal, music-first moment",
    ),
]

# ── YouTube direction affordances ──────────────────────────────────────────
# Directs the YouTube queue. Writes intents the compositor's slot-rotator
# reads on next advance.

_YOUTUBE_DIRECTION: list[CapabilityRecord] = [
    _record(
        "youtube.cut-to",
        "cuts the hero focus to the currently-playing YouTube slot when the video content claims center-stage",
        medium="visual",
    ),
    _record(
        "youtube.advance-queue",
        "pulls the next contextually relevant YouTube video into rotation when the current slot has run its course",
        medium="visual",
    ),
    _record(
        "youtube.cut-away",
        "shifts the hero focus away from YouTube to live operator content when the live moment is more relevant",
        medium="visual",
    ),
]

# ── Attention-bid winner affordances ───────────────────────────────────────
# Wires to agents/attention_bids/dispatcher.py:dispatch_recruited_winner.

_ATTENTION_WINNER: list[CapabilityRecord] = [
    _record(
        "attention.winner.code-narration",
        "dispatches a code-narration attention bid when source-code activity deserves on-stream narration",
        medium="textual",
    ),
    _record(
        "attention.winner.briefing",
        "dispatches a briefing attention bid when a daily or weekly briefing is due",
        medium="textual",
    ),
    _record(
        "attention.winner.nudge",
        "dispatches an operator nudge attention bid when an actionable nudge is ready",
        medium="notification",
    ),
    _record(
        "attention.winner.goal-advance",
        "dispatches a goal-advancement attention bid when a tracked objective is ripe for movement",
        medium="textual",
    ),
]

# ── Stream-mode transitions ────────────────────────────────────────────────
# Axiom-gated by stream_transition_gate. The pipeline's consent gate
# filters these out when prerequisites fail.

_STREAM_MODE: list[CapabilityRecord] = [
    CapabilityRecord(
        name="stream.mode.public-research.transition",
        description=(
            "transitions the stream mode to public_research when the operator "
            "has declared intent to open the session to consented observers for research"
        ),
        daemon=_DAEMON,
        operational=OperationalProperties(
            latency_class="fast",
            medium="notification",
            consent_required=True,
        ),
    ),
]

# ── Catalog ────────────────────────────────────────────────────────────────

COMPOSITIONAL_CAPABILITIES: list[CapabilityRecord] = (
    _CAMERA_HERO
    + _PRESET_FAMILY
    + _OVERLAY_EMPHASIS
    + _YOUTUBE_DIRECTION
    + _ATTENTION_WINNER
    + _STREAM_MODE
)


def by_family(family: str) -> list[CapabilityRecord]:
    """All capabilities whose name starts with ``family + '.'``."""
    prefix = family.rstrip(".") + "."
    return [c for c in COMPOSITIONAL_CAPABILITIES if c.name.startswith(prefix)]


def capability_names() -> set[str]:
    return {c.name for c in COMPOSITIONAL_CAPABILITIES}
