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


_WARD_HIGHLIGHT_MODIFIERS: dict[str, dict[str, float]] = {
    "pulse": {"border_pulse_hz": 2.0, "scale_bump_pct": 0.05},
    "glow": {"glow_radius_px": 12.0},
    "flash": {"alpha": 1.0, "scale_bump_pct": 0.15},
    "dim": {"alpha": 0.35},
    "foreground": {"alpha": 1.0, "glow_radius_px": 6.0},
    "default": {},
}

_WARD_SIZE_MODIFIERS: dict[str, float] = {
    "shrink-20pct": 0.80,
    "shrink-50pct": 0.50,
    "natural": 1.0,
    "default": 1.0,
    "grow-110pct": 1.10,
    "grow-150pct": 1.50,
}

_WARD_POSITION_MODIFIERS: dict[str, dict[str, float]] = {
    "drift-sine-1hz": {"drift_type_sine": 1.0, "drift_hz": 1.0, "drift_amplitude_px": 12.0},
    "drift-sine-slow": {"drift_type_sine": 1.0, "drift_hz": 0.25, "drift_amplitude_px": 20.0},
    "drift-circle-1hz": {"drift_type_circle": 1.0, "drift_hz": 1.0, "drift_amplitude_px": 16.0},
    "static": {"drift_hz": 0.0, "drift_amplitude_px": 0.0},
    "default": {"drift_hz": 0.0, "drift_amplitude_px": 0.0},
}

_WARD_STAGING_MODIFIERS: dict[str, dict[str, float | bool | int | None]] = {
    "hide": {"visible": False},
    "show": {"visible": True},
    "top": {"z_order_override": 90},
    "bottom": {"z_order_override": 5},
    "default": {"z_order_override": None, "visible": True},
}

_WARD_CADENCE_MODIFIERS: dict[str, float | None] = {
    "pulse-2hz": 2.0,
    "pulse-4hz": 4.0,
    "quick": 6.0,
    "slow": 1.0,
    "default": None,
}


def _ward_dispatch_common(
    capability_name: str,
    family_prefix: str,
) -> tuple[str, str] | None:
    """Parse a ``ward.<family>.<ward_id>.<modifier>`` capability name.

    Returns ``(ward_id, modifier)`` on success or ``None`` if the name is
    malformed. ``ward_id`` may itself contain hyphens (camera-pip:role,
    overlay-zone:main, etc.) so the split limit is set to consume the
    family prefix and trailing modifier with everything in-between
    treated as the ward identifier.
    """
    if not capability_name.startswith(family_prefix + "."):
        log.warning("malformed %s name: %s", family_prefix, capability_name)
        return None
    suffix = capability_name[len(family_prefix) + 1 :]
    if "." not in suffix:
        log.warning("malformed %s name (no modifier): %s", family_prefix, capability_name)
        return None
    ward_id, _, modifier = suffix.rpartition(".")
    if not ward_id or not modifier:
        log.warning("malformed %s name (empty parts): %s", family_prefix, capability_name)
        return None
    return ward_id, modifier


def dispatch_ward_size(capability_name: str, ttl_s: float) -> bool:
    """``ward.size.<ward_id>.<modifier>`` → ward-properties.json (scale field).

    Modifier vocabulary: ``shrink-20pct``, ``shrink-50pct``, ``natural``,
    ``default``, ``grow-110pct``, ``grow-150pct``. Unknown modifiers
    log a warning and return False without writing — silently clobbering
    a prior in-flight override with a typo would be worse than no-op.
    """
    parsed = _ward_dispatch_common(capability_name, "ward.size")
    if parsed is None:
        return False
    ward_id, modifier = parsed
    scale = _WARD_SIZE_MODIFIERS.get(modifier)
    if scale is None:
        log.warning("ward.size unknown modifier %s in %s", modifier, capability_name)
        return False
    _write_ward_property(ward_id, ttl_s, scale=scale)
    _mark_recruitment("ward.size")
    return True


def dispatch_ward_position(capability_name: str, ttl_s: float) -> bool:
    """``ward.position.<ward_id>.<modifier>`` → ward-properties.json (drift_*).

    Modifier vocabulary: ``drift-sine-1hz``, ``drift-sine-slow``,
    ``drift-circle-1hz``, ``static``, ``default``. Unknown modifiers
    return False without writing — see ``dispatch_ward_size`` rationale.
    """
    parsed = _ward_dispatch_common(capability_name, "ward.position")
    if parsed is None:
        return False
    ward_id, modifier = parsed
    spec = _WARD_POSITION_MODIFIERS.get(modifier)
    if spec is None:
        log.warning("ward.position unknown modifier %s in %s", modifier, capability_name)
        return False
    if spec.get("drift_type_sine"):
        drift_type = "sine"
    elif spec.get("drift_type_circle"):
        drift_type = "circle"
    else:
        drift_type = "none"
    _write_ward_property(
        ward_id,
        ttl_s,
        drift_type=drift_type,
        drift_hz=float(spec.get("drift_hz", 0.0)),
        drift_amplitude_px=float(spec.get("drift_amplitude_px", 0.0)),
    )
    _mark_recruitment("ward.position")
    return True


