"""Conversation pipeline construction and startup for VoiceDaemon."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


def _apply_mode_grounding_defaults(flags: dict) -> None:
    """Set grounding flags based on working mode.

    R&D mode: enable all grounding features by default.
    Research mode: leave flags as-is (controlled by experiment config).
    If experiment_mode is explicitly set, never override.
    """
    from agents._working_mode import get_working_mode

    if flags.get("experiment_mode", False):
        return

    if get_working_mode().value == "rnd":
        flags.setdefault("grounding_directive", True)
        flags.setdefault("effort_modulation", True)
        flags.setdefault("cross_session", True)
        flags.setdefault("stable_frame", True)
        flags.setdefault("message_drop", True)


async def start_conversation_pipeline(daemon: VoiceDaemon) -> None:
    """Start the lightweight conversation pipeline.

    Most dependencies are precomputed at startup. This method builds
    the fresh system prompt and creates the pipeline object (<50ms).
    """
    from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline
    from agents.hapax_daimonion.conversational_policy import get_policy
    from agents.hapax_daimonion.persona import screen_context_block, system_prompt

    # Load experiment flags
    if not hasattr(daemon, "_experiment_flags"):
        daemon._experiment_flags = {}
    try:
        _exp_path = Path.home() / ".cache" / "hapax" / "voice-experiment.json"
        if _exp_path.exists():
            import json as _json

            _raw_exp = _json.loads(_exp_path.read_text())
            daemon._experiment_flags = _raw_exp.get("components", {})
            daemon.event_log.set_experiment(
                name=_raw_exp.get("name", "unnamed"),
                condition=_raw_exp.get("condition", "A"),
                phase=_raw_exp.get("phase", "baseline"),
            )
    except Exception:
        log.debug("Experiment config load failed (non-fatal)", exc_info=True)

    _exp = daemon._experiment_flags

    _apply_mode_grounding_defaults(_exp)

    _experiment_mode = _exp.get("experiment_mode", False)

    policy_block = get_policy(
        env=daemon.perception.latest,
        guest_mode=daemon.session.is_guest_mode,
        experiment_mode=_experiment_mode,
    )
    prompt = system_prompt(
        guest_mode=daemon.session.is_guest_mode,
        policy_block=policy_block,
        experiment_mode=_experiment_mode,
    )

    if _exp.get("screen_context", True):
        screen_ctx = screen_context_block(daemon.workspace_monitor.latest_analysis)
        if screen_ctx:
            prompt += screen_ctx

    # Cross-session memory
    from agents.hapax_daimonion.session_memory import load_recent_memory, load_seed_entries

    _seed_entries = load_seed_entries(daemon)
    if not _seed_entries:
        recent_memory = load_recent_memory(daemon)
        if recent_memory:
            prompt += f"\n\n## Recent Conversations\n{recent_memory}"

    # Dynamic tool filtering
    tools, tool_handlers = _resolve_tools(daemon, _exp, get_working_mode)

    if not daemon._bridges_presynthesized:
        daemon._bridge_engine.presynthesize_all(daemon.tts)
        daemon._bridges_presynthesized = True

    daemon._conversation_pipeline = ConversationPipeline(
        stt=daemon._resident_stt,
        tts_manager=daemon.tts,
        system_prompt=prompt,
        tools=tools or None,
        tool_handlers=tool_handlers,
        llm_model=daemon.cfg.llm_model,
        event_log=daemon.event_log,
        conversation_buffer=daemon._conversation_buffer,
        consent_reader=daemon._precomputed_consent_reader,
        env_context_fn=daemon._env_context_fn,
        ambient_fn=daemon._ambient_fn,
        policy_fn=daemon._policy_fn,
        screen_capturer=getattr(daemon.workspace_monitor, "_screen_capturer", None),
        echo_canceller=daemon._echo_canceller,
        bridge_engine=daemon._bridge_engine,
    )

    # Wire callbacks
    daemon._conversation_pipeline._goals_fn = daemon._goals_fn
    daemon._conversation_pipeline._health_fn = daemon._health_fn
    daemon._conversation_pipeline._nudges_fn = daemon._nudges_fn
    daemon._conversation_pipeline._dmn_fn = daemon._dmn_fn
    daemon._conversation_pipeline._imagination_fn = daemon._imagination_fn
    daemon._cognitive_loop._speech_capability = daemon._speech_capability
    daemon._cognitive_loop._daemon = daemon

    # Wire salience
    if daemon._salience_router is not None:
        daemon._conversation_pipeline._salience_router = daemon._salience_router
        daemon._conversation_pipeline._salience_diagnostics = daemon._salience_diagnostics
        from agents.hapax_daimonion.salience_helpers import (
            refresh_concern_graph,
            refresh_context_distillation,
        )

        refresh_concern_graph(daemon)
        refresh_context_distillation(daemon)
        daemon._conversation_pipeline._context_distillation = daemon._context_distillation

    daemon._conversation_pipeline._experiment_flags = daemon._experiment_flags
    if _seed_entries:
        daemon._conversation_pipeline._conversation_thread = list(_seed_entries)

    await daemon._conversation_pipeline.start()
    log.info("Conversation pipeline started (mic stays shared)")

    # Create cognitive loop
    _start_cognitive_loop(daemon)

    # Wake greeting
    _play_wake_greeting(daemon)


def _resolve_tools(daemon, _exp, get_working_mode):
    """Resolve tools for the pipeline based on system context."""
    from agents._capability import SystemContext

    _stimmung_stance = "nominal"
    try:
        import json as _json

        _shm = Path("/dev/shm/hapax-stimmung/state.json")
        if _shm.exists():
            _stimmung_stance = _json.loads(_shm.read_text()).get("overall_stance", "nominal")
    except Exception:
        pass

    _active_backends: set[str] = set()
    if hasattr(daemon, "perception") and daemon.perception is not None:
        for b in getattr(daemon.perception, "_backends", []):
            try:
                if b.available():
                    _active_backends.add(b.name)
            except Exception:
                pass

    tool_ctx = SystemContext(
        stimmung_stance=_stimmung_stance,
        consent_state={},
        guest_present=daemon.session.is_guest_mode,
        active_backends=frozenset(_active_backends),
        working_mode=get_working_mode().value,
        experiment_flags={"tools_enabled": _exp.get("tools_enabled", False)},
    )
    tools = daemon._tool_registry.schemas_for_llm(tool_ctx) or None
    tool_handlers = daemon._tool_registry.handler_map(tool_ctx)
    return tools, tool_handlers


def _start_cognitive_loop(daemon: VoiceDaemon) -> None:
    """Create and start the cognitive loop."""
    from agents.hapax_daimonion.cognitive_loop import CognitiveLoop
    from agents.hapax_daimonion.conversational_model import ConversationalModel
    from agents.hapax_daimonion.speculative_stt import SpeculativeTranscriber

    spec_stt = SpeculativeTranscriber(daemon._resident_stt) if daemon._resident_stt else None
    conv_model = ConversationalModel()
    _speaker_id = daemon._speaker_identifier if daemon.session.trigger != "wake_word" else None

    daemon._cognitive_loop = CognitiveLoop(
        buffer=daemon._conversation_buffer,
        pipeline=daemon._conversation_pipeline,
        session=daemon.session,
        speaker_identifier=_speaker_id,
        salience_router=daemon._salience_router,
        speculative_stt=spec_stt,
        conversational_model=conv_model,
        event_log=daemon.event_log,
        active_silence_enabled=daemon.cfg.active_silence_enabled,
        silence_notification_threshold_s=daemon.cfg.silence_notification_threshold_s,
        silence_winddown_threshold_s=daemon.cfg.silence_winddown_threshold_s,
        notification_queue=daemon.notifications,
    )
    daemon.perception.replace_backend(daemon._cognitive_loop)
    daemon._pipeline_task = asyncio.create_task(daemon._cognitive_loop.run())


def _play_wake_greeting(daemon: VoiceDaemon) -> None:
    """Play a presynthesized acknowledging phrase."""
    try:
        from agents.hapax_daimonion.bridge_engine import BridgeContext

        ctx = BridgeContext(
            turn_position=0,
            response_type="acknowledging",
            session_id=daemon._conversation_pipeline._session_id,
        )
        phrase, pcm = daemon._bridge_engine.select(ctx)
        if pcm and daemon._conversation_pipeline._audio_output:
            daemon._conversation_buffer.set_speaking(True)
            daemon._conversation_pipeline._audio_output.write(pcm)
            daemon._conversation_buffer.set_speaking(False)
            log.info("Wake greeting: '%s'", phrase)
    except Exception:
        log.debug("Wake greeting failed (non-fatal)", exc_info=True)
