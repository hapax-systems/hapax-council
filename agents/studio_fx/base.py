"""Base class for all studio effects."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

    from agents.studio_fx.perception import PerceptionSnapshot


class BaseEffect(ABC):
    """Abstract base for a visual effect.

    Each effect receives a BGR frame (numpy uint8 HWC), a perception snapshot,
    and a monotonic timestamp.  It must return a frame of the *same* dimensions.
    """

    name: str

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def resize(self, width: int, height: int) -> None:
        """Called when the resolution tier changes.  Subclasses should resize
        any internal buffers here."""
        self.width = width
        self.height = height

    @abstractmethod
    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        """Process one frame.  Must return same dimensions as *frame*."""

    def reset(self) -> None:  # noqa: B027
        """Clear temporal state (trail buffers, reference frames, etc.)."""
