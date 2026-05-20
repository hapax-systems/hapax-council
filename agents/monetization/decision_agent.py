"""Monetization decision agent — recommendation-only.

Reads value-braid scores, determines revenue-optimal routing, and deposits
PreprintArtifact recommendations into the publish orchestrator inbox. Makes
no direct publish() calls or payment platform mutations.

Authority: CASE-VISIBILITY-ENGINE-001 / ISAP-MONETIZATION-DECISION-AGENT
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from shared.monetization_publication_connector import (
    REVENUE_BEARING_SURFACES,
    MonetizationDecision,
    check_surface_monetization_readiness,
)
from shared.monetization_readiness_ledger import (
    MonetizationReadinessLedger,
    evaluate_default_monetization_readiness,
)
from shared.preprint_artifact import ApprovalState, PreprintArtifact

log = logging.getLogger(__name__)

INBOX_DIR = Path.home() / "hapax-state" / "publish" / "inbox"
VALUE_BRAID_DIR = Path.home() / "hapax-state" / "value-braid"
MIN_MONETARY_SCORE = 0.4


class ValueBraidEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str
    title: str = ""
    abstract: str = ""
    body_md: str = ""
    monetary_value: float = 0.0
    research_value: float = 0.0
    tree_unblock_value: float = 0.0
    source_path: str | None = None


class RoutingRecommendation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: str
    surfaces: tuple[str, ...]
    monetary_score: float
    reason: str
    deposited_at: datetime | None = None


def load_value_braid_entries(braid_dir: Path = VALUE_BRAID_DIR) -> list[ValueBraidEntry]:
    entries: list[ValueBraidEntry] = []
    if not braid_dir.is_dir():
        log.warning("value-braid directory does not exist: %s", braid_dir)
        return entries
    for p in sorted(braid_dir.glob("*.json")):
        try:
            raw = json.loads(p.read_text())
            entries.append(ValueBraidEntry.model_validate(raw))
        except Exception:
            log.warning("skipping malformed value-braid entry: %s", p.name, exc_info=True)
    return entries


def select_revenue_surfaces(
    entry: ValueBraidEntry,
    ledger: MonetizationReadinessLedger | None = None,
) -> list[str]:
    """Select revenue-bearing surfaces that are ready for this entry."""
    surfaces: list[str] = []
    for surface in sorted(REVENUE_BEARING_SURFACES):
        result = check_surface_monetization_readiness(surface, ledger=ledger)
        if result.decision == MonetizationDecision.PROCEED:
            surfaces.append(surface)
    return surfaces


def build_recommendation(
    entry: ValueBraidEntry,
    surfaces: list[str],
) -> PreprintArtifact:
    return PreprintArtifact(
        slug=f"monetization-rec-{entry.slug}",
        title=entry.title or entry.slug,
        abstract=entry.abstract,
        body_md=entry.body_md,
        surfaces_targeted=surfaces,
        approval=ApprovalState.DRAFT,
        source_path=entry.source_path,
    )


def deposit_to_inbox(
    artifact: PreprintArtifact,
    inbox_dir: Path = INBOX_DIR,
) -> Path:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{artifact.slug}.json"
    dest = inbox_dir / filename
    dest.write_text(artifact.model_dump_json(indent=2))
    log.info("deposited recommendation: %s → %s", artifact.slug, dest)
    return dest


def run(
    *,
    braid_dir: Path = VALUE_BRAID_DIR,
    inbox_dir: Path = INBOX_DIR,
    min_score: float = MIN_MONETARY_SCORE,
    dry_run: bool = False,
) -> list[RoutingRecommendation]:
    entries = load_value_braid_entries(braid_dir)
    if not entries:
        log.info("no value-braid entries found")
        return []

    ledger: MonetizationReadinessLedger | None = None
    try:
        ledger = evaluate_default_monetization_readiness()
    except Exception:
        log.warning("monetization readiness evaluation failed; proceeding without ledger")

    recommendations: list[RoutingRecommendation] = []
    for entry in entries:
        if entry.monetary_value < min_score:
            continue

        surfaces = select_revenue_surfaces(entry, ledger=ledger)
        if not surfaces:
            log.debug("no ready surfaces for %s", entry.slug)
            continue

        artifact = build_recommendation(entry, surfaces)
        deposited_at = None
        if not dry_run:
            deposit_to_inbox(artifact, inbox_dir)
            deposited_at = datetime.now(UTC)

        recommendations.append(
            RoutingRecommendation(
                slug=entry.slug,
                surfaces=tuple(surfaces),
                monetary_score=entry.monetary_value,
                reason="value-braid monetary score above threshold",
                deposited_at=deposited_at,
            )
        )

    log.info(
        "monetization decision agent: %d entries scanned, %d recommendations%s",
        len(entries),
        len(recommendations),
        " (dry-run)" if dry_run else "",
    )
    return recommendations


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Monetization decision agent")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    results = run(dry_run=args.dry_run)
    for r in results:
        print(f"  {r.slug} → {', '.join(r.surfaces)} (score={r.monetary_score:.2f})")
