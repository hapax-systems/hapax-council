"""Voice panel — voice daemon state detail for the seam layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gi.repository import Gtk

if TYPE_CHECKING:
    from hapax_bar.stimmung import StimmungState


class VoicePanel(Gtk.Box):
    """Shows voice state, routing tier, last utterance."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            css_classes=["voice-panel"],
        )
        self._label = Gtk.Label(xalign=0, css_classes=["metrics-row"])
        self.append(self._label)
        self.set_visible(False)

    def update(self, state: StimmungState) -> None:
        if not state.voice_active and state.voice_state == "off":
            self.set_visible(False)
            return

        self.set_visible(True)
        # Read extended voice info from visual layer state if available
        parts = [f"Voice: {state.voice_state}"]
        self._label.set_label("  ".join(parts))
