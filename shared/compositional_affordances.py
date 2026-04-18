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

# ── Ward-property affordances ─────────────────────────────────────────────
# Per-ward modulation of the livestream surface (memory
# `reference_wards_taxonomy.md`). Each entry pairs one ward (Cairo source,
# overlay zone, hothouse panel, etc.) with one modifier from the dispatcher's
# vocabulary. Recruitment writes the corresponding entry to
# /dev/shm/hapax-compositor/ward-properties.json or ward-animation-state.json.
# The catalog is intentionally narrow at first — the high-leverage entries
# (album emphasize, hothouse quiet during silence, captions dim during
# study) — and grows as operators identify new modulation moves worth
# recruiting against.

_WARD_HIGHLIGHT: list[CapabilityRecord] = [
    _record(
        "ward.highlight.album.foreground",
        "brightens the album cover ward when the music is the subject of the moment",
    ),
    _record(
        "ward.highlight.album.dim",
        "dims the album cover ward when the music is incidental and other content claims attention",
    ),
    _record(
        "ward.highlight.captions.dim",
        "dims the captions strip when the operator is silent or chat is the subject",
    ),
    _record(
        "ward.highlight.captions.foreground",
        "brightens the captions strip when the operator is speaking and accessibility matters",
    ),
    _record(
        "ward.highlight.thinking_indicator.pulse",
        "pulses the thinking indicator when an LLM tick is in flight to make latency visible",
    ),
]

_WARD_STAGING: list[CapabilityRecord] = [
    _record(
        "ward.staging.recruitment_candidate_panel.hide",
        "hides the recruitment candidate panel during a public stream when internal cognition should not be foregrounded",
    ),
    _record(
        "ward.staging.recruitment_candidate_panel.show",
        "shows the recruitment candidate panel during research-mode streams when transparency is the subject",
    ),
    _record(
        "ward.staging.impingement_cascade.hide",
        "hides the impingement cascade panel when the audience is non-research and the diagnostic is noise",
    ),
    _record(
        "ward.staging.activity_variety_log.hide",
        "hides the activity variety log when the operator wants the chrome to retreat",
    ),
]

_WARD_CHOREOGRAPHY: list[CapabilityRecord] = [
    _record(
        "ward.choreography.album-emphasize",
        "scales up and brightens the album cover while dimming peripheral wards when music becomes the moment",
    ),
    _record(
        "ward.choreography.hothouse-quiet",
        "fades all hothouse diagnostic panels to half opacity when primary content should claim attention",
    ),
    _record(
        "ward.choreography.camera-spotlight",
        "scales up the hero camera tile and dims the other PiPs when one camera deserves a spotlight moment",
    ),
]

_WARD_CADENCE: list[CapabilityRecord] = [
    _record(
        "ward.cadence.thinking_indicator.pulse-2hz",
        "speeds the thinking indicator's pulse to 2hz to signal heightened cognitive activity",
    ),
    _record(
        "ward.cadence.thinking_indicator.default",
        "returns the thinking indicator to its baseline cadence when activity has settled",
    ),
]

# Audit C1 (2026-04-18): the ward.size / ward.position / ward.appearance
# IntentFamily values were promoted to first-class in PR #1046's prompt
# enum but had ZERO catalog entries — so family-restricted retrieval
# (PR #1044) returned empty for every recruitment. These three lists
# close that gap. Each entry pairs (ward, modifier) with a Gibson-verb
# description per the unified-semantic-recruitment rubric.
_WARD_SIZE: list[CapabilityRecord] = [
    _record(
        "ward.size.album.grow-150pct",
        "scales the album cover up to 150% when music takes center stage",
    ),
    _record(
        "ward.size.album.shrink-20pct",
        "scales the album cover down 20% when music recedes and other content claims focus",
    ),
    _record(
        "ward.size.album.natural",
        "returns the album cover to its layout-declared natural size",
    ),
    _record(
        "ward.size.token_pole.grow-110pct",
        "enlarges the token pole when token economy or attention dynamics are the subject",
    ),
    _record(
        "ward.size.token_pole.natural",
        "returns the token pole to its natural size",
    ),
    _record(
        "ward.size.captions.grow-110pct",
        "enlarges the captions strip when accessibility or speech-clarity is the subject",
    ),
    _record(
        "ward.size.captions.natural",
        "returns captions to natural size",
    ),
    _record(
        "ward.size.recruitment_candidate_panel.shrink-50pct",
        "shrinks the recruitment candidate panel when its diagnostic detail is noise to the audience",
    ),
]

_WARD_POSITION: list[CapabilityRecord] = [
    _record(
        "ward.position.token_pole.drift-sine-1hz",
        "drifts the token pole vertically on a slow sine to signal gentle attention dynamics",
    ),
    _record(
        "ward.position.token_pole.drift-sine-slow",
        "drifts the token pole on a very slow sine for ambient hold states",
    ),
    _record(
        "ward.position.album.drift-circle-1hz",
        "circles the album cover slowly to signal the spinning vinyl when audio energy is high",
    ),
    _record(
        "ward.position.album.static",
        "holds the album cover at its layout position when music is incidental",
    ),
    _record(
        "ward.position.captions.static",
        "holds captions at their bottom-strip position",
    ),
    _record(
        "ward.position.thinking_indicator.drift-sine-1hz",
        "drifts the thinking indicator on a slow sine while LLM tick is in flight",
    ),
]

