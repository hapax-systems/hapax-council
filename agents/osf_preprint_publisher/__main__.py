"""One-shot CLI for the OSF preprint publisher.

Usage::

    uv run python -m agents.osf_preprint_publisher --slug <slug>

Loads a single ``PreprintArtifact`` from ``~/hapax-state/publish/inbox/{slug}.json``
and dispatches it to the OSF v2 REST API. Production dispatch goes
through ``agents.publish_orchestrator``; this CLI is for manual
single-artifact debugging only.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from agents.osf_preprint_publisher.publisher import publish_artifact
from shared.preprint_artifact import INBOX_DIR_NAME, PreprintArtifact

log = logging.getLogger(__name__)


def _default_state_root() -> Path:
    env = os.environ.get("HAPAX_STATE")
    if env:
        return Path(env)
    return Path.home() / "hapax-state"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="agents.osf_preprint_publisher",
        description="One-shot OSF preprint dispatch for debugging.",
    )
    parser.add_argument("--slug", required=True, help="Inbox artifact slug")
    parser.add_argument(
        "--state-root",
        type=Path,
        default=_default_state_root(),
        help="Override $HAPAX_STATE for testing",
    )
    args = parser.parse_args(argv)

    inbox_path = args.state_root / INBOX_DIR_NAME / f"{args.slug}.json"
    if not inbox_path.exists():
        log.error("inbox artifact not found: %s", inbox_path)
        return 2

    artifact = PreprintArtifact.model_validate_json(inbox_path.read_text())
    result = publish_artifact(artifact)
    log.info("dispatch result for %s: %s", args.slug, result)
    return 0 if result == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
