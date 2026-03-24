"""Audio module — volume + mic via AstalWp (WirePlumber), real-time."""

from __future__ import annotations

import math

from gi.repository import AstalWp, GObject, Gtk

SYNC = GObject.BindingFlags.SYNC_CREATE


class _AudioEndpoint(Gtk.Box):
    """Base for speaker/mic display with scroll-to-adjust and click-to-mute."""

    def __init__(self, prefix: str, css_extra: list[str] | None = None) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "audio"] + (css_extra or []),
        )
        self._prefix = prefix
        self._label = Gtk.Label()
        self.append(self._label)
        self._endpoint: AstalWp.Endpoint | None = None

        # Click to toggle mute
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        # Scroll to adjust volume
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

    def set_endpoint(self, endpoint: AstalWp.Endpoint | None) -> None:
        self._endpoint = endpoint
        if endpoint is None:
            self._label.set_label(f"[{self._prefix}:--]")
            return
        endpoint.connect("notify::volume", self._update)
        endpoint.connect("notify::mute", self._update)
        self._update()

    def _update(self, *_args: object) -> None:
        if self._endpoint is None:
            return
        if self._endpoint.get_mute():
            self._label.set_label(f"[{self._prefix}:mute]")
            self.set_css_classes(["module", "audio", "muted"])
        else:
            vol = math.floor(self._endpoint.get_volume() * 100)
            self._label.set_label(f"[{self._prefix}:{vol}%]")
            self.set_css_classes(["module", "audio"])

    def _on_click(self, *_args: object) -> None:
        if self._endpoint is not None:
            self._endpoint.set_mute(not self._endpoint.get_mute())

    def _on_scroll(self, _ctrl: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        if self._endpoint is None:
            return False
        current = self._endpoint.get_volume()
        step = 0.02
        new_vol = max(0.0, min(1.0, current - dy * step))
        self._endpoint.set_volume(new_vol)
        return True


class VolumeModule(_AudioEndpoint):
    """Speaker volume display."""

    def __init__(self) -> None:
        super().__init__("vol")
        wp = AstalWp.get_default()
        if wp is not None:
            audio = wp.get_audio()
            if audio is not None:
                speaker = audio.get_default_speaker()
                self.set_endpoint(speaker)
                audio.connect("notify::default-speaker", self._on_default_changed)

    def _on_default_changed(self, audio: AstalWp.Audio, *_args: object) -> None:
        self.set_endpoint(audio.get_default_speaker())


class MicModule(_AudioEndpoint):
    """Microphone volume display."""

    def __init__(self) -> None:
        super().__init__("mic")
        wp = AstalWp.get_default()
        if wp is not None:
            audio = wp.get_audio()
            if audio is not None:
                mic = audio.get_default_microphone()
                self.set_endpoint(mic)
                audio.connect("notify::default-microphone", self._on_default_changed)

    def _on_default_changed(self, audio: AstalWp.Audio, *_args: object) -> None:
        self.set_endpoint(audio.get_default_microphone())
