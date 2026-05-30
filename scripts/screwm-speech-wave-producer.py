#!/usr/bin/env python3
"""screwm-speech-wave-producer — Hapax's live speech as the Sierpinski-centre oscilloscope.

Reads the daimonion speech-wave ring (m8 oscilloscope on-disk format, written by
agents/hapax_daimonion/tts_envelope_publisher.py) and draws a single-stroke
time-domain oscilloscope into a 512x128 BGRA slot buffer at ~60Hz. This is the
operator's #1 aesthetic invariant: the centre waveform IS Hapax's speech — RAW
time domain (NOT FFT bars), off-centerline, tight (single-frame, no IIR lag).

- Silence -> the line fades toward a flat midline (fades, never freezes/garbage).
- Amplitude modulates line-WIDTH + ALPHA only (spatial/tonal) — never a global
  flash/dim/pulse (the consumer is one ward surface, not the whole scene).
- HOMAGE accent tint via the active package (no hardcoded hex), resolved once at
  startup behind a hard fallback so a missing/heavy import can NEVER stop the
  producer — the meeting backdrop must keep getting frames.
- Output is EXACTLY 512*128*4 = 262144 bytes; the engine live-texture slot guard
  silently drops any frame of the wrong size.

Transparent background = a floating waveform, not a solid panel.
"""

from __future__ import annotations

import os
import signal
import struct
import sys
import time
from pathlib import Path

import cairo

WIDTH = 512
HEIGHT = 128
FRAME_SIZE = WIDTH * HEIGHT * 4  # 262144 — must match the slot's w*h*4 exactly

DEFAULT_RING = Path(
    os.environ.get("SCREWM_SPEECH_WAVE_RING", "/dev/shm/hapax-daimonion/speech-wave.bin")
)
DEFAULT_OUTPUT = Path(
    os.environ.get(
        "SCREWM_SPEECH_WAVE_OUTPUT", "/dev/shm/hapax-compositor/quake-live-speech-wave.bgra"
    )
)
FPS = float(os.environ.get("SCREWM_SPEECH_WAVE_FPS", "60"))

# m8 oscilloscope ring format (matches tts_envelope_publisher._WAVE_*).
_HEADER_FMT = "<QBBH"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 12
_MAX_SAMPLES = 480
_RING_SIZE = _HEADER_SIZE + _MAX_SAMPLES  # 492

LINE_WIDTH = 2.0
LINE_WIDTH_AMP_SCALE = 3.0
ACTIVE_ALPHA = 1.0
ALPHA_FLOOR = 0.22
SILENCE_FADE_AFTER_S = 1.0
SILENCE_FADE_DURATION_S = 0.5
# Bounded-amplitude clamp (operator 2026-05-06: reactivity must be TIGHT) — no
# IIR lag; a percussive burst above this ceiling is clamped but the visual
# response is single-frame. The waveform draw itself uses the raw samples.
AMP_BURST_CLAMP = 0.85
ACCENT_FALLBACK = (0.27, 0.91, 1.0)  # screwm cyan if HOMAGE accent unresolved

_STOP = False


def _on_signal(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def _read_ring(path: Path) -> tuple[bytes, float] | None:
    """Read (samples, mtime) from the m8-format ring. Defensive — never raises."""
    try:
        st = path.stat()
        with path.open("rb") as fh:
            buf = fh.read(_RING_SIZE)
    except OSError:
        return None
    if len(buf) < _HEADER_SIZE:
        return None
    try:
        _frame_id, _color, _reserved, sample_count = struct.unpack(_HEADER_FMT, buf[:_HEADER_SIZE])
    except struct.error:
        return None
    sample_count = min(sample_count, _MAX_SAMPLES)
    return buf[_HEADER_SIZE : _HEADER_SIZE + sample_count], st.st_mtime


def _silence_alpha(mtime: float, now: float) -> float:
    """Map ring mtime age to [0, ACTIVE_ALPHA] — fade out when speech stops."""
    age = now - mtime
    if age <= SILENCE_FADE_AFTER_S:
        return ACTIVE_ALPHA
    fade_elapsed = age - SILENCE_FADE_AFTER_S
    if fade_elapsed >= SILENCE_FADE_DURATION_S:
        return 0.0
    return ACTIVE_ALPHA * (1.0 - (fade_elapsed / SILENCE_FADE_DURATION_S))


def _amplitude(samples: bytes) -> float:
    """Peak deviation from the 128 midline, normalized to [0, 1]."""
    if not samples:
        return 0.0
    peak = max(abs(int(s) - 128) for s in samples)
    return min(peak / 128.0, 1.0)


def _resolve_accent() -> tuple[float, float, float]:
    """HOMAGE accent colour, resolved ONCE behind a hard fallback (never raises)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from agents.studio_compositor.homage import get_active_package

        pkg = get_active_package()
        r, g, b, _a = pkg.resolve_colour("accent")
        return (float(r), float(g), float(b))
    except Exception:  # noqa: BLE001 — colour is cosmetic; never stop the producer
        return ACCENT_FALLBACK


def _surface_bgra(surface: cairo.ImageSurface) -> bytes:
    """Extract tightly-packed BGRA bytes, stripping any Cairo row padding."""
    surface.flush()
    stride = surface.get_stride()
    data = bytes(surface.get_data())
    if stride == WIDTH * 4:
        return data
    return b"".join(data[y * stride : y * stride + WIDTH * 4] for y in range(HEIGHT))


def _render(accent: tuple[float, float, float], now: float) -> bytes:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    cr = cairo.Context(surface)  # transparent background by default
    ring = _read_ring(DEFAULT_RING)
    if ring is not None:
        samples, mtime = ring
        base_alpha = _silence_alpha(mtime, now)
        if samples and base_alpha > 0.0:
            amplitude = min(_amplitude(samples), AMP_BURST_CLAMP)
            alpha = base_alpha * (ALPHA_FLOOR + (1.0 - ALPHA_FLOOR) * amplitude)
            r, g, b = accent
            cr.set_line_width(LINE_WIDTH + amplitude * LINE_WIDTH_AMP_SCALE)
            cr.set_source_rgba(r, g, b, alpha)
            n = len(samples)
            x_step = WIDTH / max(1, n - 1) if n > 1 else 0.0
            y_mid = HEIGHT / 2.0
            for i, sample in enumerate(samples):
                y = y_mid - ((sample - 128) / 128.0) * (HEIGHT / 2.0)
                x = i * x_step
                if i == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            cr.stroke()
    return _surface_bgra(surface)


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def main() -> int:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    accent = _resolve_accent()
    interval = 1.0 / max(FPS, 1.0)
    blank = bytes(FRAME_SIZE)
    while not _STOP:
        try:
            frame = _render(accent, time.time())
            if len(frame) != FRAME_SIZE:
                frame = blank
            _atomic_write(DEFAULT_OUTPUT, frame)
        except Exception:  # noqa: BLE001 — never crash; keep feeding the slot
            try:
                _atomic_write(DEFAULT_OUTPUT, blank)
            except OSError:
                pass
        time.sleep(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
