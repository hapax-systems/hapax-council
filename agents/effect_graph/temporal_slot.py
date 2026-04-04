"""Temporal feedback state for a single glfilterapp slot.

Manages ping-pong texture IDs for frame-to-frame accumulation.
GL texture allocation happens on the GL thread via the render callback;
this class only tracks IDs and swap state.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class TemporalSlotState:
    """Ping-pong FBO state for one temporal shader slot."""

    def __init__(self, num_buffers: int = 1) -> None:
        self._num_buffers = max(1, num_buffers)
        self._textures: list[int] = []
        self._current_idx: int = 0
        self._width: int = 0
        self._height: int = 0

    @property
    def initialized(self) -> bool:
        return len(self._textures) > 0

    @property
    def accum_texture_id(self) -> int | None:
        if not self._textures:
            return None
        return self._textures[self._current_idx]

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def initialize(self, width: int, height: int, texture_id: int) -> None:
        """Register the primary accumulation texture (created on GL thread)."""
        self._width = width
        self._height = height
        if not self._textures:
            self._textures.append(texture_id)
        else:
            self._textures[0] = texture_id

    def initialize_secondary(self, texture_id: int) -> None:
        """Register secondary texture for double-buffered ping-pong."""
        if len(self._textures) < 2:
            self._textures.append(texture_id)
        else:
            self._textures[1] = texture_id

    def swap(self) -> None:
        """Swap ping-pong buffers. Call after each frame render."""
        if len(self._textures) >= 2:
            self._current_idx = 1 - self._current_idx
