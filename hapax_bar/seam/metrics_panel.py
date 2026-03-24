"""Metrics panel — health, GPU, system stats for the seam layer."""

from __future__ import annotations

from typing import Any

from gi.repository import Gtk


class MetricsPanel(Gtk.Box):
    """Compact grid of system metrics."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            css_classes=["metrics-panel"],
        )
        self._row1 = Gtk.Label(xalign=0, css_classes=["metrics-row"])
        self._row2 = Gtk.Label(xalign=0, css_classes=["metrics-row"])
        self.append(self._row1)
        self.append(self._row2)

    def update(self, health: dict[str, Any], gpu: dict[str, Any]) -> None:
        healthy = health.get("healthy", 0)
        total = health.get("total_checks", 0)
        status = health.get("status", health.get("overall_status", "?"))
        failed = health.get("failed_checks", [])
        failed_str = f"  [{', '.join(failed[:3])}]" if failed else ""

        temp = gpu.get("temperature", gpu.get("temp", "?"))
        mem_used = gpu.get("memory_used_mib", gpu.get("vram_used_mib", 0))
        mem_total = gpu.get("memory_total_mib", gpu.get("vram_total_mib", 24576))
        util = gpu.get("utilization", gpu.get("gpu_util", "?"))
        mem_gb = mem_used / 1024 if isinstance(mem_used, (int, float)) else 0

        self._row1.set_label(
            f"Health: {healthy}/{total} {status}{failed_str}    "
            f"GPU: {temp}°C  {mem_gb:.1f}G/{mem_total // 1024}G  {util}%"
        )
        self._row2.set_label("")  # Will be populated with CPU/mem/disk in later integration
