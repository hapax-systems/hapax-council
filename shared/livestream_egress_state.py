"""Fail-closed livestream egress state resolver.

This module is intentionally evidence-oriented. A public live claim is only
allowed when the local capture path, privacy floor, audio floor, RTMP relay,
YouTube-facing ingest proof, active video id, and metadata evidence agree.
Absent evidence is a blocker, not a default-live boolean.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.broadcast_audio_health import DEFAULT_STATE_PATH, read_broadcast_audio_health_state
from shared.content_source_provenance_egress import (
    DEFAULT_BROADCAST_MANIFEST_PATH,
    DEFAULT_KILL_SWITCH_PATH,
    BroadcastProvenanceManifest,
    EgressKillSwitchState,
    EgressManifestGate,
    EgressOffender,
    read_broadcast_manifest,
    read_egress_kill_switch_state,
)
from shared.face_obscure_policy import FaceObscurePolicy, resolve_policy
from shared.stream_mode import StreamMode
from shared.working_mode import WorkingMode


class EvidenceStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"


class FloorState(StrEnum):
    SATISFIED = "satisfied"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class EgressState(StrEnum):
    OFFLINE = "offline"
    LOCAL_PREVIEW = "local_preview"
    RESEARCH_CAPTURE_READY = "research_capture_ready"
    PUBLIC_BLOCKED = "public_blocked"
    PUBLIC_READY = "public_ready"
    PUBLIC_LIVE = "public_live"


class LivestreamEgressEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    status: EvidenceStatus
    summary: str
    observed: dict[str, Any] = Field(default_factory=dict)
    age_s: float | None = None
    stale: bool = False
    timestamp: str | None = None


class LivestreamEgressState(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: EgressState
    confidence: float
    public_claim_allowed: bool
    public_ready: bool
    research_capture_ready: bool
    monetization_risk: str
    privacy_floor: FloorState
    audio_floor: FloorState
    evidence: list[LivestreamEgressEvidence]
    public_claim_blockers: list[str] = Field(default_factory=list)
    last_transition: str | None
    operator_action: str


@dataclass(frozen=True)
class LivestreamEgressPaths:
    compositor_status: Path = Path.home() / ".cache" / "hapax-compositor" / "status.json"
    compositor_snapshot: Path = Path("/dev/shm/hapax-compositor/snapshot.jpg")
    hls_playlist: Path = Path.home() / ".cache" / "hapax-compositor" / "hls" / "stream.m3u8"
    hls_archive_root: Path = Path.home() / "hapax-state" / "stream-archive" / "hls"
    livestream_status: Path = Path("/dev/shm/hapax-compositor/livestream-status.json")
    youtube_video_id: Path = Path("/dev/shm/hapax-compositor/youtube-video-id.txt")
    youtube_ingest_proof: Path = Path("/dev/shm/hapax-broadcast/youtube-ingest.json")
    broadcast_events: Path = Path("/dev/shm/hapax-broadcast/events.jsonl")
    stream_mode: Path = Path.home() / ".cache" / "hapax" / "stream-mode"
    working_mode: Path = Path.home() / ".cache" / "hapax" / "working-mode"
    broadcast_audio_health: Path = DEFAULT_STATE_PATH
    broadcast_manifest: Path = DEFAULT_BROADCAST_MANIFEST_PATH
    egress_kill_switch: Path = DEFAULT_KILL_SWITCH_PATH
    consent_state: Path = Path("/dev/shm/hapax-compositor/consent-state.txt")
    perception_state: Path = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
    monetization_flagged_root: Path = Path.home() / "hapax-state" / "monetization-flagged"


@dataclass(frozen=True)
class LivestreamEgressThresholds:
    compositor_status_max_age_s: float = 20.0
    local_preview_max_age_s: float = 10.0
    hls_playlist_max_age_s: float = 15.0
    hls_archive_max_age_s: float = 300.0
    perception_max_age_s: float = 15.0
    min_audio_energy_rms: float = 0.0001
    audio_health_max_age_s: float = 30.0
    broadcast_manifest_max_age_s: float = 15.0
    egress_kill_switch_max_age_s: float = 15.0
    youtube_ingest_proof_max_age_s: float = 90.0
    broadcast_event_max_age_s: float = 12 * 3600.0
    monetization_window_s: float = 24 * 3600.0


HttpProbe = Callable[[str, float], int | None]

MEDIAMTX_HLS_URL = "http://127.0.0.1:8888/studio/index.m3u8"
_EGRESS_PROVENANCE_RECOVERY = (
    "replace or remove the blocked source, verify provenance/rights, then wait for a fresh "
    "broadcast manifest and inactive kill-switch"
)


@dataclass(frozen=True)
class _EgressProvenanceDecision:
    public_claim_allowed: bool
    status: EvidenceStatus
    summary: str
    reason_codes: tuple[str, ...]
    observed: dict[str, Any]
    age_s: float | None
    stale: bool
    monetization_risk: str
    kill_switch_fired_observed: dict[str, Any] | None = None


def resolve_livestream_egress_state(
    *,
    paths: LivestreamEgressPaths | None = None,
    thresholds: LivestreamEgressThresholds | None = None,
    now: float | None = None,
    http_probe: HttpProbe | None = None,
    probe_network: bool = True,
    env: Mapping[str, str] | None = None,
) -> LivestreamEgressState:
    """Resolve the current livestream egress state from local evidence."""

    p = paths or LivestreamEgressPaths()
    t = thresholds or LivestreamEgressThresholds()
    current = now if now is not None else time.time()
    probe = http_probe or _http_status
    evidence: list[LivestreamEgressEvidence] = []

    status_data, status_age, status_err = _read_json_file(p.compositor_status, current)
    status_running = (
        isinstance(status_data, dict)
        and status_data.get("state") == "running"
        and status_age is not None
        and status_age <= t.compositor_status_max_age_s
    )
    _append(
        evidence,
        "compositor",
        EvidenceStatus.PASS if status_running else EvidenceStatus.FAIL,
        "studio compositor status is fresh and running"
        if status_running
        else f"compositor status unavailable/stale ({status_err or 'not running'})",
        observed={
            "state": status_data.get("state") if isinstance(status_data, dict) else None,
            "active_cameras": status_data.get("active_cameras")
            if isinstance(status_data, dict)
            else None,
        },
        age_s=status_age,
        stale=not status_running,
    )

    local_preview = _path_fresh(p.compositor_snapshot, current, t.local_preview_max_age_s)
    _append(
        evidence,
        "local_preview",
        EvidenceStatus.PASS if local_preview else EvidenceStatus.FAIL,
        "composited preview snapshot is fresh"
        if local_preview
        else "local preview is missing/stale",
        age_s=_path_age_s(p.compositor_snapshot, current),
        stale=not local_preview,
    )

    hls_playlist = _path_fresh(p.hls_playlist, current, t.hls_playlist_max_age_s)
    hls_config_enabled = (
        bool(status_data.get("hls_enabled")) if isinstance(status_data, dict) else False
    )
    hls_ready = hls_playlist and hls_config_enabled
    _append(
        evidence,
        "hls_playlist",
        EvidenceStatus.PASS if hls_ready else EvidenceStatus.FAIL,
        "local HLS playlist is fresh"
        if hls_ready
        else "local HLS playlist is missing/stale or compositor HLS disabled",
        observed={"hls_enabled": hls_config_enabled},
        age_s=_path_age_s(p.hls_playlist, current),
        stale=not hls_ready,
    )

    archive_age = _latest_archive_age_s(p.hls_archive_root, current)
    archive_ok = archive_age is not None and archive_age <= t.hls_archive_max_age_s
    _append(
        evidence,
        "hls_archive",
        EvidenceStatus.PASS if archive_ok else EvidenceStatus.WARN,
        "HLS archive sidecars are rotating"
        if archive_ok
        else "no recent HLS archive sidecar found",
        age_s=archive_age,
        stale=not archive_ok,
    )

    rtmp_attached = (
        bool(status_data.get("rtmp_attached")) if isinstance(status_data, dict) else False
    )
    rtmp_known = isinstance(status_data, dict) and "rtmp_attached" in status_data
    _append(
        evidence,
        "rtmp_output",
        EvidenceStatus.PASS
        if rtmp_attached
        else EvidenceStatus.FAIL
        if rtmp_known
        else EvidenceStatus.UNKNOWN,
        "RTMP output bin is attached"
        if rtmp_attached
        else "RTMP output bin is detached or not reported",
        observed={
            "rtmp_attached": rtmp_attached if rtmp_known else None,
            "rtmp_rebuild_count": status_data.get("rtmp_rebuild_count")
            if isinstance(status_data, dict)
            else None,
        },
    )

    mediamtx_ok = False
    mediamtx_status: int | None = None
    if probe_network:
        mediamtx_status = probe(MEDIAMTX_HLS_URL, 0.35)
        mediamtx_ok = mediamtx_status == 200
    _append(
        evidence,
        "mediamtx_hls",
        EvidenceStatus.PASS
        if mediamtx_ok
        else EvidenceStatus.FAIL
        if probe_network
        else EvidenceStatus.UNKNOWN,
        "MediaMTX is serving the studio HLS path"
        if mediamtx_ok
        else "MediaMTX studio HLS path is unavailable",
        observed={"url": MEDIAMTX_HLS_URL, "http_status": mediamtx_status},
    )

    mode, mode_age = _read_enum_file(p.stream_mode, StreamMode, current)
    stream_public = mode in (StreamMode.PUBLIC, StreamMode.PUBLIC_RESEARCH)
    _append(
        evidence,
        "stream_mode",
        EvidenceStatus.PASS if stream_public else EvidenceStatus.FAIL,
        f"stream mode permits public egress ({mode.value})"
        if stream_public and mode is not None
        else "stream mode is not public/public_research",
        observed={"mode": mode.value if mode is not None else None},
        age_s=mode_age,
        stale=mode is None,
    )

    working_mode, working_mode_age = _read_enum_file(p.working_mode, WorkingMode, current)
    working_fortress = working_mode is WorkingMode.FORTRESS
    _append(
        evidence,
        "working_mode",
        EvidenceStatus.PASS if working_fortress else EvidenceStatus.FAIL,
        "working mode is fortress"
        if working_fortress
        else "working mode is not fortress; public live claim remains blocked",
        observed={"mode": working_mode.value if working_mode is not None else None},
        age_s=working_mode_age,
        stale=working_mode is None,
    )

    privacy_floor = _resolve_privacy_floor(
        status_data=status_data if isinstance(status_data, dict) else {},
        consent_state_path=p.consent_state,
        env=env,
    )
    _append(
        evidence,
        "privacy_floor",
        EvidenceStatus.PASS if privacy_floor is FloorState.SATISFIED else EvidenceStatus.FAIL,
        "face-obscure/privacy floor is satisfied"
        if privacy_floor is FloorState.SATISFIED
        else "face-obscure/privacy floor is blocked or unknown",
        observed={
            "consent_recording_allowed": status_data.get("consent_recording_allowed")
            if isinstance(status_data, dict)
            else None,
            "guest_present": status_data.get("guest_present")
            if isinstance(status_data, dict)
            else None,
            "consent_phase": status_data.get("consent_phase")
            if isinstance(status_data, dict)
            else None,
        },
    )

    audio_health = read_broadcast_audio_health_state(
        p.broadcast_audio_health,
        now=current,
        max_age_s=t.audio_health_max_age_s,
    )
    audio_floor = FloorState.SATISFIED if audio_health.safe else FloorState.BLOCKED
    _append(
        evidence,
        "audio_floor",
        EvidenceStatus.PASS if audio_floor is FloorState.SATISFIED else EvidenceStatus.FAIL,
        "audio_safe_for_broadcast is true"
        if audio_floor is FloorState.SATISFIED
        else "audio_safe_for_broadcast is false, missing, stale, or malformed",
        observed={
            "audio_safe_for_broadcast": audio_health.model_dump(mode="json"),
        },
        age_s=audio_health.freshness_s,
        stale=audio_health.status == "unknown",
    )

    provenance = _resolve_egress_provenance(
        manifest_path=p.broadcast_manifest,
        kill_switch_path=p.egress_kill_switch,
        now=current,
        manifest_max_age_s=t.broadcast_manifest_max_age_s,
        kill_switch_max_age_s=t.egress_kill_switch_max_age_s,
    )
    _append(
        evidence,
        "egress_provenance",
        provenance.status,
        provenance.summary,
        observed=provenance.observed,
        age_s=provenance.age_s,
        stale=provenance.stale,
    )
    if provenance.kill_switch_fired_observed is not None:
        _append(
            evidence,
            "egress.kill_switch_fired",
            EvidenceStatus.FAIL,
            "egress provenance kill-switch is active",
            observed=provenance.kill_switch_fired_observed,
            age_s=provenance.age_s,
            stale=provenance.stale,
        )

    video_id = _read_text(p.youtube_video_id).strip()
    video_id_present = bool(video_id)
    video_id_age = _path_age_s(p.youtube_video_id, current)
    _append(
        evidence,
        "active_video_id",
        EvidenceStatus.PASS if video_id_present else EvidenceStatus.FAIL,
        "active YouTube broadcast id is published"
        if video_id_present
        else "active YouTube broadcast id is missing",
        observed={"video_id_present": video_id_present, "video_id": video_id or None},
        age_s=video_id_age,
        stale=not video_id_present,
    )

    ingest_data, ingest_age, ingest_err = _read_json_file(p.youtube_ingest_proof, current)
    ingest_active = (
        isinstance(ingest_data, dict)
        and ingest_data.get("status") == "active"
        and (not video_id or ingest_data.get("video_id") == video_id)
        and ingest_age is not None
        and ingest_age <= t.youtube_ingest_proof_max_age_s
    )
    _append(
        evidence,
        "youtube_ingest",
        EvidenceStatus.PASS if ingest_active else EvidenceStatus.FAIL,
        "YouTube ingest proof is active and matches the video id"
        if ingest_active
        else f"YouTube ingest proof is missing/stale/mismatched ({ingest_err or 'no active proof'})",
        observed={
            "status": ingest_data.get("status") if isinstance(ingest_data, dict) else None,
            "video_id_matches": ingest_data.get("video_id") == video_id
            if isinstance(ingest_data, dict) and video_id
            else None,
        },
        age_s=ingest_age,
        stale=not ingest_active,
    )

    metadata_ok, metadata_age, metadata_summary = _metadata_matches(
        p.broadcast_events,
        video_id,
        current,
        t.broadcast_event_max_age_s,
    )
    _append(
        evidence,
        "metadata",
        EvidenceStatus.PASS if metadata_ok else EvidenceStatus.FAIL,
        metadata_summary,
        age_s=metadata_age,
        stale=not metadata_ok,
    )

    monetization_risk = _recent_monetization_risk(
        p.monetization_flagged_root,
        current,
        t.monetization_window_s,
    )
    monetization_risk = _max_monetization_risk(monetization_risk, provenance.monetization_risk)
    _append(
        evidence,
        "monetization_risk",
        EvidenceStatus.PASS if monetization_risk in {"none", "low"} else EvidenceStatus.FAIL,
        f"recent/provenance monetization risk is {monetization_risk}",
        observed={
            "risk": monetization_risk,
            "egress_provenance_risk": provenance.monetization_risk,
        },
    )

    research_capture_ready = (
        status_running and local_preview and hls_ready and privacy_floor is FloorState.SATISFIED
    )
    public_ready = (
        research_capture_ready
        and audio_floor is FloorState.SATISFIED
        and provenance.public_claim_allowed
        and rtmp_attached
        and mediamtx_ok
        and stream_public
        and working_fortress
        and video_id_present
        and metadata_ok
        and monetization_risk in {"none", "low"}
    )
    public_claim_allowed = public_ready and ingest_active
    state = _classify_state(
        public_claim_allowed=public_claim_allowed,
        public_ready=public_ready,
        research_capture_ready=research_capture_ready,
        local_preview=local_preview,
        stream_public=stream_public,
    )
    confidence = _confidence(evidence)
    return LivestreamEgressState(
        state=state,
        confidence=confidence,
        public_claim_allowed=public_claim_allowed,
        public_ready=public_ready,
        research_capture_ready=research_capture_ready,
        monetization_risk=monetization_risk,
        privacy_floor=privacy_floor,
        audio_floor=audio_floor,
        evidence=evidence,
        public_claim_blockers=_public_claim_blockers(evidence),
        last_transition=_last_transition_iso(
            p, status_data if isinstance(status_data, dict) else {}
        ),
        operator_action=_operator_action(evidence, stream_public=stream_public),
    )


def _resolve_egress_provenance(
    *,
    manifest_path: Path,
    kill_switch_path: Path,
    now: float,
    manifest_max_age_s: float,
    kill_switch_max_age_s: float,
) -> _EgressProvenanceDecision:
    reason_codes: list[str] = []
    offenders: list[dict[str, Any]] = []
    observed: dict[str, Any] = {
        "manifest_path": str(manifest_path),
        "kill_switch_path": str(kill_switch_path),
        "reason_codes": reason_codes,
        "recovery_instruction": _EGRESS_PROVENANCE_RECOVERY,
    }
    ages: list[float] = []

    manifest = _read_manifest_for_egress(
        manifest_path,
        now=now,
        max_age_s=manifest_max_age_s,
        reason_codes=reason_codes,
        observed=observed,
        ages=ages,
    )
    if manifest is not None:
        decision = EgressManifestGate().evaluate(manifest)
        observed["manifest_gate"] = {
            "kill_switch_fired": decision.kill_switch_fired,
            "audio_action": decision.audio_action,
            "visual_action": decision.visual_action,
        }
        for offender in decision.offenders:
            reason_codes.append(_offender_reason_code(offender))
            offenders.append(
                _offender_observed(
                    offender,
                    audio_action=decision.audio_action,
                    visual_action=decision.visual_action,
                )
            )

    kill_state = _read_kill_switch_for_egress(
        kill_switch_path,
        now=now,
        max_age_s=kill_switch_max_age_s,
        reason_codes=reason_codes,
        observed=observed,
        ages=ages,
    )
    kill_switch_fired_observed: dict[str, Any] | None = None
    if kill_state is not None and kill_state.active:
        reason_codes.append("egress_kill_switch_active")
        active_offenders = [
            _offender_observed(
                offender,
                audio_action=kill_state.audio_action,
                visual_action=kill_state.visual_action,
            )
            for offender in kill_state.offenders
        ]
        offenders.extend(active_offenders)
        kill_switch_fired_observed = {
            "event_type": "egress.kill_switch_fired",
            "reason_codes": ["egress_kill_switch_active"],
            "active": True,
            "audio_action": kill_state.audio_action,
            "visual_action": kill_state.visual_action,
            "fallback_visual_token": kill_state.fallback_visual_token,
            "fallback_action": _combined_fallback_action(
                kill_state.audio_action,
                kill_state.visual_action,
            ),
            "recovery_instruction": _EGRESS_PROVENANCE_RECOVERY,
            "offenders": active_offenders,
            "producer_states": {
                key: value.model_dump(mode="json")
                for key, value in kill_state.producer_states.items()
            },
        }

    reason_codes = tuple(dict.fromkeys(reason_codes))
    observed["reason_codes"] = list(reason_codes)
    observed["offenders"] = _dedupe_offenders(offenders)
    public_claim_allowed = not reason_codes
    status = EvidenceStatus.PASS if public_claim_allowed else EvidenceStatus.FAIL
    monetization_risk = _egress_provenance_monetization_risk(reason_codes)
    observed["public_claim_allowed"] = public_claim_allowed
    observed["health_input"] = {
        "status": "pass" if public_claim_allowed else "fail",
        "reason_codes": list(reason_codes),
    }
    observed["monetization_readiness"] = {
        "status": "pass" if public_claim_allowed else "fail",
        "risk": monetization_risk,
        "reason_codes": list(reason_codes),
    }
    return _EgressProvenanceDecision(
        public_claim_allowed=public_claim_allowed,
        status=status,
        summary="broadcast provenance manifest and kill-switch are fresh and clear"
        if public_claim_allowed
        else "broadcast provenance manifest or kill-switch blocks public claims",
        reason_codes=reason_codes,
        observed=observed,
        age_s=max(ages) if ages else None,
        stale=any(code.endswith("_stale") for code in reason_codes),
        monetization_risk=monetization_risk,
        kill_switch_fired_observed=kill_switch_fired_observed,
    )


def _read_manifest_for_egress(
    path: Path,
    *,
    now: float,
    max_age_s: float,
    reason_codes: list[str],
    observed: dict[str, Any],
    ages: list[float],
) -> BroadcastProvenanceManifest | None:
    file_age = _path_age_s(path, now)
    if file_age is not None:
        ages.append(file_age)
    try:
        manifest = read_broadcast_manifest(path)
    except Exception as exc:
        reason_codes.append("egress_provenance_manifest_malformed")
        observed["manifest"] = {
            "status": "malformed",
            "file_age_s": file_age,
            "error": exc.__class__.__name__,
        }
        return None
    if manifest is None:
        reason_codes.append("egress_provenance_manifest_missing")
        observed["manifest"] = {"status": "missing", "file_age_s": file_age}
        return None

    manifest_age = max(0.0, now - manifest.ts)
    ages.append(manifest_age)
    stale = file_age is None or file_age > max_age_s or manifest_age > max_age_s
    if stale:
        reason_codes.append("egress_provenance_manifest_stale")
    observed["manifest"] = {
        "status": "stale" if stale else "fresh",
        "tick_id": manifest.tick_id,
        "max_content_risk": manifest.max_content_risk,
        "audio_asset_count": len(manifest.audio_assets),
        "visual_asset_count": len(manifest.visual_assets),
        "file_age_s": round(file_age, 3) if file_age is not None else None,
        "manifest_age_s": round(manifest_age, 3),
        "authority_ceiling": manifest.authority_ceiling.model_dump(mode="json"),
    }
    return manifest


def _read_kill_switch_for_egress(
    path: Path,
    *,
    now: float,
    max_age_s: float,
    reason_codes: list[str],
    observed: dict[str, Any],
    ages: list[float],
) -> EgressKillSwitchState | None:
    file_age = _path_age_s(path, now)
    if file_age is not None:
        ages.append(file_age)
    try:
        state = read_egress_kill_switch_state(path)
    except Exception as exc:
        reason_codes.append("egress_kill_switch_malformed")
        observed["kill_switch"] = {
            "status": "malformed",
            "file_age_s": file_age,
            "error": exc.__class__.__name__,
        }
        return None
    if state is None:
        reason_codes.append("egress_kill_switch_missing")
        observed["kill_switch"] = {"status": "missing", "file_age_s": file_age}
        return None

    state_age = max(0.0, now - state.updated_at)
    ages.append(state_age)
    stale = file_age is None or file_age > max_age_s or state_age > max_age_s
    if stale:
        reason_codes.append("egress_kill_switch_stale")
    observed["kill_switch"] = {
        "status": "active" if state.active else "clear",
        "active": state.active,
        "audio_action": state.audio_action,
        "visual_action": state.visual_action,
        "fallback_visual_token": state.fallback_visual_token,
        "file_age_s": round(file_age, 3) if file_age is not None else None,
        "state_age_s": round(state_age, 3),
        "producer_states": {
            key: value.model_dump(mode="json") for key, value in state.producer_states.items()
        },
    }
    return state


def _offender_reason_code(offender: EgressOffender) -> str:
    return {
        "missing_token": "egress_provenance_missing_token",
        "not_broadcast_safe": "egress_provenance_not_broadcast_safe",
        "over_tier": "egress_provenance_over_tier",
    }[offender.reason]


def _offender_observed(
    offender: EgressOffender,
    *,
    audio_action: str,
    visual_action: str,
) -> dict[str, Any]:
    return {
        "token": offender.token,
        "risk_tier": offender.tier,
        "source": offender.source,
        "surface": offender.medium,
        "reason": offender.reason,
        "reason_code": _offender_reason_code(offender),
        "fallback_action": visual_action if offender.medium == "visual" else audio_action,
        "recovery_instruction": _EGRESS_PROVENANCE_RECOVERY,
    }


def _combined_fallback_action(audio_action: str, visual_action: str) -> str:
    return f"audio:{audio_action};visual:{visual_action}"


def _dedupe_offenders(offenders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for offender in offenders:
        key = (
            offender.get("token"),
            offender.get("risk_tier"),
            offender.get("source"),
            offender.get("surface"),
            offender.get("reason"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(offender)
    return deduped


def _egress_provenance_monetization_risk(reason_codes: tuple[str, ...]) -> str:
    if not reason_codes:
        return "none"
    if any(
        code
        in {
            "egress_kill_switch_active",
            "egress_provenance_missing_token",
            "egress_provenance_not_broadcast_safe",
            "egress_provenance_over_tier",
        }
        for code in reason_codes
    ):
        return "high"
    return "unknown"


def _max_monetization_risk(left: str, right: str) -> str:
    order = {"none": 0, "low": 1, "medium": 2, "high": 3, "unknown": 4}
    return left if order.get(left, 0) >= order.get(right, 0) else right


def _public_claim_blockers(evidence: list[LivestreamEgressEvidence]) -> list[str]:
    blockers: list[str] = []
    for item in evidence:
        if item.status is EvidenceStatus.PASS:
            continue
        raw = item.observed.get("reason_codes")
        if isinstance(raw, list):
            blockers.extend(str(code) for code in raw)
        elif isinstance(raw, str):
            blockers.append(raw)
    return list(dict.fromkeys(blockers))


def _append(
    evidence: list[LivestreamEgressEvidence],
    source: str,
    status: EvidenceStatus,
    summary: str,
    *,
    observed: dict[str, Any] | None = None,
    age_s: float | None = None,
    stale: bool = False,
) -> None:
    evidence.append(
        LivestreamEgressEvidence(
            source=source,
            status=status,
            summary=summary,
            observed=observed or {},
            age_s=round(age_s, 3) if age_s is not None else None,
            stale=stale,
            timestamp=_iso_from_epoch(time.time() - age_s) if age_s is not None else None,
        )
    )


def _http_status(url: str, timeout_s: float) -> int | None:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            resp.read(1)
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _read_json_file(
    path: Path, now: float
) -> tuple[dict[str, Any] | None, float | None, str | None]:
    age = _path_age_s(path, now)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, age, "missing"
    except json.JSONDecodeError:
        return None, age, "malformed"
    except OSError as exc:
        return None, age, str(exc)
    return data if isinstance(data, dict) else None, age, None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_enum_file[T: StrEnum](
    path: Path, enum_type: type[T], now: float
) -> tuple[T | None, float | None]:
    text = _read_text(path).strip()
    if not text:
        return None, _path_age_s(path, now)
    try:
        return enum_type(text), _path_age_s(path, now)
    except ValueError:
        return None, _path_age_s(path, now)


def _path_age_s(path: Path, now: float) -> float | None:
    try:
        return max(0.0, now - path.stat().st_mtime)
    except OSError:
        return None


def _path_fresh(path: Path, now: float, max_age_s: float) -> bool:
    age = _path_age_s(path, now)
    return age is not None and age <= max_age_s


def _latest_archive_age_s(root: Path, now: float) -> float | None:
    day_dir = root / datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    try:
        candidates = list(day_dir.glob("*.ts.json"))
    except OSError:
        return None
    if not candidates:
        return None
    try:
        latest = max(path.stat().st_mtime for path in candidates)
    except OSError:
        return None
    return max(0.0, now - latest)


def _resolve_privacy_floor(
    *,
    status_data: dict[str, Any],
    consent_state_path: Path,
    env: Mapping[str, str] | None,
) -> FloorState:
    face_policy = resolve_policy(dict(env) if env is not None else None)
    if face_policy is FaceObscurePolicy.DISABLED:
        return FloorState.BLOCKED
    consent_file = _read_text(consent_state_path).strip().lower()
    if consent_file == "blocked":
        return FloorState.BLOCKED
    if status_data.get("consent_recording_allowed") is False:
        return FloorState.BLOCKED
    guest_present = bool(status_data.get("guest_present"))
    consent_phase = str(status_data.get("consent_phase") or "")
    if guest_present and consent_phase != "consent_granted":
        return FloorState.BLOCKED
    if consent_phase in {
        "consent_refused",
        "consent_pending",
        "guest_detected",
        "contract_expiring",
    }:
        return FloorState.BLOCKED
    return FloorState.SATISFIED


def _metadata_matches(
    path: Path,
    video_id: str,
    now: float,
    max_age_s: float,
) -> tuple[bool, float | None, str]:
    if not video_id:
        return False, _path_age_s(path, now), "metadata cannot match without an active video id"
    latest: dict[str, Any] | None = None
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("event_type") == "broadcast_rotated":
                latest = data
    except FileNotFoundError:
        return False, None, "broadcast metadata event log is missing"
    except OSError as exc:
        return False, _path_age_s(path, now), f"broadcast metadata event log unreadable: {exc}"
    if latest is None:
        return False, _path_age_s(path, now), "no broadcast metadata rotation event found"
    event_age = _broadcast_event_age_s(latest, now)
    if event_age is None:
        return False, _path_age_s(path, now), "latest metadata event has no parseable timestamp"
    ids = {
        latest.get("incoming_broadcast_id"),
        latest.get("active_broadcast_id"),
        latest.get("outgoing_broadcast_id"),
    }
    if video_id not in ids:
        return False, event_age, "latest metadata event does not match active video id"
    if event_age > max_age_s:
        return False, event_age, "latest matching metadata event is stale"
    return True, event_age, "latest broadcast metadata event matches active video id"


def _broadcast_event_age_s(event: Mapping[str, Any], now: float) -> float | None:
    raw = event.get("timestamp")
    if isinstance(raw, int | float):
        return max(0.0, now - float(raw))
    if isinstance(raw, str):
        text = raw.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            return max(0.0, now - datetime.fromisoformat(text).timestamp())
        except ValueError:
            return None
    return None


def _recent_monetization_risk(root: Path, now: float, window_s: float) -> str:
    order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    risk = "none"
    if not root.exists():
        return risk
    for path in root.glob("*/*.jsonl"):
        if _path_age_s(path, now) is None or (_path_age_s(path, now) or 0.0) > window_s:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines[-50:]:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ts = _safe_float(data.get("ts"))
            if ts <= 0 or now - ts > window_s:
                continue
            candidate = str(data.get("risk") or "none").lower()
            if order.get(candidate, 0) > order[risk]:
                risk = candidate
    return risk


def _classify_state(
    *,
    public_claim_allowed: bool,
    public_ready: bool,
    research_capture_ready: bool,
    local_preview: bool,
    stream_public: bool,
) -> EgressState:
    if public_claim_allowed:
        return EgressState.PUBLIC_LIVE
    if public_ready:
        return EgressState.PUBLIC_READY
    if stream_public and not public_claim_allowed:
        return EgressState.PUBLIC_BLOCKED
    if research_capture_ready:
        return EgressState.RESEARCH_CAPTURE_READY
    if local_preview:
        return EgressState.LOCAL_PREVIEW
    return EgressState.OFFLINE


def _confidence(evidence: list[LivestreamEgressEvidence]) -> float:
    if not evidence:
        return 0.0
    weights = {
        EvidenceStatus.PASS: 1.0,
        EvidenceStatus.WARN: 0.55,
        EvidenceStatus.UNKNOWN: 0.25,
        EvidenceStatus.FAIL: 0.0,
    }
    return round(sum(weights[item.status] for item in evidence) / len(evidence), 3)


def _operator_action(
    evidence: list[LivestreamEgressEvidence],
    *,
    stream_public: bool,
) -> str:
    by_source = {item.source: item for item in evidence}
    ordered_actions = (
        ("compositor", "start or restart studio-compositor.service"),
        ("local_preview", "restore compositor local preview output"),
        ("hls_playlist", "restore local HLS playlist generation"),
        ("privacy_floor", "restore face-obscure/privacy floor before public egress"),
        ("audio_floor", "restore broadcast audio floor before public egress"),
        (
            "egress_provenance",
            "restore fresh broadcast provenance manifest and clear egress kill-switch",
        ),
        ("working_mode", "switch working mode to fortress before public egress"),
        ("stream_mode", "set stream mode to public_research only when ready"),
        ("rtmp_output", "activate the RTMP output bin"),
        ("mediamtx_hls", "start mediamtx.service and verify /studio/index.m3u8"),
        ("active_video_id", "publish/resolve the active YouTube broadcast id"),
        ("youtube_ingest", "verify YouTube ingest with a fresh active proof"),
        ("metadata", "align broadcast metadata with the active video id"),
        ("monetization_risk", "clear recent high/medium monetization-risk evidence"),
    )
    for source, action in ordered_actions:
        item = by_source.get(source)
        if item is not None and item.status is not EvidenceStatus.PASS:
            if source == "stream_mode" and not stream_public:
                return action
            return action
    return "none"


def _last_transition_iso(paths: LivestreamEgressPaths, status_data: dict[str, Any]) -> str | None:
    candidates: list[float] = []
    for path in (
        paths.livestream_status,
        paths.stream_mode,
        paths.working_mode,
        paths.youtube_ingest_proof,
    ):
        try:
            candidates.append(path.stat().st_mtime)
        except OSError:
            pass
    ts = _safe_float(status_data.get("timestamp"))
    if ts > 0:
        candidates.append(ts)
    if not candidates:
        return None
    return _iso_from_epoch(max(candidates))


def _iso_from_epoch(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


def _safe_float(value: object) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "EgressState",
    "EvidenceStatus",
    "FloorState",
    "LivestreamEgressEvidence",
    "LivestreamEgressPaths",
    "LivestreamEgressState",
    "LivestreamEgressThresholds",
    "resolve_livestream_egress_state",
]
