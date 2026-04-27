"""Advanced music selector — T2-1 skeleton for CVS #130.

Implements the 7-step stimmung/BPM/key-weighted selector that will govern
the ``vinyl_playing == False`` window. This is a skeleton implementation;
the mathematical core of the affinities (Gaussian/Camelot) and the
softmax sampling are stubbed out for later phase execution.
"""

from __future__ import annotations

import logging
import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.music_repo import LocalMusicTrack

log = logging.getLogger(__name__)


class StimmungVector:
    """Stub representation of the current room mood vector."""

    def to_mood_vector(self) -> list[float]:
        return [0.0, 0.0, 0.0]


class TrackMeta:
    """Stub representation of the last vinyl track's metadata."""

    def __init__(self, bpm: float | None = None, key: str | None = None) -> None:
        self.bpm = bpm
        self.key = key


def _camelot_distance(key_a: str, key_b: str) -> float:
    """Compute affinity [0, 1] based on Camelot wheel distance.

    Returns 1.0 for same key, 0.8 adjacent, 0.7 relative minor/major,
    0.2 for tritone, etc.
    """
    # Stub implementation
    if key_a == key_b:
        return 1.0
    return 0.5


def _gaussian_affinity(target: float, actual: float, sigma: float = 6.0) -> float:
    """Compute Gaussian affinity [0, 1] around a target value."""
    diff = target - actual
    return math.exp(-(diff**2) / (2 * sigma**2))


class AdvancedMusicSelector:
    """Selects the next local track based on stimmung, BPM, and Key."""

    def __init__(self) -> None:
        # Repetition penalty state: remember the last 5 selected paths
        self._session_history: list[str] = []

    def select_next(
        self,
        pool: list[LocalMusicTrack],
        stimmung: StimmungVector,
        last_vinyl: TrackMeta | None,
        tau: float = 0.35,
    ) -> LocalMusicTrack | None:
        """Select the next track from the pool using the 7-step algorithm.

        Args:
            pool: The full set of available tracks (e.g. from LocalMusicRepo).
            stimmung: The current room mood vector.
            last_vinyl: Metadata of the last played vinyl track, if any.
            tau: Softmax temperature parameter.
        """
        # Step 1: Filter to selectable (must have BPM and Key)
        # Note: 'key' isn't on LocalMusicTrack yet, assume it's in frontmatter/tags
        selectable = [t for t in pool if getattr(t, "bpm", None) is not None]
        if not selectable:
            return None

        scored_candidates: list[tuple[float, LocalMusicTrack]] = []
        target_bpm = last_vinyl.bpm if last_vinyl else None
        target_key = last_vinyl.key if last_vinyl else None

        for track in selectable:
            # Step 2: Stimmung score
            # cosine_similarity(stimmung.to_mood_vector(), track.mood_vector)
            score_stimmung = 0.5  # Stub

            # Step 3: BPM affinity
            if target_bpm is not None and track.bpm is not None:
                score_bpm = _gaussian_affinity(target_bpm, track.bpm, sigma=6.0)
            else:
                score_bpm = 1.0

            # Step 4: Key affinity
            track_key = "C major"  # Stub, would read from frontmatter
            if target_key is not None:
                score_key = _camelot_distance(target_key, track_key)
            else:
                score_key = 1.0

            # Step 5: Repetition penalty
            score_rep = 0.0 if track.path in self._session_history else 1.0

            # Step 6: Final score
            # Weights: 0.45 stimmung, 0.25 bpm, 0.20 key, 0.10 rep
            final_score = (
                (0.45 * score_stimmung)
                + (0.25 * score_bpm)
                + (0.20 * score_key)
                + (0.10 * score_rep)
            )
            scored_candidates.append((final_score, track))

        if not scored_candidates:
            return None

        # Step 7: Selection via Softmax
        # Convert scores to probabilities: e^(score/tau) / sum(e^(score/tau))
        max_score = max(s for s, _ in scored_candidates)
        exp_scores = [math.exp((s - max_score) / tau) for s, _ in scored_candidates]
        sum_exp = sum(exp_scores)
        probs = [e / sum_exp for e in exp_scores]

        # Sample based on probabilities
        selected_track = random.choices([t for _, t in scored_candidates], weights=probs, k=1)[0]

        # Update repetition history (rolling window of 5)
        self._session_history.append(selected_track.path)
        if len(self._session_history) > 5:
            self._session_history.pop(0)

        return selected_track
