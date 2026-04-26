"""Module entry point: ``python -m agents.payment_processors``.

Boots the ``MonetizationAggregator`` daemon. Used by the
``hapax-money-rails.service`` systemd unit and by ad-hoc operator
runs.
"""

from __future__ import annotations

import logging
import os
import signal
import sys

from agents.payment_processors.monetization_aggregator import MonetizationAggregator


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_MONEY_RAILS_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    aggregator = MonetizationAggregator()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, lambda *_: aggregator.stop())
        except ValueError:
            pass
    aggregator.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
