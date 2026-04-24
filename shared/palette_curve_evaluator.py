"""Palette curve evaluator — sRGB ↔ LAB + six curve modes.

Phase 3b of the video-container epic. Takes a
:class:`shared.palette_family.PaletteResponseCurve` plus an input
pixel in LAB and produces an output pixel in LAB. The six curve
modes are implemented against a documented reference, not against a
specific shader — the scrim GPU renderer (Phase 5+) will embed
equivalent math in WGSL, and keeping the CPU evaluator authoritative
lets tests pin cross-surface behaviour before the shader ships.

## Colour math

sRGB ↔ CIE-LAB (D65 illuminant) with the standard gamma curve:

- ``rgb_to_lab`` expects sRGB floats in ``[0, 1]``; returns LAB with
  L* in ``[0, 100]`` and a*/b* roughly in ``[-128, 127]``.
- ``lab_to_rgb`` is the inverse; out-of-gamut results are clamped to
  ``[0, 1]`` at the return (caller decides whether to soft-clip first
  via :attr:`PaletteResponseCurve.clip_s_curve`).
- Both routines are pure Python (no numpy). The evaluator runs on a
  per-pixel sample basis in the CPU path; numpy vectorisation is a
  Phase 3c optimisation when the scrim sampler reads a kernel of
  pixels rather than a single sample.

## Curve modes

Each mode reads a specific subset of ``curve.params``. Unknown keys
are ignored; missing required keys produce a :class:`CurveParamError`.

- ``identity``: no modulation.
- ``lab_shift``: output = input + (``delta_l``, ``delta_a``, ``delta_b``).
- ``duotone``: output = lerp(``stop_low``, ``stop_high``, L_norm)
  where L_norm = L* / 100. Params accept either in-line LAB lists or
  fall back to the palette's dominant/accent anchors (see
  :func:`apply_palette`).
- ``gradient_map``: output = multi-stop LAB lookup keyed by L*/100.
  Stops are authored as ``[{t: 0.0, lab: [...]}, ...]``.
- ``hue_rotate``: LAB → LCh, rotate H by ``degrees``, LCh → LAB.
- ``channel_mix``: round-trips LAB → RGB, applies the 3×3 matrix
  declared by 9 float params (rr, rg, rb, gr, gg, gb, br, bg, bb),
  then RGB → LAB.

## Post-processing

Every mode's result passes through the curve's
``preserve_luminance`` (replaces output L* with input L*) and
``clip_s_curve`` (clamps L* to a band) options. These apply
uniformly regardless of mode.
"""

from __future__ import annotations

import math

from shared.palette_family import (
    LabTriple,
    PaletteResponseCurve,
    ScrimPalette,
)

# sRGB → linear RGB → XYZ (D65) matrix, row-major.
_M_RGB_TO_XYZ = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)

# XYZ → linear RGB inverse matrix.
_M_XYZ_TO_RGB = (
    (3.2404542, -1.5371385, -0.4985314),
    (-0.9692660, 1.8760108, 0.0415560),
    (0.0556434, -0.2040259, 1.0572252),
)

# D65 reference white (LAB standard).
_XN = 0.95047
_YN = 1.00000
_ZN = 1.08883


class CurveParamError(ValueError):
    """Raised when a curve's params don't match its declared mode."""


# ---------------------------------------------------------------------------
# sRGB ↔ LAB
# ---------------------------------------------------------------------------


