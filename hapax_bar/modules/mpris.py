"""MPRIS media player — AstalMpris, real-time."""

from __future__ import annotations

from gi.repository import AstalMpris, Gtk


class MprisModule(Gtk.Box):
    """Shows currently playing media. Click play/pause, scroll next/prev."""

    def __init__(self, max_length: int = 40) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "mpris"],
        )
        self._max_length = max_length
        self._label = Gtk.Label()
        self.append(self._label)
        self._player: AstalMpris.Player | None = None

        # Click: play/pause
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        # Scroll: next/prev
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        mpris = AstalMpris.get_default()
        mpris.connect("notify::players", self._on_players_changed)
        self._on_players_changed()

    def _on_players_changed(self, *_args: object) -> None:
        mpris = AstalMpris.get_default()
        players = mpris.get_players()

        # Find first non-Firefox player
        player = None
        for p in players:
            identity = (p.get_identity() or "").lower()
            bus_name = (p.get_bus_name() or "").lower()
            if "firefox" not in identity and "firefox" not in bus_name:
                player = p
                break

        if self._player is not None:
            # Can't easily disconnect — just replace
            pass

        self._player = player
        if player is None:
            self.set_visible(False)
            return

        self.set_visible(True)
        player.connect("notify::title", self._update)
        player.connect("notify::artist", self._update)
        player.connect("notify::playback-status", self._update)
        self._update()

    def _update(self, *_args: object) -> None:
        if self._player is None:
            return

        artist = self._player.get_artist() or ""
        title = self._player.get_title() or ""
        status = self._player.get_playback_status()

        text = f"{artist} - {title}" if artist else title
        if len(text) > self._max_length:
            text = text[: self._max_length - 1] + "\u2026"

        paused = status == AstalMpris.PlaybackStatus.PAUSED
        prefix = "|| " if paused else ""
        self._label.set_label(f"[{prefix}{text}]")
        self.set_css_classes(["module", "mpris", "paused"] if paused else ["module", "mpris"])

    def _on_click(self, *_args: object) -> None:
        if self._player is not None:
            self._player.play_pause()

    def _on_scroll(self, _ctrl: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        if self._player is None:
            return False
        if dy < 0:
            self._player.next()
        else:
            self._player.previous()
        return True
