"""Entry point: uv run python -m agents.visual_layer_aggregator"""

from __future__ import annotations

import asyncio
import logging

from .aggregator import VisualLayerAggregator


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    agg = VisualLayerAggregator()
    try:
        await agg.run()
    finally:
        await agg.close()


if __name__ == "__main__":
    asyncio.run(main())
