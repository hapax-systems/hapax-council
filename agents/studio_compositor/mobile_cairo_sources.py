"""Mobile-scaled Cairo sources and RGBA overlay runner."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cairo

from agents.studio_compositor.cairo_source import CairoSource
from agents.studio_compositor.mobile_layout import (
    MOBILE_HEIGHT,
    MOBILE_WIDTH,
    MobileLayout,
    load_mobile_layout,
    select_mobile_sources,
)
from agents.studio_compositor.text_render import TextStyle, render_text

log = logging.getLogger(__name__)

MOBILE_OVERLAY_PATH = Path("/dev/shm/hapax-compositor/mobile-overlay.rgba")
MOBILE_SALIENCE_PATH = Path("/dev/shm/hapax-compositor/mobile-salience.json")
MOBILE_TARGET_FPS = 10.0


@dataclass(frozen=True)
class MobileTextSpec:
    source_id: str
    class_name: str
    font_size_pt: int
    font_description: str
    natural_width: int
    natural_height: int


MOBILE_SOURCE_SPECS: tuple[MobileTextSpec, ...] = (
    MobileTextSpec(
        "activity_header",
        "MobileActivityHeaderCairoSource",
        20,
        "Px437 IBM VGA 8x16 20",
        1080,
        192,
    ),
    MobileTextSpec(
        "stance_indicator",
        "MobileStanceIndicatorCairoSource",
        20,
        "Px437 IBM VGA 8x16 20",
        1080,
        192,
    ),
    MobileTextSpec(
        "impingement_cascade",
        "MobileImpingementCascadeCairoSource",
        18,
        "Px437 IBM VGA 8x16 18",
        1080,
        192,
    ),
    MobileTextSpec(
        "token_pole",
        "MobileTokenPoleCairoSource",
        18,
        "Px437 IBM VGA 8x16 18",
        1080,
        96,
    ),
    MobileTextSpec(
        "captions",
        "MobileCaptionsCairoSource",
        22,
        "Px437 IBM VGA 8x16 22",
        1080,
        240,
    ),
)

_SPEC_BY_SOURCE = {spec.source_id: spec for spec in MOBILE_SOURCE_SPECS}


class _MobileSourceBase(CairoSource):
    source_id = ""

    def _spec(self) -> MobileTextSpec:
        return _SPEC_BY_SOURCE[self.source_id]

    def _draw_bg(self, cr: cairo.Context, canvas_w: int, canvas_h: int) -> None:
        cr.save()
        cr.set_source_rgba(0.08, 0.09, 0.09, 0.74)
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()
        cr.set_line_width(2)
        cr.set_source_rgba(0.45, 0.50, 0.42, 0.78)
        cr.rectangle(1, 1, max(0, canvas_w - 2), max(0, canvas_h - 2))
        cr.stroke()
        cr.restore()

    def _draw_text(
        self,
        cr: cairo.Context,
        text: str,
        x: int,
        y: int,
        *,
        max_width_px: int = 1020,
    ) -> None:
        spec = self._spec()
        render_text(
            cr,
            TextStyle(
                text=text,
                font_description=spec.font_description,
                color_rgba=(0.92, 0.94, 0.86, 0.98),
                outline_color_rgba=(0.0, 0.0, 0.0, 0.88),
                outline_offsets=((-2, 0), (2, 0), (0, -2), (0, 2)),
                max_width_px=max_width_px,
                wrap="word_char",
            ),
            x,
            y,
        )

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        self._draw_bg(cr, canvas_w, canvas_h)
        self.render_mobile(cr, canvas_w, canvas_h, t, state)

    def render_mobile(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        raise NotImplementedError


class MobileActivityHeaderCairoSource(_MobileSourceBase):
    source_id = "activity_header"

    def render_mobile(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        del canvas_w, canvas_h, t
        narrative = state.get("narrative") if isinstance(state.get("narrative"), dict) else {}
        activity = str(
            narrative.get("activity") or narrative.get("current_activity") or "neutral_hold"
        )
        gloss = str(narrative.get("gloss") or narrative.get("summary") or "mobile density minimum")
        self._draw_text(cr, f">>> [{activity} | {gloss}]", 28, 52)


class MobileStanceIndicatorCairoSource(_MobileSourceBase):
    source_id = "stance_indicator"

    def render_mobile(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        del canvas_w, canvas_h
        narrative = state.get("narrative") if isinstance(state.get("narrative"), dict) else {}
        stance = str(narrative.get("stance") or narrative.get("overall_stance") or "nominal")
        del t
        cr.save()
        cr.set_source_rgba(0.32, 0.58, 0.56, 0.66)
        cr.rectangle(26, 42, 18, 84)
        cr.fill()
        cr.restore()
        self._draw_text(cr, f"[+H {stance}]", 62, 58)


class MobileImpingementCascadeCairoSource(_MobileSourceBase):
    source_id = "impingement_cascade"

    def render_mobile(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        del canvas_w, canvas_h, t
        rows = []
        salience = state.get("salience") if isinstance(state.get("salience"), dict) else {}
        entries = salience.get("scores") if isinstance(salience.get("scores"), dict) else {}
        for ward, score in sorted(entries.items(), key=lambda item: (-float(item[1]), item[0]))[:3]:
            rows.append(f"{ward}: {float(score):0.2f}")
        if not rows:
            rows = ["minimum_density: no fresh mobile salience"]
        for idx, text in enumerate(rows[:3]):
            self._draw_text(cr, text, 28, 28 + idx * 50)


class MobileTokenPoleCairoSource(_MobileSourceBase):
    source_id = "token_pole"

    def render_mobile(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        del canvas_w, t
        salience = state.get("salience") if isinstance(state.get("salience"), dict) else {}
        scores = salience.get("scores") if isinstance(salience.get("scores"), dict) else {}
        progress = max([float(v) for v in scores.values()] or [0.0])
        progress = max(0.0, min(1.0, progress))
        cr.save()
        cr.set_source_rgba(0.18, 0.20, 0.18, 0.95)
        cr.rectangle(30, 32, 1020, 32)
        cr.fill()
        cr.set_source_rgba(0.70, 0.62, 0.30, 0.95)
        cr.rectangle(30, 32, 1020 * progress, 32)
        cr.fill()
        cr.restore()
        self._draw_text(cr, f"token pressure {progress:0.2f}", 30, max(66, canvas_h - 34))


class MobileCaptionsCairoSource(_MobileSourceBase):
    source_id = "captions"

    def render_mobile(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        del canvas_w, canvas_h, t
        text = str(state.get("caption") or "")
        if not text:
            text = "neutral_hold: captions unavailable"
        self._draw_text(cr, text, 28, 36, max_width_px=1020)


class MobileCairoRunner:
    """Render selected mobile Cairo sources into one 1080x1920 BGRA file."""

    def __init__(
        self,
        *,
        layout_path: Path | None = None,
        salience_path: Path = MOBILE_SALIENCE_PATH,
        output_path: Path = MOBILE_OVERLAY_PATH,
        target_fps: float = MOBILE_TARGET_FPS,
    ) -> None:
        if target_fps <= 0:
            raise ValueError("target_fps must be > 0")
        self.layout: MobileLayout = load_mobile_layout(layout_path)
        self.salience_path = salience_path
        self.output_path = output_path
        self._period = 1.0 / target_fps
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sources: dict[str, CairoSource] = {
            "activity_header": MobileActivityHeaderCairoSource(),
            "stance_indicator": MobileStanceIndicatorCairoSource(),
            "impingement_cascade": MobileImpingementCascadeCairoSource(),
            "token_pole": MobileTokenPoleCairoSource(),
            "captions": MobileCaptionsCairoSource(),
        }
        self._surface: cairo.ImageSurface | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="mobile-cairo")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.render_once()
            except Exception:
                log.exception("mobile cairo render failed")
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.0, self._period - elapsed))

    def render_once(self) -> Path:
        started = time.monotonic()
        salience = self._read_json(self.salience_path)
        selection = select_mobile_sources(self.layout, salience)

        surface = self._render_surface()
        cr = cairo.Context(surface)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.0)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        state: dict[str, Any] = {
            "salience": salience,
            "selection": selection,
            "narrative": self._read_json(Path("/dev/shm/hapax-director/narrative-state.json")),
            "caption": self._read_caption(Path("/dev/shm/hapax-daimonion/stt-recent.txt")),
        }
        self._draw_hero_bounds(cr)
        self._draw_wards(cr, selection.selected_wards, state)
        self._draw_footer(cr, selection)

        surface.flush()
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_surface_atomic(surface)

        try:
            from agents.studio_compositor import metrics

            if metrics.HAPAX_MOBILE_CAIRO_RENDER_DURATION_MS is not None:
                metrics.HAPAX_MOBILE_CAIRO_RENDER_DURATION_MS.observe(
                    (time.monotonic() - started) * 1000.0
                )
        except Exception:
            log.debug("mobile cairo metric update failed", exc_info=True)

        return self.output_path

    def _render_surface(self) -> cairo.ImageSurface:
        if (
            self._surface is None
            or self._surface.get_width() != MOBILE_WIDTH
            or self._surface.get_height() != MOBILE_HEIGHT
        ):
            self._surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, MOBILE_WIDTH, MOBILE_HEIGHT)
        return self._surface

    def _write_surface_atomic(self, surface: cairo.ImageSurface) -> None:
        tmp = self.output_path.with_suffix(self.output_path.suffix + ".tmp")
        data = memoryview(surface.get_data())
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            written_total = 0
            while written_total < len(data):
                written = os.write(fd, data[written_total:])
                if written <= 0:
                    raise OSError("short write while publishing mobile overlay")
                written_total += written
        finally:
            os.close(fd)
        tmp.rename(self.output_path)

    def _draw_hero_bounds(self, cr: cairo.Context) -> None:
        cr.save()
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.0)
        cr.rectangle(
            self.layout.hero_cam.dest.x,
            self.layout.hero_cam.dest.y,
            self.layout.hero_cam.dest.width,
            self.layout.hero_cam.dest.height,
        )
        cr.fill()
        cr.restore()

    def _draw_wards(
        self,
        cr: cairo.Context,
        selected_wards: tuple[str, ...],
        state: dict[str, Any],
    ) -> None:
        zone = self.layout.ward_zone
        for idx, ward in enumerate(selected_wards):
            source = self._sources.get(ward)
            if source is None:
                continue
            y = zone.y_top + idx * zone.ward_height
            cr.save()
            cr.translate(zone.padding_px, y)
            source.render(
                cr,
                MOBILE_WIDTH - 2 * zone.padding_px,
                zone.ward_height,
                time.monotonic(),
                state,
            )
            cr.restore()

    def _draw_footer(self, cr: cairo.Context, selection: Any) -> None:
        footer = self.layout.metadata_footer
        cr.save()
        cr.set_source_rgba(0.05, 0.055, 0.05, 0.86)
        cr.rectangle(0, footer.y_top, MOBILE_WIDTH, footer.y_bottom - footer.y_top)
        cr.fill()
        render_text(
            cr,
            TextStyle(
                text=f"{selection.claim_posture} / {selection.density_mode}",
                font_description=f"Px437 IBM VGA 8x16 {footer.font_size_pt}",
                color_rgba=(0.82, 0.86, 0.78, 0.95),
                max_width_px=1020,
            ),
            28,
            footer.y_top + 54,
        )
        cr.restore()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _read_caption(path: Path) -> str:
        try:
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                text = line.strip()
                if text:
                    return text
        except OSError:
            return ""
        return ""
