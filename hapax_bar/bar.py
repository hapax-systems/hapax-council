"""Bar window — one Astal.Window per monitor with CenterBox layout.

v2: Stimmung field replaces text modules in center zone.
Right zone has only mode badge, volume, clock, tray.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gi.repository import Astal, Gtk

from hapax_bar.modules.audio import MicModule, VolumeModule
from hapax_bar.modules.cost_whisper import CostWhisper
from hapax_bar.modules.mpris import MprisModule
from hapax_bar.modules.stimmung_field import StimmungField
from hapax_bar.modules.submap import SubmapModule
from hapax_bar.modules.temporal_ribbon import TemporalRibbon
from hapax_bar.modules.tray import TrayModule
from hapax_bar.modules.window_title import WindowTitleModule
from hapax_bar.modules.working_mode import WorkingModeModule
from hapax_bar.modules.workspaces import WorkspacesModule

if TYPE_CHECKING:
    from hapax_bar.seam.seam_window import SeamWindow


def create_bar(
    monitor_index: int | None = None,
    workspace_ids: list[int] | None = None,
    primary: bool = True,
    seam_window: SeamWindow | None = None,
) -> tuple[Astal.Window, StimmungField]:
    """Create a bar window. Returns (window, stimmung_field) for wiring.

    Args:
        monitor_index: Monitor index (gint). None = default.
        workspace_ids: Which workspace IDs to show buttons for.
        primary: If True, shows all modules. If False, shows subset.
        seam_window: Seam layer window to toggle on stimmung field click.
    """
    # Left: workspaces + submap + mpris
    left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    left.append(WorkspacesModule(workspace_ids))
    left.append(SubmapModule())
    if primary:
        left.append(MprisModule())

    # Center: stimmung field (replaces text modules)
    stimmung_field = StimmungField()
    if seam_window is not None:
        stimmung_field.set_seam_toggle(seam_window.toggle)

    center = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    # Window title rendered subtly alongside stimmung field
    title = WindowTitleModule(max_length=40 if primary else 30)
    center.append(title)
    center.append(stimmung_field)

    # Right: minimal interaction points only
    right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    right.append(WorkingModeModule())
    right.append(VolumeModule())
    if primary:
        right.append(MicModule())
        right.append(CostWhisper())
    right.append(TemporalRibbon())
    if primary:
        right.append(TrayModule())

    centerbox = Gtk.CenterBox()
    centerbox.set_start_widget(left)
    centerbox.set_center_widget(center)
    centerbox.set_end_widget(right)

    window = Astal.Window(
        namespace="hapax-bar" if primary else "hapax-bar-secondary",
        anchor=Astal.WindowAnchor.TOP | Astal.WindowAnchor.LEFT | Astal.WindowAnchor.RIGHT,
        exclusivity=Astal.Exclusivity.EXCLUSIVE,
        css_classes=["bar"],
        default_height=24,
    )

    if monitor_index is not None:
        window.set_monitor(monitor_index)

    window.set_child(centerbox)
    window.present()
    return window, stimmung_field
