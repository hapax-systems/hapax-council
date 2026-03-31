"""Signal mapping functions — convert API/perception data to SignalEntry lists."""

from __future__ import annotations

import logging
import time
from datetime import datetime

from agents._stimmung import SystemStimmung
from agents.temporal_delta import compute_temporal_delta
from agents.temporal_scales import MinuteSummary
from agents.visual_layer_state import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    BiometricState,
    ClassificationDetection,
    SignalCategory,
    SignalEntry,
    SupplementaryContent,
    VoiceSessionState,
)

from .constants import (
    _ROLE_MAP,
    PERCEPTION_MINUTES_PATH,
    cam_resolution,
    can_enrich_persons,
)

log = logging.getLogger("visual_layer_aggregator")


def map_health(data: dict) -> list[SignalEntry]:
    """Map /api/health response to signals."""
    signals: list[SignalEntry] = []
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
    signals: list[SignalEntry] = []
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
    signals: list[SignalEntry] = []
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
    signals: list[SignalEntry] = []
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
    signals: list[SignalEntry] = []
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
    signals: list[SignalEntry] = []
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
    signals: list[SignalEntry] = []
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
    signals: list[SignalEntry] = []

    flow_score = data.get("flow_score", 0.0)
    audio_energy = data.get("audio_energy_rms", 0.0)
    production = data.get("production_activity", "idle")
    production_active = production not in ("idle", "")

    # Consent phase as governance signal
    consent = data.get("consent_phase", "no_guest")
    if consent not in ("no_guest", ""):
        consent_severity = {
            "guest_detected": SEVERITY_LOW,
            "consent_pending": SEVERITY_HIGH,
            "consent_refused": SEVERITY_CRITICAL,
            "consent_granted": SEVERITY_LOW,
        }
        consent_titles = {
            "guest_detected": "Guest detected -- identifying",
            "consent_pending": "Consent pending -- data curtailed",
            "consent_refused": "Consent refused -- data purged",
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

    # Desk activity from contact mic
    desk_activity = data.get("desk_activity", "")
    if desk_activity and desk_activity != "idle":
        signals.append(
            SignalEntry(
                category=SignalCategory.AMBIENT_SENSOR,
                severity=0.0,
                title=f"desk: {desk_activity}",
                source_id="contact-mic-activity",
            )
        )

    desk_energy_val = float(data.get("desk_energy", 0.0) or 0.0)
    if desk_energy_val > 0.12:
        signals.append(
            SignalEntry(
                category=SignalCategory.AMBIENT_SENSOR,
                severity=0.0,
                title=f"desk energy: {desk_energy_val:.0%}",
                source_id="contact-mic-energy",
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
        context_anchor_success=vs.get("context_anchor_success", 0.0),
        frustration_score=vs.get("frustration_score", 0.0),
        frustration_rolling_avg=vs.get("frustration_rolling_avg", 0.0),
        acceptance_type=vs.get("acceptance_type", ""),
        spoken_words=vs.get("spoken_words", 0),
        word_limit=vs.get("word_limit", 35),
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
        clamped = max(0.0, min(1.0, dim.value))
        severity = clamped
        label = name.replace("_", " ")
        trend_suffix = f" ({dim.trend})" if dim.trend != "stable" else ""
        signals.append(
            SignalEntry(
                category=SignalCategory.SYSTEM_STATE,
                severity=severity,
                title=f"{label}: {clamped:.0%}{trend_suffix}",
                source_id=f"stimmung-{name}",
            )
        )
    return signals


def _persist_minute(minute: MinuteSummary) -> None:
    """Append a MinuteSummary to the perception-minutes JSONL log."""
    try:
        PERCEPTION_MINUTES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PERCEPTION_MINUTES_PATH.open("a", encoding="utf-8") as f:
            f.write(minute.model_dump_json() + "\n")
            f.flush()
    except OSError as exc:
        log.warning("Failed to persist minute summary: %s", exc)


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

        # Compute novelty
        seen_count = obj.get("seen_count", 1)
        count_novelty = max(0.0, 1.0 - (seen_count - 1) / 20.0)
        first_seen_age_s = obj.get("first_seen_age_s") or 0.0
        recency_novelty = min(1.0, 5.0 / max(float(first_seen_age_s), 0.1))
        mob_score = obj.get("mobility_score")
        mobility_novelty = float(mob_score) if mob_score is not None else 0.0
        novelty = max(
            0.0,
            min(1.0, 0.5 * count_novelty + 0.3 * recency_novelty + 0.2 * mobility_novelty),
        )

        # Normalize bounding box to 0-1 coordinates
        box_raw = obj.get("box", obj.get("last_box"))
        if box_raw and len(box_raw) == 4:
            res_w, res_h = cam_resolution(camera_raw)
            x1 = max(0.0, min(1.0, box_raw[0] / res_w))
            y1 = max(0.0, min(1.0, box_raw[1] / res_h))
            x2 = max(0.0, min(1.0, box_raw[2] / res_w))
            y2 = max(0.0, min(1.0, box_raw[3] / res_h))
            box = (x1, y1, x2, y2)
        else:
            continue

        is_person = label == "person"
        if is_person and remove_person_detections and camera_raw != "operator":
            continue

        consent_suppressed = suppress_person_enrichments and is_person
        is_enrichment_cam = can_enrich_persons(camera_raw)

        enrichment_kwargs: dict[str, object] = {}
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

        mobility_score_raw = obj.get("mobility_score")
        first_seen_age_raw = obj.get("first_seen_age_s")
        camera_count_raw = obj.get("camera_count")

        raw_sightings_norm = obj.get("sightings")
        norm_sightings: list[tuple[float, float, float, float]] | None = None
        if raw_sightings_norm and isinstance(raw_sightings_norm, list):
            norm_sightings = []
            for sb in raw_sightings_norm[-5:]:
                if isinstance(sb, (list, tuple)) and len(sb) == 4:
                    norm_sightings.append((float(sb[0]), float(sb[1]), float(sb[2]), float(sb[3])))

        # Temporal delta
        temporal_kwargs: dict[str, object] = {}
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
                camera=camera_raw,
            )
            last_seen_age = obj.get("last_seen_age_s", 0.0)
            seen_count_td = obj.get("seen_count", 0)
            temporal_kwargs = {
                "velocity": delta.velocity,
                "direction_deg": delta.direction_deg,
                "confidence_stability": delta.confidence_stability,
                "dwell_s": delta.dwell_s,
                "is_entering": seen_count_td <= 3 and last_seen_age < 5.0,
                "is_exiting": last_seen_age > 20.0,
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

    if data.get("phone_media_playing"):
        title = data.get("phone_media_title", "")
        artist = data.get("phone_media_artist", "")
        if title:
            media_text = f"{title} -- {artist}" if artist else title
            signals.append(
                SignalEntry(
                    category=SignalCategory.AMBIENT_SENSOR,
                    severity=SEVERITY_LOW,
                    title="Now playing",
                    detail=media_text[:60],
                    source_id="phone_media",
                )
            )

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


def time_of_day_warmth_offset() -> float:
    """Return a warmth offset based on time of day (always warm spectrum)."""
    hour = datetime.now().hour
    if hour < 6:
        return 0.7
    elif hour < 9:
        return 0.4
    elif hour < 12:
        return 0.2
    elif hour < 17:
        return 0.25
    elif hour < 21:
        return 0.5
    else:
        return 0.65
