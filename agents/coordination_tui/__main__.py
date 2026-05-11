"""agents/coordination_tui/__main__.py — Entry point for the coordination TUI."""

from agents.coordination_tui.app import CoordinationApp


def main() -> None:
    app = CoordinationApp()
    app.run()


if __name__ == "__main__":
    main()
