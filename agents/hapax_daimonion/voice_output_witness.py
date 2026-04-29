"""Publish and read the daimonion voice-output witness.

The witness is intentionally about evidence, not claims. A commanded narration
drive, composed text, synthesized PCM, and completed playback are separate
states; only the playback result can mark the public voice path as playback
present.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

WITNESS_PATH = Path("/dev/shm/hapax-daimonion/voice-output-witness.json")

WitnessStatus = Literal[
    "unknown",
    "drive_seen",
    "composed",
    "synthesis_completed",
    "synthesis_failed",
    "playback_completed",
    "playback_failed",
    "drop_recorded",
    "missing",
    "malformed",
    "stale",
]

ImpulseTerminalState = Literal["pending", "completed", "inhibited", "interrupted", "failed"]


class VoiceOutputWitness(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int = 1
    updated_at: str
    freshness_s: float = 0.0
    status: WitnessStatus = "unknown"
    last_narration_drive: dict[str, Any] | None = None
    last_narration_impulse: dict[str, Any] | None = None
    last_composed_autonomous_narrative: dict[str, Any] | None = None
    last_tts_synthesis: dict[str, Any] | None = None
    last_playback: dict[str, Any] | None = None
    downstream_route_status: dict[str, Any] | None = None
    broadcast_egress_activity: dict[str, Any] | None = None
    planned_utterance: dict[str, Any] | None = None
    blocker_drop_reason: str | None = None

    @property
    def playback_present(self) -> bool:
        return bool(self.last_playback and self.last_playback.get("status") == "completed")


def record_narration_drive(
    impingement: object,
    *,
    fallback_dispatched: bool,
    duplicate_prevented: bool,
    terminal_state: ImpulseTerminalState = "pending",
    terminal_reason: str | None = None,
    path: Path = WITNESS_PATH,
    now: float | None = None,
) -> VoiceOutputWitness:
    ts = _now(now)
    content = getattr(impingement, "content", {}) or {}
    impulse = build_narration_impulse(
        impingement,
        terminal_state=terminal_state,
        terminal_reason=terminal_reason,
        fallback_dispatched=fallback_dispatched,
        duplicate_prevented=duplicate_prevented,
        now=ts,
    )
    evidence = {
        "ts": _iso(ts),
        "impulse_id": impulse["impulse_id"],
        "source": getattr(impingement, "source", ""),
        "drive": content.get("drive") if isinstance(content, dict) else None,
        "strength": _float_or_none(getattr(impingement, "strength", None)),
        "fallback_dispatched": fallback_dispatched,
        "duplicate_prevented": duplicate_prevented,
        "capability_contract": "narration.autonomous_first_system",
    }
    return _merge_and_publish(
        path,
        now=ts,
        status="drive_seen",
        last_narration_drive=evidence,
        last_narration_impulse=impulse,
        blocker_drop_reason=None,
    )


def record_composed_autonomous_narrative(
    *,
    text: str,
    impingement: object,
    candidate: object,
    emit_status: str,
    impulse_id: str | None = None,
    path: Path = WITNESS_PATH,
    now: float | None = None,
) -> VoiceOutputWitness:
    ts = _now(now)
    planned = _planned_utterance(text)
    evidence = {
        "ts": _iso(ts),
        "impulse_id": impulse_id,
        "source": getattr(impingement, "source", ""),
        "capability_name": getattr(candidate, "capability_name", ""),
        "score": _float_or_none(getattr(candidate, "combined", None)),
        "emit_status": emit_status,
    }
    updates: dict[str, Any] = {}
    impulse_update = _impulse_update_for_state(
        _load_existing_payload(path).get("last_narration_impulse"),
        impulse_id=impulse_id,
        terminal_state="pending",
        terminal_reason=f"compose_{emit_status}",
        now=ts,
    )
    if impulse_update is not None:
        updates["last_narration_impulse"] = impulse_update
    return _merge_and_publish(
        path,
        now=ts,
        status="composed",
        last_composed_autonomous_narrative=evidence,
        planned_utterance=planned,
        blocker_drop_reason=None,
        **updates,
    )


def record_tts_synthesis(
    *,
    status: Literal["completed", "failed", "empty"],
    text: str,
    pcm: bytes | None = None,
    error: str | None = None,
    impulse_id: str | None = None,
    path: Path = WITNESS_PATH,
    now: float | None = None,
) -> VoiceOutputWitness:
    ts = _now(now)
    pcm_duration_s = None
    if pcm is not None:
        pcm_duration_s = round(len(pcm) / (2 * 24000), 3)
    evidence = {
        "ts": _iso(ts),
        "impulse_id": impulse_id,
        "status": status,
        "planned_utterance_chars": len(text),
        "planned_utterance_words": len(text.split()),
        "pcm_bytes": len(pcm or b""),
        "pcm_duration_s": pcm_duration_s,
        "error": error,
    }
    impulse_update = _impulse_update_for_state(
        _load_existing_payload(path).get("last_narration_impulse"),
        impulse_id=impulse_id,
        terminal_state="pending" if status == "completed" else "failed",
        terminal_reason=f"tts_{status}",
        now=ts,
    )
    return _merge_and_publish(
        path,
        now=ts,
        status="synthesis_completed" if status == "completed" else "synthesis_failed",
        last_tts_synthesis=evidence,
        planned_utterance=_planned_utterance(text),
        blocker_drop_reason=None if status == "completed" else f"tts_{status}",
        last_narration_impulse=impulse_update,
    )


def record_playback_result(
    *,
    text: str,
    playback_result: object,
    destination: str,
    target: str | None,
    media_role: str,
    impulse_id: str | None = None,
    path: Path = WITNESS_PATH,
    now: float | None = None,
) -> VoiceOutputWitness:
    ts = _now(now)
    status = str(getattr(playback_result, "status", "failed"))
    completed = bool(getattr(playback_result, "completed", False))
    route = _route_status(destination=destination, target=target, media_role=media_role)
    playback = {
        "ts": _iso(ts),
        "impulse_id": impulse_id,
        "status": status,
        "completed": completed,
        "returncode": getattr(playback_result, "returncode", None),
        "target": target,
        "media_role": media_role,
        "pcm_duration_s": _float_or_none(getattr(playback_result, "duration_s", None)),
        "timeout_s": _float_or_none(getattr(playback_result, "timeout_s", None)),
        "process_status": "exited" if status in {"completed", "failed"} else status,
        "error": getattr(playback_result, "error", None),
    }
    egress = _broadcast_egress_activity(completed=completed)
    terminal_state = _playback_terminal_state(status=status, completed=completed)
    impulse_update = _impulse_update_for_state(
        _load_existing_payload(path).get("last_narration_impulse"),
        impulse_id=impulse_id,
        terminal_state=terminal_state,
        terminal_reason=f"playback_{status}",
        now=ts,
    )
    return _merge_and_publish(
        path,
        now=ts,
        status="playback_completed" if completed else "playback_failed",
        last_playback=playback,
        downstream_route_status=route,
        broadcast_egress_activity=egress,
        planned_utterance=_planned_utterance(text),
        blocker_drop_reason=None if completed else f"playback_{status}",
        last_narration_impulse=impulse_update,
    )


def record_drop(
    *,
    reason: str,
    source: str,
    destination: str | None = None,
    target: str | None = None,
    media_role: str | None = None,
    text: str | None = None,
    impulse_id: str | None = None,
    terminal_state: ImpulseTerminalState = "failed",
    path: Path = WITNESS_PATH,
    now: float | None = None,
) -> VoiceOutputWitness:
    ts = _now(now)
    route = None
    if destination is not None or target is not None or media_role is not None:
        route = _route_status(
            destination=destination or "unknown", target=target, media_role=media_role
        )
    impulse_update = _impulse_update_for_state(
        _load_existing_payload(path).get("last_narration_impulse"),
        impulse_id=impulse_id,
        terminal_state=terminal_state,
        terminal_reason=reason,
        now=ts,
    )
    return _merge_and_publish(
        path,
        now=ts,
        status="drop_recorded",
        downstream_route_status=route,
        planned_utterance=_planned_utterance(text) if text is not None else None,
        blocker_drop_reason=reason,
        last_playback={
            "ts": _iso(ts),
            "status": "dropped",
            "completed": False,
            "source": source,
            "reason": reason,
            "target": target,
            "media_role": media_role,
        },
        last_narration_impulse=impulse_update,
    )


def read_voice_output_witness(
    path: Path = WITNESS_PATH,
    *,
    now: float | None = None,
    max_age_s: float = 180.0,
) -> VoiceOutputWitness:
    ts = _now(now)
    age = _path_age_s(path, ts)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _closed_state("missing", "voice_output_witness_missing", ts, age)
    except json.JSONDecodeError:
        return _closed_state("malformed", "voice_output_witness_malformed", ts, age)
    except OSError:
        return _closed_state("malformed", "voice_output_witness_unreadable", ts, age)
    try:
        witness = VoiceOutputWitness.model_validate(raw)
    except ValidationError:
        return _closed_state("malformed", "voice_output_witness_schema_invalid", ts, age)
    freshness = round(age, 3) if age is not None else 0.0
    if age is None or age > max_age_s:
        return witness.model_copy(
            update={
                "status": "stale",
                "freshness_s": freshness,
                "blocker_drop_reason": "voice_output_witness_stale",
            }
        )
    return witness.model_copy(update={"freshness_s": freshness})


def _merge_and_publish(
    path: Path, *, now: float, status: WitnessStatus, **updates
) -> VoiceOutputWitness:
    payload = _load_existing_payload(path)
    payload.update({"version": 1, "updated_at": _iso(now), "freshness_s": 0.0, "status": status})
    for key, value in updates.items():
        if value is not None or key == "blocker_drop_reason":
            payload[key] = value
    witness = VoiceOutputWitness.model_validate(payload)
    _write_json_atomic(path, witness.model_dump(mode="json"))
    return witness


def narration_impulse_id(impingement: object) -> str:
    content = getattr(impingement, "content", {}) or {}
    if isinstance(content, dict):
        content_id = content.get("impulse_id") or content.get("drive_id")
        if content_id:
            return str(content_id)
    imp_id = getattr(impingement, "id", None)
    if imp_id:
        return str(imp_id)
    source = str(getattr(impingement, "source", "unknown"))
    digest_source = {"source": source, "content": content}
    try:
        encoded = json.dumps(digest_source, sort_keys=True, default=str)
    except TypeError:
        encoded = repr(digest_source)
    return f"narration-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:12]}"


def build_narration_impulse(
    impingement: object,
    *,
    terminal_state: ImpulseTerminalState = "pending",
    terminal_reason: str | None = None,
    fallback_dispatched: bool | None = None,
    duplicate_prevented: bool | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    ts = _now(now)
    content = getattr(impingement, "content", {}) or {}
    content_dict = content if isinstance(content, dict) else {}
    strength = _float_or_none(getattr(impingement, "strength", None))
    posterior = _clamp(strength if strength is not None else 0.3, 0.0, 1.0)
    envelope = {
        "ts": _iso(ts),
        "impulse_id": narration_impulse_id(impingement),
        "content_summary": _content_summary(content_dict),
        "evidence_refs": _evidence_refs(impingement, content_dict),
        "valence": str(content_dict.get("valence") or "pressure"),
        "urgency": posterior,
        "drive_name": str(content_dict.get("drive") or "narration"),
        "action_tendency": str(content_dict.get("action_tendency") or "speak"),
        "speech_act_candidate": str(
            content_dict.get("speech_act_candidate") or "autonomous_narrative"
        ),
        "strength_posterior": posterior,
        "role_context": str(content_dict.get("role_context") or "livestream_public_voice"),
        "inhibition_policy": str(
            content_dict.get("inhibition_policy") or "wcs_route_role_claim_gates"
        ),
        "wcs_snapshot_ref": str(
            content_dict.get("wcs_snapshot_ref") or "broadcast_audio_health.voice_output_witness"
        ),
        "learning_policy": str(
            content_dict.get("learning_policy") or "separate_drive_selection_execution_world_claim"
        ),
        "terminal_state": terminal_state,
        "terminal_reason": terminal_reason,
        "capability_contract": "narration.autonomous_first_system",
    }
    if fallback_dispatched is not None:
        envelope["fallback_dispatched"] = fallback_dispatched
    if duplicate_prevented is not None:
        envelope["duplicate_prevented"] = duplicate_prevented
    return envelope


def _impulse_update_for_state(
    current: object,
    *,
    impulse_id: str | None,
    terminal_state: ImpulseTerminalState,
    terminal_reason: str,
    now: float,
) -> dict[str, Any] | None:
    if not impulse_id or not isinstance(current, dict):
        return None
    if str(current.get("impulse_id", "")) != str(impulse_id):
        return None
    updated = dict(current)
    updated.update(
        {
            "ts": _iso(now),
            "terminal_state": terminal_state,
            "terminal_reason": terminal_reason,
        }
    )
    return updated


def _playback_terminal_state(
    *, status: str, completed: bool
) -> Literal["completed", "interrupted", "failed"]:
    if completed:
        return "completed"
    if status == "timeout":
        return "interrupted"
    return "failed"


def _content_summary(content: dict[str, Any]) -> str:
    value = (
        content.get("content_summary")
        or content.get("summary")
        or content.get("narrative")
        or content.get("metric")
        or "narration drive"
    )
    return str(value).strip()[:240]


def _evidence_refs(impingement: object, content: dict[str, Any]) -> list[str]:
    refs = [
        f"source:{getattr(impingement, 'source', 'unknown')}",
        f"drive:{content.get('drive') or 'narration'}",
    ]
    imp_id = getattr(impingement, "id", None)
    if imp_id:
        refs.append(f"impingement:{imp_id}")
    existing = content.get("evidence_refs")
    if isinstance(existing, list):
        refs.extend(str(ref) for ref in existing if ref)
    return refs


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _load_existing_payload(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _route_status(
    *, destination: str, target: str | None, media_role: str | None
) -> dict[str, Any]:
    route_present = bool(media_role) and not (destination == "livestream" and not target)
    return {
        "destination": destination,
        "target": target,
        "media_role": media_role,
        "route_present": route_present,
        "playback_present": False,
    }


def _broadcast_egress_activity(*, completed: bool) -> dict[str, Any]:
    try:
        from shared.broadcast_audio_health import read_broadcast_audio_health_state

        health = read_broadcast_audio_health_state()
        return {
            "source": "audio_safe_for_broadcast",
            "status": str(health.status),
            "safe": health.safe,
            "freshness_s": health.freshness_s,
            "route_present": bool(
                health.evidence.get("egress_binding", {}).get("bound")
                and health.evidence.get("broadcast_forward", {}).get("status") == "pass"
            ),
            "playback_present": completed,
            "egress_audible": None,
            "note": "route health is not an audible marker for this utterance",
        }
    except Exception:
        return {
            "source": "audio_safe_for_broadcast",
            "status": "unknown",
            "safe": False,
            "route_present": False,
            "playback_present": completed,
            "egress_audible": None,
            "note": "audio health read failed",
        }


def _planned_utterance(text: str) -> dict[str, int]:
    return {"chars": len(text), "words": len(text.split())}


def _closed_state(
    status: WitnessStatus, reason: str, now: float, age: float | None
) -> VoiceOutputWitness:
    return VoiceOutputWitness(
        updated_at=_iso(now),
        freshness_s=round(age, 3) if age is not None else 0.0,
        status=status,
        blocker_drop_reason=reason,
    )


def _path_age_s(path: Path, now: float) -> float | None:
    try:
        return max(0.0, now - path.stat().st_mtime)
    except OSError:
        return None


def _now(now: float | None) -> float:
    return now if now is not None else time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


__all__ = [
    "WITNESS_PATH",
    "VoiceOutputWitness",
    "build_narration_impulse",
    "narration_impulse_id",
    "read_voice_output_witness",
    "record_composed_autonomous_narrative",
    "record_drop",
    "record_narration_drive",
    "record_playback_result",
    "record_tts_synthesis",
]
