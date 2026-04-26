"""Refusal-annex Bridgy fan-out daemon — Phase 2 dry-run scaffold.

Walks ``~/hapax-state/publications/refusal-annex-*.md`` and reports
what would be fanned out via Bridgy POSSE (Mastodon + Bluesky) when
``--commit`` is implemented. Phase 1 of the refusal-annex series
(renderer + cross-linker) shipped earlier; this is the Phase 2
scaffold for the Bridgy fan-out half.

Mirrors the #1673 refusal-brief daemon + #1678 self-citation graph
DOI scanner patterns: --dry-run by default, --commit explicitly opt-in,
minting/posting deferred until cred-arrival + per-call review.

Cred state pairing: bluesky/operator-app-password +
bluesky/operator-did + omg-lol/api-key all arrived this cycle.
Bridgy webmention POSSE goes through the operator's omg.lol weblog →
brid.gy/publish/webmention → fan-out per the operator's pre-configured
brid.gy account links.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


DEFAULT_PUBLICATIONS_DIR = Path.home() / "hapax-state/publications"
"""Where the refusal-annex renderer writes ``refusal-annex-{slug}.md``."""

OMG_LOL_WEBLOG_BASE = "https://hapax.weblog.lol/refusal-annex"
"""Operator's omg.lol weblog URL stem; the renderer uploads each annex
markdown into this surface as one entry per slug."""


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
                weblog_url=f"{OMG_LOL_WEBLOG_BASE}/{slug}",
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
        lines.append("- bridgy_source:  hapax.weblog.lol (configured at brid.gy)")
        lines.append("- bridgy_targets: mastodon + bluesky (per operator's pre-linked accounts)")
        lines.append("- next_action:    (dry-run; no Bridgy webmention POSTed)")
        lines.append("")

    lines.append("Re-run with --commit to issue Bridgy webmention POSSE per target.")
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
        help="EXPLICIT opt-in to issue Bridgy webmention POSSE (Phase 2.5 — not yet implemented)",
    )
    args = parser.parse_args(argv)

    targets = scan_refusal_annexes(args.publications_dir)

    if args.commit:
        print(
            f"# --commit recognised; Bridgy fan-out loop is the Phase 2.5 sub-PR. "
            f"({len(targets)} annexes would fan out via brid.gy POSSE)",
            file=sys.stderr,
        )
        return 0

    sys.stdout.write(render_dry_run_report(targets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AnnexFanoutTarget",
    "DEFAULT_PUBLICATIONS_DIR",
    "OMG_LOL_WEBLOG_BASE",
    "main",
    "render_dry_run_report",
    "scan_refusal_annexes",
]
