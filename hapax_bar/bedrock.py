"""Bedrock bar — bottom of screen. Foundations, health, governance, controls.

Grounded, interactive, slightly warmer. Answers: is the system healthy,
is anyone being recorded, what can I adjust?
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gi.repository import Astal, Gtk

from hapax_bar.modules.audio import MicModule, VolumeModule
from hapax_bar.modules.bluetooth import BluetoothIndicator
from hapax_bar.modules.cost_whisper import CostWhisper
from hapax_bar.modules.stimmung_field import StimmungField
from hapax_bar.modules.system_indicators import CpuIndicator, GpuIndicator, NetworkIndicator
from hapax_bar.modules.tray import TrayModule
from hapax_bar.stimmung_strip import StimmungStrip

if TYPE_CHECKING:
    from hapax_bar.seam.seam_window import SeamWindow


def create_bedrock(
    monitor_index: int | None = None,
    primary: bool = True,
    seam_window: SeamWindow | None = None,
) -> tuple[Astal.Window, StimmungField]:
    """Create the bedrock (bottom) bar window. Returns (window, stimmung_field)."""
    # Left: empty (stimmung field stretches from center)
    left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

    # Center: stimmung field (fills available space)
    stimmung_field = StimmungField()
    if seam_window is not None:
        stimmung_field.set_seam_toggle(seam_window.toggle)

    # Right: volume, mic, cost, tray
    right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    right.append(NetworkIndicator())
    right.append(BluetoothIndicator())
    right.append(CpuIndicator())
    right.append(GpuIndicator())
    right.append(VolumeModule())
    if primary:
        right.append(MicModule())
        right.append(CostWhisper())
        right.append(TrayModule())

    centerbox = Gtk.CenterBox()
    centerbox.set_start_widget(left)
    centerbox.set_center_widget(stimmung_field)
    centerbox.set_end_widget(right)

    window = Astal.Window(
        namespace="hapax-bedrock" if primary else "hapax-bedrock-secondary",
        anchor=Astal.WindowAnchor.BOTTOM | Astal.WindowAnchor.LEFT | Astal.WindowAnchor.RIGHT,
        exclusivity=Astal.Exclusivity.EXCLUSIVE,
        css_classes=["bedrock"],
        default_height=40,
    )

    if monitor_index is not None:
        window.set_monitor(monitor_index)

    # Vertical stack: functional bar + stimmung strip (4px)
    strip = StimmungStrip(edge="bottom")
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    vbox.append(centerbox)
    vbox.append(strip)
    window.set_child(vbox)
    window.present()
    return window, stimmung_field, strip
