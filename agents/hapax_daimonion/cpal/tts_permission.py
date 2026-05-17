"""Continuous TTS permission scalar for public broadcast voice.

The public route still depends on the existing hard safety gates
(explicit intent, fresh programme authorization, bridge metadata, and
``audio_safe_for_broadcast``). This module adds the dynamic-audio layer:
a bounded scalar derived from programme role, live stimmung, and audio
health so public TTS can damp itself during performance-heavy moments.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from shared.broadcast_audio_health import BroadcastAudioHealth

DEFAULT_STIMMUNG_STATE_PATH = Path("/dev/shm/hapax-stimmung/state.json")
MIN_BROADCAST_TTS_PERMISSION = 0.25
STIMMUNG_DIMENSION_MAX_FRESHNESS_S = 120.0

_UNKNOWN_STIMMUNG_FACTOR = 0.5
_STANCE_FACTORS: dict[str, float] = {
    "nominal": 1.0,
    "seeking": 0.9,
    "cautious": 0.75,
    "degraded": 0.5,
    "critical": 0.2,
}


@dataclasses.dataclass(frozen=True)
class TTSPermissionDecision:
    """Continuous public-TTS permission result."""

    scalar: float
    threshold: float
    allowed: bool
    reason_code: str
    components: dict[str, float]
    blockers: tuple[str, ...]
    evidence: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "scalar": self.scalar,
            "threshold": self.threshold,
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "components": self.components,
            "blockers": list(self.blockers),
            "evidence": self.evidence,
        }


def resolve_broadcast_tts_permission(
    *,
    content: Mapping[str, Any],
    programme_auth: Mapping[str, Any],
    audio_health: BroadcastAudioHealth,
    stimmung_state_path: Path = DEFAULT_STIMMUNG_STATE_PATH,
    eligible_roles: Iterable[str] = (),
    threshold: float = MIN_BROADCAST_TTS_PERMISSION,
) -> TTSPermissionDecision:
    """Resolve the public-TTS permission scalar from live state.

    ``audio_content_mix`` follows stimmung convention where 0.0 is low
    pressure and 1.0 is high pressure. The TTS permission component is
    therefore ``1 - audio_content_mix``. Missing or malformed stimmung
    damps to a neutral 0.5 component instead of minting full permission;
    the existing programme/audio gates still fail closed separately.
    """

    blockers: list[str] = []
    evidence: dict[str, Any] = {}

    programme_factor = _programme_factor(
        content=content,
        programme_auth=programme_auth,
        eligible_roles=eligible_roles,
        blockers=blockers,
        evidence=evidence,
    )
    audio_factor = _audio_factor(audio_health, blockers=blockers, evidence=evidence)
    stimmung_factor = _stimmung_factor(
        _read_stimmung_state(stimmung_state_path, evidence=evidence, blockers=blockers),
        blockers=blockers,
        evidence=evidence,
    )

    components = {
        "programme": round(programme_factor, 3),
        "audio": round(audio_factor, 3),
        "stimmung": round(stimmung_factor, 3),
    }
    scalar = round(programme_factor * audio_factor * stimmung_factor, 3)
    allowed = scalar >= threshold
    reason_code = "tts_permission_ok" if allowed else "tts_permission_below_threshold"
    if not allowed and reason_code not in blockers:
        blockers.append(reason_code)
    return TTSPermissionDecision(
        scalar=scalar,
        threshold=threshold,
        allowed=allowed,
        reason_code=reason_code,
        components=components,
        blockers=tuple(blockers),
        evidence=evidence,
    )


def _programme_factor(
    *,
    content: Mapping[str, Any],
    programme_auth: Mapping[str, Any],
    eligible_roles: Iterable[str],
    blockers: list[str],
    evidence: dict[str, Any],
) -> float:
    if not programme_auth.get("authorized"):
        blockers.append(str(programme_auth.get("reason_code") or "programme_authorization_missing"))
        evidence["programme"] = {"authorized": False}
        return 0.0

    role = _normalise_role(content.get("programme_role") or programme_auth.get("programme_role"))
    eligible = {_normalise_role(role_value) for role_value in eligible_roles}
    if role and role != "none" and eligible and role not in eligible:
        blockers.append("programme_role_not_tts_eligible")
        evidence["programme"] = {
            "authorized": True,
            "role": role,
            "eligible": False,
        }
        return 0.0

    evidence["programme"] = {
        "authorized": True,
        "role": role,
        "eligible": True if role else None,
    }
    return 1.0


def _audio_factor(
    audio_health: BroadcastAudioHealth,
    *,
    blockers: list[str],
    evidence: dict[str, Any],
) -> float:
    reason_codes = [getattr(reason, "code", "unknown") for reason in audio_health.blocking_reasons]
    evidence["audio"] = {
        "safe": audio_health.safe,
        "status": str(audio_health.status),
        "freshness_s": audio_health.freshness_s,
        "blocking_reason_codes": reason_codes,
    }
    if not audio_health.safe:
        blockers.append("audio_safe_for_broadcast_false")
        return 0.0
    return 1.0


def _stimmung_factor(
    raw: Mapping[str, Any] | None,
    *,
    blockers: list[str],
    evidence: dict[str, Any],
) -> float:
    if raw is None:
        evidence["stimmung"] = {"read": "missing_or_invalid", "factor": _UNKNOWN_STIMMUNG_FACTOR}
        return _UNKNOWN_STIMMUNG_FACTOR

    stance = _normalise_stance(raw.get("overall_stance") or raw.get("stance"))
    stance_factor = _STANCE_FACTORS.get(stance, _UNKNOWN_STIMMUNG_FACTOR)
    dim = raw.get("audio_content_mix")
    mix_value = _dimension_value(dim)
    mix_freshness_s = _dimension_freshness(dim)
    if mix_value is None:
        blockers.append("stimmung_audio_content_mix_missing")
        mix_factor = _UNKNOWN_STIMMUNG_FACTOR
    elif mix_freshness_s is not None and mix_freshness_s > STIMMUNG_DIMENSION_MAX_FRESHNESS_S:
        blockers.append("stimmung_audio_content_mix_stale")
        mix_factor = _UNKNOWN_STIMMUNG_FACTOR
    else:
        mix_factor = 1.0 - _clamp(mix_value)

    factor = min(stance_factor, mix_factor)
    evidence["stimmung"] = {
        "read": "ok",
        "stance": stance,
        "stance_factor": round(stance_factor, 3),
        "audio_content_mix": None if mix_value is None else round(_clamp(mix_value), 3),
        "audio_content_mix_freshness_s": mix_freshness_s,
        "audio_content_mix_factor": round(mix_factor, 3),
        "factor": round(factor, 3),
    }
    return factor


def _read_stimmung_state(
    path: Path,
    *,
    evidence: dict[str, Any],
    blockers: list[str],
) -> Mapping[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        blockers.append("stimmung_state_missing")
        evidence["stimmung_state_file"] = {"path": str(path), "read": "missing"}
        return None
    except json.JSONDecodeError:
        blockers.append("stimmung_state_malformed")
        evidence["stimmung_state_file"] = {"path": str(path), "read": "malformed"}
        return None
    except OSError as exc:
        blockers.append("stimmung_state_unreadable")
        evidence["stimmung_state_file"] = {
            "path": str(path),
            "read": "error",
            "error": str(exc),
        }
        return None
    if not isinstance(raw, Mapping):
        blockers.append("stimmung_state_invalid")
        evidence["stimmung_state_file"] = {"path": str(path), "read": "invalid"}
        return None
    evidence["stimmung_state_file"] = {"path": str(path), "read": "ok"}
    return raw


def _dimension_value(value: object) -> float | None:
    if isinstance(value, Mapping):
        return _float_or_none(value.get("value"))
    return _float_or_none(value)


def _dimension_freshness(value: object) -> float | None:
    if isinstance(value, Mapping):
        return _float_or_none(value.get("freshness_s"))
    return None


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _normalise_role(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _normalise_stance(value: object) -> str:
    if value is None:
        return "unknown"
    text = str(value).strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text or "unknown"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


__all__ = [
    "DEFAULT_STIMMUNG_STATE_PATH",
    "MIN_BROADCAST_TTS_PERMISSION",
    "STIMMUNG_DIMENSION_MAX_FRESHNESS_S",
    "TTSPermissionDecision",
    "resolve_broadcast_tts_permission",
]
