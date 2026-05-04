"""Hothouse Cairo sources — emissive rewrite (HOMAGE Phase A2).

Phase A2 of the homage-completion plan (Option A) recasts every hothouse
ward as an emissive surface. No flat-fill rectangles. No raw
``cairo.show_text``. Text flows through ``text_render.render_text``
(Pango + Px437 IBM VGA 8x16); dots, halos, and pulses come from
``homage.emissive_base``. Pressure gauge is now a row of 32 CP437 half-
block emissive cells, not a flat red bar. Impingement rows slide in via
``join-message`` with a ghost trail; activity log entries ticker-scroll
in/out; thinking indicator is a breathing point-of-light at stance-
indexed Hz.

Shared helpers (``_safe_load_json``, ``_active_perceptual_signals``,
``_infer_family``, ``_read_recent_intents``, the SHM paths) are
preserved — the legacy smoke tests pin their behaviour and they still
feed the emissive renderers below.

Surfaces:

- :class:`ImpingementCascadeCairoSource` — 480×360, row-stacked emissive
  signals with per-row slide-in and alpha-decay ghost trail.
- :class:`RecruitmentCandidatePanelCairoSource` — 800×60, three emissive
  cells for the last 3 recruitment families with width-modulated bars.
- :class:`ThinkingIndicatorCairoSource` — 170×44, breathing point-of-
  light + ``[thinking...]`` label when the LLM is in flight.
- :class:`PressureGaugeCairoSource` — 300×52, 32 CP437 half-block
  emissive cells with green→yellow→red interpolation + Px437 label.
- :class:`ActivityVarietyLogCairoSource` — 400×140, 6 emissive cells
  (name + intensity) with ticker-scroll motion.
- :class:`WhosHereCairoSource` — 230×46, Px437 ``[hapax:1/N]`` with the
  ``1`` and ``N`` rendered as emissive point-of-light glyphs.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import cairo

from agents.studio_compositor.homage.emissive_base import (
    BREATHING_AMPLITUDE,
    BREATHING_BASELINE,
    SHIMMER_HZ_DEFAULT,
    paint_breathing_alpha,
    paint_emissive_bg,
    paint_emissive_point,
    paint_emissive_stroke,
    paint_scanlines,
    stance_hz,
)
from agents.studio_compositor.homage.rendering import (
    active_package,
    paint_bitchx_bg,
    paint_bitchx_header,
    select_bitchx_font_pango,
)
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from agents.studio_compositor.text_render import TextStyle, measure_text, render_text

log = logging.getLogger(__name__)

_PERCEPTION_STATE = Path(os.path.expanduser("~/.cache/hapax-daimonion/perception-state.json"))
_STIMMUNG_STATE = Path("/dev/shm/hapax-stimmung/state.json")
_LLM_IN_FLIGHT = Path("/dev/shm/hapax-director/llm-in-flight.json")
_DIRECTOR_INTENT_JSONL = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/director-intent.jsonl")
)
_PRESENCE_STATE = Path(os.path.expanduser("~/.cache/hapax-daimonion/presence-state.json"))
_RECENT_RECRUITMENT = Path("/dev/shm/hapax-compositor/recent-recruitment.json")
_YOUTUBE_VIEWER_COUNT = Path("/dev/shm/hapax-compositor/youtube-viewer-count.txt")

_BRIGHT_FIELD_OUTLINE_OFFSETS_IDLE: tuple[tuple[int, int], ...] = (
    (-2, 0),
    (2, 0),
    (0, -2),
    (0, 2),
)

_BRIGHT_FIELD_OUTLINE_OFFSETS_ACTIVE: tuple[tuple[int, int], ...] = (
    (-3, 0),
    (3, 0),
    (0, -3),
    (0, 3),
    (-2, -2),
    (2, -2),
    (-2, 2),
    (2, 2),
)

# ── Shared readers ────────────────────────────────────────────────────────


def _safe_load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.debug("hothouse read %s failed", path, exc_info=True)
    return {}


def _read_stance() -> str:
    """Return the active director stance from stimmung, falling through to
    ``nominal`` on missing / malformed state. Used by wards to index
    ``STANCE_HZ`` for the shared breathing rate."""
    data = _safe_load_json(_STIMMUNG_STATE)
    stance = data.get("overall_stance") if isinstance(data, dict) else None
    if isinstance(stance, str):
        return stance.strip().lower() or "nominal"
    return "nominal"


# FINDING-V Phase 6: narrowed-salience impingement feed written by
# ``scripts/recent-impingements-producer.py``. Cascade consumer prefers
# this when present, falls back to ``_active_perceptual_signals`` when
# absent so a producer outage is zero-downtime.
_RECENT_IMPINGEMENTS = Path("/dev/shm/hapax-compositor/recent-impingements.json")
_RECENT_IMPINGEMENTS_MAX_AGE_S: float = 10.0


def _recent_impingements_overlay(limit: int) -> list[tuple[str, float, str]] | None:
    """Return the narrowed-salience impingement top-N, or ``None``.

    ``None`` means "producer is not publishing" — callers should fall
    back to the raw perception walk. Entries older than
    :data:`_RECENT_IMPINGEMENTS_MAX_AGE_S` are also treated as producer-
    down; cascade rendering stale "just grabbed my attention" signals
    would mis-represent Hapax's current focus.
    """
    data = _safe_load_json(_RECENT_IMPINGEMENTS)
    if not isinstance(data, dict):
        return None
    generated_at = data.get("generated_at")
    if isinstance(generated_at, (int, float)):
        if (time.time() - float(generated_at)) > _RECENT_IMPINGEMENTS_MAX_AGE_S:
            return None
    entries = data.get("entries")
    if not isinstance(entries, list):
        return None
    out: list[tuple[str, float, str]] = []
    for entry in entries[:limit]:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        value = entry.get("value")
        family = entry.get("family")
        if not isinstance(path, str) or not isinstance(value, (int, float)):
            continue
        out.append((path, float(value), str(family or "—")))
    if not out:
        return None
    return out


def _active_perceptual_signals(limit: int = 10) -> list[tuple[str, float, str]]:
    """Scan perception + stimmung state, return top-N signal/value/family triples.

    Unchanged contract from the legacy implementation so legacy smoke
    tests keep pinning it. Emissive wards below consume the tuple list
    directly.
    """
    signals: list[tuple[str, float, str]] = []
    perception = _safe_load_json(_PERCEPTION_STATE)
    stimmung = _safe_load_json(_STIMMUNG_STATE)

    def _walk(d: dict, prefix: str) -> None:
        for k, v in d.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                signals.append((path, float(v), _infer_family(path)))
            elif isinstance(v, bool) and v or isinstance(v, str) and v not in ("", "unknown"):
                signals.append((path, 1.0, _infer_family(path)))
            elif isinstance(v, dict):
                _walk(v, path)

    _walk(perception, "")
    dims = stimmung.get("dimensions") or {}
    if isinstance(dims, dict):
        for name, value in dims.items():
            reading = None
            if isinstance(value, (int, float)):
                reading = float(value)
            elif isinstance(value, dict):
                try:
                    reading = float(value.get("reading", 0.0))
                except (TypeError, ValueError):
                    pass
            if reading is not None:
                signals.append((f"stimmung.{name}", reading, "stimmung"))

    signals.sort(key=lambda s: abs(s[1]), reverse=True)
    return signals[:limit]


def _infer_family(path: str) -> str:
    lp = path.lower()
    if "hand" in lp or "gaze" in lp or "head" in lp or "face" in lp:
        return "camera.hero"
    if "album" in lp or "music" in lp or "beat" in lp or "midi" in lp:
        return "preset.bias"
    if "chat" in lp or "keyword" in lp:
        return "overlay.emphasis"
    if "youtube" in lp or "playlist" in lp:
        return "youtube.direction"
    if "attention" in lp or "salience" in lp:
        return "attention.winner"
    if "stream_mode" in lp or "consent" in lp:
        return "stream_mode.transition"
    return "—"


def _read_recent_intents(n: int) -> list[dict]:
    """Tail director-intent.jsonl for the last `n` records."""
    intents: list[dict] = []
    try:
        if not _DIRECTOR_INTENT_JSONL.exists():
            return intents
        size = _DIRECTOR_INTENT_JSONL.stat().st_size
        window = min(size, 16 * 1024)
        with _DIRECTOR_INTENT_JSONL.open("rb") as fh:
            fh.seek(max(0, size - window))
            tail = fh.read().decode("utf-8", errors="ignore")
        for line in tail.splitlines()[-n:]:
            if not line.strip():
                continue
            try:
                intents.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception:
        log.debug("recent-intents tail failed", exc_info=True)
    return intents


# ── Emissive palette helpers ─────────────────────────────────────────────


def _family_role(family: str) -> str:
    """Map a recruitment family → HomagePackage palette role.

    The families are roughly orthogonal: camera (hero) is presence
    (yellow), presets are musical (magenta), overlays are chat
    (green), youtube is attention-grabbing (cyan), stream-mode is
    warning (red). Unknown families fall through to ``bright``.
    """
    fl = family.lower()
    if "camera" in fl:
        return "accent_yellow"
    if "preset" in fl or "music" in fl:
        return "accent_magenta"
    if "overlay" in fl:
        return "accent_green"
    if "youtube" in fl or "playlist" in fl:
        return "accent_cyan"
    if "attention" in fl:
        return "accent_cyan"
    if "stream" in fl or "consent" in fl:
        return "accent_red"
    if "stimmung" in fl:
        return "accent_magenta"
    return "bright"


def _lerp_rgba(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    t: float,
) -> tuple[float, float, float, float]:
    """Linear interpolate between two RGBA tuples. ``t`` clamped to [0, 1]."""
    tt = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return (
        a[0] + (b[0] - a[0]) * tt,
        a[1] + (b[1] - a[1]) * tt,
        a[2] + (b[2] - a[2]) * tt,
        a[3] + (b[3] - a[3]) * tt,
    )


def _bright_field_outline(pkg: Any) -> tuple[float, float, float, float]:
    """Dark package ink used as content outline on bright shader fields."""
    r, g, b, _a = pkg.resolve_colour("background")
    return (r, g, b, 0.95)


# ── 1. Impingement cascade ───────────────────────────────────────────────


class ImpingementCascadeCairoSource(HomageTransitionalSource):
    """Emissive readout of top-N active perceptual signals.

    480×360 surface. Each row: ``* <id> [bar] → <accent>`` where:
    - ``*`` is a 4 px emissive centre dot in ``muted``;
    - ``<id>`` is Px437 13 px in ``bright``;
    - ``[bar]`` is 8 emissive points whose count is scaled by salience
      and whose hue is the family role's accent;
    - ``<accent>`` is the family-role name in the family's accent.

    Newest rows enter via ``join-message`` semantics — a slide-in and a
    ghost-trail alpha decay (rendered as a dim trailing halo to the
    left of each row's first dot). Older rows decay alpha over the
    5-second lifetime window.

    **Performance (F14 audit):** signal data updates at director cadence
    (30-90s) but render is called every frame (~30fps). A content-hash
    cache stores the rendered surface and only re-renders when signal
    data or stance changes. Between changes, the cached surface is
    blitted in <1ms instead of spending ~112ms on full text layout +
    emissive point rendering.
    """

    _LIFETIME_S: float = 5.0
    _N_BAR_CELLS: int = 8

    def __init__(self) -> None:
        super().__init__(source_id="impingement_cascade")
        self._cached_surface: cairo.ImageSurface | None = None
        self._cached_hash: str = ""
        self._cached_w: int = 0
        self._cached_h: int = 0

    @staticmethod
    def _content_hash(
        signals: list[tuple[str, float, str]],
        stance: str,
    ) -> str:
        """Fast content hash from signal paths + values + stance.

        Only hashes the data that drives visual output. Avoids hashing
        the full JSON — just the sorted (path, rounded_value, family)
        tuples plus stance. Rounding values to 2 decimal places avoids
        cache thrashing on float jitter.
        """
        parts = [stance]
        for path, value, family in signals:
            parts.append(f"{path}:{value:.2f}:{family}")
        return "|".join(parts)

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        import cairo as _cairo

        pkg = active_package()
        stance = _read_stance()

        # Read signal data (the slow filesystem part).
        overlay = _recent_impingements_overlay(limit=14)
        signals = overlay if overlay is not None else _active_perceptual_signals(limit=14)

        # Content-hash cache: only re-render when data changes.
        content_hash = self._content_hash(signals, stance)
        if (
            content_hash == self._cached_hash
            and self._cached_surface is not None
            and self._cached_w == canvas_w
            and self._cached_h == canvas_h
        ):
            # Blit cached surface — fast path (<1ms).
            cr.set_source_surface(self._cached_surface, 0, 0)
            cr.paint()
            return

        # Full render — only runs when content changes.
        cache_surface = _cairo.ImageSurface(_cairo.FORMAT_ARGB32, canvas_w, canvas_h)
        cache_cr = _cairo.Context(cache_surface)

        paint_emissive_bg(cache_cr, canvas_w, canvas_h)
        paint_bitchx_bg(cache_cr, canvas_w, canvas_h, pkg, ward_id=self._source_id)
        paint_bitchx_header(cache_cr, "IMPINGEMENT", pkg, accent_role="accent_cyan", y=14.0, x=8.0)
        paint_scanlines(
            cache_cr,
            canvas_w,
            canvas_h,
            role_rgba=pkg.resolve_colour("muted"),
            every_n_rows=4,
            alpha=0.06,
            row_height_px=16.0,
        )

        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")
        hz = stance_hz(stance)

        row_h = 20
        y0 = 34
        font_desc = select_bitchx_font_pango(cache_cr, 11, bold=False)
        for idx, (path, value, family) in enumerate(signals):
            y = y0 + idx * row_h
            if y + row_h > canvas_h:
                break

            # Per-row lifetime: newest row is 0 s old, each older row
            # adds a synthetic age so the ghost trail reads correctly.
            age_s = idx * (self._LIFETIME_S / max(1, len(signals)))
            lifetime_alpha = max(0.25, 1.0 - age_s / self._LIFETIME_S)
            phase = idx * 0.31

            role = _family_role(family)
            try:
                accent_rgba = pkg.resolve_colour(role)
            except Exception:
                accent_rgba = bright

            # ``*`` centre dot (muted) with ghost trail — the ghost is a
            # second dim point to the left, alpha scaled by lifetime.
            paint_emissive_point(
                cache_cr,
                cx=12.0,
                cy=y + 6.0,
                role_rgba=muted,
                t=t,
                phase=phase,
                baseline_alpha=lifetime_alpha,
                centre_radius_px=2.0,
                halo_radius_px=5.0,
                outer_glow_radius_px=7.0,
                shimmer_hz=hz * SHIMMER_HZ_DEFAULT,
            )
            if idx == 0:
                # Join-message slide-in ghost for the newest row only —
                # a faint trailing dot suggesting arrival from the left.
                paint_emissive_point(
                    cache_cr,
                    cx=4.0,
                    cy=y + 6.0,
                    role_rgba=muted,
                    t=t,
                    phase=phase + math.pi / 3.0,
                    baseline_alpha=0.35,
                    centre_radius_px=1.2,
                    halo_radius_px=3.5,
                    outer_glow_radius_px=5.0,
                    shimmer_hz=hz * SHIMMER_HZ_DEFAULT,
                )

            # Signal id — Px437 bright.
            id_text = path[:26]
            id_style = TextStyle(
                text=id_text,
                font_description=font_desc,
                color_rgba=(bright[0], bright[1], bright[2], bright[3] * lifetime_alpha),
            )
            render_text(cache_cr, id_style, x=24.0, y=y - 2.0)

            # Salience bar — N emissive points, filled per |value|.
            filled = int(min(1.0, abs(value)) * self._N_BAR_CELLS)
            bar_x0 = 220.0
            for i in range(self._N_BAR_CELLS):
                is_filled = i < filled
                bar_role = accent_rgba if is_filled else muted
                paint_emissive_point(
                    cache_cr,
                    cx=bar_x0 + i * 12.0,
                    cy=y + 6.0,
                    role_rgba=bar_role,
                    t=t,
                    phase=phase + i * 0.19,
                    baseline_alpha=lifetime_alpha if is_filled else 0.45 * lifetime_alpha,
                    centre_radius_px=1.5,
                    halo_radius_px=3.8,
                    outer_glow_radius_px=5.0,
                    shimmer_hz=hz * SHIMMER_HZ_DEFAULT,
                )

            # Family accent label — right-aligned, Px437 in accent.
            family_style = TextStyle(
                text=family,
                font_description=font_desc,
                color_rgba=(
                    accent_rgba[0],
                    accent_rgba[1],
                    accent_rgba[2],
                    accent_rgba[3] * lifetime_alpha,
                ),
            )
            render_text(
                cache_cr, family_style, x=bar_x0 + self._N_BAR_CELLS * 12.0 + 10.0, y=y - 2.0
            )

        cache_surface.flush()

        # Store cache and blit to output.
        self._cached_surface = cache_surface
        self._cached_hash = content_hash
        self._cached_w = canvas_w
        self._cached_h = canvas_h

        cr.set_source_surface(cache_surface, 0, 0)
        cr.paint()


# ── 2. Recruitment candidate panel ───────────────────────────────────────


class RecruitmentCandidatePanelCairoSource(HomageTransitionalSource):
    """Last-3 recruitments as three emissive cells.

    800×60 surface. Each cell: Px437 family label in the family's accent
    role + a width-modulated bar of emissive points (recency drives bar
    width). Ticker-scroll-in entry on the newest cell via a per-cell
    phase offset.
    """

    _N_CELLS: int = 3
    _BAR_POINTS: int = 16

    def __init__(self) -> None:
        super().__init__(source_id="recruitment_candidate_panel")

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pkg = active_package()
        paint_emissive_bg(cr, canvas_w, canvas_h)
        paint_bitchx_bg(cr, canvas_w, canvas_h, pkg, ward_id=self._source_id)
        paint_bitchx_header(cr, "RECRUIT", pkg, accent_role="accent_green", y=14.0, x=8.0)

        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")
        stance = _read_stance()
        hz = stance_hz(stance)

        items: list[tuple[str, float, float]] = []
        try:
            recent_path = _RECENT_RECRUITMENT
            if recent_path.exists():
                raw = json.loads(recent_path.read_text(encoding="utf-8"))
                now = time.time()
                for family_name, detail in (raw.get("families") or {}).items():
                    if not isinstance(detail, dict):
                        continue
                    last = float(detail.get("last_recruited_ts") or 0.0)
                    if last <= 0:
                        continue
                    age = now - last
                    extras: list[str] = []
                    if "family" in detail and detail["family"]:
                        extras.append(str(detail["family"]))
                    if "pending_source" in detail and detail["pending_source"]:
                        extras.append(str(detail["pending_source"]))
                    suffix = f" [{', '.join(extras)}]" if extras else ""
                    label = f"{family_name}{suffix}"
                    items.append((label, age, last))
                items.sort(key=lambda entry: entry[2], reverse=True)
                items = items[: self._N_CELLS]
        except Exception:
            items = []

        cell_w = (canvas_w - 16.0) / self._N_CELLS
        font_desc = select_bitchx_font_pango(cr, 11, bold=False)

        if not items:
            empty_style = TextStyle(
                text="(no recent recruitments)",
                font_description=font_desc,
                color_rgba=muted,
            )
            render_text(cr, empty_style, x=8.0, y=32.0)
            return

        for i, (label, age_s, _last) in enumerate(items):
            cx0 = 8.0 + i * cell_w
            cy_center = 32.0
            phase = i * 0.47

            # Family name token at left of the cell, in family accent.
            family_token = label.split()[0] if label else "—"
            role = _family_role(family_token)
            try:
                accent_rgba = pkg.resolve_colour(role)
            except Exception:
                accent_rgba = bright

            # Point-of-light marker at cell start.
            paint_emissive_point(
                cr,
                cx=cx0 + 4.0,
                cy=cy_center,
                role_rgba=accent_rgba,
                t=t,
                phase=phase,
                baseline_alpha=1.0,
                centre_radius_px=2.2,
                halo_radius_px=5.5,
                outer_glow_radius_px=8.0,
                shimmer_hz=hz * SHIMMER_HZ_DEFAULT,
            )

            # Family label.
            label_style = TextStyle(
                text=label[:22],
                font_description=font_desc,
                color_rgba=accent_rgba,
            )
            render_text(cr, label_style, x=cx0 + 14.0, y=cy_center - 10.0)

            # Age-as-width bar: fewer points = fresher (stronger salience).
            # Newer recruitments (small age) show more cells lit.
            recency = max(0.0, 1.0 - min(age_s, 60.0) / 60.0)
            filled = int(recency * self._BAR_POINTS)
            bar_y = cy_center + 10.0
            for j in range(self._BAR_POINTS):
                is_filled = j < filled
                pt_role = accent_rgba if is_filled else muted
                paint_emissive_point(
                    cr,
                    cx=cx0 + 14.0 + j * 8.0,
                    cy=bar_y,
                    role_rgba=pt_role,
                    t=t,
                    phase=phase + j * 0.11,
                    baseline_alpha=1.0 if is_filled else 0.35,
                    centre_radius_px=1.4,
                    halo_radius_px=3.2,
                    outer_glow_radius_px=4.5,
                    shimmer_hz=hz * SHIMMER_HZ_DEFAULT,
                )

            # Age tail — right-edge Px437.
            age_style = TextStyle(
                text=f"{int(age_s)}s",
                font_description=font_desc,
                color_rgba=muted,
            )
            render_text(cr, age_style, x=cx0 + cell_w - 28.0, y=cy_center - 10.0)


# ── 3. Thinking indicator ────────────────────────────────────────────────


class ThinkingIndicatorCairoSource(HomageTransitionalSource):
    """Breathing point-of-light + ``[thinking...]`` label when LLM is in flight.

    170×44 surface. Idle: a dim muted dot at the left edge. In flight:
    the dot brightens and pulses at stance-indexed Hz, and the
    ``[thinking...]`` label fades in beside it in Px437 bright.
    """

    def __init__(self) -> None:
        super().__init__(source_id="thinking_indicator")

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pkg = active_package()
        paint_emissive_bg(cr, canvas_w, canvas_h)
        paint_bitchx_bg(cr, canvas_w, canvas_h, pkg, ward_id=self._source_id)

        info = _safe_load_json(_LLM_IN_FLIGHT)
        active = bool(info)
        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")
        accent_cyan = pkg.resolve_colour("accent_cyan")
        outline = _bright_field_outline(pkg)
        stance = _read_stance()
        hz = stance_hz(stance)

        cy = canvas_h / 2.0
        if active:
            # In flight: amplified breathing alpha + accent colour.
            amp_alpha = paint_breathing_alpha(
                t,
                hz=hz,
                baseline=BREATHING_BASELINE,
                amplitude=BREATHING_AMPLITUDE * 1.8,
            )
            paint_emissive_point(
                cr,
                cx=14.0,
                cy=cy,
                role_rgba=accent_cyan,
                t=t,
                phase=0.0,
                baseline_alpha=amp_alpha,
                centre_radius_px=3.2,
                halo_radius_px=9.0,
                outer_glow_radius_px=13.0,
                shimmer_hz=hz,
                outline_rgba=outline,
                outline_radius_px=14.0,
            )
            # Label fade-in — alpha tracks the breathing amplitude.
            elapsed = max(0.0, time.time() - float(info.get("started_at") or time.time()))
            model = str(info.get("model") or "?")
            font_desc = select_bitchx_font_pango(cr, 12, bold=True)
            label_style = TextStyle(
                text=f"[thinking...] {model} {elapsed:.1f}s",
                font_description=font_desc,
                color_rgba=(bright[0], bright[1], bright[2], bright[3] * amp_alpha),
                outline_color_rgba=outline,
                outline_offsets=_BRIGHT_FIELD_OUTLINE_OFFSETS_ACTIVE,
            )
            render_text(cr, label_style, x=30.0, y=cy - 8.0)
        else:
            # Idle: a dim muted breathing point.
            paint_emissive_point(
                cr,
                cx=14.0,
                cy=cy,
                role_rgba=muted,
                t=t,
                phase=0.0,
                baseline_alpha=0.55,
                centre_radius_px=2.0,
                halo_radius_px=5.5,
                outer_glow_radius_px=8.0,
                shimmer_hz=hz,
                outline_rgba=outline,
                outline_radius_px=6.0,
            )
            font_desc = select_bitchx_font_pango(cr, 11, bold=False)
            idle_style = TextStyle(
                text="(idle)",
                font_description=font_desc,
                color_rgba=muted,
                outline_color_rgba=outline,
                outline_offsets=_BRIGHT_FIELD_OUTLINE_OFFSETS_IDLE,
            )
            render_text(cr, idle_style, x=30.0, y=cy - 8.0)


# ── 4. Pressure gauge ────────────────────────────────────────────────────


class PressureGaugeCairoSource(HomageTransitionalSource):
    """Row of 32 CP437 half-block emissive cells driven by pressure saturation.

    300×52 surface. Each cell is a centre dot + halo via
    ``paint_emissive_point``; hue interpolates green → yellow → red by
    cell fill. Label ``>>> [PRESSURE | <count>/<saturation%>]`` in Px437
    above the cells.
    """

    _SIGNIFICANT_MAGNITUDE = 0.35
    _GAUGE_MAX = 12.0
    _N_CELLS: int = 32

    def __init__(self) -> None:
        super().__init__(source_id="pressure_gauge")

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pkg = active_package()
        paint_emissive_bg(cr, canvas_w, canvas_h)
        paint_bitchx_bg(cr, canvas_w, canvas_h, pkg, ward_id=self._source_id)

        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")
        accent_green = pkg.resolve_colour("accent_green")
        accent_yellow = pkg.resolve_colour("accent_yellow")
        accent_red = pkg.resolve_colour("accent_red")
        stance = _read_stance()
        hz = stance_hz(stance)

        signals = _active_perceptual_signals(limit=30)
        n_active = sum(1 for _, value, _ in signals if abs(value) >= self._SIGNIFICANT_MAGNITUDE)
        saturation = min(1.0, n_active / self._GAUGE_MAX)
        filled_cells = int(saturation * self._N_CELLS)

        # Label row — Px437, chevron-prefixed BitchX form.
        font_desc_hdr = select_bitchx_font_pango(cr, 11, bold=True)
        label_style = TextStyle(
            text=f">>> [PRESSURE | {n_active}/{int(saturation * 100)}%]",
            font_description=font_desc_hdr,
            color_rgba=muted,
        )
        render_text(cr, label_style, x=8.0, y=4.0)

        # 32 CP437 half-block cells — green→yellow→red interpolation by
        # cell fill across the row. Unfilled cells render as muted dim
        # dots so the row still reads as a full gauge even near zero.
        cells_y = 32.0
        inner_w = canvas_w - 16.0
        step = inner_w / self._N_CELLS
        for i in range(self._N_CELLS):
            is_filled = i < filled_cells
            # Hue interpolation along the full row — fill position, not
            # per-cell saturation.
            cell_t = i / max(1, self._N_CELLS - 1)
            if cell_t < 0.5:
                cell_rgba = _lerp_rgba(accent_green, accent_yellow, cell_t * 2.0)
            else:
                cell_rgba = _lerp_rgba(accent_yellow, accent_red, (cell_t - 0.5) * 2.0)

            if is_filled:
                role_rgba = cell_rgba
                baseline_alpha = 1.0
            else:
                role_rgba = muted
                baseline_alpha = 0.35

            paint_emissive_point(
                cr,
                cx=8.0 + step * (i + 0.5),
                cy=cells_y,
                role_rgba=role_rgba,
                t=t,
                phase=i * 0.13,
                baseline_alpha=baseline_alpha,
                centre_radius_px=1.7,
                halo_radius_px=4.0,
                outer_glow_radius_px=5.5,
                shimmer_hz=hz * SHIMMER_HZ_DEFAULT,
            )

        # Baseline glow-stroke under the cell row — ties the 32 cells
        # together visually so the row reads as a gauge, not loose dots.
        if filled_cells > 0:
            fill_frac = filled_cells / self._N_CELLS
            if fill_frac < 0.5:
                tail_rgba = _lerp_rgba(accent_green, accent_yellow, fill_frac * 2.0)
            else:
                tail_rgba = _lerp_rgba(accent_yellow, accent_red, (fill_frac - 0.5) * 2.0)
            paint_emissive_stroke(
                cr,
                x0=8.0,
                y0=cells_y + 6.0,
                x1=8.0 + step * filled_cells,
                y1=cells_y + 6.0,
                role_rgba=tail_rgba,
                t=t,
                phase=0.0,
                baseline_alpha=0.55,
                width_px=1.5,
                glow_width_mult=2.2,
                glow_alpha_mult=0.35,
                shimmer_hz=hz * SHIMMER_HZ_DEFAULT,
            )

        # Tail row — count/saturation stats, right-aligned.
        font_desc = select_bitchx_font_pango(cr, 10, bold=False)
        stats_style = TextStyle(
            text=f"{n_active} active · {saturation:.0%} saturated",
            font_description=font_desc,
            color_rgba=bright,
        )
        render_text(cr, stats_style, x=8.0, y=canvas_h - 14.0)


# ── 5. Activity variety log ──────────────────────────────────────────────


class ActivityVarietyLogCairoSource(HomageTransitionalSource):
    """Horizontal stack of 6 emissive name+intensity cells.

    400×140 surface. Newest entries ticker-scroll in from the right;
    oldest ticker-scroll out to the left. Cells render the activity
    name in Px437 + an emissive intensity bar (age-damped).
    """

    _WINDOW_S = 180.0
    _N_CELLS: int = 6
    _INTENSITY_POINTS: int = 6

    def __init__(self) -> None:
        super().__init__(source_id="activity_variety_log")

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pkg = active_package()
        paint_emissive_bg(cr, canvas_w, canvas_h)
        paint_bitchx_bg(cr, canvas_w, canvas_h, pkg, ward_id=self._source_id)
        paint_bitchx_header(cr, "ACTIVITY", pkg, accent_role="accent_cyan", y=14.0, x=8.0)
        paint_scanlines(
            cr,
            canvas_w,
            canvas_h,
            role_rgba=pkg.resolve_colour("muted"),
            every_n_rows=6,
            alpha=0.06,
            row_height_px=16.0,
        )

        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")
        stance = _read_stance()
        hz = stance_hz(stance)

        intents = _read_recent_intents(n=16)
        now = time.time()
        deduped: list[dict] = []
        for intent in intents:
            if deduped and deduped[-1].get("activity") == intent.get("activity"):
                continue
            deduped.append(intent)
        # Keep newest-first layout: newest rightmost cell.
        recent = deduped[-self._N_CELLS :]

        font_desc = select_bitchx_font_pango(cr, 10, bold=False)
        cell_w = (canvas_w - 16.0) / self._N_CELLS

        for idx, intent in enumerate(recent):
            # Oldest on left (idx=0), newest on right.
            cx0 = 8.0 + idx * cell_w
            cy_center = canvas_h / 2.0 + 8.0
            activity = str(intent.get("activity") or "—")
            emitted = float(intent.get("emitted_at") or now)
            age = max(0.0, now - emitted)
            if age > self._WINDOW_S:
                age_alpha = 0.25
            else:
                age_alpha = max(0.3, 1.0 - (age / self._WINDOW_S) * 0.7)
            phase = idx * 0.29
            is_newest = idx == len(recent) - 1

            # Accent role: newest gets bright, older get muted-blend.
            role = "accent_green" if is_newest else "muted"
            try:
                pt_rgba = pkg.resolve_colour(role)
            except Exception:
                pt_rgba = bright

            # Leading point-of-light marker.
            paint_emissive_point(
                cr,
                cx=cx0 + 4.0,
                cy=cy_center,
                role_rgba=pt_rgba,
                t=t,
                phase=phase,
                baseline_alpha=age_alpha,
                centre_radius_px=2.2,
                halo_radius_px=5.5,
                outer_glow_radius_px=7.5,
                shimmer_hz=hz * SHIMMER_HZ_DEFAULT,
            )

            # Activity name label.
            name_style = TextStyle(
                text=activity[:12],
                font_description=font_desc,
                color_rgba=(bright[0], bright[1], bright[2], bright[3] * age_alpha),
            )
            render_text(cr, name_style, x=cx0 + 14.0, y=cy_center - 18.0)

            # Intensity bar — N points, filled by 1.0 - age_fraction.
            intensity = max(0.0, 1.0 - age / self._WINDOW_S)
            filled = int(intensity * self._INTENSITY_POINTS)
            for j in range(self._INTENSITY_POINTS):
                is_filled = j < filled
                bar_rgba = pt_rgba if is_filled else muted
                paint_emissive_point(
                    cr,
                    cx=cx0 + 14.0 + j * 9.0,
                    cy=cy_center + 4.0,
                    role_rgba=bar_rgba,
                    t=t,
                    phase=phase + j * 0.17,
                    baseline_alpha=age_alpha if is_filled else 0.35 * age_alpha,
                    centre_radius_px=1.4,
                    halo_radius_px=3.2,
                    outer_glow_radius_px=4.5,
                    shimmer_hz=hz * SHIMMER_HZ_DEFAULT,
                )

            # Age tail.
            age_style = TextStyle(
                text=f"{int(age)}s",
                font_description=font_desc,
                color_rgba=(muted[0], muted[1], muted[2], muted[3] * age_alpha),
            )
            render_text(cr, age_style, x=cx0 + 14.0, y=cy_center + 14.0)


# ── 6. Who's here indicator ──────────────────────────────────────────────


class WhosHereCairoSource(HomageTransitionalSource):
    """Px437 ``[hapax:1/N]`` with the ``1`` and ``N`` as emissive glyphs.

    230×46 surface. The ``1`` takes the stance colour (green/yellow/
    muted/red) and the ``N`` takes the audience colour (bright cyan
    when viewers present; muted otherwise).
    """

    def __init__(self) -> None:
        super().__init__(source_id="whos_here")

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pkg = active_package()
        paint_emissive_bg(cr, canvas_w, canvas_h)
        paint_bitchx_bg(cr, canvas_w, canvas_h, pkg, ward_id=self._source_id)

        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")
        accent_cyan = pkg.resolve_colour("accent_cyan")

        presence = _safe_load_json(_PRESENCE_STATE)
        presence_state = str(presence.get("state") or "PRESENT").upper()

        external = 0
        try:
            if _YOUTUBE_VIEWER_COUNT.exists():
                external = int(_YOUTUBE_VIEWER_COUNT.read_text().strip() or "0")
        except Exception:
            external = 0

        stance = _read_stance()
        hz = stance_hz(stance)

        stance_rgba = {
            "PRESENT": pkg.resolve_colour("accent_green"),
            "UNCERTAIN": pkg.resolve_colour("accent_yellow"),
        }.get(presence_state, muted)
        audience_rgba = accent_cyan if external > 0 else muted

        # Header line: ``[hapax:``, then the 1 as emissive glyph, then
        # ``/``, then the N as emissive glyph, then ``]``.
        cy = canvas_h / 2.0 + 2.0
        font_desc = select_bitchx_font_pango(cr, 14, bold=True)

        prefix_style = TextStyle(
            text="[hapax:",
            font_description=font_desc,
            color_rgba=muted,
        )
        w_prefix, _ = measure_text(cr, prefix_style)
        render_text(cr, prefix_style, x=8.0, y=cy - 12.0)

        # Stance "1" — point-of-light halo underneath, text over.
        x_one = 8.0 + w_prefix
        paint_emissive_point(
            cr,
            cx=x_one + 6.0,
            cy=cy - 4.0,
            role_rgba=stance_rgba,
            t=t,
            phase=0.0,
            baseline_alpha=1.0,
            centre_radius_px=2.0,
            halo_radius_px=7.0,
            outer_glow_radius_px=10.0,
            shimmer_hz=hz,
        )
        one_style = TextStyle(
            text="1",
            font_description=font_desc,
            color_rgba=(stance_rgba[0], stance_rgba[1], stance_rgba[2], stance_rgba[3]),
        )
        w_one, _ = measure_text(cr, one_style)
        render_text(cr, one_style, x=x_one, y=cy - 12.0)

        # Slash separator.
        x_slash = x_one + w_one
        slash_style = TextStyle(text="/", font_description=font_desc, color_rgba=muted)
        w_slash, _ = measure_text(cr, slash_style)
        render_text(cr, slash_style, x=x_slash, y=cy - 12.0)

        # Audience "N" — point-of-light halo + text. N = 1 + external.
        x_n = x_slash + w_slash
        n_text = str(1 + external)
        paint_emissive_point(
            cr,
            cx=x_n + 6.0,
            cy=cy - 4.0,
            role_rgba=audience_rgba,
            t=t,
            phase=math.pi / 3.0,
            baseline_alpha=1.0,
            centre_radius_px=2.0,
            halo_radius_px=7.0,
            outer_glow_radius_px=10.0,
            shimmer_hz=hz,
        )
        n_style = TextStyle(
            text=n_text,
            font_description=font_desc,
            color_rgba=(audience_rgba[0], audience_rgba[1], audience_rgba[2], audience_rgba[3]),
        )
        w_n, _ = measure_text(cr, n_style)
        render_text(cr, n_style, x=x_n, y=cy - 12.0)

        # Closing bracket.
        x_close = x_n + w_n
        close_style = TextStyle(text="]", font_description=font_desc, color_rgba=muted)
        render_text(cr, close_style, x=x_close, y=cy - 12.0)

        # Presence-state sub-label.
        sub_font = select_bitchx_font_pango(cr, 10, bold=False)
        sub_style = TextStyle(
            text=f"{presence_state.lower()} · {external} viewers",
            font_description=sub_font,
            color_rgba=(bright[0], bright[1], bright[2], bright[3] * 0.6),
        )
        render_text(cr, sub_style, x=8.0, y=cy + 8.0)


__all__ = [
    "ActivityVarietyLogCairoSource",
    "ImpingementCascadeCairoSource",
    "PressureGaugeCairoSource",
    "RecruitmentCandidatePanelCairoSource",
    "ThinkingIndicatorCairoSource",
    "WhosHereCairoSource",
]
