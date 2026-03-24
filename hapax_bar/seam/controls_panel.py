"""Controls panel — secondary controls for the seam layer."""

from __future__ import annotations

import subprocess

from gi.repository import Gtk


class ControlsPanel(Gtk.Box):
    """Voice start/stop/restart + studio toggle."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            css_classes=["controls-panel"],
        )

        # Voice controls
        voice_label = Gtk.Label(label="Voice:", css_classes=["metrics-row"])
        self.append(voice_label)

        for label, action in [("Start", "start"), ("Stop", "stop"), ("Restart", "restart")]:
            btn = Gtk.Button(label=label, css_classes=["seam-button"])
            btn.connect("clicked", self._on_voice_action, action)
            self.append(btn)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self.append(sep)

        # Studio toggle
        studio_btn = Gtk.Button(label="Toggle Visual Layer", css_classes=["seam-button"])
        studio_btn.connect("clicked", self._on_studio_toggle)
        self.append(studio_btn)

    @staticmethod
    def _on_voice_action(_btn: Gtk.Button, action: str) -> None:
        subprocess.Popen(["systemctl", "--user", action, "hapax-voice.service"])

    @staticmethod
    def _on_studio_toggle(_btn: Gtk.Button) -> None:
        import urllib.request

        try:
            req = urllib.request.Request(
                "http://localhost:8051/api/studio/visual-layer/toggle",
                method="POST",
                headers={"Content-Type": "application/json"},
                data=b"{}",
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass
