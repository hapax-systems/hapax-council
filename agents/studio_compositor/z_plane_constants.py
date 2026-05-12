"""Z-plane depth constants for ward stratification.

Five semantic depth categories layer wards in a notional fishbowl
(scrim spatial design at ``docs/research/2026-04-20-nebulous-scrim-design.md``).
The default ``"on-scrim"`` is the legibility plane and renders without
visible attenuation; deeper planes attenuate via :func:`fx_chain.blit_with_depth`.

Kept as a separate module to avoid a circular import between
:mod:`fx_chain` and :mod:`ward_properties`.
"""

from __future__ import annotations

from typing import Final

# Per-plane base depth in [0.0 far, 1.0 near]. The blit path combines this
# base with the modulator-written ``z_index_float`` to produce an effective
# depth that drives opacity attenuation.
_Z_INDEX_BASE: Final[dict[str, float]] = {
    "beyond-scrim": 0.2,
    "mid-scrim": 0.5,
    "on-scrim": 0.9,
    "surface-scrim": 1.0,
}

DEFAULT_Z_PLANE: Final[str] = "on-scrim"
DEFAULT_Z_INDEX_FLOAT: Final[float] = 0.5

# Per-ward initial z-plane assignments (spec §4 taxonomy at
# ``docs/superpowers/specs/2026-04-21-ward-stimmung-modulator-design.md``).
# These apply only when no ward override exists yet — director
# ``placement_bias`` and explicit recruitment metadata still take
# precedence (spec §7). Wards not listed here resolve to the default
# ``"on-scrim"`` plane.
#
# - ``surface-scrim`` (foreground, opacity ≈ 1.0): always-legible chrome
#   that must read clearly even under heavy depth attenuation
# - ``mid-scrim`` (informational backdrop, opacity ≈ 0.8 at depth=0.5):
#   chrome that benefits from sitting slightly recessed so cameras +
#   sierpinski + reverie content read forward
# - ``beyond-scrim`` (atmosphere layer, opacity ≈ 0.68 at depth=0.5):
#   immersive background pieces that should fade as the imagination
#   ``depth`` dim rises
WARD_Z_PLANE_DEFAULTS: Final[dict[str, str]] = {
    # Surface — always legible. 2026-04-21 Tier D of the
    # livestream-crispness research: the 4 smallest-surface-area
    # wards — stance_indicator (4k px²), thinking_indicator (7.5k
    # px²), whos_here (10.5k px²), pressure_gauge (15.6k px²), per
    # the per-ward opacity audit PR #1161 — are status-of-self
    # chrome. Recessing them under mid-scrim attenuation lost them
    # against bright shader output. Elevating to surface-scrim so
    # they render at full opacity. thinking_indicator demoted from
    # mid-scrim to surface-scrim for the same reason.
    "stream_overlay": "surface-scrim",
    "stance_indicator": "surface-scrim",
    "thinking_indicator": "surface-scrim",
    "whos_here": "surface-scrim",
    "pressure_gauge": "surface-scrim",
    # DURF (Display Under Reflective Frame) — operator directive 2026-04-25
    # ('It does need modulation, just not a pulse like that, it's too
    # heavy handed and distracting'). Pinning to surface-scrim keeps DURF
    # legible through the FX chain — content can be consumed without the
    # heavy 1-2s shader-feedback pulse that hits mid/beyond planes.
    # DURF still composites pre_fx (in the scrim) so the scrim is felt,
    # but its depth-attenuation factor is at the surface ceiling.
    "durf": "surface-scrim",
    # ytb-LORE-EXT future wards: the task requires the lore family to
    # render at the surface scrim depth so the typography remains legible
    # while still flowing through the ward FX/depth path.
    "precedent_ticker": "surface-scrim",
    "programme_history": "surface-scrim",
    "research_instrument_dashboard": "surface-scrim",
    "interactive_lore_query": "surface-scrim",
    # Mid — informational backdrop
    "chat_ambient": "mid-scrim",
    "impingement_cascade": "mid-scrim",
    # ``hardm_dot_matrix`` retired 2026-04-23 (GEAL Phase 0) —
    # superseded by the Sierpinski-native expressive layer. See
    # ``docs/archive/homage-hardm/``.
    # Beyond — atmosphere. 2026-04-23: sierpinski added per nebulous-scrim
    # spec §6.4 ("what the audience peers at"). It was grandfathered to
    # the default ``on-scrim`` plane; assigning it to beyond-scrim places
    # it alongside album as a peered-through-scrim element.
    "sierpinski": "beyond-scrim",
    "album": "beyond-scrim",
}

__all__ = [
    "_Z_INDEX_BASE",
    "DEFAULT_Z_INDEX_FLOAT",
    "DEFAULT_Z_PLANE",
    "WARD_Z_PLANE_DEFAULTS",
]
