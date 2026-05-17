"""Conversation pipeline construction and startup for VoiceDaemon."""

from __future__ import annotations

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
    from agents._working_mode import get_working_mode
    from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline
    from agents.hapax_daimonion.conversational_policy import get_policy
    from agents.hapax_daimonion.persona import screen_context_block, system_prompt

    # Load experiment flags
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

    tool_recruitment_gate = getattr(daemon, "_tool_recruitment_gate", None)

    policy_block = get_policy(
        env=daemon.perception.latest,
        guest_mode=daemon.session.is_guest_mode,
        experiment_mode=_experiment_mode,
    )
    prompt = system_prompt(
        guest_mode=daemon.session.is_guest_mode,
        policy_block=policy_block,
        experiment_mode=_experiment_mode,
        tool_recruitment_active=tool_recruitment_gate is not None,
    )

    if _exp.get("screen_context", True):
        screen_ctx = screen_context_block(daemon.workspace_monitor.latest_analysis)
        if screen_ctx:
            prompt += screen_ctx

    # Stimmung directives handled by phenomenal_context.render_stimmung() in the
    # per-turn VOLATILE band rebuild. No startup injection needed — ~111 tokens saved.

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
        import threading

        def _presynth() -> None:
            try:
                daemon._bridge_engine.presynthesize_all(daemon.tts)
                daemon._bridges_presynthesized = True
            except Exception:
                log.warning("Bridge presynthesis failed (bridges will synthesize on demand)")

        threading.Thread(target=_presynth, daemon=True, name="bridge-presynth").start()

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
        tool_recruitment_gate=tool_recruitment_gate,
    )

    # Per-programme thread persistence: INTERVIEW disables mid-session compression
    daemon._conversation_pipeline._message_drop_threshold = _resolve_message_drop_threshold(daemon)

    # Wire callbacks
    daemon._conversation_pipeline._goals_fn = daemon._goals_fn
    daemon._conversation_pipeline._health_fn = daemon._health_fn
    daemon._conversation_pipeline._nudges_fn = daemon._nudges_fn
    daemon._conversation_pipeline._dmn_fn = daemon._dmn_fn
    daemon._conversation_pipeline._imagination_fn = daemon._imagination_fn

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

    # Wire pipeline to CPAL runner for T3 delegation
    if daemon._cpal_runner is not None:
        daemon._cpal_runner.set_pipeline(daemon._conversation_pipeline)

        # Wire grounding ledger for GQI feedback loop
        if getattr(daemon._conversation_pipeline, "_grounding_ledger", None) is not None:
            daemon._cpal_runner.set_grounding_ledger(
                daemon._conversation_pipeline._grounding_ledger
            )

        # Wire audio output for T1 acknowledgments + backchannels.
        # Use attach_audio_output so the GEAL TTS envelope publisher tap
        # also gets wrapped onto the now-real PwAudioOutput.write.
        # (Direct attribute set still works for callers that don't need
        # the tap; the new method is preferred.)
        if getattr(daemon._conversation_pipeline, "_audio_output", None) is not None:
            audio_output = daemon._conversation_pipeline._audio_output
            attach = getattr(daemon._cpal_runner, "attach_audio_output", None)
            if callable(attach):
                attach(audio_output)
            else:
                daemon._cpal_runner._audio_output = audio_output

    # Wake greeting
    _play_wake_greeting(daemon)


_PROGRAMME_MESSAGE_DROP_THRESHOLD: dict[str, int] = {
    "interview": 999,
    "lecture": 50,
    "tutorial": 30,
}


def _resolve_message_drop_threshold(daemon: VoiceDaemon) -> int:
    """INTERVIEW programmes keep full thread — set threshold impossibly high."""
    try:
        pm = getattr(daemon, "programme_manager", None)
        if pm is not None:
            active = pm.store.active_programme()
            if active is not None:
                role_val = getattr(active.role, "value", str(active.role))
                threshold = _PROGRAMME_MESSAGE_DROP_THRESHOLD.get(role_val)
                if threshold is not None:
                    log.info("Programme role '%s' → message_drop_threshold=%d", role_val, threshold)
                    return threshold
    except Exception:
        log.debug("Programme message drop threshold resolution failed", exc_info=True)
    return 12


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


def _play_wake_greeting(daemon: VoiceDaemon) -> None:
    """Play a presynthesized acknowledging phrase in a background thread.

    Must not block the event loop — routed audio_output.write() sleeps for the
    audio duration (real-time pacing). Blocking here freezes the cognitive
    loop and causes utterances to be swallowed. The greeting still resolves
    private-or-drop and records voice-output witness before any write.
    """
    try:
        from agents.hapax_daimonion.bridge_engine import BridgeContext
        from agents.hapax_daimonion.cpal.destination_channel import resolve_playback_decision
        from agents.hapax_daimonion.voice_output_witness import (
            record_destination_decision,
            record_drop,
        )

        ctx = BridgeContext(
            turn_position=0,
            response_type="acknowledging",
            session_id=daemon._conversation_pipeline._session_id,
        )
        phrase, pcm = daemon._bridge_engine.select(ctx)
        if pcm and daemon._conversation_pipeline._audio_output:
            import threading

            decision = resolve_playback_decision(None)
            destination_target = decision.target
            destination_role = decision.media_role
            record_destination_decision(
                source="pipeline_start_wake_greeting",
                destination=decision.destination.value,
                route_accepted=decision.allowed,
                reason=decision.reason_code,
                safety_gate=decision.safety_gate,
                target=destination_target,
                media_role=destination_role,
                text=phrase,
                terminal_state="pending" if decision.allowed else "inhibited",
            )
            if not decision.allowed:
                record_drop(
                    reason=decision.reason_code,
                    source="pipeline_start_wake_greeting",
                    destination=decision.destination.value,
                    target=destination_target,
                    media_role=destination_role,
                    text=phrase,
                    terminal_state="inhibited",
                )
                return

            def _play() -> None:
                daemon._conversation_buffer.set_speaking(True)
                try:
                    daemon._conversation_pipeline._write_audio(
                        daemon._conversation_pipeline._audio_output,
                        getattr(daemon._conversation_pipeline, "_echo_canceller", None),
                        pcm,
                        destination_target,
                        destination_role,
                    )
                finally:
                    daemon._conversation_buffer.set_speaking(False)

            threading.Thread(target=_play, daemon=True).start()
            log.info("Wake greeting: '%s'", phrase)
    except Exception:
        log.debug("Wake greeting failed (non-fatal)", exc_info=True)
