"""StutterElement — GStreamer element that implements freeze/replay temporal disruption.

Sits in the pipeline and controls which frames pass through:
- Normal: passes current frame
- Freeze: holds and re-pushes a frozen frame for N ticks
- Replay: replays the last few frames from a ring buffer

Used by Screwed and Datamosh presets.
"""

from __future__ import annotations

import logging
import random
from collections import deque

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, GObject, Gst

log = logging.getLogger(__name__)

Gst.init(None)


class StutterElement(Gst.Element):
    """GStreamer element that implements frame stutter/freeze/replay."""

    __gstmetadata__ = (
        "Stutter",
        "Filter/Effect/Video",
        "Frame stutter with freeze and replay",
        "hapax",
    )

    __gsttemplates__ = (
        Gst.PadTemplate.new(
            "sink",
            Gst.PadDirection.SINK,
            Gst.PadPresence.ALWAYS,
            Gst.Caps.new_any(),
        ),
        Gst.PadTemplate.new(
            "src",
            Gst.PadDirection.SRC,
            Gst.PadPresence.ALWAYS,
            Gst.Caps.new_any(),
        ),
    )

    check_interval = GObject.Property(
        type=int, default=10, nick="Check interval",
        blurb="Ticks between freeze checks",
    )
    freeze_chance = GObject.Property(
        type=float, default=0.3, nick="Freeze chance",
        blurb="Probability of freezing per check (0-1)",
    )
    freeze_min = GObject.Property(
        type=int, default=3, nick="Freeze min",
        blurb="Minimum ticks to hold frozen frame",
    )
    freeze_max = GObject.Property(
        type=int, default=10, nick="Freeze max",
        blurb="Maximum ticks to hold frozen frame",
    )
    replay_frames = GObject.Property(
        type=int, default=3, nick="Replay frames",
        blurb="Number of frames to replay after freeze",
    )

    def __init__(self) -> None:
        super().__init__()
        self.sinkpad = Gst.Pad.new_from_template(self.__gsttemplates__[0], "sink")
        self.sinkpad.set_chain_function_full(self._chain)
        self.sinkpad.set_event_function_full(self._sink_event)
        self.add_pad(self.sinkpad)

        self.srcpad = Gst.Pad.new_from_template(self.__gsttemplates__[1], "src")
        self.add_pad(self.srcpad)

        self._ring: deque[Gst.Buffer] = deque(maxlen=16)
        self._tick = 0
        self._phase = "play"  # play | freeze | replay
        self._hold_ticks = 0
        self._freeze_for = 0
        self._replay_step = 0
        self._frozen_buf: Gst.Buffer | None = None

    def _sink_event(self, pad: Gst.Pad, parent: Gst.Element, event: Gst.Event) -> bool:
        return self.srcpad.push_event(event)

    def _chain(self, pad: Gst.Pad, parent: Gst.Element, buf: Gst.Buffer) -> Gst.FlowReturn:
        self._ring.append(buf)
        self._tick += 1

        if self._phase == "play":
            # Check for freeze
            if (
                self._tick % self.check_interval == 0
                and random.random() < self.freeze_chance
                and len(self._ring) > self.replay_frames + 2
            ):
                self._phase = "freeze"
                self._freeze_for = random.randint(self.freeze_min, self.freeze_max)
                self._hold_ticks = 0
                self._frozen_buf = buf
            return self.srcpad.push(buf)

        elif self._phase == "freeze":
            self._hold_ticks += 1
            if self._hold_ticks >= self._freeze_for:
                self._phase = "replay"
                self._replay_step = 0
                self._hold_ticks = 0
            # Push the frozen frame again
            if self._frozen_buf is not None:
                return self.srcpad.push(self._frozen_buf)
            return self.srcpad.push(buf)

        elif self._phase == "replay":
            self._hold_ticks += 1
            if self._hold_ticks >= 2:
                self._hold_ticks = 0
                self._replay_step += 1
                if self._replay_step >= self.replay_frames:
                    self._phase = "play"

            # Push frame from N steps back in the ring
            ring_list = list(self._ring)
            replay_idx = max(0, len(ring_list) - self.replay_frames + self._replay_step - 1)
            return self.srcpad.push(ring_list[replay_idx])

        return self.srcpad.push(buf)


# Register the element
GObject.type_register(StutterElement)
__gstelementfactory__ = ("stutterelement", Gst.Rank.NONE, StutterElement)