_WARD_APPEARANCE: list[CapabilityRecord] = [
    _record(
        "ward.appearance.album.tint-warm",
        "warms the album cover ward's color register when the music is warm or nostalgic",
    ),
    _record(
        "ward.appearance.album.tint-cool",
        "cools the album cover ward when the music is cold or melancholic",
    ),
    _record(
        "ward.appearance.album.desaturate",
        "desaturates the album cover for grayscale moments when color would distract",
    ),
    _record(
        "ward.appearance.album.palette-default",
        "returns the album cover to its default palette",
    ),
    _record(
        "ward.appearance.captions.tint-warm",
        "warms the captions strip's color when the speaker is the operator and warmth helps legibility",
    ),
    _record(
        "ward.appearance.captions.palette-default",
        "returns captions to their default color palette",
    ),
    _record(
        "ward.appearance.token_pole.tint-cool",
        "cools the token pole when token dynamics are subdued or contemplative",
    ),
    _record(
        "ward.appearance.token_pole.palette-default",
        "returns the token pole to its default palette",
    ),
]

_WARD_AFFORDANCES: list[CapabilityRecord] = (
    _WARD_HIGHLIGHT
    + _WARD_STAGING
    + _WARD_CHOREOGRAPHY
    + _WARD_CADENCE
    + _WARD_SIZE
    + _WARD_POSITION
    + _WARD_APPEARANCE
)


# ── HOMAGE framework affordances (spec §4.11) ─────────────────────────────
# Each maps to a package-specific transition that the choreographer
# reconciles. Dispatch writes into homage-pending-transitions.json;
# the choreographer consumes the next tick and emits the ordered plan.

_HOMAGE_ROTATION: list[CapabilityRecord] = [
    _record(
        "homage.rotation.signature",
        "rotates to a new signature artefact (quit-quip, join-banner, MOTD) under the active homage package",
    ),
    _record(
        "homage.rotation.package-cycle",
        "cycles the active homage package to the next value in the structural director's rotation",
    ),
]

_HOMAGE_EMERGENCE: list[CapabilityRecord] = [
    _record(
        "homage.emergence.ward",
        "brings a dormant ward into view via the package's default entry transition",
    ),
    _record(
        "homage.emergence.activity-header",
        "emerges the activity header for fresh legibility when activity changes",
    ),
    _record(
        "homage.emergence.stance-indicator",
        "emerges the stance indicator when stance shifts so viewers can read the change",
    ),
    _record(
        "homage.emergence.grounding-ticker",
        "emerges the grounding provenance ticker to foreground the signals driving this move",
    ),
]

_HOMAGE_SWAP: list[CapabilityRecord] = [
    _record(
        "homage.swap.hero-chrome",
        "swaps the hero camera with chrome wards in a choreographed exit-plus-entry pair",
    ),
    _record(
        "homage.swap.legibility-pair",
        "swaps two legibility surfaces so attention trades from activity to stance framing",
    ),
    _record(
        "homage.swap.signature-motd",
        "swaps a quit-quip off-frame and a MOTD block on-frame under the active package",
    ),
]

_HOMAGE_CYCLE: list[CapabilityRecord] = [
    _record(
        "homage.cycle.legibility-wards",
        "sweeps through the legibility wards in order, foregrounding each briefly",
    ),
    _record(
        "homage.cycle.hothouse-wards",
        "cycles hothouse diagnostic panels so viewers glimpse the machinery in rotation",
    ),
    _record(
        "homage.cycle.chat-keywords",
        "cycles chat vocabulary entries so the topic line refreshes which keywords are live",
    ),
]

_HOMAGE_RECEDE: list[CapabilityRecord] = [
    _record(
        "homage.recede.ward",
        "retires a ward to absent via the package's default exit transition",
    ),
    _record(
        "homage.recede.all-chrome",
        "retires all chrome wards for a music-first moment; mass part-message under the active package",
    ),
    _record(
        "homage.recede.diagnostic",
        "retires diagnostic hothouse panels when the moment is not a machinery moment",
    ),
]

_HOMAGE_EXPAND: list[CapabilityRecord] = [
    _record(
        "homage.expand.hero",
        "expands the hero camera with a scale-bump under the package's expansion transition",
    ),
    _record(
        "homage.expand.album",
        "expands the album overlay when music is the centre of the moment",
    ),
    _record(
        "homage.expand.captions",
        "expands the captions strip to emphasise a narration line that carries weight",
    ),
]


_HOMAGE_AFFORDANCES: list[CapabilityRecord] = (
    _HOMAGE_ROTATION
    + _HOMAGE_EMERGENCE
    + _HOMAGE_SWAP
    + _HOMAGE_CYCLE
    + _HOMAGE_RECEDE
    + _HOMAGE_EXPAND
)


# ── Catalog ────────────────────────────────────────────────────────────────

COMPOSITIONAL_CAPABILITIES: list[CapabilityRecord] = (
    _CAMERA_HERO
    + _PRESET_FAMILY
    + _OVERLAY_EMPHASIS
    + _YOUTUBE_DIRECTION
    + _ATTENTION_WINNER
    + _STREAM_MODE
    + _WARD_AFFORDANCES
    + _HOMAGE_AFFORDANCES
)


def by_family(family: str) -> list[CapabilityRecord]:
    """All capabilities whose name starts with ``family + '.'``."""
    prefix = family.rstrip(".") + "."
    return [c for c in COMPOSITIONAL_CAPABILITIES if c.name.startswith(prefix)]


def capability_names() -> set[str]:
    return {c.name for c in COMPOSITIONAL_CAPABILITIES}
