#!/usr/bin/env python3
"""cc-hygiene-dashboard-renderer — vault dashboard sentinel-block writer (PR5 surface B).

Reads ``~/.cache/hapax/cc-hygiene-state.json`` (PR1 output) and updates
the operator-facing vault dashboard at
``~/Documents/Personal/20-projects/hapax-cc-tasks/_dashboard/cc-active.md``.

The renderer writes ONLY between ``<!-- HYGIENE-AUTO-START -->`` /
``<!-- HYGIENE-AUTO-END -->`` sentinels. Existing Dataview tables and
hand-edits outside the sentinel block are preserved verbatim.

Usage::

    uv run python scripts/cc-hygiene-dashboard-renderer.py
    HAPAX_CC_HYGIENE_OFF=1 uv run python scripts/cc-hygiene-dashboard-renderer.py  # killswitch
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from cc_hygiene.dashboard import (  # noqa: E402
    DEFAULT_DASHBOARD_PATH,
    DEFAULT_VAULT_ACTIVE,
    update_dashboard,
)
from cc_hygiene.events import DEFAULT_EVENT_LOG_PATH  # noqa: E402
from cc_hygiene.models import HygieneState  # noqa: E402
from cc_hygiene.state import DEFAULT_STATE_PATH  # noqa: E402

LOG = logging.getLogger("cc-hygiene-dashboard-cli")


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
        "--dashboard-path",
        type=Path,
        default=DEFAULT_DASHBOARD_PATH,
        help="Dashboard markdown file to update (sentinel block only).",
    )
    parser.add_argument(
        "--event-log-path",
        type=Path,
        default=DEFAULT_EVENT_LOG_PATH,
        help="Sweeper event log (used to render Recent Hygiene Events).",
    )
    parser.add_argument(
        "--vault-active",
        type=Path,
        default=DEFAULT_VAULT_ACTIVE,
        help="Active cc-task notes directory (used for status counters).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    state = _load_state(args.state_path)
    if state is None:
        LOG.info("no state file at %s — nothing to render", args.state_path)
        return 0

    out = update_dashboard(
        state,
        dashboard_path=args.dashboard_path,
        event_log_path=args.event_log_path,
        vault_active=args.vault_active,
    )
    LOG.info("dashboard updated: %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
