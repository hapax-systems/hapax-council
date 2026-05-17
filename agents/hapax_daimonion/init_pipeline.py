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

    # Consent reader (stable, reloads contracts on session start).
    #
    # BETA-FINDING-K (queue 024 Phase 0): the prior version of this
    # block silently caught any exception raised by
    # ``ConsentGatedReader.create()`` (which fans out to
    # ``ConsentRegistry.load_all()``), logged a warning, and left
    # ``_precomputed_consent_reader`` at ``None``. The downstream
    # ``conversation_pipeline._handle_tool_calls`` then fell through
    # unfiltered, delivering tool results to the LLM *without* the
    # consent gate — a direct violation of the
    # ``interpersonal_transparency`` axiom (weight 88).
    #
    # A malformed contract file on disk tripped this in production
    # on 2026-04-13 (beta caught the live violation in queue 024).
    # The fix is fail-closed: if the reader cannot be constructed,
    # raise so the daemon refuses to start, forcing operator
    # attention to the malformed contract rather than degrading
    # silently. The operator can still boot the daemon by fixing or
    # removing the offending contract; silent fall-through is no
    # longer an option.
    from agents._consent_reader import ConsentGatedReader

    daemon._precomputed_consent_reader = ConsentGatedReader.create()

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

    # Collect ALL capability records for batch indexing
    _all_records: list[CapabilityRecord] = []

    # Speech production — Hapax TTS emission to livestream.
    # Tagged medium-risk: speech_safety (shared/speech_safety.py) redacts
    # slurs pre-TTS, persona constrains register, but the LLM remains
    # the source of record for potentially monetization-eligible
    # phrases. Programme monetization_opt_ins gates broadcast.
    _all_records.append(
        CapabilityRecord(
            name="speech_production",
            description=SPEECH_DESCRIPTION,
            daemon="hapax_daimonion",
            operational=OperationalProperties(
                requires_gpu=True,
                medium="auditory",
                monetization_risk="medium",
                risk_reason="LLM-generated speech; speech_safety filters slurs pre-TTS but LLM output is source-of-record. Programme opt-in gates broadcast surfaces.",
            ),
        )
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
    _all_records.extend(VOCAL_CHAIN_RECORDS)

    # Vinyl Mode D: granular-wash capability for Content-ID defeat on
    # vinyl source. Shares the MIDI output with the vocal chain (both
    # talk to Evil Pet + S-4) but is mutually exclusive with the vocal
    # chain — only one set of base CCs can be on the device at a time.
    # activate_mode_d() writes the granular-engaged scene; the vocal
    # chain's startup scene wins when Mode D is not active.
    from agents.hapax_daimonion.vinyl_chain import VINYL_CHAIN_RECORDS, VinylChainCapability

    daemon._vinyl_chain = VinylChainCapability(
        midi_output=daemon._midi_output,
        evil_pet_channel=daemon.cfg.midi_evil_pet_channel,
        s4_channel=daemon.cfg.midi_s4_channel,
    )
    _all_records.extend(VINYL_CHAIN_RECORDS)

    # System awareness
    from agents.hapax_daimonion.system_awareness import (
        SYSTEM_AWARENESS_DESCRIPTION,
        SystemAwarenessCapability,
    )

    daemon._system_awareness = SystemAwarenessCapability()
    _all_records.append(
        CapabilityRecord(
            name="system_awareness",
            description=SYSTEM_AWARENESS_DESCRIPTION,
            daemon="hapax_daimonion",
        )
    )

    # Cross-modal expression coordinator
    from agents._expression import ExpressionCoordinator

    daemon._expression_coordinator = ExpressionCoordinator()

    # Novel capability discovery
    from agents.hapax_daimonion.discovery_affordance import (
        DISCOVERY_AFFORDANCE,
        CapabilityDiscoveryHandler,
    )

    _all_records.append(
        CapabilityRecord(
            name=DISCOVERY_AFFORDANCE[0],
            description=DISCOVERY_AFFORDANCE[1],
            daemon="hapax_daimonion",
            operational=OperationalProperties(
                latency_class="slow",
                requires_network=True,
                consent_required=True,
            ),
        )
    )
    daemon._discovery_handler = CapabilityDiscoveryHandler()

    # Tool recruitment: collect tool affordances
    from agents.hapax_daimonion.tool_affordances import TOOL_AFFORDANCES
    from agents.hapax_daimonion.tool_recruitment import ToolRecruitmentGate

    for name, desc in TOOL_AFFORDANCES:
        medium = "visual" if name in ToolRecruitmentGate._VISUAL_TOOLS else "textual"
        _all_records.append(
            CapabilityRecord(
                name=name,
                description=desc,
                daemon="hapax_daimonion",
                operational=OperationalProperties(latency_class="fast", medium=medium),
            )
        )
    tool_names = {name for name, _ in TOOL_AFFORDANCES}
    daemon._tool_recruitment_gate = ToolRecruitmentGate(daemon._affordance_pipeline, tool_names)

    # World affordances from shared registry
    from shared.affordance_registry import ALL_AFFORDANCES

    _all_records.extend(ALL_AFFORDANCES)

    # Batch-index everything in one Ollama + Qdrant call
    _indexed = daemon._affordance_pipeline.index_capabilities_batch(_all_records)

    # Register interrupt handlers (no embedding needed)
    daemon._affordance_pipeline.register_interrupt(
        "population_critical", "speech_production", "hapax_daimonion"
    )
    daemon._affordance_pipeline.register_interrupt(
        "operator_distress", "speech_production", "hapax_daimonion"
    )
    daemon._affordance_pipeline.register_interrupt(
        "system_critical", "system_awareness", "hapax_daimonion"
    )

    # Seed context associations for audio performance mode modulation.
    # active_performance boosts expression/fx, dampens speech.
    # speaking boosts speech, dampens expression.
    _PERFORMANCE_SEEDS: list[tuple[str, str, float]] = [
        ("active_performance", "speech_production", -0.3),
        ("active_performance", "vocal_chain.intensity", 0.4),
        ("active_performance", "vocal_chain.diffusion", 0.3),
        ("active_performance", "vocal_chain.depth", 0.3),
        ("passive_music", "vocal_chain.diffusion", 0.2),
        ("passive_music", "vocal_chain.depth", 0.2),
        ("speaking", "speech_production", 0.3),
        ("speaking", "vocal_chain.intensity", -0.2),
    ]
    for cue, cap, delta in _PERFORMANCE_SEEDS:
        daemon._affordance_pipeline.update_context_association(cue, cap, delta=delta)

    log.info("Pipeline dependencies precomputed (batch-indexed %d capabilities)", _indexed)
