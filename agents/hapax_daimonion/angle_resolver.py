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
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from agents.hapax_daimonion.turn_budget import PREP_LLM_TIMEOUT_S
from shared.source_packet import ResolvedSourceSet, SourcePacket, build_resolved_source_set

log = logging.getLogger(__name__)

# Grounding-source collections. "stream-reactions" is EXCLUDED: it is Hapax's OWN
# prior live-stream generations, so recruiting it as a "source" is both circular
# (grounding a claim on your own output) and STYLE-CONTAMINATING — the composer
# mimics the slop it is shown as exemplar "sources". Verified 2026-06-14: the live
# 35B regressed into the stream-reactions phrasing ("Let's delve into the intricate
# web..."), yet the SAME model scores coherence 4.25 (vs 2.0 live) when composing
# against clean sources (scripts/compose-model-bakeoff.py). Self-generated content
# may inform angle elsewhere, but never serves as a grounding source here.
QDRANT_COLLECTIONS = ("documents", "operator-episodes", "studio-moments")
_SELF_GENERATED_COLLECTIONS = ("stream-reactions",)
VAULT_ROOTS = ("30-areas", "20-projects", "50-resources")
MIN_SOURCES_FOR_ANGLE = 3

# Plan-time slate recruitment bounds. recruit_source_sets runs BEFORE planning
# over a candidate slate, so it must fit the prep budget — bound the slate width
# and per-candidate retrieval so a slate-wide recruit cannot blow PREP_BUDGET_S.
RECRUIT_MAX_CANDIDATES = 6
RECRUIT_PER_CANDIDATE_LIMIT = 5
RECRUIT_BUDGET_S = 600.0
# Below this many local packets a candidate is "sparse" and we recruit the open
# world (Tavily, directly — never the dead LiteLLM web-* routes).
_MIN_LOCAL_PACKETS_BEFORE_WEB = 1


def recruit_source_set(
    topic: str,
    *,
    max_sources_per_collection: int = 5,
) -> ResolvedSourceSet | None:
    """Recruit a content-hash-bound ResolvedSourceSet for a topic — the citable surface.

    This is the LLM-free recruiter: it gathers real packets (Qdrant + vault) and
    binds them into a closed, deduplicated, set-hashed ``ResolvedSourceSet`` whose
    handles (``src:0..N``) are the ONLY things a composer may cite. Returns None
    when no source resolves — the caller must REFUSE, never fabricate to fill.

    Unlike ``resolve_angle`` (which adds an advisory thesis/tension via an LLM call
    that may fail), this surface is load-bearing and depends only on retrieval, so a
    degraded LLM cannot collapse the citation set.
    """
    packets = _gather_sources(topic, max_per_collection=max_sources_per_collection)
    if not packets:
        log.warning("recruit_source_set: no sources resolved for topic: %s", topic[:80])
        return None
    return build_resolved_source_set(topic, packets)


def rank_source_sets_by_density(
    sets: Sequence[ResolvedSourceSet],
) -> list[ResolvedSourceSet]:
    """Order resolved sets by how dense their resolved material is (most first).

    Density = count of resolved packets. Topics emerge where the corpus is
    thickest, so the planner sees the best-grounded candidates first.
    """
    return sorted(sets, key=lambda source_set: len(source_set.packets), reverse=True)


def _tavily_packets(topic: str, *, max_results: int = 3) -> list[SourcePacket]:
    """Recruit open-world sources via Tavily DIRECTLY (lane ``narrative_grounding``).

    Calls ``shared.tavily_client`` rather than the dead LiteLLM ``web-*`` routes
    (which silently fall back to non-grounded Claude). Fails soft — a Tavily
    outage degrades to local-only recruitment, never an exception. (main's
    ``_web_supplement`` was excised as a no-op because the only web route was the
    unawaited async web-verify; this is the grounded provider it flagged missing.)
    """
    try:
        from shared.tavily_client import TavilyClient, TavilySearchRequest

        client = TavilyClient()
        response = client.search(
            TavilySearchRequest(query=topic, max_results=max_results, lane="narrative_grounding")
        )
    except Exception:
        log.debug("recruit: tavily search failed for topic=%s", topic[:60], exc_info=True)
        return []

    packets: list[SourcePacket] = []
    seen_hashes: set[str] = set()
    for result in response.results:
        text = (result.content or "").strip()
        if not text:
            continue
        content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)
        url = (result.url or "").strip()
        packets.append(
            SourcePacket(
                source_ref=(f"web:tavily:{url}" if url else f"web:tavily:{topic[:40]}")[:300],
                content_hash=content_hash,
                snippet=text[:500],
                freshness="fresh",
                rights_status="web",
                source_consequence="without this web source, only the local corpus is available",
            )
        )
    return packets


