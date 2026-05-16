"""Content resolution handlers for recruited affordances.

Each handler takes a narrative string and activation level, resolves the
content (text render, Qdrant query, etc.), and writes to the sources protocol.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from pathlib import Path

from shared.config import embed_safe, get_qdrant

log = logging.getLogger("reverie.content_resolvers")

SOURCES_DIR = Path("/dev/shm/hapax-imagination/sources")
RECRUITED_CONTENT_TTL_MS = 30_000
WAVEFORM_CONTENT_TTL_MS = 8_000


def resolve_narrative_text(
    narrative: str,
    level: float,
    sources_dir: Path = SOURCES_DIR,
    recent_ids: deque | None = None,
) -> bool:
    """Render imagination narrative as visible text on the visual surface."""
    from agents.reverie.content_injector import inject_text

    return inject_text(
        "content-narrative_text",
        narrative,
        opacity=level,
        z_order=20,
        tags=["content", "recruited", "narrative"],
        ttl_ms=RECRUITED_CONTENT_TTL_MS,
    )


def resolve_episodic_recall(
    narrative: str,
    level: float,
    sources_dir: Path = SOURCES_DIR,
    recent_ids: deque | None = None,
) -> bool:
    """Query operator-episodes Qdrant collection for similar past experiences."""
    try:
        embedding = embed_safe(narrative, prefix="search_query")
        if embedding is None:
            return _fallback_text("episodic_recall", f"Recalling: {narrative[:80]}", level)

        client = get_qdrant()
        results = client.query_points(
            collection_name="operator-episodes",
            query=embedding,
            limit=3,
        ).points
        if not results:
            return _fallback_text("episodic_recall", f"No episodes match: {narrative[:80]}", level)

        # Recency penalty
        recent_set = set(recent_ids) if recent_ids is not None else set()
        non_recent = [pt for pt in results if str(pt.id) not in recent_set]
        selected = non_recent[0] if non_recent else results[0]

        if recent_ids is not None:
            recent_ids.append(str(selected.id))

        text = selected.payload.get(
            "narrative", selected.payload.get("text", str(selected.payload))
        )
        return _inject_recalled_text("episodic_recall", text[:400], level)
    except Exception:
        log.debug("Episodic recall failed", exc_info=True)
        return _fallback_text("episodic_recall", f"Recalling: {narrative[:80]}", level)


def resolve_knowledge_recall(
    narrative: str,
    level: float,
    sources_dir: Path = SOURCES_DIR,
    recent_ids: deque | None = None,
) -> bool:
    """Query documents Qdrant collection for relevant knowledge.

    Retrieves top-5, deduplicates by source filename, applies recency
    penalty (ACT-R principle: recently returned content is suppressed
    to prevent monotonic lock-on). Maintains the recruitment invariant:
    narrative drives the query, recency modulates selection.
    """
    try:
        embedding = embed_safe(narrative, prefix="search_query")
        if embedding is None:
            return _fallback_text("knowledge_recall", f"Searching: {narrative[:80]}", level)

        client = get_qdrant()
        results = client.query_points(
            collection_name="documents",
            query=embedding,
            limit=5,
        ).points
        if not results:
            return _fallback_text(
                "knowledge_recall", f"No documents match: {narrative[:80]}", level
            )

        # Dedup by filename (same document chunked multiple times)
        seen_files: set[str] = set()
        unique: list = []
        for pt in results:
            fname = pt.payload.get("filename", pt.id)
            if fname not in seen_files:
                seen_files.add(fname)
                unique.append(pt)

        # Recency penalty: prefer documents not recently shown
        recent_set = set(recent_ids) if recent_ids is not None else set()
        non_recent = [pt for pt in unique if str(pt.id) not in recent_set]
        selected = non_recent[0] if non_recent else unique[0]

        # Track this selection
        if recent_ids is not None:
            recent_ids.append(str(selected.id))

        text = selected.payload.get("text", selected.payload.get("content", str(selected.payload)))
        return _inject_recalled_text("knowledge_recall", text[:400], level)
    except Exception:
        log.debug("Knowledge recall failed", exc_info=True)
        return _fallback_text("knowledge_recall", f"Searching: {narrative[:80]}", level)


def resolve_profile_recall(
    narrative: str,
    level: float,
    sources_dir: Path = SOURCES_DIR,
    recent_ids: deque | None = None,
) -> bool:
    """Query profile-facts Qdrant collection for operator preferences."""
    try:
        embedding = embed_safe(narrative, prefix="search_query")
        if embedding is None:
            return _fallback_text("profile_recall", f"Profile: {narrative[:80]}", level)

        client = get_qdrant()
        results = client.query_points(
            collection_name="profile-facts",
            query=embedding,
            limit=2,
        ).points
        if not results:
            return _fallback_text("profile_recall", f"No profile match: {narrative[:80]}", level)

        facts = [p.payload.get("fact", str(p.payload))[:150] for p in results]
        return _inject_recalled_text("profile_recall", "\n".join(facts), level)
    except Exception:
        log.debug("Profile recall failed", exc_info=True)
        return _fallback_text("profile_recall", f"Profile: {narrative[:80]}", level)


def resolve_waveform_viz(
    narrative: str,
    level: float,
    sources_dir: Path = SOURCES_DIR,
    recent_ids: deque | None = None,
) -> bool:
    """Render current audio energy as a simple visual waveform indicator."""
    try:
        import json as json_mod

        perc_path = Path("/dev/shm/hapax-daimonion/perception-state.json")
        perc = json_mod.loads(perc_path.read_text())
        energy = float(perc.get("audio_energy_rms", 0.0))
        bars = int(energy * 20) + 5
        viz = "▁▂▃▄▅▆▇█"
        waveform = "".join(viz[min(int(energy * 8 + i * 0.5) % 9, 8)] for i in range(bars))
        return _inject_recalled_text(
            "waveform_viz",
            f"Audio: {waveform}",
            level * 0.5,
            WAVEFORM_CONTENT_TTL_MS,
        )
    except Exception:
        log.debug("Waveform viz failed", exc_info=True)
        return False


def _inject_recalled_text(
    source_suffix: str,
    text: str,
    level: float,
    ttl_ms: int = RECRUITED_CONTENT_TTL_MS,
) -> bool:
    """Write recalled text to the sources protocol."""
    from agents.reverie.content_injector import inject_text

    return inject_text(
        f"content-{source_suffix}",
        text,
        opacity=level,
        z_order=15,
        tags=["content", "recruited", "recall"],
        ttl_ms=ttl_ms,
    )


def _fallback_text(source_suffix: str, text: str, level: float) -> bool:
    """Fallback: render the query itself as visible text."""
    from agents.reverie.content_injector import inject_text

    return inject_text(
        f"content-{source_suffix}",
        text,
        opacity=level * 0.3,
        z_order=15,
        tags=["content", "recruited", "fallback"],
        ttl_ms=RECRUITED_CONTENT_TTL_MS,
    )


# Dispatch table: affordance name → resolver function.
# Keys must match names in shared/affordance_registry.py — only names
# indexed in Qdrant can be recruited by the pipeline.
CONTENT_RESOLVERS: dict[str, Callable[..., bool]] = {
    "content.narrative_text": resolve_narrative_text,
    "content.waveform_viz": resolve_waveform_viz,
    "knowledge.episodic_recall": resolve_episodic_recall,
    "knowledge.document_search": resolve_knowledge_recall,
    "knowledge.vault_search": resolve_knowledge_recall,
    "knowledge.profile_facts": resolve_profile_recall,
}
