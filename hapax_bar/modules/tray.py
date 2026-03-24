"""System tray — AstalTray, real-time via DBus."""

from __future__ import annotations

from gi.repository import AstalTray, GObject, Gtk

SYNC = GObject.BindingFlags.SYNC_CREATE


class TrayModule(Gtk.Box):
    """System tray icons with popup menus."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "tray"],
        )
        self._items: dict[str, Gtk.MenuButton] = {}

        tray = AstalTray.get_default()
        tray.connect("item-added", self._on_item_added)
        tray.connect("item-removed", self._on_item_removed)

    def _on_item_added(self, tray: AstalTray.Tray, item_id: str) -> None:
        if item_id in self._items:
            return

        item = tray.get_item(item_id)
        if item is None:
            return

        icon = Gtk.Image()
        item.bind_property("gicon", icon, "gicon", SYNC)

        menu_model = item.get_menu_model()
        popover = Gtk.PopoverMenu.new_from_model(menu_model) if menu_model else Gtk.Popover()

        button = Gtk.MenuButton(child=icon, popover=popover)

        action_group = item.get_action_group()
        if action_group is not None:
            popover.insert_action_group("dbusmenu", action_group)

        item.connect(
            "notify::action-group",
            lambda *_: popover.insert_action_group("dbusmenu", item.get_action_group()),
        )

        self._items[item_id] = button
        self.append(button)

    def _on_item_removed(self, _tray: AstalTray.Tray, item_id: str) -> None:
        button = self._items.pop(item_id, None)
        if button is not None:
            self.remove(button)
            button.run_dispose()
