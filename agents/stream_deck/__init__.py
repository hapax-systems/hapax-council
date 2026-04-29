"""Stream Deck control surface (task #140, Phase 1).

Physical hardware surface — 15-key StreamDeck Mini — mapped to the Logos
command registry. The operator presses a key, the adapter resolves the
slot to a ``(command, args)`` pair from ``config/stream-deck/manifest.yaml``,
and dispatches through the central Logos control surface.

Phase 1 (this module) ships the adapter layer only. Wiring to the
``streamdeck`` python library is a Phase 2 concern; the probe script
(``scripts/stream-deck-probe.py``) degrades gracefully when the library
or the hardware is absent, so the adapter can be exercised end-to-end
with a mocked dispatcher until hardware lands.
"""

from agents.stream_deck.adapter import (
    DispatchResult,
    StreamDeckAdapter,
    StreamDeckKey,
    StreamDeckManifest,
    StreamDeckManifestError,
    load_manifest,
)

__all__ = [
    "DispatchResult",
    "StreamDeckAdapter",
    "StreamDeckKey",
    "StreamDeckManifest",
    "StreamDeckManifestError",
    "load_manifest",
]
