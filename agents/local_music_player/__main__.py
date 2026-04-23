"""Entrypoint: ``uv run python -m agents.local_music_player``.

Phase 4b: spins up a MusicProgrammer on top of the player so the
daemon auto-recruits the next track when one ends. The repos the
programmer queries are loaded fresh on each ``select_next()`` call.
"""

from __future__ import annotations

import logging
import sys

from agents.local_music_player.player import LocalMusicPlayer, PlayerConfig
from agents.local_music_player.programmer import MusicProgrammer
from shared.music_repo import LocalMusicRepo

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = PlayerConfig.from_env()
    local_repo = LocalMusicRepo(path=cfg.repo_path)
    local_repo.load()
    sc_repo = LocalMusicRepo(path=cfg.sc_repo_path)
    sc_repo.load()
    programmer = MusicProgrammer(local_repo=local_repo, sc_repo=sc_repo)
    sys.exit(LocalMusicPlayer(cfg, programmer=programmer).run())
