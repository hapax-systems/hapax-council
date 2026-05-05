"""Producer adapters: existing perception outputs → CameraObservationEnvelope.

Phase A of cc-task ``bayesian-camera-salience-broker-production-wiring``.

Four pure-function adapters that transform runtime perception state into
typed envelopes the :class:`CameraSalienceBroker` accepts. Each adapter:

- Takes an existing producer's snapshot dict (the same dict the producer
  already writes to shm or hands to ``contribute()``)
- Returns a valid ``CameraObservationEnvelope`` or ``None`` (fail-closed)
- Never imports the producer module itself — works on the dict contract
- Catches all exceptions internally and returns ``None`` on failure

These adapters are the seam between the existing perception backends and
the broker. Phase B will wire them into the production tick paths.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from shared.bayesian_camera_salience_world_surface import (
    CameraEvidenceRow,
    CameraFreshness,
    CameraObservationEnvelope,
    CameraTemporalWindow,
    ClaimAuthorityCeiling,
    EvidenceClass,
    FreshnessState,
    ObservationApertureKind,
    ObservationState,
    PrivacyMode,
    ProducerKind,
)

log = logging.getLogger(__name__)

# Runtime camera-role → canonical aperture mapping. Extended to cover the
# full studio camera fleet (cc-task: bayesian-camera-salience-runtime-aperture-coverage).
# Per CLAUDE.md the live RGB cameras are: brio-operator (desk-co-located,
# Pi-1), c920-desk (Pi-1), c920-room (Pi-2), c920-overhead (Pi-6); the live
# IR Pis are noir-desk (Pi-1), noir-room (Pi-2), noir-overhead (Pi-6).
# Each role string a producer might emit resolves to one of the canonical
# apertures declared in
# ``config/bayesian-camera-salience-world-surface-fixtures.json`` so no
# adapter ever returns ``None`` for a known live camera (and the broker's
# ``unspecified`` fail-closed slot is reserved for genuinely unknown
# producer output).
_VISION_ROLE_TO_APERTURE_ID = {
    "operator": "aperture:studio-rgb.brio-operator",
    "brio-operator": "aperture:studio-rgb.brio-operator",
    "desk": "aperture:studio-rgb.c920-desk",
    "c920-desk": "aperture:studio-rgb.c920-desk",
    "room": "aperture:studio-rgb.c920-room",
    "c920-room": "aperture:studio-rgb.c920-room",
    "overhead": "aperture:studio-rgb.c920-overhead",
    "c920-overhead": "aperture:studio-rgb.c920-overhead",
}

_VISION_ROLE_TO_CANONICAL_SOURCE = {
    "operator": "brio-operator",
    "brio-operator": "brio-operator",
    "desk": "c920-desk",
    "c920-desk": "c920-desk",
    "room": "c920-room",
    "c920-room": "c920-room",
    "overhead": "c920-overhead",
    "c920-overhead": "c920-overhead",
}

_IR_ROLE_TO_APERTURE_ID = {
    "desk": "aperture:studio-ir.noir-desk",
    "noir-desk": "aperture:studio-ir.noir-desk",
    "pi-noir-desk": "aperture:studio-ir.noir-desk",
    "room": "aperture:studio-ir.noir-room",
    "noir-room": "aperture:studio-ir.noir-room",
    "pi-noir-room": "aperture:studio-ir.noir-room",
    "overhead": "aperture:studio-ir.noir-overhead",
    "noir-overhead": "aperture:studio-ir.noir-overhead",
    "pi-noir-overhead": "aperture:studio-ir.noir-overhead",
}

_IR_ROLE_TO_CANONICAL_SOURCE = {
    "desk": "pi-noir-desk",
    "noir-desk": "pi-noir-desk",
    "pi-noir-desk": "pi-noir-desk",
    "room": "pi-noir-room",
    "noir-room": "pi-noir-room",
    "pi-noir-room": "pi-noir-room",
    "overhead": "pi-noir-overhead",
    "noir-overhead": "pi-noir-overhead",
    "pi-noir-overhead": "pi-noir-overhead",
}


def _normalize_role(role: object) -> str:
    return str(role or "").strip().lower()


def _vision_aperture_id(camera_role: object, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    return _VISION_ROLE_TO_APERTURE_ID.get(_normalize_role(camera_role))


def _canonical_vision_source(camera_role: object) -> str | None:
    return _VISION_ROLE_TO_CANONICAL_SOURCE.get(_normalize_role(camera_role))


def _ir_aperture_id(pi_name: object, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    return _IR_ROLE_TO_APERTURE_ID.get(_normalize_role(pi_name))


def _canonical_ir_source(pi_name: object) -> str | None:
    return _IR_ROLE_TO_CANONICAL_SOURCE.get(_normalize_role(pi_name))


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _freshness(
    *,
    age_s: float,
    ttl_s: int,
    source_ref: str,
) -> CameraFreshness:
    """Build a freshness record. Stale if age exceeds TTL."""
    if age_s <= ttl_s:
        return CameraFreshness(
            state=FreshnessState.FRESH,
            checked_at=_now_iso(),
            ttl_s=ttl_s,
            observed_age_s=int(age_s),
            source_ref=source_ref,
        )
    return CameraFreshness(
        state=FreshnessState.STALE,
        checked_at=_now_iso(),
        ttl_s=ttl_s,
        observed_age_s=int(age_s),
        source_ref=source_ref,
    )


# ── Vision backend adapter ─────────────────────────────────────────────


def vision_to_envelope(
    snapshot: dict[str, Any],
    *,
    camera_role: str,
    aperture_id: str | None = None,
    ttl_s: int = 10,
) -> CameraObservationEnvelope | None:
    """Transform a VisionBackend cache snapshot into a typed envelope.

    ``snapshot`` is the dict returned by ``_VisionCache.read()`` or the
    per-camera behavior dict from ``_per_camera_behaviors[role]``.
    ``camera_role`` is the camera name (e.g., ``"brio-operator"``).

    Returns ``None`` on any validation or data error (fail-closed).
    """
    try:
        now_str = _now_iso()
        aid = _vision_aperture_id(camera_role, aperture_id)
        canonical_role = _canonical_vision_source(camera_role) or _normalize_role(camera_role)
        if aid is None:
            return None
        source_ref = f"vision-backend:camera-classifications:{canonical_role}"

        updated_at = snapshot.get("updated_at") or snapshot.get("ts", 0.0)
        age_s = time.monotonic() - float(updated_at) if updated_at else 0.0
        age_s = max(0.0, age_s)

        person_count = int(snapshot.get("person_count", 0))
        gaze = str(snapshot.get("gaze_direction", "unknown"))
        action = str(snapshot.get("detected_action", "unknown"))
        scene_objects = str(snapshot.get("scene_objects", ""))

        # Build hypothesis from the dominant signal
        if person_count > 0 and gaze == "screen":
            hypothesis = "operator_attention_screen"
        elif person_count > 0:
            hypothesis = "operator_attention_desk"
        else:
            hypothesis = "operator_absent"

        semantic_labels = []
        if person_count > 0:
            semantic_labels.append("person_present")
        if action and action != "unknown":
            semantic_labels.append(action)
        if scene_objects:
            for obj in scene_objects.split(",")[:3]:
                obj = obj.strip()
                if obj:
                    semantic_labels.append(obj)

        confidence = 0.5
        if person_count > 0 and gaze != "unknown":
            confidence = 0.82
        elif person_count > 0:
            confidence = 0.65

        likelihood = min(0.999, max(0.001, confidence * 0.95))

        freshness = _freshness(age_s=age_s, ttl_s=ttl_s, source_ref=source_ref)

        # Determine observation state
        if freshness.state == FreshnessState.STALE:
            obs_state = ObservationState.STALE
            blocked_reasons = ("stale_evidence",)
            stale_refs = (f"{source_ref}:stale",)
        else:
            obs_state = ObservationState.OBSERVED
            blocked_reasons = ()
            stale_refs = ()

        evidence_row = CameraEvidenceRow(
            evidence_ref=f"camera-evidence:frame.{canonical_role}.{hypothesis}",
            evidence_class=EvidenceClass.FRAME,
            hypothesis=hypothesis,
            likelihood=likelihood,
            confidence=confidence,
            observation_state=obs_state,
            supports_hypothesis=True,
            source_refs=(source_ref,),
            witness_refs=(f"witness:vision-backend:{canonical_role}:frame",),
            span_refs=(f"span:frame:{canonical_role}:{now_str}",),
            wcs_refs=(f"wcs-surface:camera.{canonical_role}",),
            metadata={
                "semantic_role": canonical_role,
                "source_camera_role": str(camera_role),
            },
        )

        window = CameraTemporalWindow(
            window_id=f"camera-window:vision.{canonical_role}.frame",
            kind="current_frame",
            aperture_id=aid,
            observed_at=now_str,
            duration_s=0.0,
            span_ref=f"span:frame:{canonical_role}:{now_str}",
        )

        return CameraObservationEnvelope(
            envelope_id=f"camera-observation:vision.{canonical_role}.frame",
            aperture_id=aid,
            aperture_kind=ObservationApertureKind.STUDIO_RGB_CAMERA,
            producer=ProducerKind.VISION_BACKEND,
            evidence_class=EvidenceClass.FRAME,
            observation_state=obs_state,
            temporal_window=window,
            freshness=freshness,
            confidence=confidence,
            semantic_labels=tuple(semantic_labels),
            evidence_rows=(evidence_row,),
            source_refs=(source_ref,),
            wcs_surface_refs=(f"wcs-surface:camera.{canonical_role}",),
            witness_refs=(f"witness:vision-backend:{canonical_role}:frame",),
            span_refs=(f"span:frame:{canonical_role}:{now_str}",),
            authority_ceiling=ClaimAuthorityCeiling.EVIDENCE_BOUND,
            privacy_mode=PrivacyMode.PRIVATE,
            image_ref=f"image-ref:{canonical_role}-frame",
            blocked_reasons=blocked_reasons,
            stale_refs=stale_refs,
        )
    except (ValidationError, KeyError, TypeError, ValueError):
        log.debug("vision_to_envelope failed for %s", camera_role, exc_info=True)
        return None


# ── IR presence adapter ─────────────────────────────────────────────────


def ir_to_envelope(
    ir_state: dict[str, Any],
    *,
    pi_name: str = "desk",
    aperture_id: str | None = None,
    ttl_s: int = 15,
) -> CameraObservationEnvelope | None:
    """Transform a Pi NoIR IR presence state dict into a typed envelope.

    ``ir_state`` is the dict from ``read_all_ir_reports()`` for a single Pi,
    or a fused dict from the IR presence backend.
    ``pi_name`` is the Pi identifier (e.g., ``"desk"``, ``"room"``).

    Returns ``None`` on failure (fail-closed).
    """
    try:
        now_str = _now_iso()
        aid = _ir_aperture_id(pi_name, aperture_id)
        canonical_source = _canonical_ir_source(pi_name) or _normalize_role(pi_name)
        if aid is None:
            return None
        canonical_surface = canonical_source.removeprefix("pi-")
        source_ref = f"ir-presence-backend:{canonical_source}"

        # IR reports typically have a timestamp field
        report_ts = ir_state.get("timestamp") or ir_state.get("ts", 0.0)
        if isinstance(report_ts, str):
            age_s = 5.0  # assume reasonably fresh for string timestamps
        else:
            age_s = max(0.0, time.time() - float(report_ts)) if report_ts else 0.0

        persons = ir_state.get("persons", [])
        person_detected = bool(ir_state.get("person_detected", False)) or bool(persons)
        motion_delta = float(ir_state.get("motion_delta", 0.0))
        brightness = float(ir_state.get("brightness", ir_state.get("ir_brightness", 0.0)))

        if person_detected:
            hypothesis = "operator_present_ir"
            confidence = 0.75
        elif motion_delta > 0.1:
            hypothesis = "motion_detected_ir"
            confidence = 0.55
        else:
            hypothesis = "operator_absent_ir"
            confidence = 0.80

        likelihood = min(0.999, max(0.001, confidence * 0.90))
        freshness = _freshness(age_s=age_s, ttl_s=ttl_s, source_ref=source_ref)

        if freshness.state == FreshnessState.STALE:
            obs_state = ObservationState.STALE
            blocked_reasons = ("stale_evidence",)
            stale_refs = (f"{source_ref}:stale",)
        else:
            obs_state = ObservationState.OBSERVED
            blocked_reasons = ()
            stale_refs = ()

        evidence_row = CameraEvidenceRow(
            evidence_ref=f"camera-evidence:ir-presence.{canonical_surface}.{hypothesis}",
            evidence_class=EvidenceClass.IR_PRESENCE,
            hypothesis=hypothesis,
            likelihood=likelihood,
            confidence=confidence,
            observation_state=obs_state,
            supports_hypothesis=True,
            source_refs=(source_ref,),
            witness_refs=(f"witness:ir-backend:{canonical_source}:presence",),
            span_refs=(f"span:ir:{canonical_surface}:{now_str}",),
            wcs_refs=(f"wcs-surface:ir.{canonical_surface}",),
            metadata={
                "motion_delta": motion_delta,
                "brightness": brightness,
                "person_detected": person_detected,
                "source_pi_name": str(pi_name),
            },
        )

        window = CameraTemporalWindow(
            window_id=f"camera-window:ir.{canonical_surface}.presence",
            kind="current_frame",
            aperture_id=aid,
            observed_at=now_str,
            duration_s=0.0,
            span_ref=f"span:ir:{canonical_surface}:{now_str}",
        )

        return CameraObservationEnvelope(
            envelope_id=f"camera-observation:ir.{canonical_surface}.presence",
            aperture_id=aid,
            aperture_kind=ObservationApertureKind.STUDIO_IR_CAMERA,
            producer=ProducerKind.IR_PRESENCE_BACKEND,
            evidence_class=EvidenceClass.IR_PRESENCE,
            observation_state=obs_state,
            temporal_window=window,
            freshness=freshness,
            confidence=confidence,
            semantic_labels=("ir_presence", hypothesis),
            evidence_rows=(evidence_row,),
            source_refs=(source_ref,),
            wcs_surface_refs=(f"wcs-surface:ir.{canonical_surface}",),
            witness_refs=(f"witness:ir-backend:{canonical_source}:presence",),
            span_refs=(f"span:ir:{canonical_surface}:{now_str}",),
            authority_ceiling=ClaimAuthorityCeiling.INTERNAL_ONLY,
            privacy_mode=PrivacyMode.PRIVATE,
            blocked_reasons=blocked_reasons,
            stale_refs=stale_refs,
        )
    except (ValidationError, KeyError, TypeError, ValueError):
        log.debug("ir_to_envelope failed for %s", pi_name, exc_info=True)
        return None


# ── Cross-camera tracklet adapter ───────────────────────────────────────


def cross_camera_to_envelope(
    tracklet: dict[str, Any],
    *,
    aperture_id: str | None = None,
    ttl_s: int = 30,
) -> CameraObservationEnvelope | None:
    """Transform a cross-camera tracklet into a typed envelope.

    ``tracklet`` is the dict emitted by ``agents.models.cross_camera``
    after stitching detections across cameras. Expected keys:
    ``track_id``, ``cameras``, ``similarity``, ``time_delta_s``,
    ``confidence``, ``topology_path``.

    Returns ``None`` on failure (fail-closed).
    """
    try:
        now_str = _now_iso()
        track_id = str(tracklet.get("track_id", "unknown"))
        raw_cameras = tracklet.get("cameras", [])
        if isinstance(raw_cameras, str):
            cameras = [raw_cameras]
        else:
            cameras = [str(camera) for camera in raw_cameras]
        similarity = float(tracklet.get("similarity", 0.5))
        time_delta_s = float(tracklet.get("time_delta_s", 0.0))
        confidence = float(tracklet.get("confidence", 0.5))
        topology_path = str(tracklet.get("topology_path", "unknown"))

        primary_role = next(
            (
                canonical
                for canonical in (_canonical_vision_source(camera) for camera in cameras)
                if canonical is not None
            ),
            None,
        )
        aid = aperture_id or (
            _VISION_ROLE_TO_APERTURE_ID[primary_role] if primary_role is not None else None
        )
        if aid is None:
            return None
        source_ref = f"cross-camera-stitcher:tracklet:{track_id}"

        hypothesis = f"cross_camera_movement_{track_id}"
        likelihood = min(0.999, max(0.001, similarity * 0.95))
        uncertainty = max(0.0, min(1.0, 1.0 - similarity))

        freshness = CameraFreshness(
            state=FreshnessState.FRESH,
            checked_at=now_str,
            ttl_s=ttl_s,
            observed_age_s=0,
            source_ref=source_ref,
        )

        evidence_row = CameraEvidenceRow(
            evidence_ref=f"camera-evidence:tracklet.{track_id}",
            evidence_class=EvidenceClass.CROSS_CAMERA_TRACKLET,
            hypothesis=hypothesis,
            likelihood=likelihood,
            confidence=confidence,
            observation_state=ObservationState.OBSERVED,
            supports_hypothesis=True,
            source_refs=(source_ref,),
            witness_refs=tuple(f"witness:camera:{c}" for c in cameras[:3]) or ("witness:stitcher",),
            span_refs=(f"span:tracklet:{track_id}:{now_str}",),
            wcs_refs=(
                f"wcs-surface:camera.{primary_role}"
                if primary_role is not None
                else "wcs-surface:cross-camera.stitcher",
            ),
            metadata={
                "topology_path": topology_path,
                "time_delta_s": time_delta_s,
                "similarity": similarity,
                "uncertainty": uncertainty,
                "cameras": ",".join(cameras),
            },
        )

        window = CameraTemporalWindow(
            window_id=f"camera-window:tracklet.{track_id}",
            kind="cross_camera_delta",
            aperture_id=aid,
            observed_at=now_str,
            duration_s=time_delta_s,
            span_ref=f"span:tracklet:{track_id}:{now_str}",
        )

        return CameraObservationEnvelope(
            envelope_id=f"camera-observation:tracklet.{track_id}",
            aperture_id=aid,
            aperture_kind=ObservationApertureKind.STUDIO_RGB_CAMERA,
            producer=ProducerKind.CROSS_CAMERA_STITCHER,
            evidence_class=EvidenceClass.CROSS_CAMERA_TRACKLET,
            observation_state=ObservationState.OBSERVED,
            temporal_window=window,
            freshness=freshness,
            confidence=confidence,
            semantic_labels=("cross_camera_tracklet",),
            evidence_rows=(evidence_row,),
            source_refs=(source_ref,),
            wcs_surface_refs=(
                (
                    f"wcs-surface:camera.{primary_role}",
                    "wcs-surface:cross-camera.stitcher",
                )
                if primary_role is not None
                else ("wcs-surface:cross-camera.stitcher",)
            ),
            witness_refs=tuple(f"witness:camera:{c}" for c in cameras[:3]) or ("witness:stitcher",),
            span_refs=(f"span:tracklet:{track_id}:{now_str}",),
            authority_ceiling=ClaimAuthorityCeiling.INTERNAL_ONLY,
            privacy_mode=PrivacyMode.PRIVATE,
        )
    except (ValidationError, KeyError, TypeError, ValueError):
        log.debug("cross_camera_to_envelope failed", exc_info=True)
        return None


# ── Livestream compositor frame adapter ─────────────────────────────────


def livestream_to_envelope(
    compositor_state: dict[str, Any],
    *,
    aperture_id: str | None = None,
    ttl_s: int = 5,
) -> CameraObservationEnvelope | None:
    """Transform a compositor frame/state snapshot into a typed envelope.

    ``compositor_state`` is the dict from the studio compositor's
    per-tick snapshot (active scene, camera positions, OBS state).
    Expected keys: ``active_camera``, ``scene_name``, ``frame_ts``,
    ``confidence``.

    Returns ``None`` on failure (fail-closed).
    """
    try:
        now_str = _now_iso()
        aid = aperture_id or "aperture:livestream.composed-frame"
        source_ref = "compositor:livestream-composed-frame"

        frame_ts = compositor_state.get("frame_ts") or compositor_state.get("ts", 0.0)
        if isinstance(frame_ts, (int, float)) and frame_ts > 0:
            age_s = max(0.0, time.time() - frame_ts)
        else:
            age_s = 0.0

        active_camera = str(compositor_state.get("active_camera", "unknown"))
        scene_name = str(compositor_state.get("scene_name", "unknown"))
        confidence = float(compositor_state.get("confidence", 0.6))

        hypothesis = f"livestream_scene_{scene_name}"
        likelihood = min(0.999, max(0.001, confidence * 0.90))

        freshness = _freshness(age_s=age_s, ttl_s=ttl_s, source_ref=source_ref)

        if freshness.state == FreshnessState.STALE:
            obs_state = ObservationState.STALE
            blocked_reasons = ("stale_evidence",)
            stale_refs = (f"{source_ref}:stale",)
        else:
            obs_state = ObservationState.OBSERVED
            blocked_reasons = ()
            stale_refs = ()

        evidence_row = CameraEvidenceRow(
            evidence_ref=f"camera-evidence:livestream.{scene_name}",
            evidence_class=EvidenceClass.COMPOSED_LIVESTREAM,
            hypothesis=hypothesis,
            likelihood=likelihood,
            confidence=confidence,
            observation_state=obs_state,
            supports_hypothesis=True,
            source_refs=(source_ref,),
            witness_refs=(f"witness:compositor:{scene_name}",),
            span_refs=(f"span:livestream:{scene_name}:{now_str}",),
            wcs_refs=("wcs-surface:livestream.composed-frame",),
            metadata={
                "active_camera": active_camera,
                "scene_name": scene_name,
            },
        )

        window = CameraTemporalWindow(
            window_id=f"camera-window:livestream.{scene_name}",
            kind="current_frame",
            aperture_id=aid,
            observed_at=now_str,
            duration_s=0.0,
            span_ref=f"span:livestream:{scene_name}:{now_str}",
        )

        return CameraObservationEnvelope(
            envelope_id=f"camera-observation:livestream.{scene_name}",
            aperture_id=aid,
            aperture_kind=ObservationApertureKind.LIVESTREAM_COMPOSED_FRAME,
            producer=ProducerKind.COMPOSITOR_SNAPSHOT,
            evidence_class=EvidenceClass.COMPOSED_LIVESTREAM,
            observation_state=obs_state,
            temporal_window=window,
            freshness=freshness,
            confidence=confidence,
            semantic_labels=("livestream", scene_name),
            evidence_rows=(evidence_row,),
            source_refs=(source_ref,),
            wcs_surface_refs=("wcs-surface:livestream.composed-frame",),
            witness_refs=(f"witness:compositor:{scene_name}",),
            span_refs=(f"span:livestream:{scene_name}:{now_str}",),
            authority_ceiling=ClaimAuthorityCeiling.EVIDENCE_BOUND,
            privacy_mode=PrivacyMode.PUBLIC_SAFE,
            blocked_reasons=blocked_reasons,
            stale_refs=stale_refs,
        )
    except (ValidationError, KeyError, TypeError, ValueError):
        log.debug("livestream_to_envelope failed", exc_info=True)
        return None


__all__ = [
    "cross_camera_to_envelope",
    "ir_to_envelope",
    "livestream_to_envelope",
    "vision_to_envelope",
]
