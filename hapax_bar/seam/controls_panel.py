"""Controls panel — state-aware secondary controls for the seam layer."""

from __future__ import annotations

import subprocess

from gi.repository import GLib, Gtk


class ControlsPanel(Gtk.Box):
    """Voice and studio controls with live state indicators."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            css_classes=["controls-panel"],
        )

        # Voice state + action
        self._voice_status = Gtk.Label(css_classes=["metrics-row"])
        self.append(self._voice_status)

        self._voice_btn = Gtk.Button(css_classes=["seam-button"])
        self._voice_btn.connect("clicked", self._on_voice_toggle)
        self.append(self._voice_btn)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self.append(sep)

        # Studio state + action
        self._studio_status = Gtk.Label(css_classes=["metrics-row"])
        self.append(self._studio_status)

        studio_btn = Gtk.Button(label="toggle", css_classes=["seam-button"])
        studio_btn.connect("clicked", self._on_studio_toggle)
        self.append(studio_btn)

        # Poll state every 3s
        self._voice_active = False
        self._update_state()
        GLib.timeout_add(3000, self._update_state)

    def _update_state(self, *_a: object) -> bool:
        # Check voice daemon state
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "hapax-voice.service"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            state = result.stdout.strip()
        except Exception:
            state = "unknown"

        self._voice_active = state == "active"
        if state == "active":
            self._voice_status.set_label("Voice: active")
            self._voice_status.set_css_classes(["metrics-row", "healthy"])
            self._voice_btn.set_label("stop")
        elif state == "failed":
            self._voice_status.set_label("Voice: failed")
            self._voice_status.set_css_classes(["metrics-row", "failed"])
            self._voice_btn.set_label("restart")
        else:
            self._voice_status.set_label(f"Voice: {state}")
            self._voice_status.set_css_classes(["metrics-row"])
            self._voice_btn.set_label("start")

        # Check visual layer
        try:
            from pathlib import Path

            vl = Path("/dev/shm/hapax-compositor/visual-layer-enabled.txt")
            enabled = vl.read_text().strip() == "true" if vl.exists() else False
        except Exception:
            enabled = False

        self._studio_status.set_label(f"Visual: {'on' if enabled else 'off'}")
        return GLib.SOURCE_CONTINUE

    def _on_voice_toggle(self, _btn: Gtk.Button) -> None:
        action = "stop" if self._voice_active else "start"
        subprocess.Popen(["systemctl", "--user", action, "hapax-voice.service"])
        GLib.timeout_add(1000, self._update_state)

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
