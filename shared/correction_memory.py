"""Correction memory — stores and retrieves operator corrections for experiential learning.

WS3 Level 1: the foundation of experiential refinement. Every time the operator
corrects Hapax's interpretation (activity label, flow state, presence detection,
etc.), the correction is embedded and stored in Qdrant for semantic retrieval.

When making future interpretations, the system retrieves similar past corrections
to avoid repeating the same mistakes. Over time this builds a corpus of operator-
specific ground truth that all higher WS3 levels consume.

Uses the same Qdrant patterns as profile_store and axiom_precedents:
  - 768-dim nomic-embed-text-v2-moe embeddings via Ollama
  - Deterministic UUID5 IDs
  - Cosine similarity search
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

log = logging.getLogger("correction_memory")

COLLECTION = "operator-corrections"
VECTOR_DIM = 768

# ── Data Models ──────────────────────────────────────────────────────────────


class Correction(BaseModel):
    """An operator correction of a system interpretation."""

    id: str = ""
    timestamp: float = 0.0

    # What was wrong
    dimension: str  # activity | flow | presence | emotion | genre | other
    original_value: str  # what the system said
    corrected_value: str  # what the operator said

    # Context at the time of correction
    context: str = ""  # free-text context (what was happening)
    flow_score: float = 0.0
    activity: str = ""
    hour: int = 0

    # Retrieval metadata
    applied_count: int = 0  # how many times this correction influenced a decision
    last_applied: float = 0.0

    @property
    def correction_text(self) -> str:
        """Text used for embedding and retrieval."""
        parts = [
            f"{self.dimension}: {self.original_value} → {self.corrected_value}",
        ]
        if self.context:
            parts.append(f"context: {self.context}")
        if self.activity:
            parts.append(f"during: {self.activity}")
        return ". ".join(parts)


class CorrectionMatch(BaseModel):
    """A retrieved correction with similarity score."""

    correction: Correction
    score: float = 0.0


# ── Correction Store ─────────────────────────────────────────────────────────


class CorrectionStore:
    """Qdrant-backed semantic correction memory.

    Usage:
        store = CorrectionStore()
        store.ensure_collection()

        # Record a correction
        store.record(Correction(
            dimension="activity",
            original_value="coding",
            corrected_value="writing",
            context="was in Obsidian, not VS Code",
        ))

        # Retrieve similar corrections
        matches = store.search("activity detection when in Obsidian")
    """

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from shared.config import get_qdrant

            client = get_qdrant()
        self.client = client

    def ensure_collection(self) -> None:
        """Create the operator-corrections collection if it doesn't exist."""
        from qdrant_client.models import Distance, VectorParams

        collections = [c.name for c in self.client.get_collections().collections]
        if COLLECTION not in collections:
            self.client.create_collection(
                COLLECTION,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
            log.info("Created Qdrant collection: %s", COLLECTION)

    def record(self, correction: Correction) -> str:
        """Store a correction. Returns the correction ID."""
        from qdrant_client.models import PointStruct

        from shared.config import embed

        if not correction.id:
            correction.id = f"corr-{uuid.uuid4().hex[:12]}"
        if not correction.timestamp:
            correction.timestamp = time.time()

        vec = embed(correction.correction_text, prefix="search_document")
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"correction-{correction.id}"))

        self.client.upsert(
            COLLECTION,
            [
                PointStruct(
                    id=point_id,
                    vector=vec,
                    payload=correction.model_dump(),
                )
            ],
        )
        log.info(
            "Recorded correction: %s → %s (%s)",
            correction.original_value,
            correction.corrected_value,
            correction.dimension,
        )
        return correction.id

    def search(
        self,
        query: str,
        *,
        dimension: str | None = None,
        limit: int = 5,
        min_score: float = 0.3,
    ) -> list[CorrectionMatch]:
        """Semantic search for corrections similar to a situation.

        Args:
            query: Description of the current situation.
            dimension: Optional filter (activity, flow, presence, etc.).
            limit: Max results.
            min_score: Minimum similarity score to include.
        """
        from shared.config import embed

        query_vec = embed(query, prefix="search_query")

        query_filter = None
        if dimension:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            query_filter = Filter(
                must=[FieldCondition(key="dimension", match=MatchValue(value=dimension))]
            )

        results = self.client.query_points(
            COLLECTION,
            query=query_vec,
            query_filter=query_filter,
            limit=limit,
        )

        matches = []
        for point in results.points:
            if point.score < min_score:
                continue
            correction = Correction.model_validate(point.payload)
            matches.append(CorrectionMatch(correction=correction, score=point.score))

        return matches

    def search_for_dimension(
        self,
        dimension: str,
        current_value: str,
        context: str = "",
        limit: int = 3,
    ) -> list[CorrectionMatch]:
        """Search for corrections relevant to a specific interpretation.

        Convenience method for the common case: "I'm about to interpret
        dimension X as value Y — have I been corrected in similar situations?"
        """
        query = f"{dimension}: {current_value}"
        if context:
            query += f". context: {context}"
        return self.search(query, dimension=dimension, limit=limit)

    def get_all(self, *, limit: int = 100) -> list[Correction]:
        """Retrieve all corrections (for export/analysis)."""
        results = self.client.scroll(COLLECTION, limit=limit, with_vectors=False)
        return [Correction.model_validate(p.payload) for p in results[0]]

    def count(self) -> int:
        """Number of stored corrections."""
        info = self.client.get_collection(COLLECTION)
        return info.points_count


# ── File-based correction intake ─────────────────────────────────────────────

CORRECTION_INTAKE_PATH = Path("/dev/shm/hapax-compositor/activity-correction.json")


def check_for_corrections(store: CorrectionStore, current_state: dict[str, Any]) -> Correction | None:
    """Check if the operator has submitted a correction via the intake file.

    The correction file is written by the studio UI when the operator
    corrects the activity label. Format:
        {"label": "writing", "detail": "in Obsidian", "timestamp": ..., "ttl_s": 1800}

    If found and the label differs from the current activity, record it
    as a correction and return it. Returns None if no correction pending.
    """
    try:
        data = json.loads(CORRECTION_INTAKE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    corrected_label = data.get("label", "")
    current_activity = current_state.get("production_activity", "")

    if not corrected_label or corrected_label == current_activity:
        return None

    # Check freshness (only process corrections from the last 5 min)
    correction_time = data.get("timestamp", 0)
    if correction_time and (time.time() - correction_time) > 300:
        return None

    correction = Correction(
        dimension="activity",
        original_value=current_activity,
        corrected_value=corrected_label,
        context=data.get("detail", ""),
        flow_score=current_state.get("flow_score", 0.0),
        activity=current_activity,
        hour=current_state.get("hour", 0),
    )

    try:
        store.record(correction)
    except Exception:
        log.debug("Failed to record correction", exc_info=True)
        return None

    return correction
