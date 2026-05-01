"""Module entrypoint: ``python -m agents.overlay_producer``."""

from __future__ import annotations

from agents.overlay_producer.daemon import main

if __name__ == "__main__":
    raise SystemExit(main())
