"""Ward property cache + SHM I/O — per-ward modulation surface.

The :class:`WardProperties` dataclass collects the nine modulation
dimensions (size, shape, appearance, highlighting, transitions, staging,
dynamism, movement, choreography) into one value object. The on-disk
format is a single JSON file at
``/dev/shm/hapax-compositor/ward-properties.json`` keyed by ward_id, with
``"all"`` as a fallback that ward-specific entries override.

Read path: :func:`resolve_ward_properties` is the hot-path entry. It
caches the parsed file with a 200ms TTL so a sub-2ms cairooverlay
callback can call it freely. Expired per-ward overrides (TTL-based) are
discarded at read time.

Write path: :func:`set_ward_properties` performs an atomic upsert
(tmp+rename, same idiom as ``compositional_consumer``). Writers are the
``ward.*`` dispatchers in :mod:`compositional_consumer`.

Render path (cascade-delta 2026-04-18, operator directive
"deeply felt and in-your-face impact"): :func:`ward_render_scope` wraps
every HOMAGE-participating Cairo source and now applies the emphasis
envelope (glow_radius_px, border_pulse_hz, scale_bump_pct) on top of
the source's content. Without this, structural-intent emphasis writes
to ward-properties.json were silently dropped at render time — the
surface still looked like "flat text-on-black rectangles" even when
the director was actively bumping emphasis every tick. The scope now
renders the source into a group, then overlays a radial glow + pulsing
border + optional scale bump, so emphasized wards visibly shimmer.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

WARD_PROPERTIES_PATH = Path("/dev/shm/hapax-compositor/ward-properties.json")

# Hot-path cache TTL — same as ``OverlayZoneManager._resolve_chrome_alpha``
# (200ms) so the cairooverlay synchronous draw callback stays under 2ms.
_CACHE_TTL_S = 0.2


@dataclass
class WardProperties:
    """Per-ward modulation envelope.

    Defaults are the no-op values: every property is "as if no override
    was set". The compositor's render path treats a ``WardProperties``
    instance as the merged view of (a) the ``"all"`` global fallback
    override, (b) the ward-specific override, (c) the active animation
    transitions for that ward.
    """

    # Visibility / staging
    visible: bool = True
    z_order_override: int | None = None

    # Highlighting (alpha is the existing chrome-dim mechanism extended
    # to a per-ward axis; glow + border_pulse + scale_bump add new
    # emphasis primitives the compositor's blit callback can apply).
    alpha: float = 1.0
    glow_radius_px: float = 0.0
    glow_color_rgba: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    border_pulse_hz: float = 0.0
    border_color_rgba: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    scale_bump_pct: float = 0.0  # 0.0 = no bump; 0.10 = 10% size pulse

    # Size / shape
    scale: float = 1.0
    border_radius_px: float = 0.0
    mask_kind: str | None = None  # e.g. "circle", "rounded-rect"; None = no mask

    # Movement
    position_offset_x: float = 0.0
    position_offset_y: float = 0.0
    drift_type: str = "none"  # "none" | "sine" | "circle"
    drift_hz: float = 0.0
    drift_amplitude_px: float = 0.0

    # Appearance
    color_override_rgba: tuple[float, float, float, float] | None = None
    typography_override: dict[str, Any] | None = None  # {font_family, font_size, font_weight}

    # Cadence
    rate_hz_override: float | None = None

    # Depth (z-plane stratification — see ``z_plane_constants._Z_INDEX_BASE``).
    # ``z_plane`` is the semantic category set by director / recruitment.
    # ``z_index_float`` is sub-plane position [0.0 far, 1.0 near] written by
    # the ward stimmung modulator. Both are read by ``fx_chain.blit_with_depth``.
    z_plane: str = "on-scrim"
    z_index_float: float = 0.5

    def merge_animation(self, animated: dict[str, float]) -> WardProperties:
        """Return a copy with animation-engine interpolated values applied.

        ``animated`` maps property names to floats. Only properties named
        in :data:`animation_engine.SUPPORTED_PROPERTIES` make sense here;
        unknown keys are silently ignored. Used by the Compile phase to
        fold per-frame transition values into the base override envelope.
        """
        merged = WardProperties(**asdict(self))
        valid = {f.name for f in fields(WardProperties)}
        for prop, value in animated.items():
            if prop in valid:
                setattr(merged, prop, value)
        return merged


@dataclass
class _CachedSnapshot:
    """One parsed snapshot of the ward-properties JSON file."""

    read_at: float
    by_ward: dict[str, WardProperties] = field(default_factory=dict)
    fallback_all: WardProperties = field(default_factory=WardProperties)


_cache: _CachedSnapshot | None = None


def resolve_ward_properties(ward_id: str) -> WardProperties:
    """Hot-path: return the merged property view for ``ward_id``.

    Reads the SHM file (cached 200ms), discards expired entries, returns
    the ward-specific entry if present, otherwise the ``"all"`` fallback,
    otherwise the default no-op ``WardProperties``. Specific entries are
    *full takes* — they don't merge with the fallback because the
    dataclass cannot distinguish "deliberately set to default" from "not
    specified". Operators wanting the all-fallback's modulation on a
    specific ward should not register a per-ward entry at all.

    Fail-open: any I/O or parse error returns the default no-op
    ``WardProperties()``.
    """
    snapshot = _refresh_cache_if_stale()
    specific = snapshot.by_ward.get(ward_id)
    if specific is not None:
        return specific
    return snapshot.fallback_all


def get_specific_ward_properties(ward_id: str) -> WardProperties | None:
    """Return the ward's specific override entry, or ``None`` if none exists.

    Distinct from :func:`resolve_ward_properties` in that it does NOT
    fall back to the ``"all"`` entry — useful for the dispatcher's
    read-modify-write path which must distinguish "no specific entry yet"
    (start from default) from "use the fallback values" (would
    contaminate the specific entry with fallback values that then
    survive the fallback's expiry).
    """
    snapshot = _refresh_cache_if_stale()
    return snapshot.by_ward.get(ward_id)


def all_resolved_properties() -> dict[str, WardProperties]:
    """Return a snapshot of every ward's resolved properties.

    Convenience for the Compile phase — lets it precompute one merged
    envelope per ward, then hand the per-ward result to the corresponding
    blit point so the streaming thread does no JSON I/O.
    """
    snapshot = _refresh_cache_if_stale()
    out: dict[str, WardProperties] = {}
    for ward_id, specific in snapshot.by_ward.items():
        out[ward_id] = specific
    return out


def set_ward_properties(
    ward_id: str,
    properties: WardProperties,
    ttl_s: float,
) -> None:
    """Atomic upsert of one ward's override entry.

    The override expires at ``time.time() + ttl_s``; expired entries are
    discarded by the next reader. Special key ``"all"`` is honored as a
    global fallback; ward-specific entries beat it on merge.

    The in-process cache is invalidated after the write so a follow-up
    :func:`resolve_ward_properties` call within the 200ms TTL window
    sees the new value. Without this, two dispatches against the same
    ward within 200ms would race: the second's read-modify-write would
    operate on a stale cached snapshot and silently drop the first
    write's fields.
    """
    if ttl_s <= 0:
        log.warning("set_ward_properties: ttl_s must be > 0, got %.3f", ttl_s)
        return
    try:
        WARD_PROPERTIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        current = _safe_load_raw()
        wards = current.get("wards") or {}
        wards[ward_id] = {
            **_dataclass_to_jsonable(properties),
            "expires_at": time.time() + ttl_s,
        }
        out = {"wards": wards, "updated_at": time.time()}
        tmp = WARD_PROPERTIES_PATH.with_suffix(WARD_PROPERTIES_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(out), encoding="utf-8")
        tmp.replace(WARD_PROPERTIES_PATH)
    except Exception:
        log.warning("set_ward_properties write failed for %s", ward_id, exc_info=True)
    finally:
        clear_ward_properties_cache()


def clear_ward_properties_cache() -> None:
    """Drop the in-process cache. Tests + any layout swap should call this."""
    global _cache
    _cache = None


@contextmanager
def ward_render_scope(cr: Any, ward_id: str, *, canvas_w: int = 0, canvas_h: int = 0):
    """Context manager that wraps a Cairo source's per-tick draw with ward modulation.

    Usage::

        with ward_render_scope(cr, "token_pole", canvas_w=w, canvas_h=h) as props:
            if props is None:
                return  # ward is hidden, skip the entire draw
            # ... normal drawing into ``cr`` ...

    Behavior:
    - Resolves the ward's properties (200ms cache).
    - If ``visible`` is false, yields ``None`` so the caller can short-
      circuit and the cairo surface stays transparent (the gst mixer
      composites nothing visible).
    - If any of {``alpha < 1.0``, ``glow_radius_px > 0``,
      ``border_pulse_hz > 0``, ``scale_bump_pct > 0``} the draw is
      wrapped in a Cairo group. On exit the group is popped back to
      source and composited with the alpha-modulated emphasis envelope:
      a radial glow border, a pulsing rectangular outline, and an
      optional scale-bump around the surface centre.
    - Otherwise yields ``props`` directly with no extra Cairo state.

    Cairo source authors call this once at the top of their
    ``render()`` to honor the dispatched per-ward properties without
    re-implementing the visibility + alpha plumbing each time. The
    ``canvas_w`` / ``canvas_h`` kwargs let the scope compute the border
    rectangle; callers that can't pass them (legacy sites) see a no-op
    border and only the alpha path runs — previous behaviour.
    """
    props = resolve_ward_properties(ward_id)
    if not props.visible:
        yield None
        return
    needs_emphasis = (
        props.alpha < 0.999
        or props.glow_radius_px > 0.1
        or props.border_pulse_hz > 0.01
        or props.scale_bump_pct > 0.001
    )
    if needs_emphasis:
        cr.push_group()
    try:
        yield props
    finally:
        if needs_emphasis:
            _finalize_ward_emphasis(cr, props, canvas_w, canvas_h)


def _finalize_ward_emphasis(
    cr: Any,
    props: WardProperties,
    canvas_w: int,
    canvas_h: int,
) -> None:
    """Pop the emphasis group and paint the composited overlay.

    Split out of :func:`ward_render_scope`'s ``finally`` block so
    exceptions raised inside the ``with`` body still propagate to the
    caller (Python's generator-based context manager re-raises from
    ``finally`` only when the finally itself doesn't swallow). Body
    exceptions must propagate for the compositor's error handling to
    see render crashes; at the same time, *emphasis overlay* failures
    must never cascade into the render path — hence the inner try.
    """
    try:
        cr.pop_group_to_source()
        effective_alpha = max(0.0, min(1.0, props.alpha))
        # 2026-04-23 operator "homage wards keep falling off the screen" —
        # scale_bump_pct was the culprit. Audio-kick / chain-swap / preset-
        # family-change events were pushing ward content up to 50% larger
        # around its centre, which punched surface edges past the 1920x1080
        # canvas intermittently. The scale_bump code path is disabled here;
        # upstream events (fx_chain_ward_reactor) continue to write
        # scale_bump_pct values but this painter ignores them. If a future
        # need reintroduces scale emphasis, it must clamp scale so the
        # transformed rect stays inside canvas_w × canvas_h at ALL times.
        cr.paint_with_alpha(effective_alpha)

        if canvas_w <= 0 or canvas_h <= 0:
            return
        if props.glow_radius_px > 0.1:
            _paint_emissive_glow(
                cr,
                float(canvas_w),
                float(canvas_h),
                float(props.glow_radius_px),
                props.glow_color_rgba,
            )
        if props.border_pulse_hz > 0.01:
            _paint_border_pulse(
                cr,
                float(canvas_w),
                float(canvas_h),
                float(props.border_pulse_hz),
                props.border_color_rgba,
            )
    except Exception:
        log.debug("ward_render_scope emphasis overlay failed", exc_info=True)


def _paint_emissive_glow(
    cr: Any,
    w: float,
    h: float,
    radius: float,
    rgba: tuple[float, float, float, float],
) -> None:
    """Paint a soft emissive glow along the ward's rectangular perimeter.

    2026-04-23 operator directive: zero container opacity. The
    four-edge glow halos gave each ward a visible container
    outline — chrome, not content. Retired. Emphasis flows through
    content primitives now (text weight, crop shift, fronting per
    the video-container epic). Signature preserved for back-compat.
    """
    _ = (cr, w, h, radius, rgba)  # params retained; unused


def _paint_border_pulse(
    cr: Any,
    w: float,
    h: float,
    hz: float,
    rgba: tuple[float, float, float, float],
) -> None:
    """Stroke the ward's rectangular outline.

    2026-04-23 operator directive: zero container opacity. The
    rectangular border stroke is chrome. Retired. Signature +
    ``hz`` parameter retained for back-compat so reactor callers
    don't need re-threading.
    """
    _ = (cr, w, h, hz, rgba)  # params retained; unused


# ── Internals ──────────────────────────────────────────────────────────────


def _refresh_cache_if_stale() -> _CachedSnapshot:
    global _cache
    now = time.monotonic()
    if _cache is not None and (now - _cache.read_at) < _CACHE_TTL_S:
        return _cache
    snapshot = _build_snapshot(now)
    _cache = snapshot
    return snapshot


def _build_snapshot(now_monotonic: float) -> _CachedSnapshot:
    snapshot = _CachedSnapshot(read_at=now_monotonic)
    raw = _safe_load_raw()
    wards = raw.get("wards") or {}
    if not isinstance(wards, dict):
        return snapshot
    now_wall = time.time()
    for ward_id, entry in wards.items():
        if not isinstance(entry, dict):
            continue
        expires_at = entry.get("expires_at")
        if isinstance(expires_at, (int, float)) and now_wall > float(expires_at):
            continue
        props = _dict_to_properties(entry)
        if ward_id == "all":
            snapshot.fallback_all = props
        else:
            snapshot.by_ward[ward_id] = props
    return snapshot


def _safe_load_raw() -> dict:
    try:
        if WARD_PROPERTIES_PATH.exists():
            return json.loads(WARD_PROPERTIES_PATH.read_text(encoding="utf-8"))
    except Exception:
        log.debug("ward-properties.json read failed", exc_info=True)
    return {}


def _dataclass_to_jsonable(props: WardProperties) -> dict:
    payload: dict[str, Any] = {}
    for f in fields(WardProperties):
        value = getattr(props, f.name)
        if isinstance(value, tuple):
            payload[f.name] = list(value)
        else:
            payload[f.name] = value
    return payload


def _dict_to_properties(entry: dict) -> WardProperties:
    """Tolerant constructor — unknown keys ignored, missing keys default."""
    kwargs: dict[str, Any] = {}
    valid_names = {f.name for f in fields(WardProperties)}
    for key, value in entry.items():
        if key not in valid_names:
            continue
        if (
            key in ("glow_color_rgba", "border_color_rgba")
            and isinstance(value, list)
            or key == "color_override_rgba"
            and isinstance(value, list)
        ):
            kwargs[key] = tuple(value)
        else:
            kwargs[key] = value
    try:
        return WardProperties(**kwargs)
    except TypeError:
        log.debug("invalid ward properties entry; using defaults", exc_info=True)
        return WardProperties()


__all__ = [
    "WARD_PROPERTIES_PATH",
    "WardProperties",
    "all_resolved_properties",
    "clear_ward_properties_cache",
    "resolve_ward_properties",
    "set_ward_properties",
    "ward_render_scope",
]
