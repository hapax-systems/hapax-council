"""Seam layer — fullscreen overlay with metrics and secondary controls.

Implemented as a separate Astal.Window (not Gtk.Popover) because popovers
clip on narrow layer-shell surfaces. Click outside to dismiss.
"""

from __future__ import annotations

from typing import Any

from gi.repository import Astal, Gdk, Gtk

from hapax_bar.seam.controls_panel import ControlsPanel
from hapax_bar.seam.metrics_panel import MetricsPanel
from hapax_bar.seam.stimmung_detail import StimmungDetailPanel
from hapax_bar.seam.voice_panel import VoicePanel


class SeamWindow(Astal.Window):
    """Fullscreen overlay showing detail metrics behind the stimmung field."""

    def __init__(self) -> None:
        super().__init__(
            namespace="hapax-bar-seam",
            anchor=Astal.WindowAnchor.TOP
            | Astal.WindowAnchor.BOTTOM
            | Astal.WindowAnchor.LEFT
            | Astal.WindowAnchor.RIGHT,
            exclusivity=Astal.Exclusivity.IGNORE,
            keymode=Astal.Keymode.ON_DEMAND,
            css_classes=["seam-overlay"],
            visible=False,
        )

        # Transparent background click → dismiss
        overlay = Gtk.Overlay()
        dismiss_bg = Gtk.Box(hexpand=True, vexpand=True, css_classes=["seam-dismiss"])
        dismiss_click = Gtk.GestureClick()
        dismiss_click.connect("pressed", self._dismiss)
        dismiss_bg.add_controller(dismiss_click)
        overlay.set_child(dismiss_bg)

        # Content panel positioned below bar
        self._revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
            transition_duration=200,
            reveal_child=False,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.START,
            margin_top=28,  # bar height + gap
        )

        panel = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            css_classes=["seam-panel"],
        )
        self._metrics = MetricsPanel()
        self._stimmung_detail = StimmungDetailPanel()
        self._voice_panel = VoicePanel()
        self._controls = ControlsPanel()
        panel.append(self._metrics)
        panel.append(self._stimmung_detail)
        panel.append(self._voice_panel)
        panel.append(self._controls)

        self._revealer.set_child(panel)
        overlay.add_overlay(self._revealer)
        self.set_child(overlay)

        # Escape to dismiss
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctrl)

    def toggle(self) -> None:
        if self.get_visible():
            self._revealer.set_reveal_child(False)
            # Hide after animation
            from gi.repository import GLib

            GLib.timeout_add(250, self._hide_after_animation)
        else:
            self.set_visible(True)
            self.present()
            # Slight delay for present to register
            from gi.repository import GLib

            GLib.idle_add(lambda: self._revealer.set_reveal_child(True) or False)

    def update_data(self, health: dict, gpu: dict, stimmung_state: Any) -> None:
        self._metrics.update(health, gpu)
        self._stimmung_detail.update(stimmung_state)
        self._voice_panel.update(stimmung_state)

    def _dismiss(self, *_args: object) -> None:
        self._revealer.set_reveal_child(False)
        from gi.repository import GLib

        GLib.timeout_add(250, self._hide_after_animation)

    def _hide_after_animation(self) -> bool:
        if not self._revealer.get_reveal_child():
            self.set_visible(False)
        return False

    def _on_key(
        self, _ctrl: Gtk.EventControllerKey, keyval: int, _code: int, _state: Gdk.ModifierType
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._dismiss()
            return True
        return False
