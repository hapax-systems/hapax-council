"""Workspace buttons — AstalHyprland, real-time via IPC socket."""

from __future__ import annotations

from gi.repository import AstalHyprland, GObject, Gtk

SYNC = GObject.BindingFlags.SYNC_CREATE


class WorkspacesModule(Gtk.Box):
    """Clickable workspace buttons with focused/urgent highlighting."""

    def __init__(self, workspace_ids: list[int] | None = None) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "workspaces"],
        )
        self._workspace_ids = workspace_ids or list(range(1, 6))
        self._buttons: dict[int, Gtk.Button] = {}
        self._hypr = AstalHyprland.get_default()

        for ws_id in self._workspace_ids:
            btn = Gtk.Button(label=str(ws_id), css_classes=["workspace"])
            btn.connect("clicked", self._on_click, ws_id)
            self._buttons[ws_id] = btn
            self.append(btn)

        self._hypr.connect("notify::focused-workspace", self._sync)
        self._hypr.connect("event", self._on_event)
        self._sync()

    def _sync(self, *_args: object) -> None:
        focused = self._hypr.get_focused_workspace()
        focused_id = focused.get_id() if focused else -1
        for ws_id, btn in self._buttons.items():
            classes = ["workspace"]
            if ws_id == focused_id:
                classes.append("focused")
            # Check if workspace has clients (occupied)
            ws = self._hypr.get_workspace(ws_id)
            if ws is not None:
                classes.append("occupied")
            btn.set_css_classes(classes)

    def _on_event(self, _hypr: AstalHyprland.Hyprland, event: str, _args: str) -> None:
        if event in ("urgent", "createworkspacev2", "destroyworkspacev2"):
            self._sync()

    def _on_click(self, _btn: Gtk.Button, ws_id: int) -> None:
        self._hypr.dispatch("workspace", str(ws_id))