def dispatch_ward_staging(capability_name: str, ttl_s: float) -> bool:
    """``ward.staging.<ward_id>.<modifier>`` → ward-properties.json (visible/z_order).

    Modifier vocabulary: ``hide``, ``show``, ``top``, ``bottom``, ``default``.
    Unknown modifiers return False without writing.
    """
    parsed = _ward_dispatch_common(capability_name, "ward.staging")
    if parsed is None:
        return False
    ward_id, modifier = parsed
    spec = _WARD_STAGING_MODIFIERS.get(modifier)
    if spec is None:
        log.warning("ward.staging unknown modifier %s in %s", modifier, capability_name)
        return False
    update: dict = {}
    if "visible" in spec:
        update["visible"] = bool(spec["visible"])
    if "z_order_override" in spec:
        update["z_order_override"] = spec["z_order_override"]
    _write_ward_property(ward_id, ttl_s, **update)
    _mark_recruitment("ward.staging")
    return True


def dispatch_ward_highlight(capability_name: str, ttl_s: float) -> bool:
    """``ward.highlight.<ward_id>.<modifier>`` → ward-properties.json (alpha/glow/pulse).

    Modifier vocabulary: ``pulse``, ``glow``, ``flash``, ``dim``,
    ``foreground``, ``default``. Unknown modifiers return False without
    writing.
    """
    parsed = _ward_dispatch_common(capability_name, "ward.highlight")
    if parsed is None:
        return False
    ward_id, modifier = parsed
    spec = _WARD_HIGHLIGHT_MODIFIERS.get(modifier)
    if spec is None:
        log.warning("ward.highlight unknown modifier %s in %s", modifier, capability_name)
        return False
    _write_ward_property(ward_id, ttl_s, **{k: float(v) for k, v in spec.items()})
    _mark_recruitment("ward.highlight")
    return True


def dispatch_ward_appearance(capability_name: str, ttl_s: float) -> bool:
    """``ward.appearance.<ward_id>.<modifier>`` → ward-properties.json (color).

    Modifier vocabulary: ``tint-warm``, ``tint-cool``, ``desaturate``,
    ``palette-default``, ``default``. The two ``*default`` modifiers
    explicitly clear any prior color override; other unknown modifiers
    return False without writing.
    """
    parsed = _ward_dispatch_common(capability_name, "ward.appearance")
    if parsed is None:
        return False
    ward_id, modifier = parsed
    palette: dict[str, tuple[float, float, float, float] | None] = {
        "tint-warm": (1.0, 0.85, 0.65, 1.0),
        "tint-cool": (0.65, 0.85, 1.0, 1.0),
        "desaturate": (0.7, 0.7, 0.7, 1.0),
        "palette-default": None,
        "default": None,
    }
    if modifier not in palette:
        log.warning("ward.appearance unknown modifier %s in %s", modifier, capability_name)
        return False
    _write_ward_property(ward_id, ttl_s, color_override_rgba=palette[modifier])
    _mark_recruitment("ward.appearance")
    return True


def dispatch_ward_cadence(capability_name: str, ttl_s: float) -> bool:
    """``ward.cadence.<ward_id>.<modifier>`` → ward-properties.json (rate_hz_override).

    Modifier vocabulary: ``pulse-2hz``, ``pulse-4hz``, ``quick``,
    ``slow``, ``default``. ``default`` clears the override; other
    unknown modifiers return False without writing.
    """
    parsed = _ward_dispatch_common(capability_name, "ward.cadence")
    if parsed is None:
        return False
    ward_id, modifier = parsed
    if modifier not in _WARD_CADENCE_MODIFIERS:
        log.warning("ward.cadence unknown modifier %s in %s", modifier, capability_name)
        return False
    _write_ward_property(ward_id, ttl_s, rate_hz_override=_WARD_CADENCE_MODIFIERS[modifier])
    _mark_recruitment("ward.cadence")
    return True


