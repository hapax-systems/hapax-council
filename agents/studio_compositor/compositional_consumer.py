"""CompositionalConsumer — dispatches recruited compositional capabilities.

The AffordancePipeline recruits a capability by name (e.g.
`"cam.hero.overhead.vinyl-spinning"` or `"fx.family.audio-reactive"`) from
the catalog in `shared/compositional_affordances.py`. This consumer
translates recruited names into concrete compositor state mutations by
writing well-defined SHM files the compositor's existing layout mutator,
effect-graph pipeline, overlay renderer, and attention-bid dispatcher
read.

Writes are atomic (tmp + rename) so a reader never sees a partial file.
Each dispatch is best-effort: a dispatch failure logs a warning but
does not raise into the director's tick path.

Epic: volitional grounded director (PR #1017, spec §3.3).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── SHM paths the compositor layer reads ──────────────────────────────────

_HERO_CAMERA_OVERRIDE = Path("/dev/shm/hapax-compositor/hero-camera-override.json")
_OVERLAY_ALPHA_OVERRIDES = Path("/dev/shm/hapax-compositor/overlay-alpha-overrides.json")
_RECENT_RECRUITMENT = Path("/dev/shm/hapax-compositor/recent-recruitment.json")
_YOUTUBE_DIRECTION = Path("/dev/shm/hapax-compositor/youtube-direction.json")
_STREAM_MODE_INTENT = Path("/dev/shm/hapax-compositor/stream-mode-intent.json")

# Camera-role name mapping — capability suffix → camera role reported by
# agents/_cameras.py. The capability catalog uses composite labels (e.g.
# "overhead") that map to the inventory's `c920-overhead` role.
_CAMERA_ROLE_MAP: dict[str, str] = {
    "overhead": "c920-overhead",
    "synths-brio": "brio-synths",
    "operator-brio": "brio-operator",
    "desk-c920": "c920-desk",
    "room-c920": "c920-room",
    "room-brio": "brio-room",
}


class RecruitmentRecord(BaseModel):
    """One recruited capability the pipeline emitted for the consumer."""

    name: str = Field(..., description="Full capability name from the catalog.")
    score: float = Field(default=1.0, ge=0.0, le=1.0)
    impingement_narrative: str = Field(default="")
    ttl_s: float = Field(default=30.0, gt=0.0)


# ── Atomic writers ─────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        log.warning("atomic write to %s failed", path, exc_info=True)


def _safe_load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.debug("read %s failed", path, exc_info=True)
    return {}


# ── Per-family dispatchers ─────────────────────────────────────────────────


_CAMERA_ROLE_HISTORY: list[tuple[float, str]] = []
_CAMERA_MIN_DWELL_S = 12.0
_CAMERA_VARIETY_WINDOW = 3


def _record_camera_role(role: str) -> None:
    now = time.time()
    _CAMERA_ROLE_HISTORY.append((now, role))
    # Keep last 20 or whatever's in the variety window span
    cutoff = now - 600.0
    while _CAMERA_ROLE_HISTORY and _CAMERA_ROLE_HISTORY[0][0] < cutoff:
        _CAMERA_ROLE_HISTORY.pop(0)
    if len(_CAMERA_ROLE_HISTORY) > 20:
        del _CAMERA_ROLE_HISTORY[:-20]


def dispatch_camera_hero(capability_name: str, ttl_s: float) -> bool:
    """cam.hero.<role-slug>.<context> → hero-camera-override.json.

    Returns True iff the role-slug resolved to a known camera role.

    2026-04-18 viewer-experience audit: hero-camera was cycling between
    only 2 of 6 cameras (c920-desk + brio-operator), with 4 cameras
    never picked. Two new gates:
      1. ``_CAMERA_MIN_DWELL_S`` — refuse a swap if the same role was
         just applied within the dwell window (prevents frenetic back-
         and-forth, cinematic minimum ~12s).
      2. ``_CAMERA_VARIETY_WINDOW`` — if the proposed role is among the
         last N applied roles, reject so the pipeline has to surface a
         less-recent camera. Falls through rather than hard-failing so
         the pipeline can still select something.
    Both rules use a module-level history list so they survive across
    back-to-back recruitment passes without requiring state on the
    daimonion-side loop.
    """
    parts = capability_name.split(".", 3)
    if len(parts) < 3 or parts[0] != "cam" or parts[1] != "hero":
        log.warning("malformed camera.hero name: %s", capability_name)
        return False
    role_slug = parts[2]
    role = _CAMERA_ROLE_MAP.get(role_slug)
    if role is None:
        log.warning(
            "camera.hero capability %s has unknown role-slug %s",
            capability_name,
            role_slug,
        )
        return False
    now = time.time()
    # Min-dwell: refuse the swap if the same role was applied very recently.
    if _CAMERA_ROLE_HISTORY:
        last_ts, last_role = _CAMERA_ROLE_HISTORY[-1]
        if last_role == role and (now - last_ts) < _CAMERA_MIN_DWELL_S:
            log.info(
                "camera.hero dwell-gate: %s applied %.1fs ago (< %.0fs), skipping",
                role,
                now - last_ts,
                _CAMERA_MIN_DWELL_S,
            )
            return False
    # Variety window: reject if role is in the last N picks.
    recent_roles = [r for (_ts, r) in _CAMERA_ROLE_HISTORY[-_CAMERA_VARIETY_WINDOW:]]
    if role in recent_roles:
        log.info(
            "camera.hero variety-gate: %s in recent %s, skipping",
            role,
            recent_roles,
        )
        return False
    _atomic_write_json(
        _HERO_CAMERA_OVERRIDE,
        {
            "camera_role": role,
            "ttl_s": ttl_s,
            "set_at": now,
            "source_capability": capability_name,
        },
    )
    _record_camera_role(role)
    _mark_recruitment("camera.hero")
    return True


def dispatch_preset_bias(capability_name: str, ttl_s: float) -> bool:
    """fx.family.<family> → recent-recruitment.json (with family + ttl).

    The compositor's random_mode checks this file before picking a
    random preset; if a fx.family.* was recruited within the ttl, it
    defers to `preset_family_selector.py` (shipped in Phase 3).
    """
    parts = capability_name.split(".", 2)
    if len(parts) < 3 or parts[0] != "fx" or parts[1] != "family":
        log.warning("malformed preset.bias name: %s", capability_name)
        return False
    family = parts[2]
    _mark_recruitment("preset.bias", extra={"family": family, "ttl_s": ttl_s})
    return True


def dispatch_overlay_emphasis(capability_name: str, ttl_s: float) -> bool:
    """overlay.{foreground,dim}.<source> → overlay-alpha-overrides.json.

    Foreground → alpha 1.0 for ttl_s seconds. Dim → alpha 0.3 for ttl_s.
    The compositor's layout mutator merges these with the baseline alphas.
    """
    parts = capability_name.split(".", 2)
    if len(parts) < 3 or parts[0] != "overlay":
        log.warning("malformed overlay.* name: %s", capability_name)
        return False
    action = parts[1]
    target = parts[2]
    if action == "foreground":
        alpha = 1.0
    elif action == "dim":
        alpha = 0.3
    else:
        log.warning("unknown overlay action: %s", action)
        return False
    current = _safe_load_json(_OVERLAY_ALPHA_OVERRIDES)
    overrides = current.get("overrides") or {}
    overrides[target] = {
        "alpha": alpha,
        "expires_at": time.time() + ttl_s,
        "source_capability": capability_name,
    }
    _atomic_write_json(
        _OVERLAY_ALPHA_OVERRIDES,
        {"overrides": overrides, "updated_at": time.time()},
    )
    _mark_recruitment("overlay.emphasis")
    return True


def dispatch_youtube_direction(capability_name: str, ttl_s: float) -> bool:
    """youtube.<action> → youtube-direction.json. Consumed by the director
    loop's slot rotator on next advance decision."""
    parts = capability_name.split(".", 1)
    if len(parts) < 2 or parts[0] != "youtube":
        log.warning("malformed youtube.* name: %s", capability_name)
        return False
    action = parts[1]  # e.g. "cut-to", "advance-queue", "cut-away"
    _atomic_write_json(
        _YOUTUBE_DIRECTION,
        {
            "action": action,
            "ttl_s": ttl_s,
            "set_at": time.time(),
            "source_capability": capability_name,
        },
    )
    _mark_recruitment("youtube.direction")
    return True


