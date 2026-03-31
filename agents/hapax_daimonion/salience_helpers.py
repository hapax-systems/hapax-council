"""Salience router helpers for VoiceDaemon."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


def refresh_concern_graph(daemon: VoiceDaemon) -> None:
    """Refresh concern anchors from current infrastructure state."""
    if daemon._salience_embedder is None or daemon._salience_concern_graph is None:
        return

    try:
        from agents.hapax_daimonion.salience.anchor_builder import build_anchors

        env = daemon.perception.latest if hasattr(daemon, "perception") else None

        notif_texts: list[str] = []
        if hasattr(daemon, "notifications"):
            for n in daemon.notifications._items[:5]:
                notif_texts.append(getattr(n, "message", str(n)))

        anchors = build_anchors(
            env_state=env,
            notifications=notif_texts,
        )

        if anchors:
            texts = [a.text for a in anchors]
            embeddings = daemon._salience_embedder.embed_batch(texts)
            daemon._salience_concern_graph.refresh(anchors, embeddings)
    except Exception:
        log.debug("Concern graph refresh failed (non-fatal)", exc_info=True)


def refresh_context_distillation(daemon: VoiceDaemon) -> None:
    """Generate context distillation for LOCAL tier prompts."""
    try:
        from agents.hapax_daimonion.salience.anchor_builder import build_context_distillation

        env = daemon.perception.latest if hasattr(daemon, "perception") else None
        notif_count = daemon.notifications.pending_count if hasattr(daemon, "notifications") else 0

        daemon._context_distillation = build_context_distillation(
            env_state=env,
            notification_count=notif_count,
        )

        if daemon._conversation_pipeline is not None:
            daemon._conversation_pipeline._context_distillation = daemon._context_distillation
    except Exception:
        log.debug("Context distillation refresh failed (non-fatal)", exc_info=True)
