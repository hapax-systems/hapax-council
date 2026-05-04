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
import os
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


# ── Pattern-1 observability counters ─────────────────────────────────────
# Every dispatch site increments ``hapax_compositional_consumer_dispatch_total``
# labelled by family + outcome (ok / veto / error). This is the observability
# pair the 2026-04-20 dynamic-audit catalog §6.4 + §15 emergent-misbehavior
# detectors require: every intent-emit path carries a happy-path counter
# (outcome=ok) AND a violation-path counter (outcome=veto/error), so the
# dashboard can see rate-change without waiting for a human to notice.
#
# Dynamic-audit catalog-2 §6.4 flagged this as the missing counter; the
# static audit-catalog §7.1 pattern-1 meta-fix calls for every emitter to
# ship with it. Best-effort import: when prometheus_client isn't
# available (unit-test workers, minimal envs), counter stubs no-op so
# the dispatch path stays hot.
try:  # pragma: no cover — covered implicitly by any test using real metrics
    from prometheus_client import Counter as _PromCounter

    _DISPATCH_COUNTER = _PromCounter(
        "hapax_compositional_consumer_dispatch_total",
        "Compositional-consumer dispatches, labelled by family + outcome.",
        labelnames=("family", "outcome"),
    )
except Exception:  # noqa: BLE001 — any import / registration failure → no-op

    class _NoOpCounterChild:
        def inc(self, amount: float = 1.0) -> None:  # noqa: ARG002
            return

    class _NoOpCounter:
        def labels(self, **_kwargs: object) -> _NoOpCounterChild:
            return _NoOpCounterChild()

    _DISPATCH_COUNTER = _NoOpCounter()  # type: ignore[assignment]


def _observe_dispatch(family: str, outcome: str) -> None:
    """Increment the compositional-consumer dispatch counter.

    ``outcome`` is one of ``ok`` (dispatch landed), ``veto`` (gate
    rejected the dispatch — e.g., hero-gate zero-person), or ``error``
    (exception caught upstream). Called from every dispatch function;
    best-effort so metric-backend failures never break a director tick.
    """
    try:
        _DISPATCH_COUNTER.labels(family=family, outcome=outcome).inc()
    except Exception:  # noqa: BLE001
        log.debug("dispatch counter inc failed for %s/%s", family, outcome, exc_info=True)


