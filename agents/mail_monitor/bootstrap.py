"""One-shot CLI bootstrap: install Hapax labels + filters in Gmail.

Run after ``agents.mail_monitor.oauth --first-consent`` succeeds and
the operator has approved the ``gmail.modify`` scope.

::

    uv run python -m agents.mail_monitor.bootstrap

Idempotent — second runs are no-ops once labels and filters are
present. ``--check`` mode reports current label / filter state without
creating anything.

The daemon (mail-monitor-005 onwards) calls
:func:`bootstrap_labels` + :func:`bootstrap_filters` in process at
every startup so a fresh deployment self-heals.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from agents.mail_monitor.filter_bootstrap import (
    FilterBootstrapError,
    bootstrap_filters,
    load_filter_specs,
)
from agents.mail_monitor.label_bootstrap import (
    HAPAX_LABEL_NAMES,
    LabelBootstrapError,
    bootstrap_labels,
)
from agents.mail_monitor.oauth import build_gmail_service, load_credentials

log = logging.getLogger(__name__)


def _check(service: Any) -> int:
    """Report current label + filter presence without mutating Gmail."""
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    label_names = {label["name"] for label in labels}
    label_status = {
        name: ("present" if name in label_names else "MISSING") for name in HAPAX_LABEL_NAMES
    }

    filters = service.users().settings().filters().list(userId="me").execute().get("filter", [])
    queries = {f.get("criteria", {}).get("query") for f in filters}
    filter_status = {
        spec["id"]: ("present" if spec["query"] in queries else "MISSING")
        for spec in load_filter_specs()
    }

    print(
        json.dumps(
            {"labels": label_status, "filters": filter_status},
            indent=2,
        )
    )
    has_missing = any(v == "MISSING" for v in label_status.values()) or any(
        v == "MISSING" for v in filter_status.values()
    )
    return 1 if has_missing else 0


def _install(service: Any) -> int:
    try:
        label_ids = bootstrap_labels(service)
    except LabelBootstrapError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    try:
        filter_ids = bootstrap_filters(service, label_ids)
    except FilterBootstrapError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"labels": label_ids, "filters": filter_ids},
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: ``python -m agents.mail_monitor.bootstrap [--check]``."""
    parser = argparse.ArgumentParser(
        prog="python -m agents.mail_monitor.bootstrap",
        description="Install Hapax/* labels + server-side Gmail filters.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report current state; exit 1 if anything is missing.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    creds = load_credentials()
    if creds is None:
        print(
            "FAIL: load_credentials returned None. "
            "Run python -m agents.mail_monitor.oauth --first-consent first.",
            file=sys.stderr,
        )
        return 1
    service = build_gmail_service(creds=creds)
    if service is None:
        print("FAIL: build_gmail_service returned None.", file=sys.stderr)
        return 1

    return _check(service) if args.check else _install(service)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
