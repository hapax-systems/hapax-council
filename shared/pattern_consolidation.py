"""Pattern consolidation — LLM-driven extraction of if-then rules from episodes.

WS3 Level 3: reviews accumulated episodes and corrections to extract
reusable patterns. Runs on-demand or as a daily cron. Patterns are
stored in Qdrant for semantic retrieval.

Example pattern:
  "IF activity=coding AND audio_energy drops AND flow_trend falling
   THEN break likely within 5 minutes
   (confidence 0.75, based on 12 episodes, 1 correction)"

Patterns have confidence that:
  - Rises when confirmed by new episodes
  - Decays when contradicted or not seen
  - Starts at the LLM's initial assessment
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger("pattern_consolidation")

COLLECTION = "operator-patterns"
VECTOR_DIM = 768

# ── Data Models ──────────────────────────────────────────────────────────────


class Pattern(BaseModel):
    """An if-then pattern extracted from episodes and corrections."""

    id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    # The rule
    condition: str  # IF part: "activity=coding AND flow_trend falling"
    prediction: str  # THEN part: "break likely within 5 minutes"
    dimension: str = ""  # which dimension this predicts (activity, flow, etc.)

    # Evidence
    confidence: float = 0.5  # 0.0-1.0
    supporting_episodes: int = 0
    contradicting_episodes: int = 0
    corrections_incorporated: int = 0

    # Lifecycle
    last_confirmed: float = 0.0
    last_contradicted: float = 0.0
    active: bool = True  # set to False when superseded or decayed to 0

    @property
    def pattern_text(self) -> str:
        """Text for embedding and retrieval."""
        return f"IF {self.condition} THEN {self.prediction}"

    @property
    def evidence_ratio(self) -> float:
        """Supporting / (supporting + contradicting). 1.0 = never contradicted."""
        total = self.supporting_episodes + self.contradicting_episodes
        if total == 0:
            return 0.5
        return self.supporting_episodes / total

    def confirm(self, now: float | None = None) -> None:
        """Record that this pattern was confirmed by a new episode."""
        if now is None:
            now = time.time()
        self.supporting_episodes += 1
        self.last_confirmed = now
        self.confidence = min(0.95, self.confidence + 0.02)
        self.updated_at = now

    def contradict(self, now: float | None = None) -> None:
        """Record that this pattern was contradicted."""
        if now is None:
            now = time.time()
        self.contradicting_episodes += 1
        self.last_contradicted = now
        self.confidence = max(0.05, self.confidence - 0.05)
        self.updated_at = now

    def decay(self, days_since_confirmed: float) -> None:
        """Apply time-based confidence decay. Called during consolidation."""
        if days_since_confirmed > 30:
            self.confidence = max(0.05, self.confidence * 0.95)
        if self.confidence < 0.1 and days_since_confirmed > 60:
            self.active = False


class PatternMatch(BaseModel):
    """A retrieved pattern with similarity score."""

    pattern: Pattern
    score: float = 0.0


# ── Pattern Extractor (LLM) ─────────────────────────────────────────────────


class ExtractedPattern(BaseModel):
    """Output schema for the LLM pattern extraction."""

    condition: str
    prediction: str
    dimension: str = ""
    confidence: float = 0.5
    reasoning: str = ""


class ConsolidationResult(BaseModel):
    """Output schema for a consolidation run."""

    patterns: list[ExtractedPattern] = Field(default_factory=list)
    summary: str = ""


async def extract_patterns(
    episodes: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
    existing_patterns: list[dict[str, Any]] | None = None,
) -> ConsolidationResult:
    """Use LLM to extract if-then patterns from episodes and corrections.

    Args:
        episodes: Recent episode dicts (from EpisodeStore.get_all or search).
        corrections: Recent correction dicts (from CorrectionStore.get_all).
        existing_patterns: Already-known patterns to avoid duplicates.
    """
    from pydantic_ai import Agent

    from shared.config import get_model
    from shared.operator import get_system_prompt_fragment

    system_prompt = get_system_prompt_fragment("pattern-consolidation") + "\n\n" + _EXTRACT_PROMPT

    agent = Agent(
        get_model("fast"),
        system_prompt=system_prompt,
        output_type=ConsolidationResult,
    )

    # Build the input context
    context_parts: list[str] = []

    if episodes:
        context_parts.append(f"## Recent Episodes ({len(episodes)})\n")
        for ep in episodes[:30]:  # cap at 30 to stay within context
            activity = ep.get("activity", "idle")
            duration = ep.get("duration_s", 0)
            flow = ep.get("flow_state", "idle")
            trend = ep.get("flow_trend", 0)
            hour = ep.get("hour", 0)
            voice = ep.get("voice_turns", 0)
            context_parts.append(
                f"- {activity} ({duration:.0f}s, flow={flow}, "
                f"trend={trend:+.4f}, hour={hour}, voice_turns={voice})"
            )

    if corrections:
        context_parts.append(f"\n## Corrections ({len(corrections)})\n")
        for corr in corrections[:20]:
            dim = corr.get("dimension", "")
            orig = corr.get("original_value", "")
            fixed = corr.get("corrected_value", "")
            ctx = corr.get("context", "")
            context_parts.append(f"- {dim}: {orig} → {fixed}" + (f" ({ctx})" if ctx else ""))

    if existing_patterns:
        context_parts.append(f"\n## Existing Patterns ({len(existing_patterns)})\n")
        for pat in existing_patterns[:15]:
            cond = pat.get("condition", "")
            pred = pat.get("prediction", "")
            conf = pat.get("confidence", 0)
            context_parts.append(f"- IF {cond} THEN {pred} (confidence={conf:.2f})")

    user_prompt = "\n".join(context_parts)

    result = await agent.run(user_prompt)
    return result.output


_EXTRACT_PROMPT = """\
You are a pattern consolidation agent. Your job is to review perception \
episodes and operator corrections to identify recurring if-then patterns \
in operator behavior.

