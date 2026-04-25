#!/usr/bin/env python3
"""Render Oudepode "Dump Disciple: Register 0" album cover at 3000x3000.

Path C of the Enlightenment+BitchX hybrid HOMAGE:
- Outer Moksha (Enlightenment) window chrome (palette: focus_color, fg_color,
  bg_color, fg_selected from authentic-v1 EDC)
- Inner BitchX IRC channel buffer (typography: Px437 IBM VGA 8x16; palette:
  byte-exact mIRC 16-color contract)
- Tracklist rendered as <oudepode> chat lines

Drops to ~/gdrive-drop/oudepode-cover-3000.png.
"""

from __future__ import annotations

from pathlib import Path

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

from agents.studio_compositor.homage import (  # noqa: E402
    BITCHX_AUTHENTIC_PACKAGE as BX,
)
from agents.studio_compositor.homage import (  # noqa: E402
    ENLIGHTENMENT_MOKSHA_AUTHENTIC_PACKAGE as MO,
)

# -- Album content -------------------------------------------------------
TITLE = "Dump Disciple: Register 0"
ARTIST = "oudepode"
RELEASE_DATE = "2026-05-15"
SOUNDCLOUD_URL = "soundcloud.com/oudepode"
CHANNEL = "#the-empty-set"
TRACKLIST: list[tuple[str, str, str]] = [
    ("01", "visage best", "2:26"),
    ("02", "PLUMPCORP", "4:29"),
    ("03", "dump disciple", "1:49"),
    ("04", "BIOSCOPE", "3:22"),
    ("05", "UNKNOWNTRON", "2:32"),
    ("06", "alekhine batteries", "2:00"),
    ("07", "Halted", "1:45"),
    ("08", "least favorite diving bell", "3:48"),
]

# -- Canvas --------------------------------------------------------------
SIZE = 3000
SHADOW_MARGIN = 28
BORDER = 6
TITLEBAR_H = 140
PAD = 80
PX437 = "Px437 IBM VGA 8x16"

# Px437 IBM VGA 8x16 is 16px native height. 1pt = 1.3333px @ 96 DPI.
# Body 96px -> 72pt; banner 192px -> 144pt; small 80px -> 60pt.
BODY_PT = 72
BANNER_PT = 120
SMALL_PT = 56


def set_rgba(ctx: cairo.Context, c: tuple, alpha: float = 1.0) -> None:
    r, g, b = c[0], c[1], c[2]
    a = c[3] if len(c) == 4 else 1.0
    ctx.set_source_rgba(r, g, b, a * alpha)


def opaque(c: tuple) -> tuple[float, float, float, float]:
    return (c[0], c[1], c[2], 1.0)


def make_layout(
    ctx: cairo.Context, text: str, *, pt: int = BODY_PT, bold: bool = False
) -> Pango.Layout:
    layout = PangoCairo.create_layout(ctx)
    desc = Pango.FontDescription()
    desc.set_family(PX437)
    desc.set_size(int(pt * Pango.SCALE))
    if bold:
        desc.set_weight(Pango.Weight.BOLD)
    layout.set_font_description(desc)
    fopt = cairo.FontOptions()
    fopt.set_antialias(cairo.ANTIALIAS_NONE)
    fopt.set_hint_style(cairo.HINT_STYLE_NONE)
    PangoCairo.context_set_font_options(layout.get_context(), fopt)
    layout.set_text(text, -1)
    return layout


def draw_text(
    ctx: cairo.Context,
    x: float,
    y: float,
    text: str,
    color: tuple,
    *,
    pt: int = BODY_PT,
    bold: bool = False,
) -> int:
    set_rgba(ctx, color)
    ctx.move_to(x, y)
    layout = make_layout(ctx, text, pt=pt, bold=bold)
    PangoCairo.show_layout(ctx, layout)
    _, ext = layout.get_pixel_extents()
    return ext.width


def text_extents(
    ctx: cairo.Context, text: str, *, pt: int = BODY_PT, bold: bool = False
) -> tuple[int, int]:
    layout = make_layout(ctx, text, pt=pt, bold=bold)
    _, ext = layout.get_pixel_extents()
    return ext.width, ext.height


