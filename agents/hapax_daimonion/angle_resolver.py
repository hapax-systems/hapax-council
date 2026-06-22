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
# Phase 0 ("make the matter readable"): the producer can only name specifics its
# sources actually contain. The legacy text[:500] truncation — and the path-only
# vault stub ("Vault note: <path>", no text) — starved the composer of named
# entities, dragging argumentative_specificity. Read real content, generously
# bounded. (The gap-keyed UNBOUNDED deep-read is a later hermeneutic phase; this is
# the surgical precondition that the whole loop depends on.)
_SOURCE_SNIPPET_CHARS = 1500
_VAULT_NOTE_CHARS = 4000


def recruit_source_set(
    topic: str,
    *,
    max_sources_per_collection: int = 5,
    use_web: bool = True,
    max_reangles: int = 2,
) -> ResolvedSourceSet | None:
    """Recruit a content-hash-bound ResolvedSourceSet for a topic — the citable surface.

    Gathers real packets (Qdrant + vault, then the open web via Tavily when the local
    corpus is dry) and binds them into a closed, deduplicated, set-hashed
    ``ResolvedSourceSet`` whose handles (``src:0..N``) are the ONLY things a composer may
    cite. A DEAD END (0 sources) does not one-shot-refuse: the recruiter RE-ANGLES — it
    re-frames the same matter via LLM-generated alternative queries and re-gathers, until
    density is recovered or the generated angles are spent. Returns None only AFTER that
    traversal honestly exhausts — never a first-miss, never fabricate-to-fill.

    Web recruitment is RETRIEVAL (not an LLM) and fails soft to local-only on any Tavily
    outage; the re-angle's query generation is the ONLY LLM call and is bounded + fail-soft,
    so neither a degraded LLM nor a web outage can collapse the citation set.
    """
    packets = _gather_with_web(
        topic, max_per_collection=max_sources_per_collection, use_web=use_web
    )
    if not packets and max_reangles > 0:
        # Honest exhaustion THEN pivot: traverse the SAME matter from reframed angles and
        # re-gather until density is recovered or the generated angles are spent, before the
        # refusal below fires. "Free to traverse, never free to collapse." The stop is a
        # measured density target, not a topic rule.
        seen: set[str] = set()
        for query in _reangle_queries(topic, packets, limit=max_reangles):
            fresh = [
                packet
                for packet in _gather_with_web(
                    query, max_per_collection=max_sources_per_collection, use_web=use_web
                )
                if packet.content_hash not in seen
            ]
            seen.update(packet.content_hash for packet in fresh)
            packets.extend(fresh)
            if len(packets) >= MIN_SOURCES_FOR_ANGLE:
                break
    if not packets:
        log.warning(
            "recruit_source_set: no sources resolved after re-angle for topic: %s", topic[:80]
        )
        return None
    return build_resolved_source_set(topic, packets)


def _gather_with_web(
    topic: str, *, max_per_collection: int = 5, use_web: bool = True
) -> list[SourcePacket]:
    """Gather local packets (Qdrant + vault) then the open web (Tavily) for ONE query.

    The shared per-query retrieval primitive ``recruit_source_set`` runs for the topic and
    for each re-angle: local first, Tavily only when local is sparse, fail soft on web outage.
    """
    packets = _gather_sources(topic, max_per_collection=max_per_collection)
    if use_web and len(packets) < _MIN_LOCAL_PACKETS_BEFORE_WEB:
        packets.extend(
            _tavily_packets(topic, max_results=max(1, max_per_collection - len(packets)))
        )
    return packets


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
                snippet=text[:_SOURCE_SNIPPET_CHARS],
                freshness="fresh",
                rights_status="web",
                source_consequence="without this web source, only the local corpus is available",
            )
        )
    return packets


