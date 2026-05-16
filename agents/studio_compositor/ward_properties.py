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
import os
import threading
import time
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from itertools import count
from pathlib import Path
from typing import Any, Literal

from agents.studio_compositor.action_receipts import emit_action_receipt
from agents.studio_compositor.z_plane_constants import (
    DEFAULT_Z_INDEX_FLOAT,
    DEFAULT_Z_PLANE,
)
from shared.action_receipt import ActionReceiptStatus

log = logging.getLogger(__name__)

WARD_PROPERTIES_PATH = Path("/dev/shm/hapax-compositor/ward-properties.json")

# Hot-path cache TTL — same as ``OverlayZoneManager._resolve_chrome_alpha``
# (200ms) so the cairooverlay synchronous draw callback stays under 2ms.
_CACHE_TTL_S = 0.2

# Per-writer unique tmp suffix counter. Multiple threads within the same
# compositor process (modulator + fx_chain_ward_reactor + compositional
# consumers) would otherwise race on the single ``.tmp`` filename and
# silently lose writes when ``tmp.replace(dest)`` saw the source already
# consumed by a sibling writer's rename.
_TMP_SUFFIX_COUNTER = count()

# Serializes the full read-modify-write transaction in
# :func:`set_ward_properties`. Without it, two concurrent writers can both
# read the file with wards={} (say), each add their own ward entry, and
# have one rename clobber the other — the last writer's rename wins and
# the other writer's entry is silently lost. A threading.Lock suffices
# because all known writers (modulator, compositional_consumer,
# fx_chain_ward_reactor, dispatchers in compositor.py) run inside the
# single studio-compositor process.
_WRITE_LOCK = threading.Lock()


# Orphan ward IDs — entries that no current layout declares but that
# legacy producer code may still try to write. Per cc-task lssh-010
# (orphan-ward-cleanup), these clutter ``/dev/shm/.../ward-properties.json``
# without affecting broadcast — the compositor render path resolves
# property merges per layout-declared ward only, so orphan entries are
# inert noise that complicates debugging. We drop them at write time
# rather than at read time so the file on disk stays clean (a stale
# entry from a prior unfiltered process won't outlive the next write).
#
# Provenance:
# - vinyl_platter         — agents/studio_compositor/vinyl_platter.py
#                           writes property updates; layout omits it
#                           since the vinyl-image-as-HOMAGE rework.
# - objectives_overlay    — agents/studio_compositor/objective_hero_switcher.py
#                           writes; layout uses overlay-zones for
#                           objective surfacing.
# - music_candidate_surfacer — agents/studio_compositor/
#                           music_candidate_surfacer.py writes; surface
#                           was retired in favor of music_block writes.
# - scene_director        — metadata-only writer (not a CairoSource);
#                           no compositor render path consumes it.
# - structural_director   — metadata-only writer; SHM entry stale >1h
#                           in 2026-04-21 livestream-surface audit.
ORPHAN_WARD_IDS: frozenset[str] = frozenset(
    {
        "vinyl_platter",
        "objectives_overlay",
        "music_candidate_surfacer",
        "scene_director",
        "structural_director",
    }
)


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
    # Drift defaults give every ward subtle spatial life by default rather
    # than dead-static positioning. Director / recruitment / per-ward
    # overrides remain authoritative — these are the *fallback* when nothing
    # else has set a drift. Conservative numbers: 0.1 Hz = one full cycle
    # per 10s (slow enough not to be distracting), 3 px amplitude = visible
    # but small. Override per-ward via ``set_ward_properties`` to escalate
    # (e.g. compositional_consumer's "drift-sine-1hz" preset uses 12 px).
    drift_type: str = "sine"  # "none" | "sine" | "circle"
    drift_hz: float = 0.1
    drift_amplitude_px: float = 3.0

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

    # Video-container + mirror-emissive Phase 2 additions (2026-04-23).
    # These fields govern paired wards (video + emissive legs at the same
    # semantic slot). Solo wards ignore them — every field has a neutral
    # default that preserves legacy single-leg rendering.
    #
    # ``front_state`` is the pair-level lifecycle: whether the video leg
    # is behind the scrim (integrated), moving forward (fronting), fully
    # forward (fronted), or pulling back (retiring). The choreographer
    # writes transitions; the renderer reads to drive per-leg parallax +
    # scale envelopes.
    #
    # ``front_t0`` is the monotonic timestamp the current state entered,
    # so the renderer can compute an envelope progress curve without
    # reading wall-clock in the hot path.
    #
    # ``parallax_scalar_*`` scale the per-leg parallax response to the
    # audio / imagination depth signal. Defaults to 1.0 (full response).
    # The emissive leg often wants a larger scalar so the mirror moves
    # further when the video moves — exaggerating complementarity.
    #
    # ``crop_rect_override`` lets a programme re-crop the video leg
    # without touching the source schema — e.g., tightening the peephole
    # under deep scrim (nebulous-scrim §12.8). Normalised (x, y, w, h)
    # in [0, 1]²; None preserves the source's natural framing.
    front_state: Literal["integrated", "fronting", "fronted", "retiring"] = "integrated"
    front_t0: float = 0.0
    parallax_scalar_video: float = 1.0
    parallax_scalar_emissive: float = 1.0
    crop_rect_override: tuple[float, float, float, float] | None = None

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
    *,
    request_id: str | None = None,
    capability_name: str | None = None,
) -> bool:
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
    return set_many_ward_properties(
        {ward_id: properties},
        ttl_s=ttl_s,
        request_id=request_id,
        capability_name=capability_name or f"ward.properties.{ward_id}",
    )