def dispatch_attention_winner(capability_name: str) -> bool:
    """attention.winner.<source> → records pending winner in recruitment marker.

    Epic 2 Phase A3 fix: the sibling dispatcher `dispatch_recruited_winner`
    does NOT exist in `agents.attention_bids.dispatcher`. Rather than
    silently swallow an ImportError on every call, record the pending
    winner in the recruitment marker and return True. A future commit can
    add a dispatcher function that reads the marker and acts on the winner.
    """
    parts = capability_name.split(".", 2)
    if len(parts) < 3 or parts[0] != "attention" or parts[1] != "winner":
        log.warning("malformed attention.winner name: %s", capability_name)
        return False
    source = parts[2]
    _mark_recruitment("attention.winner", extra={"pending_source": source})
    return True


def dispatch_stream_mode_transition(capability_name: str) -> bool:
    """stream.mode.<mode>.transition → stream-mode-intent.json. A separate
    gate (shared/stream_transition_gate.py) adjudicates whether the
    transition is permitted. This consumer only REQUESTS the transition."""
    parts = capability_name.split(".")
    if len(parts) < 4 or parts[0] != "stream" or parts[1] != "mode" or parts[-1] != "transition":
        log.warning("malformed stream.mode.*.transition: %s", capability_name)
        return False
    target_mode = parts[2]
    _atomic_write_json(
        _STREAM_MODE_INTENT,
        {
            "target_mode": target_mode,
            "set_at": time.time(),
            "source_capability": capability_name,
        },
    )
    _mark_recruitment("stream_mode.transition")
    return True


