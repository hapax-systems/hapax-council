"""agents/audio_perception/__main__.py — Entry point for the audio perception daemon."""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict

from agents.audio_perception.daemon import run_forever
from agents.audio_perception.models import load_clap, load_essentia, load_pyannote


def main() -> None:
    parser = argparse.ArgumentParser(description="Hapax audio perception daemon (CPU-only)")
    parser.add_argument(
        "--tick-s",
        type=float,
        default=float(os.environ.get("HAPAX_AUDIO_PERCEPTION_TICK_S", "1.0")),
    )
    parser.add_argument("--once", action="store_true", help="Run one perception tick and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.once:
        from agents.audio_perception.daemon import perceive_once, write_state

        clap = load_clap()
        essentia = load_essentia()
        pyannote = load_pyannote()
        state = perceive_once(clap, essentia, pyannote)
        write_state(state)
        print(json.dumps(asdict(state), indent=2))
    else:
        run_forever(tick_s=args.tick_s)


if __name__ == "__main__":
    main()
