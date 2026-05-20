"""Replay card marketplace publisher — publish verified ReplayDemoCards.

Consumes ReplayDemoCard objects and deposits them as marketplace entries
to institutional, grant, residency, and catalog surfaces. Fails closed
when event refs, provenance, rights, privacy, or n=1 explanation are
missing.

Does NOT perform custom operator narration, bespoke presentation, or
audience-specific private access.

Authority: CASE-LIVESTREAM-RESEARCH-VEHICLE-SUITCASE-PAR
CC-task: replay-card-marketplace-publisher
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import AllowlistGate
from shared.replay_demo_card import ReplayDemoCard

log = logging.getLogger(__name__)

OUTPUT_DIR = Path.home() / "hapax-state" / "publish" / "replay-cards"

REQUIRED_CARD_FIELDS = (
    "event_id",
    "provenance_token",
    "rights_class",
    "privacy_class",
    "n1_explanation",
)

ALLOWED_SURFACES = frozenset(
    {
        "catalog",
        "demo",
        "grant",
        "residency",
        "marketplace",
    }
)


def validate_card(card: ReplayDemoCard) -> list[str]:
    """Return a list of missing-evidence reasons. Empty = card is publishable."""
    blockers: list[str] = []
    if not card.event_id:
        blockers.append("event_id:missing")
    if not card.provenance_token and not card.provenance_evidence_refs:
        blockers.append("provenance:missing")
    if not card.rights_class:
        blockers.append("rights_class:missing")
    if not card.privacy_class:
        blockers.append("privacy_class:missing")
    if not card.n1_explanation:
        blockers.append("n1_explanation:missing")
    return blockers


def card_to_manifest(card: ReplayDemoCard, surface: str) -> dict:
    """Render a ReplayDemoCard to a marketplace manifest entry."""
    return {
        "schema_version": 1,
        "surface": surface,
        "event_id": card.event_id,
        "replay_title": card.replay_title,
        "public_url": card.public_url,
        "chapter_label": card.chapter_label,
        "chapter_timecode": card.chapter_timecode,
        "frame_uri": card.frame_uri,
        "frame_kind": card.frame_kind,
        "provenance_token": card.provenance_token,
        "provenance_evidence_refs": list(card.provenance_evidence_refs),
        "rights_class": card.rights_class,
        "privacy_class": card.privacy_class,
        "n1_explanation": card.n1_explanation,
        "suggested_audience": card.suggested_audience,
        "programme_id": card.programme_id,
        "broadcast_id": card.broadcast_id,
        "published_at": datetime.now(UTC).isoformat(),
    }


class ReplayCardPublisher(Publisher):
    """V5 publisher for replay demo card marketplace entries."""

    surface_name: ClassVar[str] = "replay-card-marketplace"
    allowlist: ClassVar[AllowlistGate] = AllowlistGate(
        surface_name="replay-card-marketplace",
        permitted=ALLOWED_SURFACES,
    )
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, output_dir: Path = OUTPUT_DIR) -> None:
        self._output_dir = output_dir

    def publish_card(
        self,
        card: ReplayDemoCard,
        surface: str,
    ) -> PublisherResult:
        """Validate and publish a ReplayDemoCard to a surface.

        Fail-closed: refuses if any required evidence field is missing.
        """
        blockers = validate_card(card)
        if blockers:
            log.warning(
                "replay_card_publisher: refused %s — %s",
                card.event_id,
                ", ".join(blockers),
            )
            return PublisherResult(refused=True, detail=f"missing evidence: {', '.join(blockers)}")

        manifest = card_to_manifest(card, surface)
        payload = PublisherPayload(
            target=surface,
            text=json.dumps(manifest, indent=2),
        )
        return self.publish(payload)

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        manifest = json.loads(payload.text)
        event_id = manifest.get("event_id", "unknown")
        surface = manifest.get("surface", "unknown")
        filename = f"{surface}-{event_id}.json"
        dest = self._output_dir / filename
        dest.write_text(payload.text)
        log.info("replay_card_publisher: published %s → %s", event_id, dest)
        return PublisherResult(ok=True, detail=str(dest))
