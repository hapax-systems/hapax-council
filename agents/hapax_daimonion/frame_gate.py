"""FrameGate — Pipecat processor that gates audio based on governor directive.

Inserted before STT in the pipeline:
  transport.input() → FrameGate → STT → ...

On "process": all frames pass through.
On "pause": audio frames are dropped, control frames pass.
On "withdraw": not handled here (daemon closes session externally).
"""

from __future__ import annotations

import logging

from pipecat.frames.frames import AudioRawFrame, Frame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from agents.hapax_daimonion.commands import Command

log = logging.getLogger(__name__)


class FrameGate(FrameProcessor):
    """Gates audio frames based on an external directive.

    The governor sets the directive via set_directive() or apply_command().
    When paused, audio frames are silently dropped while control frames
    (start, stop, end-of-stream) pass through to keep Pipecat's lifecycle intact.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._directive: str = "process"
        self._dropped_count: int = 0
        self._last_command: Command | None = None

    @property
    def directive(self) -> str:
        return self._directive

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    @property
    def last_command(self) -> Command | None:
        """Last Command applied, if any. Provides full governance provenance."""
        return self._last_command

    def set_directive(self, directive: str) -> None:
        """Update the gate directive. Called by the daemon on each governor tick."""
        if directive != self._directive:
            log.info("FrameGate directive: %s → %s", self._directive, directive)
            self._directive = directive

    def apply_command(self, command: Command) -> None:
        """Apply a typed Command. Extracts action and stores provenance."""
        self._last_command = command
        self.set_directive(command.action)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Process or drop frames based on current directive."""
        if self._directive == "pause" and isinstance(frame, AudioRawFrame):
            self._dropped_count += 1
            return  # drop audio frame

        await self.push_frame(frame, direction)
