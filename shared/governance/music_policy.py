"""Music policy — what to do when third-party music is detected on-stream.

Phase 8 of ``docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md``.
Two paths documented in §11 Q1 of the plan:

- **Path A (mute-and-transcript)** — detected music triggers a mute of
  the broadcast sink + a transcript burn-in of the most recent
  operator utterance (via the existing chronicle). Preserves narrative
  continuity for viewers. Chosen as delta's default per the
  ``unblock yourself, make the calls`` operator directive.
- **Path B (≤30s clip windower)** — detected music is allowed to play
  for a bounded window (30 s default), then muted until the operator
  explicitly re-authorises. Relies on fair-use interpretation which
  YouTube's ContentID does not honour algorithmically.

Chosen path: **A**. Rationale:

1. Silence cannot fingerprint-match.
2. Aligns with the "LLMs prepare, humans deliver" axiom — operator
   retains override via ``hapax-music-policy``.
3. Transcript preserves continuity.
4. Path B depends on fair-use heuristics ContentID ignores.

This module ships the policy surface. The detection path is a
``MusicDetector`` Protocol — a concrete implementation lands with
Phase 3 Ring 2 pre-render classifier (task #202). Until then, the
default ``NullMusicDetector`` returns "no music detected" so the
policy is an identity pass-through in production.

Reference:
    - docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md §8
    - Research §11 Q1 (path A vs B rationale)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

log = logging.getLogger(__name__)


class MusicPath(StrEnum):
    """Which response policy is active.

    ``PATH_A`` is the default; Path B requires operator opt-in via CLI
    because it risks ContentID hits during the clip window.
    """

    PATH_A = "mute_and_transcript"
    PATH_B = "clip_windower"


# Path B clip-window default — 30 s per the plan §11 Q1 option B.
PATH_B_DEFAULT_WINDOW_S: Final[float] = 30.0


@dataclass(frozen=True)
class MusicDetectionResult:
    """One pass of the music detector over an audio window."""

    detected: bool
    confidence: float = 0.0  # 0..1; >0.5 treated as detected
    title_guess: str | None = None  # populated by AcoustID/Chromaprint if present
    source: str = "unknown"  # "vinyl" | "youtube" | "system" | "unknown"


class MusicDetector(Protocol):
    """Structural type for concrete detectors (acoustid, chromaprint, LLM classifier)."""

    def detect(self, audio_window: Any) -> MusicDetectionResult: ...


class NullMusicDetector:
    """No-op detector — always returns 'no music detected'.

    Ships as the default until Phase 3 Ring 2 classifier (task #202)
    lands. The policy + CLI are fully functional on top of this; the
    detector is the only piece that's a stub.
    """

    def detect(self, audio_window: Any) -> MusicDetectionResult:
        return MusicDetectionResult(detected=False, confidence=0.0, source="null")


@dataclass(frozen=True)
class MusicPolicyDecision:
    """What the policy says to do at this tick.

    Consumers:
    - ``should_mute`` → cpal/compositor silences the broadcast sink
    - ``surface_transcript`` → pango text ward renders the last operator
      utterance's transcript
    - ``reason`` → logged + emitted via the egress audit (Phase 6)
    """

    should_mute: bool
    surface_transcript: bool
    reason: str
    path: MusicPath
    detection: MusicDetectionResult


@dataclass
class MusicPolicy:
    """Runtime policy state + decision function.

    Stateful only for Path B (tracks clip-window open/close time).
    Path A is effectively stateless — each detection produces the
    same mute+transcript decision.
    """

    path: MusicPath = MusicPath.PATH_A
    detector: MusicDetector = None  # type: ignore[assignment]
    window_s: float = PATH_B_DEFAULT_WINDOW_S
    _path_b_window_opened_at: float | None = None

    def __post_init__(self) -> None:
        if self.detector is None:
            self.detector = NullMusicDetector()

    def evaluate(self, audio_window: Any, *, now: float | None = None) -> MusicPolicyDecision:
        """Inspect ``audio_window`` + apply the active-path policy."""
        result = self.detector.detect(audio_window)
        if not result.detected:
            # Close any open Path B window when music stops.
            if self.path == MusicPath.PATH_B:
                self._path_b_window_opened_at = None
            return MusicPolicyDecision(
                should_mute=False,
                surface_transcript=False,
                reason="no music detected",
                path=self.path,
                detection=result,
            )
        if self.path == MusicPath.PATH_A:
            return MusicPolicyDecision(
                should_mute=True,
                surface_transcript=True,
                reason=(
                    f"music detected (conf={result.confidence:.2f}, "
                    f"source={result.source}): Path A mute+transcript"
                ),
                path=self.path,
                detection=result,
            )
        # Path B: check window.
        import time as _time

        ts = now if now is not None else _time.time()
        if self._path_b_window_opened_at is None:
            self._path_b_window_opened_at = ts
            return MusicPolicyDecision(
                should_mute=False,
                surface_transcript=False,
                reason=(
                    f"music detected (conf={result.confidence:.2f}): "
                    f"Path B window opened, {self.window_s:.1f} s budget"
                ),
                path=self.path,
                detection=result,
            )
        elapsed = ts - self._path_b_window_opened_at
        if elapsed < self.window_s:
            return MusicPolicyDecision(
                should_mute=False,
                surface_transcript=False,
                reason=(
                    f"music detected: Path B window open, "
                    f"{elapsed:.1f}/{self.window_s:.1f} s elapsed"
                ),
                path=self.path,
                detection=result,
            )
        return MusicPolicyDecision(
            should_mute=True,
            surface_transcript=True,
            reason=(
                f"music detected: Path B window expired after "
                f"{elapsed:.1f} s; mute engaged until operator resets"
            ),
            path=self.path,
            detection=result,
        )

    def reset_window(self) -> None:
        """Operator-initiated reset of the Path B window (for re-authorisation)."""
        self._path_b_window_opened_at = None


def default_policy() -> MusicPolicy:
    """Module-level convenience — Path A with NullMusicDetector."""
    return MusicPolicy(path=MusicPath.PATH_A, detector=NullMusicDetector())
