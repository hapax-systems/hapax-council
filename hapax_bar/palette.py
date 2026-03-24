"""Mode-aware color palette for Cairo rendering.

Mirrors CSS custom properties as Python RGB tuples (0.0-1.0).
Colors verified against logos-design-language.md §3.1.
"""

from __future__ import annotations

from hapax_bar.theme import current_mode

_RND = {
    "bg": (0.114, 0.125, 0.129),
    "surface": (0.157, 0.157, 0.157),
    "elevated": (0.235, 0.220, 0.212),
    "text_primary": (0.922, 0.859, 0.698),
    "text_secondary": (0.659, 0.600, 0.518),
    "text_dim": (0.400, 0.361, 0.329),
    "green_400": (0.722, 0.733, 0.149),
    "yellow_400": (0.980, 0.741, 0.184),
    "orange_400": (0.996, 0.502, 0.098),
    "red_400": (0.984, 0.286, 0.204),
    "blue_400": (0.514, 0.647, 0.596),
    "fuchsia_400": (0.827, 0.525, 0.608),
    "aqua_400": (0.557, 0.753, 0.486),
    "zinc_700": (0.400, 0.361, 0.329),
}

_RESEARCH = {
    "bg": (0.0, 0.169, 0.212),
    "surface": (0.027, 0.212, 0.259),
    "elevated": (0.039, 0.251, 0.314),
    "text_primary": (0.514, 0.580, 0.588),
    "text_secondary": (0.396, 0.482, 0.514),
    "text_dim": (0.263, 0.376, 0.408),
    "green_400": (0.522, 0.600, 0.0),
    "yellow_400": (0.710, 0.537, 0.0),
    "orange_400": (0.796, 0.294, 0.086),
    "red_400": (0.863, 0.196, 0.184),
    "blue_400": (0.149, 0.545, 0.824),
    "fuchsia_400": (0.827, 0.212, 0.510),
    "aqua_400": (0.165, 0.631, 0.596),
    "zinc_700": (0.345, 0.431, 0.459),
}

_PALETTES = {"rnd": _RND, "research": _RESEARCH}


def get_palette() -> dict[str, tuple[float, float, float]]:
    return _PALETTES.get(current_mode(), _RND)


def color(name: str) -> tuple[float, float, float]:
    return get_palette()[name]
