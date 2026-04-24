"""Regenerate the LAB stops for the ``mirc-16-standard`` scrim palette.

Reads ``assets/aesthetic-library/bitchx/colors/mirc16.yaml`` and prints the
16 ``{t, lab: [L, a, b]}`` gradient_map stops the way they appear in
``presets/scrim_palettes/registry.yaml`` under ``mirc-16-standard``.

Run after any change to the source palette YAML; copy the printed block
into the registry. The palette registry loader does NOT do sRGB→LAB at
runtime (registry loads stay pure data) — this script is the authoring
bridge.

Usage::

    uv run python scripts/bin/_mirc16_to_lab.py

Pipeline: sRGB → linear RGB (gamma 2.4 with knee) → XYZ (D65, 2°) → CIE-LAB
following the standard formulas. Round to 2 decimal places to keep the
registry YAML readable; round-trip tolerance pinned at ±1/255 per channel
in ``tests/test_mirc16_palette.py``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_YAML = REPO_ROOT / "assets" / "aesthetic-library" / "bitchx" / "colors" / "mirc16.yaml"

# D65 white point (CIE 1931 2° observer), normalized so Y=1.
XN, YN, ZN = 0.95047, 1.00000, 1.08883


def srgb_decode(c: float) -> float:
    """Inverse sRGB gamma."""
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def lab_f(t: float) -> float:
    delta = 6.0 / 29.0
    if t > delta**3:
        return t ** (1.0 / 3.0)
    return (t / (3.0 * delta * delta)) + (4.0 / 29.0)


def hex_to_lab(hex_str: str) -> tuple[float, float, float]:
    s = hex_str.lstrip("#")
    r = srgb_decode(int(s[0:2], 16) / 255.0)
    g = srgb_decode(int(s[2:4], 16) / 255.0)
    b = srgb_decode(int(s[4:6], 16) / 255.0)
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    fx, fy, fz = lab_f(x / XN), lab_f(y / YN), lab_f(z / ZN)
    return (
        round(116.0 * fy - 16.0, 2),
        round(500.0 * (fx - fy), 2),
        round(200.0 * (fy - fz), 2),
    )


def main() -> None:
    data = yaml.safe_load(SOURCE_YAML.read_text(encoding="utf-8"))
    slots = data["slots"]
    keys = sorted(slots.keys())  # "00" .. "15"
    print("# Paste under mirc-16-standard.curve.params.stops:")
    for slot_key in keys:
        entry = slots[slot_key]
        L, a, b = hex_to_lab(entry["hex"])
        t = int(slot_key) / 15.0
        print(
            f"  - {{t: {t:.4f}, lab: [{L:>6.2f}, {a:>6.2f}, {b:>7.2f}]}}  # slot {slot_key} {entry['name']}"
        )


if __name__ == "__main__":
    main()
