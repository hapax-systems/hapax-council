#!/usr/bin/env python3
"""cc-hygiene-ntfy — high-severity ntfy alerts (PR5 surface A).

Reads ``~/.cache/hapax/cc-hygiene-state.json`` (PR1 output) and dispatches
ntfy alerts for any **high-severity** event in the latest sweep, modulo
the per-topic-class throttle.

This script is normally invoked from the sweeper after every sweep, but
it can be run ad-hoc::

    uv run python scripts/cc-hygiene-ntfy.py
    HAPAX_CC_HYGIENE_OFF=1 uv run python scripts/cc-hygiene-ntfy.py  # killswitch

State file shape is contracted by ``scripts/cc_hygiene/models.HygieneState``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# When invoked as a CLI script, the package sits next to us under cc_hygiene/.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Make sibling repo modules importable when invoked directly.
_REPO_ROOT = _HERE.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cc_hygiene.models import HygieneState  # noqa: E402
from cc_hygiene.ntfy import (  # noqa: E402
    DEFAULT_THROTTLE_PATH,
    NTFY_PRIORITY,
    NTFY_TOPIC,
    dispatch_alerts,
)
from cc_hygiene.state import DEFAULT_STATE_PATH  # noqa: E402

LOG = logging.getLogger("cc-hygiene-ntfy-cli")


def _load_state(path: Path) -> HygieneState | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        LOG.warning("could not read state file %s: %s", path, exc)
        return None
    try:
        return HygieneState.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("invalid state-file shape: %s", exc)
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-path",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="hygiene-state JSON written by the sweeper (PR1).",
    )
    parser.add_argument(
        "--throttle-path",
        type=Path,
        default=DEFAULT_THROTTLE_PATH,
        help="Per-topic-class throttle state file.",
    )
    parser.add_argument("--topic", default=NTFY_TOPIC, help="ntfy topic.")
    parser.add_argument("--priority", default=NTFY_PRIORITY, help="ntfy priority.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    state = _load_state(args.state_path)
    if state is None:
        LOG.info("no state file at %s — nothing to alert on", args.state_path)
        return 0

    if state.killswitch_active:
        LOG.info("state file marks killswitch active; no alerts dispatched")
        return 0

    results = dispatch_alerts(
        state.events,
        throttle_path=args.throttle_path,
        topic=args.topic,
        priority=args.priority,
    )
    sent = sum(1 for r in results if r.sent)
    throttled = sum(1 for r in results if r.reason == "throttled")
    skipped = sum(1 for r in results if r.reason == "sub-threshold")
    LOG.info(
        "ntfy summary: %d sent, %d throttled, %d sub-threshold (of %d events)",
        sent,
        throttled,
        skipped,
        len(state.events),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
