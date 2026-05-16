"""Multi-source angle resolution for segment prep.

Given a topic, queries multiple knowledge sources (Qdrant collections,
vault, web) to find competing positions. Selects the angle with maximum
productive disagreement and returns an AngleHypothesis that feeds into
beat scaffolding.

No expert rules — the angle emerges from source disagreement, not from
hardcoded narrative templates.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from shared.source_packet import SourcePacket

log = logging.getLogger(__name__)

QDRANT_COLLECTIONS = ("documents", "operator-episodes", "stream-reactions", "studio-moments")
VAULT_ROOTS = ("30-areas", "20-projects", "50-resources")
MIN_SOURCES_FOR_ANGLE = 3


@dataclass(frozen=True)
class AngleHypothesis:
    topic: str
    thesis_position: str
    supporting_sources: tuple[SourcePacket, ...]
    challenging_sources: tuple[SourcePacket, ...]
    opening_pressure: str
    angle_hash: str = ""

    @property
    def has_tension(self) -> bool:
        return len(self.challenging_sources) > 0

    @property
    def source_count(self) -> int:
        return len(self.supporting_sources) + len(self.challenging_sources)


def resolve_angle(
    topic: str,
    *,
    max_sources_per_collection: int = 5,
) -> AngleHypothesis | None:
    """Resolve competing sources for a topic and identify the productive fault line."""
    packets = _gather_sources(topic, max_per_collection=max_sources_per_collection)
    if len(packets) < MIN_SOURCES_FOR_ANGLE:
        packets = _web_supplement(topic, packets)
    if not packets:
        log.warning("angle_resolver: no sources found for topic: %s", topic[:80])
        return None

    return _select_angle(topic, packets)


def _gather_sources(topic: str, *, max_per_collection: int = 5) -> list[SourcePacket]:
    """Query Qdrant collections + vault for source material."""
    from agents.programme_authors.asset_resolver import _qdrant_search, _vault_notes_for_topic

    packets: list[SourcePacket] = []
    seen_hashes: set[str] = set()

    for collection in QDRANT_COLLECTIONS:
        try:
            hits = _qdrant_search(collection, topic, limit=max_per_collection)
            for text, source, _score in hits:
                h = hashlib.sha256(text.encode()).hexdigest()[:16]
                if h in seen_hashes:
                    continue
                seen_hashes.add(h)
                packets.append(
                    SourcePacket(
                        source_ref=f"qdrant:{collection}:{source[:80]}",
                        content_hash=h,
                        snippet=text[:500],
                        freshness="fresh",
                        source_consequence=(
                            f"without this source, the {collection} perspective is absent"
                        ),
                    )
                )
        except Exception:
            log.debug("angle_resolver: %s query failed", collection, exc_info=True)

    try:
        vault_notes = _vault_notes_for_topic(topic, roots=VAULT_ROOTS, limit=5)
        for note_path in vault_notes:
            h = hashlib.sha256(note_path.encode()).hexdigest()[:16]
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            packets.append(
                SourcePacket(
                    source_ref=f"vault:{note_path}",
                    content_hash=h,
                    snippet=f"Vault note: {note_path}",
                    freshness="fresh",
                    source_consequence=(
                        "without this vault note, operator's documented perspective is absent"
                    ),
                )
            )
    except Exception:
        log.debug("angle_resolver: vault query failed", exc_info=True)

    log.info("angle_resolver: gathered %d sources for topic: %s", len(packets), topic[:60])
    return packets


def _web_supplement(topic: str, existing: list[SourcePacket]) -> list[SourcePacket]:
    """Supplement sparse local sources with web search."""
    try:
        from agents.deliberative_council.tools import web_verify

        result = web_verify(None, topic)
        if result and isinstance(result, str) and len(result) > 50:
            h = hashlib.sha256(result.encode()).hexdigest()[:16]
            existing.append(
                SourcePacket(
                    source_ref="web:perplexity-sonar",
                    content_hash=h,
                    snippet=result[:500],
                    freshness="fresh",
                    rights_status="web",
                    source_consequence="without web context, only local knowledge is available",
                )
            )
            log.info("angle_resolver: web supplement added 1 source")
    except Exception:
        log.debug("angle_resolver: web supplement failed", exc_info=True)
    return existing


def _select_angle(topic: str, packets: list[SourcePacket]) -> AngleHypothesis:
    """Use the LLM to identify competing positions and select the angle."""
    from shared.config import MODELS

    try:
        import litellm

        source_block = "\n\n".join(
            f"SOURCE {i + 1} [{p.source_ref}]:\n{p.snippet}" for i, p in enumerate(packets[:8])
        )
        prompt = (
            f"Topic: {topic}\n\n"
            f"Below are {len(packets[:8])} sources on this topic.\n\n"
            f"{source_block}\n\n"
            "Analyze these sources and identify:\n"
            "1. THESIS: The strongest claim these sources collectively support\n"
            "2. CHALLENGE: The strongest counter-position or tension visible in the sources\n"
            "3. OPENING PRESSURE: A one-sentence hook that frames the disagreement as a "
            "question the audience needs answered\n\n"
            "Respond in exactly this format:\n"
            "THESIS: [one sentence]\n"
            "CHALLENGE: [one sentence]\n"
            "OPENING_PRESSURE: [one sentence]\n"
            "SUPPORTING_SOURCES: [comma-separated source numbers that support the thesis]\n"
            "CHALLENGING_SOURCES: [comma-separated source numbers that challenge it]"
        )

        response = litellm.completion(
            model=MODELS.get("local-fast", "local-fast"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3,
        )
        text = response.choices[0].message.content or ""
        return _parse_angle_response(topic, text, packets)
    except Exception:
        log.warning("angle_resolver: LLM angle selection failed, using all sources", exc_info=True)
        return AngleHypothesis(
            topic=topic,
            thesis_position=topic,
            supporting_sources=tuple(packets),
            challenging_sources=(),
            opening_pressure=topic,
            angle_hash=hashlib.sha256(topic.encode()).hexdigest()[:16],
        )


def _parse_angle_response(topic: str, text: str, packets: list[SourcePacket]) -> AngleHypothesis:
    """Parse the structured LLM response into an AngleHypothesis."""
    thesis = topic
    opening = topic
    supporting_idx: list[int] = []
    challenging_idx: list[int] = []

    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("THESIS:"):
            thesis = line[7:].strip()
        elif line.startswith("OPENING_PRESSURE:"):
            opening = line[17:].strip()
        elif line.startswith("SUPPORTING_SOURCES:"):
            supporting_idx = _parse_source_numbers(line[19:])
        elif line.startswith("CHALLENGING_SOURCES:"):
            challenging_idx = _parse_source_numbers(line[20:])

    supporting = tuple(packets[i - 1] for i in supporting_idx if 0 < i <= len(packets))
    challenging = tuple(packets[i - 1] for i in challenging_idx if 0 < i <= len(packets))

    if not supporting:
        supporting = tuple(packets[:3])

    h = hashlib.sha256(f"{thesis}|{opening}".encode()).hexdigest()[:16]
    return AngleHypothesis(
        topic=topic,
        thesis_position=thesis,
        supporting_sources=supporting,
        challenging_sources=challenging,
        opening_pressure=opening,
        angle_hash=h,
    )


def _parse_source_numbers(text: str) -> list[int]:
    nums: list[int] = []
    for part in text.split(","):
        part = part.strip().lstrip("#")
        try:
            nums.append(int(part))
        except ValueError:
            pass
    return nums


def format_angle_for_composer(angle: AngleHypothesis) -> str:
    """Format an AngleHypothesis as context for the segment composer prompt."""
    lines = [
        "## Angle Analysis",
        f"**Thesis:** {angle.thesis_position}",
        f"**Opening pressure:** {angle.opening_pressure}",
        "",
        f"### Supporting sources ({len(angle.supporting_sources)}):",
    ]
    for i, s in enumerate(angle.supporting_sources):
        lines.append(f"  {i + 1}. [{s.source_ref}]: {s.snippet[:200]}")

    if angle.challenging_sources:
        lines.append(f"\n### Challenging sources ({len(angle.challenging_sources)}):")
        for i, s in enumerate(angle.challenging_sources):
            lines.append(f"  {i + 1}. [{s.source_ref}]: {s.snippet[:200]}")

    return "\n".join(lines)
