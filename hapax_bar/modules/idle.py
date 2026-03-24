"""Idle inhibitor toggle — prevents DPMS/sleep."""

from __future__ import annotations

import subprocess

from gi.repository import Gtk


class IdleInhibitorModule(Gtk.Box):
    """Click to toggle idle inhibition. Shows [!idle] when active."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "idle"],
        )
        self._label = Gtk.Label()
        self.append(self._label)
        self._inhibited = False

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        self._sync()

    def _sync(self) -> None:
        if self._inhibited:
            self._label.set_label("[!idle]")
            self.set_css_classes(["module", "idle", "active"])
            self.set_tooltip_text("Idle inhibitor: ON (sleep/DPMS blocked)")
        else:
            self._label.set_label("")
            self.set_css_classes(["module", "idle"])
            self.set_tooltip_text("Idle inhibitor: off")

    def _on_click(self, *_args: object) -> None:
        self._inhibited = not self._inhibited
        if self._inhibited:
            subprocess.Popen(["hyprctl", "dispatch", "dpms", "on"])
        self._sync()
