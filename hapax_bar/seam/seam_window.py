"""Seam layer — edge-anchored overlay for detail-on-demand.

Parameterized by position (top/bottom). Each bar gets its own seam window.
Auto-dismisses on Escape, click-outside (focus loss), or second toggle.
"""

from __future__ import annotations

from gi.repository import Astal, Gdk, GLib, Gtk


class SeamWindow(Astal.Window):
    """Edge-anchored overlay that slides open from its parent bar."""

    def __init__(self, position: str = "top") -> None:
        is_top = position == "top"
        # Anchor to edge + LEFT only (not RIGHT) — window takes natural width/height
        # instead of stretching to fill the entire screen
        anchor = (
            Astal.WindowAnchor.TOP if is_top else Astal.WindowAnchor.BOTTOM
        ) | Astal.WindowAnchor.LEFT

        super().__init__(
            namespace=f"hapax-seam-{position}",
            anchor=anchor,
            exclusivity=Astal.Exclusivity.IGNORE,
            keymode=Astal.Keymode.EXCLUSIVE,
            css_classes=["seam-overlay"],
            visible=False,
        )

        self._revealer = Gtk.Revealer(
            transition_type=(
                Gtk.RevealerTransitionType.SLIDE_DOWN
                if is_top
                else Gtk.RevealerTransitionType.SLIDE_UP
            ),
            transition_duration=200,
            reveal_child=False,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.START if is_top else Gtk.Align.END,
        )

        if is_top:
            self._revealer.set_margin_top(28)
        else:
            self._revealer.set_margin_bottom(36)

        self._panel = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            css_classes=["seam-panel"],
        )
        self._revealer.set_child(self._panel)
        self.set_child(self._revealer)

        # Escape or middle-click to dismiss
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key)
        self.add_controller(key_ctrl)

        dismiss_click = Gtk.GestureClick(button=2)  # middle-click
        dismiss_click.connect("pressed", lambda *_: self._dismiss())
        self.add_controller(dismiss_click)

        self._panels: list[Gtk.Widget] = []

        # Auto-dismiss after timeout (seam is transient)
        self._dismiss_timer: int | None = None

    def add_panel(self, widget: Gtk.Widget) -> None:
        self._panel.append(widget)
        self._panels.append(widget)

    def toggle(self) -> None:
        if self.get_visible():
            self._dismiss()
        else:
            # Refresh panels that support no-arg refresh
            for panel in self._panels:
                try:
                    if hasattr(panel, "refresh"):
                        panel.refresh()
                except TypeError:
                    pass
            self.set_visible(True)
            self.present()
            GLib.idle_add(lambda: self._revealer.set_reveal_child(True) or False)
            # Auto-dismiss after 10 seconds of inactivity
            if self._dismiss_timer is not None:
                GLib.source_remove(self._dismiss_timer)
            self._dismiss_timer = GLib.timeout_add(15_000, self._auto_dismiss)

    def _dismiss(self) -> None:
        if self._dismiss_timer is not None:
            GLib.source_remove(self._dismiss_timer)
            self._dismiss_timer = None
        self._revealer.set_reveal_child(False)
        GLib.timeout_add(250, self._hide)

    def _auto_dismiss(self) -> bool:
        self._dismiss_timer = None
        self._dismiss()
        return False

    def _hide(self) -> bool:
        if not self._revealer.get_reveal_child():
            self.set_visible(False)
        return False

    def _on_key(
        self,
        _ctrl: Gtk.EventControllerKey,
        keyval: int,
        _code: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._dismiss()
            return True
        return False
