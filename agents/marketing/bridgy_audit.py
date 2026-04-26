"""Bridgy POSSE coverage audit — Phase 1.

Per cc-task ``leverage-mktg-bridgy-coverage-audit``. PR #1482
(``BridgyPublisher``) is already merged and emitting webmention POSSE
to brid.gy/publish/webmention; this module is the audit-only follow-
up that surfaces fan-out coverage across the canonical Bridgy
surfaces and routes uncovered platforms to the refusal-brief annex.

Phase 1 ships:

  - Canonical platform list (:data:`BRIDGY_PLATFORMS`)
  - :class:`PlatformOutcome` + :class:`BridgyCoverageReport` typed
    aggregate shapes
  - :func:`coverage_pct` per-platform success ratio
  - :func:`render_coverage_report` markdown renderer
  - :func:`write_coverage_report` writer to
    ``~/hapax-state/marketing/bridgy-coverage-{iso-date}.md``
  - Counter ``hapax_leverage_bridgy_coverage_pct{platform}``

Phase 2 will wire the daemon main() that scans the BridgyPublisher
Counter values (or queries brid.gy/{platform}/{user-id}/status for
live status), composes a 30-day window report, and appends per-
unreached-surface entries to the refusal-brief annex via the existing
:mod:`agents.publication_bus.refusal_brief_publisher` path.

Reading from prometheus_client.REGISTRY in Phase 1 would couple
the audit to the running daemon's process; instead, Phase 1 keeps
``audit_30d()`` as a pure function over already-collected
:class:`PlatformOutcome` instances. Phase 2 will provide the
collector that reads from REGISTRY or a JSONL audit log.

Per refusal-as-data: Bridgy doesn't natively reach all surfaces
(e.g., specific hashtag-watch platforms). Those gaps become refusal
entries — we are NOT going to ship native ATProto / Mastodon fan-out
clients beyond what Bridgy already covers (POSSE convention is the
constitutional fit).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from prometheus_client import Gauge

log = logging.getLogger(__name__)

BRIDGY_PLATFORMS: Final[tuple[str, ...]] = (
    "mastodon",
    "bluesky",
    "github",
    "webmention-incoming",
)
"""Canonical Bridgy POSSE fan-out surfaces.

- ``mastodon`` — operator's Mastodon instance via brid.gy/publish
- ``bluesky`` — operator's Bluesky PDS via brid.gy/publish
- ``github`` — GitHub fan-out for issue/PR mentions
- ``webmention-incoming`` — incoming webmention archive on omg.lol weblog

Each platform gets one row in the coverage report. Zero-attempt
platforms surface as refusal candidates."""

DEFAULT_MARKETING_DIR: Final[Path] = Path.home() / "hapax-state" / "marketing"
"""Append-only marketing audit reports landing zone."""


coverage_gauge = Gauge(
    "hapax_leverage_bridgy_coverage_pct",
    "Per-platform Bridgy POSSE fan-out coverage ratio (0.0..1.0)",
    ["platform"],
)


@dataclass(frozen=True)
class PlatformOutcome:
    """Per-platform Bridgy publish-attempt aggregate over a window.

    Mirrors the V5 Publisher ABC's three-state outcome shape so the
    audit reads cleanly off the Counter labels (``ok``, ``refused``,
    ``error``). ``platform`` is the Bridgy fan-out surface name from
    :data:`BRIDGY_PLATFORMS`.
    """

    platform: str
    ok: int
    refused: int
    error: int


@dataclass(frozen=True)
class BridgyCoverageReport:
    """One audit window's coverage snapshot.

    Carries per-platform outcomes plus generation metadata for the
    rendered report header.
    """

    generated_at: datetime
    window_days: int
    outcomes: list[PlatformOutcome]


def coverage_pct(outcome: PlatformOutcome) -> float:
    """Return the success ratio for one platform's outcome.

    ``ok / (ok + refused + error)`` when there were any attempts;
    ``0.0`` when there were none. Zero-attempt platforms are
    distinguished from zero-success-ratio ones by the
    :func:`render_coverage_report` renderer, which surfaces them as
    refusal candidates.
    """
    total = outcome.ok + outcome.refused + outcome.error
    if total == 0:
        return 0.0
    return outcome.ok / total


def render_coverage_report(report: BridgyCoverageReport) -> str:
    """Render :class:`BridgyCoverageReport` to markdown.

    Surfaces:
    - generated-at ISO date
    - window days
    - per-platform success-pct row
    - explicit "no attempts" / refusal-candidate flag for
      zero-attempt platforms
    """
    lines: list[str] = []
    lines.append(f"# Bridgy POSSE coverage report — {report.generated_at.date().isoformat()}")
    lines.append("")
    lines.append(f"Window: last **{report.window_days}** days")
    lines.append("")
    lines.append("| Platform | OK | Refused | Error | Coverage |")
    lines.append("|----------|---:|--------:|------:|---------:|")
    for outcome in report.outcomes:
        total = outcome.ok + outcome.refused + outcome.error
        if total == 0:
            coverage = "no attempts (refusal candidate)"
        else:
            pct = coverage_pct(outcome) * 100.0
            coverage = f"{pct:.0f}%"
        lines.append(
            f"| {outcome.platform} | {outcome.ok} | {outcome.refused} | {outcome.error} | {coverage} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "Per refusal-as-data convention, zero-attempt platforms surface as "
        "refusal candidates: Bridgy POSSE does not reach them and the "
        "constitutional envelope precludes shipping native fan-out clients."
    )
    return "\n".join(lines) + "\n"


def write_coverage_report(
    report: BridgyCoverageReport,
    *,
    marketing_dir: Path = DEFAULT_MARKETING_DIR,
) -> Path:
    """Write the rendered coverage report to an ISO-dated file.

    File naming: ``bridgy-coverage-{YYYY-MM-DD}.md``. Creates the
    parent directory if missing. Returns the path written.
    """
    marketing_dir.mkdir(parents=True, exist_ok=True)
    iso_date = report.generated_at.date().isoformat()
    target = marketing_dir / f"bridgy-coverage-{iso_date}.md"
    target.write_text(render_coverage_report(report), encoding="utf-8")
    for outcome in report.outcomes:
        coverage_gauge.labels(platform=outcome.platform).set(coverage_pct(outcome))
    return target


__all__ = [
    "BRIDGY_PLATFORMS",
    "BridgyCoverageReport",
    "DEFAULT_MARKETING_DIR",
    "PlatformOutcome",
    "coverage_gauge",
    "coverage_pct",
    "render_coverage_report",
    "write_coverage_report",
]
