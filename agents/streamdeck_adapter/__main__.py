"""Entrypoint for ``python -m agents.streamdeck_adapter``."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .adapter import run_adapter

DEFAULT_KEY_MAP = Path("config/streamdeck.yaml")


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    key_map_path = Path(os.environ.get("HAPAX_STREAMDECK_KEYMAP", str(DEFAULT_KEY_MAP)))
    run_adapter(key_map_path)


if __name__ == "__main__":
    main()
