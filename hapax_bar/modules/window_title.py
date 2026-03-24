"""Active window title — AstalHyprland, real-time."""

from __future__ import annotations

from gi.repository import AstalHyprland, Gtk


class WindowTitleModule(Gtk.Box):
    """Shows the focused window title, truncated."""

    def __init__(self, max_length: int = 60) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "window-title"],
        )
        self._max_length = max_length
        self._label = Gtk.Label()
        self.append(self._label)

        hypr = AstalHyprland.get_default()
        hypr.connect("notify::focused-client", self._sync)
        self._client_handler: int | None = None
        self._current_client: AstalHyprland.Client | None = None
        self._sync()

    def _sync(self, *_args: object) -> None:
        hypr = AstalHyprland.get_default()
        client = hypr.get_focused_client()

        # Disconnect from previous client
        if self._client_handler is not None and self._current_client is not None:
            self._current_client.disconnect(self._client_handler)
            self._client_handler = None

        if client is None:
            self._label.set_label("")
            self._current_client = None
            return

        self._current_client = client
        self._client_handler = client.connect("notify::title", self._on_title_changed)
        self._on_title_changed()

    def _on_title_changed(self, *_args: object) -> None:
        if self._current_client is None:
            return
        title = self._current_client.get_title() or ""
        if len(title) > self._max_length:
            title = title[: self._max_length - 1] + "\u2026"
        self._label.set_label(title)
