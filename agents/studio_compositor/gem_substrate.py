"""GEM substrate — Gray-Scott reaction-diffusion field for Candidate C Phase 1.

Background substrate that always animates beneath the text mural. Per the
2026-04-22 GEM brainstorm (Candidate C, operator decision: text wins), the
substrate brightness is hard-clamped so text always reads above it.

The implementation is a small pure-NumPy Gray-Scott step on a low-res grid
(default 230×30 = ~7 KB f32 buffer) ticked once per `render_content` call
at the source's 24 Hz cadence. The rendered substrate is upscaled into the
1840×240 GEM canvas via Cairo's nearest/bilinear scaling, so the substrate
cost stays in the per-tick render budget regardless of canvas resolution.

Kernel constants are the canonical "U-skate" values from Pearson's 1993
classification — same family as the kernel in `agents/reverie/rd.wgsl` —
producing slow-evolving spotted/labyrinthine patterns rather than the
faster wave-front regimes (which would compete with text legibility).

The substrate is *not* a recruitable affordance and *not* a perception
input. It is a fixed background process owned by the GEM renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-checking-only: numpy is always present at runtime in the council
    # baseline, but the try/except guard below preserves graceful degradation.
    # Pyright reads this branch and resolves NDArrayF32 to numpy's actual
    # type so substrate field/return annotations type-check correctly.
    import numpy as _np_for_types
    from numpy.typing import NDArray

    NDArrayF32 = NDArray[_np_for_types.float32]
else:
    NDArrayF32 = object  # runtime-only fallback when numpy missing

try:
    import numpy as np

    _HAVE_NUMPY = True
except ImportError:  # pragma: no cover — numpy is in the council baseline
    _HAVE_NUMPY = False


# Default low-res grid. 230×30 ≈ 7 KB per buffer (×2 for U/V), 6,900 cells —
# a Gray-Scott step is ~30k float ops. At 24 Hz that's ~720k ops/sec, well
# under 1 ms/tick on the workstation CPU. Upscale ratio to the 1840×240
# canvas is exactly 8× horizontally and 8× vertically.
DEFAULT_GRID_W = 230
DEFAULT_GRID_H = 30

# Pearson "U-skate" / spotted regime — same family as reverie's `rd.wgsl`
# default. F + k must satisfy 0.04 < F+k < 0.07 for the spotted regime.
DEFAULT_DU = 0.16
DEFAULT_DV = 0.08
DEFAULT_F = 0.035
DEFAULT_K = 0.060

# Substrate brightness ceiling — enforces "text wins" per operator decision
# 2026-04-22. The substrate cell value (V channel of Gray-Scott, range
# roughly [0, 1]) is multiplied by this before being painted, so the
# brightest substrate pixel is at most this fraction of full intensity.
# Text is painted at 0.95-1.0 alpha so this gives ≥0.6 contrast headroom.
SUBSTRATE_BRIGHTNESS_CEILING = 0.35


@dataclass
class SubstrateState:
    """Two-buffer Gray-Scott field state.

    `u` and `v` are float32 arrays of shape `(grid_h, grid_w)`. `u` starts
    saturated (1.0); `v` starts at 0 except for a small seeded patch that
    gives the reaction something to consume. Without the seed the field
    decays to a flat plain.
    """

    u: NDArrayF32  # numpy float32 array shape (grid_h, grid_w); object at runtime if numpy missing
    v: NDArrayF32
    grid_w: int
    grid_h: int


def _make_initial_state(grid_w: int, grid_h: int) -> SubstrateState:
    """Build a fresh Gray-Scott state with a small central seed of V."""
    if not _HAVE_NUMPY:
        raise RuntimeError("gem_substrate requires numpy — install in the compositor venv")
    u = np.ones((grid_h, grid_w), dtype=np.float32)
    v = np.zeros((grid_h, grid_w), dtype=np.float32)
    cy, cx = grid_h // 2, grid_w // 2
    # Seed a 3×6 patch so the initial spot has enough mass to spread.
    v[cy - 1 : cy + 2, cx - 3 : cx + 3] = 0.5
    u[cy - 1 : cy + 2, cx - 3 : cx + 3] = 0.5
    return SubstrateState(u=u, v=v, grid_w=grid_w, grid_h=grid_h)


def _step(
    state: SubstrateState,
    *,
    du: float = DEFAULT_DU,
    dv: float = DEFAULT_DV,
    f: float = DEFAULT_F,
    k: float = DEFAULT_K,
    dt: float = 1.0,
) -> None:
    """One forward-Euler Gray-Scott update applied in place to `state`."""
    u, v = state.u, state.v
    # 5-point Laplacian via array shifts. `np.roll` wraps at edges, giving
    # the substrate periodic boundary conditions — fine for a background
    # field where edge artifacts are not a concern.
    lap_u = (
        np.roll(u, 1, axis=0)
        + np.roll(u, -1, axis=0)
        + np.roll(u, 1, axis=1)
        + np.roll(u, -1, axis=1)
        - 4.0 * u
    )
    lap_v = (
        np.roll(v, 1, axis=0)
        + np.roll(v, -1, axis=0)
        + np.roll(v, 1, axis=1)
        + np.roll(v, -1, axis=1)
        - 4.0 * v
    )
    uvv = u * v * v
    state.u = u + dt * (du * lap_u - uvv + f * (1.0 - u))
    state.v = v + dt * (dv * lap_v + uvv - (f + k) * v)


def _to_brightness(state: SubstrateState, *, ceiling: float) -> NDArrayF32:
    """Project the V channel to a clamped brightness array in `[0, ceiling]`.

    V values can briefly exceed 1.0 during transient growth phases; the
    clamp keeps the substrate from ever out-shining the text layer.
    """
    bright = np.clip(state.v, 0.0, 1.0) * ceiling
    return bright.astype(np.float32)


class GemSubstrate:
    """Stateful Gray-Scott substrate ticked once per render_content call.

    Owned by `GemCairoSource` (Candidate C Phase 1). The substrate is
    rendered as a background fill before the text layer composites on top.

    ``ticks_per_render`` controls how many GS steps run per Cairo render
    tick. At the GEM ward's 24 Hz cadence, 4 steps/tick gives ~96 GS
    steps/sec — fast enough that the spotted pattern visibly drifts but
    slow enough to remain calm under voice.
    """

    def __init__(
        self,
        *,
        grid_w: int = DEFAULT_GRID_W,
        grid_h: int = DEFAULT_GRID_H,
        ticks_per_render: int = 4,
        ceiling: float = SUBSTRATE_BRIGHTNESS_CEILING,
    ) -> None:
        if grid_w <= 0 or grid_h <= 0:
            raise ValueError(f"grid dimensions must be positive, got {grid_w}x{grid_h}")
        if not 0.0 <= ceiling <= 1.0:
            raise ValueError(f"ceiling must be in [0, 1], got {ceiling}")
        if ticks_per_render < 1:
            raise ValueError(f"ticks_per_render must be >= 1, got {ticks_per_render}")
        self._state = _make_initial_state(grid_w, grid_h)
        self._ticks_per_render = ticks_per_render
        self._ceiling = ceiling

    @property
    def grid_w(self) -> int:
        return self._state.grid_w

    @property
    def grid_h(self) -> int:
        return self._state.grid_h

    @property
    def ceiling(self) -> float:
        return self._ceiling

    def step(self) -> None:
        """Advance the substrate by ``ticks_per_render`` Gray-Scott steps."""
        for _ in range(self._ticks_per_render):
            _step(self._state)

    def brightness_array(self) -> NDArrayF32:
        """Return the clamped brightness array (shape `(grid_h, grid_w)`)."""
        return _to_brightness(self._state, ceiling=self._ceiling)

    def max_brightness(self) -> float:
        """Current max brightness across the grid — useful for tests."""
        bright = self.brightness_array()
        return float(bright.max())


def is_within_text_priority(substrate_max: float, text_alpha: float) -> bool:
    """Verify the substrate cannot out-shine the text layer.

    The "text wins" operator decision (2026-04-22) requires that under no
    condition does the substrate paint brighter than the text. Tests use
    this to pin the invariant.
    """
    return substrate_max <= text_alpha


__all__ = [
    "DEFAULT_DU",
    "DEFAULT_DV",
    "DEFAULT_F",
    "DEFAULT_GRID_H",
    "DEFAULT_GRID_W",
    "DEFAULT_K",
    "SUBSTRATE_BRIGHTNESS_CEILING",
    "GemSubstrate",
    "SubstrateState",
    "is_within_text_priority",
]
