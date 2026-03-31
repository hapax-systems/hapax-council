"""Cross-session memory persistence and retrieval for VoiceDaemon."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


def persist_session_digest(daemon: VoiceDaemon) -> None:
    """Save conversation digest to episodic memory for cross-session recall."""
    if daemon._conversation_pipeline is None:
        return
    try:
        digest = daemon._conversation_pipeline.get_session_digest()
        if not digest or not digest.get("thread"):
            return

        import uuid

        from qdrant_client.models import PointStruct

        from agents._config import embed
        from agents._episodic_memory import Episode, EpisodeStore

        store = EpisodeStore()
        store.ensure_collection()

        episode = Episode(
            activity="voice_conversation",
            voice_turns=digest.get("turn_count", 0),
            duration_s=0,
            start_ts=digest.get("start_ts", time.time()),
        )
        topic_str = ", ".join(digest.get("topic_words", []))
        thread_str = "; ".join(digest.get("thread", []))
        summary = f"Voice conversation about {topic_str}. {thread_str}"

        vec = embed(summary, prefix="search_document")
        point_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"voice-session-{digest.get('session_id', 'unknown')}",
            )
        )
        unresolved = digest.get("unresolved", [])
        grounding_state = "has_unresolved" if unresolved else "resolved"

        store.client.upsert(
            "operator-episodes",
            [
                PointStruct(
                    id=point_id,
                    vector=vec,
                    payload={
                        **episode.model_dump(),
                        "thread": digest.get("thread", []),
                        "topic_words": digest.get("topic_words", []),
                        "session_id": digest.get("session_id", ""),
                        "unresolved": unresolved,
                        "grounding_state": grounding_state,
                    },
                )
            ],
        )
        log.info(
            "Session digest persisted: %d turns, topics=%s",
            digest.get("turn_count", 0),
            topic_str,
        )
    except Exception:
        log.debug("Session digest persistence failed (non-fatal)", exc_info=True)


def load_seed_entries(daemon: VoiceDaemon) -> list:
    """Load cross-session memory as ThreadEntry seed entries for the thread.

    Returns a list of ThreadEntry objects with is_seeded=True, or empty list.
    """
    if not getattr(daemon, "_experiment_flags", {}).get("cross_session", True):
        return []

    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        from agents._episodic_memory import EpisodeStore
        from agents.hapax_daimonion.conversation_pipeline import ThreadEntry

        store = EpisodeStore()
        points, _offset = store.client.scroll(
            "operator-episodes",
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="activity",
                        match=MatchValue(value="voice_conversation"),
                    )
                ]
            ),
            limit=20,
            with_payload=True,
            with_vectors=False,
        )

        if not points:
            return []

        points.sort(key=lambda p: p.payload.get("start_ts", 0), reverse=True)

        def _urgency_sort(p):
            unresolved = p.payload.get("unresolved", [])
            return (1.0 if unresolved else 0.2, p.payload.get("start_ts", 0))

        points.sort(key=_urgency_sort, reverse=True)
        top = points[:3]

        entries = []
        for point in top:
            payload = point.payload or {}
            thread = payload.get("thread", [])
            topics = payload.get("topic_words", [])
            unresolved = payload.get("unresolved", [])

            if not thread and not unresolved:
                continue

            if unresolved:
                user_text = unresolved[0][:100]
                resp = "unresolved from prior session"
                grounding = "ungrounded"
            elif thread:
                last = thread[-1] if thread else ""
                user_text = last[:100] if isinstance(last, str) else str(last)[:100]
                topic_str = ", ".join(topics[:3]) if topics else "prior"
                resp = topic_str
                grounding = "grounded"
            else:
                continue

            entries.append(
                ThreadEntry(
                    turn=0,
                    user_text=user_text,
                    response_summary=resp,
                    acceptance="ACCEPT",
                    grounding_state=grounding,
                    is_repair=False,
                    is_seeded=True,
                )
            )

        return entries[:3]
    except Exception:
        log.debug("Seed entries load failed (non-fatal)", exc_info=True)
        return []


def load_recent_memory(daemon: VoiceDaemon) -> str:
    """Load recent voice session digests from episodic memory.

    Returns a formatted string for system prompt injection, or empty string.
    """
    if not getattr(daemon, "_experiment_flags", {}).get("cross_session", True):
        return ""

    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        from agents._episodic_memory import EpisodeStore

        store = EpisodeStore()
        points, _offset = store.client.scroll(
            "operator-episodes",
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="activity",
                        match=MatchValue(value="voice_conversation"),
                    )
                ]
            ),
            limit=20,
            with_payload=True,
            with_vectors=False,
        )

        if not points:
            return ""

        points.sort(key=lambda p: p.payload.get("start_ts", 0), reverse=True)
        top = points[:3]

        lines = []
        for point in top:
            payload = point.payload or {}
            thread = payload.get("thread", [])
            topics = payload.get("topic_words", [])
            turns = payload.get("voice_turns", 0)

            if thread:
                topic_str = ", ".join(topics[:3]) if topics else "general"
                lines.append(f"- {turns} turns about {topic_str}: " + "; ".join(thread[-3:]))

        return "\n".join(lines) if lines else ""
    except Exception:
        log.debug("Recent memory load failed (non-fatal)", exc_info=True)
        return ""
