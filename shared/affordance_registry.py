"""Centralized affordance registry — Gibson-verb taxonomy for the entire system.

Every affordance the system can recruit lives here. Nine perceptual domains
plus shader nodes, content affordances, and legacy bridge entries.

Theoretical status: pragmatic Roschian categorization of the operator's niche.
Domains are prototypical centers of a radial category system (Lakoff 1987),
not exhaustive containers. The concentric spatial structure (space → env → world)
maps to Schutz's phenomenological zones of reach. The three-level structure
(domain → affordance → instance) follows Rosch's basic-level categories (1978).
Competitive recruitment across domains mirrors Cisek's affordance competition
hypothesis (2007). See spec §6 for full theoretical analysis.
"""

from shared.affordance import CapabilityRecord, ContentRisk, MonetizationRisk, OperationalProperties

_PUBLIC_MONETIZATION_REASON = (
    "Operator-owned or generated local system output; no third-party monetizable source is "
    "introduced by this capability."
)
_PUBLIC_CONTENT_REASON = (
    "Operator-owned, generated, or hardware-captured local studio output; tier_0_owned for "
    "broadcast provenance."
)
_PUBLIC_RIGHTS_REF = "rights:operator-owned-local-system-output"
_PUBLIC_PROVENANCE_REF = "provenance:capability-registry-local-studio-output"
_PUBLIC_EVIDENCE_REFS = (
    "docs/superpowers/specs/2026-04-29-world-capability-surface-parent-spec.md",
)


