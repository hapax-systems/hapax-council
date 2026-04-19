"""Entrypoint for ``python -m agents.kdeconnect_bridge``."""

from __future__ import annotations

import asyncio
import logging
import os

from .bridge import run_bridge


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_bridge())


if __name__ == "__main__":
    main()
