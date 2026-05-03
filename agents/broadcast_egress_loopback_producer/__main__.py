"""CLI entry: ``uv run python -m agents.broadcast_egress_loopback_producer``.

Configured via ``HAPAX_LOOPBACK_*`` env vars (see
:func:`producer.load_config_from_env`). The systemd unit
``hapax-broadcast-egress-loopback-producer.service`` invokes this
module as a long-running ``Type=simple`` daemon that ticks once per
second and writes the witness JSON consumed by PR #2209's evaluator.
"""

from __future__ import annotations

import logging
import sys

from .producer import EgressLoopbackProducer, load_config_from_env

log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = load_config_from_env()
    producer = EgressLoopbackProducer(**cfg)  # type: ignore[arg-type]
    try:
        producer.run_forever()
    except KeyboardInterrupt:
        log.info("egress loopback producer: shutting down on SIGINT")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
