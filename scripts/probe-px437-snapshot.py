#!/usr/bin/env python3
"""Deterministic Px437 snapshot probe.

Closes ``visual-quality-px437-live-snapshot-fixture`` (cc-task). The
previous Tier-B verification produced two artifacts:

  - A live compositor snapshot — no text overlay, so it could not
    prove Px437 edge sharpness either way.
  - An HLS-extracted frame — text was visible but the live FX stack
    smeared the glyphs.

This probe sits *upstream* of the FX stack. It calls
``agents.studio_compositor.text_render.render_text_to_surface`` with
the Px437 IBM VGA 8x16 face and dumps the raw Cairo ARGB surface to
PNG. The output is the **clean pixel-grid proof** that the text
renderer itself produces sharp edges; the FX-smearing seen in HLS is
introduced *after* this stage by the GL-mixer / videoscale / JPEG
chain (see docs/visual-quality/px437-fx-smearing.md).

The probe never touches GStreamer, the compositor service, or any
RTMP / YouTube credential. It is safe to run from a session shell:

  uv run python scripts/probe-px437-snapshot.py

Default output dir is
``~/.cache/hapax/verification/visual-quality-px437-live-snapshot-fixture/``;
override with ``--output-dir``. Output filename is
``probe-{iso8601-z}.png``.

Determinism: same text + style + padding deterministically yields the
same byte stream. The unit test in
``tests/scripts/test_probe_px437_snapshot.py`` pins this by hashing
the ARGB pixel bytes (not the PNG file, whose timestamp metadata
would diverge across runs).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from agents.studio_compositor.text_render import TextStyle, render_text_to_surface

DEFAULT_TEXT = "PX437 IBM VGA 8x16 -- 0123456789 -- the quick brown fox"
DEFAULT_FONT = "Px437 IBM VGA 8x16 32"
DEFAULT_OUTPUT_DIR = (
    Path.home()
    / ".cache"
    / "hapax"
    / "verification"
    / ("visual-quality-px437-live-snapshot-fixture")
)


def make_style(text: str = DEFAULT_TEXT, font: str = DEFAULT_FONT) -> TextStyle:
    """Return the canonical Px437 probe TextStyle.

    White-on-transparent so the artifact reads as a clean glyph grid
    without compositing assumptions. No outline (the smearing question
    is about the foreground glyphs themselves, not the outline pass).
    """
    return TextStyle(
        text=text,
        font_description=font,
        color_rgba=(1.0, 1.0, 1.0, 1.0),
        outline_offsets=(),
    )


def render_probe_png(
    output_path: Path,
    *,
    text: str = DEFAULT_TEXT,
    font: str = DEFAULT_FONT,
    padding_px: int = 8,
) -> tuple[int, int]:
    """Render the probe and write to ``output_path``. Returns (w, h)."""
    style = make_style(text=text, font=font)
    surface, w, h = render_text_to_surface(style, padding_px=padding_px)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    surface.write_to_png(str(output_path))
    return w, h


def _utc_now_iso8601_z() -> str:
    return dt.datetime.now(tz=dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a deterministic Px437 snapshot for the visual-quality fixture."
    )
    parser.add_argument(
        "--text",
        default=DEFAULT_TEXT,
        help="Text to render through the Px437 face.",
    )
    parser.add_argument(
        "--font",
        default=DEFAULT_FONT,
        help="Pango font description (default: %(default)r).",
    )
    parser.add_argument(
        "--padding-px",
        type=int,
        default=8,
        help="Padding around the laid-out text in pixels (default: %(default)d).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory (default: %(default)s).",
    )
    parser.add_argument(
        "--output-filename",
        default=None,
        help="Override output filename. Default: probe-<utc-iso>.png.",
    )
    args = parser.parse_args(argv)

    filename = args.output_filename or f"probe-{_utc_now_iso8601_z()}.png"
    output_path = args.output_dir / filename
    w, h = render_probe_png(
        output_path,
        text=args.text,
        font=args.font,
        padding_px=args.padding_px,
    )
    print(f"probe-px437: wrote {output_path} ({w}x{h})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