def recruit_source_sets(
    seed_topics: Sequence[str],
    *,
    max_candidates: int = RECRUIT_MAX_CANDIDATES,
    per_candidate_limit: int = RECRUIT_PER_CANDIDATE_LIMIT,
    budget_s: float = RECRUIT_BUDGET_S,
    use_web: bool = True,
    now: Callable[[], float] = time.monotonic,
) -> list[ResolvedSourceSet]:
    """Recruit a density-ranked slate of ``ResolvedSourceSet``s BEFORE planning.

    The plan-time recruiter: it resolves real source material across a candidate
    slate so Hapax authors FROM resolved sources rather than inventing handles
    blind. Reuses ``_gather_sources`` (Qdrant + vault) and ``build_resolved_source_set``
    (the same primitives ``recruit_source_set`` uses), supplementing the open world
    via Tavily when a candidate is sparse. Bounded by ``max_candidates`` and
    ``budget_s`` so a slate-wide recruit cannot blow the prep budget; topics with
    zero resolved material are dropped (never a naked topic to decorate). Returned
    densest-first.
    """
    topics: list[str] = []
    seen_topics: set[str] = set()
    for raw_topic in seed_topics:
        topic = (raw_topic or "").strip()
        if not topic or topic in seen_topics:
            continue
        seen_topics.add(topic)
        topics.append(topic)
        if len(topics) >= max_candidates:
            break

    start = now()
    sets: list[ResolvedSourceSet] = []
    for topic in topics:
        if now() - start >= budget_s:
            log.info(
                "recruit_source_sets: budget %.0fs exhausted after %d candidate(s)",
                budget_s,
                len(sets),
            )
            break
        packets = list(_gather_sources(topic, max_per_collection=per_candidate_limit))
        if use_web and len(packets) < _MIN_LOCAL_PACKETS_BEFORE_WEB:
            packets.extend(
                _tavily_packets(topic, max_results=max(1, per_candidate_limit - len(packets)))
            )
        source_set = build_resolved_source_set(topic, packets)
        if source_set is None:
            log.debug("recruit_source_sets: no resolved material for topic=%s", topic[:60])
            continue
        sets.append(source_set)

    log.info(
        "recruit_source_sets: recruited %d/%d candidate set(s) from %d seed topic(s)",
        len(sets),
        len(topics),
        len(seen_topics),
    )
    return rank_source_sets_by_density(sets)


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
    """Web supplement is EXCISED — an explicit, logged no-op, not a silent one.

    The only available web route was the council's ``async`` web-verify tool,
    which the prior code called WITHOUT ``await``. A coroutine is never a
    ``str``, so the result check always failed and the supplement silently added
    nothing. The fix does NOT "add await": awaiting it routes to the
    ``web-research`` LiteLLM alias the research found mis-routes to a non-grounded
    model, which would launder ungrounded output as "web verification" —
    converting a silent no-op into a silent FAILURE. Until a real grounded web
    provider exists the supplement stays disabled and a sparse-source topic stays
    sparse (``resolve_angle`` then honestly returns no angle rather than a
    fabricated one). Loud here so the disablement is visible, not assumed.
    """
    log.warning(
        "angle_resolver: web supplement DISABLED (no grounded web provider) — "
        "%d local source(s) for topic stay un-supplemented: %s",
        len(existing),
        topic[:80],
    )
    return existing


def _select_angle(topic: str, packets: list[SourcePacket]) -> AngleHypothesis | None:
    """Use the LLM to identify competing positions and select the angle.

    Returns None on LLM failure — the advisory angle is NOT fabricated over all
    packets. The recruited citation set (``recruit_source_set``) is independent of
    this call, so a missing angle costs only the thesis/tension prose, never the
    citable handles.
    """
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
            # Route through the LiteLLM gateway with an explicit provider prefix +
            # api_base. A bare model name (e.g. "local-fast") has no provider, so
            # litellm raises "LLM Provider NOT provided" before any network I/O —
            # which crashed every angle resolution into the degenerate ``except``
            # fallback below (topic-as-thesis, no challenging sources). Mirrors the
            # deployed ``_research_enrich_angle`` routing in daily_segment_prep.py.
            model=f"openai/{MODELS.get('local-fast', 'local-fast')}",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3,
            api_base=os.environ.get("LITELLM_API_BASE", "http://127.0.0.1:4000"),
            api_key=os.environ.get("LITELLM_API_KEY", "not-set"),
            # Audit v2 §5e "every LLM call bounded": this was the one
            # daimonion call site with no timeout (litellm default: 600s).
            timeout=PREP_LLM_TIMEOUT_S,
        )
        text = response.choices[0].message.content or ""
        return _parse_angle_response(topic, text, packets)
    except Exception:
        log.warning(
            "angle_resolver: LLM angle selection failed — no advisory angle (sources intact)",
            exc_info=True,
        )
        return None


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

    # No fabricate-to-fill: if the model named no supporting sources, the advisory
    # angle simply lists none. The citable surface is the recruited set, not this.

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
