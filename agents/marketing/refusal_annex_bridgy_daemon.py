"""Refusal-annex Bridgy fan-out daemon - dry-run inventory.

Walks ``~/hapax-state/publications/refusal-annex-*.md`` and reports
what would be eligible for Bridgy POSSE once refusal-annex webmention
fanout has a committed source-URL witness path. The daemon is not a
publisher; ``--commit`` fails closed with the blocker instead of
issuing a webmention POST.

Generic Bridgy webmention publishing exists for normal weblog artifacts.
Refusal-annex fanout remains blocked because the orchestrator dispatches
surfaces in parallel, while Bridgy must only POST after the omg.lol
weblog source URL exists and is witnessable.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from agents.bridgy_adapter import WEBLOG_TARGET_URL
from agents.marketing.refusal_annex_renderer import BRIDGY_FANOUT_BLOCKER

log = logging.getLogger(__name__)


DEFAULT_PUBLICATIONS_DIR = Path.home() / "hapax-state/publications"
"""Where the refusal-annex renderer writes ``refusal-annex-{slug}.md``."""

REFUSAL_ANNEX_WEBLOG_PREFIX = f"{WEBLOG_TARGET_URL}/refusal-annex-"
"""Operator's omg.lol weblog URL stem for rendered refusal-annex artifacts."""

COMMIT_BLOCKER = BRIDGY_FANOUT_BLOCKER
"""Why ``--commit`` refuses to POST a webmention."""


@dataclass(frozen=True)
class AnnexFanoutTarget:
    """One annex's planned Bridgy fan-out invocation."""

    slug: str
    source_path: Path
    weblog_url: str
    """Operator's omg.lol weblog URL — Bridgy reads this as the source
    for the webmention POSSE."""


def scan_refusal_annexes(
    publications_dir: Path = DEFAULT_PUBLICATIONS_DIR,
) -> list[AnnexFanoutTarget]:
    """Walk the publications dir for refusal-annex markdowns.

    Returns one ``AnnexFanoutTarget`` per ``refusal-annex-*.md`` file,
    pointing the operator's omg.lol weblog URL as the Bridgy source.
    Missing dir returns []. The renderer itself ships the local file;
    this scanner only reports on what's been rendered.
    """
    if not publications_dir.is_dir():
        return []

    targets: list[AnnexFanoutTarget] = []
    for path in sorted(publications_dir.glob("refusal-annex-*.md")):
        slug = path.stem.removeprefix("refusal-annex-")
        if not slug:
            continue
        targets.append(
            AnnexFanoutTarget(
                slug=slug,
                source_path=path,
                weblog_url=f"{REFUSAL_ANNEX_WEBLOG_PREFIX}{slug}",
            )
        )
    return targets


def render_dry_run_report(targets: list[AnnexFanoutTarget]) -> str:
    """Format the scan as an operator-readable dry-run report."""
    lines: list[str] = []
    lines.append("# Refusal-annex Bridgy fan-out dry-run")
    lines.append("")
    lines.append(f"Scan found:     {len(targets):>3} refusal-annex markdowns")
    lines.append("")

    if not targets:
        lines.append("(no refusal-annex-*.md files found in publications/ dir)")
        return "\n".join(lines)

    lines.append("## Per-annex fan-out plan")
    lines.append("")
    for target in targets:
        lines.append(f"### refusal-annex-{target.slug}")
        lines.append(f"- source_path: {target.source_path}")
        lines.append(f"- weblog_url:  {target.weblog_url}")
        lines.append(f"- bridgy_target:  {WEBLOG_TARGET_URL}")
        lines.append("- bridgy_targets: mastodon + bluesky (per operator's pre-linked accounts)")
        lines.append("- status:         dry-run only; no Bridgy webmention POSTed")
        lines.append(f"- blocker:        {COMMIT_BLOCKER}")
        lines.append("")

    lines.append("Live refusal-annex Bridgy fanout is blocked until source URL witness exists.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publications-dir",
        type=Path,
        default=DEFAULT_PUBLICATIONS_DIR,
        help="Refusal-annex publications dir (default ~/hapax-state/publications)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Fail closed with the current blocker; live refusal-annex Bridgy is not implemented",
    )
    args = parser.parse_args(argv)

    targets = scan_refusal_annexes(args.publications_dir)

    if args.commit:
        print(
            f"# --commit refused; {COMMIT_BLOCKER}. "
            f"({len(targets)} annexes inventoried; no webmention POST issued)",
            file=sys.stderr,
        )
        return 2

    sys.stdout.write(render_dry_run_report(targets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AnnexFanoutTarget",
    "COMMIT_BLOCKER",
    "DEFAULT_PUBLICATIONS_DIR",
    "REFUSAL_ANNEX_WEBLOG_PREFIX",
    "main",
    "render_dry_run_report",
    "scan_refusal_annexes",
]
