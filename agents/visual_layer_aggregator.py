"""Visual layer signal aggregator — polls cockpit API and perception state.

Standalone async process. Reads signals from the cockpit API and perception
state file, runs the DisplayStateMachine, and writes VisualLayerState
atomically to /dev/shm for the studio compositor to render.

Decoupled dual-loop architecture (WS5):
  State tick (3s, adaptive 0.5-5s): perception → state machine → scheduler → write
  API poll: 15s health/GPU, 60s nudges/briefing, 45s ambient content

Entry point: uv run python -m agents.visual_layer_aggregator
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from agents.content_scheduler import (
    ContentPools,
    ContentScheduler,
    ContentSource,
    SchedulerContext,
    SchedulerDecision,
)
from agents.predictive_cache import PredictiveCache
from agents.protention_engine import ProtentionEngine
from agents.temporal_bands import TemporalBandFormatter
from agents.temporal_delta import compute_temporal_delta
from agents.temporal_filter import ClassificationFilter
from agents.temporal_scales import MultiScaleAggregator
from agents.visual_layer_state import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    AmbientParams,
    BiometricState,
    ClassificationDetection,
    DisplayStateMachine,
    EnvironmentalColor,
    InjectedFeed,
    SignalCategory,
    SignalEntry,
    SignalStaleness,
    SupplementaryContent,
    TemporalContext,
    VisualLayerState,
    VoiceSessionState,
)
from shared.active_correction import CorrectionSeeker
from shared.apperception_tick import ApperceptionTick
from shared.correction_memory import CorrectionStore, check_for_corrections
from shared.episodic_memory import EpisodeBuilder, EpisodeStore
from shared.stimmung import StimmungCollector, SystemStimmung
from shared.telemetry import (
    hapax_interaction,
    trace_api_poll,
    trace_episode_closed,
    trace_phone_signals,
    trace_prediction_tick,
    trace_stimmung_update,
    trace_visual_tick,
)

log = logging.getLogger("visual_layer_aggregator")

# ── Paths ────────────────────────────────────────────────────────────────────

PERCEPTION_STATE_PATH = Path.home() / ".cache" / "hapax-voice" / "perception-state.json"
OUTPUT_DIR = Path("/dev/shm/hapax-compositor")
OUTPUT_FILE = OUTPUT_DIR / "visual-layer-state.json"
STIMMUNG_DIR = Path("/dev/shm/hapax-stimmung")
STIMMUNG_FILE = STIMMUNG_DIR / "state.json"
TEMPORAL_DIR = Path("/dev/shm/hapax-temporal")
TEMPORAL_FILE = TEMPORAL_DIR / "bands.json"

# ── Stimmung data source paths ─────────────────────────────────────────────

HEALTH_HISTORY_PATH = Path("profiles/health-history.jsonl")
INFRA_SNAPSHOT_PATH = Path("profiles/infra-snapshot.json")
LANGFUSE_STATE_PATH = Path.home() / ".cache" / "langfuse-sync" / "state.json"

# ── Cadences ─────────────────────────────────────────────────────────────────

STATE_TICK_BASE_S = 3.0  # Base state tick (adaptive: 0.5-5.0s)
HEALTH_POLL_S = 15.0  # Health + GPU
SLOW_POLL_S = 60.0  # Nudges, briefing, drift, goals, copilot
AMBIENT_CONTENT_INTERVAL_S = 45.0  # Ambient content pool refresh
AMBIENT_POOL_REFRESH_S = 300.0  # Full pool refresh every 5 min

# Legacy alias for backward compat with tests
FAST_INTERVAL_S = STATE_TICK_BASE_S
SLOW_INTERVAL_S = SLOW_POLL_S

# ── API ──────────────────────────────────────────────────────────────────────

# ── Camera roles available for injection ─────────────────────────────────────
from shared.cameras import (
    CAMERA_ROLES,
    can_enrich_persons,
)
from shared.cameras import (
    SHORT_TO_ROLE as _ROLE_MAP,
)
from shared.cameras import (
    resolution as cam_resolution,
)
from shared.config import COCKPIT_API_URL as COCKPIT_BASE

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

    # Consent phase as governance signal — escalating severity by phase
    consent = data.get("consent_phase", "no_guest")
    if consent not in ("no_guest", ""):
        consent_severity = {
            "guest_detected": SEVERITY_LOW,
            "consent_pending": SEVERITY_HIGH,
            "consent_refused": SEVERITY_CRITICAL,
            "consent_granted": SEVERITY_LOW,
        }
        consent_titles = {
            "guest_detected": "Guest detected — identifying",
            "consent_pending": "Consent pending — data curtailed",
            "consent_refused": "Consent refused — data purged",
            "consent_granted": "Guest consented",
        }
        signals.append(
            SignalEntry(
                category=SignalCategory.GOVERNANCE,
                severity=consent_severity.get(consent, SEVERITY_MEDIUM),
                title=consent_titles.get(consent, f"Consent: {consent.replace('_', ' ')}"),
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
        routing_tier=vs.get("routing_tier", ""),
        routing_reason=vs.get("routing_reason", ""),
        routing_activation=vs.get("routing_activation", 0.0),
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


def map_stimmung(stimmung: SystemStimmung) -> list[SignalEntry]:
    """Map non-nominal stimmung dimensions to system_state signals."""
    signals: list[SignalEntry] = []
    for name, dim in stimmung.non_nominal_dimensions.items():
        severity = min(1.0, dim.value)
        label = name.replace("_", " ")
        trend_suffix = f" ({dim.trend})" if dim.trend != "stable" else ""
        signals.append(
            SignalEntry(
                category=SignalCategory.SYSTEM_STATE,
                severity=severity,
                title=f"{label}: {dim.value:.0%}{trend_suffix}",
                source_id=f"stimmung-{name}",
            )
        )
    return signals


def _map_scene_inventory(data: dict) -> list[ClassificationDetection]:
    """Map scene_inventory from perception state to classification detections.

    Normalizes bounding boxes to 0-1, computes novelty from seen_count,
    checks consent phase for person suppression. Attaches person enrichments
    from perception-state top-level keys when on operator camera and not
    consent-suppressed. Returns top 5 by confidence.
    """
    inventory = data.get("scene_inventory", {})
    objects = inventory.get("objects", [])
    consent_phase = data.get("consent_phase", "no_guest")
    suppress_person_enrichments = consent_phase in (
        "guest_detected",
        "consent_pending",
        "consent_refused",
    )
    remove_person_detections = consent_phase == "consent_refused"

    # Camera config from shared.cameras (supports 6 cameras: 3 Brio + 3 C920)

    # Person enrichments from perception-state top-level keys (global, first-person only)
    _ENRICHMENT_MAP = (
        ("gaze_direction", "gaze_direction"),
        ("emotion", "top_emotion"),
        ("posture", "posture"),
        ("gesture", "hand_gesture"),
        ("action", "detected_action"),
        ("depth", "nearest_person_distance"),
    )
    person_enrichments: dict[str, str | None] = {}
    if not suppress_person_enrichments:
        for field, key in _ENRICHMENT_MAP:
            val = data.get(key, "")
            person_enrichments[field] = val if val else None

    detections: list[ClassificationDetection] = []
    for obj in objects:
        confidence = obj.get("confidence", 0.0)
        if confidence < 0.3:
            continue

        camera_raw = obj.get("camera", "")
        camera = _ROLE_MAP.get(camera_raw, camera_raw)
        label = obj.get("label", "")
        entity_id = obj.get("entity_id", "")

        # Compute novelty from seen_count (fewer sightings = more novel)
        seen_count = obj.get("seen_count", 1)
        novelty = max(0.0, min(1.0, 1.0 - (seen_count - 1) / 20.0))

        # Normalize bounding box to 0-1 coordinates
        # Objects from snapshot() don't include raw box, check for it
        box_raw = obj.get("box", obj.get("last_box"))
        if box_raw and len(box_raw) == 4:
            res_w, res_h = cam_resolution(camera_raw)
            x1 = max(0.0, min(1.0, box_raw[0] / res_w))
            y1 = max(0.0, min(1.0, box_raw[1] / res_h))
            x2 = max(0.0, min(1.0, box_raw[2] / res_w))
            y2 = max(0.0, min(1.0, box_raw[3] / res_h))
            box = (x1, y1, x2, y2)
        else:
            continue  # Skip objects without bbox data

        is_person = label == "person"

        # CONSENT_REFUSED: remove non-operator person detections entirely
        if is_person and remove_person_detections:
            continue

        consent_suppressed = suppress_person_enrichments and is_person
        is_enrichment_cam = can_enrich_persons(camera_raw)

        # Person enrichments: for persons on any enrichment-capable camera, not suppressed
        # Prefer per-entity enrichments from inventory, fall back to global perception-state
        enrichment_kwargs: dict[str, Any] = {}
        if is_person and is_enrichment_cam and not consent_suppressed:
            for field_name in (
                "gaze_direction",
                "emotion",
                "posture",
                "gesture",
                "action",
                "depth",
            ):
                entity_val = obj.get(field_name)
                if entity_val:
                    enrichment_kwargs[field_name] = entity_val
                elif person_enrichments.get(field_name):
                    enrichment_kwargs[field_name] = person_enrichments[field_name]

        # Entity metadata (available for all entities from snapshot_for_overlay)
        mobility_score_raw = obj.get("mobility_score")
        first_seen_age_raw = obj.get("first_seen_age_s")
        camera_count_raw = obj.get("camera_count")

        # Normalize sightings to tuples
        raw_sightings = obj.get("sightings")
        norm_sightings: list[tuple[float, float, float, float]] | None = None
        if raw_sightings and isinstance(raw_sightings, list):
            norm_sightings = []
            for sb in raw_sightings[-5:]:
                if isinstance(sb, (list, tuple)) and len(sb) == 4:
                    norm_sightings.append(
                        (
                            float(sb[0]),
                            float(sb[1]),
                            float(sb[2]),
                            float(sb[3]),
                        )
                    )

        # Temporal delta: compute from raw sightings with timestamps
        temporal_kwargs: dict[str, Any] = {}
        raw_sightings = obj.get("raw_sightings", [])
        first_seen_ts = obj.get("first_seen", 0.0)
        last_seen_ts = obj.get("last_seen", 0.0)
        if raw_sightings and len(raw_sightings) >= 2:
            now_ts = time.time()
            delta = compute_temporal_delta(
                sightings=raw_sightings,
                first_seen=first_seen_ts,
                last_seen=last_seen_ts,
                now=now_ts,
                camera=camera_raw,  # filter to same-camera sightings
            )
            temporal_kwargs = {
                "velocity": delta.velocity,
                "direction_deg": delta.direction_deg,
                "confidence_stability": delta.confidence_stability,
                "dwell_s": delta.dwell_s,
                "is_entering": delta.is_entering,
                "is_exiting": delta.is_exiting,
            }

        detections.append(
            ClassificationDetection(
                entity_id=entity_id,
                label=label,
                camera=camera,
                box=box,
                confidence=confidence,
                mobility=obj.get("mobility", "unknown"),
                novelty=novelty,
                consent_suppressed=consent_suppressed,
                mobility_score=float(mobility_score_raw)
                if mobility_score_raw is not None
                else None,
                first_seen_age_s=float(first_seen_age_raw)
                if first_seen_age_raw is not None
                else None,
                camera_count=int(camera_count_raw) if camera_count_raw is not None else None,
                sightings=norm_sightings if norm_sightings else None,
                **enrichment_kwargs,
                **temporal_kwargs,
            )
        )

    # Sort by confidence descending, take top 5
    detections.sort(key=lambda d: d.confidence, reverse=True)
    return detections[:5]


def map_biometrics(data: dict) -> BiometricState:
    """Map biometric fields from perception state."""
    return BiometricState(
        heart_rate_bpm=data.get("heart_rate_bpm", 0),
        stress_elevated=data.get("stress_elevated", False),
        physiological_load=data.get("physiological_load", 0.0),
        sleep_quality=data.get("sleep_quality", 1.0),
        watch_activity=data.get("watch_activity_state", "unknown"),
        phone_battery_pct=data.get("phone_battery_pct", 0),
        phone_connected=data.get("phone_kde_connected", False),
    )


def map_phone(data: dict) -> list[SignalEntry]:
    """Map phone/KDEConnect fields to visual layer signals."""
    signals: list[SignalEntry] = []

    # Incoming call — CRITICAL, bypasses deep-flow gate
    if data.get("phone_call_incoming"):
        number = data.get("phone_call_number", "unknown")
        signals.append(
            SignalEntry(
                category=SignalCategory.PROFILE_STATE,
                severity=SEVERITY_CRITICAL,
                title="Incoming call",
                detail=number,
                source_id="phone_call",
            )
        )
    elif data.get("phone_call_active"):
        signals.append(
            SignalEntry(
                category=SignalCategory.PROFILE_STATE,
                severity=SEVERITY_HIGH,
                title="On call",
                detail=data.get("phone_call_number", ""),
                source_id="phone_call",
            )
        )

    # Battery
    battery = data.get("phone_battery_pct", 0)
    charging = data.get("phone_battery_charging", False)
    if battery > 0 and battery < 15:
        signals.append(
            SignalEntry(
                category=SignalCategory.PROFILE_STATE,
                severity=SEVERITY_HIGH,
                title="Phone battery low",
                detail=f"{battery}%",
                source_id="phone_battery",
            )
        )
    elif battery > 0 and battery < 30 and not charging:
        signals.append(
            SignalEntry(
                category=SignalCategory.PROFILE_STATE,
                severity=SEVERITY_MEDIUM,
                title="Phone battery",
                detail=f"{battery}%",
                source_id="phone_battery",
            )
        )

    # SMS unread
    sms_unread = data.get("phone_sms_unread", 0)
    if sms_unread > 0:
        sender = data.get("phone_sms_sender", "")
        signals.append(
            SignalEntry(
                category=SignalCategory.WORK_TASKS,
                severity=SEVERITY_LOW,
                title=f"{sms_unread} unread SMS",
                detail=sender,
                source_id="phone_sms",
            )
        )

    # Notifications threshold
    notif_count = data.get("phone_notification_count", 0)
    if notif_count >= 5:
        signals.append(
            SignalEntry(
                category=SignalCategory.WORK_TASKS,
                severity=SEVERITY_LOW,
                title=f"{notif_count} notifications",
                detail="",
                source_id="phone_notifications",
            )
        )

    # Media playing
    if data.get("phone_media_playing"):
        title = data.get("phone_media_title", "")
        artist = data.get("phone_media_artist", "")
        if title:
            media_text = f"{title} — {artist}" if artist else title
            signals.append(
                SignalEntry(
                    category=SignalCategory.AMBIENT_SENSOR,
                    severity=SEVERITY_LOW,
                    title="Now playing",
                    detail=media_text[:60],
                    source_id="phone_media",
                )
            )

    # KDE disconnected — only flag when we've seen phone data before
    kde_connected = data.get("phone_kde_connected")
    has_prior_data = data.get("phone_battery_pct", 0) > 0 or data.get("phone_sms_unread", 0) > 0
    if kde_connected is False and has_prior_data:
        signals.append(
            SignalEntry(
                category=SignalCategory.HEALTH_INFRA,
                severity=SEVERITY_MEDIUM,
                title="Phone disconnected",
                detail="KDE Connect lost",
                source_id="phone_kde",
            )
        )

    return signals


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
        self._phone_signals: list[SignalEntry] = []
        self._flow_score: float = 0.0
        self._audio_energy: float = 0.0
        self._production_active: bool = False

        # Voice session + content state
        self._voice_session = VoiceSessionState()
        self._voice_content: list[SupplementaryContent] = []
        self._biometrics = BiometricState()

        # Classification detection overlay
        self._classification_detections: list[ClassificationDetection] = []
        # Per-entity temporal stability filters (Batch 4)
        self._entity_filters: dict[str, ClassificationFilter] = {}

        # Content scheduler (replaces _rotate_ambient_text + _maybe_inject_camera)
        self._scheduler = ContentScheduler()
        self._ambient_text: str = ""
        self._ambient_facts: list[str] = []
        self._nudge_titles: list[str] = []
        self._ambient_moments: list[str] = []
        self._last_ambient_fetch: float = 0.0
        self._injected_feeds: list[InjectedFeed] = []

        # Staleness tracking (Phase 3)
        self._ts_perception: float = 0.0
        self._ts_health: float = 0.0
        self._ts_gpu: float = 0.0
        self._ts_nudges: float = 0.0
        self._ts_briefing: float = 0.0

        # Adaptive cadence state (Phase 5)
        self._prev_display_state: str = "ambient"
        self._last_perception_data: dict[str, Any] = {}

        # Stimmung (WS2): system self-state
        self._stimmung_collector = StimmungCollector()
        self._stimmung: SystemStimmung | None = None

        # Protention engine (WS1): statistical transition predictions
        self._protention = ProtentionEngine()
        self._protention.load()  # restore learned state
        self._last_protention_save: float = 0.0

        # Predictive cache (WS5): pre-computed visual states for likely transitions
        self._predictive_cache = PredictiveCache()

        # Multi-scale temporal aggregator (WS1)
        self._multi_scale = MultiScaleAggregator()

        # WS1: temporal band formatter — retention/impression/protention for LLM prompts
        self._temporal_formatter = TemporalBandFormatter(protention_engine=self._protention)

        # WS3: experiential learning pipeline
        self._episode_builder = EpisodeBuilder()
        self._episode_store: EpisodeStore | None = None
        self._correction_store: CorrectionStore | None = None
        self._correction_seeker = CorrectionSeeker()
        self._ws3_initialized = False

        # Self-band: apperception tick (standalone, reads from shm)
        self._apperception = ApperceptionTick()

        # BOCPD: change-point detection on perception signals
        from agents.bocpd import MultiSignalBOCPD

        self._bocpd = MultiSignalBOCPD(
            signals=["flow_score", "audio_energy", "heart_rate"],
            hazard_lambda=30,
            threshold=0.2,
        )
        self._last_change_points: list[dict] = []

    async def _fetch_json(self, path: str) -> dict | list | None:
        """Fetch a cockpit API endpoint. Returns None on any error."""
        t0 = time.monotonic()
        try:
            resp = await self._client.get(path)
            latency_ms = (time.monotonic() - t0) * 1000
            if resp.status_code == 200:
                trace_api_poll(path, latency_ms, success=True, status_code=200)
                return resp.json()
            trace_api_poll(path, latency_ms, success=False, status_code=resp.status_code)
        except Exception:
            latency_ms = (time.monotonic() - t0) * 1000
            trace_api_poll(path, latency_ms, success=False)
            log.debug("Failed to fetch %s", path, exc_info=True)
        return None

    async def poll_fast(self) -> None:
        """Poll fast-cadence endpoints (health, GPU)."""
        signals: list[SignalEntry] = []
        now = time.monotonic()

        health = await self._fetch_json("/health")
        if isinstance(health, dict):
            signals.extend(map_health(health))
            self._ts_health = now

        gpu = await self._fetch_json("/gpu")
        if isinstance(gpu, dict):
            signals.extend(map_gpu(gpu))
            self._ts_gpu = now

        self._fast_signals = signals

    async def poll_slow(self) -> None:
        """Poll slow-cadence endpoints (nudges, briefing, drift, goals, copilot)."""
        signals: list[SignalEntry] = []
        now = time.monotonic()

        nudges = await self._fetch_json("/nudges")
        if isinstance(nudges, list):
            signals.extend(map_nudges(nudges))
            self._ts_nudges = now

        briefing = await self._fetch_json("/briefing")
        if isinstance(briefing, dict):
            signals.extend(map_briefing(briefing))
            self._ts_briefing = now

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
            self._ts_perception = time.monotonic()
            self._last_perception_data = data

            # Voice session (Batch A)
            voice_signals, voice_state = map_voice_session(data)
            self._voice_signals = voice_signals
            self._voice_session = voice_state

            # Supplementary content (Batch B)
            self._voice_content = map_voice_content(data)

            # Biometrics (Batch E)
            self._biometrics = map_biometrics(data)

            # Phone signals (Batch F)
            self._phone_signals = map_phone(data)
            if self._phone_signals or data.get("phone_kde_connected"):
                trace_phone_signals(
                    signal_count=len(self._phone_signals),
                    battery_pct=data.get("phone_battery_pct", 0),
                    connected=data.get("phone_kde_connected", False),
                    signals=[s.title for s in self._phone_signals],
                )

            # Phone media → ambient moments
            if data.get("phone_media_playing"):
                title = data.get("phone_media_title", "")
                artist = data.get("phone_media_artist", "")
                if title:
                    media_text = f"Now playing: {title}" + (f" — {artist}" if artist else "")
                    self._ambient_moments = [
                        m for m in self._ambient_moments if not m.startswith("Now playing:")
                    ]
                    self._ambient_moments.append(media_text)

            # Classification detection overlay
            raw_detections = _map_scene_inventory(data)
            self._classification_detections = self._apply_stability_filter(raw_detections)

            # BOCPD: detect activity transitions
            bocpd_cps = self._bocpd.update(
                {
                    "flow_score": self._flow_score,
                    "audio_energy": self._audio_energy,
                    "heart_rate": float(self._biometrics.heart_rate_bpm),
                },
                timestamp=time.time(),
            )
            if bocpd_cps:
                self._last_change_points = [
                    {
                        "signal": cp.signal_name,
                        "probability": cp.probability,
                        "timestamp": cp.timestamp,
                        "run_length": cp.run_length_before,
                    }
                    for cp in bocpd_cps
                ]
                log.info(
                    "Change points detected: %s",
                    ", ".join(f"{cp.signal_name}(p={cp.probability:.2f})" for cp in bocpd_cps),
                )

            # WS1: feed multi-scale aggregator
            self._multi_scale.tick(data)

            # WS1: feed protention engine with best available activity
            # Precedence: workspace monitor > LLM classification > empty
            best_activity = data.get("production_activity", "")
            if not best_activity:
                llm_act = data.get("llm_activity", "")
                if llm_act and llm_act != "idle":
                    best_activity = llm_act
            self._protention.observe(
                activity=best_activity,
                flow_score=data.get("flow_score", 0.0),
                hour=datetime.now().hour,
            )

            # WS3: experiential learning pipeline
            self._tick_experiential(data)

        except (FileNotFoundError, json.JSONDecodeError):
            pass  # perception daemon may not be running

    def _init_ws3(self) -> None:
        """Lazy-init WS3 stores (avoids Qdrant connection at import time)."""
        if self._ws3_initialized:
            return
        self._ws3_initialized = True
        try:
            self._correction_store = CorrectionStore()
            self._correction_store.ensure_collection()
            self._episode_store = EpisodeStore()
            self._episode_store.ensure_collection()
        except Exception:
            log.debug("WS3 stores unavailable (Qdrant down?)", exc_info=True)
            self._correction_store = None
            self._episode_store = None

    def _tick_experiential(self, data: dict) -> None:
        """Feed perception data to the WS3 experiential pipeline.

        Called every perception tick. Lazy-inits Qdrant stores on first call.
        All operations are best-effort — failures don't block perception.
        """
        self._init_ws3()

        # 1. Episode boundary detection
        if self._episode_store is not None:
            try:
                episode = self._episode_builder.observe(data)
                if episode is not None:
                    self._episode_store.record(episode)
                    log.info(
                        "Episode recorded: %s (%.0fs, %d snapshots)",
                        episode.activity,
                        episode.duration_s,
                        episode.snapshot_count,
                    )
                    trace_episode_closed(
                        activity=episode.activity,
                        duration_s=episode.duration_s,
                        flow_state=episode.flow_state,
                        snapshot_count=episode.snapshot_count,
                    )
            except Exception:
                log.debug("Episode recording failed", exc_info=True)

        # 2. Correction intake (check if operator submitted a correction)
        if self._correction_store is not None:
            try:
                check_for_corrections(self._correction_store, data)
            except Exception:
                log.debug("Correction intake failed", exc_info=True)

        # 3. Active correction seeking
        if self._correction_store is not None:
            try:
                stimmung_stance = (
                    self._stimmung.overall_stance.value if self._stimmung else "nominal"
                )
                confidence = data.get("aggregate_confidence", 1.0)
                self._correction_seeker.evaluate(
                    activity=data.get("production_activity", ""),
                    flow_score=data.get("flow_score", 0.0),
                    confidence=float(confidence),
                    hour=datetime.now().hour,
                    stimmung_stance=stimmung_stance,
                    correction_store=self._correction_store,
                )
            except Exception:
                log.debug("Active correction seeking failed", exc_info=True)

    def _update_stimmung(self) -> None:
        """Collect stimmung readings from all available data sources.

        Best-effort: each source silently falls back to defaults on error.
        Called from _api_poll_loop every 15s alongside health/GPU polls.
        """
        # 1. Health history — last line of JSONL
        try:
            text = HEALTH_HISTORY_PATH.read_text(encoding="utf-8").strip()
            if text:
                last_line = text.split("\n")[-1]
                h = json.loads(last_line)
                healthy = h.get("healthy", 0)
                total = h.get("total", healthy + h.get("degraded", 0) + h.get("failed", 0))
                self._stimmung_collector.update_health(healthy, total)
        except (OSError, json.JSONDecodeError, IndexError):
            pass

        # 2. Infra snapshot → GPU
        try:
            infra = json.loads(INFRA_SNAPSHOT_PATH.read_text(encoding="utf-8"))
            gpu = infra.get("gpu", {})
            used = gpu.get("used_mb", 0)
            total = gpu.get("total_mb", 0)
            if total > 0:
                self._stimmung_collector.update_gpu(used, total)
        except (OSError, json.JSONDecodeError):
            pass

        # 3. Langfuse sync state
        try:
            lf = json.loads(LANGFUSE_STATE_PATH.read_text(encoding="utf-8"))
            daily_costs = lf.get("daily_costs", {})
            # Sum today's cost (keys are date strings)
            from datetime import date

            today = date.today().isoformat()
            daily_cost = daily_costs.get(today, 0.0) if isinstance(daily_costs, dict) else 0.0
            self._stimmung_collector.update_langfuse(
                daily_cost=float(daily_cost),
                error_count=int(lf.get("error_count", 0)),
                total_traces=int(lf.get("total_traces_synced", 0)),
            )
        except (OSError, json.JSONDecodeError):
            pass

        # 4. Engine status via API — done in poll_fast already, use cached response
        # (avoid double HTTP call — we'll update from _api_poll_loop directly)

        # 5. Perception freshness + confidence
        now = time.monotonic()
        perception_age = now - self._ts_perception if self._ts_perception else 60.0
        confidence = self._last_perception_data.get("aggregate_confidence", 1.0)
        self._stimmung_collector.update_perception(
            freshness_s=perception_age, confidence=float(confidence)
        )

        # 6. Snapshot
        prev_stance = self._stimmung.overall_stance.value if self._stimmung else "nominal"
        self._stimmung = self._stimmung_collector.snapshot()

        # 7. Telemetry
        trace_stimmung_update(
            stance=self._stimmung.overall_stance.value,
            health=self._stimmung.health.value,
            resource_pressure=self._stimmung.resource_pressure.value,
            error_rate=self._stimmung.error_rate.value,
            throughput=self._stimmung.processing_throughput.value,
            perception_confidence=self._stimmung.perception_confidence.value,
            llm_cost=self._stimmung.llm_cost_pressure.value,
            prev_stance=prev_stance,
        )

        # 8. Write atomically
        self._write_stimmung()

        # 9. WS1: compute and write temporal bands for LLM prompt injection
        self._write_temporal_bands()

    def _write_stimmung(self) -> None:
        """Write stimmung state to /dev/shm for external consumers."""
        if self._stimmung is None:
            return
        try:
            STIMMUNG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = STIMMUNG_FILE.with_suffix(".tmp")
            tmp.write_text(self._stimmung.model_dump_json(), encoding="utf-8")
            tmp.rename(STIMMUNG_FILE)
        except OSError:
            log.debug("Failed to write stimmung state", exc_info=True)

    def _write_temporal_bands(self) -> None:
        """Compute temporal bands from perception ring and write to shm.

        Agents read this via shared.operator._read_temporal_block() for
        Husserlian temporal context in LLM prompts.
        """
        try:
            from agents.hapax_voice._perception_state_writer import get_perception_ring
        except ImportError:
            return

        ring = get_perception_ring()
        if ring is None or len(ring) < 2:
            return

        try:
            bands = self._temporal_formatter.format(ring)
            xml = self._temporal_formatter.format_xml(bands)
            payload = {
                "xml": xml,
                "max_surprise": bands.max_surprise,
                "retention_count": len(bands.retention),
                "protention_count": len(bands.protention),
                "surprise_count": len(bands.surprises),
                "timestamp": time.time(),
            }
            TEMPORAL_DIR.mkdir(parents=True, exist_ok=True)
            tmp = TEMPORAL_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.rename(TEMPORAL_FILE)
        except Exception:
            log.debug("Failed to write temporal bands", exc_info=True)

    # ── Self-band: Apperception (delegated to ApperceptionTick) ────────────

    def _tick_apperception(self) -> None:
        """Delegate to standalone ApperceptionTick (reads all inputs from shm)."""
        self._apperception.tick()

    def _save_apperception_model(self) -> None:
        """Delegate model persistence to ApperceptionTick."""
        self._apperception.save_model()

    def _compute_staleness(self) -> SignalStaleness:
        """Compute per-source staleness from last-update timestamps."""
        now = time.monotonic()
        return SignalStaleness(
            perception_s=round(now - self._ts_perception, 1) if self._ts_perception else 0.0,
            health_s=round(now - self._ts_health, 1) if self._ts_health else 0.0,
            gpu_s=round(now - self._ts_gpu, 1) if self._ts_gpu else 0.0,
            nudges_s=round(now - self._ts_nudges, 1) if self._ts_nudges else 0.0,
            briefing_s=round(now - self._ts_briefing, 1) if self._ts_briefing else 0.0,
        )

    def _compute_temporal_context(self) -> TemporalContext:
        """Build temporal context from the perception ring buffer."""
        try:
            from agents.hapax_voice._perception_state_writer import get_perception_ring
        except ImportError:
            return TemporalContext()

        ring = get_perception_ring()
        if ring is None or len(ring) < 2:
            return TemporalContext(
                perception_age_s=round(time.monotonic() - self._ts_perception, 1)
                if self._ts_perception
                else 0.0,
            )

        return TemporalContext(
            trend_flow=round(ring.trend("flow_score", window_s=15.0), 4),
            trend_audio=round(ring.trend("audio_energy_rms", window_s=15.0), 4),
            trend_hr=round(ring.trend("heart_rate_bpm", window_s=20.0), 4),
            perception_age_s=round(time.monotonic() - self._ts_perception, 1)
            if self._ts_perception
            else 0.0,
            ring_depth=len(ring),
        )

    def _adaptive_tick_interval(self, state: VisualLayerState) -> float:
        """Compute adaptive tick interval based on volatility + stimmung. Bounded [0.5, 5.0].

        Speeds up for: state transitions, voice active, perception trends changing,
                       error rate spikes (track recovery).
        Slows down for: sustained ambient, operator absent, presenting,
                        resource pressure, degraded/critical stance.
        """
        interval = STATE_TICK_BASE_S  # 3.0s base

        # State transition just happened → fast updates
        if state.display_state != self._prev_display_state:
            return 0.5

        # Voice active → responsive
        if self._voice_session.active:
            return 1.0

        # Perception trends changing → track closely
        tc = state.temporal_context
        if abs(tc.trend_flow) > 0.01 or abs(tc.trend_audio) > 0.01:
            return 1.5

        # WS2: Stimmung-driven modulation — system interoception affects tick rate
        if self._stimmung is not None:
            stance = self._stimmung.overall_stance.value

            # Critical → conserve aggressively (only state transitions break through above)
            if stance == "critical":
                return 5.0

            # Degraded → slow down, preserve resources
            if stance == "degraded":
                interval = max(interval, 4.0)

            # High resource pressure → back off even in nominal/cautious
            if self._stimmung.resource_pressure.value > 0.7:
                interval = max(interval, 4.0)

            # Error rate spiking → speed up to track recovery
            if (
                self._stimmung.error_rate.value > 0.5
                and self._stimmung.error_rate.trend == "rising"
            ):
                interval = min(interval, 1.5)

            # LLM cost pressure high → slow down (fewer ticks = fewer downstream LLM calls)
            if self._stimmung.llm_cost_pressure.value > 0.6:
                interval = max(interval, 3.5)

        # Sustained ambient → slow down
        if state.display_state == "ambient" and not self._production_active:
            interval = max(interval, 5.0)

        # Presenting mode → minimal updates
        if state.display_density == "presenting":
            interval = max(interval, 4.0)

        # Operator absent (no perception updates for >10s)
        if tc.perception_age_s > 10.0:
            interval = max(interval, 5.0)

        return max(0.5, min(5.0, interval))

    async def poll_ambient_content(self) -> None:
        """Fetch ambient content from cockpit API (profile facts, moments, nudges)."""
        now = time.monotonic()
        if now - self._last_ambient_fetch < 300.0:  # refresh pool every 5 min
            return
        self._last_ambient_fetch = now

        data = await self._fetch_json("/studio/ambient-content")
        if isinstance(data, dict):
            facts = data.get("facts", [])
            if facts:
                self._ambient_facts = facts
            moments = data.get("moments", [])
            if moments:
                self._ambient_moments = moments
            nudge_titles = data.get("nudge_titles", [])
            if nudge_titles:
                self._nudge_titles = nudge_titles

    def _run_scheduler(self, state: VisualLayerState) -> None:
        """Run the content scheduler and apply its decision."""
        now = time.monotonic()

        # Expire old camera injections
        self._injected_feeds = [
            f for f in self._injected_feeds if now - f.injected_at < f.duration_s
        ]

        activity_label, _ = self._infer_activity()
        tc = state.temporal_context if state.temporal_context else TemporalContext()
        ctx = SchedulerContext(
            activity=activity_label,
            flow_score=self._flow_score,
            audio_energy=self._audio_energy,
            stress_elevated=self._biometrics.stress_elevated,
            heart_rate=self._biometrics.heart_rate_bpm,
            sleep_quality=self._biometrics.sleep_quality,
            voice_active=self._voice_session.active,
            display_state=state.display_state,
            hour=datetime.now().hour,
            signal_count=sum(len(v) for v in state.signals.values()),
            # Phase 6: temporal context from perception ring
            trend_flow=tc.trend_flow,
            trend_audio=tc.trend_audio,
            perception_age_s=tc.perception_age_s,
            # WS2: stimmung stance
            stimmung_stance=self._stimmung.overall_stance.value if self._stimmung else "nominal",
            # Classification consumption: enriched perception signals
            gaze_direction=self._last_perception_data.get("gaze_direction", "unknown"),
            emotion=self._last_perception_data.get("top_emotion", "neutral"),
            posture=self._last_perception_data.get("posture", "unknown"),
            # BOCPD: activity transition detected in last 30s
            recent_transition=any(
                time.time() - cp.get("timestamp", 0) < 30.0 for cp in self._last_change_points
            ),
        )

        pools = ContentPools(
            facts=self._ambient_facts,
            moments=self._ambient_moments,
            nudge_titles=self._nudge_titles,
            camera_roles=CAMERA_ROLES,
            camera_filters=CAMERA_FILTERS,
        )

        decision = self._scheduler.tick(ctx, pools, now=now)
        if decision:
            self._apply_scheduler_decision(decision, state, now)
            state.scheduler_source = decision.source.value
            state.display_density = self._scheduler._compute_density(ctx).value

    def _apply_scheduler_decision(
        self, decision: SchedulerDecision, state: VisualLayerState, now: float
    ) -> None:
        """Apply a scheduler decision to the visual layer state."""
        if decision.source == ContentSource.PROFILE_FACT and decision.content:
            self._ambient_text = decision.content

        elif decision.source == ContentSource.CAMERA_FEED and decision.camera_role:
            if not self._injected_feeds:  # don't stack camera feeds
                feed = InjectedFeed(
                    role=decision.camera_role,
                    x=decision.camera_x,
                    y=decision.camera_y,
                    w=decision.camera_w,
                    h=decision.camera_h,
                    opacity=decision.camera_opacity,
                    css_filter=decision.camera_filter,
                    duration_s=decision.dwell_s,
                    injected_at=now,
                )
                self._injected_feeds.append(feed)
                log.debug("Scheduler injected camera: %s", decision.camera_role)

        elif decision.content and decision.source in (
            ContentSource.STUDIO_MOMENT,
            ContentSource.SIGNAL_CARD,
        ):
            self._ambient_text = decision.content

        # Apply shader nudge
        nudge = decision.shader_nudge
        state.ambient_params.speed = round(state.ambient_params.speed * nudge.speed_mult, 3)
        state.ambient_params.turbulence = round(
            state.ambient_params.turbulence * nudge.turbulence_mult, 3
        )
        state.ambient_params.color_warmth = round(
            min(1.0, max(0.0, state.ambient_params.color_warmth + nudge.warmth_offset)), 3
        )
        state.ambient_params.brightness = round(
            min(1.0, max(0.0, state.ambient_params.brightness + nudge.brightness_offset)), 3
        )

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

    def _apply_stability_filter(
        self, detections: list[ClassificationDetection]
    ) -> list[ClassificationDetection]:
        """Apply N-of-M hysteresis filter to prevent flickering enrichments.

        Per-entity filters ensure gaze/emotion/posture/gesture/action/mobility
        only change after 3 consistent readings in a 5-sample window.
        """
        # GC stale filters for entities no longer present
        active_ids = {d.entity_id for d in detections}
        stale = [eid for eid in self._entity_filters if eid not in active_ids]
        for eid in stale:
            del self._entity_filters[eid]

        filtered: list[ClassificationDetection] = []
        for det in detections:
            if det.entity_id not in self._entity_filters:
                self._entity_filters[det.entity_id] = ClassificationFilter()

            filt = self._entity_filters[det.entity_id]
            stable = filt.filter(
                gaze_direction=det.gaze_direction,
                emotion=det.emotion,
                posture=det.posture,
                gesture=det.gesture,
                action=det.action,
                mobility=det.mobility,
            )

            # Reconstruct detection with filtered values
            filtered.append(
                det.model_copy(
                    update={
                        "gaze_direction": stable.get("gaze_direction"),
                        "emotion": stable.get("emotion"),
                        "posture": stable.get("posture"),
                        "gesture": stable.get("gesture"),
                        "action": stable.get("action"),
                        "mobility": stable.get("mobility") or det.mobility,
                    }
                )
            )

        return filtered

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

        # CLIP scene_state inference — between workspace monitor and LLM fallback
        scene_state_clip = perception_data.get("scene_state_clip", "")
        _CLIP_ACTIVITY_MAP = {
            "focused coding": "coding",
            "music production": "making music",
            "video meeting": "in a meeting",
            "reading": "reading",
            "conversation": "in conversation",
        }
        clip_activity = _CLIP_ACTIVITY_MAP.get(scene_state_clip, "")
        if clip_activity:
            return clip_activity, "(CLIP)"

        # LLM activity classification as fallback (WS5)
        # Precedence: operator correction > voice > workspace monitor > LLM > flow/music
        llm_activity = perception_data.get("llm_activity", "")
        if not production and llm_activity and llm_activity != "idle":
            llm_confidence = perception_data.get("llm_confidence", 0.0)
            if llm_confidence >= 0.5:
                return llm_activity.replace("_", " "), f"(LLM, {llm_confidence:.0%})"

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
        # WS5: check predictive cache for pre-computed transition
        cache_hit = self._predictive_cache.match(
            flow_score=self._flow_score,
            activity=self._last_perception_data.get("production_activity", ""),
            heart_rate=self._biometrics.heart_rate_bpm,
        )

        all_signals = (
            self._fast_signals
            + self._slow_signals
            + self._perception_signals
            + self._voice_signals
            + self._phone_signals
        )

        # WS2: add stimmung signals
        stimmung_stance = "nominal"
        if self._stimmung is not None:
            all_signals = all_signals + map_stimmung(self._stimmung)
            stimmung_stance = self._stimmung.overall_stance.value

        # Phase 3: set staleness before tick so opacity computation uses it
        staleness = self._compute_staleness()
        self._sm.set_staleness(staleness)

        state = self._sm.tick(
            signals=all_signals,
            flow_score=self._flow_score,
            audio_energy=self._audio_energy,
            production_active=self._production_active,
            stimmung_stance=stimmung_stance,
        )

        # Content scheduler: intelligent text rotation + camera injection + shader nudges
        self._run_scheduler(state)

        # WS5: blend cached ambient params on prediction hit (smooth transition)
        if cache_hit is not None:
            cached = cache_hit.ambient_params
            blend = cache_hit.prediction.probability  # blend by confidence
            ap = state.ambient_params
            state.ambient_params = AmbientParams(
                speed=round(ap.speed * (1 - blend) + cached.speed * blend, 3),
                turbulence=round(ap.turbulence * (1 - blend) + cached.turbulence * blend, 3),
                color_warmth=round(ap.color_warmth * (1 - blend) + cached.color_warmth * blend, 3),
                brightness=round(ap.brightness * (1 - blend) + cached.brightness * blend, 3),
            )
            # Log cache hit rate periodically
            total = self._predictive_cache._hits + self._predictive_cache._misses
            if total > 0 and total % 20 == 0:
                log.info(
                    "Predictive cache hit rate: %.0f%% (%d/%d)",
                    self._predictive_cache.hit_rate * 100,
                    self._predictive_cache._hits,
                    total,
                )

        # Apply biometric modulation (Batch E)
        state.ambient_params = self._apply_biometric_modulation(state.ambient_params)

        # Classification consumption: environmental color from ambient sensors
        ambient_brightness = self._last_perception_data.get("ambient_brightness", 0.0)
        color_temperature = self._last_perception_data.get("color_temperature", "unknown")
        if ambient_brightness or color_temperature != "unknown":
            hue_shift = 0.0
            lightness_bias = 0.0
            source = ""
            # Warm color temperature → positive hue shift (amber)
            # Cool → negative (blue)
            _TEMP_HUE_MAP = {"warm": 15.0, "neutral": 0.0, "cool": -15.0}
            hue_shift = _TEMP_HUE_MAP.get(color_temperature, 0.0)
            if color_temperature != "unknown":
                source = color_temperature
            # Low brightness → darken, high → brighten
            if ambient_brightness:
                lightness_bias = round((ambient_brightness - 0.5) * 0.2, 3)
            state.environmental_color = EnvironmentalColor(
                hue_shift=hue_shift,
                lightness_bias=lightness_bias,
                source=source,
            )

        # Attach additional state
        state.voice_session = self._voice_session
        state.voice_content = self._voice_content
        state.biometrics = self._biometrics
        state.injected_feeds = self._injected_feeds
        state.ambient_text = self._ambient_text

        # Classification detection overlay
        state.classification_detections = self._classification_detections

        # BOCPD change points for voice pipeline (Bayesian Tier 1)
        now_ts = time.time()
        state.recent_change_points = [
            cp for cp in self._last_change_points if now_ts - cp.get("timestamp", 0) < 120.0
        ]

        # Activity label — what Hapax thinks operator is doing
        activity_label, activity_detail = self._infer_activity()
        state.activity_label = activity_label
        state.activity_detail = activity_detail

        # Phase 2+3: temporal context and staleness
        state.temporal_context = self._compute_temporal_context()
        state.signal_staleness = staleness

        # WS2: attach stimmung stance
        state.stimmung_stance = stimmung_stance

        # Track for adaptive cadence
        self._prev_display_state = state.display_state

        # WS5: precompute next states from protention predictions
        protention_snap = self._protention.predict(
            current_activity=self._last_perception_data.get("production_activity", ""),
            flow_score=self._flow_score,
            hour=datetime.now().hour,
        )
        self._predictive_cache.precompute(
            protention=protention_snap,
            current_flow=self._flow_score,
            current_audio=self._audio_energy,
            stimmung_stance=stimmung_stance,
        )

        # Telemetry: visual tick + prediction cycle
        trace_visual_tick(
            display_state=state.display_state,
            signal_count=sum(len(v) for v in state.signals.values()),
            tick_interval=self._adaptive_tick_interval(state),
            stimmung_stance=stimmung_stance,
            cache_hit=cache_hit is not None,
            scheduler_source=state.scheduler_source,
        )
        trace_prediction_tick(
            predictions=len(protention_snap.predictions),
            cache_hit=cache_hit is not None,
            cache_hit_rate=self._predictive_cache.hit_rate,
        )

        # Log stimmung → engine modulation interaction
        if stimmung_stance in ("degraded", "critical"):
            hapax_interaction(
                "stimmung",
                "visual",
                "ambient_modulation",
                metadata={"stance": stimmung_stance},
            )

        # Atomic write
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            tmp = OUTPUT_FILE.with_suffix(".tmp")
            tmp.write_text(state.model_dump_json(), encoding="utf-8")
            tmp.rename(OUTPUT_FILE)
        except OSError:
            log.debug("Failed to write visual layer state", exc_info=True)

        return state

    async def _state_tick_loop(self) -> None:
        """Fast state loop: perception → state machine → scheduler → write.

        Adaptive cadence: 0.5s during transitions, 5s when ambient-quiet.
        """
        tick_interval = STATE_TICK_BASE_S

        while True:
            # Read perception (local file, microseconds)
            self.poll_perception()

            # Compute and write
            state = self.compute_and_write()
            log.debug(
                "Tick %.1fs | %s | signals: %d | flow: %.2f | voice: %s",
                tick_interval,
                state.display_state,
                sum(len(v) for v in state.signals.values()),
                self._flow_score,
                state.voice_session.state if state.voice_session.active else "off",
            )

            # Self-band: apperception cascade
            try:
                self._tick_apperception()
            except Exception:
                log.debug("Apperception tick failed", exc_info=True)

            # Phase 5: adaptive cadence
            tick_interval = self._adaptive_tick_interval(state)
            await asyncio.sleep(tick_interval)

    async def _api_poll_loop(self) -> None:
        """Slow API loop: health/GPU at 15s, slow endpoints at 60s, ambient at 45s."""
        last_health: float = 0.0
        last_slow: float = 0.0
        last_ambient: float = 0.0

        while True:
            now = time.monotonic()

            # Adaptive stimmung poll rate: faster when stressed, normal otherwise
            stimmung_stance = self._stimmung.overall_stance.value if self._stimmung else "nominal"
            health_interval = 5.0 if stimmung_stance in ("degraded", "critical") else HEALTH_POLL_S

            if now - last_health >= health_interval:
                await self.poll_fast()
                # Feed engine status to stimmung (piggyback on health poll)
                engine = await self._fetch_json("/engine/status")
                if isinstance(engine, dict):
                    self._stimmung_collector.update_engine(
                        events_processed=int(engine.get("events_processed", 0)),
                        actions_executed=int(engine.get("actions_executed", 0)),
                        errors=int(engine.get("errors", 0)),
                        uptime_s=float(engine.get("uptime_s", 0)),
                    )
                self._update_stimmung()
                last_health = now

            if now - last_slow >= SLOW_POLL_S:
                await self.poll_slow()
                last_slow = now

            if now - last_ambient >= AMBIENT_CONTENT_INTERVAL_S:
                await self.poll_ambient_content()
                last_ambient = now

            # WS1: persist protention engine state every 5 min
            if now - self._last_protention_save >= 300.0:
                self._protention.save()
                self._last_protention_save = now

            # Sleep at the fastest sub-interval to stay responsive
            await asyncio.sleep(5.0)

    async def run(self) -> None:
        """Main entry: two concurrent loops, no locking needed (single-threaded asyncio)."""
        log.info("Visual layer aggregator starting (decoupled fast/slow loops)")
        await asyncio.gather(self._state_tick_loop(), self._api_poll_loop())

    async def close(self) -> None:
        # WS3: flush partial episode on shutdown
        if self._episode_store is not None:
            episode = self._episode_builder.flush()
            if episode is not None:
                try:
                    self._episode_store.record(episode)
                    log.info("Flushed partial episode on shutdown: %s", episode.activity)
                except Exception:
                    log.debug("Failed to flush episode on shutdown", exc_info=True)
        # WS1: save protention state
        self._protention.save()
        # Self-band: persist self-model on shutdown
        self._save_apperception_model()
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
