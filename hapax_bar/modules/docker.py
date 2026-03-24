"""Docker container count — polls Logos API /api/infrastructure."""

from __future__ import annotations

import subprocess
from typing import Any

from gi.repository import Gtk

from hapax_bar.logos_client import fetch_infrastructure, poll_api


class DockerModule(Gtk.Box):
    """Displays [dock:N] container count."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "docker"],
        )
        self._label = Gtk.Label(label="[dock:--]")
        self.append(self._label)

        # Click: show docker ps
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        self._poll_id = poll_api(fetch_infrastructure, 30_000, self._update)

    def _update(self, data: dict[str, Any]) -> None:
        containers = data.get("containers", [])
        count = len(containers) if isinstance(containers, list) else 0

        self._label.set_label(f"[dock:{count}]")

        classes = ["module", "docker"]
        if count == 0:
            classes.append("warning")
        self.set_css_classes(classes)

        self.set_tooltip_text(f"Docker: {count} running containers")

    def _on_click(self, *_args: object) -> None:
        subprocess.Popen(["foot", "-e", "bash", "-c", "docker ps -a; read"])
