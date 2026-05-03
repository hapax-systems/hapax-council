"""systemd-driven entry point: `python -m agents.m8_control`."""

from __future__ import annotations

import asyncio
import logging

from agents.m8_control.daemon import M8ControlDaemon


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    daemon = M8ControlDaemon()
    asyncio.run(daemon.serve())


if __name__ == "__main__":
    main()
