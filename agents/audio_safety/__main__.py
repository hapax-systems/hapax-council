"""Entrypoint: `uv run python -m agents.audio_safety`.

Runs the vinyl-into-Evil-Pet broadcast safety detector. Reads
`HAPAX_AUDIO_SAFETY_*` env vars for tuning (see vinyl_pet_detector.py).
"""

from __future__ import annotations

import logging
import sys

from agents.audio_safety.vinyl_pet_detector import run

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    sys.exit(run())
