"""Visual layer signal aggregator — polls cockpit API and perception state.

Standalone async process. Reads signals from the cockpit API and perception
state file, runs the DisplayStateMachine, and writes VisualLayerState
atomically to /dev/shm for the studio compositor to render.

Two cadences:
  Fast (15s): health, GPU, infrastructure
  Slow (60s): nudges, briefing, drift, goals, copilot

Entry point: uv run python -m agents.visual_layer_aggregator
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from agents.visual_layer_state import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    BiometricState,
    DisplayStateMachine,
    InjectedFeed,
    SignalCategory,
    SignalEntry,
    SupplementaryContent,
    VisualLayerState,
    VoiceSessionState,
)

log = logging.getLogger("visual_layer_aggregator")

# ── Paths ────────────────────────────────────────────────────────────────────

PERCEPTION_STATE_PATH = Path.home() / ".cache" / "hapax-voice" / "perception-state.json"
OUTPUT_DIR = Path("/dev/shm/hapax-compositor")
OUTPUT_FILE = OUTPUT_DIR / "visual-layer-state.json"

# ── Cadences ─────────────────────────────────────────────────────────────────

FAST_INTERVAL_S = 15.0
SLOW_INTERVAL_S = 60.0
AMBIENT_CONTENT_INTERVAL_S = 45.0  # New ambient content every 30-90s (avg 45)

# ── API ──────────────────────────────────────────────────────────────────────

COCKPIT_BASE = os.environ.get("COCKPIT_BASE_URL", "http://127.0.0.1:8051/api")

# ── Camera roles available for injection ─────────────────────────────────────

CAMERA_ROLES = ["brio-operator", "c920-hardware", "c920-room", "c920-aux"]

# ── Experimental camera filters for ambient injection ────────────────────────

CAMERA_FILTERS = [
    "sepia(0.8) contrast(1.3) brightness(0.7)",
    "hue-rotate(30deg) saturate(1.8) brightness(0.6)",
    "saturate(2.5) contrast(1.1) brightness(0.5)",
    "grayscale(0.6) contrast(1.4) brightness(0.8) sepia(0.3)",
    "hue-rotate(-20deg) saturate(1.5) contrast(1.2)",
]


# ── Signal Mapping ───────────────────────────────────────────────────────────


def map_health(data: dict) -> list[SignalEntry]:
    """Map /api/health response to signals."""
    signals = []
    status = data.get("overall_status", "healthy")
    if status == "healthy":
        return signals

    failed = data.get("failed_checks", [])
    failed_count = data.get("failed", 0)

    if status == "failed" or failed_count >= 3:
        severity = SEVERITY_CRITICAL
    elif status == "degraded":
        severity = SEVERITY_HIGH
    else:
        severity = SEVERITY_MEDIUM

    title = f"System {status}"
    detail = ", ".join(failed[:3]) if failed else f"{failed_count} checks failing"
    signals.append(
        SignalEntry(
            category=SignalCategory.HEALTH_INFRA,
            severity=severity,
            title=title,
            detail=detail,
            source_id="health-overall",
        )
    )
    return signals


def map_gpu(data: dict) -> list[SignalEntry]:
    """Map /api/gpu response to signals."""
    signals = []
    usage_pct = data.get("usage_pct", 0)
    temp = data.get("temperature_c", 0)

    if usage_pct > 90:
        signals.append(
            SignalEntry(
                category=SignalCategory.HEALTH_INFRA,
                severity=SEVERITY_HIGH,
                title=f"VRAM {usage_pct:.0f}%",
                detail=f"{data.get('free_mb', 0)}MB free",
                source_id="gpu-vram",
            )
        )
    elif usage_pct > 80:
        signals.append(
            SignalEntry(
                category=SignalCategory.HEALTH_INFRA,
                severity=SEVERITY_MEDIUM,
                title=f"VRAM {usage_pct:.0f}%",
                source_id="gpu-vram",
            )
        )

    if temp > 85:
        signals.append(
            SignalEntry(
                category=SignalCategory.HEALTH_INFRA,
                severity=SEVERITY_HIGH,
                title=f"GPU {temp}\u00b0C",
                source_id="gpu-temp",
            )
        )

    return signals


def map_nudges(data: list[dict]) -> list[SignalEntry]:
    """Map /api/nudges response to signals. Top 3 by priority."""
    signals = []
    for nudge in data[:3]:
        label = nudge.get("priority_label", "low")
        score = nudge.get("priority_score", 0)

        if label == "critical":
            severity = SEVERITY_CRITICAL
        elif label == "high":
            severity = SEVERITY_HIGH
        elif label == "medium":
            severity = SEVERITY_MEDIUM
        else:
            severity = SEVERITY_LOW

        signals.append(
            SignalEntry(
                category=SignalCategory.WORK_TASKS,
                severity=severity,
                title=nudge.get("title", "Nudge"),
                detail=nudge.get("suggested_action", ""),
                source_id=nudge.get("source_id", f"nudge-{score}"),
            )
        )
    return signals


def map_briefing(data: dict) -> list[SignalEntry]:
    """Map /api/briefing response to signals."""
    signals = []
    headline = data.get("headline", "")
    if not headline:
        return signals

    action_items = data.get("action_items", [])
    high_items = [a for a in action_items if a.get("priority") == "high"]

    severity = SEVERITY_MEDIUM if high_items else SEVERITY_LOW
    detail = f"{len(action_items)} items" if action_items else ""

    signals.append(
        SignalEntry(
            category=SignalCategory.CONTEXT_TIME,
            severity=severity,
            title=headline[:60],
            detail=detail,
            source_id="briefing-headline",
        )
    )
    return signals


def map_drift(data: dict) -> list[SignalEntry]:
    """Map /api/drift response to signals."""
    signals = []
    items = data.get("items", [])
    high_items = [i for i in items if i.get("severity") == "high"]

    if high_items:
        signals.append(
            SignalEntry(
                category=SignalCategory.GOVERNANCE,
                severity=SEVERITY_MEDIUM,
                title=f"{len(high_items)} high-drift items",
                detail=high_items[0].get("description", "")[:60] if high_items else "",
                source_id="drift-high",
            )
        )
    return signals


def map_goals(data: dict) -> list[SignalEntry]:
    """Map /api/goals response to signals."""
    signals = []
    stale = data.get("primary_stale", [])
    if stale:
        signals.append(
            SignalEntry(
                category=SignalCategory.WORK_TASKS,
                severity=SEVERITY_LOW,
                title=f"{len(stale)} stale goal{'s' if len(stale) > 1 else ''}",
                detail=stale[0] if stale else "",
                source_id="goals-stale",
            )
        )
    return signals


def map_copilot(data: dict) -> list[SignalEntry]:
    """Map /api/copilot response to signals."""
    signals = []
    message = data.get("message", "")
    if message and len(message) > 10:
        signals.append(
            SignalEntry(
                category=SignalCategory.CONTEXT_TIME,
                severity=SEVERITY_LOW,
                title=message[:60],
                source_id="copilot-msg",
            )
        )
    return signals


def map_perception(data: dict) -> tuple[list[SignalEntry], float, float, bool]:
    """Map perception-state.json to signals + flow/audio/production metadata."""
    signals = []

    flow_score = data.get("flow_score", 0.0)
    audio_energy = data.get("audio_energy_rms", 0.0)
    production = data.get("production_activity", "idle")
    production_active = production not in ("idle", "")

    # Consent phase as governance signal
    consent = data.get("consent_phase", "no_guest")
    if consent not in ("no_guest", ""):
        signals.append(
            SignalEntry(
                category=SignalCategory.GOVERNANCE,
                severity=SEVERITY_MEDIUM if consent == "pending_consent" else SEVERITY_LOW,
                title=f"Consent: {consent.replace('_', ' ')}",
                source_id="consent-phase",
            )
        )

    # Music genre as ambient sensor
    genre = data.get("music_genre", "")
    if genre:
        signals.append(
            SignalEntry(
                category=SignalCategory.AMBIENT_SENSOR,
                severity=0.0,
                title=genre,
                source_id="music-genre",
            )
        )

    return signals, flow_score, audio_energy, production_active


def map_voice_session(data: dict) -> tuple[list[SignalEntry], VoiceSessionState]:
    """Map voice_session block from perception state to signals + state model."""
    vs = data.get("voice_session", {})
    voice_state = VoiceSessionState(
        active=vs.get("active", False),
        state=vs.get("state", "idle"),
        turn_count=vs.get("turn_count", 0),
        last_utterance=vs.get("last_utterance", ""),
        last_response=vs.get("last_response", ""),
        active_tool=vs.get("active_tool"),
        barge_in=vs.get("barge_in", False),
    )

    signals: list[SignalEntry] = []
    if voice_state.active:
        state_labels = {
            "listening": "LISTENING",
            "transcribing": "TRANSCRIBING",
            "thinking": "THINKING",
            "speaking": "SPEAKING",
        }
        label = state_labels.get(voice_state.state, voice_state.state.upper())
        detail = ""
        if voice_state.active_tool:
            detail = f"tool: {voice_state.active_tool}"
        elif voice_state.last_utterance:
            detail = voice_state.last_utterance[:60]

        signals.append(
            SignalEntry(
                category=SignalCategory.VOICE_SESSION,
                severity=SEVERITY_LOW,
                title=label,
                detail=detail,
                source_id="voice-state",
            )
        )

    return signals, voice_state


def map_voice_content(data: dict) -> list[SupplementaryContent]:
    """Map voice_content block from perception state to content cards."""
    items = data.get("voice_content", [])
    return [
        SupplementaryContent(
            content_type=item.get("content_type", "text"),
            title=item.get("title", ""),
            body=item.get("body", ""),
            image_path=item.get("image_path", ""),
            timestamp=item.get("timestamp", 0.0),
        )
        for item in items[:5]
    ]


def map_biometrics(data: dict) -> BiometricState:
    """Map biometric fields from perception state."""
    return BiometricState(
        heart_rate_bpm=data.get("heart_rate_bpm", 0),
        stress_elevated=data.get("stress_elevated", False),
        physiological_load=data.get("physiological_load", 0.0),
        sleep_quality=data.get("sleep_quality", 1.0),
        watch_activity=data.get("watch_activity_state", "unknown"),
    )


# ── Time-of-day color evolution ──────────────────────────────────────────────


def time_of_day_warmth_offset() -> float:
    """Return a warmth offset based on time of day (always warm spectrum).

    Evening/night = warmer, midday = slightly brighter.
    """
    hour = datetime.now().hour
    if hour < 6:
        return 0.7  # deep red, late night
    elif hour < 9:
        return 0.4  # warming up, morning
    elif hour < 12:
        return 0.2  # slightly brighter midday
    elif hour < 17:
        return 0.25  # afternoon
    elif hour < 21:
        return 0.5  # warm amber evening
    else:
        return 0.65  # deep evening


# ── Aggregator ───────────────────────────────────────────────────────────────


class VisualLayerAggregator:
    """Polls cockpit API and perception state, runs state machine, writes output."""

    def __init__(self) -> None:
        self._sm = DisplayStateMachine()
        self._client = httpx.AsyncClient(base_url=COCKPIT_BASE, timeout=5.0)
        self._fast_signals: list[SignalEntry] = []
        self._slow_signals: list[SignalEntry] = []
        self._perception_signals: list[SignalEntry] = []
        self._voice_signals: list[SignalEntry] = []
        self._flow_score: float = 0.0
        self._audio_energy: float = 0.0
        self._production_active: bool = False

        # Voice session + content state
        self._voice_session = VoiceSessionState()
        self._voice_content: list[SupplementaryContent] = []
        self._biometrics = BiometricState()

        # Ambient content rotation
        self._ambient_text: str = ""
        self._ambient_facts: list[str] = []
        self._last_ambient_fetch: float = 0.0
        self._last_ambient_rotate: float = 0.0
        self._ambient_text_history: list[str] = []  # track recent to avoid repetition

        # Camera feed injection
        self._injected_feeds: list[InjectedFeed] = []
        self._last_feed_inject: float = 0.0

    async def _fetch_json(self, path: str) -> dict | list | None:
        """Fetch a cockpit API endpoint. Returns None on any error."""
        try:
            resp = await self._client.get(path)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            log.debug("Failed to fetch %s", path, exc_info=True)
        return None

    async def poll_fast(self) -> None:
        """Poll fast-cadence endpoints (health, GPU)."""
        signals: list[SignalEntry] = []

        health = await self._fetch_json("/health")
        if isinstance(health, dict):
            signals.extend(map_health(health))

        gpu = await self._fetch_json("/gpu")
        if isinstance(gpu, dict):
            signals.extend(map_gpu(gpu))

        self._fast_signals = signals

    async def poll_slow(self) -> None:
        """Poll slow-cadence endpoints (nudges, briefing, drift, goals, copilot)."""
        signals: list[SignalEntry] = []

        nudges = await self._fetch_json("/nudges")
        if isinstance(nudges, list):
            signals.extend(map_nudges(nudges))

        briefing = await self._fetch_json("/briefing")
        if isinstance(briefing, dict):
            signals.extend(map_briefing(briefing))

        drift = await self._fetch_json("/drift")
        if isinstance(drift, dict):
            signals.extend(map_drift(drift))

        goals = await self._fetch_json("/goals")
        if isinstance(goals, dict):
            signals.extend(map_goals(goals))

        copilot = await self._fetch_json("/copilot")
        if isinstance(copilot, dict):
            signals.extend(map_copilot(copilot))

        self._slow_signals = signals

    def poll_perception(self) -> None:
        """Read perception-state.json (local file, no HTTP)."""
        try:
            data = json.loads(PERCEPTION_STATE_PATH.read_text())
            signals, flow, audio, prod = map_perception(data)
            self._perception_signals = signals
            self._flow_score = flow
            self._audio_energy = audio
            self._production_active = prod

            # Voice session (Batch A)
            voice_signals, voice_state = map_voice_session(data)
            self._voice_signals = voice_signals
            self._voice_session = voice_state

            # Supplementary content (Batch B)
            self._voice_content = map_voice_content(data)

            # Biometrics (Batch E)
            self._biometrics = map_biometrics(data)

        except (FileNotFoundError, json.JSONDecodeError):
            pass  # perception daemon may not be running

    async def poll_ambient_content(self) -> None:
        """Fetch ambient content from cockpit API (profile facts, moments)."""
        now = time.monotonic()
        if now - self._last_ambient_fetch < 300.0:  # refresh pool every 5 min
            return
        self._last_ambient_fetch = now

        data = await self._fetch_json("/studio/ambient-content")
        if isinstance(data, dict):
            facts = data.get("facts", [])
            if facts:
                self._ambient_facts = facts

    def _rotate_ambient_text(self) -> None:
        """Pick a new ambient text fragment, avoiding recent repetition."""
        now = time.monotonic()
        interval = random.uniform(30.0, 90.0)
        if now - self._last_ambient_rotate < interval:
            return
        self._last_ambient_rotate = now

        if not self._ambient_facts:
            return

        # Filter out recently shown (last 30 min worth)
        available = [f for f in self._ambient_facts if f not in self._ambient_text_history[-20:]]
        if not available:
            available = self._ambient_facts
            self._ambient_text_history.clear()

        self._ambient_text = random.choice(available)
        self._ambient_text_history.append(self._ambient_text)

    def _maybe_inject_camera(self, display_state: str) -> None:
        """Decide whether to inject a camera feed for visual interest."""
        now = time.monotonic()

        # Expire old injections
        self._injected_feeds = [
            f for f in self._injected_feeds if now - f.injected_at < f.duration_s
        ]

        # Don't inject if we already have one or too recently
        if self._injected_feeds or now - self._last_feed_inject < 120.0:
            return

        # Only inject in ambient state, occasionally
        if display_state != "ambient":
            return

        # 15% chance per tick (every 15s -> roughly once per ~100s)
        if random.random() > 0.15:
            return

        # Pick a random camera and filter
        role = random.choice(CAMERA_ROLES)
        css_filter = random.choice(CAMERA_FILTERS)
        duration = random.uniform(30.0, 60.0)

        # Random position in the right half
        x = random.uniform(0.5, 0.7)
        y = random.uniform(0.15, 0.55)

        feed = InjectedFeed(
            role=role,
            x=x,
            y=y,
            w=random.uniform(0.25, 0.4),
            h=random.uniform(0.25, 0.4),
            opacity=random.uniform(0.3, 0.6),
            css_filter=css_filter,
            duration_s=duration,
            injected_at=now,
        )
        self._injected_feeds.append(feed)
        self._last_feed_inject = now
        log.debug("Injected camera feed: %s with %s", role, css_filter)

    def _apply_biometric_modulation(self, params: Any) -> Any:
        """Modulate ambient params based on biometric state (Batch E).

        Modulate, don't comment. Changes visual texture so the operator's
        nervous system responds subconsciously.
        """
        bio = self._biometrics

        if bio.stress_elevated:
            # Calming: reduce turbulence, slow speed, deepen colors
            params.speed = round(params.speed * 0.5, 3)
            params.turbulence = round(params.turbulence * 0.4, 3)
            params.color_warmth = round(min(1.0, params.color_warmth + 0.3), 3)
            params.brightness = round(max(0.12, params.brightness - 0.05), 3)

        elif bio.heart_rate_bpm > 90 and bio.watch_activity not in ("exercise", "workout"):
            # Elevated HR (non-exercise): warmer, subtle
            params.color_warmth = round(min(1.0, params.color_warmth + 0.2), 3)

        if bio.physiological_load > 0.6:
            # High load: maximum calm
            params.speed = round(params.speed * 0.4, 3)
            params.turbulence = round(params.turbulence * 0.3, 3)

        if bio.sleep_quality < 0.6:
            # Poor sleep: gentler visuals
            params.brightness = round(max(0.10, params.brightness * 0.7), 3)
            params.turbulence = round(params.turbulence * 0.6, 3)

        # Time-of-day warmth (always active)
        tod_offset = time_of_day_warmth_offset()
        params.color_warmth = round(min(1.0, max(params.color_warmth, tod_offset)), 3)

        return params

    def _infer_activity(self) -> tuple[str, str]:
        """Infer what the operator is doing from perception state.

        Returns (label, detail) — always shows on screen so operator can
        correct Hapax's assumptions.
        """
        # Check for operator correction (overrides inference for TTL duration)
        correction_path = Path("/dev/shm/hapax-compositor/activity-correction.json")
        try:
            correction = json.loads(correction_path.read_text())
            elapsed = time.time() - correction.get("timestamp", 0)
            if elapsed < correction.get("ttl_s", 1800):
                return correction["label"], correction.get("detail", "")
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

        # Voice session takes priority
        if self._voice_session.active:
            return "talking to hapax", f"turn {self._voice_session.turn_count}"

        # Production activity from perception
        perception_data = {}
        try:
            perception_data = json.loads(PERCEPTION_STATE_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        production = perception_data.get("production_activity", "")
        music_genre = perception_data.get("music_genre", "")
        flow_state = perception_data.get("flow_state", "idle")

        if production == "coding":
            detail = f"flow: {flow_state}" if flow_state != "idle" else ""
            return "coding", detail
        elif production == "writing":
            return "writing", ""
        elif production == "browsing":
            return "browsing", ""
        elif production == "meeting":
            return "in a meeting", ""
        elif production in ("music_production", "producing"):
            detail = music_genre if music_genre else ""
            return "making music", detail
        elif production == "gaming":
            return "gaming", ""
        elif production:
            return production, ""

        # Fallback: use flow state and music
        if music_genre:
            if flow_state == "active":
                return "deep work", music_genre
            return "listening", music_genre

        if flow_state == "active":
            return "deep work", ""
        elif flow_state == "warming":
            return "getting focused", ""

        # Watch activity
        watch = self._biometrics.watch_activity
        if watch in ("exercise", "workout"):
            return "exercising", ""
        elif watch == "sleeping":
            return "sleeping", ""

        return "present", ""

    def compute_and_write(self) -> VisualLayerState:
        """Run state machine and write output atomically."""
        all_signals = (
            self._fast_signals + self._slow_signals + self._perception_signals + self._voice_signals
        )

        state = self._sm.tick(
            signals=all_signals,
            flow_score=self._flow_score,
            audio_energy=self._audio_energy,
            production_active=self._production_active,
        )

        # Rotate ambient content
        self._rotate_ambient_text()

        # Camera feed injection (Batch F)
        self._maybe_inject_camera(state.display_state)

        # Apply biometric modulation (Batch E)
        state.ambient_params = self._apply_biometric_modulation(state.ambient_params)

        # Attach additional state
        state.voice_session = self._voice_session
        state.voice_content = self._voice_content
        state.biometrics = self._biometrics
        state.injected_feeds = self._injected_feeds
        state.ambient_text = self._ambient_text

        # Activity label — what Hapax thinks operator is doing
        activity_label, activity_detail = self._infer_activity()
        state.activity_label = activity_label
        state.activity_detail = activity_detail

        # Atomic write
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            tmp = OUTPUT_FILE.with_suffix(".tmp")
            tmp.write_text(state.model_dump_json(), encoding="utf-8")
            tmp.rename(OUTPUT_FILE)
        except OSError:
            log.debug("Failed to write visual layer state", exc_info=True)

        return state

    async def run(self) -> None:
        """Main loop: dual-cadence polling."""
        log.info("Visual layer aggregator starting")
        last_slow = 0.0
        last_ambient = 0.0

        while True:
            now = time.monotonic()

            # Always: read perception state (local file, fast)
            self.poll_perception()

            # Fast cadence: health, GPU
            await self.poll_fast()

            # Slow cadence: nudges, briefing, drift, goals
            if now - last_slow >= SLOW_INTERVAL_S:
                await self.poll_slow()
                last_slow = now

            # Ambient content refresh
            if now - last_ambient >= AMBIENT_CONTENT_INTERVAL_S:
                await self.poll_ambient_content()
                last_ambient = now

            # Compute and write
            state = self.compute_and_write()
            log.debug(
                "State: %s, signals: %d, flow: %.2f, voice: %s",
                state.display_state,
                sum(len(v) for v in state.signals.values()),
                self._flow_score,
                state.voice_session.state if state.voice_session.active else "inactive",
            )

            await asyncio.sleep(FAST_INTERVAL_S)

    async def close(self) -> None:
        await self._client.aclose()


# ── Entry Point ──────────────────────────────────────────────────────────────


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    agg = VisualLayerAggregator()
    try:
        await agg.run()
    finally:
        await agg.close()


if __name__ == "__main__":
    asyncio.run(main())
