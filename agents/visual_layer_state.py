"""Visual communication layer — data models and display state machine.

Pure-logic module: no I/O, no threading, no network. Takes signal inputs
and produces display state + zone opacities. Fully testable in isolation.

Architecture:
  Signal Aggregator (polls API) → VisualLayerState (this module's output)
  → Studio Compositor (reads JSON, renders Cairo overlay)

Five display states, seven signal categories, opacity-driven transitions.
Designed for ADHD/autism operator: muted palette, ≥500ms transitions,
max 5 simultaneous info chunks, flow-state-gated escalation.
"""

from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel, Field

# ── Display States ───────────────────────────────────────────────────────────


class DisplayState(StrEnum):
    """Visual layer operating mode."""

    AMBIENT = "ambient"  # Generative shader only, no data (80% of time)
    PERIPHERAL = "peripheral"  # 1-2 subtle indicators at ~40% opacity (15%)
    INFORMATIONAL = "informational"  # Structured layout, readable (4%)
    ALERT = "alert"  # Critical signal breaks through (1%)
    PERFORMATIVE = "performative"  # Audio-reactive, rules suspended (<1%)


# ── Signal Categories ────────────────────────────────────────────────────────


class SignalCategory(StrEnum):
    """Visual zone categories. Each maps to a fixed spatial zone."""

    CONTEXT_TIME = "context_time"  # Top-left: calendar, briefing, copilot
    GOVERNANCE = "governance"  # Top-right: consent, axioms, drift
    WORK_TASKS = "work_tasks"  # Left edge: nudges, open loops, goals
    HEALTH_INFRA = "health_infra"  # Bottom-right: system health, GPU, containers
    PROFILE_STATE = "profile_state"  # Center-top: flow state, activity mode
    AMBIENT_SENSOR = "ambient_sensor"  # Bottom strip: audio energy, genre
    VOICE_SESSION = "voice_session"  # Bottom-center: voice conversation state


# ── Zone Layout ──────────────────────────────────────────────────────────────


class ZoneSpec(BaseModel, frozen=True):
    """Zone position as fractions of canvas dimensions."""

    x: float
    y: float
    w: float
    h: float


ZONE_LAYOUT: dict[str, ZoneSpec] = {
    SignalCategory.CONTEXT_TIME: ZoneSpec(x=0.01, y=0.03, w=0.25, h=0.12),
    SignalCategory.GOVERNANCE: ZoneSpec(x=0.74, y=0.03, w=0.25, h=0.12),
    SignalCategory.WORK_TASKS: ZoneSpec(x=0.01, y=0.20, w=0.18, h=0.45),
    SignalCategory.HEALTH_INFRA: ZoneSpec(x=0.78, y=0.78, w=0.21, h=0.18),
    SignalCategory.PROFILE_STATE: ZoneSpec(x=0.35, y=0.01, w=0.30, h=0.06),
    SignalCategory.AMBIENT_SENSOR: ZoneSpec(x=0.01, y=0.92, w=0.75, h=0.06),
    SignalCategory.VOICE_SESSION: ZoneSpec(x=0.25, y=0.88, w=0.50, h=0.10),
}


# ── Signal Entry ─────────────────────────────────────────────────────────────


class SignalEntry(BaseModel, frozen=True):
    """A single signal to potentially surface in the visual layer."""

    category: SignalCategory
    severity: float  # 0.0 (info) to 1.0 (critical)
    title: str
    detail: str = ""
    source_id: str = ""


# ── Ambient Parameters ───────────────────────────────────────────────────────


class AmbientParams(BaseModel):
    """Parameters for the generative ambient shader."""

    speed: float = 0.08
    turbulence: float = 0.1
    color_warmth: float = 0.0  # 0.0 = cool teal, 1.0 = warm red
    brightness: float = 0.25


# ── Injected Camera Feed ────────────────────────────────────────────────────


class InjectedFeed(BaseModel):
    """A camera feed injected into the canvas by the aggregator."""

    role: str  # e.g. "brio-operator", "c920-room"
    x: float = 0.6
    y: float = 0.3
    w: float = 0.35
    h: float = 0.35
    opacity: float = 0.7
    css_filter: str = "sepia(0.5) contrast(1.2)"
    duration_s: float = 45.0
    injected_at: float = 0.0


# ── Voice Session State ─────────────────────────────────────────────────────


class VoiceSessionState(BaseModel):
    """Voice conversation state forwarded from perception state."""

    active: bool = False
    state: str = "idle"  # listening | transcribing | thinking | speaking
    turn_count: int = 0
    last_utterance: str = ""
    last_response: str = ""
    active_tool: str | None = None
    barge_in: bool = False


# ── Supplementary Content ────────────────────────────────────────────────────


class SupplementaryContent(BaseModel):
    """A content card surfaced from voice tool execution."""

    content_type: str  # image | text | weather | calendar | status
    title: str
    body: str = ""
    image_path: str = ""
    timestamp: float = 0.0


# ── Biometric State ─────────────────────────────────────────────────────────