def _srgb_to_linear(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(v: float) -> float:
    return v * 12.92 if v <= 0.0031308 else 1.055 * (v ** (1.0 / 2.4)) - 0.055


def _f(t: float) -> float:
    # LAB nonlinearity.
    delta = 6.0 / 29.0
    if t > delta**3:
        return t ** (1.0 / 3.0)
    return t / (3.0 * delta**2) + 4.0 / 29.0


def _f_inv(t: float) -> float:
    delta = 6.0 / 29.0
    if t > delta:
        return t**3
    return 3.0 * delta**2 * (t - 4.0 / 29.0)


def rgb_to_lab(r: float, g: float, b: float) -> LabTriple:
    """Convert sRGB (each in ``[0, 1]``) to CIE-LAB under D65."""
    rl = _srgb_to_linear(r)
    gl = _srgb_to_linear(g)
    bl = _srgb_to_linear(b)
    x = _M_RGB_TO_XYZ[0][0] * rl + _M_RGB_TO_XYZ[0][1] * gl + _M_RGB_TO_XYZ[0][2] * bl
    y = _M_RGB_TO_XYZ[1][0] * rl + _M_RGB_TO_XYZ[1][1] * gl + _M_RGB_TO_XYZ[1][2] * bl
    z = _M_RGB_TO_XYZ[2][0] * rl + _M_RGB_TO_XYZ[2][1] * gl + _M_RGB_TO_XYZ[2][2] * bl
    fx = _f(x / _XN)
    fy = _f(y / _YN)
    fz = _f(z / _ZN)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b_star = 200.0 * (fy - fz)
    return (L, a, b_star)


def lab_to_rgb(L: float, a: float, b: float) -> tuple[float, float, float]:
    """Convert CIE-LAB to sRGB. Out-of-gamut values are clamped to ``[0, 1]``."""
    fy = (L + 16.0) / 116.0
    fx = a / 500.0 + fy
    fz = fy - b / 200.0
    x = _XN * _f_inv(fx)
    y = _YN * _f_inv(fy)
    z = _ZN * _f_inv(fz)
    rl = _M_XYZ_TO_RGB[0][0] * x + _M_XYZ_TO_RGB[0][1] * y + _M_XYZ_TO_RGB[0][2] * z
    gl = _M_XYZ_TO_RGB[1][0] * x + _M_XYZ_TO_RGB[1][1] * y + _M_XYZ_TO_RGB[1][2] * z
    bl = _M_XYZ_TO_RGB[2][0] * x + _M_XYZ_TO_RGB[2][1] * y + _M_XYZ_TO_RGB[2][2] * z
    r = max(0.0, min(1.0, _linear_to_srgb(rl)))
    g = max(0.0, min(1.0, _linear_to_srgb(gl)))
    b_out = max(0.0, min(1.0, _linear_to_srgb(bl)))
    return (r, g, b_out)


# ---------------------------------------------------------------------------
# Per-mode evaluators
# ---------------------------------------------------------------------------


def _lerp_lab(a_lab: LabTriple, b_lab: LabTriple, t: float) -> LabTriple:
    t = max(0.0, min(1.0, t))
    return (
        a_lab[0] + (b_lab[0] - a_lab[0]) * t,
        a_lab[1] + (b_lab[1] - a_lab[1]) * t,
        a_lab[2] + (b_lab[2] - a_lab[2]) * t,
    )


def _as_lab(value: object, name: str) -> LabTriple:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise CurveParamError(f"{name}: expected 3-element LAB triple, got {value!r}")
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError) as exc:
        raise CurveParamError(f"{name}: non-numeric LAB entry in {value!r}") from exc


def _mode_identity(curve: PaletteResponseCurve, input_lab: LabTriple) -> LabTriple:
    del curve  # unused
    return input_lab


def _mode_lab_shift(curve: PaletteResponseCurve, input_lab: LabTriple) -> LabTriple:
    p = curve.params
    dl = float(p.get("delta_l", 0.0))
    da = float(p.get("delta_a", 0.0))
    db = float(p.get("delta_b", 0.0))
    return (input_lab[0] + dl, input_lab[1] + da, input_lab[2] + db)


def _mode_duotone(
    curve: PaletteResponseCurve,
    input_lab: LabTriple,
    palette: ScrimPalette | None,
) -> LabTriple:
    p = curve.params
    if "stop_low" in p:
        lo = _as_lab(p["stop_low"], "stop_low")
    elif palette is not None:
        lo = palette.accent_lab
    else:
        raise CurveParamError("duotone: stop_low missing and no palette provided")
    if "stop_high" in p:
        hi = _as_lab(p["stop_high"], "stop_high")
    elif palette is not None:
        hi = palette.dominant_lab
    else:
        raise CurveParamError("duotone: stop_high missing and no palette provided")
    # Map input L* (0..100) to blend position.
    t = max(0.0, min(1.0, input_lab[0] / 100.0))
    return _lerp_lab(lo, hi, t)


