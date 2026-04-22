"""Luminance-delta harness for ward blink-threshold regression tests.

Phase B of lssh-001 (operator 2026-04-21: "way too much BLINKING for
the homage wards. it's not even an interesting behavior and it is
extremely hard to look at"). Phase A (PR #1181) softened the
inverse-flash from 0.45→0.0 over 200 ms (linear) to 0.15→0.0 over
400 ms (cosine ease-out). Phase B (this module) is the regression
gate that prevents the next equivalent regression from sliding back
in silently.

The audit heuristic, made operational here:

  No visual element changes mean luminance by more than 40 % faster
  than once every 500 ms.

Implementation: render N frames of a ward at a fixed cadence into a
cairo ARGB32 surface, compute mean luminance per frame, then compute
the largest 500 ms-equivalent change-rate across the sequence. If
the rate exceeds the threshold the test fails with a legible
diagnostic naming the ward and the offending pair of frames.

Mean luminance uses Rec. 709 weights (0.2126·R + 0.7152·G +
0.0722·B), normalized to [0, 1] over the rendered area. Premultiplied
alpha is divided out per pixel before weighting so a transparent
half-frame doesn't read as half-luminance — the harness measures
what the pixel WOULD show against the standard ground, not the raw
ARGB32 byte values.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Rec. 709 luminance weights. Same standard the rest of the broadcast
# pipeline uses; matches the operator's "is this thing flashing" check
# rather than any agent-internal alpha math.
_LUMA_R: float = 0.2126
_LUMA_G: float = 0.7152
_LUMA_B: float = 0.0722

# Default blink threshold from lssh-001. 40 % luminance change per 500
# ms is the bar; tighter wards (chrome that needs to be readable for
# minutes at a time) can pass a tighter ``max_rate_per_500ms``.
DEFAULT_MAX_RATE_PER_500MS: float = 0.40


@dataclass(frozen=True)
class BlinkAuditResult:
    """One ward's worst-window measurement.

    ``max_rate_per_500ms`` is the largest |Δ luminance| / 0.5 s
    sample across the rendered sequence. ``worst_pair_seconds`` is
    the (t_a, t_b) of the frames that produced it; useful when
    debugging a regression to know exactly which animation phase is
    the offender.
    """

    ward_name: str
    frame_count: int
    mean_luminance_min: float
    mean_luminance_max: float
    max_rate_per_500ms: float
    worst_pair_seconds: tuple[float, float]
    threshold: float

    @property
    def passes(self) -> bool:
        return self.max_rate_per_500ms <= self.threshold

    def diagnostic(self) -> str:
        verdict = "OK" if self.passes else "BLINK"
        return (
            f"[{verdict}] {self.ward_name}: max change-rate "
            f"{self.max_rate_per_500ms:.3f} per 500 ms "
            f"(limit {self.threshold:.3f}); "
            f"luminance range [{self.mean_luminance_min:.3f}, "
            f"{self.mean_luminance_max:.3f}]; "
            f"worst pair t={self.worst_pair_seconds[0]:.3f}s vs "
            f"t={self.worst_pair_seconds[1]:.3f}s; "
            f"frames={self.frame_count}"
        )


def mean_luminance(surface: Any) -> float:
    """Mean Rec. 709 luminance over a cairo ARGB32 surface, in [0, 1].

    Cairo ARGB32 pixels are premultiplied alpha, native-endian. On
    little-endian (the only platform we run) the byte order in memory
    is BGRA. Premultiplied alpha is divided out per pixel so a
    transparent half-frame doesn't artificially halve the luminance.

    Returns 0.0 for fully-transparent surfaces (every pixel α=0) so
    the caller can tell "blank surface" apart from "black surface."
    """
    width = surface.get_width()
    height = surface.get_height()
    stride = surface.get_stride()
    data = bytes(surface.get_data())
    total = 0.0
    visible = 0
    for y in range(height):
        row = y * stride
        for x in range(width):
            offset = row + x * 4
            b = data[offset]
            g = data[offset + 1]
            r = data[offset + 2]
            a = data[offset + 3]
            if a == 0:
                continue
            inv_a = 255.0 / a
            r_un = min(255.0, r * inv_a)
            g_un = min(255.0, g * inv_a)
            b_un = min(255.0, b * inv_a)
            luma = (_LUMA_R * r_un + _LUMA_G * g_un + _LUMA_B * b_un) / 255.0
            total += luma * (a / 255.0)
            visible += 1
    if visible == 0:
        return 0.0
    return total / visible


def audit_ward_blink(
    ward_name: str,
    render_fn: Callable[[float], Any],
    *,
    duration_s: float = 6.0,
    frame_interval_s: float = 0.05,
    max_rate_per_500ms: float = DEFAULT_MAX_RATE_PER_500MS,
) -> BlinkAuditResult:
    """Render the ward across ``duration_s`` and measure the worst
    500 ms-equivalent luminance change-rate.

    ``render_fn(t)`` must return a fresh ``cairo.ImageSurface`` for
    the wall-clock time ``t``. The harness is responsible for
    deciding cadence (default 50 ms = 20 Hz, matching the compositor's
    overlay tick); the ward is responsible for whatever animation
    state needs to advance between frames.

    The 500 ms window is computed as |L(t_b) - L(t_a)| × (0.5 / (t_b
    - t_a)) for every adjacent pair of sampled frames, so the bound
    is consistent with the operator's "no luminance change > 40 %
    faster than once every 500 ms" heuristic regardless of what
    cadence the harness sampled at.
    """
    if frame_interval_s <= 0.0:
        raise ValueError("frame_interval_s must be > 0")
    if duration_s <= frame_interval_s:
        raise ValueError("duration_s must exceed frame_interval_s")
    n_frames = max(2, int(math.ceil(duration_s / frame_interval_s)))

    luminances: list[float] = []
    for i in range(n_frames):
        t = i * frame_interval_s
        surface = render_fn(t)
        luminances.append(mean_luminance(surface))

    max_rate = 0.0
    worst_pair = (0.0, 0.0)
    for i in range(1, n_frames):
        delta = abs(luminances[i] - luminances[i - 1])
        rate_per_500ms = delta * (0.5 / frame_interval_s)
        if rate_per_500ms > max_rate:
            max_rate = rate_per_500ms
            worst_pair = ((i - 1) * frame_interval_s, i * frame_interval_s)

    return BlinkAuditResult(
        ward_name=ward_name,
        frame_count=n_frames,
        mean_luminance_min=min(luminances),
        mean_luminance_max=max(luminances),
        max_rate_per_500ms=max_rate,
        worst_pair_seconds=worst_pair,
        threshold=max_rate_per_500ms,
    )


# ── Ward-vs-background contrast (lssh-005) ───────────────────────────────
# Phase B of lssh-001 measured the ward in isolation. lssh-005 asks the
# next question: when the same ward composites OVER a bright shader
# field, do its emissive glyphs still read against the background, or
# does the shader overpower the chrome? Small-area wards (stance ~4 k
# px², thinking ~7.5 k px²) sit at the highest risk per the
# 2026-04-21 per-ward opacity audit even after PR #1167 promoted them
# to surface-scrim.
#
# Threshold rationale: WCAG 2.1 §1.4.3 sets 4.5 : 1 luminance
# contrast for normal-size text and 3.0 : 1 for large text + UI
# components. Hapax chrome wards sit between those — they are small
# but are not body text, and the operator's goal is "remain legible
# against worst-case shader preset" rather than full WCAG-AA. The
# default here is 3.0 : 1 (WCAG-AA UI). A ward that fails at 3.0
# needs the outline-bump / size-bump mitigation called out in
# lssh-005 acceptance criteria.

# WCAG-style luminance ratio threshold. Wards below this against the
# tested background fail the contrast audit.
DEFAULT_MIN_CONTRAST_RATIO: float = 3.0


@dataclass(frozen=True)
class WardContrastResult:
    """One ward's luminance against a synthetic background.

    ``contrast_ratio`` is the WCAG luminance ratio
    ``(lighter + 0.05) / (darker + 0.05)`` between the ward's mean
    foreground luminance and the background's mean luminance. Always
    ≥ 1.0; higher = more contrast.
    """

    ward_name: str
    background_name: str
    ward_luminance: float
    background_luminance: float
    contrast_ratio: float
    threshold: float

    @property
    def passes(self) -> bool:
        return self.contrast_ratio >= self.threshold

    def diagnostic(self) -> str:
        verdict = "OK" if self.passes else "OVERPOWERED"
        return (
            f"[{verdict}] {self.ward_name} vs {self.background_name}: "
            f"contrast {self.contrast_ratio:.2f} : 1 "
            f"(min {self.threshold:.1f} : 1); "
            f"ward luminance {self.ward_luminance:.3f}, "
            f"background luminance {self.background_luminance:.3f}"
        )


def _wcag_contrast_ratio(luminance_a: float, luminance_b: float) -> float:
    """WCAG 2.1 contrast ratio: (lighter + 0.05) / (darker + 0.05)."""
    if luminance_a < luminance_b:
        luminance_a, luminance_b = luminance_b, luminance_a
    return (luminance_a + 0.05) / (luminance_b + 0.05)


def synthetic_bright_background(
    width: int,
    height: int,
    *,
    luminance: float = 0.85,
) -> Any:
    """Render a uniform bright background as a stand-in for worst-case
    halftone / chromatic shader output.

    The compositor's halftone preset typically averages around 0.80
    luminance over the chrome region; defaulting slightly higher
    (0.85) gives a deliberately worst-case test. Returns a cairo
    ImageSurface the caller composites the ward over via
    ``set_source_surface`` + ``paint``.
    """
    import cairo

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.set_source_rgba(luminance, luminance, luminance, 1.0)
    cr.rectangle(0, 0, width, height)
    cr.fill()
    surface.flush()
    return surface


def audit_ward_against_background(
    ward_name: str,
    render_fn: Callable[[float], Any],
    background_factory: Callable[[int, int], Any],
    *,
    width: int,
    height: int,
    background_name: str = "synthetic-bright",
    sample_at: float = 1.0,
    min_contrast_ratio: float = DEFAULT_MIN_CONTRAST_RATIO,
) -> WardContrastResult:
    """Render the ward, composite it over a synthetic background, and
    measure WCAG luminance contrast.

    Approach: the ward's render produces emissive glyphs that already
    composite alpha-correctly against any underlying field. We sample
    the ward at a single representative time (``sample_at``) and
    measure mean luminance over only the pixels the ward TOUCHES
    (alpha > 0). That gives the foreground signal. The background is
    rendered separately at full size and measured the same way. The
    contrast ratio between those two means is the audit number.

    Why this shape rather than a full composite: WCAG ratios are
    foreground-vs-background; the ward's glow does want to be lighter
    than the background, but the bright bloom alone is not what the
    viewer reads — the glyph centers are. Measuring ward-pixel-only
    luminance approximates the brightest ward feature (centre dots
    and outline glyphs) which is the operator's actual legibility
    surface.
    """
    import cairo

    ward_surface = render_fn(sample_at)
    bg_surface = background_factory(width, height)

    ward_only_luminance = _mean_luminance_of_alpha_pixels(ward_surface)
    bg_luminance = mean_luminance(bg_surface)
    ratio = _wcag_contrast_ratio(ward_only_luminance, bg_luminance)

    # Suppress unused-import false positive in environments where
    # cairo's import side effects are required for the rendered
    # surfaces but pyright cannot tell.
    del cairo

    return WardContrastResult(
        ward_name=ward_name,
        background_name=background_name,
        ward_luminance=ward_only_luminance,
        background_luminance=bg_luminance,
        contrast_ratio=ratio,
        threshold=min_contrast_ratio,
    )


def _mean_luminance_of_alpha_pixels(surface: Any) -> float:
    """Mean Rec. 709 luminance over pixels with alpha > 0 only.

    Differs from ``mean_luminance`` (which weights by alpha across
    every pixel of the surface). This variant treats transparent
    pixels as not-rendered and excludes them from the mean. Use this
    when measuring "what does the ward's foreground look like" rather
    than "what does the ward contribute to a composite background".
    """
    width = surface.get_width()
    height = surface.get_height()
    stride = surface.get_stride()
    data = bytes(surface.get_data())
    total = 0.0
    visible = 0
    for y in range(height):
        row = y * stride
        for x in range(width):
            offset = row + x * 4
            b = data[offset]
            g = data[offset + 1]
            r = data[offset + 2]
            a = data[offset + 3]
            if a == 0:
                continue
            inv_a = 255.0 / a
            r_un = min(255.0, r * inv_a)
            g_un = min(255.0, g * inv_a)
            b_un = min(255.0, b * inv_a)
            total += (_LUMA_R * r_un + _LUMA_G * g_un + _LUMA_B * b_un) / 255.0
            visible += 1
    if visible == 0:
        return 0.0
    return total / visible


__all__ = [
    "DEFAULT_MAX_RATE_PER_500MS",
    "DEFAULT_MIN_CONTRAST_RATIO",
    "BlinkAuditResult",
    "WardContrastResult",
    "audit_ward_against_background",
    "audit_ward_blink",
    "mean_luminance",
    "synthetic_bright_background",
]
