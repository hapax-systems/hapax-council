"""Pipeline dependency precomputation for VoiceDaemon."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


def precompute_pipeline_deps(daemon: VoiceDaemon) -> None:
    """Precompute pipeline dependencies at startup so session open is instant.

    Called once during daemon init. Tools, consent reader, and callbacks
    are stable across sessions. Only the system prompt needs refreshing
    per session (policy + screen context depend on current environment).
    """
    from agents.hapax_daimonion.conversational_policy import get_policy
    from agents.hapax_daimonion.env_context import serialize_environment
    from agents.hapax_daimonion.perception import EnvironmentState
    from agents.hapax_daimonion.tool_definitions import build_registry

    # Tools (stable across sessions)
    daemon._tool_registry = (
        build_registry(
            guest_mode=False,
            config=daemon.cfg,
            webcam_capturer=getattr(daemon.workspace_monitor, "_webcam_capturer", None),
            screen_capturer=getattr(daemon.workspace_monitor, "_screen_capturer", None),
        )
        if daemon.cfg.tools_enabled
        else build_registry(guest_mode=True)
    )

    # Consent reader (stable, reloads contracts on session start)
    daemon._precomputed_consent_reader = None
    try:
        from agents._consent_reader import ConsentGatedReader

        daemon._precomputed_consent_reader = ConsentGatedReader.create()
    except Exception:
        log.warning("ConsentGatedReader unavailable, proceeding without consent filtering")

    # Callbacks (closures over daemon — stable)
    daemon._env_context_fn = lambda: serialize_environment(
        daemon.perception.latest or EnvironmentState(timestamp=0),
        daemon.workspace_monitor.latest_analysis,
        daemon.gate._ambient_result,
        perception_tier=daemon._perception_tier.value,
        experiment_mode=getattr(daemon, "_experiment_flags", {}).get("experiment_mode", False),
    )
    daemon._ambient_fn = lambda: daemon.gate._ambient_result
    daemon._policy_fn = lambda: get_policy(
        env=daemon.perception.latest,
        guest_mode=daemon.session.is_guest_mode,
        experiment_mode=getattr(daemon, "_experiment_flags", {}).get("experiment_mode", False),
    )

    from agents.hapax_daimonion.context_enrichment import (
        render_dmn,
        render_goals,
        render_health,
        render_nudges,
    )

    daemon._goals_fn = render_goals
    daemon._health_fn = render_health
    daemon._nudges_fn = render_nudges
    daemon._dmn_fn = render_dmn

    # Shared context assembler
    from agents._context import ContextAssembler
    from agents.hapax_daimonion.context_enrichment import (
        _collect_goals,
        _collect_health,
        _collect_nudges,
        set_assembler,
    )

    daemon._context_assembler = ContextAssembler(
        goals_fn=_collect_goals,
        health_fn=_collect_health,
        nudges_fn=_collect_nudges,
        perception_fn=lambda: (
            daemon.perception.latest if hasattr(daemon, "perception") and daemon.perception else {}
        ),
    )
    set_assembler(daemon._context_assembler)

    # Imagination context injection
    from agents.imagination_context import format_imagination_context

    daemon._imagination_fn = format_imagination_context

    # Proactive gate for imagination-driven speech
    from agents.proactive_gate import ProactiveGate

    daemon._proactive_gate = ProactiveGate()
    daemon._last_utterance_time = time.monotonic()

    # Impingement cascade: speech as a recruited capability
    from agents.hapax_daimonion.capability import SPEECH_DESCRIPTION, SpeechProductionCapability

    daemon._speech_capability = SpeechProductionCapability()

    # Affordance pipeline
    from agents._affordance import CapabilityRecord, OperationalProperties
    from agents._affordance_pipeline import AffordancePipeline

    daemon._affordance_pipeline = AffordancePipeline()
    daemon._affordance_pipeline.index_capability(
        CapabilityRecord(
            name="speech_production",
            description=SPEECH_DESCRIPTION,
            daemon="hapax_daimonion",
            operational=OperationalProperties(requires_gpu=True, medium="auditory"),
        )
    )
    daemon._affordance_pipeline.register_interrupt(
        "population_critical", "speech_production", "hapax_daimonion"
    )
    daemon._affordance_pipeline.register_interrupt(
        "operator_distress", "speech_production", "hapax_daimonion"
    )

    # Vocal chain: MIDI affordances for speech modulation
    from agents.hapax_daimonion.midi_output import MidiOutput
    from agents.hapax_daimonion.vocal_chain import VOCAL_CHAIN_RECORDS, VocalChainCapability

    daemon._midi_output = MidiOutput(port_name=daemon.cfg.midi_output_port)
    daemon._vocal_chain = VocalChainCapability(
        midi_output=daemon._midi_output,
        evil_pet_channel=daemon.cfg.midi_evil_pet_channel,
        s4_channel=daemon.cfg.midi_s4_channel,
    )
    for record in VOCAL_CHAIN_RECORDS:
        daemon._affordance_pipeline.index_capability(record)

    # System awareness: surface DMN degradation to operator
    from agents.hapax_daimonion.system_awareness import (
        SYSTEM_AWARENESS_DESCRIPTION,
        SystemAwarenessCapability,
    )

    daemon._system_awareness = SystemAwarenessCapability()
    daemon._affordance_pipeline.index_capability(
        CapabilityRecord(
            name="system_awareness",
            description=SYSTEM_AWARENESS_DESCRIPTION,
            daemon="hapax_daimonion",
        )
    )
    daemon._affordance_pipeline.register_interrupt(
        "system_critical", "system_awareness", "hapax_daimonion"
    )

    # Cross-modal expression coordinator
    from agents._expression import ExpressionCoordinator

    daemon._expression_coordinator = ExpressionCoordinator()

    # Tool recruitment: register tool affordances and create gate
    from agents.hapax_daimonion.tool_affordances import TOOL_AFFORDANCES
    from agents.hapax_daimonion.tool_recruitment import ToolRecruitmentGate

    ToolRecruitmentGate.register_tools(daemon._affordance_pipeline, TOOL_AFFORDANCES)
    tool_names = {name for name, _ in TOOL_AFFORDANCES}
    daemon._tool_recruitment_gate = ToolRecruitmentGate(daemon._affordance_pipeline, tool_names)

    log.info(
        "Pipeline dependencies precomputed"
        " (affordance pipeline: speech + 9 vocal chain dims + system_awareness"
        " + %d tool affordances)",
        len(TOOL_AFFORDANCES),
    )
