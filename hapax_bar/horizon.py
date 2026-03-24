"""Horizon bar — top of screen. Time, work context, awareness.

Ambient, peripheral, cool. Answers: what am I doing, when is it, what needs attention?
"""

from __future__ import annotations

from gi.repository import Astal, Gtk

from hapax_bar.modules.mpris import MprisModule
from hapax_bar.modules.submap import SubmapModule
from hapax_bar.modules.temporal_ribbon import TemporalRibbon
from hapax_bar.modules.window_title import WindowTitleModule
from hapax_bar.modules.working_mode import WorkingModeModule
from hapax_bar.modules.workspaces import WorkspacesModule


def create_horizon(
    monitor_index: int | None = None,
    workspace_ids: list[int] | None = None,
    primary: bool = True,
    seam_toggle: object = None,
) -> Astal.Window:
    """Create the horizon (top) bar window."""
    # Left: workspaces + submap
    left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    left.append(WorkspacesModule(workspace_ids))
    left.append(SubmapModule())

    # Center: window title + mpris (ambient text)
    center = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    center.append(WindowTitleModule(max_length=50 if primary else 35))
    if primary:
        center.append(MprisModule(max_length=30))

    # Right: mode badge + temporal ribbon
    right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    if primary:
        right.append(WorkingModeModule())
    right.append(TemporalRibbon())

    centerbox = Gtk.CenterBox()
    centerbox.set_start_widget(left)
    centerbox.set_center_widget(center)
    centerbox.set_end_widget(right)

    window = Astal.Window(
        namespace="hapax-horizon" if primary else "hapax-horizon-secondary",
        anchor=Astal.WindowAnchor.TOP | Astal.WindowAnchor.LEFT | Astal.WindowAnchor.RIGHT,
        exclusivity=Astal.Exclusivity.EXCLUSIVE,
        css_classes=["horizon"],
        default_height=24,
    )

    if monitor_index is not None:
        window.set_monitor(monitor_index)

    window.set_child(centerbox)
    # Click on center area opens horizon seam
    if seam_toggle is not None:
        center_click = Gtk.GestureClick()
        center_click.connect("pressed", lambda *_: seam_toggle())
        center.add_controller(center_click)

    window.present()
    return window
