"""Session event handling for VoiceDaemon (hotkey, wake word, scan)."""

from __future__ import annotations

import logging
import subprocess
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


def screen_flash(kind: str = "activation") -> None:
    """Brief desktop notification as visual acknowledgment."""
    icons = {
        "activation": "audio-input-microphone",
        "deactivation": "microphone-sensitivity-muted",
        "error": "dialog-error",
        "completion": "dialog-ok",
    }
    labels = {
        "activation": "Listening…",
        "deactivation": "Session closed",
        "error": "Error",
        "completion": "Done",
    }
    try:
        subprocess.Popen(
            [
                "notify-send",
                "--app-name=Hapax Daimonion",
                f"--icon={icons.get(kind, 'dialog-information')}",
                "--expire-time=1500",
                "--transient",
                labels.get(kind, kind),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass


def acknowledge(daemon: VoiceDaemon, kind: str = "activation") -> None:
    """Play chime or screen flash depending on config."""
    if daemon.cfg.chime_enabled:
        daemon.chime_player.play(kind)
    else:
        screen_flash(kind)


async def _open_session(daemon: VoiceDaemon, trigger: str) -> None:
    """Open session, activate buffer, start pipeline, wire CPAL.

    Shared helper used by both engagement detection and hotkey paths.
    If pipeline start fails, the session is closed (zombie recovery).
    """
    acknowledge(daemon, "activation")
    daemon.governor.engagement_active = True
    daemon._frame_gate.set_directive("process")
    daemon.session.open(trigger=trigger)
    daemon.session.set_speaker("operator", confidence=1.0)
    daemon._conversation_buffer.activate()
    log.info("Session opened via %s", trigger)
    daemon.event_log.set_session_id(daemon.session.session_id)
    daemon.event_log.emit("session_lifecycle", action="opened", trigger=trigger)

    if daemon._conversation_pipeline is None:
        try:
            await daemon._start_pipeline()
            if daemon._cpal_runner is not None:
                daemon._cpal_runner.set_pipeline(daemon._conversation_pipeline)
            log.info("Pipeline started for CPAL T3")
        except Exception:
            log.exception("Pipeline start failed — closing session")
            await close_session(daemon, reason="pipeline_start_failed")


async def on_engagement_detected(daemon: VoiceDaemon) -> None:
    """Called (via ensure_future) when engagement classifier fires.

    Single entry point: boosts CPAL gain, opens session if needed,
    runs axiom veto, starts pipeline, and wires to CPAL runner.
    """
    # 1. Boost CPAL gain on every engagement detection
    if daemon._cpal_runner is not None:
        from agents.hapax_daimonion.cpal.types import GainUpdate

        daemon._cpal_runner.evaluator.gain_controller.apply(
            GainUpdate(delta=0.2, source="engagement_detected")
        )

    # 2. Early return if session already active
    if daemon.session.is_active:
        return

    # 3. Axiom veto check
    state = daemon.perception.tick()
    veto = daemon.governor._veto_chain.evaluate(state)
    if not veto.allowed and "axiom_compliance" in veto.denied_by:
        log.warning("Engagement blocked by axiom compliance: %s", veto.denied_by)
        acknowledge(daemon, "denied")
        return

    # 4. Open session via shared helper
    await _open_session(daemon, trigger="engagement")


async def handle_hotkey(daemon: VoiceDaemon, cmd: str) -> None:
    """Handle hotkey commands."""

    if cmd == "toggle":
        if daemon.session.is_active:
            await close_session(daemon, reason="hotkey")
        else:
            state = daemon.perception.tick()
            veto = daemon.governor._veto_chain.evaluate(state)
            if not veto.allowed and "axiom_compliance" in veto.denied_by:
                log.warning("Hotkey toggle blocked by axiom compliance: %s", veto.denied_by)
                acknowledge(daemon, "denied")
                return
            await _open_session(daemon, trigger="hotkey")
    elif cmd == "open":
        state = daemon.perception.tick()
        veto = daemon.governor._veto_chain.evaluate(state)
        if not veto.allowed and "axiom_compliance" in veto.denied_by:
            log.warning("Hotkey open blocked by axiom compliance: %s", veto.denied_by)
            acknowledge(daemon, "denied")
            return
        await _open_session(daemon, trigger="hotkey")
    elif cmd == "close":
        await close_session(daemon, reason="hotkey")
    elif cmd == "scan":
        await handle_scan(daemon)
    elif cmd == "status":
        log.info(
            "Status: session=%s presence=%s queue=%d pipeline=%s tier=%s",
            daemon.session.state,
            daemon.presence.score,
            daemon.notifications.pending_count,
            "running" if daemon._pipeline_task is not None else "idle",
            daemon._perception_tier.value,
        )
    elif cmd.startswith("perception:"):
        tier_name = cmd.split(":", 1)[1].strip()
        set_perception_tier(daemon, tier_name)


def set_perception_tier(daemon: VoiceDaemon, tier_name: str) -> None:
    """Switch perception tier (voice/hotkey command)."""
    from agents.hapax_daimonion.config import PerceptionTier

    try:
        new_tier = PerceptionTier(tier_name)
    except ValueError:
        log.warning("Unknown perception tier: %s", tier_name)
        return
    old_tier = daemon._perception_tier
    daemon._perception_tier = new_tier
    log.info("Perception tier: %s -> %s", old_tier.value, new_tier.value)
    daemon.event_log.emit("perception_tier_changed", old=old_tier.value, new=new_tier.value)


async def close_session(daemon: VoiceDaemon, reason: str) -> None:
    """Close the active session and stop the pipeline."""
    from agents.hapax_daimonion.session_memory import persist_session_digest

    persist_session_digest(daemon)
    await daemon._stop_pipeline()
    acknowledge(daemon, "deactivation")
    if daemon.session.is_active:
        duration = time.monotonic() - daemon.session._opened_at
        daemon.event_log.emit(
            "session_lifecycle", action="closed", reason=reason, duration_s=round(duration, 1)
        )
    daemon.event_log.set_session_id(None)
    daemon.event_log.clear_experiment()
    # Notify engagement classifier so context/follow-up windows reset
    if hasattr(daemon, "_engagement"):
        daemon._engagement.notify_session_closed()
    daemon.session.close(reason=reason)


async def handle_scan(daemon: VoiceDaemon) -> None:
    """Capture a high-res frame from BRIO and extract text via Gemini."""
    if not daemon.workspace_monitor.has_camera("operator"):
        log.warning("Scan requested but no operator camera available")
        return

    daemon.workspace_monitor._webcam_capturer.reset_cooldown("operator")
    frame_b64 = daemon.workspace_monitor._webcam_capturer.capture("operator")
    if frame_b64 is None:
        log.warning("Scan: failed to capture frame")
        return

    try:
        client = daemon.workspace_monitor._analyzer._get_client()
        response = await client.chat.completions.create(
            model=daemon.workspace_monitor._analyzer.model,
            messages=[
                {
                    "role": "system",
                    "content": "Extract all text from this image. Return plain text only.",
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"},
                        },
                        {"type": "text", "text": "Extract text from this document/label."},
                    ],
                },
            ],
            temperature=0.0,
            max_tokens=1024,
        )
        text = response.choices[0].message.content.strip()
        subprocess.run(["wl-copy", text], timeout=5)
        log.info("Scan: extracted %d chars, copied to clipboard", len(text))
    except Exception as exc:
        log.warning("Scan failed: %s", exc)