def _public_operational(
    *,
    requires_gpu: bool = False,
    requires_network: bool = False,
    latency_class: str = "fast",
    persistence: str = "none",
    medium: str | None = None,
    consent_required: bool = False,
    priority_floor: bool = False,
    monetization_risk: MonetizationRisk = "none",
    risk_reason: str | None = _PUBLIC_MONETIZATION_REASON,
    content_risk: ContentRisk = "tier_0_owned",
    content_risk_reason: str | None = _PUBLIC_CONTENT_REASON,
    rights_ref: str | None = _PUBLIC_RIGHTS_REF,
    provenance_ref: str | None = _PUBLIC_PROVENANCE_REF,
    evidence_refs: tuple[str, ...] = _PUBLIC_EVIDENCE_REFS,
) -> OperationalProperties:
    return OperationalProperties(
        requires_gpu=requires_gpu,
        requires_network=requires_network,
        latency_class=latency_class,
        persistence=persistence,
        medium=medium,
        consent_required=consent_required,
        priority_floor=priority_floor,
        public_capable=True,
        monetization_risk=monetization_risk,
        risk_reason=risk_reason,
        content_risk=content_risk,
        content_risk_reason=content_risk_reason,
        rights_ref=rights_ref,
        provenance_ref=provenance_ref,
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# Domain 1: Environment (env.*)
# ---------------------------------------------------------------------------

ENV_AFFORDANCES = [
    CapabilityRecord(
        name="env.weather_conditions",
        description=(
            "Sense current weather to ground atmospheric context and environmental awareness"
        ),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="env.weather_forecast",
        description=(
            "Anticipate coming weather to prepare for environmental shifts and plan accordingly"
        ),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="env.time_of_day",
        description=("Orient to the current time and its rhythmic significance in the daily cycle"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="env.season_phase",
        description=(
            "Sense the seasonal context and its affective qualities for temporal grounding"
        ),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="env.ambient_light",
        description=("Sense ambient illumination level in the workspace for environmental context"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
]

# ---------------------------------------------------------------------------
# Domain 2: Body (body.*)
# ---------------------------------------------------------------------------

BODY_AFFORDANCES = [
    CapabilityRecord(
        name="body.heart_rate",
        description="Sense cardiac rhythm as a ground of physiological arousal and presence",
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="body.heart_variability",
        description=("Sense autonomic balance through heart rate variability for stress detection"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="body.stress_level",
        description=("Sense accumulated physiological stress load from multiple biometric sources"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="body.sleep_quality",
        description=("Recall recent sleep quality to contextualize available energy and attention"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="body.activity_state",
        description=("Sense current physical activity mode including walking sitting and resting"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="body.circadian_phase",
        description=("Sense alignment with the circadian cycle for temporal energy context"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
]

# ---------------------------------------------------------------------------
# Domain 3: Studio (studio.*)
# ---------------------------------------------------------------------------

STUDIO_AFFORDANCES = [
    CapabilityRecord(
        name="studio.midi_beat",
        description=("Synchronize with the musical beat for rhythmic visual and vocal expression"),
        daemon="perception",
        operational=OperationalProperties(latency_class="realtime"),
    ),
    CapabilityRecord(
        name="studio.midi_tempo",
        description=("Sense the current tempo to calibrate temporal dynamics and pacing"),
        daemon="perception",
        operational=OperationalProperties(latency_class="realtime"),
    ),
    CapabilityRecord(
        name="studio.mixer_energy",
        description=("Sense total acoustic energy from the mixer output as presence intensity"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.mixer_bass",
        description=("Sense low-frequency energy as weight and grounding in the sound field"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.mixer_mid",
        description=("Sense midrange presence as warmth and body in the acoustic environment"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.mixer_high",
        description=("Sense high-frequency energy as brightness and air in the sound field"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.desk_activity",
        description=("Sense physical desk engagement through vibration and contact pressure"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.desk_gesture",
        description=(
            "Recognize specific desk gestures including typing tapping drumming and scratching"
        ),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.speech_emotion",
        description=("Sense the emotional quality of detected speech for affective grounding"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="studio.music_genre",
        description=("Sense the current genre of music production for creative context"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="studio.flow_state",
        description=("Sense the degree of creative flow engagement and productive absorption"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="studio.audio_events",
        description=("Sense ambient audio events including applause laughter and background music"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="studio.ambient_noise",
        description=(
            "Sense room-level noise floor from ambient microphone as occupancy and activity proxy"
        ),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    # --- Studio Controls (compositor FX chain) ---
    CapabilityRecord(
        name="studio.activate_preset",
        description="Transform the camera aesthetic by activating a visual effect preset from the library",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.adjust_node_param",
        description="Fine-tune a specific parameter on a shader effect node in the active graph",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.toggle_layer",
        description="Enable or disable a compositor output layer for selective visual routing",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.adjust_palette",
        description="Shift the color palette of a compositor layer adjusting warmth saturation and contrast",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.select_camera",
        description="Choose which camera perspective dominates the studio composition",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.bind_modulation",
        description="Connect a live signal source to a shader parameter for reactive visual modulation",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.add_effect_node",
        description="Insert a new shader effect node into the active compositor graph",
        daemon="compositor",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="studio.remove_effect_node",
        description="Remove a shader effect node from the active compositor graph",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="studio.toggle_recording",
        description="Start or stop recording the composed visual output to disk",
        daemon="compositor",
        operational=OperationalProperties(latency_class="fast"),
    ),
    # CC1: stream-as-affordance. Beta-side registration; the compositor-side
    # RTMP handler is alpha's A7 prerequisite per the 2026-04-12 work-stream
    # split (~/.cache/hapax/relay/context/2026-04-12-work-stream-split.md).
    # consent_required because broadcasting the composed studio visual to a
    # public destination is materially different from local-only routing —
    # axiom interpersonal_transparency requires explicit consent before any
    # outbound transmission of room/operator imagery.
    CapabilityRecord(
        name="studio.toggle_livestream",
        description=(
            "Begin or end broadcasting the composed studio visual to a live streaming destination"
        ),
        daemon="compositor",
        operational=_public_operational(latency_class="slow", consent_required=True),
    ),
    # --- Output Destinations ---
    CapabilityRecord(
        name="studio.output_snapshot",
        description="Capture the current effected frame as a high-quality still image",
        daemon="compositor",
        operational=_public_operational(latency_class="fast", medium="visual"),
    ),
    CapabilityRecord(
        name="studio.output_fullscreen",
        description="Display the composed visual fullscreen with overlay controls for monitoring",
        daemon="compositor",
        operational=_public_operational(latency_class="fast", medium="visual"),
    ),
    CapabilityRecord(
        name="studio.output_record",
        description="Route the composed visual to persistent disk recording as video segments",
        daemon="compositor",
        operational=_public_operational(latency_class="fast"),
    ),
    # Re-Splay Homage Ward — Dirtywave M8 LCD reveal. cc-task
    # re-splay-homage-ward-m8 Phase 4. Recruitment is narrative-first +
    # presence-gated: the ward is only recruitable when m8c-hapax has
    # written a recent frame to /dev/shm/hapax-sources/m8-display.rgba
    # (camera_pipeline checks via the source's heartbeat); director-tick
    # impingement narratives mentioning instrument / sequencer / tracker /
    # drum-machine / synth / live-parameter concepts drive recruitment.
    # No auto-on-plug per feedback_no_expert_system_rules + per
    # project_programmes_enable_grounding (programmes can boost via
    # capability_bias_multiplier but never pre-determine appearance).
    CapabilityRecord(
        name="studio.m8_lcd_reveal",
        description=(
            "Reveal the Dirtywave M8's LCD display in the broadcast composite "
            "when the instrument is the subject of attention"
        ),
        daemon="compositor",
        operational=_public_operational(
            latency_class="fast",
            medium="visual",
            consent_required=False,
        ),
    ),
    # cc-task m8-remote-button-control-daemon. Hardware-actuation
    # affordance (buttons, keyjazz, theme, display reset). No PII —
    # button presses don't carry operator-identifying data — so
    # consent_required=False per the cc-task spec.
    CapabilityRecord(
        name="studio.m8_remote_control",
        description=(
            "Actuate the Dirtywave M8's buttons and synth voice via serial "
            "to navigate UI, queue songs, or audition notes programmatically"
        ),
        daemon="m8_control",
        operational=_public_operational(
            latency_class="realtime",
            medium="action",
            consent_required=False,
        ),
    ),
    # cc-task m8-song-queue-control. Symbolic-name → button-sequence
    # dispatcher built on m8_remote_control. Recruitment can route
    # "queue tonally-aligned M8 set" to this affordance with a
    # project_name argument.
    CapabilityRecord(
        name="studio.m8_song_queue",
        description=(
            "Queue a Dirtywave M8 project by symbolic name so the next "
            "chain swap loads a musically-aligned set automatically"
        ),
        daemon="m8_control",
        operational=_public_operational(
            latency_class="fast",
            medium="action",
            consent_required=False,
        ),
    ),
]

# ---------------------------------------------------------------------------
# Domain 4: Space (space.*)
# ---------------------------------------------------------------------------

SPACE_AFFORDANCES = [
    CapabilityRecord(
        name="space.ir_presence",
        description=("Sense whether a person occupies the room via infrared body heat detection"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="space.ir_hand_zone",
        description=("Sense where hands are active in the workspace for gesture context"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="space.ir_motion",
        description=("Sense movement dynamics in the room for activity level awareness"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="space.overhead_perspective",
        description=(
            "Observe workspace from above providing spatial context for physical activity"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="fast", medium="visual"),
    ),
    CapabilityRecord(
        name="space.desk_perspective",
        description=("Observe the operator's face hands and immediate work surface at close range"),
        daemon="reverie",
        operational=_public_operational(latency_class="fast", medium="visual"),
    ),
    CapabilityRecord(
        name="space.operator_perspective",
        description=("Observe the operator directly capturing presence and expression"),
        daemon="reverie",
        operational=_public_operational(latency_class="fast", medium="visual"),
    ),
    CapabilityRecord(
        name="space.room_occupancy",
        description=("Sense the number of persons present in the room via multi-camera detection"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="space.gaze_direction",
        description=("Sense where the operator is looking for attentional focus context"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="space.posture",
        description=("Sense the operator's physical posture for engagement and comfort context"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="space.scene_objects",
        description=("Sense what objects are visible in the environment for spatial context"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="space.presence_probability",
        description=(
            "Sense Bayesian posterior probability of operator presence fused from all available signals"
        ),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="space.bt_proximity",
        description=(
            "Sense whether the operator's watch is physically nearby via Bluetooth connection state"
        ),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
]

# ---------------------------------------------------------------------------
# Domain 5: Digital Life (digital.*)
# ---------------------------------------------------------------------------

DIGITAL_AFFORDANCES = [
    CapabilityRecord(
        name="digital.active_application",
        description=("Sense which application the operator is focused on for workflow context"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="digital.workspace_context",
        description=("Sense the current desktop workspace arrangement and layout"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="digital.communication_cadence",
        description=(
            "Sense the operator's email and message send-receive rhythm without person details"
        ),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="digital.calendar_density",
        description=("Sense how packed the operator's schedule is today for commitment awareness"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="digital.next_meeting_proximity",
        description=("Sense time until the next scheduled commitment for urgency context"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="digital.git_activity",
        description=("Sense the operator's recent coding commit patterns for work rhythm"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="digital.clipboard_intent",
        description=("Sense what kind of content was just copied for workflow context"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="digital.keyboard_activity",
        description=(
            "Sense physical keyboard and mouse engagement from raw HID events for presence grounding"
        ),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="digital.llm_activity_class",
        description=(
            "Sense LLM-classified operator activity and flow state from local model inference"
        ),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
]

# ---------------------------------------------------------------------------
# Domain 6: Knowledge (knowledge.*)
# ---------------------------------------------------------------------------

KNOWLEDGE_AFFORDANCES = [
    CapabilityRecord(
        name="knowledge.vault_search",
        description=(
            "Search the operator's personal knowledge base for relevant notes and concepts"
        ),
        daemon="recall",
        operational=_public_operational(
            latency_class="slow",
            medium="visual",
            monetization_risk="low",
            risk_reason="Operator-authored vault snippets can be displayed, but visible text still gets low-risk catalog scrutiny before broadcast.",
        ),
    ),
    CapabilityRecord(
        name="knowledge.episodic_recall",
        description=(
            "Recall and visualize past experiences similar to the current moment from memory"
        ),
        daemon="recall",
        operational=_public_operational(
            latency_class="slow",
            medium="visual",
            monetization_risk="low",
            risk_reason="Operator episodic memory visualization is first-party, but visible narrative text remains low-risk public surface material.",
        ),
    ),
    CapabilityRecord(
        name="knowledge.profile_facts",
        description=("Recall known facts about the operator's preferences patterns and history"),
        daemon="recall",
        operational=_public_operational(
            latency_class="slow",
            medium="visual",
            monetization_risk="low",
            risk_reason="Operator profile facts are first-party, but visible text remains low-risk public surface material.",
        ),
    ),
    CapabilityRecord(
        name="knowledge.document_search",
        description=("Search ingested documents and notes for relevant knowledge on a topic"),
        daemon="recall",
        operational=_public_operational(
            latency_class="slow",
            medium="visual",
            monetization_risk="medium",
            risk_reason="Ingested document snippets can include third-party or copyrighted text; Programme opt-in required before visual broadcast.",
            content_risk="tier_2_provenance_known",
            content_risk_reason="Document corpus provenance is known at ingest time but may include third-party materials; requires Programme content opt-in.",
            rights_ref="rights:document-ingest-provenance-required",
            provenance_ref="provenance:rag-ingest-document-source",
        ),
    ),
    CapabilityRecord(
        name="knowledge.web_search",
        description=("Search the open web for current information and real-time knowledge"),
        daemon="discovery",
        operational=OperationalProperties(
            latency_class="slow",
            requires_network=True,
            consent_required=True,
            monetization_risk="medium",
            risk_reason="Third-party web content; may contain brand-name / trademarked / copyrighted text. Requires Programme opt-in for broadcast surfaces.",
        ),
    ),
    CapabilityRecord(
        name="knowledge.wikipedia",
        description="Look up encyclopedic knowledge on a topic from Wikipedia",
        daemon="discovery",
        operational=OperationalProperties(
            latency_class="slow",
            requires_network=True,
            consent_required=True,
            monetization_risk="low",
            risk_reason="Wikipedia text is CC-BY-SA licensed; monetization-safe for short excerpts but flag low for prudence.",
        ),
    ),
    CapabilityRecord(
        name="knowledge.image_search",
        description="Find relevant images from the open web for visual reference",
        daemon="discovery",
        operational=_public_operational(
            latency_class="slow",
            requires_network=True,
            consent_required=True,
            medium="visual",
            monetization_risk="high",
            risk_reason="Open-web image search returns arbitrary third-party imagery; Content-ID fingerprint risk + potential graphic content. Blocked unconditionally from broadcast; operator must resolve images via a curated pipeline instead.",
            content_risk="tier_4_risky",
            content_risk_reason="Open-web image results have unknown rights and visual fingerprints; broadcast egress is blocked.",
            rights_ref="rights:open-web-image-search-unlicensed",
            provenance_ref="provenance:open-web-image-search",
        ),
    ),
]

# ---------------------------------------------------------------------------
# Domain 7: Social (social.*)
# ---------------------------------------------------------------------------

SOCIAL_AFFORDANCES = [
    CapabilityRecord(
        name="social.phone_notifications",
        description=("Sense incoming phone notification activity level for awareness"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="social.phone_battery",
        description="Sense the phone's charge state for device awareness",
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="social.phone_media",
        description="Sense what media is currently playing on the phone",
        daemon="perception",
        operational=OperationalProperties(
            latency_class="slow",
            monetization_risk="medium",
            risk_reason="Phone media metadata (song/podcast/video titles) may surface third-party copyrighted titles; broadcasting those titles is generally safe (fair use) but Programme should opt in for confidence.",
        ),
    ),
    CapabilityRecord(
        name="social.sms_activity",
        description=(
            "Sense unread message count for communication awareness without identifying persons"
        ),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="social.meeting_context",
        description=("Sense the nature of the current or next meeting topic for preparation"),
        daemon="perception",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="social.phone_call",
        description=("Sense whether a phone call is active or incoming for interruption awareness"),
        daemon="perception",
        operational=OperationalProperties(latency_class="fast"),
    ),
]

# ---------------------------------------------------------------------------
# Domain 8: System (system.*)
# ---------------------------------------------------------------------------

SYSTEM_AFFORDANCES = [
    CapabilityRecord(
        name="system.health_ratio",
        description="Sense overall infrastructure health for operational awareness",
        daemon="system",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="system.gpu_pressure",
        description="Sense GPU memory utilization pressure for resource awareness",
        daemon="system",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="system.error_rate",
        description=("Sense the current error frequency across all running services"),
        daemon="system",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="system.exploration_deficit",
        description=("Sense the system's accumulated need for novelty and new stimulation"),
        daemon="system",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="system.stimmung_stance",
        description=("Sense the overall attunement state governing system behavior"),
        daemon="system",
        operational=OperationalProperties(latency_class="fast"),
    ),
    CapabilityRecord(
        name="system.cost_pressure",
        description=("Sense LLM spending rate relative to budget for cost awareness"),
        daemon="system",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="system.drift_signals",
        description=("Sense accumulated system drift from intended operational state"),
        daemon="system",
        operational=OperationalProperties(latency_class="slow"),
    ),
    CapabilityRecord(
        name="system.notify_operator",
        description="Alert the operator to urgent or noteworthy events via push notification",
        daemon="system",
        operational=_public_operational(latency_class="fast", medium="notification"),
    ),
]

# ---------------------------------------------------------------------------
# Domain 9: Open World (world.*)
# ---------------------------------------------------------------------------

WORLD_AFFORDANCES = [
    CapabilityRecord(
        name="world.news_headlines",
        description="Sense current news headlines for broad situational awareness",
        daemon="discovery",
        operational=OperationalProperties(
            latency_class="slow",
            requires_network=True,
            consent_required=True,
            monetization_risk="medium",
            risk_reason="Third-party headlines may include brand-name / political / graphic content. Programme opt-in required for any broadcast surface.",
        ),
    ),
    CapabilityRecord(
        name="world.weather_elsewhere",
        description=("Sense weather in another location the operator is thinking about"),
        daemon="discovery",
        operational=OperationalProperties(
            latency_class="slow", requires_network=True, consent_required=True
        ),
    ),
    CapabilityRecord(
        name="world.music_metadata",
        description=("Look up metadata about a track or artist from music databases"),
        daemon="discovery",
        operational=OperationalProperties(
            latency_class="slow", requires_network=True, consent_required=True
        ),
    ),
    CapabilityRecord(
        name="world.astronomy",
        description=("Sense current celestial events including moon phase and planet visibility"),
        daemon="discovery",
        operational=OperationalProperties(
            latency_class="slow", requires_network=True, consent_required=True
        ),
    ),
]

# ---------------------------------------------------------------------------
# Shader Nodes (node.*)
# ---------------------------------------------------------------------------

SHADER_NODE_AFFORDANCES = [
    CapabilityRecord(
        name="node.noise_gen",
        description=(
            "Generate continuous procedural texture as the visual field's ambient substrate"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.reaction_diffusion",
        description=("Produce self-organizing emergent patterns that respond to regime shifts"),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.colorgrade",
        description=("Transform the visual field's color palette warmth and atmospheric tone"),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.drift",
        description="Displace spatial patterns with gentle coherent warping",
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.breathing",
        description=("Modulate rhythmic expansion and contraction to convey life cadence"),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.feedback",
        description=("Sustain temporal persistence and afterimage as a dwelling trace"),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.content_layer",
        description="Materialize imagination content onto the visual surface",
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.postprocess",
        description=("Enclose the final composition with vignette sediment and grading"),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.fluid_sim",
        description=(
            "Propel directional flow with inertia and viscous vorticity for "
            "Navier-Stokes liquid-current and smoke-plume register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.trail",
        description=(
            "Accumulate motion history as temporal thickness from velocity for "
            "comet-tail brush-stroke and persistence-of-vision register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.voronoi_overlay",
        description=(
            "Partition space into organic cellular boundaries and territories for "
            "geological-strata mosaic-tessellation and cellular-membrane register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.echo",
        description=(
            "Replicate discrete temporal copies as ghosting and fading repetition for "
            "afterimage spectral-trace and dub-delay register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    # yt-content-reverie-sierpinski-separation Phase 1C (2026-04-21).
    # Sierpinski tiles a YouTube frame inside a triangular composition
    # at scene cut-points. Tagged ``slot_family: "youtube_pip"`` in the
    # shader manifest so the Rust runtime (Phase 1B) binds only YT-slot
    # sources here — Reverie's narrative substrate stays unbled.
    # Recruitment via the affordance pipeline produces the
    # ``sat_sierpinski_content`` graph node per CLAUDE.md § Reverie
    # Vocabulary Integrity.
    CapabilityRecord(
        name="node.sierpinski_content",
        description=(
            "Tile a YouTube frame inside a Sierpinski triangular composition "
            "during scene cut-points to feature broadcast video without "
            "letting it bleed into the generative substrate"
        ),
        daemon="reverie",
        operational=_public_operational(
            latency_class="realtime",
            medium="visual",
            monetization_risk="high",
            risk_reason="Sierpinski can tile YouTube frames; third-party video fingerprints are blocked until source provenance is explicit.",
            content_risk="tier_4_risky",
            content_risk_reason="YouTube frame content is external video unless a later provenance gate proves otherwise.",
            rights_ref="rights:youtube-frame-unverified",
            provenance_ref="provenance:youtube-slot-unverified",
        ),
    ),
    # cc-task wgsl-node-recruitment-investigation (audit U7, 2026-05-03):
    # Pre-this-PR coverage was 13 of 60 WGSL nodes registered as
    # affordances — the other 47 lived on disk but were unrecruitable
    # because the AffordancePipeline cosine-similarity stage had no
    # Qdrant entries to find. The 12 entries below add the most
    # thematically-distinct of those 47 so director impingements with
    # narratives like "lo-fi VHS texture" or "ASCII glitch" can recruit
    # something instead of falling back to the bare 8-pass core. Each
    # description is tuned to be cosine-similarity-discoverable for the
    # impingement vocabulary (visual register, perceptual effect, mood)
    # rather than being a literal restatement of the shader algorithm.
    CapabilityRecord(
        name="node.bloom",
        description=(
            "Suffuse the visual field with luminous halation that lifts highlights "
            "into a soft glowing bloom for warm cinematic atmosphere"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.vhs",
        description=(
            "Lay down analog VHS tape texture with chroma bleed scanline noise "
            "and head-switching artifacts for nostalgic lo-fi register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.halftone",
        description=(
            "Reduce the visual field to printed dot-matrix halftone screen "
            "evoking newsprint comic and risograph publication aesthetics"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.kaleidoscope",
        description=(
            "Fold the visual field into kaleidoscopic radial mirror symmetry "
            "for psychedelic mandala-like patterning"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.scanlines",
        description=(
            "Overlay CRT scanlines and phosphor mask to evoke retro television "
            "broadcast and arcade monitor texture"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.ascii",
        description=(
            "Render the visual field as luminance-mapped ASCII typography "
            "for terminal-aesthetic text-art register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.glitch_block",
        description=(
            "Inject blocky datamosh corruption and macroblock displacement "
            "for digital-decay glitch register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.pixsort",
        description=(
            "Sort pixel rows and columns by luminance to produce flowing "
            "stratified bands of color for generative-art register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.kuwahara",
        description=(
            "Smooth the visual field into painterly impressionist regions "
            "with edge-preserving anisotropic flattening"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.dither",
        description=(
            "Quantize the color palette with ordered Bayer dithering "
            "for limited-palette retro-computing aesthetic"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.palette_remap",
        description=(
            "Remap the visual field to a constrained color palette for "
            "stylized graphic-design register and mood enforcement"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.edge_detect",
        description=(
            "Reveal the visual field as line-art contour drawing emphasizing "
            "structural boundaries for diagrammatic-sketch register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    # cc-task wgsl-node-affordance-coverage-batch-2 (Phase 2 of audit U7,
    # 2026-05-03): raise SHADER_NODE_AFFORDANCES coverage 25 → 35 by
    # registering 10 more thematically-distinct nodes. Same description
    # convention as batch 1: name the visual register / mood / aesthetic
    # the impingement vocabulary uses, not the shader algorithm.
    CapabilityRecord(
        name="node.chroma_key",
        description=(
            "Mask out a target color band so layered content shows through "
            "for green-screen compositing and selective-region reveal"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.chromatic_aberration",
        description=(
            "Split the visual field into RGB channel offsets evoking lens-fringing "
            "optical-imperfection and dreamlike refractive register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.circular_mask",
        description=(
            "Vignette the visual field through a circular aperture for telescopic "
            "porthole or surveillance-monitor framing register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.color_map",
        description=(
            "Translate luminance through a gradient lookup table for false-color "
            "thermal imaging and scientific-visualization register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.crossfade",
        description=(
            "Blend smoothly between two visual sources for seamless scene "
            "transitions and temporal layering"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.displacement_map",
        description=(
            "Warp the visual field by a secondary texture's gradients for "
            "liquid-surface heat-haze and dimensional-distortion register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.droste",
        description=(
            "Recurse the visual field into infinite logarithmic spiral self-similarity "
            "for vertiginous mise-en-abyme register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.emboss",
        description=(
            "Render the visual field as raised relief sculpture with directional "
            "lighting for tactile bas-relief and stamped-metal register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.fisheye",
        description=(
            "Bend the visual field through wide-angle hemispherical projection "
            "for security-camera and skateboard-video register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.mirror",
        description=(
            "Reflect the visual field along a symmetry axis for Rorschach-blot "
            "introspective and ritual-symmetry register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    # cc-task wgsl-node-affordance-coverage-batch-3 (Phase 3 of audit U7,
    # 2026-05-03): raise SHADER_NODE_AFFORDANCES coverage 35 → 45 by
    # registering 10 more nodes. Same description convention as prior
    # batches.
    CapabilityRecord(
        name="node.blend",
        description=(
            "Mix two visual sources via configurable blend mode for compositing "
            "layered content with multiply screen overlay or additive register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.diff",
        description=(
            "Compute the absolute difference between two visual sources to surface "
            "motion-edge change-detection register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.thermal",
        description=(
            "Map luminance to thermal infrared palette for body-heat surveillance "
            "and predator-vision register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.tunnel",
        description=(
            "Project the visual field through radial tunnel perspective for "
            "vortex motion-toward-center hypnotic register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.posterize",
        description=(
            "Quantize the visual field into flat tonal regions for screen-print "
            "poster-art and pop-graphic register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.slitscan",
        description=(
            "Smear the visual field along the temporal axis for time-displacement "
            "scanline-trail and motion-stretch register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.waveform_render",
        description=(
            "Trace audio amplitude as oscillographic waveform overlay for "
            "music-visualization and signal-monitoring register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.particle_system",
        description=(
            "Emit and animate particle agents across the visual field for "
            "ember-spark sparkle-flow and dust-cloud register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.invert",
        description=(
            "Negate the visual field to its color complement for darkroom-negative "
            "and inversion-photography register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.strobe",
        description=(
            "Pulse the visual field at high frequency for nightclub-flash and "
            "warning-signal seizure-adjacent register (use sparingly)"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    # cc-task wgsl-node-affordance-coverage-batch-4 (Phase 4 of audit U7,
    # 2026-05-03): close the registration gap. 45 → 60, full coverage of
    # agents/shaders/nodes/*.wgsl.
    CapabilityRecord(
        name="node.grain_bump",
        description=(
            "Overlay film-grain texture as a tactile noise field for analog "
            "celluloid and photographic-print register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.luma_key",
        description=(
            "Mask the visual field by luminance threshold for shadow-mask and "
            "high-key compositing register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.noise_overlay",
        description=(
            "Layer animated noise atop the visual field for static-snow and "
            "broadcast-interference register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.palette_extract",
        description=(
            "Sample dominant colors from the visual field for swatch-extraction "
            "and palette-discovery register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.rutt_etra",
        description=(
            "Extrude scanlines into 3D ridge geometry for analog-video-synthesizer "
            "and topographic-elevation register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.sharpen",
        description=("Boost edge contrast for crisp-detail high-frequency-emphasis register"),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.sierpinski_lines",
        description=(
            "Draw Sierpinski triangular line-art subdivision for fractal-geometry "
            "and recursive-pattern register (companion to sierpinski_content)"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.solid",
        description=(
            "Fill the visual field with a single solid color for backdrop-fill "
            "and color-card register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.stutter",
        description=(
            "Repeat short visual fragments out of sequence for glitch-stutter "
            "and breakcore-rhythmic register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.syrup",
        description=(
            "Slow the visual field's temporal flow as viscous syrupy lag for "
            "underwater-dream and somnambulant register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.threshold",
        description=(
            "Binarize the visual field at a luminance cutoff for stencil-cut "
            "and pure-monochrome high-contrast register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.tile",
        description=(
            "Replicate the visual field as a grid of repeating tiles for "
            "Warhol-pop and CCTV-multiviewer register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.transform",
        description=(
            "Apply affine transform — translate rotate scale — to the visual "
            "field for spatial reorientation"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.vignette",
        description=(
            "Darken the visual field's perimeter into a soft vignette for "
            "intimate-portrait and lens-falloff register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.warp",
        description=(
            "Bend the visual field's geometry through nonlinear warping for "
            "funhouse-mirror and dream-distortion register"
        ),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
]

# ---------------------------------------------------------------------------
# Content affordances
# ---------------------------------------------------------------------------

CONTENT_AFFORDANCES = [
    CapabilityRecord(
        name="content.narrative_text",
        description=(
            "Render imagination narrative as visible text making thought legible"
            " in the visual field"
        ),
        daemon="reverie",
        operational=_public_operational(
            latency_class="slow",
            medium="visual",
            monetization_risk="medium",
            risk_reason="LLM-generated text on visible surface; passes speech_safety but Ring 2 classifier needed for full coverage. Programme opt-in governs broadcast surfaces.",
        ),
    ),
    CapabilityRecord(
        name="content.waveform_viz",
        description=("Sense acoustic energy and render sound as visible waveform shape"),
        daemon="reverie",
        operational=_public_operational(latency_class="fast", medium="visual"),
    ),
    # Phase 2 of yt-content-reverie-sierpinski-separation (2026-04-21).
    # Hapax-authored YT featuring affordance — director impingements at
    # scene cut-points score this above threshold; the reverie mixer
    # dispatches to ``ContentCapabilityRouter.activate_youtube`` which
    # writes ``/dev/shm/hapax-compositor/featured-yt-slot``. The studio
    # compositor's Sierpinski renderer reads that file and elevates the
    # named slot's opacity in the triangular composition. Distinct from
    # Phase 1 which only routes raw bindings — this is the first-class
    # fronting mechanism on par with ward.position, camera.hero, etc.
    CapabilityRecord(
        name="content.yt.feature",
        description=(
            "Elevate a YouTube video thumbnail to attention-peak presence "
            "at a scene cut-point so the broadcast video reads as featured "
            "rather than ambient backdrop"
        ),
        daemon="reverie",
        operational=_public_operational(
            latency_class="fast",
            medium="visual",
            monetization_risk="high",
            risk_reason="Featured YouTube thumbnails/video frames are third-party visual content until a provenance gate proves clearance; blocked unconditionally from broadcast.",
            content_risk="tier_4_risky",
            content_risk_reason="YouTube video visual content has unverified source rights and Content ID risk.",
            rights_ref="rights:youtube-feature-unverified",
            provenance_ref="provenance:youtube-slot-unverified",
        ),
    ),
]

# ---------------------------------------------------------------------------
# GEM (Graffiti Emphasis Mural) affordances — operator-directed 2026-04-19.
# Distinct list (not under CONTENT_AFFORDANCES) so the "all CONTENT_AFFORDANCES
# names start with content." invariant in tests/test_reverie_mixer.py stays
# intact. Both still flow into ALL_AFFORDANCES below for pipeline recruitment.
#
# Hapax authors mural keyframes that land on /dev/shm/hapax-compositor/
# gem-frames.json, picked up by GemCairoSource at the gem-mural-bottom
# surface. See docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md
# and docs/research/2026-04-19-gem-ward-design.md.
# ---------------------------------------------------------------------------

GEM_AFFORDANCES = [
    CapabilityRecord(
        name="gem.emphasis",
        description=(
            "Highlight a fragment of speech or thought with mural-style emphasis "
            "in the lower-band CP437 raster surface; frame the word, hold it, fade it"
        ),
        daemon="hapax_daimonion",
        operational=_public_operational(
            latency_class="fast",
            medium="visual",
            monetization_risk="low",
            risk_reason=(
                "Hapax-authored CP437-only raster; AntiPatternKind enforced "
                "(emoji rejected) + HARDM Pearson <0.6 face-correlation gate at render"
            ),
        ),
    ),
    CapabilityRecord(
        name="gem.composition",
        description=(
            "Compose abstract glyph sequence — ASCII drawings, frame-by-frame "
            "animation, box-draw containers — in the mural surface"
        ),
        daemon="hapax_daimonion",
        operational=_public_operational(
            latency_class="fast",
            medium="visual",
            monetization_risk="low",
            risk_reason=(
                "Hapax-authored CP437-only raster; AntiPatternKind enforced "
                "(emoji rejected) + HARDM Pearson <0.6 face-correlation gate at render"
            ),
        ),
    ),
]

# ---------------------------------------------------------------------------
# Domain 10: Expression (narration.*)
# ---------------------------------------------------------------------------

EXPRESSION_AFFORDANCES = [
    CapabilityRecord(
        name="narration.autonomous_first_system",
        description=(
            "Compose neutral first-system narration grounding observed perceptual"
            " events into TTS-ready prose during operator-absent stretches"
        ),
        daemon="daimonion",
        operational=_public_operational(
            latency_class="slow",
            medium="speech",
            monetization_risk="medium",
            risk_reason="Autonomous LLM narration can produce monetization-sensitive wording; Programme opt-in required for broadcast speech.",
        ),
    ),
]

# ---------------------------------------------------------------------------
# Domain 11: Chat (chat.*) — livestream audience reactivity
# ---------------------------------------------------------------------------

CHAT_AFFORDANCES = [
    CapabilityRecord(
        name="chat.acknowledge_message",
        description=(
            "Acknowledge a livestream chat message with a brief vocal nod"
            " confirming receipt without committing to a full reply"
        ),
        daemon="daimonion",
        operational=_public_operational(
            latency_class="fast",
            medium="speech",
            monetization_risk="low",
            risk_reason=(
                "Brief acknowledgement carries minimal third-party content risk;"
                " operator-voiced TTS over operator-owned broadcast surface."
            ),
        ),
    ),
    CapabilityRecord(
        name="chat.answer_question",
        description=(
            "Compose a short spoken answer to a question posed in livestream"
            " chat grounding it in the current studio context"
        ),
        daemon="daimonion",
        operational=_public_operational(
            latency_class="slow",
            medium="speech",
            monetization_risk="medium",
            risk_reason=(
                "Generated answers can produce monetization-sensitive wording"
                " when the question solicits opinion or third-party content;"
                " Programme opt-in for broadcast speech."
            ),
        ),
    ),
    CapabilityRecord(
        name="chat.tier_suggestion_add",
        description=(
            "Surface a chat-suggested item to the programme tier list as a"
            " candidate without committing to inclusion"
        ),
        daemon="programme",
        operational=_public_operational(
            latency_class="fast",
            persistence="session",
            medium="textual",
        ),
    ),
    CapabilityRecord(
        name="chat.mood_shift",
        description=(
            "Bias the studio compositor preset family toward a mood the chat"
            " is collectively gravitating toward as audience-aware reactivity"
        ),
        daemon="compositor",
        operational=_public_operational(
            latency_class="fast",
            medium="visual",
        ),
    ),
    CapabilityRecord(
        name="chat.hero_swap",
        description=(
            "Swap the camera hero perspective in response to chat directing"
            " attention to a specific studio surface or instrument"
        ),
        daemon="compositor",
        operational=_public_operational(
            latency_class="fast",
            medium="visual",
        ),
    ),
]

# ---------------------------------------------------------------------------
# Legacy bridge entries (pre-dot-namespace names)
# ---------------------------------------------------------------------------

LEGACY_AFFORDANCES = [
    CapabilityRecord(
        name="shader_graph",
        description="Activate shader graph effects from imagination",
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="visual_chain",
        description=("Modulate visual chain from stimmung and evaluative signals"),
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="fortress_visual_response",
        description="Visual pipeline for fortress crisis events",
        daemon="reverie",
        operational=_public_operational(latency_class="realtime", medium="visual"),
    ),
]

# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

AFFORDANCE_DOMAINS: dict[str, list[CapabilityRecord]] = {
    "env": ENV_AFFORDANCES,
    "body": BODY_AFFORDANCES,
    "studio": STUDIO_AFFORDANCES,
    "space": SPACE_AFFORDANCES,
    "digital": DIGITAL_AFFORDANCES,
    "knowledge": KNOWLEDGE_AFFORDANCES,
    "social": SOCIAL_AFFORDANCES,
    "system": SYSTEM_AFFORDANCES,
    "world": WORLD_AFFORDANCES,
    "narration": EXPRESSION_AFFORDANCES,
    "chat": CHAT_AFFORDANCES,
}

ALL_AFFORDANCES: list[CapabilityRecord] = (
    [r for domain in AFFORDANCE_DOMAINS.values() for r in domain]
    + SHADER_NODE_AFFORDANCES
    + CONTENT_AFFORDANCES
    + GEM_AFFORDANCES
    + LEGACY_AFFORDANCES
)
