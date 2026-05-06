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
# Floor of the amplitude-driven alpha modulation — when the waveform is
# silent (samples all near 128), the ward still renders at this fraction
# of its mtime-driven alpha so a connected-but-quiet M8 stays legibly
# present. Loud waveforms scale linearly up to 1.0×.
AMPLITUDE_ALPHA_FLOOR: float = 0.5
# Additional Cairo line width (in pixels) at full ±128 amplitude. The
# rendered stroke is ``DEFAULT_LINE_WIDTH + amplitude × this`` — silent
# midline draws at the base width; loud waveforms thicken proportionally
# so peaks read as bold strokes against a thin idle baseline. Mirrors
# the sierpinski waveform's ``1.5 + audio_energy × 2.0`` precedent at a
# more conservative scale (the M8 osc is a thinner ward by default).
LINE_WIDTH_AMPLITUDE_SCALE: float = 1.0
# One-pole IIR coefficient on the modulation amplitude. Per-frame
# ``smoothed = smoothed × (1 − α) + raw × α``. The waveform DRAW
# continues to read raw samples — that surface IS the audio. Only the
# alpha + line-width MODULATIONS see the smoothed envelope so percussive
# transients don't whip those parameters frame-to-frame. Matches the
# sierpinski IIR alpha (#2639) for cross-ward consistency.
AMPLITUDE_IIR_ALPHA: float = 0.3


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


def _amplitude_normalized(samples: bytes) -> float:
    """Peak-normalized amplitude of the M8 waveform in [0, 1].

    M8 sends samples as 0..255 unsigned, centred at 128. The peak of
    ``max(abs(sample - 128))`` divided by 128 gives the normalized
    amplitude — 0 when the waveform is a flat midline, 1 at full ±128
    swing. Empty input yields 0 so callers never see NaN.
    """
    if not samples:
        return 0.0
    peak = max(abs(int(s) - 128) for s in samples)
    return min(peak / 128.0, 1.0)


def _amplitude_scaled_alpha(base_alpha: float, amplitude: float, *, floor: float) -> float:
    """Scale a base alpha by amplitude, clamped at the configured floor.

    At ``amplitude=0`` returns ``base_alpha * floor``; at ``amplitude=1``
    returns ``base_alpha``. Clamps amplitude to [0, 1] defensively so an
    out-of-band caller cannot drive alpha above the silence-fade ceiling.
    """
    a = max(0.0, min(1.0, amplitude))
    return base_alpha * (floor + (1.0 - floor) * a)


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
        amplitude_alpha_floor: float = AMPLITUDE_ALPHA_FLOOR,
        line_width_amplitude_scale: float = LINE_WIDTH_AMPLITUDE_SCALE,
        amplitude_iir_alpha: float = AMPLITUDE_IIR_ALPHA,
    ) -> None:
        super().__init__(source_id=self.source_id)
        self._ring_path = ring_path
        self._line_width = line_width
        self._silence_fade_after_s = silence_fade_after_s
        self._silence_fade_duration_s = silence_fade_duration_s
        self._active_alpha = active_alpha
        self._amplitude_alpha_floor = amplitude_alpha_floor
        self._line_width_amplitude_scale = line_width_amplitude_scale
        self._amplitude_iir_alpha = amplitude_iir_alpha
        self._amplitude_smoothed = 0.0

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

        base_alpha = _silence_alpha(
            mtime,
            time.time(),
            fade_after_s=self._silence_fade_after_s,
            fade_duration_s=self._silence_fade_duration_s,
            active_alpha=self._active_alpha,
        )
        if base_alpha <= 0.0:
            return

        amplitude = _amplitude_normalized(samples)
        # One-pole IIR — feeds the alpha + line-width MODULATIONS only.
        # The waveform draw below uses the raw samples because that
        # surface IS the audio. Mirrors the sierpinski IIR pattern (#2639).
        self._amplitude_smoothed = (
            self._amplitude_smoothed * (1.0 - self._amplitude_iir_alpha)
            + amplitude * self._amplitude_iir_alpha
        )
        alpha = _amplitude_scaled_alpha(
            base_alpha,
            self._amplitude_smoothed,
            floor=self._amplitude_alpha_floor,
        )

        pkg = get_active_package() or _fallback_package()
        r, g, b, a = _resolve_waveform_tint(pkg, alpha)

        cr.save()
        line_width = self._line_width + self._amplitude_smoothed * self._line_width_amplitude_scale
        cr.set_line_width(line_width)
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
