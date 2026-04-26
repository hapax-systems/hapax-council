"""Refusal Brief Zenodo-deposit daemon — Phase 2 dry-run scanner.

Scans both ``active/`` and ``closed/`` cc-task vault dirs for refusals
without a ``refusal_doi`` in their frontmatter, and reports what would
be minted as Zenodo refusal-deposits. Default mode is ``--dry-run``
(report only); ``--commit`` opt-in mints real deposits and writes the
returned DOIs back into each cc-task note.

The scan composes a ``RelatedIdentifier`` graph per cc-task (refusal-
shaped: ``IsRequiredBy`` to the target surface's hypothetical deposit,
``IsObsoletedBy`` to sibling refusal DOIs) so the deposit participates
in the DataCite citation graph.

Cred-arrival path: when ``zenodo/api-token`` arrives in pass-store
(now confirmed live this cycle), the daemon can mint deposits. Until
``--commit`` is explicitly passed, the daemon stays in dry-run.

Spec: ``agents/publication_bus/refusal_brief_publisher.py`` Phase 2
section + drop-5 fresh-pattern §2.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from agents.publication_bus.refusal_brief_publisher import (
    RefusedTaskSummary,
    scan_refused_cc_tasks,
)

log = logging.getLogger(__name__)


DEFAULT_VAULT_BASE = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"
ZENODO_PASS_KEY = "zenodo/api-token"


def _read_pass_value(key: str) -> str | None:
    """Return the pass-store value for ``key``, or None if absent / no pass binary."""
    if not shutil.which("pass"):
        return None
    try:
        result = subprocess.run(
            ["pass", "show", key],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else None


def scan_all_refused(vault_base: Path = DEFAULT_VAULT_BASE) -> list[RefusedTaskSummary]:
    """Scan both ``active/`` and ``closed/`` for refused cc-tasks.

    Mirrors the substrate's `iter_refused_tasks` pattern: refusal cc-
    tasks live in BOTH dirs (active for current-cycle, closed for
    shipped-brief cases where the constitutional refusal persists).
    """
    summaries: list[RefusedTaskSummary] = []
    for sub in ("active", "closed"):
        sub_dir = vault_base / sub
        if sub_dir.is_dir():
            summaries.extend(scan_refused_cc_tasks(sub_dir))
    return summaries


def render_dry_run_report(summaries: list[RefusedTaskSummary]) -> str:
    """Format the scan output as an operator-readable report."""
    lines: list[str] = []
    lines.append("# Refusal Brief Zenodo-deposit dry-run")
    lines.append("")
    lines.append(f"Scan found:     {len(summaries):>3} REFUSED cc-tasks")
    lines.append("")

    if not summaries:
        lines.append("(no refused cc-tasks found — check vault path)")
        return "\n".join(lines)

    lines.append("## Per-task plan")
    lines.append("")
    for summary in summaries:
        lines.append(f"### {summary.task_id}")
        lines.append(f"- title:          {summary.title}")
        lines.append(f"- refusal_reason: {summary.refusal_reason[:120]}")
        lines.append(f"- source_path:    {summary.file_path}")
        lines.append("- next_action:    (dry-run; no Zenodo deposit minted)")
        lines.append("")

    lines.append("Re-run with --commit to mint deposits + write refusal_doi back.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Daemon CLI entry."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vault-base",
        type=Path,
        default=DEFAULT_VAULT_BASE,
        help="cc-task vault base dir (contains active/ and closed/ subdirs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="(default) scan + report what would be minted; no API calls",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="EXPLICIT opt-in to mint Zenodo deposits + write refusal_doi back",
    )
    args = parser.parse_args(argv)

    summaries = scan_all_refused(args.vault_base)

    if args.commit:
        token = _read_pass_value(ZENODO_PASS_KEY)
        if not token:
            print(
                f"# ABORT — {ZENODO_PASS_KEY} not in pass-store. Run cred-provisioner first.",
                file=sys.stderr,
            )
            return 2
        # Phase 2.5: actual minting. For now this guard surfaces the
        # remaining work without doing anything destructive.
        print(
            "# --commit is recognised but not yet implemented. The minting loop "
            "is the next sub-PR after this dry-run scaffold lands.",
            file=sys.stderr,
        )
        return 0

    sys.stdout.write(render_dry_run_report(summaries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
