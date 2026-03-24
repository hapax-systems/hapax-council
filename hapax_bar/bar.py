"""Bar window — one Astal.Window per monitor with CenterBox layout."""

from __future__ import annotations

from gi.repository import Astal, Gtk

from hapax_bar.modules.audio import MicModule, VolumeModule
from hapax_bar.modules.clock import ClockModule
from hapax_bar.modules.docker import DockerModule
from hapax_bar.modules.gpu import GpuModule
from hapax_bar.modules.health import HealthModule
from hapax_bar.modules.idle import IdleInhibitorModule
from hapax_bar.modules.mpris import MprisModule
from hapax_bar.modules.network import NetworkModule
from hapax_bar.modules.submap import SubmapModule
from hapax_bar.modules.sysinfo import CpuModule, DiskModule, MemoryModule, TemperatureModule
from hapax_bar.modules.systemd import SystemdFailedModule
from hapax_bar.modules.tray import TrayModule
from hapax_bar.modules.window_title import WindowTitleModule
from hapax_bar.modules.working_mode import WorkingModeModule
from hapax_bar.modules.workspaces import WorkspacesModule


def create_bar(
    monitor_index: int | None = None,
    workspace_ids: list[int] | None = None,
    primary: bool = True,
) -> Astal.Window:
    """Create a bar window for a specific monitor.

    Args:
        monitor_index: Monitor index (gint). None = default.
        workspace_ids: Which workspace IDs to show buttons for.
        primary: If True, shows all modules. If False, shows subset.
    """
    # Left: workspaces + submap + mpris
    left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    left.append(WorkspacesModule(workspace_ids))
    left.append(SubmapModule())
    if primary:
        left.append(MprisModule())

    # Center: window title
    center = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    max_title = 60 if primary else 50
    center.append(WindowTitleModule(max_length=max_title))

    # Right: system modules — ordered to match waybar layout
    right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

    right.append(WorkingModeModule())
    right.append(HealthModule())
    right.append(GpuModule())
    if primary:
        right.append(TemperatureModule())
    right.append(CpuModule())
    right.append(MemoryModule())
    if primary:
        right.append(DiskModule())
        right.append(DockerModule())
    right.append(VolumeModule())
    if primary:
        right.append(MicModule())
    right.append(NetworkModule())
    if primary:
        right.append(IdleInhibitorModule())
        right.append(SystemdFailedModule())
    right.append(ClockModule())
    if primary:
        right.append(TrayModule())

    centerbox = Gtk.CenterBox()
    centerbox.set_start_widget(left)
    centerbox.set_center_widget(center)
    centerbox.set_end_widget(right)

    window = Astal.Window(
        namespace="hapax-bar",
        anchor=Astal.WindowAnchor.TOP | Astal.WindowAnchor.LEFT | Astal.WindowAnchor.RIGHT,
        exclusivity=Astal.Exclusivity.EXCLUSIVE,
        css_classes=["bar"],
        default_height=24,
    )

    if monitor_index is not None:
        window.set_monitor(monitor_index)

    window.set_child(centerbox)
    window.present()
    return window
