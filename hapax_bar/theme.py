"""CSS theme loading and runtime mode switching."""

from __future__ import annotations

from pathlib import Path

from gi.repository import Gdk, Gtk

STYLES_DIR = Path(__file__).parent / "styles"
WORKING_MODE_FILE = Path.home() / ".cache" / "hapax" / "working-mode"

_provider: Gtk.CssProvider | None = None


def _read_working_mode() -> str:
    """Read current working mode from cache file."""
    try:
        return WORKING_MODE_FILE.read_text().strip()
    except FileNotFoundError:
        return "rnd"


def _css_path(mode: str) -> Path:
    return STYLES_DIR / f"hapax-bar-{mode}.css"


def load_initial_theme() -> None:
    """Load CSS for current working mode. Call once at startup."""
    mode = _read_working_mode()
    switch_theme(mode)


def switch_theme(mode: str) -> None:
    """Hot-swap the CSS theme. No restart needed."""
    global _provider

    css_file = _css_path(mode)
    if not css_file.exists():
        css_file = _css_path("rnd")  # fallback

    display = Gdk.Display.get_default()
    if display is None:
        return

    if _provider is not None:
        Gtk.StyleContext.remove_provider_for_display(display, _provider)

    _provider = Gtk.CssProvider()
    _provider.load_from_path(str(css_file))
    Gtk.StyleContext.add_provider_for_display(
        display,
        _provider,
        Gtk.STYLE_PROVIDER_PRIORITY_USER,
    )


def current_mode() -> str:
    return _read_working_mode()
