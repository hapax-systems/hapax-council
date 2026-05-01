#!/usr/bin/env python
"""Project GitHub public-surface evidence into publication-log witness rows."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from shared.github_public_surface import GitHubPublicSurfaceReport
from shared.github_publication_log import (
    DEFAULT_PUBLICATION_LOG,
    events_from_github_public_surface_report,
    write_publication_log_events,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / "docs/repo-pres/github-public-surface-live-state-reconcile.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_PUBLICATION_LOG)
    parser.add_argument("--generated-at", default=_now_iso())
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print JSONL rows to stdout instead of appending to the publication log.",
    )
    args = parser.parse_args(argv)

    report = _read_report(args.report)
    events = events_from_github_public_surface_report(report, generated_at=args.generated_at)
    lines = write_publication_log_events(events, log_path=args.output, dry_run=args.dry_run)
    if args.dry_run:
        sys.stdout.writelines(lines)
    else:
        print(
            json.dumps(
                {
                    "events_written": len(lines),
                    "output": str(args.output),
                    "report": str(args.report),
                    "claim_ceiling": "publication_witness_rows",
                    "authority": "witness_only",
                },
                sort_keys=True,
            )
        )
    return 0


def _read_report(path: Path) -> GitHubPublicSurfaceReport:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"cannot read GitHub public-surface report: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"malformed GitHub public-surface report: {path}: {exc}") from exc
    return GitHubPublicSurfaceReport.model_validate(payload)


def _now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
