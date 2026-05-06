"""M8 oscilloscope waveform Cairo ward.

Companion to ``packages/m8c-hapax/shm_sink.c``'s
``shm_sink_publish_oscilloscope`` (the carry-fork patch added by
``cc-task m8-oscilloscope-reactive-surface``). Reads the binary ring
file at ``/dev/shm/hapax-sources/m8-osc.bin`` (12-byte header +
up to 480 8-bit samples) and draws the waveform as a tinted line at
HOMAGE-aesthetic scale, distinct from the small pixel-art LCD reveal
ward.

Constitutional binders:

* ``feedback_show_dont_tell_director`` — the waveform IS the M8's
  audio activity. No narration, no caption.
* ``reference_wards_taxonomy`` — new Cairo overlay ward, slotted next
  to sierpinski / vitruvian / album / token-pole.
* Anti-anthropomorphization — instrument waveform, not personified.
* Palette discipline — tint via the active HOMAGE package's
  ``resolve_colour``; never hardcoded hex.

Silence handling: when the ring file's mtime is older than
``SILENCE_FADE_AFTER_S`` (default 1.0 s), the rendered alpha fades
linearly to zero over ``SILENCE_FADE_DURATION_S`` (0.5 s). Configurable
via class init params for tests.
"""

from __future__ import annotations

import logging
import struct
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    import cairo

    from shared.homage_package import HomagePackage

log = logging.getLogger(__name__)

DEFAULT_RING_PATH: Path = Path("/dev/shm/hapax-sources/m8-osc.bin")

# Header layout (must match shm_sink_publish_oscilloscope in the
# carry-fork): 8-byte LE frame_id, 1-byte color, 1-byte reserved,
# 2-byte LE sample_count, then up to 480 sample bytes.
_HEADER_FMT = "<QBBH"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_MAX_SAMPLES = 480
_FILE_SIZE = _HEADER_SIZE + _MAX_SAMPLES

DEFAULT_NATURAL_W: int = 1280
DEFAULT_NATURAL_H: int = 128
DEFAULT_LINE_WIDTH: float = 1.4
SILENCE_FADE_AFTER_S: float = 1.0
SILENCE_FADE_DURATION_S: float = 0.5
ACTIVE_ALPHA: float = 0.75


def _fallback_package() -> HomagePackage:
    """Return the compiled-in BitchX package when registry resolution fails.

    Mirrors ``egress_footer_source._fallback_package`` so the module
    stays importable in CI harnesses that don't boot the compositor far
    enough to load the active HomagePackage.
    """
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


def _resolve_waveform_tint(pkg: HomagePackage, alpha: float) -> tuple[float, float, float, float]:
    """Resolve the HOMAGE ``accent`` colour role at the given alpha.

    ``accent`` keeps the waveform reading as instrument-of-the-operator
    rather than chrome (``muted``). Falls back to a neutral grey if the
    package does not declare ``accent``.
    """
    try:
        r, g, b, _ = pkg.resolve_colour("accent")
    except Exception:
        log.debug("accent role unresolved on %s", pkg.name, exc_info=True)
        r, g, b = 0.6, 0.6, 0.6
    return (r, g, b, alpha)


def _read_ring(path: Path) -> tuple[int, int, bytes, float] | None:
    """Read the oscilloscope ring file.

    Returns ``(frame_id, color, samples, mtime)`` on success, ``None``
    when the file is absent / truncated / malformed. Defensive — the
    Cairo source must never raise into the compositor's render thread.
    """
    try:
        st = path.stat()
        with path.open("rb") as f:
            buf = f.read(_FILE_SIZE)
    except OSError:
        return None
    if len(buf) < _HEADER_SIZE:
        return None
    try:
        frame_id, color, _reserved, sample_count = struct.unpack(_HEADER_FMT, buf[:_HEADER_SIZE])
    except struct.error:
        return None
    if sample_count > _MAX_SAMPLES:
        sample_count = _MAX_SAMPLES
    samples = buf[_HEADER_SIZE : _HEADER_SIZE + sample_count]
    return frame_id, color, samples, st.st_mtime


def _silence_alpha(
    mtime: float,
    now: float,
    *,
    fade_after_s: float,
    fade_duration_s: float,
    active_alpha: float,
) -> float:
    """Map ring-file mtime age to a render alpha in [0, active_alpha]."""
    age = now - mtime
    if age <= fade_after_s:
        return active_alpha
    fade_elapsed = age - fade_after_s
    if fade_elapsed >= fade_duration_s:
        return 0.0
    return active_alpha * (1.0 - (fade_elapsed / fade_duration_s))


class M8OscilloscopeCairoSource(HomageTransitionalSource):
    """M8 0xFC waveform rendered as a tinted line at audience scale.

    Default natural size: 1280×128 px (HOMAGE-aesthetic; complementary
    to the 320×240 pixel-art LCD reveal — both can coexist on the
    broadcast). Single-stroke Cairo path for performance — never
    per-pixel ``cairo_set_source_rgba`` calls per the task notes.
    """

    source_id: str = "m8_oscilloscope"

    def __init__(
        self,
        *,
        ring_path: Path = DEFAULT_RING_PATH,
        line_width: float = DEFAULT_LINE_WIDTH,
        silence_fade_after_s: float = SILENCE_FADE_AFTER_S,
        silence_fade_duration_s: float = SILENCE_FADE_DURATION_S,
        active_alpha: float = ACTIVE_ALPHA,
    ) -> None:
        super().__init__(source_id=self.source_id)
        self._ring_path = ring_path
        self._line_width = line_width
        self._silence_fade_after_s = silence_fade_after_s
        self._silence_fade_duration_s = silence_fade_duration_s
        self._active_alpha = active_alpha

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        ring = _read_ring(self._ring_path)
        if ring is None:
            return
        _frame_id, _color, samples, mtime = ring
        if not samples:
            return

        alpha = _silence_alpha(
            mtime,
            time.time(),
            fade_after_s=self._silence_fade_after_s,
            fade_duration_s=self._silence_fade_duration_s,
            active_alpha=self._active_alpha,
        )
        if alpha <= 0.0:
            return

        pkg = get_active_package() or _fallback_package()
        r, g, b, a = _resolve_waveform_tint(pkg, alpha)

        cr.save()
        cr.set_line_width(self._line_width)
        cr.set_source_rgba(r, g, b, a)

        n = len(samples)
        x_step = canvas_w / max(1, n - 1) if n > 1 else 0.0
        y_mid = canvas_h / 2.0
        # M8 sends samples as 0..255 unsigned; centre at 128 and map
        # ±128 onto ±(canvas_h/2). Single Cairo path stroked once.
        for i, sample in enumerate(samples):
            y = y_mid - ((sample - 128) / 128.0) * (canvas_h / 2.0)
            x = i * x_step
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()
        cr.restore()
