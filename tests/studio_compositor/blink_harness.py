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


__all__ = [
    "DEFAULT_MAX_RATE_PER_500MS",
    "BlinkAuditResult",
    "audit_ward_blink",
    "mean_luminance",
]
