"""Read & cache the state inputs the composer narrates from.

Each reader has its own TTL — chronicle reads are always fresh because
they drive chapter extraction; working-mode and goal notes change rarely
so they cache for 5 min; stimmung and director activity cache for 60 s.

The cache is per-process and uses a simple monotonic-time gate; tests
clear it via ``_reset_cache()``.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from agents.metadata_composer.public_claim_gate import ClaimEvidence

log = logging.getLogger(__name__)

_CHRONICLE_PATH = Path("/dev/shm/hapax-chronicle/events.jsonl")
_DIRECTOR_INTENT_PATH = Path("/dev/shm/hapax-compositor/director_intent.jsonl")
_RESEARCH_MARKER_PATH = Path("/dev/shm/hapax-compositor/research-marker.json")
_STIMMUNG_PATH = Path("/dev/shm/hapax-stimmung/current.json")
_PUBLIC_CLAIM_EVIDENCE_PATH = Path("/dev/shm/hapax-metadata/public-claim-evidence.json")

# Per-source TTLs in seconds.
_TTL_SLOW_S = 300.0  # working_mode, goals
_TTL_FAST_S = 60.0  # stimmung, director, programme

_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl_s: float, fetch):
    now = time.monotonic()
    entry = _cache.get(key)
    if entry is not None and (now - entry[0]) < ttl_s:
        return entry[1]
    value = fetch()
    _cache[key] = (now, value)
    return value


def _reset_cache() -> None:
    """Test hook — drop all cached state so the next read re-fetches."""
    _cache.clear()


@dataclass(frozen=True)
class StateSnapshot:
    """The set of state values the composer reads in a single tick.

    Frozen so callers can't mutate; assembled by ``snapshot()``.
    """

    working_mode: str
    programme: Any  # Programme | None — typed as Any to keep import-light
    stimmung_tone: str
    director_activity: str
    chronicle_events: list[dict] = field(default_factory=list)


def snapshot() -> StateSnapshot:
    """Assemble a single composer-tick view of state."""
    return StateSnapshot(
        working_mode=read_working_mode(),
        programme=read_active_programme(),
        stimmung_tone=read_stimmung_tone(),
        director_activity=read_director_activity(),
        chronicle_events=[],  # composer pulls per-window for chapters
    )


def read_working_mode() -> str:
    def _fetch() -> str:
        try:
            from shared.working_mode import get_working_mode  # noqa: PLC0415

            return str(get_working_mode().value)
        except Exception as exc:  # missing config / file
            log.debug("working mode read failed: %s", exc)
            return "research"

    return _cached("working_mode", _TTL_SLOW_S, _fetch)


def read_active_programme():
    def _fetch():
        try:
            from shared.programme_store import default_store  # noqa: PLC0415

            return default_store().active_programme()
        except Exception as exc:
            log.debug("active programme read failed: %s", exc)
            return None

    return _cached("active_programme", _TTL_FAST_S, _fetch)


def read_stimmung_tone() -> str:
    def _fetch() -> str:
        try:
            data = json.loads(_STIMMUNG_PATH.read_text(encoding="utf-8"))
            tone = data.get("tone")
            if isinstance(tone, str):
                return tone
            stance = data.get("stance")
            if isinstance(stance, str):
                return stance
        except (OSError, ValueError) as exc:
            log.debug("stimmung read failed: %s", exc)
        return "ambient"

    return _cached("stimmung_tone", _TTL_FAST_S, _fetch)


def read_director_activity() -> str:
    def _fetch() -> str:
        try:
            data = json.loads(_RESEARCH_MARKER_PATH.read_text(encoding="utf-8"))
            activity = data.get("activity")
            if isinstance(activity, str):
                return activity
        except (OSError, ValueError):
            pass
        try:
            with _DIRECTOR_INTENT_PATH.open("r", encoding="utf-8") as fh:
                lines = fh.readlines()
            if lines:
                last = json.loads(lines[-1])
                activity = last.get("activity") or last.get("intent")
                if isinstance(activity, str):
                    return activity
        except (OSError, ValueError) as exc:
            log.debug("director intent read failed: %s", exc)
        return "observe"

    return _cached("director_activity", _TTL_FAST_S, _fetch)


def read_chronicle(*, since: float, until: float) -> list[dict]:
    """Return chronicle events in [since, until). Always fresh, no cache."""
    if not _CHRONICLE_PATH.exists():
        return []
    out: list[dict] = []
    try:
        with _CHRONICLE_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                ts = event.get("ts")
                if not isinstance(ts, (int, float)):
                    continue
                if since <= ts < until:
                    out.append(event)
    except OSError as exc:
        log.warning("chronicle read failed: %s", exc)
    return out


def read_public_claim_evidence(
    *,
    state: StateSnapshot,
    broadcast_id: str | None,
    triggering_event: dict | None,
) -> ClaimEvidence:
    """Return fail-closed evidence for the metadata public-claim gate.

    Producers may publish the canonical JSON object at
    ``/dev/shm/hapax-metadata/public-claim-evidence.json``. When that file is
    absent, the reader derives only narrow live evidence from the livestream
    egress resolver and otherwise leaves fields empty so unsupported claims
    refuse rather than infer authority from private state.
    """

    data, provided = _read_public_claim_evidence_file()
    egress = _read_livestream_egress_state()
    if egress is not None:
        active_id, active_age = _active_video_id(egress)
        candidate_id = broadcast_id or active_id
        if "broadcast_id" not in provided:
            data["broadcast_id"] = candidate_id or ""
        if "broadcast_age_s" not in provided:
            data["broadcast_age_s"] = (
                active_age if candidate_id and candidate_id == active_id else None
            )
        if "egress_active" not in provided:
            data["egress_active"] = bool(
                candidate_id and candidate_id == active_id and egress.public_claim_allowed
            )
        if "monetization_active" not in provided:
            data["monetization_active"] = bool(
                egress.public_claim_allowed and egress.monetization_risk in {"none", "low"}
            )

    if "current_activity" not in provided and state.director_activity != "observe":
        data["current_activity"] = state.director_activity
    role = _programme_role_value(state.programme)
    if role:
        if "programme_role" not in provided:
            data["programme_role"] = role
        if "programme_role_age_s" not in provided:
            data["programme_role_age_s"] = 0.0

    payload = triggering_event.get("payload") if triggering_event is not None else None
    payload = payload if isinstance(payload, dict) else {}
    event_sources = [payload, triggering_event or {}]
    if "archive_url" not in provided:
        data["archive_url"] = _first_text(event_sources, "archive_url", "replay_url", "public_url")
    if "rights_clear" not in provided and any(
        key in payload for key in ("rights_clear", "rights_state", "rights_class")
    ):
        data["rights_clear"] = _rights_clear(payload)
    if "support_surface_active" not in provided:
        data["support_surface_active"] = bool(
            _first_text(event_sources, "support_url") or payload.get("support_ready") is True
        )
    if "declared_license" not in provided:
        data["declared_license"] = _first_text(event_sources, "declared_license", "license_class")
    if "publication_state" not in provided:
        data["publication_state"] = _first_text(event_sources, "publication_state")
    if "publication_evidence_url" not in provided:
        data["publication_evidence_url"] = _first_text(event_sources, "publication_evidence_url")
    if "issues_disabled" not in provided and "issues_disabled" in payload:
        data["issues_disabled"] = bool(payload.get("issues_disabled"))

    try:
        return ClaimEvidence(**data)
    except (TypeError, ValueError) as exc:
        log.warning("public claim evidence invalid; failing closed: %s", exc)
        return ClaimEvidence()


def _read_public_claim_evidence_file() -> tuple[dict[str, Any], set[str]]:
    if not _PUBLIC_CLAIM_EVIDENCE_PATH.exists():
        return {}, set()
    try:
        payload = json.loads(_PUBLIC_CLAIM_EVIDENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("public claim evidence read failed: %s", exc)
        return {}, set()
    if not isinstance(payload, dict):
        return {}, set()
    allowed = {field.name for field in fields(ClaimEvidence)}
    data = {key: payload[key] for key in allowed if key in payload}
    return data, set(data)


def _read_livestream_egress_state() -> Any | None:
    try:
        from shared.livestream_egress_state import resolve_livestream_egress_state  # noqa: PLC0415

        return _cached(
            "livestream_egress_state",
            _TTL_FAST_S,
            lambda: resolve_livestream_egress_state(probe_network=False),
        )
    except Exception as exc:
        log.debug("livestream egress read failed: %s", exc)
        return None


def _active_video_id(egress: Any) -> tuple[str, float | None]:
    for evidence in getattr(egress, "evidence", []):
        if getattr(evidence, "source", None) != "active_video_id":
            continue
        observed = getattr(evidence, "observed", {})
        if not isinstance(observed, dict):
            continue
        video_id = observed.get("video_id")
        if isinstance(video_id, str) and video_id:
            return video_id, getattr(evidence, "age_s", None)
    return "", None


def _programme_role_value(programme: Any) -> str:
    if programme is None:
        return ""
    role = getattr(programme, "role", "")
    value = getattr(role, "value", role)
    return str(value) if value else ""


def _first_text(sources: list[dict], *keys: str) -> str:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _rights_clear(payload: dict[str, Any]) -> bool:
    if payload.get("rights_clear") is True:
        return True
    rights_state = payload.get("rights_state")
    if isinstance(rights_state, str) and rights_state in {"operator_original", "cleared"}:
        return True
    rights_class = payload.get("rights_class")
    return isinstance(rights_class, str) and rights_class in {
        "operator_original",
        "operator_controlled",
        "third_party_attributed",
        "platform_embedded",
    }
