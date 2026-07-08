#!/usr/bin/env python3
"""Build witness-only freshness state for public publication surfaces."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.github_public_surface import GitHubPublicSurfaceReport
from shared.github_publication_log import events_from_github_public_surface_report
from shared.publication_freshness import (
    DEFAULT_FRESHNESS_EVENTS,
    DEFAULT_FRESHNESS_STATE,
    DEFAULT_GITHUB_TTL_S,
    build_publication_freshness_event,
    build_publication_freshness_snapshot,
    github_events_to_freshness_envelopes,
    parse_iso_z,
    write_publication_freshness_events,
    write_publication_freshness_snapshot,
)

DEFAULT_GITHUB_REPORT = REPO_ROOT / "docs/repo-pres/github-public-surface-live-state-reconcile.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-report", type=Path, default=DEFAULT_GITHUB_REPORT)
    parser.add_argument("--output-events", type=Path, default=DEFAULT_FRESHNESS_EVENTS)
    parser.add_argument("--output-state", type=Path, default=DEFAULT_FRESHNESS_STATE)
    parser.add_argument("--generated-at", default=_now_iso())
    parser.add_argument("--github-ttl-s", type=int, default=DEFAULT_GITHUB_TTL_S)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the derived state summary instead of writing ledger/state files.",
    )
    parser.add_argument(
        "--fail-on-blockers",
        action="store_true",
        help="Exit 1 if the derived freshness state has public-current blockers.",
    )
    args = parser.parse_args(argv)

    report = _read_github_report(args.github_report)
    _validate_audit_timestamp(args.generated_at, report.generated_at)
    github_checked_at = report.generated_at
    github_events = events_from_github_public_surface_report(
        report,
        generated_at=github_checked_at,
    )
    envelopes = github_events_to_freshness_envelopes(
        github_events,
        checked_at=github_checked_at,
        ttl_s=args.github_ttl_s,
    )
    snapshot = build_publication_freshness_snapshot(envelopes, generated_at=args.generated_at)
    freshness_events = tuple(
        build_publication_freshness_event(
            envelope,
            event_type="publication.surface_readback",
            generated_at=args.generated_at,
            occurred_at=github_checked_at,
        )
        for envelope in envelopes
    )

    if args.dry_run:
        print(
            json.dumps(
                {
                    "authority": "freshness_witness_only",
                    "claim_ceiling": "freshness_witness_only",
                    "events": [event.model_dump(mode="json") for event in freshness_events],
                    "github_checked_at": github_checked_at,
                    "github_report": str(args.github_report),
                    "state": snapshot.model_dump(mode="json"),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        event_lines = write_publication_freshness_events(
            freshness_events,
            log_path=args.output_events,
        )
        write_publication_freshness_snapshot(snapshot, path=args.output_state)
        print(
            json.dumps(
                {
                    "authority": "freshness_witness_only",
                    "claim_ceiling": "freshness_witness_only",
                    "events_written": len(event_lines),
                    "github_checked_at": github_checked_at,
                    "output_events": str(args.output_events),
                    "output_state": str(args.output_state),
                    "github_report": str(args.github_report),
                    "blockers": list(snapshot.blockers),
                },
                sort_keys=True,
            )
        )

    return 1 if args.fail_on_blockers and snapshot.blockers else 0


def _read_github_report(path: Path) -> GitHubPublicSurfaceReport:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"cannot read GitHub public-surface report: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"malformed GitHub public-surface report: {path}: {exc}") from exc
    return GitHubPublicSurfaceReport.model_validate(payload)


def _validate_audit_timestamp(generated_at: str, checked_at: str) -> None:
    if parse_iso_z(generated_at) < parse_iso_z(checked_at):
        raise SystemExit(
            "publication freshness audit generated_at predates the source GitHub "
            f"report generated_at ({checked_at}); rerun with a generated_at at or "
            "after the checked report timestamp"
        )


def _now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