def dispatch_ward_choreography(capability_name: str, ttl_s: float) -> bool:
    """``ward.choreography.<sequence_name>`` → ward-animation-state.json transitions.

    Sequence vocabulary: ``album-emphasize``, ``hothouse-quiet``,
    ``camera-spotlight``. Each sequence emits a coordinated set of
    ``Transition`` entries that the animation engine plays in parallel.

    The choreography modifier (sequence name) is everything after
    ``ward.choreography.``; we don't sub-parse a ward_id for this family
    because the sequence itself names the wards it touches.
    """
    if not capability_name.startswith("ward.choreography."):
        log.warning("malformed ward.choreography name: %s", capability_name)
        return False
    sequence_name = capability_name[len("ward.choreography.") :]
    if not sequence_name:
        log.warning("ward.choreography name has empty sequence: %s", capability_name)
        return False
    transitions = _build_choreography_sequence(sequence_name, ttl_s)
    if not transitions:
        log.warning("ward.choreography unknown sequence: %s", sequence_name)
        return False
    from agents.studio_compositor.animation_engine import append_transitions

    append_transitions(transitions)
    _mark_recruitment("ward.choreography")
    return True


def _build_choreography_sequence(sequence_name: str, ttl_s: float) -> list:
    """Return the predefined ``Transition`` list for ``sequence_name``.

    Empty list signals an unknown sequence name. Sequences are kept
    short and predictable; new sequences should be added here with a
    one-line comment explaining the operator-facing intent.

    The ``ttl_s`` argument is the dispatch-side TTL; sequences cap each
    transition's ``duration_s`` at min(ttl_s, baked_default) so a long
    TTL doesn't extend a quick pulse.

    ``from_value`` is read from each ward's current property state via
    :func:`resolve_ward_properties` so the transition starts where the
    ward actually IS — not where the sequence author guessed it would
    be. Without this read, a ward that was previously dimmed to 0.4
    would visibly snap to 1.0 (the guessed start) before easing.

    Note on consumer wiring: ``album-emphasize``, ``hothouse-quiet``,
    and ``camera-spotlight`` target Cairo source IDs (album, token_pole,
    sierpinski, hothouse panels) and surface IDs (pip-ur etc.). Today
    only ``OverlayZone.render`` consumes ward-properties; until per-
    Cairo-source consumption + glvideomixer pad mutation land in
    follow-up PRs, these sequences write to the animation-state file
    but produce no visible effect on the livestream surface.
    """
    from agents.studio_compositor.animation_engine import Transition
    from agents.studio_compositor.ward_properties import resolve_ward_properties

    now = time.time()
    cap = max(0.1, min(ttl_s, 5.0))

    def _alpha(ward_id: str) -> float:
        return resolve_ward_properties(ward_id).alpha

    def _scale(ward_id: str) -> float:
        return resolve_ward_properties(ward_id).scale

    if sequence_name == "album-emphasize":
        # Album scales up + brightens; everything else dims.
        return [
            Transition(
                "album", "scale", _scale("album"), 1.15, min(cap, 0.6), "ease-out-quad", now
            ),
            Transition("album", "alpha", _alpha("album"), 1.0, min(cap, 0.4), "ease-out-quad", now),
            Transition(
                "token_pole",
                "alpha",
                _alpha("token_pole"),
                0.5,
                min(cap, 0.5),
                "ease-in-quad",
                now,
            ),
            Transition(
                "sierpinski",
                "alpha",
                _alpha("sierpinski"),
                0.5,
                min(cap, 0.5),
                "ease-in-quad",
                now,
            ),
        ]
    if sequence_name == "hothouse-quiet":
        # All hothouse panels fade to half, leaving primary content prominent.
        return [
            Transition(w, "alpha", _alpha(w), 0.4, min(cap, 0.5), "ease-out-quad", now)
            for w in (
                "impingement_cascade",
                "recruitment_candidate_panel",
                "thinking_indicator",
                "pressure_gauge",
                "activity_variety_log",
                "whos_here",
            )
        ]
    if sequence_name == "camera-spotlight":
        # The hero camera tile pops up; chrome dims out of the way.
        return [
            Transition(
                "pip-ur", "scale", _scale("pip-ur"), 1.1, min(cap, 0.4), "ease-out-quad", now
            ),
            Transition(
                "pip-ul", "alpha", _alpha("pip-ul"), 0.6, min(cap, 0.5), "ease-in-quad", now
            ),
            Transition(
                "pip-ll", "alpha", _alpha("pip-ll"), 0.6, min(cap, 0.5), "ease-in-quad", now
            ),
            Transition(
                "pip-lr", "alpha", _alpha("pip-lr"), 0.6, min(cap, 0.5), "ease-in-quad", now
            ),
        ]
    return []


