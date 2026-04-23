"""Local music player daemon — content-source-registry Phase 4a.

Watches `/dev/shm/hapax-compositor/music-selection.json` for operator-
approved selections written by the music_candidate_surfacer flow + the
`hapax-music-play` CLI, plays the selected track via pw-cat (default
sink = PipeWire default = Ryzen analog stereo on the operator's box),
writes splattribution to compositor SHM, and marks the play in the
LocalMusicRepo (so the recency cooldown updates).

Per `docs/superpowers/plans/2026-04-23-content-source-registry-plan.md`
Phase 4 + the broader operator directive 2026-04-23: aim for music
actually playing on stream.

Read-only on the broadcast graph: pw-cat writes to a sink (default OR
``HAPAX_MUSIC_PLAYER_SINK``); the operator's existing L-12 routing
(CH11/12 → AUX-B → Evil Pet → broadcast capture) is what carries the
audio into the stream. This daemon does NOT modify PipeWire links.
"""

from agents.local_music_player.player import (
    DEFAULT_SELECTION_PATH,
    LocalMusicPlayer,
    PlayerConfig,
    write_selection,
)

__all__ = [
    "DEFAULT_SELECTION_PATH",
    "LocalMusicPlayer",
    "PlayerConfig",
    "write_selection",
]
