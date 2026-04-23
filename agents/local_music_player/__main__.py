"""Entrypoint: ``uv run python -m agents.local_music_player``."""

from __future__ import annotations

import logging
import sys

from agents.local_music_player.player import LocalMusicPlayer

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    sys.exit(LocalMusicPlayer().run())
