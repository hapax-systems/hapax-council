"""HARDM (Hapax Avatar Representational Dot-Matrix) — 16×16 signal grid.

HOMAGE follow-on #121. Spec:
``docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md``.

A 256×256 px CP437-raster avatar-readout. Each of the 256 cells is a
16×16 px dot bound to a real-time system signal. Cells colour-code
their signal state using the **active HomagePackage's palette** (BitchX
mIRC-16 by default): grey idle skeleton, family-keyed accent on
activity, accent-red for stress / overflow / staleness.

The consumer here reads
``/dev/shm/hapax-compositor/hardm-cell-signals.json``. The publisher
lives in ``scripts/hardm-publish-signals.py`` (systemd-timer driven).
If the file is absent or malformed every cell falls back to idle.

Package-invariant geometry: the grid never changes shape. Palette
swaps with :func:`set_active_package` and recolour immediately.

Source id: ``hardm_dot_matrix``. Placement via Layout JSON; the
canonical assignment is upper-right (x=1600, y=20, 256×256).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)


# ── Grid geometry (package-invariant per spec §2) ─────────────────────────

CELL_SIZE_PX: int = 16
GRID_ROWS: int = 16
GRID_COLS: int = 16
TOTAL_CELLS: int = GRID_ROWS * GRID_COLS  # 256
SURFACE_W: int = CELL_SIZE_PX * GRID_COLS  # 256
SURFACE_H: int = CELL_SIZE_PX * GRID_ROWS  # 256


# ── Signal inventory (spec §3). 16 primary signals, one per row. ──────────

SIGNAL_NAMES: tuple[str, ...] = (
    "midi_active",
    "vad_speech",
    "room_occupancy",
    "ir_person_detected",
    "watch_hr",
    "bt_phone",
    "kde_connect",
    "ambient_sound",
    "screen_focus",
    "director_stance",
    "consent_gate",
    "stimmung_energy",
    "shader_energy",
    "reverie_pass",
    "degraded_stream",
    "homage_package",
)


# ── Signal → family accent role mapping (spec §5). ────────────────────────
# The 16 primary signals are grouped into five HOMAGE palette families.
# Cell hue stays locked to the family; intensity is expressed via alpha.

_SIGNAL_FAMILY_ROLE: dict[str, str] = {
    # timing
    "midi_active": "accent_cyan",
    # operator
    "vad_speech": "accent_green",
    "watch_hr": "accent_green",
    "bt_phone": "accent_green",
    "kde_connect": "accent_green",
    "screen_focus": "accent_green",
    # perception
    "room_occupancy": "accent_yellow",
    "ir_person_detected": "accent_yellow",
    "ambient_sound": "accent_yellow",
    # cognition
    "director_stance": "accent_magenta",
    "stimmung_energy": "accent_magenta",
    "shader_energy": "accent_magenta",
    "reverie_pass": "accent_magenta",
    # governance
    "consent_gate": "bright",
    "degraded_stream": "bright",
    "homage_package": "bright",
}


# ── Signal-state vocabulary ────────────────────────────────────────────────
# A signal's raw value collapses into one of three render states:
#   - idle     → palette.muted (grey skeleton)
#   - active   → family accent role (with alpha modulation)
#   - stress   → palette.accent_red (override, regardless of family)
# Multi-level signals (level3/level4) vary alpha inside ``active`` state.

SIGNAL_FILE: Path = Path("/dev/shm/hapax-compositor/hardm-cell-signals.json")

# Staleness cutoff for the signal payload. The publisher timer fires every
# 2 s (``hapax-hardm-publisher.timer``); this 3 s cutoff gives a 50 %
# margin for publisher cold-start / IO latency so cells don't flicker to
# stress during routine scheduling jitter. See beta audit F-AUDIT-1062-2.
STALENESS_CUTOFF_S: float = 3.0


# ── Consumer ──────────────────────────────────────────────────────────────


def _read_signals(path: Path | None = None, now: float | None = None) -> dict[str, Any]:
    """Read the signal payload. Returns ``{}`` on any failure.

    Default path resolves from ``SIGNAL_FILE`` at *call time* so tests
    (and any runtime override) can monkeypatch the module-level constant
    without having to thread a path through the render call.

    Staleness: if the payload's ``generated_at`` is older than
    :data:`STALENESS_CUTOFF_S`, return ``{}`` (all cells render idle)
    rather than surfacing arbitrarily old values. ``now`` is injectable
    for deterministic tests; defaults to ``time.time()``.
    """
    target = path if path is not None else SIGNAL_FILE
    try:
        if not target.exists():
            return {}
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        log.debug("hardm-cell-signals read failed", exc_info=True)
        return {}
    if not isinstance(data, dict):
        return {}
    generated_at = data.get("generated_at")
    if isinstance(generated_at, (int, float)):
        current = now if now is not None else time.time()
        if current - float(generated_at) > STALENESS_CUTOFF_S:
            return {}
    signals = data.get("signals")
    if not isinstance(signals, dict):
        return {}
    return signals


def _classify_cell(signal_name: str, value: Any) -> tuple[str, float]:
    """Return ``(role, alpha)`` for a (signal, value) tuple.

    ``role`` is one of:
      - ``"muted"`` (idle)
      - a family accent role (``accent_cyan`` / ``_green`` / ``_yellow`` /
        ``_magenta`` / ``bright``)
      - ``"accent_red"`` (stress)

    ``alpha`` scales family-accent intensity 0.4–1.0 so multi-level signals
    read as graduated glow without breaking BitchX hue lock (spec §5).

    Stress conditions:
      * numeric overflow (``>= 1.0`` where the signal is level4-bucketed
        meaningfully — we treat ``stress`` / ``error`` string values as
        the explicit signal)
      * the value ``{"stress": True}`` / ``"stress"``
      * signal not present in payload for ``consent_gate`` (fail-closed)
    """
    if value is None:
        # Missing signal — governance signals fail closed.
        if signal_name == "consent_gate":
            return ("accent_red", 1.0)
        return ("muted", 1.0)

    # Explicit stress markers
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("stress", "error", "overflow", "blocked", "stale"):
            return ("accent_red", 1.0)

    if isinstance(value, dict):
        if value.get("stress") is True or value.get("error") is True:
            return ("accent_red", 1.0)

    family_role = _SIGNAL_FAMILY_ROLE.get(signal_name, "bright")

    # Boolean-like signals
    if isinstance(value, bool):
        if value:
            return (family_role, 1.0)
        return ("muted", 1.0)

    # Numeric signals — interpret as intensity 0.0..1.0 (clamped). Values
    # strictly greater than 1.0 are treated as stress (overflow).
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        if v > 1.0:
            return ("accent_red", 1.0)
        if v <= 0.0:
            return ("muted", 1.0)
        # Quantise into 4 alpha levels for graduated glow.
        if v < 0.25:
            return (family_role, 0.30)
        if v < 0.55:
            return (family_role, 0.55)
        if v < 0.80:
            return (family_role, 0.80)
        return (family_role, 1.00)

    # String categorical (e.g. "nominal" / "cautious" / "critical"). Map
    # stance-like values to roles; everything else renders active.
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("nominal", "ok", "idle", "off"):
            return ("muted", 1.0)
        if lowered in ("cautious", "seeking", "warn"):
            return (family_role, 0.7)
        if lowered in ("critical", "overflow", "degraded"):
            return ("accent_red", 1.0)
        return (family_role, 1.0)

    # Fallback — paint as active.
    return (family_role, 1.0)


def _signal_for_row(row: int) -> str:
    """Return the signal name bound to ``row`` (row-major layout)."""
    if 0 <= row < len(SIGNAL_NAMES):
        return SIGNAL_NAMES[row]
    return ""


# ── Cairo source ──────────────────────────────────────────────────────────


class HardmDotMatrix(HomageTransitionalSource):
    """16×16 signal-bound dot-matrix avatar ward.

    Each row is bound to one signal. Every column in that row is a
    repeated stamp of the same signal state — the grid reads as 16
    horizontal signal-bars, but the raster grammar (square cells, no
    gutters, no anti-aliasing) is preserved so the avatar looks like a
    CP437 stamp rather than a progress bar.

    When row 15 (``homage_package``) is bound, the cell cycles accent
    hue per registered package; other rows stay locked to their family
    accent.
    """

    def __init__(self) -> None:
        super().__init__(source_id="hardm_dot_matrix")

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pkg = get_active_package()
        if pkg is None:
            # Consent-safe layout — HOMAGE disabled. Render transparent.
            return

        signals = _read_signals()

        # Flat background so cells sit on the CP437 skeleton rather than
        # floating against the shader surface. Uses the package's
        # ``background`` role — no hardcoded hex.
        bg_rgba = pkg.resolve_colour("background")
        cr.save()
        cr.set_source_rgba(*bg_rgba)
        cr.rectangle(0, 0, SURFACE_W, SURFACE_H)
        cr.fill()
        cr.restore()

        # Paint 256 cells. Row-major: cell_0 = top-left.
        for row in range(GRID_ROWS):
            signal_name = _signal_for_row(row)
            value = signals.get(signal_name) if signal_name else None
            role, alpha = _classify_cell(signal_name, value)
            r, g, b, a = pkg.resolve_colour(role)  # type: ignore[arg-type]
            cell_alpha = a * alpha
            for col in range(GRID_COLS):
                x = col * CELL_SIZE_PX
                y = row * CELL_SIZE_PX
                # 1 px muted-grey rule between cells (CP437-thin, §2).
                cr.set_source_rgba(r, g, b, cell_alpha)
                cr.rectangle(
                    x + 1,
                    y + 1,
                    CELL_SIZE_PX - 2,
                    CELL_SIZE_PX - 2,
                )
                cr.fill()


__all__ = [
    "CELL_SIZE_PX",
    "GRID_COLS",
    "GRID_ROWS",
    "HardmDotMatrix",
    "SIGNAL_FILE",
    "SIGNAL_NAMES",
    "STALENESS_CUTOFF_S",
    "SURFACE_H",
    "SURFACE_W",
    "TOTAL_CELLS",
    "_classify_cell",
    "_read_signals",
    "_signal_for_row",
]
