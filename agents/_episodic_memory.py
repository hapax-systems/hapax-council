"""Episodic memory — perception episode store for experiential learning.

WS3 Level 2: downsamples perception ring snapshots into episodes bounded
by activity transitions, flow state shifts, time gaps, or consent changes.
Stored in Qdrant for semantic retrieval of "situations like this one."

Episode boundaries:
  - Activity change (coding → browsing)
  - Flow state shift (idle → active)
  - Time gap > 60s (context loss)
  - Consent phase change (guest arrives/departs)

Each episode stores: dominant activity/flow, downsampled signals (5 points),
trends, voice interaction count, and correction linkage.

Follows the same Qdrant patterns as correction_memory:
  - 768-dim nomic-embed-text-v2-moe embeddings
  - Deterministic UUID5 IDs
  - Cosine similarity search
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger("episodic_memory")

COLLECTION = "operator-episodes"
from agents._config import EXPECTED_EMBED_DIMENSIONS as VECTOR_DIM

# ── Data Models ──────────────────────────────────────────────────────────────


class Episode(BaseModel):
    """A contiguous perception episode bounded by state transitions."""

    id: str = ""
    start_ts: float = 0.0
    end_ts: float = 0.0
    duration_s: float = 0.0

    # Dominant state
    activity: str = ""
    flow_state: str = "idle"
    consent_phase: str = "no_guest"

    # Downsampled signals (5 points each, uniform buckets)
    flow_scores: list[float] = Field(default_factory=list)
    audio_energy: list[float] = Field(default_factory=list)
    heart_rates: list[float] = Field(default_factory=list)

    # Trends (slope/s over episode)
    flow_trend: float = 0.0
    audio_trend: float = 0.0

    # Interaction
    voice_turns: int = 0

    # Metadata
    snapshot_count: int = 0
    hour: int = 0

    # Correction linkage
    corrections_applied: list[str] = Field(default_factory=list)

    @property
    def summary_text(self) -> str:
        """Text used for embedding and retrieval."""
        parts = [f"{self.activity or 'idle'} for {self.duration_s:.0f}s"]
        if self.flow_state != "idle":
            parts.append(f"flow: {self.flow_state}")
        if self.flow_trend != 0:
            direction = "rising" if self.flow_trend > 0 else "falling"
            parts.append(f"flow {direction}")
        if self.voice_turns > 0:
            parts.append(f"{self.voice_turns} voice turns")
        if self.heart_rates:
            avg_hr = sum(self.heart_rates) / len(self.heart_rates)
            if avg_hr > 0:
                parts.append(f"heart_rate ~{avg_hr:.0f}bpm")
        if self.audio_energy:
            avg_energy = sum(self.audio_energy) / len(self.audio_energy)
            if avg_energy > 0.01:
                parts.append(f"audio_energy {avg_energy:.2f}")
        if self.consent_phase != "no_guest":
            parts.append(f"consent: {self.consent_phase}")
        return ". ".join(parts)


class EpisodeMatch(BaseModel):
    """A retrieved episode with similarity score."""

    episode: Episode
    score: float = 0.0


# ── Episode Builder ──────────────────────────────────────────────────────────


class EpisodeBuilder:
    """Accumulates perception snapshots and detects episode boundaries.

    Pure logic — no I/O. Call observe() with each perception snapshot.
    When an episode boundary is detected, the completed episode is returned.

    Usage:
        builder = EpisodeBuilder()
        for snapshot in perception_ticks:
            episode = builder.observe(snapshot)
            if episode is not None:
                store.record(episode)
    """

    def __init__(self, gap_threshold_s: float = 60.0) -> None:
        self._snapshots: list[dict[str, Any]] = []
        self._gap_threshold = gap_threshold_s

    def observe(self, snapshot: dict[str, Any]) -> Episode | None:
        """Feed a perception snapshot. Returns completed episode on boundary, else None."""
        if not self._snapshots:
            self._snapshots.append(snapshot)
            return None

        prev = self._snapshots[-1]
        boundary = self._check_boundary(prev, snapshot)

        if boundary:
            episode = self._close_episode()
            self._snapshots = [snapshot]
            return episode

        self._snapshots.append(snapshot)
        return None

    def flush(self) -> Episode | None:
        """Force-close the current episode (e.g., on shutdown)."""
        if len(self._snapshots) >= 2:
            return self._close_episode()
        return None

    def _check_boundary(self, prev: dict[str, Any], current: dict[str, Any]) -> bool:
        """Check all episode boundary conditions."""
        # Activity change
        if current.get("production_activity", "") != prev.get("production_activity", ""):
            if current.get("production_activity", "") or prev.get("production_activity", ""):
                return True

        # Flow state shift
        prev_flow = _flow_state(prev.get("flow_score", 0.0))
        curr_flow = _flow_state(current.get("flow_score", 0.0))
        if prev_flow != curr_flow:
            return True

        # Time gap
        prev_ts = prev.get("timestamp", prev.get("ts", 0))
        curr_ts = current.get("timestamp", current.get("ts", 0))
        if curr_ts - prev_ts > self._gap_threshold:
            return True

        # Consent phase change
        return current.get("consent_phase", "no_guest") != prev.get("consent_phase", "no_guest")

    def _close_episode(self) -> Episode:
        """Build an Episode from accumulated snapshots."""
        snaps = self._snapshots
        first = snaps[0]
        last = snaps[-1]

        start_ts = first.get("timestamp", first.get("ts", 0))
        end_ts = last.get("timestamp", last.get("ts", 0))
        duration = max(0, end_ts - start_ts)

        # Dominant activity (mode)
        activity = _mode([s.get("production_activity", "") for s in snaps])

        # Dominant flow state
        flow_states = [_flow_state(s.get("flow_score", 0.0)) for s in snaps]
        flow_state = _mode(flow_states)

        # Consent phase (last value — represents end state)
        consent = last.get("consent_phase", "no_guest")

        # Downsample signals to 5 points
        flow_scores = _downsample([s.get("flow_score", 0.0) for s in snaps], 5)
        audio_energy = _downsample([s.get("audio_energy_rms", 0.0) for s in snaps], 5)
        heart_rates = _downsample([float(s.get("heart_rate_bpm", 0)) for s in snaps], 5)

        # Trends (simple: last - first / duration)
        flow_trend = 0.0
        audio_trend = 0.0
        if duration > 0 and len(snaps) >= 2:
            flow_trend = (
                snaps[-1].get("flow_score", 0.0) - snaps[0].get("flow_score", 0.0)
            ) / duration
            audio_trend = (
                snaps[-1].get("audio_energy_rms", 0.0) - snaps[0].get("audio_energy_rms", 0.0)
            ) / duration

        # Voice turns
        voice_turns = 0
        for s in snaps:
            vs = s.get("voice_session", {})
            if isinstance(vs, dict):
                voice_turns = max(voice_turns, vs.get("turn_count", 0))

        # Hour from first snapshot
        from datetime import datetime

        hour = datetime.fromtimestamp(start_ts).hour if start_ts > 1e9 else 0

        return Episode(
            id=f"ep-{uuid.uuid4().hex[:12]}",
            start_ts=start_ts,
            end_ts=end_ts,
            duration_s=round(duration, 1),
            activity=activity,
            flow_state=flow_state,
            consent_phase=consent,
            flow_scores=flow_scores,
            audio_energy=audio_energy,
            heart_rates=heart_rates,
            flow_trend=round(flow_trend, 6),
            audio_trend=round(audio_trend, 6),
            voice_turns=voice_turns,
            snapshot_count=len(snaps),
            hour=hour,
        )


# ── Episode Store ────────────────────────────────────────────────────────────


class EpisodeStore:
    """Qdrant-backed semantic episode store.

    Usage:
        store = EpisodeStore()
        store.ensure_collection()
        store.record(episode)
        matches = store.search("coding session with rising flow")
    """

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from agents._config import get_qdrant

            client = get_qdrant()
        self.client = client

    def ensure_collection(self) -> None:
        """Create the operator-episodes collection if it doesn't exist."""
        from qdrant_client.models import Distance, VectorParams

        collections = [c.name for c in self.client.get_collections().collections]
        if COLLECTION not in collections:
            self.client.create_collection(
                COLLECTION,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
            log.info("Created Qdrant collection: %s", COLLECTION)

    def record(self, episode: Episode) -> str:
        """Store an episode. Returns the episode ID."""
        from qdrant_client.models import PointStruct

        from agents._config import embed

        if not episode.id:
            episode.id = f"ep-{uuid.uuid4().hex[:12]}"

        vec = embed(episode.summary_text, prefix="search_document")
        point_id = str(
            uuid.uuid5(uuid.NAMESPACE_DNS, f"episode-{episode.start_ts:.0f}-{episode.activity}")
        )

        self.client.upsert(
            COLLECTION,
            [PointStruct(id=point_id, vector=vec, payload=episode.model_dump())],
        )
        log.debug(
            "Recorded episode: %s (%s, %.0fs)", episode.id, episode.activity, episode.duration_s
        )
        return episode.id

    def search(
        self,
        query: str,
        *,
        activity: str | None = None,
        flow_state: str | None = None,
        limit: int = 5,
        min_score: float = 0.3,
    ) -> list[EpisodeMatch]:
        """Semantic search for similar episodes."""
        from agents._config import embed

        query_vec = embed(query, prefix="search_query")

        conditions = []
        if activity:
            from qdrant_client.models import FieldCondition, MatchValue

            conditions.append(FieldCondition(key="activity", match=MatchValue(value=activity)))
        if flow_state:
            from qdrant_client.models import FieldCondition, MatchValue

            conditions.append(FieldCondition(key="flow_state", match=MatchValue(value=flow_state)))

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
            episode = Episode.model_validate(point.payload)
            matches.append(EpisodeMatch(episode=episode, score=point.score))

        return matches

    def search_for_activity(
        self, activity: str, context: str = "", limit: int = 3
    ) -> list[EpisodeMatch]:
        """Find past episodes for this activity."""
        query = f"{activity} session"
        if context:
            query += f". {context}"
        return self.search(query, activity=activity, limit=limit)

    def count(self) -> int:
        """Number of stored episodes."""
        info = self.client.get_collection(COLLECTION)
        return info.points_count


# ── Helpers ──────────────────────────────────────────────────────────────────


def _flow_state(score: float) -> str:
    """Convert flow score to discrete state."""
    if score >= 0.6:
        return "active"
    if score >= 0.3:
        return "warming"
    return "idle"


def _mode(values: list[str]) -> str:
    """Return most common non-empty value, or empty string."""
    counts: dict[str, int] = {}
    for v in values:
        if v:
            counts[v] = counts.get(v, 0) + 1
    if not counts:
        return ""
    return max(counts, key=counts.get)  # type: ignore[arg-type]


def _downsample(values: list[float], n: int) -> list[float]:
    """Downsample a list of floats to n points using bucket medians."""
    if not values:
        return [0.0] * n
    if len(values) <= n:
        padded = values + [values[-1]] * (n - len(values))
        return [round(v, 3) for v in padded]

    bucket_size = len(values) / n
    result: list[float] = []
    for i in range(n):
        start = int(i * bucket_size)
        end = int((i + 1) * bucket_size)
        bucket = sorted(values[start:end])
        median = bucket[len(bucket) // 2]
        result.append(round(median, 3))
    return result
