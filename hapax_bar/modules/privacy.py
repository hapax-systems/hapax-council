"""Privacy indicator module — monitors PipeWire for active camera/mic usage."""

from __future__ import annotations

import json
import subprocess

from gi.repository import GLib, Gtk


class PrivacyModule(Gtk.Box):
    """Displays [cam]/[mic] indicators when camera or microphone nodes are active.

    Polls PipeWire via pw-dump to detect active audio/video capture nodes.
    Shows nothing when no capture is active (zero-footprint when idle).
    """

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "privacy"],
        )
        self._cam_label = Gtk.Label(label="")
        self._mic_label = Gtk.Label(label="")
        self.append(self._cam_label)
        self.append(self._mic_label)

        # Poll every 5s — lightweight check
        self._poll_id = GLib.timeout_add(5_000, self._poll)
        self._poll()

    def _poll(self, *_args: object) -> bool:
        cam_active = False
        mic_active = False

        try:
            result = subprocess.run(
                ["pw-dump", "--no-colors"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                nodes = json.loads(result.stdout)
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    info = node.get("info", {})
                    props = info.get("props", {}) if isinstance(info, dict) else {}
                    media_class = props.get("media.class", "")
                    state = info.get("state", "") if isinstance(info, dict) else ""

                    if state == "running":
                        if "Video/Source" in media_class:
                            cam_active = True
                        elif "Audio/Source" in media_class or "Stream/Input" in media_class:
                            mic_active = True
        except Exception:
            pass

        self._cam_label.set_label("[cam]" if cam_active else "")
        self._cam_label.set_visible(cam_active)
        self._mic_label.set_label("[mic]" if mic_active else "")
        self._mic_label.set_visible(mic_active)

        classes = ["module", "privacy"]
        if cam_active or mic_active:
            classes.append("active")
        self.set_css_classes(classes)

        if cam_active or mic_active:
            parts = []
            if cam_active:
                parts.append("Camera active")
            if mic_active:
                parts.append("Microphone active")
            self.set_tooltip_text("\n".join(parts))
        else:
            self.set_tooltip_text("")

        self.set_visible(cam_active or mic_active)
        return GLib.SOURCE_CONTINUE
