"""Hothouse Cairo sources — pressure + recruitment visibility on every frame.

Phase C of the Epic-2 hothouse plan (2026-04-17). Direct operator directive:

    "no evidence of director / no variety or changes / evidence of
    directorial/host nature and presence should be unavoidable / there
    should be evidence of ALL recruitment potential and impingement
    pressure / the livestream should be a hot house of engaging
    pressure that forces Hapax into impetus and action"

Five new on-frame surfaces make that pressure visible without needing
internal observability access:

- :class:`ImpingementCascadeCairoSource` — top N active perceptual signals
  + the recruitment family each would most likely trigger.
- :class:`RecruitmentCandidatePanelCairoSource` — last 3 recruited
  compositional capabilities + their salience.
- :class:`ThinkingIndicatorCairoSource` — pulsing dot while an LLM tick
  is in flight (narrative OR structural).
- :class:`PressureGaugeCairoSource` — current impingement pressure (how
  many signals active above threshold; saturation over time).
- :class:`ActivityVarietyLogCairoSource` — ribbon of recent activities
  fading out, so stillness shows a dance of moves even when current
  activity is silence.

All surfaces read SHM files already written by the director loop +
perception state. No new producers required for 4/5 surfaces; the one
exception is the LLM-in-flight marker, which the director writes during
its ``_call_activity_llm`` + structural call windows.

Typography + color follow ``docs/logos-design-language.md`` §1.6/§3 via
the shared palette in ``legibility_sources``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any

import cairo

from agents.studio_compositor.cairo_source import CairoSource
from agents.studio_compositor.legibility_sources import (
    _draw_rounded_rect,
    _palette,
)

log = logging.getLogger(__name__)

_PERCEPTION_STATE = Path(os.path.expanduser("~/.cache/hapax-daimonion/perception-state.json"))
_STIMMUNG_STATE = Path("/dev/shm/hapax-stimmung/state.json")
_LLM_IN_FLIGHT = Path("/dev/shm/hapax-director/llm-in-flight.json")
_DIRECTOR_INTENT_JSONL = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/director-intent.jsonl")
)

# ── Shared readers ────────────────────────────────────────────────────────


def _safe_load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.debug("hothouse read %s failed", path, exc_info=True)
    return {}


def _active_perceptual_signals(limit: int = 10) -> list[tuple[str, float, str]]:
    """Scan perception + stimmung state, return top-N signal/value/family triples.

    The "family" column is a heuristic mapping: if a signal-path fragment
    matches a known recruitment-family substring (camera / overlay /
    preset / youtube / stream / attention), we show that family; else
    show "—". Mapping is intentionally minimal — the director's actual
    recruitment pass uses richer semantics. This panel is a visibility
    aid, not authoritative.
    """
    signals: list[tuple[str, float, str]] = []
    perception = _safe_load_json(_PERCEPTION_STATE)
    stimmung = _safe_load_json(_STIMMUNG_STATE)

    # Flatten perception's top-level numeric fields + nested dicts.
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
    # Stimmung dimensions (dict of name → {reading: float} or name → float).
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

    # Sort by magnitude of value descending; treat booleans/strings as 1.0.
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


# ── 1. Impingement cascade ───────────────────────────────────────────────


class ImpingementCascadeCairoSource(CairoSource):
    """Live readout of top N active perceptual signals + candidate families.

    Renders as a monospace table: ``signal.path    value    → family``.
    At 2fps the operator sees the field filling up with activity, and
    can read which signals are within reach of the director's
    recruitment pass even before a move fires.
    """

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pal = _palette()
        _draw_rounded_rect(cr, 0, 0, canvas_w, canvas_h, 6, pal["bg_overlay"])

        cr.set_source_rgba(*pal["fg_primary"])
        cr.select_font_face("DejaVu Sans Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11)
        cr.move_to(8, 14)
        cr.show_text("IMPINGEMENT FIELD")

        cr.select_font_face("DejaVu Sans Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10)
        signals = _active_perceptual_signals(limit=14)
        y = 28
        for path, value, family in signals:
            if y + 12 > canvas_h:
                break
            cr.set_source_rgba(*pal["fg_primary"])
            cr.move_to(8, y)
            cr.show_text(f"{path[:32]:<32}")
            cr.set_source_rgba(*pal["accent_nominal"])
            cr.move_to(192, y)
            cr.show_text(f"{value:+.2f}")
            cr.set_source_rgba(*pal["accent_seeking"])
            cr.move_to(248, y)
            cr.show_text(f"→ {family}")
            y += 12


# ── 2. Recruitment candidate panel ───────────────────────────────────────


class RecruitmentCandidatePanelCairoSource(CairoSource):
    """Last 3 recruited compositional capabilities + salience."""

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pal = _palette()
        _draw_rounded_rect(cr, 0, 0, canvas_w, canvas_h, 6, pal["bg_overlay"])

        cr.set_source_rgba(*pal["fg_primary"])
        cr.select_font_face("DejaVu Sans Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11)
        cr.move_to(8, 14)
        cr.show_text("RECENT RECRUITMENTS")

        cr.select_font_face("DejaVu Sans Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10)

        # 2026-04-18 viewer audit: this panel used to display the LLM's
        # flowery narrative attached to each CompositionalImpingement
        # ("cut to a close-up of the turntable", "apply a subtle water
        # overlay") as if those moves were happening. The compositor
        # can only execute family-level dispatches (camera.hero selects
        # a role, overlay.emphasis bumps alpha on a fixed set of
        # targets, etc.) — the narratives were aspirational, never
        # grounded. Operator noted the gap is visible and confusing.
        #
        # Switched to reading /dev/shm/hapax-compositor/recent-recruitment.json,
        # which records what actually dispatched: the family plus the
        # concrete family-specific detail (preset-bias family name,
        # attention.winner source, etc.) and the age. That's honest.
        items: list[tuple[str, float, float]] = []
        try:
            recent_path = Path("/dev/shm/hapax-compositor/recent-recruitment.json")
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
                items = items[:3]
        except Exception:
            items = []

        y = 28
        if not items:
            cr.set_source_rgba(*pal["fg_primary"])
            cr.move_to(8, y)
            cr.show_text("(no recent recruitments)")
            return

        for label, age_s, _last in items:
            cr.set_source_rgba(*pal["fg_primary"])
            cr.move_to(8, y)
            cr.show_text(label[:38])
            cr.set_source_rgba(*pal["accent_nominal"])
            cr.move_to(canvas_w - 44, y)
            cr.show_text(f"{age_s:4.0f}s")
            y += 14


# ── 3. Thinking indicator ────────────────────────────────────────────────


class ThinkingIndicatorCairoSource(CairoSource):
    """Pulsing dot + tier label while an LLM tick is in flight.

    The director loop writes ``/dev/shm/hapax-director/llm-in-flight.json``
    before each ``_call_activity_llm`` / structural call and deletes it
    when the call returns. This source reads the marker and pulses.
    """

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        info = _safe_load_json(_LLM_IN_FLIGHT)
        active = bool(info)
        pal = _palette()
        _draw_rounded_rect(cr, 0, 0, canvas_w, canvas_h, 6, pal["bg_overlay"])

        cx = 12.0
        cy = canvas_h / 2
        if active:
            # Sinusoidal alpha pulse at ~1.5 Hz; radius grows with elapsed.
            started = float(info.get("started_at") or time.time())
            elapsed = max(0.0, time.time() - started)
            alpha = 0.5 + 0.5 * math.sin(t * 9.42)
            cr.set_source_rgba(*pal["accent_seeking"][:3], alpha)
            cr.arc(cx, cy, 6.0, 0, 2 * math.pi)
            cr.fill()
            model = str(info.get("model") or "?")
            tier = str(info.get("tier") or "?")
            cr.set_source_rgba(*pal["fg_primary"])
            cr.select_font_face("DejaVu Sans Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(11)
            cr.move_to(28, cy + 4)
            cr.show_text(f"{tier.upper()} · {model} · {elapsed:.1f}s")
        else:
            cr.set_source_rgba(*pal["fg_primary"][:3], 0.35)
            cr.arc(cx, cy, 4.0, 0, 2 * math.pi)
            cr.fill()
            cr.select_font_face(
                "DejaVu Sans Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL
            )
            cr.set_font_size(11)
            cr.move_to(28, cy + 4)
            cr.show_text("idle")


# ── 4. Pressure gauge ────────────────────────────────────────────────────


class PressureGaugeCairoSource(CairoSource):
    """Horizontal gauge: count of active perceptual signals above threshold.

    The idea is to expose the field saturation: as signals fire above
    threshold they push the gauge right; when the director acts, the
    gauge drops because the activity "discharges" the pressure.
    """

    _SIGNIFICANT_MAGNITUDE = 0.35
    _GAUGE_MAX = 12.0

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pal = _palette()
        _draw_rounded_rect(cr, 0, 0, canvas_w, canvas_h, 6, pal["bg_overlay"])

        signals = _active_perceptual_signals(limit=30)
        active = sum(1 for _, value, _ in signals if abs(value) >= self._SIGNIFICANT_MAGNITUDE)
        saturation = min(1.0, active / self._GAUGE_MAX)

        cr.set_source_rgba(*pal["fg_primary"])
        cr.select_font_face("DejaVu Sans Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11)
        cr.move_to(8, 16)
        cr.show_text("PRESSURE")

        # Gauge bar
        bar_x = 8.0
        bar_y = 22.0
        bar_w = canvas_w - 16.0
        bar_h = 10.0
        cr.set_source_rgba(*pal["fg_primary"][:3], 0.2)
        cr.rectangle(bar_x, bar_y, bar_w, bar_h)
        cr.fill()
        # Color transitions nominal → seeking → warning as pressure rises.
        if saturation < 0.33:
            accent = pal["accent_nominal"]
        elif saturation < 0.66:
            accent = pal["accent_seeking"]
        else:
            accent = pal["accent_warning"]
        cr.set_source_rgba(*accent)
        cr.rectangle(bar_x, bar_y, bar_w * saturation, bar_h)
        cr.fill()

        cr.set_source_rgba(*pal["fg_primary"])
        cr.select_font_face("DejaVu Sans Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10)
        cr.move_to(8, canvas_h - 4)
        cr.show_text(f"{active} active · {saturation:.0%} saturated")


# ── 5. Activity variety log ──────────────────────────────────────────────


class ActivityVarietyLogCairoSource(CairoSource):
    """Bottom-left ribbon of recent director activities, fading out over time."""

    _WINDOW_S = 180.0  # show activities from the last 3 min; fade past that

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pal = _palette()
        _draw_rounded_rect(cr, 0, 0, canvas_w, canvas_h, 6, pal["bg_overlay"])

        cr.set_source_rgba(*pal["fg_primary"])
        cr.select_font_face("DejaVu Sans Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11)
        cr.move_to(8, 14)
        cr.show_text("RECENT MOVES")

        intents = _read_recent_intents(n=10)
        now = time.time()
        # Deduplicate consecutive silences — a wall of silence is noise.
        deduped: list[dict] = []
        for intent in intents:
            if deduped and deduped[-1].get("activity") == intent.get("activity"):
                continue
            deduped.append(intent)

        cr.select_font_face("DejaVu Sans Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10)
        y = 28
        for intent in reversed(deduped[-6:]):
            if y + 12 > canvas_h:
                break
            activity = str(intent.get("activity") or "—")
            emitted = float(intent.get("emitted_at") or now)
            age = max(0.0, now - emitted)
            if age > self._WINDOW_S:
                continue
            # Linear fade from 1.0 at emission → 0.3 at WINDOW_S.
            alpha = max(0.3, 1.0 - (age / self._WINDOW_S) * 0.7)
            cr.set_source_rgba(*pal["fg_primary"][:3], alpha)
            cr.move_to(8, y)
            cr.show_text(f"[{int(age):>3}s]  {activity[:24]}")
            y += 14


# ── 6. Who's here indicator (Epic 2 Phase D) ─────────────────────────────

_PRESENCE_STATE = Path(os.path.expanduser("~/.cache/hapax-daimonion/presence-state.json"))


class WhosHereCairoSource(CairoSource):
    """Top-right mini-badge: operator presence + external viewer count.

    Operator directive 2026-04-17: "even if there is no YouTube audience
    *I* am here." The operator is always a first-class audience. This
    surface makes that legible: a permanent "♦ operator" marker plus
    the external-viewer count when non-zero.
    """

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pal = _palette()
        _draw_rounded_rect(cr, 0, 0, canvas_w, canvas_h, 6, pal["bg_overlay"])

        presence = _safe_load_json(_PRESENCE_STATE)
        presence_state = str(presence.get("state") or "PRESENT").upper()

        external = 0
        try:
            stream_overlay = Path("/dev/shm/hapax-compositor/youtube-viewer-count.txt")
            if stream_overlay.exists():
                external = int(stream_overlay.read_text().strip() or "0")
        except Exception:
            external = 0

        cr.select_font_face("DejaVu Sans Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12)
        # Operator is always here — but the color tells us whether presence
        # engine confirms it (PRESENT) or not (UNCERTAIN / AWAY).
        if presence_state == "PRESENT":
            cr.set_source_rgba(*pal["accent_nominal"])
        elif presence_state == "UNCERTAIN":
            cr.set_source_rgba(*pal["accent_cautious"])
        else:
            cr.set_source_rgba(*pal["fg_primary"][:3], 0.6)
        cr.move_to(8, 18)
        cr.show_text(f"\u2666 operator ({presence_state.lower()})")

        cr.set_source_rgba(*pal["fg_primary"])
        cr.set_font_size(11)
        cr.move_to(8, 34)
        if external > 0:
            cr.show_text(f"\u25cf {external} external (YouTube)")
        else:
            cr.show_text("\u25cb 0 external (solo)")


__all__ = [
    "ActivityVarietyLogCairoSource",
    "ImpingementCascadeCairoSource",
    "PressureGaugeCairoSource",
    "RecruitmentCandidatePanelCairoSource",
    "ThinkingIndicatorCairoSource",
    "WhosHereCairoSource",
]