def observe_dispatch(family: str):
    """Decorator: wrap a ``dispatch_*`` function with the Pattern-1 counter.

    Wraps a function returning ``bool``. ``True`` returns record
    ``outcome=ok``, ``False`` returns record ``outcome=veto``, and
    uncaught exceptions record ``outcome=error`` before re-raising.
    The catalog §15 emergent-misbehavior detectors consume this counter
    to alert on rate-shift (e.g., veto-rate climbing mid-stream).
    """

    def decorator(fn):
        def wrapper(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
            except Exception:
                _observe_dispatch(family, "error")
                raise
            _observe_dispatch(family, "ok" if result else "veto")
            return result

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ── SHM paths the compositor layer reads ──────────────────────────────────

_HERO_CAMERA_OVERRIDE = Path("/dev/shm/hapax-compositor/hero-camera-override.json")
_OVERLAY_ALPHA_OVERRIDES = Path("/dev/shm/hapax-compositor/overlay-alpha-overrides.json")
_RECENT_RECRUITMENT = Path("/dev/shm/hapax-compositor/recent-recruitment.json")
_YOUTUBE_DIRECTION = Path("/dev/shm/hapax-compositor/youtube-direction.json")
_STREAM_MODE_INTENT = Path("/dev/shm/hapax-compositor/stream-mode-intent.json")

# Vision Phase 3 (#150): per_camera_person_count hero-gate. Read the
# daimonion perception-state snapshot (1 Hz writer) so we can reject a
# hero candidate whose camera shows zero people. Monkeypatched in tests.
_PERCEPTION_STATE = Path(os.path.expanduser("~/.cache/hapax-daimonion/perception-state.json"))

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


def _hero_gate_enabled() -> bool:
    """Vision Phase 3 (#150) feature flag, default ON per spec §10.

    Accepts "0", "false", "off", "no" (case-insensitive) as disable.
    Missing env var ⇒ enabled.
    """
    val = os.environ.get("HAPAX_VISION_HERO_GATE")
    if val is None:
        return True
    return val.strip().lower() not in {"0", "false", "off", "no"}


def _camera_has_people(role: str) -> bool:
    """Return True iff ``per_camera_person_count[role] > 0`` in the latest
    perception-state snapshot.

    Fail-open: if the file is missing, unreadable, lacks the key, or the
    role has no entry, return True (accept the candidate). The gate is
    purely additive — it only *rejects* when we have positive evidence
    of an empty room. Absence of evidence is not evidence of absence.

    Vision Phase 3 (#150) spec §6 + plan.
    """
    try:
        raw = _PERCEPTION_STATE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return True
    except OSError:
        log.debug("perception-state read failed", exc_info=True)
        return True
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.debug("perception-state JSON decode failed", exc_info=True)
        return True
    counts = data.get("per_camera_person_count")
    if not isinstance(counts, dict) or not counts:
        # No per-camera vision counts in the snapshot yet — fail open.
        return True
    if role not in counts:
        return True
    try:
        return int(counts[role]) > 0
    except (TypeError, ValueError):
        return True


@observe_dispatch("camera.hero")
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
    # Variety-window gate retired 2026-04-19 (HOMAGE Phase F1). The rule
    # dropped 6,358/45,178 (14%) of camera.hero dispatches over 12h by
    # rejecting any role present in the last N picks — the pipeline
    # already recruits diverse camera.hero.* capabilities via the
    # director's intent_family emissions, so the gate was silently
    # overriding the pipeline's score. Dwell-gate above still prevents
    # frenetic back-and-forth within a ~12s window; variety comes from
    # impingement generation, not post-hoc filtering. See
    # docs/research/2026-04-19-expert-system-blinding-audit.md §A1.
    # Vision Phase 3 (#150): per_camera_person_count hero-gate. Kills the
    # "hero camera picks empty room" regression flagged in the 2026-04-18
    # viewer-experience audit. Additive — rejects and lets the variety
    # fallback select a different camera. Dwell/variety history is NOT
    # updated on rejection, matching the other gates' semantics.
    if _hero_gate_enabled() and not _camera_has_people(role):
        log.info(
            "camera.hero vision-gate: %s has person_count=0, skipping",
            role,
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
    _mark_recruitment("camera.hero")
    return True


@observe_dispatch("preset.bias")
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


# overlay.* target slug → ward_id. Mirrors the informal convention the
# overlay catalog uses: "album" is the album_overlay ward, "captions" the
# captions source, "activity-header" the activity_header panel, etc. The
# slug "all-chrome" intentionally maps to None so a broad dim request
# still lands in the overlay-alpha-overrides file without firing a ward-
# properties write on an illegitimate key. Phase B2 mapping.
_OVERLAY_TARGET_TO_WARD_ID: dict[str, str] = {
    "album": "album_overlay",
    "captions": "captions",
    "chat-legend": "chat_keyword_legend",
    "activity-header": "activity_header",
    "grounding-ticker": "grounding_provenance_ticker",
}


@observe_dispatch("overlay.emphasis")
def dispatch_overlay_emphasis(
    capability_name: str,
    ttl_s: float,
    salience: float | None = None,
) -> bool:
    """overlay.{foreground,dim}.<source> → overlay-alpha-overrides.json.

    Foreground → alpha 1.0 for ttl_s seconds. Dim → alpha 0.3 for ttl_s.
    The compositor's layout mutator merges these with the baseline alphas.

    Phase B2 (homage-completion-plan §2): for ``foreground`` actions
    whose target slug maps to a known ward_id (see
    ``_OVERLAY_TARGET_TO_WARD_ID``), also write the B1 aggressive
    ward-properties envelope (glow_radius_px=14, border_pulse_hz=2.0,
    scale_bump_pct=0.06, alpha=1.0, domain-accent border) so the
    compositor's ward-property consumers visibly react. The
    alpha-overrides file write is preserved for backward compatibility
    with the legacy layout-mutator path.
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
    # Phase B2: if this is a foreground emphasis on a known ward target,
    # additionally write the aggressive ward-properties envelope. Kept
    # off the "dim" path because the whole point of dim is to recede,
    # not emphasize.
    if action == "foreground":
        ward_id = _OVERLAY_TARGET_TO_WARD_ID.get(target)
        if ward_id is not None:
            effective_ttl = ttl_s
            if salience is not None:
                clamped = max(0.0, min(1.5, float(salience)))
                effective_ttl = max(1.5, clamped * _STRUCTURAL_EMPHASIS_TTL_SCALE_S)
            _write_ward_property(
                ward_id,
                effective_ttl,
                alpha=_STRUCTURAL_EMPHASIS_PROPS["alpha"],
                glow_radius_px=_STRUCTURAL_EMPHASIS_PROPS["glow_radius_px"],
                scale_bump_pct=_STRUCTURAL_EMPHASIS_PROPS["scale_bump_pct"],
                border_pulse_hz=_STRUCTURAL_EMPHASIS_PROPS["border_pulse_hz"],
                border_color_rgba=domain_accent_rgba(ward_id),
            )
    _mark_recruitment("overlay.emphasis")
    return True


@observe_dispatch("youtube.direction")
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


@observe_dispatch("attention.winner")
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
    # Phase B2 (homage-completion-plan §2 / reckoning §3.4): the
    # "aggressive" modifiers (pulse, glow, flash, foreground) now share
    # the B1 "in-your-face" envelope (glow_radius_px=14, border_pulse_hz=
    # 2.0, scale_bump_pct=0.06, alpha=1.0) so a recruited
    # ward.highlight.<id>.<modifier> capability lands the same visible
    # impact as a narrative-director structural_intent emphasis. The
    # "dim" / "default" modifiers remain distinct because they express
    # the *opposite* intent (subordinate, reset) and the operator has
    # explicitly wanted them to stay mild.
    "pulse": {
        "alpha": 1.0,
        "glow_radius_px": 14.0,
        "border_pulse_hz": 2.0,
        "scale_bump_pct": 0.06,
    },
    "glow": {
        "alpha": 1.0,
        "glow_radius_px": 14.0,
        "border_pulse_hz": 2.0,
        "scale_bump_pct": 0.06,
    },
    "flash": {
        "alpha": 1.0,
        "glow_radius_px": 14.0,
        "border_pulse_hz": 2.0,
        "scale_bump_pct": 0.15,
    },
    "foreground": {
        "alpha": 1.0,
        "glow_radius_px": 14.0,
        "border_pulse_hz": 2.0,
        "scale_bump_pct": 0.06,
    },
    "dim": {"alpha": 0.35},
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
    _emit_homage_emphasis("ward.size", ward_id)
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
    _emit_homage_emphasis("ward.position", ward_id)
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
    _emit_homage_emphasis("ward.staging", ward_id)
    return True


@observe_dispatch("ward.highlight")
def dispatch_ward_highlight(
    capability_name: str,
    ttl_s: float,
    salience: float | None = None,
) -> bool:
    """``ward.highlight.<ward_id>.<modifier>`` → ward-properties.json (alpha/glow/pulse).

    Modifier vocabulary: ``pulse``, ``glow``, ``flash``, ``dim``,
    ``foreground``, ``default``. Unknown modifiers return False without
    writing.

    Phase B2 (homage-completion-plan §2): the "aggressive" modifiers
    (pulse / glow / flash / foreground) now additionally carry the
    domain-accent ``border_color_rgba`` and a salience-scaled TTL so a
    recruited ``ward.highlight.<id>.<modifier>`` impingement reads with
    the same visible impact as a narrative-director structural_intent
    emphasis. ``salience`` defaults to None (callers that don't pass it
    get the raw ``ttl_s``); when provided it clamps to [0, 1.5] and
    drives ``ttl_s = max(1.5, salience * 5.0)``.
    """
    parsed = _ward_dispatch_common(capability_name, "ward.highlight")
    if parsed is None:
        return False
    ward_id, modifier = parsed
    spec = _WARD_HIGHLIGHT_MODIFIERS.get(modifier)
    if spec is None:
        log.warning("ward.highlight unknown modifier %s in %s", modifier, capability_name)
        return False
    # Phase B2: aggressive modifiers get the domain accent border + the
    # salience-scaled TTL; dim/default stay on their prior (milder)
    # semantics so an LLM that dispatches a "dim" doesn't have its intent
    # inverted into a "pulse".
    aggressive = modifier in ("pulse", "glow", "flash", "foreground")
    props: dict[str, float | tuple[float, float, float, float]] = {
        k: float(v) for k, v in spec.items()
    }
    effective_ttl = ttl_s
    if aggressive:
        props["border_color_rgba"] = domain_accent_rgba(ward_id)
        if salience is not None:
            clamped = max(0.0, min(1.5, float(salience)))
            effective_ttl = max(1.5, clamped * _STRUCTURAL_EMPHASIS_TTL_SCALE_S)
    _write_ward_property(ward_id, effective_ttl, **props)
    _mark_recruitment("ward.highlight")
    _emit_homage_emphasis("ward.highlight", ward_id)
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
    _emit_homage_emphasis("ward.appearance", ward_id)
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
    _emit_homage_emphasis("ward.cadence", ward_id)
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


@observe_dispatch("stream_mode.transition")
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


def dispatch_novelty_shift(capability_name: str, ttl_s: float) -> bool:
    """novelty.shift → recent-recruitment marker only.

    Phase 6 of preset-variety-plan (#1168) registers ``novelty.shift``
    as a recruitment target for ``content.too-similar-recently``
    impingements. It has no SHM side effect of its own — the
    recruitment marker is itself the signal: downstream consumers (the
    affordance pipeline's ``recency_distance`` term) read the marker
    to perturb the next pick away from the recent cluster. So the
    dispatcher only needs to record the recruitment.
    """
    del capability_name  # unused; the recruitment timestamp is the signal
    _mark_recruitment("novelty.shift", extra={"ttl_s": ttl_s})
    return True


def dispatch_transition(capability_name: str, ttl_s: float) -> bool:
    """transition.* → recent-recruitment marker for the live consumer.

    Phase 7b of preset-variety-plan (#1177) wires ``transition.*``
    primitives into ``preset_recruitment_consumer``, which consults
    ``recent-recruitment.json`` for the latest fresh transition before
    falling back to uniform sampling. Like ``novelty.shift`` the marker
    IS the side effect; the primitive runs at the next chain change.
    """
    _mark_recruitment(capability_name, extra={"ttl_s": ttl_s})
    return True


def dispatch_gem(capability_name: str, ttl_s: float) -> bool:
    """gem.* → recent-recruitment marker.

    The GEM producer (``agents/hapax_daimonion/gem_producer.py``) tails
    the impingement bus; the recruitment marker is the signal it reads
    to decide which gem.emphasis.* / gem.composition.* / gem.spawn.*
    keyframe to render. lssh-002 (P0 GEM rendering redesign) will
    define the live visual contract; the dispatcher here keeps the
    catalog-completeness invariant green and the recruitment surface
    alive.
    """
    _mark_recruitment(capability_name, extra={"ttl_s": ttl_s})
    return True


# ── Director micromove vocabulary expansion (cc-task ────────────────────────
# `director-moves-richness-expansion`, operator outcome 3 of 5).
#
# Operator constraint: NO presets — these dispatchers write parametric
# state files only. Downstream consumers (homage choreographer, ward
# animation, imagination uniforms bridge) read these files and apply
# the parametric envelope on their next tick boundary. No preset
# selection happens here — the director NEVER picks a preset.

_COMPOSITION_STATE = Path("/dev/shm/hapax-compositor/composition-state.json")
_PACE_STATE = Path("/dev/shm/hapax-compositor/pace-state.json")
_MOOD_STATE = Path("/dev/shm/hapax-compositor/mood-state.json")
_PROGRAMME_ADVANCE_INTENT = Path("/dev/shm/hapax-compositor/programme-advance-intent.json")


def _capability_variant(capability_name: str, family_prefix: str) -> str:
    """Return the variant suffix from ``family.variant`` (e.g. ``tighten``)."""
    prefix = family_prefix.rstrip(".") + "."
    if capability_name.startswith(prefix):
        return capability_name[len(prefix) :].split(".", 1)[0]
    return ""


# Tempo multiplier table for pace.tempo_shift. Multipliers are applied
# by cadence-aware consumers (homage choreographer, ward animation,
# narrative ticker) to scale their effective period. 1.0 = baseline.
_PACE_MULTIPLIERS: dict[str, float] = {
    "slow": 0.7,
    "quicken": 1.3,
    "steady": 1.0,
}


def dispatch_composition_reframe(capability_name: str, ttl_s: float) -> bool:
    """composition.reframe.* → write composition-state.json + recruit marker.

    Parametric reframe of the active hero camera — distinct from
    ``camera.hero`` (which swaps cameras). The reframe variant
    (``tighten`` / ``widen`` / ``recompose``) is written to the
    composition-state file so the camera-tile property consumer can
    apply the matching ``scale`` / ``position_offset`` envelope on its
    next tick. The recruit marker is the same one transition / gem use
    so the family stays observable in the recent-recruitment surface.
    """
    variant = _capability_variant(capability_name, "composition.reframe") or "recompose"
    _atomic_write_json(
        _COMPOSITION_STATE,
        {
            "reframe": variant,
            "ttl_s": ttl_s,
            "ts": time.time(),
        },
    )
    _mark_recruitment(capability_name, extra={"ttl_s": ttl_s, "variant": variant})
    return True


def dispatch_pace_tempo_shift(capability_name: str, ttl_s: float) -> bool:
    """pace.tempo_shift.* → write pace-state.json + recruit marker.

    Parametric cadence multiplier — slow / quicken / steady. Cadence
    aware consumers (homage choreographer, ward animation, structural
    director) read the multiplier on their next tick boundary and
    rescale their effective period.
    """
    variant = _capability_variant(capability_name, "pace.tempo_shift") or "steady"
    multiplier = _PACE_MULTIPLIERS.get(variant, 1.0)
    _atomic_write_json(
        _PACE_STATE,
        {
            "tempo": variant,
            "multiplier": multiplier,
            "ttl_s": ttl_s,
            "ts": time.time(),
        },
    )
    _mark_recruitment(
        capability_name,
        extra={"ttl_s": ttl_s, "variant": variant, "multiplier": multiplier},
    )
    return True


def dispatch_mood_tone_pivot(capability_name: str, ttl_s: float) -> bool:
    """mood.tone_pivot.* → write mood-state.json + recruit marker.

    Parametric color / warmth / saturation pivot. The reverie uniforms
    bridge (visual_chain → uniforms.json) reads this state and applies
    the matching color-grade deltas. The generative substrate keeps
    running; only the parametric color envelope shifts.
    """
    variant = _capability_variant(capability_name, "mood.tone_pivot") or "steady"
    _atomic_write_json(
        _MOOD_STATE,
        {
            "pivot": variant,
            "ttl_s": ttl_s,
            "ts": time.time(),
        },
    )
    _mark_recruitment(capability_name, extra={"ttl_s": ttl_s, "variant": variant})
    return True


def dispatch_programme_beat_advance(capability_name: str, ttl_s: float) -> bool:
    """programme.beat_advance.* → write programme-advance-intent + recruit marker.

    Structural cue the programme manager picks up to walk the show plan
    forward. The director recognises when the current programme has run
    its course at a perceptual level (sustained activity match,
    narrative arc complete) and emits this family to mark the boundary.
    The programme manager reads the intent file on its next tick and
    advances the plan if the boundary criteria match.
    """
    variant = _capability_variant(capability_name, "programme.beat_advance") or "next"
    _atomic_write_json(
        _PROGRAMME_ADVANCE_INTENT,
        {
            "requested": True,
            "variant": variant,
            "ttl_s": ttl_s,
            "ts": time.time(),
        },
    )
    _mark_recruitment(capability_name, extra={"ttl_s": ttl_s, "variant": variant})
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
    "novelty.shift",
    "transition",
    "gem",
    "composition.reframe",
    "pace.tempo_shift",
    "mood.tone_pivot",
    "programme.beat_advance",
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
        return (
            "overlay.emphasis"
            if dispatch_overlay_emphasis(name, record.ttl_s, salience=record.score)
            else "unknown"
        )
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
        return (
            "ward.highlight"
            if dispatch_ward_highlight(name, record.ttl_s, salience=record.score)
            else "unknown"
        )
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
    if name == "novelty.shift":
        return "novelty.shift" if dispatch_novelty_shift(name, record.ttl_s) else "unknown"
    if name.startswith("transition."):
        return "transition" if dispatch_transition(name, record.ttl_s) else "unknown"
    if name.startswith("gem."):
        return "gem" if dispatch_gem(name, record.ttl_s) else "unknown"
    if name.startswith("composition.reframe."):
        return (
            "composition.reframe" if dispatch_composition_reframe(name, record.ttl_s) else "unknown"
        )
    if name.startswith("pace.tempo_shift."):
        return "pace.tempo_shift" if dispatch_pace_tempo_shift(name, record.ttl_s) else "unknown"
    if name.startswith("mood.tone_pivot."):
        return "mood.tone_pivot" if dispatch_mood_tone_pivot(name, record.ttl_s) else "unknown"
    if name.startswith("programme.beat_advance."):
        return (
            "programme.beat_advance"
            if dispatch_programme_beat_advance(name, record.ttl_s)
            else "unknown"
        )
    log.warning("unknown compositional capability family: %s", name)
    return "unknown"


# ── Narrative-tier structural intent dispatch ──────────────────────────────
#
# The narrative director (30s cadence) attaches a
# ``NarrativeStructuralIntent`` envelope on every DirectorIntent. This
# dispatcher reads it and fans out to the ward-property surface + homage
# pending-transitions queue without going through Qdrant recruitment,
# because structural-intent entries are aesthetic directives, not
# recruitable capabilities. The affordance-pipeline path still owns all
# named capability recruitment (cam.hero, overlay.*, ward.*-family, etc.).
# This dispatcher is additive: it accelerates the homage surface's
# responsiveness so the livestream visibly reacts every narrative tick.

# Per-tick emphasis TTL. The ward-property entry survives for this many
# seconds before the consumer-side expiry sweep discards it.
#
# Phase B1 (homage-completion-plan §2): TTL is now driven by salience at
# the call site (``ttl_s = salience * _STRUCTURAL_EMPHASIS_TTL_SCALE_S``)
# rather than a fixed 4.0s. The scale is 5.0s so that a full-salience
# emphasis (salience=1.0) survives five narrative-director ticks at the
# default 1s cadence — "deeply felt" per operator directive.
_STRUCTURAL_EMPHASIS_TTL_SCALE_S: float = 5.0
_STRUCTURAL_EMPHASIS_TTL_S: float = 5.0  # kept as default for salience=1.0 callers
_STRUCTURAL_PLACEMENT_TTL_S: float = 30.0

# Per-tick emphasis envelope. Phase B1: operator-directive "in-your-face"
# values per homage-completion-plan §2 / reckoning §3.4. The previous
# envelope (glow 14 / pulse 2.2 / bump 0.12) was *already* intended to
# be visible but was routed through `_apply_emphasis` with a
# ``scale = salience`` multiplier which meant salience=1.0 simply landed
# on the declared envelope. The problem the audit surfaced was that the
# *default* ward-properties file carried only the two wards wired to the
# legacy ward_fx coupling path (HARDM + album); nothing was writing
# these values for narrative-director-nominated wards. B1 fixes that by
# making `dispatch_structural_intent` write the envelope directly with
# `border_color_rgba` set to the active homage package's per-domain
# accent, rather than leaving the border-pulse a no-op.
_STRUCTURAL_EMPHASIS_PROPS: dict[str, float] = {
    "alpha": 1.0,
    "glow_radius_px": 14.0,
    "scale_bump_pct": 0.06,
    "border_pulse_hz": 2.0,
}

# Placement-hint → WardProperties field map. Phase B1 (plan §2):
# the canonical "foreground" / "left-edge" / "recede" hints drive
# alpha + ``position_offset_*`` directly per operator directive. The
# legacy drift_* / scale_* / pulse_center hints remain for backwards
# compat with older director prompts that emit those literal strings.
_PLACEMENT_HINT_TO_PROPS: dict[str, dict[str, float | str]] = {
    # Phase-B1 operator-directed hints. "foreground" brings the ward to
    # full alpha with no positional shift; "left-edge" shunts it 50px
    # left so it visibly reads as the edge of the frame; "recede"
    # drops alpha to 0.55 so the ward remains legible but compositionally
    # subordinate to whichever ward is currently foregrounded.
    "foreground": {
        "alpha": 1.0,
        "position_offset_x": 0.0,
        "position_offset_y": 0.0,
    },
    "left-edge": {
        "position_offset_x": -50.0,
    },
    "right-edge": {
        "position_offset_x": 50.0,
    },
    "recede": {
        "alpha": 0.55,
    },
    # Legacy drift / scale / pulse hints (pre-B1). Left in place so older
    # LLM prompts still land on a known placement spec rather than falling
    # through to the unknown-hint log.
    "drift_left": {
        "drift_type": "sine",
        "drift_hz": 0.3,
        "drift_amplitude_px": 14.0,
        "position_offset_x": -8.0,
    },
    "drift_right": {
        "drift_type": "sine",
        "drift_hz": 0.3,
        "drift_amplitude_px": 14.0,
        "position_offset_x": 8.0,
    },
    "drift_up": {
        "drift_type": "sine",
        "drift_hz": 0.3,
        "drift_amplitude_px": 14.0,
        "position_offset_y": -8.0,
    },
    "drift_down": {
        "drift_type": "sine",
        "drift_hz": 0.3,
        "drift_amplitude_px": 14.0,
        "position_offset_y": 8.0,
    },
    "pulse_center": {
        "border_pulse_hz": 3.2,
        "scale_bump_pct": 0.10,
    },
    "scale_0.8x": {"scale": 0.80},
    "scale_1.0x": {"scale": 1.00},
    "scale_1.15x": {"scale": 1.15},
    "scale_1.3x": {"scale": 1.30},
}

# WardDomain → accent colour role. Mirrors the authoritative mapping
# in ``homage/rendering.py:_DOMAIN_ACCENT_ROLE`` so the emphasis
# border-pulse carries the ward's identity colour. Kept local (rather
# than importing from ``homage.rendering``) to avoid a Cairo / Pango
# import chain in the dispatcher's hot path — only a tuple lookup + a
# lazy ``HomagePackage.resolve_colour`` call are needed at call time.
_DOMAIN_ACCENT_ROLE: dict[str, str] = {
    "communication": "accent_green",
    "presence": "accent_yellow",
    "token": "accent_cyan",
    "music": "accent_magenta",
    "cognition": "accent_cyan",
    "director": "accent_yellow",
    "perception": "accent_green",
}


def domain_accent_rgba(ward_id: str) -> tuple[float, float, float, float]:
    """Resolve the homage-package accent colour for ``ward_id``'s domain.

    Phase B1 helper (plan §2): the border-pulse on an emphasized ward
    should land on the active HOMAGE package's per-domain accent so a
    "cognition" ward pulses cyan, a "music" ward pulses magenta, etc.
    The resolution path mirrors ``homage/rendering.py::_domain_accent``:

        ward_id → ward_fx_mapping.domain_for_ward → _DOMAIN_ACCENT_ROLE
                → HomagePackage.resolve_colour → RGBA

    Fail-open: any resolution failure (unknown ward, missing package
    registration, package palette missing the named role) returns a
    neutral cyan ``(0.7, 0.85, 1.0, 1.0)`` so the border-pulse still
    renders legibly rather than disappearing.
    """
    try:
        from agents.studio_compositor.ward_fx_mapping import domain_for_ward

        domain = domain_for_ward(ward_id)
    except Exception:
        log.debug("domain_accent_rgba: domain_for_ward failed for %s", ward_id, exc_info=True)
        return (0.7, 0.85, 1.0, 1.0)
    role = _DOMAIN_ACCENT_ROLE.get(str(domain), "accent_cyan")
    try:
        from agents.studio_compositor.homage import get_active_package

        pkg = get_active_package()
        if pkg is None:
            from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

            pkg = BITCHX_PACKAGE
        return pkg.resolve_colour(role)  # type: ignore[arg-type]
    except Exception:
        log.debug(
            "domain_accent_rgba: package resolve_colour failed for %s", ward_id, exc_info=True
        )
        return (0.7, 0.85, 1.0, 1.0)


# Mirror of ``shared.director_intent.WardId`` — used to gate the LLM's
# ward name against typos. Kept in sync manually; drift between the two
# literal unions is caught by ``test_structural_intent_dispatch``.
_VALID_WARD_IDS: frozenset[str] = frozenset(
    [
        "chat_ambient",
        "activity_header",
        "stance_indicator",
        "grounding_provenance_ticker",
        "impingement_cascade",
        "recruitment_candidate_panel",
        "thinking_indicator",
        "pressure_gauge",
        "activity_variety_log",
        "whos_here",
        "token_pole",
        "album_overlay",
        "sierpinski",
        "stream_overlay",
        "captions",
        "research_marker_overlay",
        "chat_keyword_legend",
        "vinyl_platter",
        "overlay_zones",
    ]
)

# Dispatcher-owned pending transitions file. Same path as the homage
# family dispatchers — the choreographer drains on every reconcile.
_HOMAGE_PENDING: Path = Path("/dev/shm/hapax-compositor/homage-pending-transitions.json")


def _emit_homage_emphasis(intent_family: str, ward_id: str) -> None:
    """Best-effort bump of ``hapax_homage_emphasis_applied_total``.

    Phase C1 (homage-completion-plan §2): every ward-properties write
    driven by an intent_family increments this counter so the §7.3
    verification protocol has direct proof that the narrative director
    is actually writing to the ward-properties surface. Import and
    emit failures are swallowed — the metric is diagnostic and must
    not break the dispatcher hot path.
    """
    try:
        from shared.director_observability import emit_homage_emphasis_applied

        emit_homage_emphasis_applied(ward=ward_id, intent_family=intent_family)
    except Exception:
        log.debug(
            "emit_homage_emphasis_applied failed for %s / %s",
            ward_id,
            intent_family,
            exc_info=True,
        )


def _apply_emphasis(ward_id: str, salience: float = 1.0) -> None:
    """Bump a ward's highlight envelope for the structural-intent window.

    Phase B1 (homage-completion-plan §2 / reckoning §3.4): writes the
    full aggressive envelope (glow_radius_px=14.0, border_pulse_hz=2.0,
    scale_bump_pct=0.06, alpha=1.0) rather than the prior near-no-op
    salience-scaled modulation. The border colour is resolved through
    the active HOMAGE package's per-domain accent via
    :func:`domain_accent_rgba` so an emphasized ward pulses in its
    identity colour rather than plain white. The TTL scales linearly
    with ``salience`` (``ttl_s = max(1.5, salience * 5.0)``) so a
    full-salience emphasis survives five narrative-director ticks at
    the default 1s cadence and a brief emphasis (salience<0.3) still
    persists long enough to be visibly perceived.

    Prior (pre-B1) behaviour multiplied every envelope field by
    salience, which meant a salience=0.5 emphasis produced a 7px glow /
    1.1Hz pulse / 0.06 bump — below the reader-visibility threshold the
    operator flagged on 2026-04-18. B1 keeps the envelope fixed and
    pushes the salience degree-of-freedom into TTL instead.
    """
    if ward_id not in _VALID_WARD_IDS:
        log.debug("structural_intent: skipping unknown ward_id %s", ward_id)
        return
    try:
        from agents.studio_compositor.ward_properties import (
            WardProperties,
            get_specific_ward_properties,
            set_ward_properties,
        )
    except Exception:
        log.debug("ward_properties import failed", exc_info=True)
        return
    current = get_specific_ward_properties(ward_id) or WardProperties()
    clamped_salience = max(0.0, min(1.5, float(salience)))
    # TTL floor of 1.5s so even a low-salience emphasis is visibly
    # perceivable; ceiling falls out naturally from the salience clamp.
    ttl_s = max(1.5, clamped_salience * _STRUCTURAL_EMPHASIS_TTL_SCALE_S)
    props = {
        "alpha": _STRUCTURAL_EMPHASIS_PROPS["alpha"],
        "glow_radius_px": _STRUCTURAL_EMPHASIS_PROPS["glow_radius_px"],
        "scale_bump_pct": _STRUCTURAL_EMPHASIS_PROPS["scale_bump_pct"],
        "border_pulse_hz": _STRUCTURAL_EMPHASIS_PROPS["border_pulse_hz"],
        "border_color_rgba": domain_accent_rgba(ward_id),
    }
    merged = WardProperties(**{**current.__dict__, **props})
    set_ward_properties(ward_id, merged, ttl_s)
    _mark_recruitment("structural.emphasis", extra={"ward_id": ward_id, "ttl_s": ttl_s})
    # Phase C1 (homage-completion-plan §2): count every structural
    # emphasis write so ``rate(hapax_homage_emphasis_applied_total[5m])``
    # reflects the narrative director's actual write-rate to the
    # ward-properties surface (the §7.3 verification protocol's
    # aliveness check).
    _emit_homage_emphasis("structural.emphasis", ward_id)


def _apply_placement(ward_id: str, hint: str) -> None:
    """Translate a placement hint into ward-property fields."""
    if ward_id not in _VALID_WARD_IDS:
        return
    spec = _PLACEMENT_HINT_TO_PROPS.get(hint)
    if spec is None:
        log.debug("structural_intent: unknown placement hint %s", hint)
        return
    try:
        from agents.studio_compositor.ward_properties import (
            WardProperties,
            get_specific_ward_properties,
            set_ward_properties,
        )
    except Exception:
        log.debug("ward_properties import failed", exc_info=True)
        return
    current = get_specific_ward_properties(ward_id) or WardProperties()
    merged = WardProperties(**{**current.__dict__, **spec})
    set_ward_properties(ward_id, merged, _STRUCTURAL_PLACEMENT_TTL_S)
    _mark_recruitment("structural.placement", extra={"ward_id": ward_id, "hint": hint})


def _enqueue_homage_pending(source_id: str, transition: str, salience: float) -> None:
    """Append a homage pending-transition entry without going through a
    named capability recruitment. Mirrors ``_append_pending_transition``
    with a salience hint so ``weighted_by_salience`` rotation mode can
    score structural-intent dispatches against named recruitments."""
    now = time.time()
    current: dict = {}
    try:
        if _HOMAGE_PENDING.exists():
            loaded = json.loads(_HOMAGE_PENDING.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
    except Exception:
        log.debug("homage-pending read failed", exc_info=True)
    transitions = current.get("transitions") if isinstance(current, dict) else None
    if not isinstance(transitions, list):
        transitions = []
    transitions.append(
        {
            "source_id": source_id,
            "transition": transition,
            "enqueued_at": now,
            "salience": max(0.0, min(1.0, float(salience))),
        }
    )
    payload = {"transitions": transitions, "updated_at": now}
    _atomic_write_json(_HOMAGE_PENDING, payload)


def dispatch_structural_intent(intent) -> dict[str, int]:
    """Fan a ``NarrativeStructuralIntent`` out to ward-properties + homage queue.

    Accepts either a ``NarrativeStructuralIntent`` instance or a plain
    dict (parser-legacy path). Returns a tally
    ``{"emphasized": N, "dispatched": N, "retired": N, "placed": N}`` for
    observability. Fail-open: import or parse errors are logged and the
    tally reflects what landed.

    Writes:
      * ward-properties.json (per emphasized + placed ward)
      * homage-pending-transitions.json (per dispatched + retired ward)

    Does NOT write ``homage_rotation_mode`` to the slow structural
    intent file — the narrative-tier per-tick override is surfaced
    separately at ``/dev/shm/hapax-compositor/narrative-structural-intent.json``
    so the choreographer can prefer the fresher signal without
    overwriting the structural director's long-horizon choice.
    """
    tally = {"emphasized": 0, "dispatched": 0, "retired": 0, "placed": 0}
    try:
        if hasattr(intent, "model_dump"):
            data = intent.model_dump()
        elif isinstance(intent, dict):
            data = intent
        else:
            return tally
    except Exception:
        log.debug("structural_intent: model_dump failed", exc_info=True)
        return tally

    # Publish the rotation-mode override for the choreographer. Atomic
    # so the choreographer never sees a half-written override.
    #
    # Write on EVERY call — even when ``homage_rotation_mode`` is None —
    # so the file's mtime + ``updated_at`` reflect actual director
    # cadence. The choreographer's ``_read_rotation_mode_from`` already
    # treats missing / unknown mode values as "no narrative override"
    # and falls through to the slow structural tier. Previously this
    # write was gated on a valid rotation_mode, which left the file
    # hours stale whenever the LLM emitted structural_intent without an
    # explicit rotation choice — operators reading file mtime could not
    # distinguish "director is silent" from "director ran but did not
    # override rotation this tick" (blinding-defaults-audit §3
    # ceremonial-defaults-2, expert-system-blinding-audit §5.1).
    rotation_mode = data.get("homage_rotation_mode")
    if not (
        isinstance(rotation_mode, str)
        and rotation_mode in ("sequential", "random", "weighted_by_salience", "paused")
    ):
        rotation_mode = None
    _atomic_write_json(
        Path("/dev/shm/hapax-compositor/narrative-structural-intent.json"),
        {
            "homage_rotation_mode": rotation_mode,
            "updated_at": time.time(),
        },
    )

    for ward_id in data.get("ward_emphasis") or []:
        if not isinstance(ward_id, str):
            continue
        _apply_emphasis(ward_id, salience=1.0)
        tally["emphasized"] += 1

    for ward_id in data.get("ward_dispatch") or []:
        if not isinstance(ward_id, str) or ward_id not in _VALID_WARD_IDS:
            continue
        # Default package entry transition — ticker-scroll-in under BitchX.
        _enqueue_homage_pending(ward_id, "ticker-scroll-in", salience=1.0)
        tally["dispatched"] += 1

    for ward_id in data.get("ward_retire") or []:
        if not isinstance(ward_id, str) or ward_id not in _VALID_WARD_IDS:
            continue
        _enqueue_homage_pending(ward_id, "ticker-scroll-out", salience=1.0)
        tally["retired"] += 1

    placement = data.get("placement_bias") or {}
    if isinstance(placement, dict):
        for ward_id, hint in placement.items():
            if not isinstance(ward_id, str) or not isinstance(hint, str):
                continue
            _apply_placement(ward_id, hint)
            tally["placed"] += 1

    _mark_recruitment("structural.intent", extra=tally)
    return tally


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
    "dispatch_structural_intent",
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
    "dispatch_composition_reframe",
    "dispatch_pace_tempo_shift",
    "dispatch_mood_tone_pivot",
    "dispatch_programme_beat_advance",
    "recent_recruitment_age_s",
]
