"""agents/audio_perception/__main__.py — Entry point for the audio perception daemon."""

from __future__ import annotations

import argparse
import logging
import os

from agents.audio_perception.daemon import run_forever


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

        state = perceive_once()
        write_state(state)
        import json
        from dataclasses import asdict

        print(json.dumps(asdict(state), indent=2))
    else:
        run_forever(tick_s=args.tick_s)


if __name__ == "__main__":
    main()