def set_many_ward_properties(
    properties_by_ward: Mapping[str, WardProperties],
    ttl_s: float,
    *,
    request_id: str | None = None,
    capability_name: str = "ward.properties.batch",
) -> bool:
    """Atomic upsert of multiple ward override entries with one expiry.

    Multi-ward producers, especially FX preset-family pulses, need all
    affected wards to share the same expiration window. Calling
    :func:`set_ward_properties` in a loop computes one ``expires_at`` per
    ward; under CI or compositor load, early entries can expire before the
    last ward has even been written. This helper preserves the existing
    race-safe write semantics while committing the whole batch in one
    read-modify-write transaction.
    """
    if ttl_s <= 0:
        log.warning("set_many_ward_properties: ttl_s must be > 0, got %.3f", ttl_s)
        if request_id:
            emit_action_receipt(
                request_id=request_id,
                capability_name=capability_name,
                requested_action="set ward properties",
                status=ActionReceiptStatus.BLOCKED,
                family="ward.properties",
                command_ref="ward-properties:set-many",
                blocked_reasons=["invalid_ttl"],
            )
        return False
    filtered = {
        ward_id: properties
        for ward_id, properties in properties_by_ward.items()
        if ward_id not in ORPHAN_WARD_IDS
    }
    if not filtered:
        if request_id:
            emit_action_receipt(
                request_id=request_id,
                capability_name=capability_name,
                requested_action="set ward properties",
                status=ActionReceiptStatus.BLOCKED,
                family="ward.properties",
                command_ref="ward-properties:set-many",
                blocked_reasons=["no_non_orphan_ward_properties"],
            )
        return False
    with _WRITE_LOCK:
        try:
            WARD_PROPERTIES_PATH.parent.mkdir(parents=True, exist_ok=True)
            current = _safe_load_raw()
            wards = current.get("wards") or {}
            now = time.time()
            # Prune entries whose ``expires_at`` is in the past. The runtime
            # resolver already discards them at read time, but the on-disk
            # file accumulated stale entries indefinitely — operators
            # inspecting ``ward-properties.json`` for live state saw lies
            # (e.g. an entry from 37 hours ago overriding what the dataclass
            # default would actually produce at the next read). Pruning at
            # write keeps the disk view in sync with runtime semantics.
            # The z_plane / z_index_float preservation block below still
            # reads ``existing`` for the FRESH overlapping ward — pruning
            # only removes entries the resolver already wouldn't honor.
            wards = {
                wid: e
                for wid, e in wards.items()
                if isinstance(e, dict) and e.get("expires_at", 0) > now
            }
            expires_at = now + ttl_s
            # 2026-04-23 race-safe preservation of modulator-owned fields
            # (``z_plane`` + ``z_index_float``). The ``ward_stimmung_modulator``
            # writes these every ~200 ms from imagination depth; non-modulator
            # consumers (compositional_consumer, fx_chain_ward_reactor) use a
            # read-modify-write merge pattern whose cached read can go stale
            # between the modulator's write and the consumer's. Without this
            # preservation the consumer's stale-read ``z_plane`` (default
            # ``on-scrim``) silently clobbers the modulator's write, and wards
            # like sierpinski never leave the default plane. The heuristic:
            # if caller passes defaults AND disk already holds non-default
            # values, assume caller is round-tripping and preserve disk.
            # z_plane + z_index_float have no non-default callers outside
            # the modulator today (2026-04-23 grep), so this is a safe merge.
            for ward_id, properties in filtered.items():
                new_entry = {
                    **_dataclass_to_jsonable(properties),
                    "expires_at": expires_at,
                }
                existing = wards.get(ward_id)
                if existing is not None:
                    if (
                        new_entry.get("z_plane") == DEFAULT_Z_PLANE
                        and existing.get("z_plane", DEFAULT_Z_PLANE) != DEFAULT_Z_PLANE
                    ):
                        new_entry["z_plane"] = existing["z_plane"]
                    if (
                        new_entry.get("z_index_float") == DEFAULT_Z_INDEX_FLOAT
                        and existing.get("z_index_float", DEFAULT_Z_INDEX_FLOAT)
                        != DEFAULT_Z_INDEX_FLOAT
                    ):
                        new_entry["z_index_float"] = existing["z_index_float"]
                wards[ward_id] = new_entry
            out = {"wards": wards, "updated_at": now}
            # 2026-04-23 per-writer unique tmp suffix. Single shared ``.tmp``
            # filename loses writes when two concurrent callers
            # ``replace()`` the same source — the second caller's rename
            # raises ``FileNotFoundError`` because the first consumed it.
            # PID + monotonic counter keeps tmp names disjoint across
            # threads and processes, even without the ``_WRITE_LOCK``
            # (which also serializes the read-modify-write transaction).
            tmp_suffix = f".tmp.{os.getpid()}.{next(_TMP_SUFFIX_COUNTER)}"
            tmp = WARD_PROPERTIES_PATH.with_suffix(WARD_PROPERTIES_PATH.suffix + tmp_suffix)
            tmp.write_text(json.dumps(out), encoding="utf-8")
            tmp.replace(WARD_PROPERTIES_PATH)
            if request_id:
                emit_action_receipt(
                    request_id=request_id,
                    capability_name=capability_name,
                    requested_action="set ward properties",
                    status=ActionReceiptStatus.APPLIED,
                    family="ward.properties",
                    command_ref="ward-properties:set-many",
                    applied_refs=[f"shm:{WARD_PROPERTIES_PATH.name}"],
                )
            return True
        except Exception:
            log.warning("set_many_ward_properties write failed", exc_info=True)
            if request_id:
                emit_action_receipt(
                    request_id=request_id,
                    capability_name=capability_name,
                    requested_action="set ward properties",
                    status=ActionReceiptStatus.ERROR,
                    family="ward.properties",
                    command_ref="ward-properties:set-many",
                    error_refs=["ward_properties_write_failed"],
                )
            return False
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
    # ``scale_bump_pct`` deliberately omitted: ``_finalize_ward_emphasis``
    # ignores that field (canvas-safe scale clamp pending — see
    # ``_finalize_ward_emphasis`` below). Every audio kick writes a non-zero
    # scale_bump_pct on every audio-reactive ward; including it here would
    # wrap each ward's draw in a Cairo group push/pop per kick that the
    # finalizer no-ops anyway. Re-add this term when the safe-clamp scale
    # path is restored on the painter side.
    needs_emphasis = (
        props.alpha < 0.999 or props.glow_radius_px > 0.1 or props.border_pulse_hz > 0.01
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
    """Load ``ward-properties.json`` as a dict, or {} on any failure.

    Validates the JSON root is a mapping. A writer that produces valid
    JSON with a non-dict root (``null``, ``[...]``, a string, a number)
    previously propagated AttributeError up through ``_build_snapshot``
    into the Cairo render callback hot-path; the gate here keeps the
    contract the type signature promises and lets the cache fall back
    to defaults instead of crashing the source.
    """
    try:
        if WARD_PROPERTIES_PATH.exists():
            data = json.loads(WARD_PROPERTIES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            log.debug(
                "ward-properties.json root is %s, expected mapping",
                type(data).__name__,
            )
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


_TUPLE_FIELDS: frozenset[str] = frozenset(
    {
        "glow_color_rgba",
        "border_color_rgba",
        "color_override_rgba",
        # Phase 2 additions (2026-04-23) — crop_rect_override is the new
        # tuple-valued field and needs the same list→tuple coercion on
        # read-back as the colour fields. Future tuple fields belong here.
        "crop_rect_override",
    }
)


def _dict_to_properties(entry: dict) -> WardProperties:
    """Tolerant constructor — unknown keys ignored, missing keys default."""
    kwargs: dict[str, Any] = {}
    valid_names = {f.name for f in fields(WardProperties)}
    for key, value in entry.items():
        if key not in valid_names:
            continue
        if key in _TUPLE_FIELDS and isinstance(value, list):
            kwargs[key] = tuple(value)
        else:
            kwargs[key] = value
    try:
        return WardProperties(**kwargs)
    except TypeError:
        log.debug("invalid ward properties entry; using defaults", exc_info=True)
        return WardProperties()


__all__ = [
    "ORPHAN_WARD_IDS",
    "WARD_PROPERTIES_PATH",
    "WardProperties",
    "all_resolved_properties",
    "clear_ward_properties_cache",
    "resolve_ward_properties",
    "set_many_ward_properties",
    "set_ward_properties",
    "ward_render_scope",
]
