"""Workspace awareness orchestrator composing screen, webcam, and analysis."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING

from agents.hapax_voice.notification_queue import VoiceNotification
from agents.hapax_voice.screen_capturer import ScreenCapturer
from agents.hapax_voice.hyprland_listener import HyprlandEventListener, FocusEvent
from agents.hapax_voice.screen_models import (
    CameraConfig,
    WorkspaceAnalysis,
)
from agents.hapax_voice.webcam_capturer import WebcamCapturer
from agents.hapax_voice.workspace_analyzer import WorkspaceAnalyzer
from shared.hyprland import HyprlandIPC

if TYPE_CHECKING:
    from agents.hapax_voice.face_detector import FaceDetector
    from agents.hapax_voice.notification_queue import NotificationQueue
    from agents.hapax_voice.presence import PresenceDetector

log = logging.getLogger(__name__)

_RAG_COLLECTION = "documents"
_RAG_MAX_CHUNKS = 3
_RAG_SCORE_THRESHOLD = 0.3


class WorkspaceMonitor:
    """Orchestrates workspace awareness: screen + webcams + analysis + routing.

    Drop-in evolution of ScreenMonitor. If webcams are unavailable,
    degrades to screen-only analysis (identical to ScreenMonitor behavior).
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        poll_interval_s: float = 2.0,
        capture_cooldown_s: float = 10.0,
        proactive_min_confidence: float = 0.8,
        proactive_cooldown_s: float = 300.0,
        recapture_idle_s: float = 60.0,
        analyzer_model: str = "gemini-flash",
        cameras: list[CameraConfig] | None = None,
        webcam_cooldown_s: float = 30.0,
        face_interval_s: float = 8.0,
        face_min_confidence: float = 0.3,
    ) -> None:
        self._enabled = enabled
        self.recapture_idle_s = recapture_idle_s
        self.proactive_min_confidence = proactive_min_confidence
        self.proactive_cooldown_s = proactive_cooldown_s
        self._face_interval_s = face_interval_s
        self._face_min_confidence = face_min_confidence

        self._listener = HyprlandEventListener(debounce_s=1.0) if enabled else None
        self._hypr_ipc = HyprlandIPC() if enabled else None
        self._screen_capturer = ScreenCapturer(cooldown_s=capture_cooldown_s) if enabled else None
        self._webcam_capturer = (
            WebcamCapturer(cameras=cameras, cooldown_s=webcam_cooldown_s)
            if enabled and cameras
            else None
        )
        self._analyzer = WorkspaceAnalyzer(model=analyzer_model) if enabled else None
        self._face_detector: FaceDetector | None = None

        self._latest_analysis: WorkspaceAnalysis | None = None
        self._last_analysis_time: float = 0.0
        self._last_proactive_time: float = 0.0
        self._notification_queue: NotificationQueue | None = None
        self._presence: PresenceDetector | None = None
        self._event_log = None
        self._tracer = None

        if self._listener is not None:
            self._listener.on_focus_changed = self._on_focus_changed

    @property
    def listener(self) -> HyprlandEventListener | None:
        """Public access to the event listener for daemon-level wiring."""
        return self._listener

    @property
    def latest_analysis(self) -> WorkspaceAnalysis | None:
        return self._latest_analysis

    @property
    def is_analysis_stale(self) -> bool:
        if self._latest_analysis is None:
            return True
        return (time.monotonic() - self._last_analysis_time) > self.recapture_idle_s

    def has_camera(self, role: str) -> bool:
        if self._webcam_capturer is None:
            return False
        return self._webcam_capturer.has_camera(role)

    def set_notification_queue(self, queue: NotificationQueue) -> None:
        self._notification_queue = queue

    def set_presence(self, presence: PresenceDetector) -> None:
        """Link presence detector for face detection updates."""
        self._presence = presence

    def set_event_log(self, event_log) -> None:
        self._event_log = event_log

    def set_tracer(self, tracer) -> None:
        self._tracer = tracer

    def _emit_analysis_event(self, analysis: WorkspaceAnalysis, *, latency_ms: int, images_sent: int) -> None:
        if self._event_log is None:
            return
        self._event_log.emit(
            "analysis_complete",
            app=analysis.app,
            operator_present=analysis.operator_present,
            gear_count=len(analysis.gear_state),
            latency_ms=latency_ms,
            images_sent=images_sent,
        )

    def _emit_analysis_failed(self, error: str, *, latency_ms: int) -> None:
        if self._event_log is None:
            return
        self._event_log.emit("analysis_failed", error=error, latency_ms=latency_ms)

    def _emit_face_event(self, *, detected: bool, count: int, latency_ms: int) -> None:
        if self._event_log is None:
            return
        self._event_log.emit("face_result", detected=detected, count=count, latency_ms=latency_ms)

    def reload_context(self) -> None:
        """Reload workspace analyzer's static system context."""
        if self._analyzer is not None:
            self._analyzer.reload_context()
            log.info("Workspace analyzer context reloaded")

    def _on_focus_changed(self, event: FocusEvent) -> None:
        log.info("Focus changed: %s — %s (ws:%d)", event.app_class, event.title, event.workspace_id)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._capture_and_analyze())
        except RuntimeError:
            log.debug("No event loop available for workspace capture")

    def _query_rag(self, keywords: list[str]) -> str | None:
        """Query Qdrant documents collection with keywords for extra context."""
        if not keywords:
            return None
        try:
            from agents.shared.config import embed, get_qdrant

            query_text = " ".join(keywords)
            vector = embed(query_text, prefix="search_query")
            client = get_qdrant()
            results = client.query_points(
                _RAG_COLLECTION,
                query=vector,
                limit=_RAG_MAX_CHUNKS,
                score_threshold=_RAG_SCORE_THRESHOLD,
            )
            if not results.points:
                return None
            chunks = []
            for p in results.points:
                filename = p.payload.get("filename", "unknown")
                text = p.payload.get("text", "")
                chunks.append(f"[{filename}]\n{text}")
            return "\n\n".join(chunks)
        except Exception as exc:
            log.debug("RAG augmentation failed (non-fatal): %s", exc)
            return None

    def _build_deterministic_context(self) -> str:
        """Build workspace context string from Hyprland IPC (no LLM needed).

        This gives the LLM analyzer exact window/workspace data so it can
        focus on visual analysis (errors, code content) rather than
        identifying which apps are running.
        """
        if self._hypr_ipc is None:
            return ""
        clients = self._hypr_ipc.get_clients()
        if not clients:
            return ""
        lines = ["Open windows:"]
        for c in clients:
            lines.append(f"  - [{c.app_class}] \"{c.title}\" on workspace {c.workspace_id}")
        return "\n".join(lines)

    async def _capture_and_analyze(self) -> None:
        """Capture screen (+ webcams if available) and run analysis."""
        if self._screen_capturer is None or self._analyzer is None:
            return

        screen_b64 = self._screen_capturer.capture()
        if screen_b64 is None:
            return

        # Capture webcam frames (non-blocking, returns None if unavailable)
        operator_b64 = None
        hardware_b64 = None
        if self._webcam_capturer is not None:
            operator_b64 = self._webcam_capturer.capture("operator")
            hardware_b64 = self._webcam_capturer.capture("hardware")

        # RAG augmentation from previous keywords
        prev_keywords = self._latest_analysis.keywords if self._latest_analysis else []
        rag_context = self._query_rag(prev_keywords)

        # Add deterministic desktop context from Hyprland IPC
        desktop_context = self._build_deterministic_context()
        combined_context = "\n\n".join(filter(None, [desktop_context, rag_context]))

        images_sent = 1 + (1 if operator_b64 else 0) + (1 if hardware_b64 else 0)

        trace_cm = (
            self._tracer.trace_analysis(
                presence_score=self._presence.score if self._presence else "unknown",
                images_sent=images_sent,
                session_id=self._event_log._session_id if self._event_log else None,
                activity_mode="unknown",
            )
            if self._tracer is not None
            else contextlib.nullcontext(None)
        )

        t0 = time.monotonic()
        with trace_cm as trace:
            analysis = await self._analyzer.analyze(
                screen_b64=screen_b64,
                operator_b64=operator_b64,
                hardware_b64=hardware_b64,
                extra_context=combined_context or None,
            )
        latency_ms = int((time.monotonic() - t0) * 1000)

        if analysis is not None:
            self._latest_analysis = analysis
            self._last_analysis_time = time.monotonic()
            log.info(
                "Workspace analysis: %s — %s (operator=%s, gear=%d)",
                analysis.app,
                analysis.context,
                analysis.operator_present,
                len(analysis.gear_state),
            )
            self._route_proactive_issues(analysis)
            self._persist_analysis(analysis)
            self._emit_analysis_event(analysis, latency_ms=latency_ms, images_sent=images_sent)
        else:
            self._emit_analysis_failed("Analysis returned None", latency_ms=latency_ms)

    def _persist_analysis(self, analysis: WorkspaceAnalysis) -> None:
        """Write latest analysis to shared state file for cockpit API."""
        import json
        from pathlib import Path
        state_path = Path.home() / ".local" / "share" / "hapax-voice" / "workspace_state.json"
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "app": analysis.app,
                "context": analysis.context,
                "summary": analysis.summary,
                "operator_present": analysis.operator_present,
                "operator_activity": analysis.operator_activity,
                "gear_state": [
                    {"device": g.device, "powered": g.powered, "display_content": g.display_content}
                    for g in analysis.gear_state
                ],
                "timestamp": time.time(),
            }
            state_path.write_text(json.dumps(data))
        except Exception as exc:
            log.debug("Failed to persist workspace state: %s", exc)

    def _route_proactive_issues(self, analysis: WorkspaceAnalysis) -> None:
        """Route high-confidence error issues to notification queue."""
        if self._notification_queue is None:
            return

        now = time.monotonic()
        if (now - self._last_proactive_time) < self.proactive_cooldown_s:
            return

        for issue in analysis.issues:
            if (
                issue.severity == "error"
                and issue.confidence >= self.proactive_min_confidence
            ):
                self._notification_queue.enqueue(
                    VoiceNotification(
                        title="Workspace Alert",
                        message=issue.description,
                        priority="normal",
                        source="workspace",
                    )
                )
                self._last_proactive_time = now
                log.info(
                    "Proactive workspace alert: %s (confidence=%.2f)",
                    issue.description,
                    issue.confidence,
                )
                return  # One alert per analysis cycle

    async def _face_detection_loop(self) -> None:
        """Periodic face detection from operator camera for presence."""
        if self._webcam_capturer is None or self._presence is None:
            return
        if not self._webcam_capturer.has_camera("operator"):
            return

        # Lazy-init face detector
        if self._face_detector is None:
            try:
                from agents.hapax_voice.face_detector import FaceDetector

                self._face_detector = FaceDetector(min_confidence=self._face_min_confidence)
            except Exception as exc:
                log.warning("Face detector unavailable: %s", exc)
                return

        while True:
            try:
                frame_b64 = self._webcam_capturer.capture("operator")
                if frame_b64 is not None:
                    t0 = time.monotonic()
                    result = self._face_detector.detect_from_base64(frame_b64)
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    self._presence.record_face_event(
                        detected=result.detected,
                        count=result.count,
                    )
                    self._emit_face_event(detected=result.detected, count=result.count, latency_ms=latency_ms)
            except Exception as exc:
                log.debug("Face detection loop error: %s", exc)
            await asyncio.sleep(self._face_interval_s)

    async def run(self) -> None:
        """Main loop: run event listener + staleness check + face detection."""
        if not self._enabled or self._listener is None:
            log.info("Workspace monitor disabled")
            return

        log.info("Workspace monitor started")

        async def _staleness_loop() -> None:
            while True:
                if self.is_analysis_stale:
                    await self._capture_and_analyze()
                await asyncio.sleep(self.recapture_idle_s)

        tasks = [
            self._listener.run(),
            _staleness_loop(),
        ]
        # Add face detection if presence is linked
        if self._presence is not None:
            tasks.append(self._face_detection_loop())

        await asyncio.gather(*tasks)

    async def capture_fresh(self) -> WorkspaceAnalysis | None:
        """Force a fresh capture+analysis (e.g. on voice session open)."""
        if self._screen_capturer is not None:
            self._screen_capturer.reset_cooldown()
        if self._webcam_capturer is not None:
            self._webcam_capturer.reset_cooldown("operator")
            self._webcam_capturer.reset_cooldown("hardware")
        await self._capture_and_analyze()
        return self._latest_analysis
