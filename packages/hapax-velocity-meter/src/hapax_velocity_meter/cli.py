"""hapax-velocity-meter CLI."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING

from hapax_velocity_meter.bibtex import bibtex_self_citation
from hapax_velocity_meter.measurement import measure_repo

if TYPE_CHECKING:
    from collections.abc import Sequence


def _format_human(report) -> str:  # noqa: ANN001
    lines: list[str] = []
    lines.append(f"hapax-velocity-meter — {report.repo}")
    lines.append(f"window: {report.window_days} day(s)  measured_at: {report.measured_at}")
    lines.append("")
    lines.append(f"  commits          {report.commits:>8}   ({report.commits_per_day:.2f} / day)")
    if report.prs is not None:
        lines.append(f"  PRs              {report.prs:>8}   ({report.prs_per_day:.2f} / day)")
    else:
        lines.append("  PRs                  n/a   (gh CLI unavailable)")
    lines.append(f"  distinct authors {report.distinct_authors:>8}")
    lines.append(f"  author rotation  {report.author_rotation:>8.3f}")
    lines.append(
        f"  LOC churn       {report.additions + report.deletions:>9}   "
        f"(+{report.additions} / -{report.deletions}; "
        f"{report.loc_churn_per_day:.0f} / day)"
    )
    lines.append("")
    lines.append("Methodology: https://hapax.weblog.lol/velocity-report-2026-04-25")
    lines.append("Cite: hapax-velocity-meter cite")
    return "\n".join(lines)


def _cmd_run(args: argparse.Namespace) -> int:
    report = measure_repo(repo=args.repo, window_days=args.days)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(_format_human(report))
    return 0


def _cmd_cite(_args: argparse.Namespace) -> int:
    print(bibtex_self_citation())
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hapax-velocity-meter",
        description="Measure development velocity from any git history.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Measure velocity over a git history window.")
    p_run.add_argument("--repo", default=".", help="Path to git repository (default: .)")
    p_run.add_argument("--days", type=int, default=7, help="Window in days (default: 7)")
    p_run.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable.")
    p_run.set_defaults(func=_cmd_run)

    p_cite = sub.add_parser("cite", help="Emit BibTeX self-citation.")
    p_cite.set_defaults(func=_cmd_cite)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