def _mode_gradient_map(curve: PaletteResponseCurve, input_lab: LabTriple) -> LabTriple:
    raw_stops = curve.params.get("stops")
    if not isinstance(raw_stops, list) or len(raw_stops) < 2:
        raise CurveParamError(
            "gradient_map: params.stops must be a list of at least 2 {t, lab} entries"
        )
    stops: list[tuple[float, LabTriple]] = []
    for idx, stop in enumerate(raw_stops):
        if not isinstance(stop, dict) or "t" not in stop or "lab" not in stop:
            raise CurveParamError(f"gradient_map: stops[{idx}] must be {{t, lab}} dict")
        try:
            tval = float(stop["t"])
        except (TypeError, ValueError) as exc:
            raise CurveParamError(f"gradient_map: stops[{idx}].t non-numeric") from exc
        stops.append((tval, _as_lab(stop["lab"], f"stops[{idx}].lab")))
    stops.sort(key=lambda s: s[0])
    t = max(0.0, min(1.0, input_lab[0] / 100.0))
    # Clamp to endpoints.
    if t <= stops[0][0]:
        return stops[0][1]
    if t >= stops[-1][0]:
        return stops[-1][1]
    # Find bracketing stops.
    for i in range(1, len(stops)):
        if t <= stops[i][0]:
            t_a, lab_a = stops[i - 1]
            t_b, lab_b = stops[i]
            # Normalise t into the segment.
            span = t_b - t_a
            local = (t - t_a) / span if span > 0.0 else 0.0
            return _lerp_lab(lab_a, lab_b, local)
    return stops[-1][1]


def _mode_hue_rotate(curve: PaletteResponseCurve, input_lab: LabTriple) -> LabTriple:
    degrees = float(curve.params.get("degrees", 0.0))
    L, a, b = input_lab
    # LAB → LCh
    C = math.sqrt(a * a + b * b)
    h = math.degrees(math.atan2(b, a))
    h_rot = h + degrees
    # LCh → LAB
    rad = math.radians(h_rot)
    return (L, C * math.cos(rad), C * math.sin(rad))


def _mode_channel_mix(curve: PaletteResponseCurve, input_lab: LabTriple) -> LabTriple:
    p = curve.params
    try:
        m = (
            (float(p["rr"]), float(p["rg"]), float(p["rb"])),
            (float(p["gr"]), float(p["gg"]), float(p["gb"])),
            (float(p["br"]), float(p["bg"]), float(p["bb"])),
        )
    except KeyError as exc:
        raise CurveParamError(f"channel_mix: missing matrix param {exc.args[0]!r}") from exc
    r, g, b = lab_to_rgb(*input_lab)
    r2 = m[0][0] * r + m[0][1] * g + m[0][2] * b
    g2 = m[1][0] * r + m[1][1] * g + m[1][2] * b
    b2 = m[2][0] * r + m[2][1] * g + m[2][2] * b
    r2 = max(0.0, min(1.0, r2))
    g2 = max(0.0, min(1.0, g2))
    b2 = max(0.0, min(1.0, b2))
    return rgb_to_lab(r2, g2, b2)


# ---------------------------------------------------------------------------
# Top-level evaluator
# ---------------------------------------------------------------------------


def evaluate(
    curve: PaletteResponseCurve,
    input_lab: LabTriple,
    palette: ScrimPalette | None = None,
) -> LabTriple:
    """Apply ``curve`` to ``input_lab`` and return the output LAB.

    ``palette`` is optional: ``duotone`` falls back to the palette's
    dominant/accent anchors when ``stop_low``/``stop_high`` aren't in
    params. Other modes ignore it. Callers who always author complete
    params may pass ``None``.
    """
    mode = curve.mode
    if mode == "identity":
        out = _mode_identity(curve, input_lab)
    elif mode == "lab_shift":
        out = _mode_lab_shift(curve, input_lab)
    elif mode == "duotone":
        out = _mode_duotone(curve, input_lab, palette)
    elif mode == "gradient_map":
        out = _mode_gradient_map(curve, input_lab)
    elif mode == "hue_rotate":
        out = _mode_hue_rotate(curve, input_lab)
    elif mode == "channel_mix":
        out = _mode_channel_mix(curve, input_lab)
    else:
        raise CurveParamError(f"unknown curve mode {mode!r}")

    # Post-processing (applies uniformly regardless of mode).
    if curve.preserve_luminance:
        out = (input_lab[0], out[1], out[2])
    if curve.clip_s_curve is not None:
        lo, hi = curve.clip_s_curve
        out = (max(lo, min(hi, out[0])), out[1], out[2])
    return out


def apply_palette(palette: ScrimPalette, input_lab: LabTriple) -> LabTriple:
    """Shortcut: evaluate ``palette.curve`` with ``palette`` as fallback source."""
    return evaluate(palette.curve, input_lab, palette=palette)


__all__ = [
    "CurveParamError",
    "apply_palette",
    "evaluate",
    "lab_to_rgb",
    "rgb_to_lab",
]