def render() -> Path:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIZE, SIZE)
    ctx = cairo.Context(surface)

    # Outermost background — pure black
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()

    # Drop shadow (Moksha bg x 0.35), offset down-right
    bg = MO.palette.background
    set_rgba(ctx, (bg[0] * 0.35, bg[1] * 0.35, bg[2] * 0.35, 1.0))
    ctx.rectangle(SHADOW_MARGIN, SHADOW_MARGIN, SIZE - SHADOW_MARGIN, SIZE - SHADOW_MARGIN)
    ctx.fill()

    # Window outer border (Moksha muted = fg_color)
    set_rgba(ctx, MO.palette.muted)
    ctx.rectangle(0, 0, SIZE - SHADOW_MARGIN, SIZE - SHADOW_MARGIN)
    ctx.fill()

    win_x = BORDER
    win_y = BORDER
    win_w = SIZE - SHADOW_MARGIN - 2 * BORDER
    win_h = SIZE - SHADOW_MARGIN - 2 * BORDER

    # Titlebar
    set_rgba(ctx, MO.palette.accent_cyan)
    ctx.rectangle(win_x, win_y, win_w, TITLEBAR_H)
    ctx.fill()

    # Titlebar bottom separator
    set_rgba(ctx, MO.palette.muted)
    ctx.rectangle(win_x, win_y + TITLEBAR_H - 4, win_w, 4)
    ctx.fill()

    # Shorten titlebar text so window controls don't collide at 3000px.
    title_text = f"BitchX 1.2  -  {CHANNEL}"
    _, t_h = text_extents(ctx, title_text, pt=BODY_PT, bold=True)
    title_y = win_y + (TITLEBAR_H - t_h) // 2 - 6
    draw_text(ctx, win_x + PAD, title_y, title_text, MO.palette.bright, pt=BODY_PT, bold=True)

    ctrls = "[ _ ]  [ # ]  [ x ]"
    c_w, _ = text_extents(ctx, ctrls, pt=BODY_PT)
    draw_text(
        ctx,
        win_x + win_w - PAD - c_w,
        title_y,
        ctrls,
        MO.palette.bright,
        pt=BODY_PT,
        bold=True,
    )

    # Body
    body_x = win_x
    body_y = win_y + TITLEBAR_H
    body_w = win_w
    body_h = win_h - TITLEBAR_H
    set_rgba(ctx, opaque(MO.palette.background))
    ctx.rectangle(body_x, body_y, body_w, body_h)
    ctx.fill()

    cx = body_x + PAD
    cx_right = body_x + body_w - PAD
    cy = body_y + PAD
    line_h = 110
    small_h = 90

    status = f"[18:42] [{ARTIST}(+i)] [3:{CHANNEL}(+nt)] [Act: 12,*4]"
    draw_text(ctx, cx, cy, status, BX.palette.bright, pt=SMALL_PT)
    cy += small_h + 24

    set_rgba(ctx, BX.palette.muted)
    ctx.rectangle(cx, cy, cx_right - cx, 3)
    ctx.fill()
    cy += 36

    draw_text(
        ctx, cx, cy, f"*** Topic for {CHANNEL}: {TITLE}", BX.palette.accent_yellow, pt=BODY_PT
    )
    cy += line_h
    draw_text(
        ctx,
        cx,
        cy,
        f"*** Released {RELEASE_DATE} - {SOUNDCLOUD_URL}",
        BX.palette.accent_yellow,
        pt=BODY_PT,
    )
    cy += line_h + 20

    rule = "=" * 40
    draw_text(ctx, cx, cy, rule, BX.palette.accent_magenta, pt=BODY_PT)
    cy += line_h - 30

    bw1, bh1 = text_extents(ctx, "DUMP DISCIPLE", pt=BANNER_PT, bold=True)
    draw_text(
        ctx,
        cx + (cx_right - cx - bw1) // 2,
        cy,
        "DUMP DISCIPLE",
        BX.palette.accent_magenta,
        pt=BANNER_PT,
        bold=True,
    )
    cy += bh1 + 10

    bw2, bh2 = text_extents(ctx, "REGISTER 0", pt=BANNER_PT, bold=True)
    draw_text(
        ctx,
        cx + (cx_right - cx - bw2) // 2,
        cy,
        "REGISTER 0",
        BX.palette.accent_blue,
        pt=BANNER_PT,
        bold=True,
    )
    cy += bh2 + 10
    draw_text(ctx, cx, cy, rule, BX.palette.accent_magenta, pt=BODY_PT)
    cy += line_h + 20

    # Operator-directed join line: Oudepode@LegomenaLive joining the empty set.
    # Compact IRC-shorthand form so the line fits without right-clipping at 3000px.
    join = f"*** Oudepode@LegomenaLive joined {CHANNEL}"
    draw_text(ctx, cx, cy, join, BX.palette.accent_green, pt=BODY_PT)
    cy += line_h + 10

    for num, name, dur in TRACKLIST:
        prefix = f"<{ARTIST}>"
        body = f"  {num}. {name}"
        prefix_w = draw_text(ctx, cx, cy, prefix, BX.palette.accent_magenta, pt=BODY_PT)
        draw_text(ctx, cx + prefix_w, cy, body, BX.palette.terminal_default, pt=BODY_PT)
        dur_text = f"({dur})"
        d_w, _ = text_extents(ctx, dur_text, pt=BODY_PT)
        draw_text(ctx, cx_right - d_w, cy, dur_text, BX.palette.accent_cyan, pt=BODY_PT)
        cy += line_h

    cy += 20

    draw_text(
        ctx,
        cx,
        cy,
        f"-!- mode/{CHANNEL} [+v {ARTIST}] by ChanServ",
        BX.palette.muted,
        pt=BODY_PT,
    )
    cy += line_h + 10

    prompt = f"[{CHANNEL}] "
    p_w = draw_text(ctx, cx, cy, prompt, BX.palette.terminal_default, pt=BODY_PT)
    set_rgba(ctx, BX.palette.terminal_default)
    ctx.rectangle(cx + p_w, cy + 12, 56, 96)
    ctx.fill()

    out = Path.home() / "gdrive-drop" / "oudepode-cover-3000.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    surface.write_to_png(str(out))
    return out


if __name__ == "__main__":
    out = render()
    print(f"wrote {out}")
