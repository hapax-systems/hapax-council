"""Entry point for hapax-voice daemon."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import subprocess
import time
from pathlib import Path

from agents.hapax_voice.activity_mode import classify_activity_mode
from agents.hapax_voice.audio_input import AudioInputStream
from agents.hapax_voice.chime_player import ChimePlayer
from agents.hapax_voice.config import load_config
from agents.hapax_voice.context_gate import ContextGate
from agents.hapax_voice.event_log import EventLog
from agents.hapax_voice.frame_gate import FrameGate
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.hotkey import HotkeyServer
from agents.hapax_voice.notification_queue import NotificationQueue
from agents.hapax_voice.ntfy_listener import subscribe_ntfy
from agents.hapax_voice.perception import PerceptionEngine
from agents.hapax_voice.persona import format_notification, session_end_message
from agents.hapax_voice.presence import PresenceDetector
from agents.hapax_voice.screen_models import CameraConfig
from agents.hapax_voice.session import SessionManager
from agents.hapax_voice.tracing import VoiceTracer
from agents.hapax_voice.tts import TTSManager
from agents.hapax_voice.wake_word import WakeWordDetector
from agents.hapax_voice.wake_word_porcupine import PorcupineWakeWord
from agents.hapax_voice.workspace_monitor import WorkspaceMonitor

log = logging.getLogger("hapax_voice")


def _screen_flash(kind: str = "activation") -> None:
    """Brief desktop notification as visual acknowledgment — replaces audio chime."""
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
                "--app-name=Hapax Voice",
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


# How often to check for proactive delivery opportunities (seconds)
_PROACTIVE_CHECK_INTERVAL_S = 30
# ntfy base URL
_NTFY_BASE_URL = "http://127.0.0.1:8090"
# ntfy topics to subscribe to
_NTFY_TOPICS = ["hapax"]


class VoiceDaemon:
    """Main daemon coordinating all voice subsystems."""

    def __init__(self, cfg: VoiceConfig | None = None) -> None:

        self.cfg = cfg if cfg is not None else load_config()
        self.session = SessionManager(silence_timeout_s=self.cfg.silence_timeout_s)
        self.presence = PresenceDetector(
            window_minutes=self.cfg.presence_window_minutes,
            vad_threshold=self.cfg.presence_vad_threshold,
        )
        self.gate = ContextGate(
            session=self.session,
            volume_threshold=self.cfg.context_gate_volume_threshold,
            ambient_classification=self.cfg.context_gate_ambient_classification,
            ambient_block_threshold=self.cfg.context_gate_ambient_block_threshold,
        )
        self.notifications = NotificationQueue(
            ttls=self.cfg.notification_priority_ttls,
        )
        self.hotkey = HotkeyServer(
            socket_path=Path(self.cfg.hotkey_socket),
            on_command=self._handle_hotkey,
        )
        self.wake_word = self._create_wake_word_detector()
        self.wake_word.on_wake_word = self._on_wake_word
        self._audio_input = AudioInputStream(source_name=self.cfg.audio_input_source)
        self.tts = TTSManager(kokoro_voice=self.cfg.kokoro_voice)
        self.chime_player = ChimePlayer(
            chime_dir=Path(self.cfg.chime_dir).expanduser(),
            auto_generate=True,
            volume=self.cfg.chime_volume,
        )
        # Build camera configs from config
        cameras = []
        if self.cfg.webcam_enabled:
            cameras.append(
                CameraConfig(
                    device=self.cfg.webcam_brio_device,
                    role="operator",
                    width=self.cfg.webcam_capture_width,
                    height=self.cfg.webcam_capture_height,
                )
            )
            cameras.append(
                CameraConfig(
                    device=self.cfg.webcam_c920_device,
                    role="hardware",
                    width=self.cfg.webcam_capture_width,
                    height=self.cfg.webcam_capture_height,
                )
            )
            if self.cfg.webcam_ir_device:
                cameras.append(
                    CameraConfig(
                        device=self.cfg.webcam_ir_device,
                        role="ir",
                        width=340,
                        height=340,
                        input_format="rawvideo",
                        pixel_format="gray",
                    )
                )

        self.workspace_monitor = WorkspaceMonitor(
            enabled=self.cfg.screen_monitor_enabled,
            poll_interval_s=self.cfg.screen_poll_interval_s,
            capture_cooldown_s=self.cfg.screen_capture_cooldown_s,
            proactive_min_confidence=self.cfg.screen_proactive_min_confidence,
            proactive_cooldown_s=self.cfg.screen_proactive_cooldown_s,
            recapture_idle_s=self.cfg.screen_recapture_idle_s,
            cameras=cameras if cameras else None,
            face_interval_s=self.cfg.presence_face_interval_s,
            face_min_confidence=self.cfg.presence_face_min_confidence,
        )
        self.workspace_monitor.set_notification_queue(self.notifications)
        self.workspace_monitor.set_presence(self.presence)

        # Perception layer
        self.perception = PerceptionEngine(
            presence=self.presence,
            workspace_monitor=self.workspace_monitor,
        )

        # Wire Hyprland desktop state into perception
        listener = self.workspace_monitor.listener
        if listener is not None:
            ipc = listener._ipc  # Reuse the listener's IPC instance
            orig_cb = listener.on_focus_changed

            def _focus_with_perception(event):
                # Update perception with desktop state
                clients = ipc.get_clients()
                self.perception.update_desktop_state(
                    active_window=ipc.get_active_window(),
                    window_count=len(clients),
                    active_workspace_id=event.workspace_id,
                )
                # Chain to workspace monitor's capture trigger
                if orig_cb is not None:
                    orig_cb(event)

            listener.on_focus_changed = _focus_with_perception

        self.governor = PipelineGovernor(
            conversation_debounce_s=self.cfg.conversation_debounce_s,
            operator_absent_withdraw_s=self.cfg.operator_absent_withdraw_s,
            environment_clear_resume_s=self.cfg.environment_clear_resume_s,
        )
        self._frame_gate = FrameGate()

        self._running = True
        self._background_tasks: list[asyncio.Task] = []
        # Pipeline state (managed per-session)
        self._pipeline_task: asyncio.Task | None = None
        self._gemini_session = None

        # Observability
        events_dir = Path.home() / ".local" / "share" / "hapax-voice"
        self.event_log = EventLog(
            base_dir=events_dir,
            retention_days=self.cfg.observability_events_retention_days,
            enabled=self.cfg.observability_events_enabled,
        )
        self.tracer = VoiceTracer(enabled=self.cfg.observability_langfuse_enabled)

        # Wire observability into subsystems
        self.presence.set_event_log(self.event_log)
        self.gate.set_event_log(self.event_log)
        self.notifications.set_event_log(self.event_log)
        self.workspace_monitor.set_event_log(self.event_log)
        self.workspace_monitor.set_tracer(self.tracer)

    # ------------------------------------------------------------------
    # Wake word engine selection
    # ------------------------------------------------------------------

    def _create_wake_word_detector(self):
        """Instantiate wake word detector based on config.

        Porcupine is the default (reliable, low false-positive).
        Falls back to OpenWakeWord if configured or if Porcupine fails to load.
        """
        if self.cfg.wake_word_engine == "porcupine":
            detector = PorcupineWakeWord(sensitivity=self.cfg.porcupine_sensitivity)
            return detector
        return WakeWordDetector()

    # ------------------------------------------------------------------
    # Audio distribution
    # ------------------------------------------------------------------

    async def _audio_loop(self) -> None:
        """Distribute audio frames to wake word, VAD, and Gemini consumers.

        AudioInputStream produces 480-sample (30ms) frames.  Consumers need
        exact chunk sizes:
        - Porcupine: exactly 512 samples (32ms)
        - OpenWakeWord: exactly 1280 samples (80ms)
        - Silero VAD v5: exactly 512 samples (32ms)
        - Gemini Live: any size (gets each 30ms frame immediately)

        Wake word runs on ALL audio (no VAD gating). Porcupine is designed
        for continuous audio and uses ~0.1% CPU. VAD gating adds latency and
        failure modes (ambient noise keeps gate permanently open).

        VAD feeds the PresenceDetector for presence scoring only.
        """
        import numpy as np

        _wake_samples = getattr(self.wake_word, "frame_length", 1280)
        _WAKE_CHUNK = _wake_samples * 2  # samples × 2 bytes (int16)
        _VAD_CHUNK = 512 * 2  # 512 samples × 2 bytes (int16)
        _wake_buf = bytearray()
        _vad_buf = bytearray()

        _recovery_delay = 5.0
        while self._running:
            try:
                frame = await self._audio_input.get_frame(timeout=1.0)
            except Exception as exc:
                log.warning("Audio stream error: %s — recovering in %.0fs", exc, _recovery_delay)
                self._audio_input.stop()
                await asyncio.sleep(_recovery_delay)
                self._audio_input.start()
                _recovery_delay = min(_recovery_delay * 2, 60.0)
                continue
            if frame is None:
                continue
            _recovery_delay = 5.0

            # Gemini Live: forward each 30ms frame immediately
            if self._gemini_session is not None and self._gemini_session.is_connected:
                try:
                    await self._gemini_session.send_audio(frame)
                except Exception as exc:
                    log.warning("Gemini audio consumer error: %s", exc)

            # Accumulate for exact-sized consumer chunks
            _wake_buf.extend(frame)
            _vad_buf.extend(frame)

            # Presence/VAD: drain all complete 512-sample chunks
            while len(_vad_buf) >= _VAD_CHUNK:
                chunk = bytes(_vad_buf[:_VAD_CHUNK])
                del _vad_buf[:_VAD_CHUNK]
                try:
                    self.presence.process_audio_frame(chunk)
                except Exception as exc:
                    log.warning("Presence consumer error: %s", exc)

            # Wake word: process ALL audio (no VAD gating)
            while len(_wake_buf) >= _WAKE_CHUNK:
                chunk = bytes(_wake_buf[:_WAKE_CHUNK])
                del _wake_buf[:_WAKE_CHUNK]
                try:
                    audio_np = np.frombuffer(chunk, dtype=np.int16)
                    self.wake_word.process_audio(audio_np)
                except Exception as exc:
                    log.warning("Wake word consumer error: %s", exc)

    # ------------------------------------------------------------------
    # Pipeline lifecycle
    # ------------------------------------------------------------------

    async def _start_pipeline(self) -> None:
        """Start the voice pipeline for the current session.

        For backend="local", builds a Pipecat pipeline (STT -> LLM -> TTS)
        with LocalAudioTransport. For backend="gemini", connects a Gemini
        Live session for speech-to-speech.
        """
        if self._pipeline_task is not None:
            log.warning("Pipeline already running, skipping start")
            return

        backend = self.cfg.backend

        if backend == "gemini":
            await self._start_gemini_session()
        else:
            await self._start_local_pipeline()

    async def _start_local_pipeline(self) -> None:
        """Build and start the local Pipecat pipeline in a background task.

        Stops the daemon's AudioInputStream first so Pipecat's
        LocalAudioTransport can claim the microphone exclusively.
        """
        from pipecat.pipeline.runner import PipelineRunner

        from agents.hapax_voice.pipeline import build_pipeline_task

        # Release mic so Pipecat can open its own input stream
        self._audio_input.stop()
        log.info("Daemon audio input stopped — handing mic to pipeline")

        guest_mode = self.session.is_guest_mode

        try:
            task, transport = build_pipeline_task(
                stt_model=self.cfg.local_stt_model,
                llm_model=self.cfg.llm_model,
                kokoro_voice=self.cfg.kokoro_voice,
                guest_mode=guest_mode,
                config=self.cfg,
                webcam_capturer=getattr(self.workspace_monitor, "webcam_capturer", None),
                screen_capturer=getattr(self.workspace_monitor, "screen_capturer", None),
                frame_gate=self._frame_gate,
            )
        except Exception:
            log.exception("Failed to build Pipecat pipeline")
            # Restore daemon audio input on failure
            self._audio_input.start()
            return

        self._pipecat_task = task
        self._pipecat_transport = transport

        async def _run_pipeline() -> None:
            try:
                runner = PipelineRunner(
                    handle_sigint=False,
                    handle_sigterm=False,
                )
                log.info("Local Pipecat pipeline started (guest=%s)", guest_mode)
                await runner.run(task)
            except asyncio.CancelledError:
                log.info("Local Pipecat pipeline cancelled")
            except Exception:
                log.exception("Local Pipecat pipeline error")

        self._pipeline_task = asyncio.create_task(_run_pipeline())

    async def _start_gemini_session(self) -> None:
        """Connect and start a Gemini Live session."""
        from agents.hapax_voice.gemini_live import GeminiLiveSession
        from agents.hapax_voice.persona import system_prompt

        prompt = system_prompt(guest_mode=self.session.is_guest_mode)
        session = GeminiLiveSession(
            model=self.cfg.gemini_model,
            system_prompt=prompt,
        )
        await session.connect()
        if session.is_connected:
            self._gemini_session = session
            log.info("Gemini Live session started")
        else:
            log.error("Gemini Live session failed to connect")

    async def _stop_pipeline(self) -> None:
        """Stop the active pipeline or Gemini session.

        Restores the daemon's AudioInputStream so wake word detection
        resumes after the session ends.
        """
        if self._gemini_session is not None:
            await self._gemini_session.disconnect()
            self._gemini_session = None
            log.info("Gemini Live session stopped")

        if self._pipeline_task is not None:
            # Cancel the runner task and wait for cleanup
            self._pipeline_task.cancel()
            try:
                await self._pipeline_task
            except asyncio.CancelledError:
                pass
            self._pipeline_task = None
            self._pipecat_task = None
            self._pipecat_transport = None
            log.info("Local Pipecat pipeline stopped")

        # Restore daemon audio input for wake word / VAD
        if not self._audio_input.is_active:
            self._audio_input.start()
            log.info("Daemon audio input restored")

    # ------------------------------------------------------------------
    # Session events
    # ------------------------------------------------------------------

    def _acknowledge(self, kind: str = "activation") -> None:
        """Play chime or screen flash depending on config."""
        if self.cfg.chime_enabled:
            self.chime_player.play(kind)
        else:
            _screen_flash(kind)

    def _on_wake_word(self) -> None:
        """Called when wake word is detected."""
        if not self.session.is_active:
            self._acknowledge("activation")
            self.governor.wake_word_active = True
            self._frame_gate.set_directive("process")
            self.session.open(trigger="wake_word")
            log.info("Session opened via wake word")
            self.event_log.set_session_id(self.session.session_id)
            self.event_log.emit("session_lifecycle", action="opened", trigger="wake_word")
            asyncio.get_event_loop().create_task(self._start_pipeline())

    async def _handle_hotkey(self, cmd: str) -> None:
        if cmd == "toggle":
            if self.session.is_active:
                await self._close_session(reason="hotkey")
            else:
                self._acknowledge("activation")
                self.session.open(trigger="hotkey")
                self.event_log.set_session_id(self.session.session_id)
                self.event_log.emit("session_lifecycle", action="opened", trigger="hotkey")
                await self._start_pipeline()
        elif cmd == "open":
            self._acknowledge("activation")
            self.session.open(trigger="hotkey")
            self.event_log.set_session_id(self.session.session_id)
            self.event_log.emit("session_lifecycle", action="opened", trigger="hotkey")
            await self._start_pipeline()
        elif cmd == "close":
            await self._close_session(reason="hotkey")
        elif cmd == "scan":
            await self._handle_scan()
        elif cmd == "status":
            log.info(
                "Status: session=%s presence=%s queue=%d pipeline=%s",
                self.session.state,
                self.presence.score,
                self.notifications.pending_count,
                "running" if self._pipeline_task is not None else "idle",
            )

    async def _close_session(self, reason: str) -> None:
        """Close the active session and stop the pipeline."""
        await self._stop_pipeline()
        self._acknowledge("deactivation")
        if self.session.is_active:
            duration = time.monotonic() - self.session._opened_at
            self.event_log.emit(
                "session_lifecycle", action="closed", reason=reason, duration_s=round(duration, 1)
            )
        self.event_log.set_session_id(None)
        self.session.close(reason=reason)

    async def _handle_scan(self) -> None:
        """Capture a high-res frame from BRIO and extract text via Gemini."""
        if not self.workspace_monitor.has_camera("operator"):
            log.warning("Scan requested but no operator camera available")
            return

        self.workspace_monitor._webcam_capturer.reset_cooldown("operator")
        frame_b64 = self.workspace_monitor._webcam_capturer.capture("operator")
        if frame_b64 is None:
            log.warning("Scan: failed to capture frame")
            return

        try:
            client = self.workspace_monitor._analyzer._get_client()
            response = await client.chat.completions.create(
                model=self.workspace_monitor._analyzer.model,
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

    async def _ntfy_callback(self, notification) -> None:
        """Handle incoming ntfy notification."""
        self.notifications.enqueue(notification)
        log.info(
            "Queued ntfy notification: %s (priority=%s)",
            notification.title,
            notification.priority,
        )

    async def _proactive_delivery_loop(self) -> None:
        """Periodically check for deliverable notifications.

        When presence is detected, context gate passes, and there are
        queued notifications, deliver them via TTS.
        """
        while self._running:
            try:
                await asyncio.sleep(_PROACTIVE_CHECK_INTERVAL_S)
                if self.notifications.pending_count == 0:
                    continue
                if self.session.is_active:
                    continue

                presence = self.presence.score
                if presence == "likely_absent":
                    continue

                gate_result = self.gate.check()
                if not gate_result.eligible:
                    log.debug("Proactive delivery blocked: %s", gate_result.reason)
                    continue

                # Deliver next notification
                notification = self.notifications.next()
                if notification is None:
                    continue

                spoken = format_notification(notification.title, notification.message)
                log.info("Delivering notification: %s", spoken)
                try:
                    audio = self.tts.synthesize(spoken, use_case="notification")
                    # Audio playback will be handled by Pipecat transport
                    # when fully wired. For now, log that we produced audio.
                    log.info("TTS produced %d bytes for notification", len(audio))
                except Exception:
                    log.exception("TTS failed for notification")

            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Error in proactive delivery loop")

    async def _perception_loop(self) -> None:
        """Run perception fast tick + governor evaluation on cadence."""
        while self._running:
            try:
                await asyncio.sleep(self.cfg.perception_fast_tick_s)

                # Fast tick: read sensors, produce EnvironmentState
                state = self.perception.tick()

                # Governor: evaluate state → directive
                directive = self.governor.evaluate(state)

                # Apply directive to FrameGate
                self._frame_gate.set_directive(directive)

                # Apply directive to session
                if directive == "pause" and self.session.is_active and not self.session.is_paused:
                    self.session.pause(reason=f"governor:{state.activity_mode}")
                elif directive == "process" and self.session.is_paused:
                    self.session.resume()
                elif directive == "withdraw" and self.session.is_active:
                    await self._close_session(reason="operator_absent")

                # Update context gate with latest state
                self.gate.set_environment_state(state)

            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Error in perception loop")

    async def run(self) -> None:
        """Main daemon loop."""
        log.info("Hapax Voice daemon starting (backend=%s)", self.cfg.backend)

        # Start hotkey server
        await self.hotkey.start()

        # Load wake word model (non-blocking, logs warning if unavailable)
        self.wake_word.load()

        # Load chime sounds
        if self.cfg.chime_enabled:
            self.chime_player.load()

        # Start audio input
        self._audio_input.start()
        if self._audio_input.is_active:
            self.event_log.emit("audio_input_started")
            log.info("  Audio input: active (source=%s)", self.cfg.audio_input_source)
        else:
            self.event_log.emit("audio_input_failed", error="Stream not active after start")
            log.info("  Audio input: unavailable (visual-only mode)")

        log.info("Subsystems initialized:")
        log.info("  Backend: %s", self.cfg.backend)
        log.info("  Session: silence_timeout=%ds", self.cfg.silence_timeout_s)
        log.info(
            "  Presence: window=%dmin, threshold=%.1f",
            self.cfg.presence_window_minutes,
            self.cfg.presence_vad_threshold,
        )
        log.info(
            "  Context gate: volume_threshold=%.0f%%",
            self.cfg.context_gate_volume_threshold * 100,
        )
        log.info("  Notifications: %d pending", self.notifications.pending_count)
        ww_loaded = self.wake_word.is_loaded
        log.info(
            "  Wake word: %s (engine=%s)",
            "loaded" if ww_loaded else "unavailable",
            self.cfg.wake_word_engine,
        )
        log.info(
            "  Workspace monitor: %s (cameras: %s)",
            "enabled" if self.cfg.screen_monitor_enabled else "disabled",
            "BRIO+C920" if self.cfg.webcam_enabled else "screen-only",
        )

        # Cleanup old event logs on startup
        self.event_log.cleanup()

        # Start background tasks
        self._background_tasks.append(asyncio.create_task(self._proactive_delivery_loop()))
        self._background_tasks.append(
            asyncio.create_task(subscribe_ntfy(_NTFY_BASE_URL, _NTFY_TOPICS, self._ntfy_callback))
        )
        self._background_tasks.append(asyncio.create_task(self.workspace_monitor.run()))
        if self._audio_input.is_active:
            self._background_tasks.append(asyncio.create_task(self._audio_loop()))

        self._background_tasks.append(asyncio.create_task(self._perception_loop()))

        try:
            while self._running:
                # Session timeout check
                if self.session.is_active and self.session.is_timed_out:
                    msg = session_end_message(self.notifications.pending_count)
                    log.info("Session timeout: %s", msg)
                    await self._close_session(reason="silence_timeout")

                # Prune expired notifications
                self.notifications.prune_expired()

                await asyncio.sleep(1)

                # Update activity mode from latest workspace analysis
                analysis = self.workspace_monitor.latest_analysis
                if analysis is not None:
                    mode = classify_activity_mode(analysis)
                    self.gate.set_activity_mode(mode)
                    self.perception.update_slow_fields(activity_mode=mode)
        finally:
            # Stop any running pipeline
            await self._stop_pipeline()

            # Stop audio input
            self._audio_input.stop()

            self.chime_player.close()

            # Flush observability
            self.event_log.close()
            self.tracer.flush()

            # Cancel background tasks
            for task in self._background_tasks:
                task.cancel()
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

            await self.hotkey.stop()
            log.info("Hapax Voice daemon stopped")

    def stop(self) -> None:
        self._running = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Hapax Voice daemon")
    parser.add_argument("--config", type=str, help="Path to config YAML")
    parser.add_argument("--check", action="store_true", help="Verify config and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    cfg = load_config(Path(args.config) if args.config else None)
    if args.check:
        print(cfg.model_dump_json(indent=2))
        return

    daemon = VoiceDaemon(cfg=cfg)
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, daemon.stop)
    loop.add_signal_handler(signal.SIGHUP, daemon.workspace_monitor.reload_context)
    try:
        loop.run_until_complete(daemon.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
