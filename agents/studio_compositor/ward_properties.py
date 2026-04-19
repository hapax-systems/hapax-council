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
import math
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
        if not needs_emphasis:
            return
        try:
            cr.pop_group_to_source()
            effective_alpha = max(0.0, min(1.0, props.alpha))
            if props.scale_bump_pct > 0.001 and canvas_w > 0 and canvas_h > 0:
                # Scale-bump renders the source content around its centre
                # without breaking the outer dimensions. push/pop
                # preserves the surface for the glow + border pass below.
                scale = 1.0 + max(0.0, min(0.5, float(props.scale_bump_pct)))
                cx = canvas_w * 0.5
                cy = canvas_h * 0.5
                cr.save()
                cr.translate(cx, cy)
                cr.scale(scale, scale)
                cr.translate(-cx, -cy)
                cr.paint_with_alpha(effective_alpha)
                cr.restore()
            else:
                cr.paint_with_alpha(effective_alpha)

            if canvas_w <= 0 or canvas_h <= 0:
                return
            # Radial glow — a soft emissive border that falls off toward
            # the ward's centre. Render-time only: we paint a strip along
            # each edge using cairo's radial gradient. Colour is taken
            # from glow_color_rgba so emphasis reads as warm identity,
            # not UI highlight.
            if props.glow_radius_px > 0.1:
                _paint_emissive_glow(
                    cr,
                    float(canvas_w),
                    float(canvas_h),
                    float(props.glow_radius_px),
                    props.glow_color_rgba,
                )
            # Border pulse — alpha-modulated rectangular stroke whose
            # opacity tracks a sinusoid at ``border_pulse_hz`` Hz. The
            # stroke radius is half the glow radius so the pulse rides
            # on top of the glow as a crisp edge.
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

    Implementation: four linear gradients (one per edge) where each
    gradient fades from the full accent colour (at the edge) to alpha=0
    at ``radius`` pixels in. The four gradients composite into an
    even glow without the geometric artefacts of a single radial
    gradient. Alpha-modulated by a slow sinusoid so the glow shimmers
    rather than sitting static — matches the HARDM aesthetic (never
    totally stable, precise yet diffuse).
    """
    import cairo as _c  # local import: helpers live outside hot test paths

    r = float(max(0.0, min(radius, min(w, h) * 0.5)))
    if r <= 0.1:
        return
    r_red, g, b, a_base = rgba
    # Slow shimmer — 0.30 Hz so the glow breathes rather than flickers.
    shimmer = 0.85 + 0.15 * math.sin(time.monotonic() * 2.0 * math.pi * 0.30)
    peak_alpha = float(max(0.0, min(1.0, a_base * 0.75 * shimmer)))

    def _edge(x0: float, y0: float, x1: float, y1: float, fx: float, fy: float) -> None:
        # Gradient axis goes from the edge inward by ``r`` px.
        grad = _c.LinearGradient(x0, y0, x0 + fx * r, y0 + fy * r)
        grad.add_color_stop_rgba(0.0, r_red, g, b, peak_alpha)
        grad.add_color_stop_rgba(1.0, r_red, g, b, 0.0)
        cr.save()
        cr.set_source(grad)
        # Rectangle along the edge, r px wide on the inward side.
        if fx != 0:  # left or right edge
            cr.rectangle(x0, y0, fx * r, y1 - y0)
        else:  # top or bottom edge
            cr.rectangle(x0, y0, x1 - x0, fy * r)
        cr.fill()
        cr.restore()

    # Top edge
    _edge(0.0, 0.0, w, 0.0, 0.0, 1.0)
    # Bottom edge
    _edge(0.0, h, w, h, 0.0, -1.0)
    # Left edge
    _edge(0.0, 0.0, 0.0, h, 1.0, 0.0)
    # Right edge
    _edge(w, 0.0, w, h, -1.0, 0.0)


def _paint_border_pulse(
    cr: Any,
    w: float,
    h: float,
    hz: float,
    rgba: tuple[float, float, float, float],
) -> None:
    """Stroke the ward's rectangular outline with a sinusoidally pulsing alpha.

    The pulse frequency is ``hz``; the baseline / amplitude are chosen so
    the border is always legibly present (min alpha 0.30) but visibly
    modulates (max alpha 1.00). Line width is 2 px for screen-clear
    visibility at 720p. No rounded corners — HOMAGE grammar refuses.
    """
    r, g, b, a_base = rgba
    phase = math.sin(time.monotonic() * 2.0 * math.pi * float(hz))
    pulse_alpha = 0.30 + 0.70 * (phase * 0.5 + 0.5)
    cr.save()
    cr.set_source_rgba(r, g, b, max(0.0, min(1.0, a_base * pulse_alpha)))
    cr.set_line_width(2.0)
    cr.rectangle(1.0, 1.0, max(0.0, w - 2.0), max(0.0, h - 2.0))
    cr.stroke()
    cr.restore()


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
