"""Metrics panel — health, GPU, CPU, memory, disk for the seam layer."""

from __future__ import annotations

import os
from typing import Any

from gi.repository import Gtk


def _severity_color(value: float, thresholds: tuple[float, float, float]) -> str:
    """Return CSS color name for a value given (warn, degrade, crit) thresholds."""
    if value >= thresholds[2]:
        return "red"
    if value >= thresholds[1]:
        return "orange"
    if value >= thresholds[0]:
        return "yellow"
    return ""


def _colored(text: str, css_class: str = "") -> str:
    """Wrap text in span with foreground color class for Pango markup."""
    if not css_class:
        return text
    # Map class names to actual hex — we read from CSS vars at runtime
    # but Pango markup needs literal colors. Use the severity ladder.
    colors = {
        "green": "#b8bb26",
        "yellow": "#fabd2f",
        "orange": "#fe8019",
        "red": "#fb4934",
        "dim": "#665c54",
        "blue": "#83a598",
    }
    hex_color = colors.get(css_class, "")
    if hex_color:
        return f'<span foreground="{hex_color}">{text}</span>'
    return text


def _health_color(status: str) -> str:
    if status == "healthy":
        return "green"
    if status == "degraded":
        return "orange"
    if status == "failed":
        return "red"
    return "dim"


def _read_cpu_mem() -> tuple[str, str, float]:
    """Read CPU load and memory. Returns (cpu_str, mem_str, mem_pct)."""
    cpu_str = "?"
    mem_str = "?"
    mem_pct = 0.0
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])
            total = info.get("MemTotal", 1)
            avail = info.get("MemAvailable", 0)
            used_gb = (total - avail) / (1024 * 1024)
            total_gb = total / (1024 * 1024)
            mem_pct = 100 * (total - avail) / total
            mem_str = f"{used_gb:.1f}G/{total_gb:.0f}G ({int(mem_pct)}%)"
    except Exception:
        pass
    try:
        with open("/proc/loadavg") as f:
            cpu_str = f.read().split()[0]
    except Exception:
        pass
    return cpu_str, mem_str, mem_pct


def _read_disk() -> tuple[str, float]:
    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        pct = 100 * used / total if total > 0 else 0
        return f"{used // (1024**3)}G/{total // (1024**3)}G ({int(pct)}%)", pct
    except Exception:
        return "?", 0


class MetricsPanel(Gtk.Box):
    """Compact grid of system metrics with severity-colored values."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            css_classes=["metrics-panel"],
        )
        self._row1 = Gtk.Label(xalign=0, css_classes=["metrics-row"], use_markup=True, hexpand=True)
        self._row2 = Gtk.Label(xalign=0, css_classes=["metrics-row"], use_markup=True, hexpand=True)
        self.append(self._row1)
        self.append(self._row2)

    def update(self, health: dict[str, Any], gpu: dict[str, Any]) -> None:
        # Health — color by status
        healthy = health.get("healthy", 0)
        total = health.get("total_checks", 0)
        status = health.get("overall_status", health.get("status", "?"))
        failed = health.get("failed_checks", [])
        h_color = _health_color(status)
        h_text = _colored(f"{healthy}/{total} {status}", h_color)
        failed_str = ""
        if failed:
            failed_str = "  " + _colored(f"[{', '.join(failed[:3])}]", "red")

        # GPU — color temp and VRAM by thresholds
        temp = gpu.get("temperature_c", gpu.get("temp", 0))
        used_mb = gpu.get("used_mb", 0)
        total_mb = gpu.get("total_mb", 24576)
        usage = gpu.get("usage_pct", 0)
        used_gb = used_mb / 1024 if isinstance(used_mb, (int, float)) else 0
        total_gb = total_mb / 1024 if isinstance(total_mb, (int, float)) else 24
        models = gpu.get("loaded_models", [])

        vram_pct = (used_mb / total_mb * 100) if total_mb > 0 else 0
        vram_color = _severity_color(vram_pct, (65, 80, 90))
        temp_color = _severity_color(
            float(temp) if isinstance(temp, (int, float)) else 0, (70, 80, 90)
        )

        vram_str = _colored(f"{used_gb:.1f}G/{total_gb:.0f}G", vram_color)
        temp_str = _colored(f"{temp}\u00b0C", temp_color)
        model_str = f"  [{', '.join(models[:2])}]" if models else ""

        self._row1.set_markup(
            f"Health: {h_text}{failed_str}    "
            f"GPU: {temp_str}  {vram_str}  {usage}%"
            f"{_colored(model_str, 'dim')}"
        )

        # CPU, memory, disk — color by utilization
        cpu_str, mem_str, mem_pct = _read_cpu_mem()
        disk_str, disk_pct = _read_disk()

        mem_color = _severity_color(mem_pct, (70, 85, 95))
        disk_color = _severity_color(disk_pct, (75, 85, 95))

        self._row2.set_markup(
            f"CPU: {_colored(cpu_str, 'dim')}    "
            f"Mem: {_colored(mem_str, mem_color)}    "
            f"Disk: {_colored(disk_str, disk_color)}"
        )

    def refresh(self) -> None:
        """Refresh with last known data (called by seam on open)."""
        # CPU/mem/disk always available from /proc
        cpu_str, mem_str, mem_pct = _read_cpu_mem()
        disk_str, disk_pct = _read_disk()
        mem_color = _severity_color(mem_pct, (70, 85, 95))
        disk_color = _severity_color(disk_pct, (75, 85, 95))
        self._row2.set_markup(
            f"CPU: {_colored(cpu_str, 'dim')}    "
            f"Mem: {_colored(mem_str, mem_color)}    "
            f"Disk: {_colored(disk_str, disk_color)}"
        )
