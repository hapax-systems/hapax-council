"""Working mode badge — polls Logos API, also accepts socket push."""

from __future__ import annotations

import subprocess
from typing import Any

from gi.repository import Gtk

from hapax_bar.logos_client import fetch_working_mode, poll_api
from hapax_bar.theme import switch_theme


class WorkingModeModule(Gtk.Box):
    """Displays [R&D] or [RES] badge. Click toggles mode."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "working-mode"],
        )
        self._label = Gtk.Label()
        self.append(self._label)
        self._current_mode = "rnd"

        # Click: toggle mode
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        # Poll every 5 minutes (socket push for instant updates in Phase 4)
        self._poll_id = poll_api(fetch_working_mode, 300_000, self._update)

    def _update(self, data: dict[str, Any]) -> None:
        mode = data.get("mode", "rnd")
        self._current_mode = mode

        if mode == "research":
            self._label.set_label("[RES]")
            self.set_css_classes(["module", "working-mode", "research"])
        else:
            self._label.set_label("[R&D]")
            self.set_css_classes(["module", "working-mode", "rnd"])

    def set_mode(self, mode: str) -> None:
        """Called by socket server for instant mode switch."""
        self._current_mode = mode
        self._update({"mode": mode})
        switch_theme(mode)

    def _on_click(self, *_args: object) -> None:
        new_mode = "research" if self._current_mode == "rnd" else "rnd"
        subprocess.Popen(["hapax-working-mode", new_mode])
