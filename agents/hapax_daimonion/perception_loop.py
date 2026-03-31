"""Perception loop for VoiceDaemon."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from agents.hapax_daimonion._perception_state_writer import write_perception_state
from agents.hapax_daimonion.governance import VetoResult

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")

_DEFAULT_VETO_RESULT = VetoResult(allowed=True)


async def perception_loop(daemon: VoiceDaemon) -> None:
    """Run perception fast tick + governor evaluation on cadence."""
    from agents.hapax_daimonion.commands import Command
    from agents.hapax_daimonion.config import PerceptionTier
    from agents.hapax_daimonion.salience_helpers import (
        refresh_concern_graph,
        refresh_context_distillation,
    )

    while daemon._running:
        try:
            await asyncio.sleep(daemon.cfg.perception_fast_tick_s)

            if daemon._perception_tier == PerceptionTier.DORMANT:
                continue

            daemon.perception.set_voice_session_active(daemon.session.is_active)
            state = daemon.perception.tick()
            daemon._check_tap_gesture()

            directive = daemon.governor.evaluate(state)
            command = Command(
                action=directive,
                trigger_time=state.timestamp,
                trigger_source="perception_tick",
                min_watermark=daemon.perception.min_watermark,
                governance_result=(
                    daemon.governor.last_veto_result
                    if daemon.governor.last_veto_result is not None
                    else _DEFAULT_VETO_RESULT
                ),
                selected_by=(
                    daemon.governor.last_selected.selected_by
                    if daemon.governor.last_selected is not None
                    else "default"
                ),
            )
            daemon._frame_gate.apply_command(command)

            if directive == "pause" and daemon.session.is_active and not daemon.session.is_paused:
                daemon.session.pause(reason=f"governor:{state.activity_mode}")
            elif directive == "process" and daemon.session.is_paused:
                daemon.session.resume()
            elif (
                directive == "withdraw"
                and daemon.session.is_active
                and daemon._conversation_pipeline is None
            ):
                from agents.hapax_daimonion.session_events import close_session

                await close_session(daemon, reason="operator_absent")

            daemon.gate.set_behaviors(daemon.perception.behaviors)
            _tick_consent(daemon, state)

            if daemon._local_llm_backend is not None:
                from agents.hapax_daimonion._perception_state_writer import get_perception_ring

                ring = get_perception_ring()
                if ring is not None and ring.current() is not None:
                    daemon._local_llm_backend.set_perception_snapshot(ring.current())

            if daemon._salience_router is not None:
                refresh_concern_graph(daemon)
                refresh_context_distillation(daemon)

            _sync_pipeline_state(daemon, state)

            write_perception_state(
                daemon.perception,
                daemon.consent_registry,
                daemon.consent_tracker,
                session=daemon.session,
                pipeline=daemon._conversation_pipeline,
            )
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("Error in perception loop")


def _tick_consent(daemon: VoiceDaemon, state) -> None:
    """Process consent state tracking within perception tick."""
    try:
        speaker_is_op = (
            not daemon.session.is_active
            or getattr(daemon.session, "speaker", "operator") == "operator"
        )
        _pe = daemon._presence_engine
        _suppress = _pe is not None and _pe.state == "PRESENT" and _pe.posterior >= 0.8
        _effective = 0 if _suppress else state.guest_count

        _ir_count_b = daemon.perception.behaviors.get("ir_person_count")
        if _ir_count_b is not None and not _suppress:
            _ir = int(_ir_count_b.value or 0)
            if _ir > 1:
                _effective = max(_effective, _ir - 1)

        daemon.consent_tracker.tick(
            face_count=state.face_count,
            speaker_is_operator=speaker_is_op,
            guest_count=_effective,
            now=state.timestamp,
        )

        if (
            daemon.consent_tracker.needs_notification
            and not daemon.session.is_active
            and not daemon._consent_session_active
        ):
            asyncio.create_task(daemon._run_consent_session())
    except Exception:
        log.debug("Consent tracker error (non-fatal)", exc_info=True)


def _sync_pipeline_state(daemon: VoiceDaemon, state) -> None:
    """Sync perception state to conversation pipeline for routing."""
    if daemon._conversation_pipeline is None:
        return
    daemon._conversation_pipeline._activity_mode = state.activity_mode
    _cp = daemon.consent_tracker.phase.value if hasattr(daemon.consent_tracker, "phase") else "none"
    _phase_map = {
        "no_guest": "none",
        "guest_detected": "none",
        "consent_pending": "pending",
        "consent_granted": "active",
        "consent_refused": "refused",
    }
    daemon._conversation_pipeline._consent_phase = _phase_map.get(_cp, "none")
    daemon._conversation_pipeline._guest_mode = daemon.session.is_guest_mode
    daemon._conversation_pipeline._face_count = state.guest_count
    _desk_b = daemon.perception.behaviors.get("desk_activity")
    daemon._conversation_pipeline._desk_activity = (
        str(_desk_b.value) if _desk_b is not None else "idle"
    )
