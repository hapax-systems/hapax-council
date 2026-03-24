"""GPU status module — polls Logos API /api/gpu."""

from __future__ import annotations

import subprocess
from typing import Any

from gi.repository import Gtk

from hapax_bar.logos_client import fetch_gpu, poll_api


class GpuModule(Gtk.Box):
    """Displays [gpu:temp°C memG] with severity based on VRAM usage."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "gpu"],
        )
        self._label = Gtk.Label(label="[gpu:--]")
        self.append(self._label)

        # Click: open nvtop
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        self._poll_id = poll_api(fetch_gpu, 30_000, self._update)

    def _update(self, data: dict[str, Any]) -> None:
        temp = data.get("temperature", data.get("temp", "?"))
        mem_used = data.get("memory_used_mib", data.get("vram_used_mib", 0))
        mem_total = data.get("memory_total_mib", data.get("vram_total_mib", 24576))
        utilization = data.get("utilization", data.get("gpu_util", "?"))

        mem_gb = mem_used / 1024 if isinstance(mem_used, (int, float)) else 0

        self._label.set_label(f"[gpu:{temp}\u00b0C {mem_gb:.1f}G]")

        classes = ["module", "gpu"]
        if isinstance(mem_used, (int, float)):
            if mem_used > 20480:  # >20GB
                classes.append("critical")
            elif mem_used > 16384:  # >16GB
                classes.append("warning")
            else:
                classes.append("normal")
        self.set_css_classes(classes)

        self.set_tooltip_text(
            f"GPU Utilization: {utilization}%\n"
            f"VRAM: {mem_used}MiB / {mem_total}MiB\n"
            f"Temperature: {temp}\u00b0C"
        )

    def _on_click(self, *_args: object) -> None:
        subprocess.Popen(["foot", "-e", "nvtop"])