def _reangle_queries(topic: str, packets: list[SourcePacket], *, limit: int = 2) -> list[str]:
    """LLM-generate up to ``limit`` ALTERNATIVE search angles for a dead/sparse topic.

    The pivot half of the researcher dynamic: a 0-source first pass is re-framed —
    decomposed into a concrete sub-question, broadened to the general phenomenon, or a
    named related case — to traverse the SAME matter differently rather than one-shot-
    refusing on the first miss. Derived from the topic (+ any thin signal already found),
    NOT a fixed synonym table. Routes through the LOCAL resident model (``local-fast``), so
    the pivot costs no cloud spend; fails soft to ``[]`` on any LLM error (then the recruiter
    honestly exhausts on what it has). Bounded by ``limit`` to cap pivot depth/cost.
    """
    topic = (topic or "").strip()
    if not topic or limit <= 0:
        return []
    try:
        import litellm

        from shared.config import MODELS

        found = "; ".join(p.snippet[:80] for p in packets[:3]) or "(nothing found locally)"
        prompt = (
            f"A search for the topic below returned too few sources. Propose {limit} ALTERNATIVE "
            "search queries that re-frame the SAME underlying matter to find more — decompose it "
            "into a concrete sub-question, broaden to the general phenomenon, or name a known "
            "related case. Stay ON the matter; do not drift to a different topic. One query per "
            f"line, no numbering or commentary.\n\nTOPIC: {topic}\nALREADY FOUND: {found}"
        )
        response = litellm.completion(
            model=f"openai/{MODELS.get('local-fast', 'local-fast')}",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.4,
            api_base=os.environ.get("LITELLM_API_BASE", "http://127.0.0.1:4000"),
            api_key=os.environ.get("LITELLM_API_KEY", "not-set"),
            timeout=PREP_LLM_TIMEOUT_S,
        )
        text = response.choices[0].message.content or ""
    except Exception:
        log.debug(
            "recruit: re-angle query generation failed for topic=%s", topic[:60], exc_info=True
        )
        return []
    queries: list[str] = []
    for line in text.splitlines():
        query = line.strip(" -*\t")
        if query and query.lower() != topic.lower():
            queries.append(query)
    return queries[:limit]


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
    from agents.programme_authors.asset_resolver import (
        VAULT_ROOT,
        _qdrant_search_by_vector,
        _vault_notes_for_topic,
    )
    from shared.config import embed_safe

    packets: list[SourcePacket] = []
    seen_hashes: set[str] = set()

    # Embed the topic ONCE and reuse the vector across all collections — was: one embed per
    # collection (the same query vector recomputed N times, the recruit-density probe's
    # embed cost). Fail-soft: no vector -> skip Qdrant (the vault path still runs).
    vector = embed_safe(topic, prefix="search_query")
    for collection in QDRANT_COLLECTIONS:
        try:
            hits = (
                _qdrant_search_by_vector(collection, vector, limit=max_per_collection)
                if vector
                else []
            )
            for text, source, _score in hits:
                h = hashlib.sha256(text.encode()).hexdigest()[:16]
                if h in seen_hashes:
                    continue
                seen_hashes.add(h)
                packets.append(
                    SourcePacket(
                        source_ref=f"qdrant:{collection}:{source[:80]}",
                        content_hash=h,
                        snippet=text[:_SOURCE_SNIPPET_CHARS],
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
            # Read the note's ACTUAL text (not just its path) so the composer can
            # name the specifics it documents. Bind the packet to the CONTENT hash
            # (not the path), keeping the content-hash invariant over real matter.
            try:
                body = (VAULT_ROOT / note_path).read_text(encoding="utf-8").strip()
            except OSError:
                body = ""
            body = body or f"Vault note: {note_path}"
            h = hashlib.sha256(body.encode()).hexdigest()[:16]
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            packets.append(
                SourcePacket(
                    source_ref=f"vault:{note_path}",
                    content_hash=h,
                    snippet=body[:_VAULT_NOTE_CHARS],
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
    """Supplement sparse local sources with the live GROUNDED web path (Tavily).

    Unifies the web seam: routes through ``_tavily_packets`` — the SAME direct-Tavily
    grounded primitive ``recruit_source_set`` / ``recruit_source_sets`` use — NOT the
    dead LiteLLM ``web-*`` alias (which mis-routes to a non-grounded model and would
    launder ungrounded output as "verification"). Previously this was an excised no-op,
    so ``resolve_angle`` saw NO web sources even for a topic whose citation set
    ``recruit_source_set`` had already bound via Tavily — thinning the advisory angle and
    emitting a misleading "no sources found" log on a SUCCESSFUL recruitment. Fails soft
    to the existing local packets on any Tavily outage (never an exception, never
    fabrication; the min-1-packet honesty floor downstream is untouched).
    """
    if not topic.strip():
        return existing
    web = _tavily_packets(topic, max_results=max(1, MIN_SOURCES_FOR_ANGLE - len(existing)))
    if not web:
        return existing
    seen = {p.content_hash for p in existing}
    merged = list(existing)
    for packet in web:
        if packet.content_hash not in seen:
            seen.add(packet.content_hash)
            merged.append(packet)
    return merged


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
