"""Daemon entry point: ``python -m agents.hapax_steamdeck_bridge``."""

from __future__ import annotations

import logging
import os

from agents.hapax_steamdeck_bridge.monitor import (
    DEFAULT_POLL_INTERVAL_S,
    DEFAULT_V4L2_DEVICE,
    SteamDeckMonitor,
)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    monitor = SteamDeckMonitor(
        v4l2_device=os.environ.get("HAPAX_STEAMDECK_V4L2", DEFAULT_V4L2_DEVICE),
        poll_interval_s=float(
            os.environ.get("HAPAX_STEAMDECK_POLL_S", str(DEFAULT_POLL_INTERVAL_S))
        ),
    )
    monitor.run_forever()


if __name__ == "__main__":
    main()
