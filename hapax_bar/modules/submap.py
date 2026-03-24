"""Submap indicator — shows active Hyprland submap."""

from __future__ import annotations

from gi.repository import AstalHyprland, Gtk


class SubmapModule(Gtk.Box):
    """Shows [submap_name] when a submap is active, hides otherwise."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "submap"],
        )
        self._label = Gtk.Label()
        self.append(self._label)

        hypr = AstalHyprland.get_default()
        hypr.connect("event", self._on_event)
        self.set_visible(False)

    def _on_event(self, _hypr: AstalHyprland.Hyprland, event: str, args: str) -> None:
        if event == "submap":
            name = args.strip()
            if name:
                self._label.set_label(f"[{name}]")
                self.set_visible(True)
            else:
                self.set_visible(False)
