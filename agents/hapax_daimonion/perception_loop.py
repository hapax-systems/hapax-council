"""Perception loop for VoiceDaemon."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from agents.hapax_daimonion._perception_state_writer import write_perception_state
from agents.hapax_daimonion.consent_filter import filter_behaviors
from agents.hapax_daimonion.governance import VetoResult
from agents.hapax_daimonion.speaker_is_operator_engine import SpeakerIsOperatorEngine
from shared.control_signal import ControlSignal, publish_health

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")

_DEFAULT_VETO_RESULT = VetoResult(allowed=True)

_STIMMUNG_PATH = "/dev/shm/hapax-stimmung/state.json"


def _sync_seeking_stance(daemon: VoiceDaemon) -> None:
    """Read stimmung stance and sync SEEKING to salience router."""
    import json
    from pathlib import Path

    try:
        data = json.loads(Path(_STIMMUNG_PATH).read_text(encoding="utf-8"))
        is_seeking = data.get("overall_stance", "nominal") == "seeking"
        daemon._salience_router.set_seeking(is_seeking)
    except Exception:
        pass


async def perception_loop(daemon: VoiceDaemon) -> None:
    """Run perception fast tick + governor evaluation on cadence."""
    from agents.hapax_daimonion.commands import Command
    from agents.hapax_daimonion.config import PerceptionTier
    from agents.hapax_daimonion.salience_helpers import (
        refresh_concern_graph,
        refresh_context_distillation,
    )

    log.info("Perception loop started (tick=%.1fs)", daemon.cfg.perception_fast_tick_s)
    while daemon._running:
        try:
            await asyncio.sleep(daemon.cfg.perception_fast_tick_s)

            if daemon._perception_tier == PerceptionTier.DORMANT:
                continue

            daemon.perception.set_voice_session_active(daemon.session.is_active)
            state = daemon.perception.tick()

            # Apply consent ingestion filter — suppress person-adjacent
            # behaviors before state is consumed downstream.
            try:
                consent_phase = (
                    daemon.consent_tracker.phase.name
                    if hasattr(daemon, "consent_tracker")
                    else "NO_GUEST"
                )
                filter_behaviors(daemon.perception.behaviors, consent_phase)
            except Exception:
                pass  # consent filter is defensive — never block perception

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
                # Sync SEEKING stance to salience router
                try:
                    _sync_seeking_stance(daemon)
                except Exception:
                    pass

            _sync_pipeline_state(daemon, state)

            write_perception_state(
                daemon.perception,
                daemon.consent_registry,
                daemon.consent_tracker,
                session=daemon.session,
                pipeline=daemon._conversation_pipeline,
            )

            _now = time.time()
            _behaviors = daemon.perception.behaviors
            _total = len(_behaviors)
            _fresh = sum(1 for b in _behaviors.values() if (_now - b.watermark) < 30.0)
            publish_health(
                ControlSignal(
                    component="voice_daemon",
                    reference=1.0,
                    perception=_fresh / max(_total, 1),
                )
            )

            # Control law [voice_daemon]: <50% fresh backends → skip SLOW tier
            _vd_cl = getattr(daemon, "_cl_vd_errors", 0)
            _vd_ok = getattr(daemon, "_cl_vd_ok", 0)
            _vd_deg = getattr(daemon, "_cl_vd_degraded", False)
            if _fresh < _total / 2:
                _vd_cl += 1
                _vd_ok = 0
            else:
                _vd_cl = 0
                _vd_ok += 1

            if _vd_cl >= 3 and not _vd_deg:
                daemon._cl_vd_skip_slow = True
                _vd_deg = True
                log.warning("Control law [voice_daemon]: degrading — skipping SLOW backends")

            if _vd_ok >= 5 and _vd_deg:
                daemon._cl_vd_skip_slow = False
                _vd_deg = False
                log.info("Control law [voice_daemon]: recovered")

            daemon._cl_vd_errors = _vd_cl
            daemon._cl_vd_ok = _vd_ok
            daemon._cl_vd_degraded = _vd_deg

            _asr_available = daemon._conversation_pipeline is not None and hasattr(
                daemon._conversation_pipeline, "is_active"
            )
            publish_health(
                ControlSignal(
                    component="voice_pipeline",
                    reference=1.0,
                    perception=1.0 if _asr_available else 0.0,
                )
            )

            # Control law [voice_pipeline]: conversation pipeline unavailable
            _vp_cl = getattr(daemon, "_cl_vp_errors", 0)
            _vp_ok = getattr(daemon, "_cl_vp_ok", 0)
            _vp_deg = getattr(daemon, "_cl_vp_degraded", False)
            if not _asr_available:
                _vp_cl += 1
                _vp_ok = 0
            else:
                _vp_cl = 0
                _vp_ok += 1

            if _vp_cl >= 3 and not _vp_deg:
                daemon._cl_vp_proactive_disabled = True
                _vp_deg = True
                log.warning("Control law [voice_pipeline]: degrading — disabling proactive voice")

            if _vp_ok >= 5 and _vp_deg:
                daemon._cl_vp_proactive_disabled = False
                _vp_deg = False
                log.info("Control law [voice_pipeline]: recovered")

            daemon._cl_vp_errors = _vp_cl
            daemon._cl_vp_ok = _vp_ok
            daemon._cl_vp_degraded = _vp_deg
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("Error in perception loop")


def _get_or_create_speaker_engine(daemon: VoiceDaemon) -> SpeakerIsOperatorEngine:
    """Lazily attach a :class:`SpeakerIsOperatorEngine` to the daemon.

    Per-daemon attribute (not module singleton) so tests that construct
    a fresh ``VoiceDaemon`` get a fresh posterior — no cross-test
    pollution. Mirrors the ``daemon._presence_engine`` lazy pattern.
    """
    eng = getattr(daemon, "_speaker_is_operator_engine", None)
    if eng is None:
        eng = SpeakerIsOperatorEngine()
        daemon._speaker_is_operator_engine = eng
    return eng


def _tick_consent(daemon: VoiceDaemon, state) -> None:
    """Process consent state tracking within perception tick.

    Phase 6c-i.B (#1355 follow-on): the raw bool ``speaker_is_op`` is
    now derived from a calibrated :class:`SpeakerIsOperatorEngine`
    posterior with asymmetric temporal profile (k_enter=2 / k_exit=10).
    Brief speaker silences no longer flip ``speaker_is_operator`` to
    False on the same tick — sustained silence retracts the assertion.

    Kill-switch: ``HAPAX_BAYESIAN_BYPASS=1`` flows through the engine
    via :class:`shared.claim.ClaimEngine` to restore raw-bool semantics
    (Phase 0 FULL contract).
    """
    try:
        raw_signal = (
            not daemon.session.is_active
            or getattr(daemon.session, "speaker", "operator") == "operator"
        )
        _speaker_engine = _get_or_create_speaker_engine(daemon)
        _voice_bio: bool | None = None
        _speaker_id = getattr(daemon, "_speaker_identifier", None)
        if _speaker_id is not None and state.audio_bytes is not None:
            try:
                _result = _speaker_id.identify_audio(state.audio_bytes)
                if _result is not None:
                    _voice_bio = _result.label == "operator"
            except Exception:
                pass
        _speaker_engine.tick(
            session_speaker_says_operator=raw_signal,
            voice_biometric_match=_voice_bio,
        )
        # Asymmetric semantics: ``state != "RETRACTED"`` means single_user
        # axiom default-to-operator stays in effect during cold-start
        # (UNCERTAIN) and during transient silences (ASSERTED holds across
        # brief False ticks per k_exit=10). Posterior-threshold alone would
        # snap-flip on a single False tick (posterior crashes by one
        # log-LR shift), defeating the temporal-profile purpose. Retraction
        # only occurs after sustained False evidence (k_exit ticks below
        # exit_threshold=0.3).
        speaker_is_op = _speaker_engine.state != "RETRACTED"
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
