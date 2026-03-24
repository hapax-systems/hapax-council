"""System info modules — CPU, memory, disk, temperature from proc/sysfs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from gi.repository import GLib, Gtk

CPU_TEMP_PATH = Path("/sys/devices/pci0000:00/0000:00:18.3/hwmon")


def _read_cpu_usage() -> float:
    """Read CPU usage percentage from /proc/stat."""
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        fields = line.split()[1:]  # skip 'cpu' label
        vals = [int(x) for x in fields]
        idle = vals[3] + vals[4]  # idle + iowait
        total = sum(vals)
        return idle, total
    except Exception:
        return 0, 1


def _read_meminfo() -> tuple[int, int]:
    """Read memory usage from /proc/meminfo. Returns (used_kb, total_kb)."""
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])
        total = info.get("MemTotal", 1)
        available = info.get("MemAvailable", 0)
        return total - available, total
    except Exception:
        return 0, 1


def _read_cpu_temp() -> int | None:
    """Read CPU temperature from hwmon sysfs."""
    try:
        # Find the hwmon directory under the AMD CPU PCI device
        if CPU_TEMP_PATH.exists():
            for hwmon_dir in CPU_TEMP_PATH.iterdir():
                temp_file = hwmon_dir / "temp1_input"
                if temp_file.exists():
                    return int(temp_file.read_text().strip()) // 1000
    except Exception:
        pass
    return None


class CpuModule(Gtk.Box):
    """Displays [cpu:NN%]. Click opens htop."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "sysinfo"],
        )
        self._label = Gtk.Label(label="[cpu:--%]")
        self.append(self._label)
        self._prev_idle = 0
        self._prev_total = 0

        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_: subprocess.Popen(["foot", "-e", "htop"]))
        self.add_controller(click)

        self._update()
        GLib.timeout_add(3000, self._update)

    def _update(self, *_args: object) -> bool:
        idle, total = _read_cpu_usage()
        d_idle = idle - self._prev_idle
        d_total = total - self._prev_total
        self._prev_idle = idle
        self._prev_total = total

        if d_total > 0:
            usage = 100.0 * (1.0 - d_idle / d_total)
            self._label.set_label(f"[cpu:{int(usage)}%]")
        return GLib.SOURCE_CONTINUE


class MemoryModule(Gtk.Box):
    """Displays [mem:NN%]. Click opens htop."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "sysinfo"],
        )
        self._label = Gtk.Label(label="[mem:--%]")
        self.append(self._label)

        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_: subprocess.Popen(["foot", "-e", "htop"]))
        self.add_controller(click)

        self._update()
        GLib.timeout_add(5000, self._update)

    def _update(self, *_args: object) -> bool:
        used, total = _read_meminfo()
        pct = int(100 * used / total) if total > 0 else 0
        self._label.set_label(f"[mem:{pct}%]")

        used_gb = used / (1024 * 1024)
        total_gb = total / (1024 * 1024)
        self.set_tooltip_text(f"RAM: {used_gb:.1f}G / {total_gb:.1f}G")
        return GLib.SOURCE_CONTINUE


class DiskModule(Gtk.Box):
    """Displays [dsk:NN%]."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "sysinfo"],
        )
        self._label = Gtk.Label(label="[dsk:--%]")
        self.append(self._label)

        self._update()
        GLib.timeout_add(60_000, self._update)

    def _update(self, *_args: object) -> bool:
        try:
            st = os.statvfs("/")
            total = st.f_blocks * st.f_frsize
            used = (st.f_blocks - st.f_bfree) * st.f_frsize
            pct = int(100 * used / total) if total > 0 else 0
            self._label.set_label(f"[dsk:{pct}%]")

            used_gb = used / (1024**3)
            total_gb = total / (1024**3)
            self.set_tooltip_text(f"Disk /: {used_gb:.0f}G / {total_gb:.0f}G ({pct}%)")
        except Exception:
            pass
        return GLib.SOURCE_CONTINUE


class TemperatureModule(Gtk.Box):
    """Displays CPU temperature [NNC]. Red above 85C."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "temperature"],
        )
        self._label = Gtk.Label(label="[--C]")
        self.append(self._label)

        self._update()
        GLib.timeout_add(3000, self._update)

    def _update(self, *_args: object) -> bool:
        temp = _read_cpu_temp()
        if temp is not None:
            self._label.set_label(f"[{temp}C]")
            classes = ["module", "temperature"]
            if temp >= 85:
                classes.append("critical")
            self.set_css_classes(classes)
            self.set_tooltip_text(f"CPU Tctl: {temp}\u00b0C")
        return GLib.SOURCE_CONTINUE
