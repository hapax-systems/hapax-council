"""Session panel — alpha/beta relay protocol status for seam layer."""

from __future__ import annotations

from pathlib import Path

from gi.repository import Gtk

RELAY_DIR = Path.home() / ".cache" / "hapax" / "relay"


class SessionPanel(Gtk.Box):
    """Shows the other session's branch, last activity, and PR state."""

    def __init__(self, my_session: str = "alpha") -> None:
        # Default "alpha" is correct: hapax-bar.service runs from the alpha
        # worktree (~/projects/hapax-council/). It always shows beta's status.
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            css_classes=["session-panel"],
        )
        self._other = "beta" if my_session == "alpha" else "alpha"
        self._label = Gtk.Label(xalign=0, css_classes=["metrics-row"])
        self.append(self._label)

    def update(self) -> None:
        """Read relay protocol state for the other session."""
        peer_file = RELAY_DIR / "working-mode.yaml"
        try:
            import yaml

            data = yaml.safe_load(peer_file.read_text()) or {}
        except Exception:
            self._label.set_label(f"{self._other.title()}: relay data unavailable")
            return

        sessions = data if isinstance(data, dict) else {}
        peer = sessions.get(self._other, {})
        if not peer:
            self._label.set_label(f"{self._other.title()}: no session data")
            return

        workstream = peer.get("workstream", "?")
        focus = peer.get("focus", "?")
        updated = peer.get("updated", "?")

        self._label.set_label(
            f"{self._other.title()}: {workstream}\n  Focus: {focus}  |  Last: {updated}"
        )