# ── Top-level dispatch ─────────────────────────────────────────────────────


def dispatch(
    record: RecruitmentRecord,
) -> Literal[
    "camera.hero",
    "preset.bias",
    "overlay.emphasis",
    "youtube.direction",
    "attention.winner",
    "stream_mode.transition",
    "unknown",
]:
    """Route a recruitment record to the correct dispatcher.

    Returns the family name if dispatch succeeded, or "unknown" otherwise.
    """
    name = record.name
    if name.startswith("cam.hero."):
        return "camera.hero" if dispatch_camera_hero(name, record.ttl_s) else "unknown"
    if name.startswith("fx.family."):
        return "preset.bias" if dispatch_preset_bias(name, record.ttl_s) else "unknown"
    if name.startswith("overlay."):
        return "overlay.emphasis" if dispatch_overlay_emphasis(name, record.ttl_s) else "unknown"
    if name.startswith("youtube."):
        return "youtube.direction" if dispatch_youtube_direction(name, record.ttl_s) else "unknown"
    if name.startswith("attention.winner."):
        return "attention.winner" if dispatch_attention_winner(name) else "unknown"
    if name.startswith("stream.mode.") and name.endswith(".transition"):
        return "stream_mode.transition" if dispatch_stream_mode_transition(name) else "unknown"
    log.warning("unknown compositional capability family: %s", name)
    return "unknown"


# ── Recruitment history for fallback gates (random_mode etc.) ──────────────


def _mark_recruitment(family: str, extra: dict | None = None) -> None:
    """Append-like upsert into recent-recruitment.json.

    Schema: `{"families": {family: {last_recruited_ts: float, ...extra}}}`.
    The `random_mode` fallback reads `last_recruited_ts` for
    `"preset.bias"` and skips its uniform-random pick if the timestamp
    is within a configurable cooldown.
    """
    try:
        current = _safe_load_json(_RECENT_RECRUITMENT)
        families = current.get("families") or {}
        entry: dict = families.get(family) or {}
        entry["last_recruited_ts"] = time.time()
        if extra:
            entry.update(extra)
        families[family] = entry
        _atomic_write_json(
            _RECENT_RECRUITMENT,
            {"families": families, "updated_at": time.time()},
        )
    except Exception:
        log.warning("recruitment marker update failed", exc_info=True)


def recent_recruitment_age_s(family: str) -> float | None:
    """Seconds since `family` was last recruited, or None if never."""
    data = _safe_load_json(_RECENT_RECRUITMENT)
    families = data.get("families") or {}
    entry = families.get(family) or {}
    ts = entry.get("last_recruited_ts")
    if not isinstance(ts, (int, float)):
        return None
    return max(0.0, time.time() - float(ts))


__all__ = [
    "RecruitmentRecord",
    "dispatch",
    "dispatch_camera_hero",
    "dispatch_preset_bias",
    "dispatch_overlay_emphasis",
    "dispatch_youtube_direction",
    "dispatch_attention_winner",
    "dispatch_stream_mode_transition",
    "recent_recruitment_age_s",
]