class BiometricState(BaseModel):
    """Physiological signals from smartwatch — drives ambient modulation."""

    heart_rate_bpm: int = 0
    stress_elevated: bool = False
    physiological_load: float = 0.0
    sleep_quality: float = 1.0
    watch_activity: str = "unknown"


# ── Visual Layer State (output model) ────────────────────────────────────────


class VisualLayerState(BaseModel):
    """Complete state for the visual communication layer.

    Written atomically to /dev/shm/hapax-compositor/visual-layer-state.json
    by the signal aggregator. Read by the studio compositor for rendering.
    """

    display_state: DisplayState = DisplayState.AMBIENT
    zone_opacities: dict[str, float] = Field(default_factory=dict)
    signals: dict[str, list[SignalEntry]] = Field(default_factory=dict)
    ambient_params: AmbientParams = Field(default_factory=AmbientParams)
    voice_session: VoiceSessionState = Field(default_factory=VoiceSessionState)
    voice_content: list[SupplementaryContent] = Field(default_factory=list)
    biometrics: BiometricState = Field(default_factory=BiometricState)
    injected_feeds: list[InjectedFeed] = Field(default_factory=list)
    ambient_text: str = ""  # Dynamic ambient fragment (replaces hardcoded list)
    activity_label: str = ""  # What Hapax thinks operator is doing
    activity_detail: str = ""  # Supporting detail (app, genre, etc.)
    timestamp: float = 0.0


# ── Opacity Targets per State ────────────────────────────────────────────────

_OPACITY_TARGETS: dict[DisplayState, dict[str, float]] = {
    DisplayState.AMBIENT: {cat: 0.0 for cat in SignalCategory},
    DisplayState.PERIPHERAL: {
        SignalCategory.CONTEXT_TIME: 0.4,
        SignalCategory.GOVERNANCE: 0.4,
        SignalCategory.WORK_TASKS: 0.3,
        SignalCategory.HEALTH_INFRA: 0.3,
        SignalCategory.PROFILE_STATE: 0.2,
        SignalCategory.AMBIENT_SENSOR: 0.15,
        SignalCategory.VOICE_SESSION: 0.6,
    },
    DisplayState.INFORMATIONAL: {
        SignalCategory.CONTEXT_TIME: 0.75,
        SignalCategory.GOVERNANCE: 0.75,
        SignalCategory.WORK_TASKS: 0.7,
        SignalCategory.HEALTH_INFRA: 0.7,
        SignalCategory.PROFILE_STATE: 0.6,
        SignalCategory.AMBIENT_SENSOR: 0.5,
        SignalCategory.VOICE_SESSION: 0.8,
    },
    DisplayState.ALERT: {
        SignalCategory.CONTEXT_TIME: 0.5,
        SignalCategory.GOVERNANCE: 0.5,
        SignalCategory.WORK_TASKS: 0.4,
        SignalCategory.HEALTH_INFRA: 0.9,
        SignalCategory.PROFILE_STATE: 0.3,
        SignalCategory.AMBIENT_SENSOR: 0.3,
        SignalCategory.VOICE_SESSION: 0.7,
    },
    DisplayState.PERFORMATIVE: {cat: 0.0 for cat in SignalCategory},
}

# ── Severity Thresholds ──────────────────────────────────────────────────────

SEVERITY_CRITICAL = 0.85
SEVERITY_HIGH = 0.70
SEVERITY_MEDIUM = 0.40
SEVERITY_LOW = 0.20

MAX_SIGNALS_PER_ZONE = 3
MAX_TOTAL_VISIBLE_SIGNALS = 5

# ── De-escalation Cooldowns (seconds) ────────────────────────────────────────

_DEESCALATION_COOLDOWN: dict[tuple[DisplayState, DisplayState], float] = {
    (DisplayState.ALERT, DisplayState.INFORMATIONAL): 5.0,
    (DisplayState.ALERT, DisplayState.PERIPHERAL): 10.0,
    (DisplayState.ALERT, DisplayState.AMBIENT): 15.0,
    (DisplayState.INFORMATIONAL, DisplayState.PERIPHERAL): 8.0,
    (DisplayState.INFORMATIONAL, DisplayState.AMBIENT): 12.0,
    (DisplayState.PERIPHERAL, DisplayState.AMBIENT): 10.0,
}


# ── Display State Machine ────────────────────────────────────────────────────