def _write_ward_property(ward_id: str, ttl_s: float, **fields_) -> None:
    """Read current ward-specific entry for ``ward_id``, fold in ``fields_``, write back.

    The merge preserves any other override fields previously set on the
    same ward by an earlier dispatcher (e.g. a ``ward.size`` followed
    by a ``ward.highlight`` should leave both scale + alpha present in
    the final entry until expiry).

    Critically: this reads the *specific* entry only, NOT the resolved
    view that includes the ``"all"`` fallback. Otherwise a fresh
    dispatch against a ward with no specific entry yet would absorb the
    fallback's values into the new specific entry — and those values
    would survive past the fallback's TTL, defeating the "specific is
    full take" semantics that :func:`resolve_ward_properties`
    documents.
    """
    from agents.studio_compositor.ward_properties import (
        WardProperties,
        get_specific_ward_properties,
        set_ward_properties,
    )

    current = get_specific_ward_properties(ward_id) or WardProperties()
    update = WardProperties(**{**current.__dict__, **fields_})
    set_ward_properties(ward_id, update, ttl_s)


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


# ── HOMAGE dispatchers (spec §4.11) ────────────────────────────────────────
#
# Each homage.* recruitment writes a single pending-transition entry into
# ``/dev/shm/hapax-compositor/homage-pending-transitions.json``. The
# choreographer (``agents.studio_compositor.homage.choreographer``) reads
# on the next tick, enforces concurrency, and emits the ordered plan.
#
# Mapping capability → transition:
#   homage.rotation.*   → topic-change (non-state-changing; signals rotation)
#   homage.emergence.*  → package.default_entry (ticker-scroll-in in BitchX)
#   homage.swap.*       → part-message + join-message pair
#   homage.cycle.*      → mode-change (signals stepped rotation)
#   homage.recede.*     → package.default_exit (ticker-scroll-out in BitchX)
#   homage.expand.*     → netsplit-burst (emphasis burst per package)


_HOMAGE_PENDING_TRANSITIONS: Path = Path(
    "/dev/shm/hapax-compositor/homage-pending-transitions.json"
)


def _active_package():
    """Lazy import to avoid circular dependency at module load time."""
    from agents.studio_compositor.homage import get_active_package

    return get_active_package()


