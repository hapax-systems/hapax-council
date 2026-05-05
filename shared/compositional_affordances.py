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

from shared.affordance import CapabilityRecord, ContentRisk, MonetizationRisk, OperationalProperties

_DAEMON = "studio_compositor"
_PUBLIC_EVIDENCE_REFS = (
    "docs/superpowers/specs/2026-04-17-volitional-grounded-director-design.md",
)
_PUBLIC_RIGHTS_REF = "rights:operator-owned-compositor-control"
_PUBLIC_PROVENANCE_REF = "provenance:compositional-affordance-catalog"
_PUBLIC_MONETIZATION_REASON = (
    "Operator-authored compositor control; it changes local presentation and does not introduce "
    "new third-party monetizable content."
)
_PUBLIC_CONTENT_REASON = (
    "Compositor control over already-gated local sources; no new external media source is acquired."
)


def _record(
    name: str,
    description: str,
    *,
    medium: str = "visual",
    monetization_risk: MonetizationRisk = "none",
    risk_reason: str = _PUBLIC_MONETIZATION_REASON,
    content_risk: ContentRisk = "tier_0_owned",
    content_risk_reason: str = _PUBLIC_CONTENT_REASON,
    rights_ref: str = _PUBLIC_RIGHTS_REF,
    provenance_ref: str = _PUBLIC_PROVENANCE_REF,
) -> CapabilityRecord:
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
            public_capable=True,
            monetization_risk=monetization_risk,
            risk_reason=risk_reason,
            content_risk=content_risk,
            content_risk_reason=content_risk_reason,
            rights_ref=rights_ref,
            provenance_ref=provenance_ref,
            evidence_refs=_PUBLIC_EVIDENCE_REFS,
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
    # Phase 5 of preset-variety-plan (task #166): the neutral-ambient
    # family lives in FAMILY_PRESETS as the default fallback but was
    # never registered as a capability — so the affordance pipeline
    # could not surface it via Qdrant retrieval, only via the
    # dispatcher's hard-coded fallback path. Closing the gap so
    # recruitment can actually choose neutral-ambient when narrative
    # justifies it.
    _record(
        "fx.family.neutral-ambient",
        "neutral baseline visuals for default fallback moments without strong directional cue, coherent and unobtrusive backdrop",
    ),
    # Phase 6 of preset-variety-plan (task #166): the recruitment target
    # for ``content.too-similar-recently`` impingements emitted by
    # ``AffordancePipeline._maybe_emit_perceptual_distance_impingement``
    # when the recency window's mean cosine similarity crosses 0.85.
    # Lets the surface SEE that it's been clustering and reach for
    # something perceptually distant if the moment allows. The
    # impingement is a fact, not a rule — the pipeline still scores
    # this against whatever else recruits.
    _record(
        "novelty.shift",
        "widen the perceptual register; reach for a perceptually-distant preset family from what has recently fired, when the surface has been clustering",
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
        monetization_risk="high",
        risk_reason="Cutting to an unverified YouTube slot foregrounds third-party video; blocked until provenance gate proves clearance.",
        content_risk="tier_4_risky",
        content_risk_reason="YouTube slot video source is unverified external media by default.",
        rights_ref="rights:youtube-slot-unverified",
        provenance_ref="provenance:youtube-slot-unverified",
    ),
    _record(
        "youtube.advance-queue",
        "pulls the next contextually relevant YouTube video into rotation when the current slot has run its course",
        medium="visual",
        monetization_risk="high",
        risk_reason="Advancing an unverified YouTube queue can introduce third-party video; blocked until provenance gate proves clearance.",
        content_risk="tier_4_risky",
        content_risk_reason="YouTube queue source is unverified external media by default.",
        rights_ref="rights:youtube-slot-unverified",
        provenance_ref="provenance:youtube-slot-unverified",
    ),
    _record(
        "youtube.cut-away",
        "shifts the hero focus away from YouTube to live operator content when the live moment is more relevant",
        medium="visual",
        monetization_risk="low",
        risk_reason="Cutting away from YouTube reduces third-party exposure; low risk because it is a public control over source egress.",
        content_risk="tier_0_owned",
        content_risk_reason="The control exits external video toward local operator/studio content.",
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
            public_capable=True,
            monetization_risk="none",
            risk_reason=_PUBLIC_MONETIZATION_REASON,
            content_risk="tier_0_owned",
            content_risk_reason=_PUBLIC_CONTENT_REASON,
            rights_ref=_PUBLIC_RIGHTS_REF,
            provenance_ref=_PUBLIC_PROVENANCE_REF,
            evidence_refs=_PUBLIC_EVIDENCE_REFS,
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
    # Music — album cover lives at beyond-scrim; foreground/dim signals
    # whether music is the subject or incidental.
    _record(
        "ward.highlight.album.foreground",
        "brightens the album cover ward when the music is the subject of the moment",
    ),
    _record(
        "ward.highlight.album.dim",
        "dims the album cover ward when the music is incidental and other content claims attention",
    ),
    # Communication — captions + chat ambient + stream overlay + impingement
    # cascade. Originally only album/captions/thinking had records;
    # lssh-008 audit found ``family-restricted retrieval returned no
    # candidates`` 10× in 12h for ward.highlight.<other> queries
    # because the catalog was missing per-ward records for the rest of
    # the WARD_DOMAIN. Filling the gap.
    _record(
        "ward.highlight.captions.dim",
        "dims the captions strip when the operator is silent or chat is the subject",
    ),
    _record(
        "ward.highlight.captions.foreground",
        "brightens the captions strip when the operator is speaking and accessibility matters",
    ),
    _record(
        "ward.highlight.chat_ambient.foreground",
        "brightens the chat ambient surface when audience traffic deserves direct visibility",
    ),
    _record(
        "ward.highlight.chat_ambient.dim",
        "dims the chat ambient surface when chat is quiet or other content takes the floor",
    ),
    _record(
        "ward.highlight.stream_overlay.foreground",
        "brightens the stream-mode overlay during a mode change so viewers see the transition",
    ),
    _record(
        "ward.highlight.impingement_cascade.pulse",
        "pulses the impingement cascade when recruitment activity is itself the subject worth showing",
    ),
    # Presence — thinking, who's here, pressure.
    _record(
        "ward.highlight.thinking_indicator.pulse",
        "pulses the thinking indicator when an LLM tick is in flight to make latency visible",
    ),
    _record(
        "ward.highlight.thinking_indicator.foreground",
        "brightens the thinking indicator when sustained reasoning is the subject of the moment",
    ),
    _record(
        "ward.highlight.thinking_indicator.dim",
        "dims the thinking indicator when reactive moves dominate and reasoning posture is incidental",
    ),
    _record(
        "ward.highlight.whos_here.foreground",
        "brightens the who's-here ward when a new viewer joins and acknowledgement is appropriate",
    ),
    _record(
        "ward.highlight.whos_here.dim",
        "dims the who's-here ward when audience composition is incidental to the active move",
    ),
    _record(
        "ward.highlight.pressure_gauge.pulse",
        "pulses the pressure gauge when system pressure spikes and the spike itself is legible content",
    ),
    _record(
        "ward.highlight.pressure_gauge.foreground",
        "brightens the pressure gauge during sustained high-pressure spans so viewers can see the strain",
    ),
    # Token economy.
    _record(
        "ward.highlight.token_pole.pulse",
        "pulses the token pole when a token cascade lands and the reward beat is the move",
    ),
    _record(
        "ward.highlight.token_pole.foreground",
        "brightens the token pole when token-economy progress is itself the subject of the moment",
    ),
    # Music — vinyl platter + HARDM dot matrix.
    _record(
        "ward.highlight.vinyl_platter.foreground",
        "brightens the vinyl platter when turntable manipulation is the focus and viewers should watch the spin",
    ),
    _record(
        "ward.highlight.hardm_dot_matrix.pulse",
        "pulses the HARDM dot matrix when signal density bursts so viewers see the system reading itself",
    ),
    _record(
        "ward.highlight.hardm_dot_matrix.foreground",
        "brightens the HARDM dot matrix when system self-perception is the subject of the moment",
    ),
    # Cognition — activity log + music surfacer.
    _record(
        "ward.highlight.activity_variety_log.foreground",
        "brightens the activity variety log when activity legibility itself is the move worth showing viewers",
    ),
    _record(
        "ward.highlight.activity_variety_log.dim",
        "dims the activity variety log when current activity is sustained and meta-legibility would distract",
    ),
    _record(
        "ward.highlight.music_candidate_surfacer.foreground",
        "brightens the music candidate surfacer when track-selection cognition is the subject of the moment",
    ),
    # Director — objectives + structural state.
    _record(
        "ward.highlight.objectives_overlay.foreground",
        "brightens the objectives overlay during research-mode streams when current objective is the subject",
    ),
    _record(
        "ward.highlight.objectives_overlay.dim",
        "dims the objectives overlay during expressive moments when research framing would cool the energy",
    ),
    _record(
        "ward.highlight.structural_director.pulse",
        "pulses the structural director ward when long-horizon scene direction shifts and the shift is content",
    ),
    # Perception — sierpinski geometry.
    _record(
        "ward.highlight.sierpinski.pulse",
        "pulses the Sierpinski geometry layer when a fractal-burst beat fits the moment's rhythmic register",
    ),
    _record(
        "ward.highlight.sierpinski.foreground",
        "brightens the Sierpinski geometry layer when geometric expression is the subject of the move",
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


# ── Transition affordances ────────────────────────────────────────────────
# Phase 7 of preset-variety-plan (#166). Recruited per chain change
# alongside the preset/family pick — doubles chain-level vocabulary
# without enlarging the within-preset corpus. Implementations live in
# ``agents/studio_compositor/transition_primitives.PRIMITIVES`` and
# share a common ``(out, in_g, writer, sleep)`` signature.

_TRANSITION: list[CapabilityRecord] = [
    _record(
        "transition.fade.smooth",
        "smoothly fades the outgoing scene to black and the incoming scene up over about a second, "
        "the gentlest hand-off and the right move when continuity matters more than punctuation",
    ),
    _record(
        "transition.cut.hard",
        "cuts straight to the next scene with no fade, the sharpest possible move and right "
        "when a sudden shift in subject or energy is the point",
    ),
    _record(
        "transition.netsplit.burst",
        "drops the surface to black for a held beat then snaps the new scene in at full brightness, "
        "the move when the room itself should feel reset before the next idea lands",
    ),
    _record(
        "transition.ticker.scroll",
        "uses a slower-start slower-end S-curve crossfade with a quick perceptual snap through the middle, "
        "the move when the change should feel measured and considered rather than uniform",
    ),
    _record(
        "transition.dither.noise",
        "alternates rapidly between the outgoing and incoming scenes for a brief perceptual flicker "
        "before settling, the move when the change itself wants to feel noisy or uncertain",
    ),
]


# ── GEM (Graffiti Emphasis Mural) affordances ────────────────────────────
# The gem.* IntentFamily literals (``gem.emphasis``, ``gem.composition``)
# in ``shared/director_intent.py`` were added 2026-04-21 to unblock the
# director's Pydantic schema for GEM intents. The catalog records below
# satisfy the family-completeness audit (every IntentFamily must have at
# least one capability) and give the recruitment pipeline targets for
# gem.* impingements emitted by the producer at
# ``agents/hapax_daimonion/gem_producer.py``. The descriptions are
# placeholders — lssh-002 (P0 GEM rendering redesign) will rework the
# actual visual contract; the catalog rows here keep the
# wiring-completeness invariant green in the meantime.

_GEM: list[CapabilityRecord] = [
    _record(
        "gem.emphasis.event-marker",
        "stamps a CP437 graffiti glyph onto the GEM ward to mark the moment "
        "an event lands — the visual punctuation that says 'this just happened'",
    ),
    _record(
        "gem.composition.theme-shift",
        "rewrites the GEM ward's standing composition when the room's subject "
        "shifts — the murals's own way of saying 'we are doing a different thing now'",
    ),
    # gem.spawn (cc-task `director-moves-richness-expansion`): a fresh
    # mural spawn rather than an emphasis or composition shift. Use when
    # the moment warrants its own mark — a phrase, a beat, a punctuation
    # the lower band should carry alongside whatever was there.
    _record(
        "gem.spawn.fresh-mural",
        "mints a new CP437 graffiti onto the lower band when a phrase, beat, "
        "or punctuation warrants its own mark — distinct from modulating an "
        "existing mural; this is the surface authoring a new fragment from scratch",
    ),
]


# ── Composition reframe affordances ───────────────────────────────────────
# Parametric reframe of the active hero camera. Distinct from camera.hero
# (which swaps which camera is foregrounded) — composition.reframe modulates
# the SAME camera's crop / zoom / position_offset envelope so the framing
# itself shifts without a cut. Operator constraint (cc-task
# `director-moves-richness-expansion`): NO presets, parametric only.

_COMPOSITION_REFRAME: list[CapabilityRecord] = [
    _record(
        "composition.reframe.tighten",
        "tightens the active hero camera's framing — pulls in toward the subject "
        "without swapping cameras, the move when the moment wants closer attention "
        "on what is already on screen",
    ),
    _record(
        "composition.reframe.widen",
        "widens the active hero camera's framing — pulls back to give the subject "
        "more air, the move when the moment wants context around what is on screen",
    ),
    _record(
        "composition.reframe.recompose",
        "shifts the active hero camera's framing center — the same subject viewed "
        "from a re-balanced composition, the move when the visual balance has drifted "
        "and a small spatial reset is the right gesture",
    ),
]


# ── Pace / tempo shift affordances ────────────────────────────────────────
# Parametric shift of the surface's effective cadence. Slows or accelerates
# ward emphasis decay, transition timing, narrative-tick perceptual cadence.
# Writes to /dev/shm/hapax-compositor/pace-state.json so cadence-aware
# consumers (homage choreographer, ward animation, structural director)
# can pick up the multiplier on their next tick boundary.

_PACE: list[CapabilityRecord] = [
    _record(
        "pace.tempo_shift.slow",
        "slows the room's effective tempo — extends emphasis windows, lengthens "
        "transition timing, the move when the moment wants to breathe and "
        "the room is moving faster than it needs to",
    ),
    _record(
        "pace.tempo_shift.quicken",
        "quickens the room's effective tempo — shortens emphasis windows, snaps "
        "transition timing tighter, the move when the moment is building heat and "
        "the surface should pick up its step to match",
    ),
    _record(
        "pace.tempo_shift.steady",
        "settles the room's effective tempo back to baseline — neither slow nor "
        "quick, the move when prior pacing has run its course and the surface "
        "should return to its standing rhythm",
    ),
]


# ── Mood / tone pivot affordances ─────────────────────────────────────────
# Parametric color / warmth / saturation pivot. Distinct from preset.bias
# (operator forbids preset selection): mood.tone_pivot modulates the
# per-pass uniform overrides directly — the generative substrate keeps
# running, only the parametric color envelope shifts. Writes to the
# imagination uniforms.json override surface so the next reverie tick
# picks up the warmth / saturation deltas.

_MOOD: list[CapabilityRecord] = [
    _record(
        "mood.tone_pivot.warmer",
        "warms the room's color register — pushes the active uniforms toward "
        "warmer hue and slightly higher saturation, the move when the moment "
        "wants tenderness or familiarity in the visual register",
    ),
    _record(
        "mood.tone_pivot.cooler",
        "cools the room's color register — pulls the active uniforms toward "
        "cooler hue and slightly lower saturation, the move when the moment "
        "wants reflection or distance in the visual register",
    ),
    _record(
        "mood.tone_pivot.brighten",
        "brightens the surface's overall luminance — lifts the master opacity "
        "and pushes mid-tones up, the move when the room has dimmed past what "
        "the moment calls for",
    ),
    _record(
        "mood.tone_pivot.deepen",
        "deepens the surface's tonal contrast — pulls mid-tones down and lets "
        "highlights breathe, the move when the moment wants weight rather than "
        "bright energy",
    ),
]


# ── Programme beat advance affordance ─────────────────────────────────────
# Signals the active programme's narrative beat should advance. Consumer
# is the programme manager (agents/programme_manager.py) — advancing a
# beat is structural content programming, not visual composition. The
# director emits this when the current programme has run its course at
# a perceptual level (sustained activity match, narrative arc complete,
# operator state shifted away from the programme's design).

_PROGRAMME: list[CapabilityRecord] = [
    _record(
        "programme.beat_advance.next",
        "marks the active programme's narrative beat as run-its-course and "
        "ready to advance — a structural cue the programme manager picks up "
        "to walk the show plan forward, distinct from any visual move",
        medium="notification",
    ),
]


# ── Director parametric vocabulary tranche 2 ──────────────────────────────
# Operator directive: NO PRESETS. These are envelope-level primitives:
# recruitment resolves a capability, and the compositor writes bounded
# parameter targets for downstream consumers to ease into.

_INTENSITY_SURGE: list[CapabilityRecord] = [
    _record(
        "intensity.surge.lift",
        "temporarily lifts all nine visual-chain dimensions together while keeping "
        "every node parameter inside its authored envelope — a controlled rise in "
        "visual energy, not a preset jump",
    ),
    _record(
        "intensity.surge.crest",
        "briefly crests all nine visual-chain dimensions for a punctuation beat, "
        "then releases through bounded node parameters so the surface swells "
        "without changing preset family",
    ),
]

_SILENCE_INVITATION: list[CapabilityRecord] = [
    _record(
        "silence.invitation.hold",
        "invites a silent hold by easing narration, motion, chrome, and visual-chain "
        "dimensions down together — the surface pauses without becoming inactive",
    ),
    _record(
        "silence.invitation.soft",
        "softens the expressive surfaces for a quiet invitation rather than a full "
        "hold, preserving a low breathing cadence under bounded parameters",
    ),
]

_CHROME_DENSITY: list[CapabilityRecord] = [
    _record(
        "chrome.density.sparser",
        "thins ward chrome and diagnostic density so primary content has more air, "
        "implemented as alpha, spacing, and contrast envelopes",
    ),
    _record(
        "chrome.density.baseline",
        "returns ward chrome density to its middle register after a sparse or dense "
        "moment has run its course",
    ),
    _record(
        "chrome.density.denser",
        "densifies ward chrome when system legibility itself is the subject, using "
        "bounded alpha, contrast, and spacing envelopes rather than any preset",
    ),
]

_ATTENTION_REFOCUS: list[CapabilityRecord] = [
    _record(
        "attention.refocus.overhead",
        "softly reweights attention toward the overhead hardware camera without "
        "cutting hero focus — a salience envelope across camera weights",
    ),
    _record(
        "attention.refocus.synths-brio",
        "softly reweights attention toward the synthesizer camera while keeping "
        "other cameras alive in the mix",
    ),
    _record(
        "attention.refocus.operator-brio",
        "softly reweights attention toward the operator camera for conversational "
        "or reaction emphasis without forcing a hard camera swap",
    ),
    _record(
        "attention.refocus.desk-c920",
        "softly reweights attention toward the desk camera when reading, writing, "
        "or code work should pull visual weight",
    ),
    _record(
        "attention.refocus.room-c920",
        "softly reweights attention toward the room camera for ambient overview "
        "while preserving secondary camera context",
    ),
    _record(
        "attention.refocus.room-brio",
        "softly reweights attention toward the room BRIO camera for an alternate "
        "ambient view without collapsing the camera mix",
    ),
    _record(
        "attention.refocus.reset",
        "settles camera attention weights back to an even baseline after a soft "
        "refocus envelope has run its course",
    ),
]


# YouTube telemetry impingements (ytb-005, #1311). The youtube.telemetry
# IntentFamily is a downstream-only signal emitted by the analytics tailer
# onto /dev/shm/hapax-dmn/impingements.jsonl. Per feedback_no_expert_system_rules,
# there is no dispatcher in compositional_consumer; the affordance pipeline
# is the sole consumer. These catalog rows keep family-completeness green so
# the pipeline can match on the family even before specific producers are
# wired. The emitter publishes three salience kinds (spike / drop / stale)
# per agents/youtube_telemetry/salience.py.

_YOUTUBE_TELEMETRY: list[CapabilityRecord] = [
    _record(
        "youtube.telemetry.spike-response",
        "warms the room's pace when live viewers surge — the compositor "
        "picks up its step to match the moment's heat without announcing it",
    ),
    _record(
        "youtube.telemetry.drop-retreat",
        "settles the room into a quieter register when live viewers fall "
        "away — the stream hears the room empty and lets the air in",
    ),
]


# ── Node-patch affordances (chain composition) ────────────────────────────
# Architectural fix per researcher audit + operator memory
# `feedback_no_presets_use_parametric_modulation`: the system architecture
# mandates "constrained algorithmic parametric modulation + chain composition
# (transition primitives + affordance-recruited node add/remove). Director
# NEVER picks a preset." The `GraphPatch` type at
# `agents/effect_graph/types.py:85-89` had zero callers — the architecturally-
# correct chain mutation primitive was unwired.
#
# These capabilities fire the chain-composition primitive: instead of
# swapping between 30 fixed preset graphs (the dumb anti-pattern), the
# pipeline recruits surgical add/remove plus structural compose/fork/
# merge/route operations against the live graph. The dispatcher in
# `agents/studio_compositor/compositional_consumer.dispatch_node_patch`
# records the recruitment; `agents/studio_compositor/graph_patch_consumer`
# applies the resulting `GraphPatch` to the live `EffectGraph` and writes
# the patched graph as a mutation file.
#
# Descriptions are Gibson-verb cognitive-function (not implementation
# details). The pipeline cosine-matches impingement narratives against
# these descriptions to recruit the right node for the moment.

_NODE_PATCH: list[CapabilityRecord] = [
    # Five `node.add.<type>` capabilities (the operator-mandated minimum
    # of 5). Each capability description names the perceptual register
    # the node opens up, never the shader's implementation language.
    _record(
        "node.add.halftone",
        "opens a printed-newsprint register — adds a half-tone dot pattern that "
        "lets the surface feel inked rather than rendered, the move when the "
        "moment wants a tactile press-print quality",
    ),
    _record(
        "node.add.kaleidoscope",
        "opens a mirrored-reflection register — adds a kaleidoscopic fold so "
        "the surface multiplies its content into rotational symmetry, the "
        "move when the moment wants prismatic recursion",
    ),
    _record(
        "node.add.glitch_block",
        "opens a digital-tear register — adds blocky data corruption that lets "
        "the surface feel like a broken transmission, the move when the "
        "moment wants disrupted signal as content",
    ),
    _record(
        "node.add.slitscan",
        "opens a temporal-slice register — adds a horizontal time-shear so "
        "different image rows show different moments, the move when the "
        "moment wants visible time-stretching",
    ),
    _record(
        "node.add.fluid_sim",
        "opens a liquid-motion register — adds a fluid simulation layer that "
        "lets the surface flow and pool, the move when the moment wants "
        "physical-substance behavior in the rendering",
    ),
    # One `node.remove.<role>` capability — the satellite cleanup move.
    # Removes the most-recently-added satellite node from the chain.
    _record(
        "node.remove.last_satellite",
        "closes the most-recently-opened register — removes the last satellite "
        "node added to the chain so the surface settles back toward its "
        "core vocabulary, the move when the moment has moved on from a "
        "transient effect",
    ),
    _record(
        "node.compose.color,drift",
        "binds color and spatial drift into one composite gesture — the surface "
        "keeps both registers audible at once instead of treating tone and "
        "motion as separate steps",
    ),
    _record(
        "node.fork.fb",
        "opens a parallel feedback branch — duplicates the trace-bearing "
        "register so one path can continue while another path is prepared for "
        "a later merge",
    ),
    _record(
        "node.merge.fb,fork_fb",
        "gathers two feedback branches into a single downstream stream — the "
        "surface resolves parallel echoes into one legible blended passage "
        "when the moment wants convergence",
    ),
    _record(
        "node.route.content,out",
        "redirects content toward the output path — changes the chain's "
        "downstream route so recruited material can bypass a settled ending "
        "and arrive more directly",
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
    + _WARD_AFFORDANCES
    + _HOMAGE_AFFORDANCES
    + _TRANSITION
    + _GEM
    + _COMPOSITION_REFRAME
    + _PACE
    + _MOOD
    + _PROGRAMME
    + _INTENSITY_SURGE
    + _SILENCE_INVITATION
    + _CHROME_DENSITY
    + _ATTENTION_REFOCUS
    + _YOUTUBE_TELEMETRY
    + _NODE_PATCH
)


def by_family(family: str) -> list[CapabilityRecord]:
    """All capabilities whose name starts with ``family + '.'``."""
    prefix = family.rstrip(".") + "."
    return [c for c in COMPOSITIONAL_CAPABILITIES if c.name.startswith(prefix)]


def capability_names() -> set[str]:
    return {c.name for c in COMPOSITIONAL_CAPABILITIES}
