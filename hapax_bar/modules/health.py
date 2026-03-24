"""Health status module — polls Logos API /api/health."""

from __future__ import annotations

import subprocess
from typing import Any

from gi.repository import Gtk

from hapax_bar.logos_client import fetch_health, poll_api


class HealthModule(Gtk.Box):
    """Displays [hpx:healthy/total] with severity color classes."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "health"],
        )
        self._label = Gtk.Label(label="[hpx:--/--]")
        self.append(self._label)

        # Click: open Logos app
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        # Poll every 30s
        self._poll_id = poll_api(fetch_health, 30_000, self._update)

    def _update(self, data: dict[str, Any]) -> None:
        healthy = data.get("healthy", 0)
        total = data.get("total_checks", 0)
        status = data.get("status", data.get("overall_status", "unknown"))

        self._label.set_label(f"[hpx:{healthy}/{total}]")

        classes = ["module", "health"]
        if status == "healthy":
            classes.append("healthy")
        elif status == "degraded":
            classes.append("degraded")
        elif status == "failed":
            classes.append("failed")
        self.set_css_classes(classes)

        # Tooltip with failed checks
        failed = data.get("failed_checks", [])
        if failed:
            tooltip = f"Status: {status}\n" + "\n".join(f"  - {c}" for c in failed)
        else:
            tooltip = f"Status: {status}"
        self.set_tooltip_text(tooltip)

    def _on_click(self, *_args: object) -> None:
        subprocess.Popen(["xdg-open", "http://localhost:8051"])