def _append_pending_transition(source_id: str, transition: str) -> None:
    """Append one pending transition to the SHM file (atomic tmp+rename)."""
    now = time.time()
    current: dict = {}
    try:
        if _HOMAGE_PENDING_TRANSITIONS.exists():
            loaded = json.loads(_HOMAGE_PENDING_TRANSITIONS.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
    except Exception:
        log.debug("homage-pending-transitions read failed", exc_info=True)
    transitions = current.get("transitions") if isinstance(current, dict) else None
    if not isinstance(transitions, list):
        transitions = []
    transitions.append({"source_id": source_id, "transition": transition, "enqueued_at": now})
    payload = {"transitions": transitions, "updated_at": now}
    _atomic_write_json(_HOMAGE_PENDING_TRANSITIONS, payload)


def _homage_source_id_suffix(capability_name: str, family_prefix: str) -> str:
    """Extract the <source_id> part from ``homage.<family>.<source_id>``."""
    parts = capability_name.split(".", 2)
    if len(parts) < 3:
        return ""
    return parts[2]


def dispatch_homage_rotation(capability_name: str) -> bool:
    """Emit a rotation signal — the choreographer treats this as a
    ``topic-change`` non-state-changing transition tagged to the
    conceptual target (signature, package)."""
    suffix = _homage_source_id_suffix(capability_name, "homage.rotation")
    if not suffix:
        log.warning("malformed homage.rotation name: %s", capability_name)
        return False
    _append_pending_transition(source_id=f"rotation:{suffix}", transition="topic-change")
    _mark_recruitment("homage.rotation", extra={"target": suffix})
    return True


def dispatch_homage_emergence(capability_name: str) -> bool:
    """Emit an entry transition for the named ward using the active
    package's ``default_entry`` (ticker-scroll-in under BitchX)."""
    suffix = _homage_source_id_suffix(capability_name, "homage.emergence")
    if not suffix:
        log.warning("malformed homage.emergence name: %s", capability_name)
        return False
    pkg = _active_package()
    transition = pkg.transition_vocabulary.default_entry if pkg else "ticker-scroll-in"
    _append_pending_transition(source_id=suffix.replace("-", "_"), transition=transition)
    _mark_recruitment("homage.emergence", extra={"target": suffix})
    return True


def dispatch_homage_swap(capability_name: str) -> bool:
    """Emit a swap — choreographer sees a part-message + join-message
    pair tagged with the paired targets."""
    suffix = _homage_source_id_suffix(capability_name, "homage.swap")
    if not suffix:
        log.warning("malformed homage.swap name: %s", capability_name)
        return False
    _append_pending_transition(source_id=f"swap-out:{suffix}", transition="part-message")
    _append_pending_transition(source_id=f"swap-in:{suffix}", transition="join-message")
    _mark_recruitment("homage.swap", extra={"target": suffix})
    return True


def dispatch_homage_cycle(capability_name: str) -> bool:
    """Emit a cycle — choreographer sees a mode-change transition
    tagged with the family being cycled."""
    suffix = _homage_source_id_suffix(capability_name, "homage.cycle")
    if not suffix:
        log.warning("malformed homage.cycle name: %s", capability_name)
        return False
    _append_pending_transition(source_id=f"cycle:{suffix}", transition="mode-change")
    _mark_recruitment("homage.cycle", extra={"target": suffix})
    return True


def dispatch_homage_recede(capability_name: str) -> bool:
    """Emit an exit transition for the named ward using the active
    package's ``default_exit`` (ticker-scroll-out under BitchX)."""
    suffix = _homage_source_id_suffix(capability_name, "homage.recede")
    if not suffix:
        log.warning("malformed homage.recede name: %s", capability_name)
        return False
    pkg = _active_package()
    transition = pkg.transition_vocabulary.default_exit if pkg else "ticker-scroll-out"
    _append_pending_transition(source_id=suffix.replace("-", "_"), transition=transition)
    _mark_recruitment("homage.recede", extra={"target": suffix})
    return True


def dispatch_homage_expand(capability_name: str) -> bool:
    """Emit an expansion burst — choreographer sees a netsplit-burst
    transition so the emphasis lands as coordinated multi-ward impact."""
    suffix = _homage_source_id_suffix(capability_name, "homage.expand")
    if not suffix:
        log.warning("malformed homage.expand name: %s", capability_name)
        return False
    _append_pending_transition(source_id=f"expand:{suffix}", transition="netsplit-burst")
    _mark_recruitment("homage.expand", extra={"target": suffix})
    return True


def dispatch(
    record: RecruitmentRecord,
) -> Literal[
    "camera.hero",
    "preset.bias",
    "overlay.emphasis",
    "youtube.direction",
    "attention.winner",
    "stream_mode.transition",
    "ward.size",
    "ward.position",
    "ward.staging",
    "ward.highlight",
    "ward.appearance",
    "ward.cadence",
    "ward.choreography",
    "homage.rotation",
    "homage.emergence",
    "homage.swap",
    "homage.cycle",
    "homage.recede",
    "homage.expand",
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
    if name.startswith("ward.size."):
        return "ward.size" if dispatch_ward_size(name, record.ttl_s) else "unknown"
    if name.startswith("ward.position."):
        return "ward.position" if dispatch_ward_position(name, record.ttl_s) else "unknown"
    if name.startswith("ward.staging."):
        return "ward.staging" if dispatch_ward_staging(name, record.ttl_s) else "unknown"
    if name.startswith("ward.highlight."):
        return "ward.highlight" if dispatch_ward_highlight(name, record.ttl_s) else "unknown"
    if name.startswith("ward.appearance."):
        return "ward.appearance" if dispatch_ward_appearance(name, record.ttl_s) else "unknown"
    if name.startswith("ward.cadence."):
        return "ward.cadence" if dispatch_ward_cadence(name, record.ttl_s) else "unknown"
    if name.startswith("ward.choreography."):
        return "ward.choreography" if dispatch_ward_choreography(name, record.ttl_s) else "unknown"
    if name.startswith("homage.rotation."):
        return "homage.rotation" if dispatch_homage_rotation(name) else "unknown"
    if name.startswith("homage.emergence."):
        return "homage.emergence" if dispatch_homage_emergence(name) else "unknown"
    if name.startswith("homage.swap."):
        return "homage.swap" if dispatch_homage_swap(name) else "unknown"
    if name.startswith("homage.cycle."):
        return "homage.cycle" if dispatch_homage_cycle(name) else "unknown"
    if name.startswith("homage.recede."):
        return "homage.recede" if dispatch_homage_recede(name) else "unknown"
    if name.startswith("homage.expand."):
        return "homage.expand" if dispatch_homage_expand(name) else "unknown"
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
    "dispatch_ward_size",
    "dispatch_ward_position",
    "dispatch_ward_staging",
    "dispatch_ward_highlight",
    "dispatch_ward_appearance",
    "dispatch_ward_cadence",
    "dispatch_ward_choreography",
    "recent_recruitment_age_s",
]
