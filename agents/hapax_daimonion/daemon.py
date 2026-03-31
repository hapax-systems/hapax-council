"""VoiceDaemon — main daemon class coordinating all voice subsystems."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from agents.hapax_daimonion.audio_input import AudioInputStream
from agents.hapax_daimonion.chime_player import ChimePlayer
from agents.hapax_daimonion.config import DaimonionConfig, load_config
from agents.hapax_daimonion.context_gate import ContextGate
from agents.hapax_daimonion.event_log import EventLog
from agents.hapax_daimonion.frame_gate import FrameGate
from agents.hapax_daimonion.governor import PipelineGovernor
from agents.hapax_daimonion.hotkey import HotkeyServer
from agents.hapax_daimonion.init_phase import InitPhase
from agents.hapax_daimonion.notification_queue import NotificationQueue
from agents.hapax_daimonion.perception import PerceptionEngine
from agents.hapax_daimonion.presence import PresenceDetector
from agents.hapax_daimonion.primitives import Event
from agents.hapax_daimonion.session import SessionManager
from agents.hapax_daimonion.tts import TTSManager
from agents.hapax_daimonion.wake_word import WakeWordDetector
from agents.hapax_daimonion.wake_word_porcupine import PorcupineWakeWord
from agents.hapax_daimonion.wake_word_whisper import WhisperWakeWord
from agents.hapax_daimonion.workspace_monitor import WorkspaceMonitor

if TYPE_CHECKING:
    from agents.hapax_daimonion.hyprland_listener import FocusEvent

log = logging.getLogger("hapax_daimonion")

try:
    from agents import _langfuse_config  # noqa: F401
except ImportError:
    pass


class VoiceDaemon:
    """Main daemon coordinating all voice subsystems."""

    def __init__(self, cfg: DaimonionConfig | None = None) -> None:
        self.cfg = cfg if cfg is not None else load_config()
        self._init_completed: set[InitPhase] = set()
        self._init_failed: dict[InitPhase, str] = {}

        for phase, init_fn in [
            (InitPhase.CORE, self._init_core_subsystems),
            (InitPhase.PERCEPTION, self._init_perception_layer),
            (InitPhase.STATE, self._init_state_and_observability),
            (InitPhase.VOICE, self._init_voice_pipeline),
            (InitPhase.ACTUATION, self._init_actuation_layer),
        ]:
            try:
                init_fn()
                self._init_completed.add(phase)
            except Exception as exc:
                self._init_failed[phase] = str(exc)
                log.error("Init phase %s failed: %s", phase.value, exc, exc_info=True)

    def is_ready(self) -> bool:
        """True if all init phases completed successfully."""
        return len(self._init_completed) == len(InitPhase)

    def _init_core_subsystems(self) -> None:
        """Initialize session, presence, gate, hotkey, wake word, TTS, chime."""
        from agents.hapax_daimonion.error_strategy import DegradationRegistry

        self.degradation_registry = DegradationRegistry()
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
        self.notifications = NotificationQueue(ttls=self.cfg.notification_priority_ttls)
        self.hotkey = HotkeyServer(
            socket_path=Path(self.cfg.hotkey_socket),
            on_command=self._handle_hotkey,
        )
        self.wake_word = self._create_wake_word_detector()
        self.wake_word.on_wake_word = self._on_wake_word
        self._audio_input = AudioInputStream(source_name=self.cfg.audio_input_source)
        self.tts = TTSManager(
            voice_id=self.cfg.voxtral_voice_id,
            ref_audio_path=self.cfg.voxtral_ref_audio or None,
        )
        self.chime_player = ChimePlayer(
            chime_dir=Path(self.cfg.chime_dir).expanduser(),
            auto_generate=True,
            volume=self.cfg.chime_volume,
        )
        # Workspace monitor
        cameras = self._build_camera_configs()
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
        # Consent principals
        from agents._governance import ConsentRegistry, Principal, PrincipalKind

        self.consent_registry = ConsentRegistry()
        self.consent_registry.load()
        self._operator_principal = Principal(id="operator", kind=PrincipalKind.SOVEREIGN)
        self._daemon_principal = self._operator_principal.delegate(
            child_id="hapax-daimonion",
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

    def _init_perception_layer(self) -> None:
        """Set up perception engine, backends, Hyprland wiring, governor."""
        from agents.hapax_daimonion.init_backends import register_perception_backends

        self.perception = PerceptionEngine(
            presence=self.presence,
            workspace_monitor=self.workspace_monitor,
        )
        register_perception_backends(self)
        self._setup_tap_governance()
        self.wake_word_event: Event[None] = Event()
        self.focus_event: Event[FocusEvent] = Event()
        self._wire_hyprland_perception()
        self.governor = PipelineGovernor(
            conversation_debounce_s=self.cfg.conversation_debounce_s,
            operator_absent_withdraw_s=self.cfg.operator_absent_withdraw_s,
            environment_clear_resume_s=self.cfg.environment_clear_resume_s,
        )
        self._frame_gate = FrameGate()

    def _init_state_and_observability(self) -> None:
        """Running state, event log, consent tracking."""
        from agents.hapax_daimonion.consent_state import ConsentStateTracker

        self._running = True
        self._background_tasks: list[asyncio.Task] = []
        self._pipeline_task: asyncio.Task | None = None
        self._gemini_session = None
        self._cognitive_loop = None
        self._wake_word_signal = asyncio.Event()

        events_dir = Path.home() / ".local" / "share" / "hapax-daimonion"
        self.event_log = EventLog(
            base_dir=events_dir,
            retention_days=self.cfg.observability_events_retention_days,
            enabled=self.cfg.observability_events_enabled,
        )
        self.presence.set_event_log(self.event_log)
        self.gate.set_event_log(self.event_log)
        self.notifications.set_event_log(self.event_log)
        self.workspace_monitor.set_event_log(self.event_log)
        if self._presence_engine is not None:
            self._presence_engine.set_event_log(self.event_log)

        self.consent_tracker = ConsentStateTracker(
            debounce_s=self.cfg.consent_debounce_s,
            absence_clear_s=self.cfg.consent_absence_clear_s,
        )
        self.consent_tracker.set_event_log(self.event_log)
        self.event_log.set_consent_fn(lambda: self.consent_tracker.persistence_allowed)
        self._consent_session_active = False
        self._perception_tier = self.cfg.perception_tier

    def _init_voice_pipeline(self) -> None:
        """Conversation buffer, STT, audio processing, salience."""
        from agents.hapax_daimonion.conversation_buffer import ConversationBuffer
        from agents.hapax_daimonion.init_audio import init_audio_processing, init_salience
        from agents.hapax_daimonion.resident_stt import ResidentSTT

        self._conversation_buffer = ConversationBuffer()
        self._resident_stt = ResidentSTT(
            model=self.cfg.local_stt_model
            if "whisper" in self.cfg.local_stt_model.lower()
            or "distil" in self.cfg.local_stt_model.lower()
            else "distil-large-v3",
            device="cuda",
        )
        self._conversation_pipeline = None
        init_audio_processing(self)
        init_salience(self)

    def _init_actuation_layer(self) -> None:
        """Schedule queue, executor registry, resource arbiter."""
        from agents.hapax_daimonion.arbiter import ResourceArbiter
        from agents.hapax_daimonion.executor import ExecutorRegistry, ScheduleQueue
        from agents.hapax_daimonion.init_actuation import setup_actuation
        from agents.hapax_daimonion.resource_config import DEFAULT_PRIORITIES

        self.schedule_queue = ScheduleQueue()
        self.executor_registry = ExecutorRegistry()
        self._shared_pa = None
        self.arbiter = ResourceArbiter(priorities=DEFAULT_PRIORITIES)
        setup_actuation(self)

    # ------------------------------------------------------------------
    # Small helpers and delegation
    # ------------------------------------------------------------------

    def _build_camera_configs(self) -> list:
        from agents.hapax_daimonion.screen_models import CameraConfig

        cameras: list[CameraConfig] = []
        if not self.cfg.webcam_enabled:
            return cameras
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
        return cameras

    def _create_wake_word_detector(self) -> WakeWordDetector:
        engine = self.cfg.wake_word_engine
        if engine == "porcupine":
            return PorcupineWakeWord(sensitivity=self.cfg.porcupine_sensitivity)
        if engine == "whisper":
            return WhisperWakeWord(model_size="tiny")
        return WakeWordDetector()

    def _setup_tap_governance(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._prev_tap_gesture = "none"

    def _check_tap_gesture(self) -> None:
        gesture_behavior = self.perception.behaviors.get("desk_tap_gesture")
        if gesture_behavior is None:
            return
        gesture = gesture_behavior.value
        if gesture != "none" and gesture != self._prev_tap_gesture:
            cmd = {"double_tap": "toggle", "triple_tap": "scan"}.get(gesture)
            if cmd is not None and self._loop is not None:
                asyncio.run_coroutine_threadsafe(self._handle_hotkey(cmd), self._loop)
        self._prev_tap_gesture = gesture

    def _wire_hyprland_perception(self) -> None:
        listener = self.workspace_monitor.listener
        if listener is None:
            return
        ipc = listener._ipc
        orig_cb = listener.on_focus_changed

        def _focus_with_perception(event):
            self.perception.update_desktop_state(
                active_window=ipc.get_active_window(),
                window_count=len(ipc.get_clients()),
                active_workspace_id=event.workspace_id,
            )
            self.focus_event.emit(time.monotonic(), event)
            if orig_cb is not None:
                orig_cb(event)

        listener.on_focus_changed = _focus_with_perception

    def _on_wake_word(self) -> None:
        from agents.hapax_daimonion.session_events import on_wake_word

        on_wake_word(self)

    async def _handle_hotkey(self, cmd: str) -> None:
        from agents.hapax_daimonion.session_events import handle_hotkey

        await handle_hotkey(self, cmd)

    # ------------------------------------------------------------------
    # Delegated methods (preserve test API)
    # ------------------------------------------------------------------

    def _acknowledge(self, kind: str = "activation") -> None:
        from agents.hapax_daimonion.session_events import acknowledge

        acknowledge(self, kind)

    async def _start_pipeline(self) -> None:
        from agents.hapax_daimonion.pipeline_lifecycle import start_pipeline

        await start_pipeline(self)

    async def _stop_pipeline(self) -> None:
        from agents.hapax_daimonion.pipeline_lifecycle import stop_pipeline

        await stop_pipeline(self)

    async def _close_session(self, reason: str) -> None:
        from agents.hapax_daimonion.session_events import close_session

        await close_session(self, reason)

    async def _audio_loop(self) -> None:
        from agents.hapax_daimonion.run_loops import audio_loop

        await audio_loop(self)

    async def _wake_word_processor(self) -> None:
        from agents.hapax_daimonion.session_events import wake_word_processor

        await wake_word_processor(self)

    async def _ntfy_callback(self, notification) -> None:
        from agents.hapax_daimonion.run_loops_aux import ntfy_callback

        await ntfy_callback(self, notification)

    async def _run_consent_session(self) -> None:
        from agents.hapax_daimonion.consent_session_runner import run_consent_session

        await run_consent_session(self)

    async def run(self) -> None:
        from agents._consent_context import consent_scope

        with consent_scope(self.consent_registry, self._operator_principal):
            await self._run_inner()

    async def _run_inner(self) -> None:
        from agents.hapax_daimonion.run_inner import run_inner

        await run_inner(self)

    def stop(self) -> None:
        self._running = False