class DisplayStateMachine:
    """Pure-logic state machine for the visual layer display mode.

    Escalation is immediate — critical signals appear within one tick.
    De-escalation requires sustained quiet (cooldown timers).
    """

    def __init__(self) -> None:
        self.state = DisplayState.AMBIENT
        self._last_escalation_time: float = 0.0
        self._deescalation_timer: float = 0.0

    def tick(
        self,
        signals: list[SignalEntry],
        flow_score: float = 0.0,
        audio_energy: float = 0.0,
        production_active: bool = False,
        now: float | None = None,
    ) -> VisualLayerState:
        """Compute next state from current signals and perception."""
        if now is None:
            now = time.monotonic()

        max_severity = max((s.severity for s in signals), default=0.0)
        signal_count = len(signals)
        deep_flow = flow_score >= 0.6

        target = self._compute_target_state(
            max_severity=max_severity,
            signal_count=signal_count,
            deep_flow=deep_flow,
            production_active=production_active,
            audio_energy=audio_energy,
        )

        new_state = self._apply_transition(target, now)
        self.state = new_state

        categorized = self._categorize_signals(signals)
        zone_opacities = self._compute_opacities(new_state, categorized)
        ambient = self._compute_ambient_params(max_severity, flow_score, audio_energy)

        return VisualLayerState(
            display_state=new_state,
            zone_opacities=zone_opacities,
            signals={cat: entries for cat, entries in categorized.items() if entries},
            ambient_params=ambient,
            timestamp=now,
        )

    def _compute_target_state(
        self,
        *,
        max_severity: float,
        signal_count: int,
        deep_flow: bool,
        production_active: bool,
        audio_energy: float,
    ) -> DisplayState:
        if production_active and audio_energy > 0.05 and deep_flow:
            return DisplayState.PERFORMATIVE
        if max_severity >= SEVERITY_CRITICAL:
            return DisplayState.ALERT
        if deep_flow:
            return DisplayState.AMBIENT
        if max_severity >= SEVERITY_HIGH:
            return DisplayState.ALERT
        if signal_count >= 3 or max_severity >= SEVERITY_MEDIUM:
            return DisplayState.INFORMATIONAL
        if signal_count > 0:
            return DisplayState.PERIPHERAL
        return DisplayState.AMBIENT

    def _apply_transition(self, target: DisplayState, now: float) -> DisplayState:
        if target == self.state:
            self._deescalation_timer = now
            return self.state

        escalation_order = {
            DisplayState.AMBIENT: 0,
            DisplayState.PERIPHERAL: 1,
            DisplayState.INFORMATIONAL: 2,
            DisplayState.ALERT: 3,
            DisplayState.PERFORMATIVE: -1,
        }

        current_level = escalation_order[self.state]
        target_level = escalation_order[target]

        if target == DisplayState.PERFORMATIVE or self.state == DisplayState.PERFORMATIVE:
            self._deescalation_timer = now
            return target

        if target_level > current_level:
            self._last_escalation_time = now
            self._deescalation_timer = now
            return target

        cooldown = _DEESCALATION_COOLDOWN.get((self.state, target), 10.0)
        elapsed = now - self._deescalation_timer
        if elapsed >= cooldown:
            return target

        return self.state

    def _categorize_signals(self, signals: list[SignalEntry]) -> dict[str, list[SignalEntry]]:
        categorized: dict[str, list[SignalEntry]] = {cat.value: [] for cat in SignalCategory}

        for signal in sorted(signals, key=lambda s: s.severity, reverse=True):
            cat = signal.category.value
            if len(categorized[cat]) < MAX_SIGNALS_PER_ZONE:
                categorized[cat].append(signal)

        all_signals = []
        for entries in categorized.values():
            all_signals.extend(entries)
        all_signals.sort(key=lambda s: s.severity, reverse=True)

        if len(all_signals) > MAX_TOTAL_VISIBLE_SIGNALS:
            keep = set(id(s) for s in all_signals[:MAX_TOTAL_VISIBLE_SIGNALS])
            for cat in categorized:
                categorized[cat] = [s for s in categorized[cat] if id(s) in keep]

        return categorized

    def _compute_opacities(
        self,
        state: DisplayState,
        categorized: dict[str, list[SignalEntry]],
    ) -> dict[str, float]:
        base = dict(_OPACITY_TARGETS[state])

        if state == DisplayState.ALERT:
            max_cat = ""
            max_sev = 0.0
            for cat, entries in categorized.items():
                if entries and entries[0].severity > max_sev:
                    max_sev = entries[0].severity
                    max_cat = cat
            if max_cat:
                base[max_cat] = 0.95

        for cat in base:
            if not categorized.get(cat):
                base[cat] = min(base[cat], 0.0)

        return base

    def _compute_ambient_params(
        self,
        max_severity: float,
        flow_score: float,
        audio_energy: float,
    ) -> AmbientParams:
        speed = 0.08
        turbulence = 0.1
        warmth = 0.0
        brightness = 0.25

        if max_severity > 0.0:
            warmth = min(1.0, max_severity)
            speed = 0.08 + 0.3 * max_severity
            turbulence = 0.1 + 0.3 * max_severity

        if flow_score > 0.3:
            speed *= max(0.3, 1.0 - flow_score)
            turbulence *= max(0.3, 1.0 - flow_score)

        brightness = max(0.15, 0.25 + 0.1 * audio_energy)

        return AmbientParams(
            speed=round(speed, 3),
            turbulence=round(turbulence, 3),
            color_warmth=round(warmth, 3),
            brightness=round(brightness, 3),
        )
