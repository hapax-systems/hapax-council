"""Systemd failed units indicator."""

from __future__ import annotations

import subprocess

from gi.repository import GLib, Gtk


class SystemdFailedModule(Gtk.Box):
    """Shows [!fail:N] when user systemd units have failed. Hidden when all OK."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "systemd-failed"],
        )
        self._label = Gtk.Label()
        self.append(self._label)
        self.set_visible(False)

        self._update()
        GLib.timeout_add(30_000, self._update)

    def _update(self, *_args: object) -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "--state=failed", "--no-pager", "--no-legend", "-q"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            count = len(lines)
        except Exception:
            count = 0

        if count > 0:
            self._label.set_label(f"[!fail:{count}]")
            self.set_visible(True)
            self.set_tooltip_text(f"{count} failed systemd user unit(s)")
        else:
            self.set_visible(False)
        return GLib.SOURCE_CONTINUE
