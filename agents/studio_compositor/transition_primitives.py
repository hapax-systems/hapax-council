"""Transition primitives — the visual moves between two preset graphs.

Phase 7 of the preset-variety plan (`docs/superpowers/plans/2026-04-20-preset-variety-plan.md`).
Each primitive takes the outgoing graph (may be ``None`` when no preset
is currently active) and the incoming graph, plus a ``writer`` callback
that takes a graph dict and mutates the live ``graph-mutation.json``
SHM file, plus a ``sleep`` callback so tests can run zero-cost. The
primitive is responsible for its own per-step pacing.

Five primitives cover the chain-level transition vocabulary
(research §5.5):

- ``fade_smooth`` — 12-step bounded-luminance handoff
- ``cut_hard`` — single-frame swap, no intermediate state
- ``netsplit_burst`` — quick low-luminance floor pulse + sharp re-fill
- ``ticker_scroll`` — sigmoid (S-curve) brightness ramp, perceptually
  distinct from the linear ``fade_smooth`` (slow start + slow end)
- ``dither_noise`` — two bounded shimmer writes before settling on in

All primitives are deterministic given fixed timing — the only
non-determinism is wall-clock ``sleep`` resolution under load. Tests
inject a capture-writer + no-op sleep and assert the expected
sequence of graph mutations.

Visual goal: each primitive should be distinguishable on /dev/video42
without coherent full-frame pumping, held-black frames, or high-frequency
alternation. Brightness curves below are bounded so transitions read as
surface changes while preserving camera geometry and ward legibility.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from typing import Final

# Type aliases for clarity.
Graph = dict
GraphWriter = Callable[[Graph], None]
SleepFn = Callable[[float], None]
TransitionFn = Callable[[Graph | None, Graph, GraphWriter, SleepFn], None]


# Pacing constants (ms). Tuned so total wall-clock runtime stays within
# the random_mode loop's ~2s transition budget regardless of which
# primitive is chosen.
FADE_STEPS: Final[int] = 12
FADE_STEP_MS: Final[int] = 100  # 12 × 100 = 1200 ms

NETSPLIT_OUT_STEPS: Final[int] = 2
NETSPLIT_IN_STEPS: Final[int] = 2
NETSPLIT_STEP_MS: Final[int] = 50
NETSPLIT_HOLD_MS: Final[int] = 150  # total ≈ 350 ms

TICKER_STEPS: Final[int] = 12
TICKER_STEP_MS: Final[int] = 100  # 12 × 100 = 1200 ms (sigmoid)

DITHER_FLIPS: Final[int] = 2
DITHER_STEP_MS: Final[int] = 220
MIN_TRANSITION_BRIGHTNESS: Final[float] = 0.85


# Names used by the affordance recruitment layer. Mirror the
# capability records in ``shared/compositional_affordances.py``.
TRANSITION_NAMES: Final[tuple[str, ...]] = (
    "transition.fade.smooth",
    "transition.cut.hard",
    "transition.netsplit.burst",
    "transition.ticker.scroll",
    "transition.dither.noise",
)


def _scale_colorgrade_brightness(graph: Graph, brightness: float) -> Graph:
    """Return a deep copy of ``graph`` with colorgrade brightness scaled.

    Identical to the historical ``apply_graph_with_brightness`` mutation
    — keeps the primitive set drop-in compatible with the random_mode
    SHM contract. Wards that don't expose a ``colorgrade`` node simply
    receive an unmodified copy (the brightness scale is a no-op).
    """
    g = json.loads(json.dumps(graph))
    for node in g.get("nodes", {}).values():
        if node.get("type") == "colorgrade":
            params = node.setdefault("params", {})
            params["brightness"] = params.get("brightness", 1.0) * brightness
            break
    return g


def _surface_safe_brightness(value: float) -> float:
    """Clamp transition brightness so graph handoffs cannot blank the frame."""

    return max(MIN_TRANSITION_BRIGHTNESS, value)


def fade_smooth(
    out: Graph | None,
    in_g: Graph,
    writer: GraphWriter,
    sleep: SleepFn = time.sleep,
) -> None:
    """12-step bounded-luminance handoff."""
    if out is not None:
        for i in range(FADE_STEPS):
            t = (i + 1) / FADE_STEPS
            brightness = 1.0 - (1.0 - MIN_TRANSITION_BRIGHTNESS) * t
            writer(_scale_colorgrade_brightness(out, _surface_safe_brightness(brightness)))
            sleep(FADE_STEP_MS / 1000.0)
    for i in range(FADE_STEPS):
        t = (i + 1) / FADE_STEPS
        brightness = MIN_TRANSITION_BRIGHTNESS + (1.0 - MIN_TRANSITION_BRIGHTNESS) * t
        writer(_scale_colorgrade_brightness(in_g, _surface_safe_brightness(brightness)))
        sleep(FADE_STEP_MS / 1000.0)


def cut_hard(
    out: Graph | None,
    in_g: Graph,
    writer: GraphWriter,
    sleep: SleepFn = time.sleep,
) -> None:
    """Single-frame swap, no fade. ``out`` is intentionally ignored."""
    del out, sleep
    writer(_scale_colorgrade_brightness(in_g, 1.0))


def netsplit_burst(
    out: Graph | None,
    in_g: Graph,
    writer: GraphWriter,
    sleep: SleepFn = time.sleep,
) -> None:
    """Sharp bounded-floor pulse, brief hold, sharp re-fill.

    Reads as a network-style cut without letting the surface drop to
    black. The floor pulse marks the cut while preserving camera geometry.
    """
    if out is not None:
        for i in range(NETSPLIT_OUT_STEPS):
            t = (i + 1) / NETSPLIT_OUT_STEPS
            brightness = 1.0 - (1.0 - MIN_TRANSITION_BRIGHTNESS) * t
            writer(_scale_colorgrade_brightness(out, _surface_safe_brightness(brightness)))
            sleep(NETSPLIT_STEP_MS / 1000.0)
    writer(_scale_colorgrade_brightness(in_g, MIN_TRANSITION_BRIGHTNESS))
    sleep(NETSPLIT_HOLD_MS / 1000.0)
    for i in range(NETSPLIT_IN_STEPS):
        t = (i + 1) / NETSPLIT_IN_STEPS
        brightness = MIN_TRANSITION_BRIGHTNESS + (1.0 - MIN_TRANSITION_BRIGHTNESS) * t
        writer(_scale_colorgrade_brightness(in_g, _surface_safe_brightness(brightness)))
        sleep(NETSPLIT_STEP_MS / 1000.0)


def _sigmoid_01(x: float) -> float:
    """Logistic sigmoid mapped so [0, 1] → [~0, ~1] with steep middle.

    Steepness chosen so the curve sits close to 0 below x=0.3, climbs
    sharply through the middle, and saturates above x=0.7 — distinct
    perceptual signature from the linear ramp in ``fade_smooth``.
    """
    z = (x - 0.5) * 8.0
    return 1.0 / (1.0 + math.exp(-z))


def ticker_scroll(
    out: Graph | None,
    in_g: Graph,
    writer: GraphWriter,
    sleep: SleepFn = time.sleep,
) -> None:
    """Sigmoid (S-curve) brightness crossfade.

    Same brightness-scaling mechanism as ``fade_smooth`` but with a
    logistic curve instead of linear ramp. Reads as a slower start +
    slower end with a quick perceptual ``snap`` through the middle —
    distinct enough from the linear fade to register as a separate
    transition class. (The original "scroll-from-edge" semantic
    requires drift.position bridging that the preset graph schema
    doesn't currently expose; using the brightness curve keeps the
    primitive testable today and the visual signature distinct.)
    """
    if out is not None:
        for i in range(TICKER_STEPS):
            t = (i + 1) / TICKER_STEPS
            brightness = 1.0 - (1.0 - MIN_TRANSITION_BRIGHTNESS) * _sigmoid_01(t)
            writer(_scale_colorgrade_brightness(out, _surface_safe_brightness(brightness)))
            sleep(TICKER_STEP_MS / 1000.0)
    for i in range(TICKER_STEPS):
        t = (i + 1) / TICKER_STEPS
        brightness = MIN_TRANSITION_BRIGHTNESS + (1.0 - MIN_TRANSITION_BRIGHTNESS) * _sigmoid_01(t)
        writer(_scale_colorgrade_brightness(in_g, _surface_safe_brightness(brightness)))
        sleep(TICKER_STEP_MS / 1000.0)


def dither_noise(
    out: Graph | None,
    in_g: Graph,
    writer: GraphWriter,
    sleep: SleepFn = time.sleep,
) -> None:
    """Bounded shimmer handoff before settling.

    The old implementation flickered between graphs at ~16 Hz, which is
    exactly the whole-frame pumping failure class the live surface now
    forbids. Keep a distinguishable transition by writing one bounded
    outgoing shimmer, one bounded incoming shimmer, then the final graph.
    """
    if out is not None:
        for target in (out, in_g):
            writer(_scale_colorgrade_brightness(target, 0.93))
            sleep(DITHER_STEP_MS / 1000.0)
    writer(_scale_colorgrade_brightness(in_g, 1.0))


# Registry — keyed by capability name. Used by ``random_mode`` to
# dispatch on the recruited transition. Order matches ``TRANSITION_NAMES``.
PRIMITIVES: Final[dict[str, TransitionFn]] = {
    "transition.fade.smooth": fade_smooth,
    "transition.cut.hard": cut_hard,
    "transition.netsplit.burst": netsplit_burst,
    "transition.ticker.scroll": ticker_scroll,
    "transition.dither.noise": dither_noise,
}


__all__ = [
    "DITHER_FLIPS",
    "DITHER_STEP_MS",
    "FADE_STEPS",
    "FADE_STEP_MS",
    "MIN_TRANSITION_BRIGHTNESS",
    "NETSPLIT_HOLD_MS",
    "NETSPLIT_IN_STEPS",
    "NETSPLIT_OUT_STEPS",
    "NETSPLIT_STEP_MS",
    "PRIMITIVES",
    "TICKER_STEPS",
    "TICKER_STEP_MS",
    "TRANSITION_NAMES",
    "TransitionFn",
    "cut_hard",
    "dither_noise",
    "fade_smooth",
    "netsplit_burst",
    "ticker_scroll",
]
