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

from shared.affordance import CapabilityRecord, OperationalProperties

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
        operational=OperationalProperties(latency_class="fast", medium="visual"),
    ),
    CapabilityRecord(
        name="space.desk_perspective",
        description=("Observe the operator's face hands and immediate work surface at close range"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="fast", medium="visual"),
    ),
    CapabilityRecord(
        name="space.operator_perspective",
        description=("Observe the operator directly capturing presence and expression"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="fast", medium="visual"),
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
        operational=OperationalProperties(latency_class="slow", medium="visual"),
    ),
    CapabilityRecord(
        name="knowledge.episodic_recall",
        description=(
            "Recall and visualize past experiences similar to the current moment from memory"
        ),
        daemon="recall",
        operational=OperationalProperties(latency_class="slow", medium="visual"),
    ),
    CapabilityRecord(
        name="knowledge.profile_facts",
        description=("Recall known facts about the operator's preferences patterns and history"),
        daemon="recall",
        operational=OperationalProperties(latency_class="slow", medium="visual"),
    ),
    CapabilityRecord(
        name="knowledge.document_search",
        description=("Search ingested documents and notes for relevant knowledge on a topic"),
        daemon="recall",
        operational=OperationalProperties(latency_class="slow", medium="visual"),
    ),
    CapabilityRecord(
        name="knowledge.web_search",
        description=("Search the open web for current information and real-time knowledge"),
        daemon="discovery",
        operational=OperationalProperties(
            latency_class="slow", requires_network=True, consent_required=True
        ),
    ),
    CapabilityRecord(
        name="knowledge.wikipedia",
        description="Look up encyclopedic knowledge on a topic from Wikipedia",
        daemon="discovery",
        operational=OperationalProperties(
            latency_class="slow", requires_network=True, consent_required=True
        ),
    ),
    CapabilityRecord(
        name="knowledge.image_search",
        description="Find relevant images from the open web for visual reference",
        daemon="discovery",
        operational=OperationalProperties(
            latency_class="slow",
            requires_network=True,
            consent_required=True,
            medium="visual",
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
        operational=OperationalProperties(latency_class="slow"),
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
        operational=OperationalProperties(latency_class="fast", medium="notification"),
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
            latency_class="slow", requires_network=True, consent_required=True
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
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.reaction_diffusion",
        description=("Produce self-organizing emergent patterns that respond to regime shifts"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.colorgrade",
        description=("Transform the visual field's color palette warmth and atmospheric tone"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.drift",
        description="Displace spatial patterns with gentle coherent warping",
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.breathing",
        description=("Modulate rhythmic expansion and contraction to convey life cadence"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.feedback",
        description=("Sustain temporal persistence and afterimage as a dwelling trace"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.content_layer",
        description="Materialize imagination content onto the visual surface",
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.postprocess",
        description=("Enclose the final composition with vignette sediment and grading"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.fluid_sim",
        description=("Propel directional flow with inertia and viscous vorticity"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.trail",
        description=("Accumulate motion history as temporal thickness from velocity"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.voronoi_overlay",
        description=("Partition space into organic cellular boundaries and territories"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="node.echo",
        description=("Replicate discrete temporal copies as ghosting and fading repetition"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
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
        operational=OperationalProperties(latency_class="slow", medium="visual"),
    ),
    CapabilityRecord(
        name="content.waveform_viz",
        description=("Sense acoustic energy and render sound as visible waveform shape"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="fast", medium="visual"),
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
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="visual_chain",
        description=("Modulate visual chain from stimmung and evaluative signals"),
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    ),
    CapabilityRecord(
        name="fortress_visual_response",
        description="Visual pipeline for fortress crisis events",
        daemon="reverie",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
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
}

ALL_AFFORDANCES: list[CapabilityRecord] = (
    [r for domain in AFFORDANCE_DOMAINS.values() for r in domain]
    + SHADER_NODE_AFFORDANCES
    + CONTENT_AFFORDANCES
    + LEGACY_AFFORDANCES
)