Given a set of episodes and corrections, extract patterns like:
- "IF coding AND flow_trend falling THEN break within 5 minutes"
- "IF hour >= 22 AND activity=coding THEN flow state likely active"
- "IF system said 'coding' but corrected to 'writing' AND context contains 'Obsidian' \
THEN Obsidian usage = writing not coding"

Rules:
1. Each pattern must have a clear IF condition and THEN prediction
2. Set dimension to what the pattern predicts (activity, flow, break, etc.)
3. Confidence should reflect how strong the evidence is (0.3-0.9)
4. Do NOT extract trivial patterns (e.g., "IF coding THEN coding")
5. Do NOT duplicate existing patterns — only extract genuinely new ones
6. Corrections are especially valuable — they reveal systematic mistakes
7. Prefer patterns with at least 2 supporting episodes
8. Keep conditions specific enough to be useful but general enough to apply

Return a ConsolidationResult with the extracted patterns and a brief summary.
If no meaningful patterns emerge, return an empty list with a summary explaining why.
"""


# ── Pattern Store ────────────────────────────────────────────────────────────


class PatternStore:
    """Qdrant-backed pattern store.

    Usage:
        store = PatternStore()
        store.ensure_collection()
        store.record(pattern)
        matches = store.search("coding late at night")
    """

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from shared.config import get_qdrant

            client = get_qdrant()
        self.client = client

    def ensure_collection(self) -> None:
        """Create the operator-patterns collection if it doesn't exist."""
        from qdrant_client.models import Distance, VectorParams

        collections = [c.name for c in self.client.get_collections().collections]
        if COLLECTION not in collections:
            self.client.create_collection(
                COLLECTION,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
            log.info("Created Qdrant collection: %s", COLLECTION)

    def record(self, pattern: Pattern) -> str:
        """Store or update a pattern. Returns the pattern ID."""
        from qdrant_client.models import PointStruct

        from shared.config import embed

        if not pattern.id:
            pattern.id = f"pat-{uuid.uuid4().hex[:12]}"
        if not pattern.created_at:
            pattern.created_at = time.time()
        pattern.updated_at = time.time()

        vec = embed(pattern.pattern_text, prefix="search_document")
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"pattern-{pattern.id}"))

        self.client.upsert(
            COLLECTION,
            [PointStruct(id=point_id, vector=vec, payload=pattern.model_dump())],
        )
        log.debug(
            "Recorded pattern: %s → %s (%.2f)",
            pattern.condition,
            pattern.prediction,
            pattern.confidence,
        )
        return pattern.id

    def search(
        self,
        query: str,
        *,
        dimension: str | None = None,
        active_only: bool = True,
        limit: int = 5,
        min_score: float = 0.3,
    ) -> list[PatternMatch]:
        """Semantic search for patterns matching a situation."""
        from shared.config import embed

        query_vec = embed(query, prefix="search_query")

        conditions = []
        if active_only:
            from qdrant_client.models import FieldCondition, MatchValue

            conditions.append(FieldCondition(key="active", match=MatchValue(value=True)))
        if dimension:
            from qdrant_client.models import FieldCondition, MatchValue

            conditions.append(FieldCondition(key="dimension", match=MatchValue(value=dimension)))

        query_filter = None
        if conditions:
            from qdrant_client.models import Filter

            query_filter = Filter(must=conditions)

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
            pattern = Pattern.model_validate(point.payload)
            matches.append(PatternMatch(pattern=pattern, score=point.score))

        return matches

    def get_active(self, *, limit: int = 100) -> list[Pattern]:
        """Retrieve all active patterns."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        results = self.client.scroll(
            COLLECTION,
            scroll_filter=Filter(must=[FieldCondition(key="active", match=MatchValue(value=True))]),
            limit=limit,
            with_vectors=False,
        )
        return [Pattern.model_validate(p.payload) for p in results[0]]

    def count(self) -> int:
        """Number of stored patterns."""
        info = self.client.get_collection(COLLECTION)
        return info.points_count


# ── Consolidation Runner ─────────────────────────────────────────────────────


async def run_consolidation(
    episode_store: Any,
    correction_store: Any,
    pattern_store: PatternStore,
) -> ConsolidationResult:
    """Run a full consolidation cycle.

    1. Fetch recent episodes and corrections
    2. Fetch existing patterns
    3. Extract new patterns via LLM
    4. Store new patterns
    5. Decay old unconfirmed patterns

    Returns the ConsolidationResult from the LLM.
    """
    # Gather data
    episodes = [ep.model_dump() for ep in episode_store.get_all(limit=50)]
    corrections = [c.model_dump() for c in correction_store.get_all(limit=30)]
    existing = [p.model_dump() for p in pattern_store.get_active(limit=20)]

    # Extract patterns via LLM
    result = await extract_patterns(episodes, corrections, existing)

    # Store new patterns
    now = time.time()
    for extracted in result.patterns:
        pattern = Pattern(
            condition=extracted.condition,
            prediction=extracted.prediction,
            dimension=extracted.dimension,
            confidence=extracted.confidence,
            supporting_episodes=1,
            created_at=now,
        )
        pattern_store.record(pattern)

    # Decay old patterns
    for existing_pat in pattern_store.get_active():
        prev_confidence = existing_pat.confidence
        if existing_pat.last_confirmed > 0:
            days_since = (now - existing_pat.last_confirmed) / 86400
        else:
            days_since = (now - existing_pat.created_at) / 86400
        existing_pat.decay(days_since)
        if not existing_pat.active or existing_pat.confidence != prev_confidence:
            pattern_store.record(existing_pat)  # update in Qdrant

    log.info(
        "Consolidation complete: %d new patterns, %d total active",
        len(result.patterns),
        pattern_store.count(),
    )
    return result
