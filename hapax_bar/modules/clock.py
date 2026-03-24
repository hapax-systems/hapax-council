"""Clock module — simple time display with click-to-toggle format."""

from __future__ import annotations

from gi.repository import GLib, Gtk


class ClockModule(Gtk.Box):
    """Displays current time. Click toggles between short and full format."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, css_classes=["module", "clock"])

        self._short_format = "%H:%M"
        self._long_format = "%Y-%m-%d %H:%M:%S"
        self._use_short = True

        self._label = Gtk.Label()
        self.append(self._label)

        # Click handler
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        # Initial update + timer
        self._update()
        self._interval = GLib.timeout_add(1000, self._update)
        self.connect("destroy", self._on_destroy)

    def _update(self, *_args: object) -> bool:
        fmt = self._short_format if self._use_short else self._long_format
        now = GLib.DateTime.new_now_local()
        text = now.format(fmt) if now else "??:??"
        self._label.set_label(f"[{text}]")
        return GLib.SOURCE_CONTINUE

    def _on_click(self, *_args: object) -> None:
        self._use_short = not self._use_short
        self._update()

    def _on_destroy(self, *_args: object) -> None:
        if self._interval:
            GLib.source_remove(self._interval)
            self._interval = None
