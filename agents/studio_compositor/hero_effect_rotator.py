"""Hero effect rotator — cycles spatial effects on the hero camera tile.

Manages a dedicated glfeedback element that applies region-masked effects
to the hero tile only.  Rotates through available hero effect shaders on
a configurable timer, independent of the global preset rotation.

The hero region is defined by normalized coordinates (0..1) matching the
hero tile's position on the 1920×1080 canvas.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .config import OUTPUT_HEIGHT, OUTPUT_WIDTH
from .models import CameraSpec, TileRect

log = logging.getLogger(__name__)

_HERO_EFFECTS_DIR = Path(__file__).resolve().parent.parent / "shaders" / "hero_effects"

# How often to rotate the hero effect (seconds).
_ROTATE_INTERVAL_MIN = 45.0
_ROTATE_INTERVAL_MAX = 90.0

# Passthrough shader — no effect, used during transitions.
_PASSTHROUGH = """#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
void main() { gl_FragColor = texture2D(tex, v_texcoord); }
"""


def hero_tile_from_layout(
    layout: Mapping[str, TileRect],
    cameras: Sequence[CameraSpec],
    *,
    mode: str = "balanced",
) -> TileRect | None:
    """Return the currently responsible hero tile for masked hero effects."""
    requested_role: str | None = None
    if mode.startswith("packed/"):
        requested_role = mode[len("packed/") :]
    elif mode.startswith("hero/"):
        requested_role = mode[len("hero/") :]

    if requested_role:
        return layout.get(requested_role)

    for cam in cameras:
        if cam.hero and cam.role in layout:
            return layout[cam.role]

    if mode == "packed" and cameras:
        return layout.get(cameras[0].role)

    return None


class HeroEffectRotator:
    """Rotates spatial effects on the hero camera tile.

    Owns a reference to a glfeedback GStreamer element (``hero_effect_slot``)
    whose ``fragment`` and ``uniforms`` properties are updated when:

    1. The rotation timer fires (new effect)
    2. The hero camera changes (new mask coordinates)
    """

    def __init__(self, hero_effect_slot: Any | None = None) -> None:
        self._slot = hero_effect_slot
        self._effects: list[tuple[str, str]] = []  # (name, glsl_source)
        self._current_idx: int = -1
        self._next_rotate: float = 0.0
        self._hero_tile: TileRect | None = None
        self._canvas_w = OUTPUT_WIDTH
        self._canvas_h = OUTPUT_HEIGHT

        self._load_effects()

    def _load_effects(self) -> None:
        """Load hero effect .frag files from disk."""
        if not _HERO_EFFECTS_DIR.is_dir():
            log.warning("Hero effects dir not found: %s", _HERO_EFFECTS_DIR)
            return
        for frag_path in sorted(_HERO_EFFECTS_DIR.glob("*.frag")):
            try:
                source = frag_path.read_text()
                name = frag_path.stem
                self._effects.append((name, source))
            except Exception:
                log.warning("Failed to load hero effect: %s", frag_path, exc_info=True)
        log.info("Loaded %d hero effects: %s", len(self._effects), [e[0] for e in self._effects])

    def set_slot(self, slot: Any) -> None:
        """Set the glfeedback element to control."""
        self._slot = slot
        # Apply current effect if we have one
        if self._current_idx >= 0 and self._effects:
            self._apply_current()

    def update_hero_tile(self, tile: TileRect) -> None:
        """Update the hero tile position (called on hero camera change)."""
        self._hero_tile = tile
        if self._slot is not None:
            self._set_mask_uniforms()

    def tick(self) -> None:
        """Called periodically from the compositor tick loop.

        Checks if it's time to rotate and applies the next effect.
        """
        if not self._effects or self._slot is None:
            return

        now = time.monotonic()
        if now >= self._next_rotate:
            self._rotate()
            self._next_rotate = now + random.uniform(_ROTATE_INTERVAL_MIN, _ROTATE_INTERVAL_MAX)

    def _rotate(self) -> None:
        """Advance to the next effect."""
        if not self._effects:
            return
        # Pick a different effect than the current one
        if len(self._effects) > 1:
            candidates = list(range(len(self._effects)))
            if self._current_idx >= 0:
                candidates.remove(self._current_idx)
            self._current_idx = random.choice(candidates)
        else:
            self._current_idx = 0
        self._apply_current()

    def _apply_current(self) -> None:
        """Apply the current effect's fragment shader to the slot."""
        if self._slot is None or self._current_idx < 0:
            return
        name, source = self._effects[self._current_idx]
        log.info("Hero effect → %s (%d chars)", name, len(source))
        self._slot.set_property("fragment", source)
        self._set_mask_uniforms()

    def _set_mask_uniforms(self) -> None:
        """Update the region mask uniforms on the glfeedback element."""
        if self._slot is None:
            return
        tile = self._hero_tile
        if tile is None:
            # Default hero position from _packed_layout
            tile = TileRect(
                x=10, y=10, w=int(self._canvas_w * 0.30), h=int(int(self._canvas_w * 0.30) * 9 / 16)
            )

        # Normalize to 0..1
        nx = tile.x / self._canvas_w
        ny = tile.y / self._canvas_h
        nw = tile.w / self._canvas_w
        nh = tile.h / self._canvas_h

        uniform_str = (
            f"u_hero_x={nx},"
            f"u_hero_y={ny},"
            f"u_hero_w={nw},"
            f"u_hero_h={nh},"
            f"u_width={float(self._canvas_w)},"
            f"u_height={float(self._canvas_h)}"
        )
        self._slot.set_property("uniforms", uniform_str)

    @property
    def current_effect_name(self) -> str | None:
        if self._current_idx < 0 or not self._effects:
            return None
        return self._effects[self._current_idx][0]

    @property
    def effect_count(self) -> int:
        return len(self._effects)
