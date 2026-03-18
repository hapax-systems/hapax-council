"""Entry point for hapax-voice daemon."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from agents.hapax_voice._perception_state_writer import write_perception_state
from agents.hapax_voice.activity_mode import classify_activity_mode
from agents.hapax_voice.audio_input import AudioInputStream
from agents.hapax_voice.chime_player import ChimePlayer
from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.config import load_config
from agents.hapax_voice.context_gate import ContextGate
from agents.hapax_voice.event_log import EventLog
from agents.hapax_voice.executor import ExecutorRegistry, ScheduleQueue
from agents.hapax_voice.frame_gate import FrameGate
from agents.hapax_voice.governance import VetoResult
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.hotkey import HotkeyServer
from agents.hapax_voice.notification_queue import NotificationQueue
from agents.hapax_voice.ntfy_listener import subscribe_ntfy
from agents.hapax_voice.perception import EnvironmentState, PerceptionEngine
from agents.hapax_voice.persona import format_notification, session_end_message
from agents.hapax_voice.presence import PresenceDetector
from agents.hapax_voice.primitives import Event
from agents.hapax_voice.screen_models import CameraConfig

if TYPE_CHECKING:
    from agents.hapax_voice.hyprland_listener import FocusEvent
from agents.hapax_voice.session import SessionManager
from agents.hapax_voice.tts import TTSManager

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
from agents.hapax_voice.wake_word import WakeWordDetector
from agents.hapax_voice.wake_word_porcupine import PorcupineWakeWord
from agents.hapax_voice.wake_word_whisper import WhisperWakeWord
from agents.hapax_voice.workspace_monitor import WorkspaceMonitor

log = logging.getLogger("hapax_voice")

_DEFAULT_VETO_RESULT = VetoResult(allowed=True)


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

        # Consent registry (loads from axioms/contracts/, empty = conservative default)
        from shared.governance.consent import ConsentRegistry

        self.consent_registry = ConsentRegistry()
        _consent_count = self.consent_registry.load()
        log.info("Loaded %d consent contracts", _consent_count)

        # Operator principal — sovereign, single-user axiom
        from shared.governance.principal import Principal, PrincipalKind

        self._operator_principal = Principal(
            id="operator",
            kind=PrincipalKind.SOVEREIGN,
        )
        # Voice daemon principal — bound, delegated by operator
        self._daemon_principal = self._operator_principal.delegate(
            child_id="hapax-voice",
            scope=frozenset(
                {
                    "audio",
                    "video",
                    "transcription",
                    "presence",
                    "biometrics",
                    "workspace",
                    "notifications",
                }
            ),
        )

        # Perception layer
        self.perception = PerceptionEngine(
            presence=self.presence,
            workspace_monitor=self.workspace_monitor,
        )

        # Register perception backends (availability-gated)
        self._register_perception_backends()

        # Perception events (Phase 2 extension points)
        self.wake_word_event: Event[None] = Event()
        self.focus_event: Event[FocusEvent] = Event()

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
                self.focus_event.emit(time.monotonic(), event)
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

        # Wake word async signaling — sync callback sets event,
        # coroutine awaits it and atomically starts the pipeline
        self._wake_word_signal = asyncio.Event()

        # Observability
        events_dir = Path.home() / ".local" / "share" / "hapax-voice"
        self.event_log = EventLog(
            base_dir=events_dir,
            retention_days=self.cfg.observability_events_retention_days,
            enabled=self.cfg.observability_events_enabled,
        )
        # Wire observability into subsystems
        self.presence.set_event_log(self.event_log)
        self.gate.set_event_log(self.event_log)
        self.notifications.set_event_log(self.event_log)
        self.workspace_monitor.set_event_log(self.event_log)
        if self._presence_engine is not None:
            self._presence_engine.set_event_log(self.event_log)

        # Wire consent curtailment into event log (deferred — consent_tracker not yet created)

        # Consent tracking (interpersonal_transparency axiom)
        from agents.hapax_voice.consent_state import ConsentStateTracker

        self.consent_tracker = ConsentStateTracker(
            debounce_s=self.cfg.consent_debounce_s,
            absence_clear_s=self.cfg.consent_absence_clear_s,
        )
        self.consent_tracker.set_event_log(self.event_log)
        # Wire consent curtailment into event log
        self.event_log.set_consent_fn(lambda: self.consent_tracker.persistence_allowed)
        self._consent_session_active = False
        self._perception_tier = self.cfg.perception_tier

        # Lightweight voice pipeline (replaces Pipecat)
        from agents.hapax_voice.conversation_buffer import ConversationBuffer
        from agents.hapax_voice.resident_stt import ResidentSTT

        self._conversation_buffer = ConversationBuffer()
        self._resident_stt = ResidentSTT(
            model=self.cfg.local_stt_model
            if "whisper" in self.cfg.local_stt_model.lower()
            or "distil" in self.cfg.local_stt_model.lower()
            else "distil-large-v3",
            device="cuda",
        )
        self._conversation_pipeline = None

        # Application-level echo cancellation (replaces broken PipeWire AEC)
        self._echo_canceller = None
        if self.cfg.aec_enabled:
            try:
                from agents.hapax_voice.echo_canceller import EchoCanceller

                self._echo_canceller = EchoCanceller(frame_size=480, tail_ms=self.cfg.aec_tail_ms)
            except Exception:
                log.warning("Echo canceller init failed, continuing without AEC", exc_info=True)

        # Audio preprocessing (highpass + noise gate + normalization)
        from agents.hapax_voice.audio_preprocess import AudioPreprocessor

        self._audio_preprocessor = AudioPreprocessor()

        # Multi-mic noise reference (C920 webcam mics as ambient reference)
        from agents.hapax_voice.multi_mic import NoiseReference

        self._noise_reference = NoiseReference(
            room_sources=[
                "HD Pro Webcam C920",  # any C920 mic — room noise reference
            ],
        )
        self._noise_reference.start()

        # Speaker identification (operator vs guest voice gating)
        self._speaker_identifier = None
        try:
            from agents.hapax_voice.speaker_id import SpeakerIdentifier

            enrollment_path = Path.home() / ".local/share/hapax-voice/speaker_embedding.npy"
            if enrollment_path.exists():
                self._speaker_identifier = SpeakerIdentifier(enrollment_path=enrollment_path)
                # Pre-load pyannote model at startup (takes ~8s, avoids first-utterance delay)
                import numpy as np

                _dummy = np.zeros(16000, dtype=np.float32)
                self._speaker_identifier.extract_embedding(_dummy, 16000)
                log.info("Speaker identifier loaded from %s (pyannote warm)", enrollment_path)
            else:
                log.warning(
                    "No speaker enrollment found at %s — speaker gating disabled", enrollment_path
                )
        except Exception:
            log.warning("Speaker identifier init failed — speaker gating disabled", exc_info=True)

        # Bridge phrase engine (pre-synthesized contextual gap fillers)
        from agents.hapax_voice.bridge_engine import BridgeEngine

        self._bridge_engine = BridgeEngine()

        # Salience-based model routing
        self._salience_router = None
        self._salience_embedder = None
        self._salience_concern_graph = None
        self._salience_diagnostics = None
        self._context_distillation: str = ""
        if self.cfg.salience_enabled:
            try:
                from agents.hapax_voice.salience.concern_graph import ConcernGraph
                from agents.hapax_voice.salience.embedder import Embedder
                from agents.hapax_voice.salience_router import SalienceRouter

                self._salience_embedder = Embedder(model_name=self.cfg.salience_model)
                if self._salience_embedder.available:
                    self._salience_concern_graph = ConcernGraph(
                        dim=self._salience_embedder.dim,
                    )
                    self._salience_router = SalienceRouter(
                        embedder=self._salience_embedder,
                        concern_graph=self._salience_concern_graph,
                        thresholds=self.cfg.salience_thresholds,
                        weights=self.cfg.salience_weights,
                    )

                    from agents.hapax_voice.salience.diagnostics import SalienceDiagnostics

                    self._salience_diagnostics = SalienceDiagnostics(
                        router=self._salience_router,
                        concern_graph=self._salience_concern_graph,
                    )
                    log.info(
                        "Salience router initialized (%dd embeddings)", self._salience_embedder.dim
                    )
                else:
                    log.warning("Salience embedder unavailable, falling back to heuristic routing")
            except Exception:
                log.warning(
                    "Salience router init failed, falling back to heuristic routing", exc_info=True
                )

        # Actuation layer
        self.schedule_queue = ScheduleQueue()
        self.executor_registry = ExecutorRegistry()
        self._shared_pa = None  # lazy init in run() if needed

        # Resource arbiter for contention resolution between governance chains
        from agents.hapax_voice.arbiter import ResourceArbiter
        from agents.hapax_voice.resource_config import DEFAULT_PRIORITIES

        self.arbiter = ResourceArbiter(priorities=DEFAULT_PRIORITIES)

        self._setup_actuation()

    # ------------------------------------------------------------------
    # Actuation setup
    # ------------------------------------------------------------------

    def _setup_actuation(self) -> None:
        """Wire MC/OBS governance → ScheduleQueue/ExecutorRegistry."""
        # MC actuation: MIDI clock → governance → schedule → audio playback
        if self.cfg.mc_enabled:
            try:
                self._setup_mc_actuation()
            except Exception:
                log.exception("MC actuation setup failed")

        # OBS actuation: perception tick → governance → command → scene switch
        if self.cfg.obs_enabled:
            try:
                self._setup_obs_actuation()
            except Exception:
                log.exception("OBS actuation setup failed")

        # Feedback behaviors: actuation events → perception behaviors (closed loop)
        from agents.hapax_voice.feedback import wire_feedback_behaviors

        feedback_behaviors = wire_feedback_behaviors(
            actuation_event=self.executor_registry.actuation_event,
            watermark=self.perception.min_watermark,
        )
        self.perception.behaviors.update(feedback_behaviors)
        log.info("Feedback behaviors wired: %s", list(feedback_behaviors.keys()))

    def _setup_mc_actuation(self) -> None:
        """Wire MC governance pipeline to AudioExecutor."""
        from agents.hapax_voice.audio_executor import AudioExecutor
        from agents.hapax_voice.mc_governance import compose_mc_governance
        from agents.hapax_voice.sample_bank import SampleBank

        # Load samples
        sample_bank = SampleBank(
            base_dir=Path(self.cfg.mc_sample_dir).expanduser(),
            sample_rate=self.cfg.mc_sample_rate,
        )
        count = sample_bank.load()
        if count == 0:
            log.info("No MC samples found, MC actuation disabled")
            return

        # Shared PyAudio (lazy init)
        self._ensure_shared_pa()

        # Register AudioExecutor
        audio_exec = AudioExecutor(pa=self._shared_pa, sample_bank=sample_bank)
        self.executor_registry.register(audio_exec)

        # Find MIDI clock tick event from backends
        midi_backend = self.perception.registered_backends.get("midi_clock")
        if midi_backend is None:
            log.info("No MIDI clock backend, MC governance cannot fire")
            return

        # Compose MC governance: tick → fused → schedule

        mc_tick = Event[float]()
        mc_output = compose_mc_governance(
            trigger=mc_tick,
            behaviors=self.perception.behaviors,
        )

        def _on_mc_schedule(timestamp: float, schedule: Schedule | None) -> None:
            if schedule is not None and schedule.command.action != "silence":
                self.schedule_queue.enqueue(schedule)
                self.event_log.emit(
                    "mc_schedule_enqueued",
                    action=schedule.command.action,
                    wall_time=schedule.wall_time,
                )

        mc_output.subscribe(_on_mc_schedule)
        self._mc_tick_event = mc_tick
        log.info("MC actuation wired: MIDI → governance → schedule → audio")

    def _setup_obs_actuation(self) -> None:
        """Wire OBS governance pipeline to OBSExecutor."""
        from agents.hapax_voice.obs_executor import OBSExecutor
        from agents.hapax_voice.obs_governance import compose_obs_governance

        obs_exec = OBSExecutor(
            host=self.cfg.obs_host,
            port=self.cfg.obs_port,
        )
        self.executor_registry.register(obs_exec)

        obs_tick = Event[float]()
        obs_output = compose_obs_governance(
            trigger=obs_tick,
            behaviors=self.perception.behaviors,
        )

        def _on_obs_command(timestamp: float, cmd: Command | None) -> None:
            if cmd is None:
                return
            from agents.hapax_voice.arbiter import ResourceClaim
            from agents.hapax_voice.resource_config import DEFAULT_PRIORITIES, RESOURCE_MAP

            resource = RESOURCE_MAP.get(cmd.action)
            if resource:
                claim = ResourceClaim(
                    resource=resource,
                    chain=cmd.trigger_source,
                    priority=DEFAULT_PRIORITIES.get((resource, cmd.trigger_source), 0),
                    command=cmd,
                )
                self.arbiter.claim(claim)
            else:
                self.executor_registry.dispatch(cmd)
            self.event_log.emit(
                "obs_command_dispatched",
                action=cmd.action,
                transition=cmd.params.get("transition", ""),
            )

        obs_output.subscribe(_on_obs_command)
        self._obs_tick_event = obs_tick
        log.info("OBS actuation wired: perception → governance → command → scene")

    def _ensure_shared_pa(self) -> None:
        """Create shared PyAudio instance if not already created."""
        if self._shared_pa is not None:
            return
        try:
            import pyaudio

            self._shared_pa = pyaudio.PyAudio()
        except Exception:
            log.warning("PyAudio not available, audio executors will be unavailable")

    # ------------------------------------------------------------------
    # Perception backend registration
    # ------------------------------------------------------------------

    def _register_perception_backends(self) -> None:
        """Instantiate and register available perception backends."""
        try:
            from agents.hapax_voice.backends.pipewire import PipeWireBackend

            self.perception.register_backend(PipeWireBackend())
        except Exception:
            log.info("PipeWireBackend not available, skipping")

        try:
            from agents.hapax_voice.backends.hyprland import HyprlandBackend

            self.perception.register_backend(HyprlandBackend())
        except Exception:
            log.info("HyprlandBackend not available, skipping")

        try:
            from agents.hapax_voice.backends.watch import WatchBackend

            self.perception.register_backend(WatchBackend())
        except Exception:
            log.info("WatchBackend not available, skipping")

        try:
            from agents.hapax_voice.backends.health import HealthBackend

            self.perception.register_backend(HealthBackend())
        except Exception:
            log.info("HealthBackend not available, skipping")

        try:
            from agents.hapax_voice.backends.circadian import CircadianBackend

            self.perception.register_backend(CircadianBackend())
        except Exception:
            log.info("CircadianBackend not available, skipping")

        # Studio ingestion backend (CLAP audio classification)
        try:
            from agents.hapax_voice.backends.studio_ingestion import StudioIngestionBackend

            self.perception.register_backend(StudioIngestionBackend())
        except Exception:
            log.info("StudioIngestionBackend not available, skipping")

        # Vision backend (YOLO object detection + pose + tracking)
        try:
            from agents.hapax_voice.backends.vision import VisionBackend

            webcam = getattr(self.workspace_monitor, "_webcam_capturer", None)
            if webcam is not None:
                self.perception.register_backend(VisionBackend(webcam_capturer=webcam))
        except Exception:
            log.info("VisionBackend not available, skipping")

        # Device state backend (USB, network)
        try:
            from agents.hapax_voice.backends.devices import DeviceStateBackend

            self.perception.register_backend(DeviceStateBackend())
        except Exception:
            log.info("DeviceStateBackend not available, skipping")

        # Local LLM backend (WS5: fast perception classification)
        try:
            from agents.hapax_voice.backends.local_llm import LocalLLMBackend

            self._local_llm_backend = LocalLLMBackend()
            self.perception.register_backend(self._local_llm_backend)
        except Exception:
            self._local_llm_backend = None
            log.info("LocalLLMBackend not available, skipping")

        # MIDI clock backend (for MC governance)
        try:
            from agents.hapax_voice.backends.midi_clock import MidiClockBackend

            self.perception.register_backend(
                MidiClockBackend(
                    port_name=self.cfg.midi_port_name,
                    beats_per_bar=self.cfg.midi_beats_per_bar,
                )
            )
        except Exception:
            log.info("MidiClockBackend not available, skipping")

        # Input activity backend (keyboard/mouse via logind)
        try:
            from agents.hapax_voice.backends.input_activity import InputActivityBackend

            self.perception.register_backend(
                InputActivityBackend(idle_threshold_s=self.cfg.input_idle_threshold_s)
            )
        except Exception:
            log.info("InputActivityBackend not available, skipping")

        # Bluetooth phone presence (paired Pixel 10)
        try:
            from agents.hapax_voice.backends.bt_presence import BTPresenceBackend

            self.perception.register_backend(BTPresenceBackend())
        except Exception:
            log.info("BTPresenceBackend not available, skipping")

        # Phone media (AVRCP track info via Bluetooth)
        try:
            from agents.hapax_voice.backends.phone_media import PhoneMediaBackend

            self.perception.register_backend(PhoneMediaBackend())
        except Exception:
            log.info("PhoneMediaBackend not available, skipping")

        # Phone SMS (MAP via Bluetooth)
        try:
            from agents.hapax_voice.backends.phone_messages import PhoneMessagesBackend

            self.perception.register_backend(PhoneMessagesBackend())
        except Exception:
            log.info("PhoneMessagesBackend not available, skipping")

        # Phone calls (HFP via PipeWire Telephony)
        try:
            from agents.hapax_voice.backends.phone_calls import PhoneCallsBackend

            self.perception.register_backend(PhoneCallsBackend())
        except Exception:
            log.info("PhoneCallsBackend not available, skipping")

        # Phone unified awareness (KDE Connect)
        try:
            from agents.hapax_voice.backends.phone_awareness import PhoneAwarenessBackend

            self.perception.register_backend(PhoneAwarenessBackend())
        except Exception:
            log.info("PhoneAwarenessBackend not available, skipping")

        # Bayesian presence engine (fuses all signals into presence probability)
        if self.cfg.presence_bayesian_enabled:
            try:
                from agents.hapax_voice.presence_engine import PresenceEngine

                self._presence_engine = PresenceEngine(
                    prior=self.cfg.presence_prior,
                    enter_threshold=self.cfg.presence_enter_threshold,
                    exit_threshold=self.cfg.presence_exit_threshold,
                    enter_ticks=self.cfg.presence_enter_ticks,
                    exit_ticks=self.cfg.presence_exit_ticks,
                    signal_weights=self.cfg.presence_signal_weights,
                )
                # event_log wired later (created after backend registration)
                self.perception.register_backend(self._presence_engine)
            except Exception:
                self._presence_engine = None
                log.warning("PresenceEngine not available, skipping", exc_info=True)
        else:
            self._presence_engine = None

    # ------------------------------------------------------------------
    # Wake word engine selection
    # ------------------------------------------------------------------

    def _create_wake_word_detector(self):
        """Instantiate wake word detector based on config.

        Engine priority:
        - "whisper": VAD + faster-whisper-tiny (no training, no license)
        - "porcupine": Picovoice Porcupine (requires access key)
        - "oww": OpenWakeWord (requires trained model)
        """
        engine = self.cfg.wake_word_engine
        if engine == "porcupine":
            detector = PorcupineWakeWord(sensitivity=self.cfg.porcupine_sensitivity)
            return detector
        if engine == "whisper":
            return WhisperWakeWord(model_size="tiny")
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

            # Wake word gets RAW audio — Porcupine is designed for unprocessed
            # mic input. AEC/noise gate/normalization can attenuate or distort
            # the signal enough to prevent detection.
            _wake_buf.extend(frame)

            # AEC: process mic frame through echo canceller before distribution
            if self._echo_canceller is not None:
                frame = self._echo_canceller.process(frame)

            # Multi-mic noise subtraction (C920 room reference)
            if self._noise_reference is not None:
                frame = self._noise_reference.subtract(frame)

            # Audio preprocessing: highpass + noise gate + normalization
            if self._audio_preprocessor is not None:
                frame = self._audio_preprocessor.process(frame)

            # Accumulate for exact-sized consumer chunks (processed audio)
            _vad_buf.extend(frame)

            # Conversation buffer: feed every frame (inline, no copy overhead)
            if self._conversation_buffer.is_active:
                self._conversation_buffer.feed_audio(frame)

            # Presence/VAD: drain all complete 512-sample chunks
            while len(_vad_buf) >= _VAD_CHUNK:
                chunk = bytes(_vad_buf[:_VAD_CHUNK])
                del _vad_buf[:_VAD_CHUNK]
                try:
                    self.presence.process_audio_frame(chunk)
                    vad_prob = self.presence._latest_vad_confidence
                    # Feed VAD probability to conversation buffer
                    if self._conversation_buffer.is_active:
                        self._conversation_buffer.update_vad(vad_prob)
                    # Feed VAD probability to whisper wake word (needs speech timing)
                    if isinstance(self.wake_word, WhisperWakeWord):
                        self.wake_word.set_vad_probability(vad_prob)
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

        For backend="local", starts the lightweight conversation pipeline.
        For backend="gemini", connects a Gemini Live session.
        """
        if self._conversation_pipeline is not None and self._conversation_pipeline.is_active:
            log.warning("Pipeline already running, skipping start")
            return

        backend = self.cfg.backend

        if backend == "gemini":
            await self._start_gemini_session()
        else:
            await self._start_conversation_pipeline()

    def _precompute_pipeline_deps(self) -> None:
        """Precompute pipeline dependencies at startup so session open is instant.

        Called once during daemon init. Tools, consent reader, and callbacks
        are stable across sessions. Only the system prompt needs refreshing
        per session (policy + screen context depend on current environment).
        """
        from agents.hapax_voice.conversational_policy import get_policy
        from agents.hapax_voice.env_context import serialize_environment
        from agents.hapax_voice.tools_openai import get_openai_tools

        # Tools (stable across sessions for operator mode)
        self._precomputed_tools = None
        self._precomputed_handlers: dict = {}
        if self.cfg.tools_enabled:
            tool_kwargs: dict = {
                "guest_mode": False,
                "config": self.cfg,
                "webcam_capturer": getattr(self.workspace_monitor, "_webcam_capturer", None),
                "screen_capturer": getattr(self.workspace_monitor, "_screen_capturer", None),
            }
            vfx = getattr(self.tts, "vocal_fx", None)
            if vfx is not None:
                import inspect

                sig = inspect.signature(get_openai_tools)
                if "vocal_fx" in sig.parameters:
                    tool_kwargs["vocal_fx"] = vfx
            self._precomputed_tools, self._precomputed_handlers = get_openai_tools(**tool_kwargs)

        # Consent reader (stable, reloads contracts on session start)
        self._precomputed_consent_reader = None
        try:
            from shared.governance.consent_reader import ConsentGatedReader

            self._precomputed_consent_reader = ConsentGatedReader.create()
        except Exception:
            log.warning("ConsentGatedReader unavailable, proceeding without consent filtering")

        # Callbacks (closures over self — stable)
        self._env_context_fn = lambda: serialize_environment(
            self.perception.latest or EnvironmentState(timestamp=0),
            self.workspace_monitor.latest_analysis,
            self.gate._ambient_result,
            perception_tier=self._perception_tier.value,
        )
        self._ambient_fn = lambda: self.gate._ambient_result
        self._policy_fn = lambda: get_policy(
            env=self.perception.latest,
            guest_mode=self.session.is_guest_mode,
        )

        log.info("Pipeline dependencies precomputed")

    def _pause_vision_for_conversation(self) -> None:
        """Pause vision inference to free ~2-3GB VRAM for voice models."""
        for backend in self.perception.registered_backends.values():
            if hasattr(backend, "pause_for_conversation"):
                try:
                    backend.pause_for_conversation()
                except Exception:
                    log.debug("Vision pause failed", exc_info=True)

    def _resume_vision_after_conversation(self) -> None:
        """Resume vision inference after conversation ends."""
        for backend in self.perception.registered_backends.values():
            if hasattr(backend, "resume_after_conversation"):
                try:
                    backend.resume_after_conversation()
                except Exception:
                    log.debug("Vision resume failed", exc_info=True)

    def _refresh_concern_graph(self) -> None:
        """Refresh concern anchors from current infrastructure state.

        Called on perception tick cadence and at session start.
        """
        if self._salience_embedder is None or self._salience_concern_graph is None:
            return

        try:
            from agents.hapax_voice.salience.anchor_builder import build_anchors

            env = self.perception.latest if hasattr(self, "perception") else None

            # Gather notification texts (read-only peek into queue)
            notif_texts: list[str] = []
            if hasattr(self, "notifications"):
                for n in self.notifications._items[:5]:
                    notif_texts.append(getattr(n, "message", str(n)))

            anchors = build_anchors(
                env_state=env,
                notifications=notif_texts,
            )

            if anchors:
                texts = [a.text for a in anchors]
                embeddings = self._salience_embedder.embed_batch(texts)
                self._salience_concern_graph.refresh(anchors, embeddings)
        except Exception:
            log.debug("Concern graph refresh failed (non-fatal)", exc_info=True)

    def _refresh_context_distillation(self) -> None:
        """Generate context distillation for LOCAL tier prompts."""
        try:
            from agents.hapax_voice.salience.anchor_builder import build_context_distillation

            env = self.perception.latest if hasattr(self, "perception") else None
            notif_count = self.notifications.pending_count if hasattr(self, "notifications") else 0

            self._context_distillation = build_context_distillation(
                env_state=env,
                notification_count=notif_count,
            )

            # Push to active pipeline if running
            if self._conversation_pipeline is not None:
                self._conversation_pipeline._context_distillation = self._context_distillation
        except Exception:
            log.debug("Context distillation refresh failed (non-fatal)", exc_info=True)

    async def _start_conversation_pipeline(self) -> None:
        """Start the lightweight conversation pipeline.

        Most dependencies are precomputed at startup. This method only builds
        the fresh system prompt (policy + screen context) and creates the
        pipeline object. Should complete in <50ms.
        """
        from agents.hapax_voice.conversation_pipeline import ConversationPipeline
        from agents.hapax_voice.conversational_policy import get_policy
        from agents.hapax_voice.persona import screen_context_block, system_prompt
        from agents.hapax_voice.tools_openai import get_openai_tools

        # Fresh system prompt (only part that changes per session)
        policy_block = get_policy(
            env=self.perception.latest,
            guest_mode=self.session.is_guest_mode,
        )
        prompt = system_prompt(
            guest_mode=self.session.is_guest_mode,
            policy_block=policy_block,
        )
        screen_ctx = screen_context_block(self.workspace_monitor.latest_analysis)
        if screen_ctx:
            prompt += screen_ctx

        # Guest mode needs fresh tools (restricted set)
        if self.session.is_guest_mode and self.cfg.tools_enabled:
            tools, tool_handlers = get_openai_tools(
                guest_mode=True,
                config=self.cfg,
                webcam_capturer=getattr(self.workspace_monitor, "_webcam_capturer", None),
                screen_capturer=getattr(self.workspace_monitor, "_screen_capturer", None),
            )
        else:
            tools = self._precomputed_tools
            tool_handlers = self._precomputed_handlers

        # Pre-synthesize bridge phrases on first session (TTS is warm by now)
        if not self._bridges_presynthesized:
            self._bridge_engine.presynthesize_all(self.tts)
            self._bridges_presynthesized = True

        self._conversation_pipeline = ConversationPipeline(
            stt=self._resident_stt,
            tts_manager=self.tts,
            system_prompt=prompt,
            tools=tools or None,
            tool_handlers=tool_handlers,
            llm_model=self.cfg.llm_model,
            event_log=self.event_log,
            conversation_buffer=self._conversation_buffer,
            consent_reader=self._precomputed_consent_reader,
            env_context_fn=self._env_context_fn,
            ambient_fn=self._ambient_fn,
            policy_fn=self._policy_fn,
            screen_capturer=getattr(self.workspace_monitor, "_screen_capturer", None),
            echo_canceller=self._echo_canceller,
            bridge_engine=self._bridge_engine,
        )

        # Wire salience router and context distillation into pipeline
        if self._salience_router is not None:
            self._conversation_pipeline._salience_router = self._salience_router
            self._conversation_pipeline._salience_diagnostics = self._salience_diagnostics
            self._refresh_concern_graph()
            self._refresh_context_distillation()
            self._conversation_pipeline._context_distillation = self._context_distillation

        # Pause vision to free GPU memory for voice models
        self._pause_vision_for_conversation()

        await self._conversation_pipeline.start()
        log.info("Conversation pipeline started (mic stays shared)")

        # Run the conversation loop as a background task
        self._pipeline_task = asyncio.create_task(self._conversation_loop())

    async def _start_gemini_session(self) -> None:
        """Connect and start a Gemini Live session."""
        from agents.hapax_voice.conversational_policy import get_policy
        from agents.hapax_voice.gemini_live import GeminiLiveSession
        from agents.hapax_voice.persona import system_prompt

        policy_block = get_policy(
            env=self.perception.latest,
            guest_mode=self.session.is_guest_mode,
        )
        prompt = system_prompt(
            guest_mode=self.session.is_guest_mode,
            policy_block=policy_block,
        )
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

    async def _conversation_loop(self) -> None:
        """Background task: poll conversation buffer for utterances.

        Runs while the conversation pipeline is active. Checks every
        50ms for complete utterances from the ConversationBuffer and
        feeds them to the pipeline for processing.

        Speaker verification: accumulates speech audio across utterances
        until enough is collected (~3s) for reliable pyannote embedding.
        Once the operator is verified, the session is trusted until it
        closes. Non-operator audio is dropped.
        """
        # Session-scoped speaker verification state
        _speaker_verified = False  # True once operator confirmed
        _speaker_audio_buf: list[bytes] = []  # accumulate for verification
        _speaker_audio_samples = 0  # total samples accumulated
        _VERIFY_MIN_SAMPLES = 16000 * 3  # 3s of 16kHz audio for reliable ID

        try:
            while (
                self._conversation_pipeline is not None
                and self._conversation_pipeline.is_active
                and self._running
            ):
                utterance = self._conversation_buffer.get_utterance()
                if utterance is not None:
                    # Speaker verification gate
                    if self._speaker_identifier is not None and not _speaker_verified:
                        _speaker_audio_buf.append(utterance)
                        _speaker_audio_samples += len(utterance) // 2  # int16 = 2 bytes/sample

                        if _speaker_audio_samples >= _VERIFY_MIN_SAMPLES:
                            # Enough audio accumulated — verify speaker
                            combined = b"".join(_speaker_audio_buf)
                            speaker = await self._verify_speaker(combined)

                            if speaker == "ryan":
                                _speaker_verified = True
                                self.session.set_speaker("ryan", 0.0)
                                log.info("Speaker gate: operator verified, session trusted")
                                # Process all buffered utterances
                                for buffered in _speaker_audio_buf:
                                    self.session.mark_activity()
                                    await self._conversation_pipeline.process_utterance(buffered)
                                    self.session.mark_activity()
                                _speaker_audio_buf.clear()
                                continue
                            elif speaker == "not_ryan":
                                log.info("Speaker gate: DROPPED — not operator")
                                _speaker_audio_buf.clear()
                                _speaker_audio_samples = 0
                                continue
                            else:
                                # Uncertain — keep accumulating, but process
                                # this utterance (fail-open for operator)
                                log.info("Speaker gate: uncertain, accumulating more audio")
                        else:
                            # Not enough audio yet — process anyway (fail-open)
                            # but keep accumulating for verification
                            pass

                    self.session.mark_activity()
                    await self._conversation_pipeline.process_utterance(utterance)
                    self.session.mark_activity()
                else:
                    await asyncio.sleep(0.01)  # 10ms poll (Phase 3d)

                # Session timeout check
                if self.session.is_active and self.session.is_timed_out:
                    log.info("Conversation timed out (silence)")
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Conversation loop error")

    async def _verify_speaker(self, audio_bytes: bytes) -> str:
        """Run speaker verification on accumulated PCM audio.

        Returns "ryan", "not_ryan", or "uncertain".
        Runs pyannote embedding extraction in a thread to avoid blocking.
        Expects at least 3s of audio for reliable identification.
        """
        try:
            import numpy as np

            audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if len(audio) < 8000:  # less than 0.5s — too short even for best-effort
                return "uncertain"

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._speaker_identifier.identify_audio(audio, 16000),
            )
            log.info(
                "Speaker verification: %s (confidence=%.3f, audio=%.1fs)",
                result.label,
                result.confidence,
                len(audio) / 16000,
            )
            return result.label
        except Exception:
            log.debug("Speaker verification failed (fail-open)", exc_info=True)
            return "uncertain"

    async def _stop_pipeline(self) -> None:
        """Stop the active pipeline or Gemini session."""
        if self._gemini_session is not None:
            await self._gemini_session.disconnect()
            self._gemini_session = None
            log.info("Gemini Live session stopped")

        if self._conversation_pipeline is not None:
            await self._conversation_pipeline.stop()
            self._conversation_pipeline = None

        if self._pipeline_task is not None:
            self._pipeline_task.cancel()
            try:
                await self._pipeline_task
            except asyncio.CancelledError:
                pass
            self._pipeline_task = None
            log.info("Conversation pipeline stopped")

        # Clear session-scoped salience state so next session starts fresh
        if self._salience_router is not None:
            self._salience_router._recent_turns.clear()
        if self._salience_concern_graph is not None:
            self._salience_concern_graph._recent_utterances.clear()

        # Resume vision now that conversation is done
        self._resume_vision_after_conversation()

        # No need to restore audio input — mic was never stopped

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
        """Called synchronously from audio loop when wake word is detected.

        Minimal handler: emits event and signals the async processor.
        All state mutations and pipeline start happen in _wake_word_processor()
        to prevent logical races with the perception loop.
        """
        self.wake_word_event.emit(time.monotonic(), None)
        if not self.session.is_active:
            self._wake_word_signal.set()

    async def _wake_word_processor(self) -> None:
        """Await wake word signal, then atomically set up session + pipeline.

        By awaiting _start_pipeline() directly (not create_task), the perception
        loop cannot tick until the pipeline is ready. The state mutations and
        pipeline start are atomic from asyncio's perspective.
        """
        while self._running:
            await self._wake_word_signal.wait()
            self._wake_word_signal.clear()

            if self.session.is_active:
                continue

            # Axiom compliance gate — operator activation overrides soft vetoes
            # but not axiom vetoes (management_governance boundary rules)
            state = self.perception.tick()
            veto = self.governor._veto_chain.evaluate(state)
            if not veto.allowed and "axiom_compliance" in veto.denied_by:
                log.warning("Wake word blocked by axiom compliance: %s", veto.denied_by)
                self._acknowledge("denied")
                continue

            self._acknowledge("activation")
            self.governor.wake_word_active = True
            self._frame_gate.set_directive("process")
            self.session.open(trigger="wake_word")
            self.session.set_speaker("ryan", confidence=1.0)  # Wake word implies operator
            log.info("Session opened via wake word")
            self.event_log.set_session_id(self.session.session_id)
            self.event_log.emit("session_lifecycle", action="opened", trigger="wake_word")
            await self._start_pipeline()

    async def _handle_hotkey(self, cmd: str) -> None:
        if cmd == "toggle":
            if self.session.is_active:
                await self._close_session(reason="hotkey")
            else:
                # Axiom compliance gate — block on axiom vetoes only
                state = self.perception.tick()
                veto = self.governor._veto_chain.evaluate(state)
                if not veto.allowed and "axiom_compliance" in veto.denied_by:
                    log.warning("Hotkey toggle blocked by axiom compliance: %s", veto.denied_by)
                    self._acknowledge("denied")
                    return
                self._acknowledge("activation")
                self.session.open(trigger="hotkey")
                self.session.set_speaker("ryan", confidence=1.0)  # Physical access = operator
                self.event_log.set_session_id(self.session.session_id)
                self.event_log.emit("session_lifecycle", action="opened", trigger="hotkey")
                await self._start_pipeline()
        elif cmd == "open":
            # Axiom compliance gate — block on axiom vetoes only
            state = self.perception.tick()
            veto = self.governor._veto_chain.evaluate(state)
            if not veto.allowed and "axiom_compliance" in veto.denied_by:
                log.warning("Hotkey open blocked by axiom compliance: %s", veto.denied_by)
                self._acknowledge("denied")
                return
            self._acknowledge("activation")
            self.session.open(trigger="hotkey")
            self.session.set_speaker("ryan", confidence=1.0)  # Physical access = operator
            self.event_log.set_session_id(self.session.session_id)
            self.event_log.emit("session_lifecycle", action="opened", trigger="hotkey")
            await self._start_pipeline()
        elif cmd == "close":
            await self._close_session(reason="hotkey")
        elif cmd == "scan":
            await self._handle_scan()
        elif cmd == "status":
            log.info(
                "Status: session=%s presence=%s queue=%d pipeline=%s tier=%s",
                self.session.state,
                self.presence.score,
                self.notifications.pending_count,
                "running" if self._pipeline_task is not None else "idle",
                self._perception_tier.value,
            )
        elif cmd.startswith("perception:"):
            tier_name = cmd.split(":", 1)[1].strip()
            self._set_perception_tier(tier_name)

    def _set_perception_tier(self, tier_name: str) -> None:
        """Switch perception tier (voice/hotkey command)."""
        from agents.hapax_voice.config import PerceptionTier

        try:
            new_tier = PerceptionTier(tier_name)
        except ValueError:
            log.warning("Unknown perception tier: %s", tier_name)
            return
        old_tier = self._perception_tier
        self._perception_tier = new_tier
        log.info("Perception tier: %s → %s", old_tier.value, new_tier.value)
        self.event_log.emit("perception_tier_changed", old=old_tier.value, new=new_tier.value)

        # Tier restrictions applied in _perception_loop via self._perception_tier

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

    async def _run_consent_session(self) -> None:
        """Run a voice consent session for a detected guest.

        Builds a separate Pipecat pipeline with the consent system prompt
        and consent-only tools. The LLM explains what the system records
        and understands the guest's natural language response.

        Guards:
        - Only runs when main voice session is inactive (audio transport free)
        - Sets _consent_session_active flag to prevent concurrent launches
        - Times out after consent_session_timeout_s
        - All exceptions are caught (non-fatal)
        """
        if self._consent_session_active:
            return

        self._consent_session_active = True
        self.event_log.emit("consent_session_start")
        log.info("Starting consent voice session for detected guest")

        try:
            from agents.hapax_voice.consent_session import (
                CONSENT_SYSTEM_PROMPT,
                CONSENT_TOOL_SCHEMAS,
                build_consent_tools_for_llm,
            )
            from agents.hapax_voice.pipeline import _build_llm, _build_stt, _build_tts

            # Build minimal pipeline components
            stt = _build_stt(self.cfg.local_stt_model)
            llm = _build_llm(self.cfg.llm_model, CONSENT_SYSTEM_PROMPT)
            tts = _build_tts(self.cfg.kokoro_voice)

            # Register consent tools (only 2: record_decision, request_clarification)
            consent_state = build_consent_tools_for_llm(
                llm,
                consent_tracker=self.consent_tracker,
                event_log=self.event_log,
            )

            # Build and run pipeline
            from pipecat.pipeline.pipeline import Pipeline
            from pipecat.pipeline.task import PipelineTask
            from pipecat.processors.aggregators.openai_llm_context import (
                LLMContext,
                LLMContextAggregatorPair,
            )
            from pipecat.transports.local.audio import LocalAudioTransport

            transport = LocalAudioTransport(
                input_name=self.cfg.audio_input_source,
            )

            context = LLMContext(
                messages=[{"role": "system", "content": CONSENT_SYSTEM_PROMPT}],
                tools=CONSENT_TOOL_SCHEMAS,
            )
            context_aggregator = LLMContextAggregatorPair(context)

            pipeline = Pipeline(
                processors=[
                    transport.input(),
                    stt,
                    context_aggregator.user(),
                    llm,
                    tts,
                    transport.output(),
                    context_aggregator.assistant(),
                ]
            )

            task = PipelineTask(pipeline)

            # Run with timeout
            from pipecat.pipeline.runner import PipelineRunner

            runner = PipelineRunner()

            async def _run_with_timeout():
                try:
                    await asyncio.wait_for(
                        runner.run(task),
                        timeout=self.cfg.consent_session_timeout_s,
                    )
                except TimeoutError:
                    log.info("Consent session timed out — curtailment continues")
                    await task.cancel()

            await _run_with_timeout()

            # Log outcome
            if consent_state.resolved:
                log.info(
                    "Consent session resolved: %s (scope: %s)",
                    consent_state.decision,
                    consent_state.scope,
                )
            else:
                log.info("Consent session ended without resolution — curtailment continues")

        except Exception:
            log.exception("Consent session failed (non-fatal, curtailment continues)")
        finally:
            self._consent_session_active = False
            self.event_log.emit(
                "consent_session_end",
                resolved=getattr(consent_state, "resolved", False)
                if "consent_state" in dir()
                else False,
            )

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

                presence = (
                    self.perception.latest.presence_score
                    if self.perception.latest
                    else "likely_absent"
                )
                if presence == "likely_absent":
                    continue

                gate_result = self.gate.check()
                if not gate_result.eligible:
                    log.debug("Proactive delivery blocked: %s", gate_result.reason)
                    continue

                # Check interruptibility — adjust threshold based on sleep quality
                latest = self.perception.latest
                sleep_b = self.perception.behaviors.get("sleep_quality")
                delivery_threshold = 0.5
                if sleep_b is not None:
                    delivery_threshold = 0.5 + 0.3 * (1.0 - sleep_b.value)
                if latest is not None and latest.interruptibility_score < delivery_threshold:
                    log.debug(
                        "Proactive delivery deferred: interruptibility %.2f < %.2f",
                        latest.interruptibility_score,
                        delivery_threshold,
                    )
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

    async def _ambient_refresh_loop(self) -> None:
        """Refresh ambient classification cache in executor thread.

        Runs PANNs + pw-record off the event loop to prevent blocking
        the audio queue consumer and wake word detector.
        """
        while self._running:
            try:
                await asyncio.sleep(30)  # classify every 30s
                await self.gate.refresh_ambient_cache()
            except asyncio.CancelledError:
                break
            except Exception:
                log.debug("Ambient refresh error (non-fatal)", exc_info=True)

    async def _perception_loop(self) -> None:
        """Run perception fast tick + governor evaluation on cadence."""
        from agents.hapax_voice.config import PerceptionTier

        while self._running:
            try:
                await asyncio.sleep(self.cfg.perception_fast_tick_s)

                # Skip perception entirely in dormant mode
                if self._perception_tier == PerceptionTier.DORMANT:
                    continue

                # Update perception with session state before tick
                self.perception.set_voice_session_active(self.session.is_active)

                # Fast tick: read sensors, produce EnvironmentState
                state = self.perception.tick()

                # Governor: evaluate state → directive
                directive = self.governor.evaluate(state)

                # Build typed Command with full provenance
                command = Command(
                    action=directive,
                    trigger_time=state.timestamp,
                    trigger_source="perception_tick",
                    min_watermark=self.perception.min_watermark,
                    governance_result=(
                        self.governor.last_veto_result
                        if self.governor.last_veto_result is not None
                        else _DEFAULT_VETO_RESULT
                    ),
                    selected_by=(
                        self.governor.last_selected.selected_by
                        if self.governor.last_selected is not None
                        else "default"
                    ),
                )

                # Apply Command to FrameGate (typed, with provenance)
                self._frame_gate.apply_command(command)

                # Apply directive to session
                if directive == "pause" and self.session.is_active and not self.session.is_paused:
                    self.session.pause(reason=f"governor:{state.activity_mode}")
                elif directive == "process" and self.session.is_paused:
                    self.session.resume()
                elif (
                    directive == "withdraw"
                    and self.session.is_active
                    and self._conversation_pipeline is None
                ):
                    await self._close_session(reason="operator_absent")

                # Update context gate with backend Behaviors
                self.gate.set_behaviors(self.perception.behaviors)

                # Consent state tracking (interpersonal_transparency axiom)
                # Pure function: no I/O, no blocking, just state transitions
                try:
                    speaker_is_op = (
                        not self.session.is_active
                        or getattr(self.session, "speaker", "ryan") == "ryan"
                    )
                    self.consent_tracker.tick(
                        face_count=state.face_count,
                        speaker_is_operator=speaker_is_op,
                        guest_count=state.guest_count,
                        now=state.timestamp,
                    )

                    # Launch consent voice session when needed
                    if (
                        self.consent_tracker.needs_notification
                        and not self.session.is_active
                        and not self._consent_session_active
                    ):
                        asyncio.create_task(self._run_consent_session())
                except Exception:
                    log.debug("Consent tracker error (non-fatal)", exc_info=True)

                # Feed perception snapshot to local LLM backend (WS5)
                if self._local_llm_backend is not None:
                    from agents.hapax_voice._perception_state_writer import (
                        get_perception_ring,
                    )

                    ring = get_perception_ring()
                    if ring is not None and ring.current() is not None:
                        self._local_llm_backend.set_perception_snapshot(ring.current())

                # Refresh salience concern graph on perception tick cadence
                if self._salience_router is not None:
                    self._refresh_concern_graph()
                    self._refresh_context_distillation()

                # Sync perception state to conversation pipeline for routing
                if self._conversation_pipeline is not None:
                    self._conversation_pipeline._activity_mode = state.activity_mode
                    # Map ConsentPhase enum to routing phase strings
                    _cp = (
                        self.consent_tracker.phase.value
                        if hasattr(self.consent_tracker, "phase")
                        else "none"
                    )
                    # Normalize to routing expectations: pending/active/refused/none
                    _phase_map = {
                        "no_guest": "none",
                        "guest_detected": "none",
                        "consent_pending": "pending",
                        "consent_granted": "active",
                        "consent_refused": "refused",
                    }
                    self._conversation_pipeline._consent_phase = _phase_map.get(_cp, "none")
                    self._conversation_pipeline._guest_mode = self.session.is_guest_mode
                    # Re-enabled: guest_count is deduplicated non-operator count
                    # from Bayesian face fusion (no longer double-counts operator
                    # across cameras or screen faces)
                    self._conversation_pipeline._face_count = state.guest_count

                # Write perception state AFTER consent tick so published state
                # reflects the current consent decision
                write_perception_state(
                    self.perception,
                    self.consent_registry,
                    self.consent_tracker,
                    session=self.session,
                    pipeline=self._conversation_pipeline,
                )

            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Error in perception loop")

    async def _actuation_loop(self) -> None:
        """Drain ScheduleQueue, resolve resource contention, dispatch winners."""
        from agents.hapax_voice.arbiter import ResourceClaim
        from agents.hapax_voice.resource_config import DEFAULT_PRIORITIES, RESOURCE_MAP

        tick_s = self.cfg.actuation_tick_ms / 1000.0
        while self._running:
            try:
                now = time.monotonic()
                ready = self.schedule_queue.drain(now)

                # Submit resource claims for each ready schedule
                for schedule in ready:
                    resource = RESOURCE_MAP.get(schedule.command.action)
                    if resource:
                        claim = ResourceClaim(
                            resource=resource,
                            chain=schedule.command.trigger_source,
                            priority=DEFAULT_PRIORITIES.get(
                                (resource, schedule.command.trigger_source), 0
                            ),
                            command=schedule.command,
                        )
                        self.arbiter.claim(claim)
                    else:
                        # No resource contention — dispatch directly
                        dispatched = self.executor_registry.dispatch(schedule.command)
                        self.event_log.emit(
                            "actuation",
                            action=schedule.command.action,
                            latency_ms=round((now - schedule.wall_time) * 1000.0, 1),
                            dispatched=dispatched,
                        )

                # Drain arbiter winners and dispatch
                for winner in self.arbiter.drain_winners(now):
                    dispatched = self.executor_registry.dispatch(winner.command)
                    self.event_log.emit(
                        "actuation",
                        action=winner.command.action,
                        chain=winner.chain,
                        resource=winner.resource,
                        latency_ms=round((now - winner.created_at) * 1000.0, 1),
                        dispatched=dispatched,
                    )

                await asyncio.sleep(tick_s)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Error in actuation loop")

    async def run(self) -> None:
        """Main daemon loop."""
        from shared.governance.consent_context import consent_scope

        with consent_scope(self.consent_registry, self._operator_principal):
            await self._run_inner()

    async def _run_inner(self) -> None:
        """Inner run loop — executes within consent_scope context."""
        log.info("Hapax Voice daemon starting (backend=%s)", self.cfg.backend)

        # Start hotkey server
        await self.hotkey.start()

        # Load wake word model (non-blocking, logs warning if unavailable)
        self.wake_word.load()

        # Preload STT + TTS models at startup so first wake word is instant.
        # These stay resident in GPU memory for the daemon's lifetime.
        if not self._resident_stt.is_loaded:
            log.info("Preloading STT model at startup...")
            self._resident_stt.load()
        self.tts.preload()

        # Bridge presynthesis happens on first session start (after TTS is warm)
        self._bridges_presynthesized = False

        # Precompute pipeline dependencies (tools, consent, callbacks)
        self._precompute_pipeline_deps()

        # Pin voice LLM model warm in Ollama (prevents 5s cold-start spikes)
        try:
            import subprocess as _sp

            _ollama_model = "gemma3-voice"
            _sp.run(
                [
                    "curl",
                    "-sf",
                    "http://localhost:11434/api/generate",
                    "-d",
                    '{"model":"' + _ollama_model + '","prompt":"","keep_alive":-1}',
                ],
                capture_output=True,
                timeout=10,
            )
            log.info("Ollama model %s pinned warm (keep_alive=-1)", _ollama_model)
        except Exception:
            log.debug("Ollama preload failed (non-fatal)", exc_info=True)

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
        self._background_tasks.append(asyncio.create_task(self._wake_word_processor()))
        self._background_tasks.append(asyncio.create_task(self._ambient_refresh_loop()))

        # Actuation loop (drains ScheduleQueue at beat precision)
        if self.cfg.mc_enabled or self.cfg.obs_enabled:
            self._background_tasks.append(asyncio.create_task(self._actuation_loop()))

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
                    self.perception.update_slow_fields(
                        activity_mode=mode,
                        workspace_context=getattr(analysis, "context", ""),
                    )
        finally:
            # Stop any running pipeline
            await self._stop_pipeline()

            # Stop audio input
            self._audio_input.stop()

            self.chime_player.close()

            # Close actuation
            self.executor_registry.close_all()
            if self._shared_pa is not None:
                try:
                    self._shared_pa.terminate()
                except Exception:
                    pass

            # Flush observability
            self.event_log.close()
            from opentelemetry.trace import get_tracer_provider

            provider = get_tracer_provider()
            if hasattr(provider, "force_flush"):
                provider.force_flush(timeout_millis=5000)

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

    from shared.log_setup import configure_logging

    configure_logging(agent="hapax-voice")

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
