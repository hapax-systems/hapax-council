"""LLM-assisted segment detection for the auto-clip Shorts pipeline.

Builds on the (in-flight) ``auto-clip-shorts-livestream-pipeline``
predecessor module. Where that pipeline handles VOD windowing, clip
rendering, face-obscure verification, and platform dispatch, this layer
adds the *proposer*: an LLM scout that reads a rolling 10-minute window
of livestream context (transcript + impingements + chat) and proposes
3–5 candidate clips per scan ranked by polysemic-decoder-channel
resonance.

The output is a typed list of :class:`SegmentCandidate` that the
downstream clip-extraction pipeline consumes via its declared input
contract.

Per ``cc-task auto-clip-shorts-livestream-pipeline`` §Scope, the six
polysemic decoder channels (visual / sonic / linguistic / typographic /
structural / marker-as-membership) are encoded as the
:class:`DecoderChannel` enum. Each candidate names the channels it
resonates on; downstream rendering uses these to select the per-channel
visual / overlay / caption template.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent

from shared.config import get_model


class DecoderChannel(StrEnum):
    """The six polysemic decoder channels per Hapax Manifesto §II.

    Each candidate clip is mapped to one or more channels; the
    downstream renderer uses these to pick per-channel templates.
    """

    VISUAL = "visual"
    SONIC = "sonic"
    LINGUISTIC = "linguistic"
    TYPOGRAPHIC = "typographic"
    STRUCTURAL = "structural"
    MARKER_AS_MEMBERSHIP = "marker_as_membership"


class SegmentCandidate(BaseModel):
    """One proposed clip from the LLM scout.

    The downstream clip-extraction pipeline consumes a ranked list of
    these. ``resonance`` is the LLM's self-rated estimate (0..1) of how
    strongly the candidate aligns with the polysemic-decoder-channel
    aesthetic; the pipeline applies its own sort order on top.
    """

    start_offset_seconds: float = Field(
        ge=0.0,
        description="Seconds from window_start at which the clip begins.",
    )
    end_offset_seconds: float = Field(
        gt=0.0,
        description="Seconds from window_start at which the clip ends.",
    )
    resonance: float = Field(
        ge=0.0,
        le=1.0,
        description="LLM self-rated resonance score on the polysemic-decoder-channel aesthetic.",
    )
    decoder_channels: list[DecoderChannel] = Field(
        min_length=1,
        description="Which polysemic decoder channels this clip resonates on. At least one.",
    )
    rationale: str = Field(
        min_length=1,
        max_length=500,
        description="One-sentence reason this segment is worth clipping.",
    )
    hook_text: str = Field(
        min_length=1,
        max_length=120,
        description="Two-second on-screen hook for the Shorts opening frame.",
    )
    suggested_title: str = Field(
        min_length=1,
        max_length=100,
        description="Title for the Shorts upload (under YouTube's 100-char limit).",
    )

    @field_validator("end_offset_seconds")
    @classmethod
    def _end_after_start(cls, v: float, info) -> float:
        start = info.data.get("start_offset_seconds")
        if start is not None and v <= start:
            raise ValueError(f"end_offset_seconds ({v}) must be > start_offset_seconds ({start})")
        return v

    @field_validator("decoder_channels")
    @classmethod
    def _dedupe_channels(cls, v: list[DecoderChannel]) -> list[DecoderChannel]:
        seen: set[DecoderChannel] = set()
        out: list[DecoderChannel] = []
        for ch in v:
            if ch not in seen:
                seen.add(ch)
                out.append(ch)
        return out


@dataclass
class RollingContext:
    """A 10-minute rolling slice of livestream signals fed to the LLM scout.

    The detector ingests three streams aligned on ``window_start`` ..
    ``window_end``:

    * ``transcript_text`` — flattened ``"speaker: text"`` lines (or
      narrator-tagged text) from the spoken layer.
    * ``impingements`` — recent narrative-shape events from
      ``/dev/shm/hapax-dmn/impingements.jsonl``.
    * ``chat_messages`` — anonymised author-hash + sentiment + text from
      ``YoutubeChatReader.recent_messages``.

    All three are optional; if a source is empty the detector still
    runs (the LLM will simply weight remaining signal more strongly).
    """

    window_start: datetime
    window_end: datetime
    transcript_text: str = ""
    impingements: list[dict] = field(default_factory=list)
    chat_messages: list[dict] = field(default_factory=list)

    @property
    def window_seconds(self) -> float:
        return (self.window_end - self.window_start).total_seconds()


_SYSTEM_PROMPT = """\
You are a livestream-clip scout for the 24/7 Hapax ambient broadcast.

Your job: read the rolling 10-minute window of context (transcript +
impingements + chat) and propose 3 to 5 high-resonance candidate clips
that would make compelling vertical-format Shorts.

Each candidate must:

1. Be 15 to 60 seconds long (Shorts duration window).
2. Map to one or more of the six polysemic decoder channels:
   - visual: shader-graph / Reverie frame transitions
   - sonic: voice excerpt / vinyl-chain transition
   - linguistic: chronicle overlay text passage
   - typographic: VGA / JetBrains-Mono register transition
   - structural: axiom-registry / governance-yaml diff
   - marker_as_membership: commit-vocabulary / persona-posture taxonomy
3. Rate its own resonance (0..1) on the polysemic-decoder aesthetic.
   Reserve scores >= 0.85 for clearly exceptional moments.
4. Provide a one-sentence rationale and a two-second on-screen hook.
5. Provide a Shorts-suitable title (under 100 characters).

Selection priority:
- Density of polysemic-decoder signal over time-window length.
- Cross-channel resonance (a moment that hits 3+ channels beats a
  single-channel moment of equal density).
- Anti-overclaim: if the window is mostly ambient with no clear hook,
  return the minimum 3 candidates and let the downstream pipeline
  filter on resonance threshold.

Output exactly 3 to 5 candidates ordered by resonance descending.
Offsets are SECONDS FROM WINDOW START (not absolute timestamps).
"""


class _AgentLike(Protocol):
    """Protocol for the pydantic-ai Agent surface this module uses.

    Defined so tests can inject a fake without touching the real LLM.
    """

    def run_sync(self, user_prompt: str) -> object: ...


def _format_context(context: RollingContext) -> str:
    """Render a :class:`RollingContext` into the LLM user prompt."""
    parts: list[str] = []
    parts.append(f"WINDOW: {context.window_seconds:.0f} seconds")
    parts.append(
        f"  start: {context.window_start.isoformat()}  end: {context.window_end.isoformat()}"
    )
    parts.append("")

    parts.append("TRANSCRIPT:")
    if context.transcript_text.strip():
        parts.append(context.transcript_text.strip())
    else:
        parts.append("  (no transcript captured for this window)")
    parts.append("")

    parts.append(f"IMPINGEMENTS ({len(context.impingements)}):")
    if context.impingements:
        for imp in context.impingements[-30:]:  # cap to avoid prompt bloat
            kind = imp.get("kind") or imp.get("type") or "?"
            narrative = imp.get("narrative") or imp.get("description") or imp.get("text") or ""
            parts.append(f"  - [{kind}] {narrative}".rstrip())
    else:
        parts.append("  (no impingements in this window)")
    parts.append("")

    parts.append(f"CHAT ({len(context.chat_messages)}):")
    if context.chat_messages:
        for msg in context.chat_messages[-40:]:
            text = msg.get("text", "")
            sentiment = msg.get("sentiment")
            tag = f"[{sentiment:+.2f}] " if isinstance(sentiment, (int, float)) else ""
            parts.append(f"  - {tag}{text}".rstrip())
    else:
        parts.append("  (no chat messages in this window)")
    parts.append("")

    return "\n".join(parts)


class LlmSegmentDetector:
    """Scout 3–5 :class:`SegmentCandidate` clips from a rolling context.

    Backed by a pydantic-ai :class:`Agent` with structured
    ``output_type=list[SegmentCandidate]``. The default model is the
    ``balanced`` alias (Claude Sonnet) for proposal quality; tests
    inject a deterministic agent instead.
    """

    MIN_CANDIDATES: int = 3
    MAX_CANDIDATES: int = 5

    def __init__(self, agent: _AgentLike | None = None, *, model_alias: str = "balanced") -> None:
        if agent is not None:
            self._agent = agent
        else:
            self._agent = Agent(
                get_model(model_alias),
                system_prompt=_SYSTEM_PROMPT,
                output_type=list[SegmentCandidate],
            )

    def detect(self, context: RollingContext) -> list[SegmentCandidate]:
        """Run the scout against ``context`` and return ranked candidates.

        The candidates are returned in resonance-descending order. The
        list is clamped to ``[MIN_CANDIDATES, MAX_CANDIDATES]`` — if the
        agent produces fewer than ``MIN_CANDIDATES`` the result is
        passed through as-is so callers can detect degraded input
        (downstream pipeline filters by resonance threshold).
        """
        prompt = _format_context(context)
        result = self._agent.run_sync(prompt)
        candidates: list[SegmentCandidate] = list(result.output)
        candidates.sort(key=lambda c: c.resonance, reverse=True)
        return candidates[: self.MAX_CANDIDATES]


def read_recent_impingements(
    *,
    path: Path = Path("/dev/shm/hapax-dmn/impingements.jsonl"),
    window: timedelta = timedelta(minutes=10),
    now: datetime | None = None,
) -> list[dict]:
    """Tail ``impingements.jsonl`` and return entries within ``window``.

    Each line is parsed as JSON. Entries lacking a parseable timestamp
    fall through (kept) so the LLM can still see them — staleness is
    tolerable for clip detection. Malformed JSON lines are skipped.
    """
    if now is None:
        now = datetime.now(UTC)
    cutoff = now - window
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts_raw = entry.get("timestamp") or entry.get("created_at") or entry.get("ts")
        if ts_raw is None:
            out.append(entry)
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except ValueError:
            out.append(entry)
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts >= cutoff:
            out.append(entry)
    return out


def chat_snapshots_to_dicts(snapshots: list) -> list[dict]:
    """Convert :class:`ChatMessageSnapshot`-shaped objects to plain dicts.

    Accepts anything with ``text`` / ``sentiment`` / ``length`` /
    ``posted_at_unix`` attributes (or already-dict entries with those
    keys). Empty input → empty list.
    """
    out: list[dict] = []
    for snap in snapshots:
        if isinstance(snap, dict):
            out.append(snap)
            continue
        out.append(
            {
                "text": getattr(snap, "text", ""),
                "sentiment": getattr(snap, "sentiment", None),
                "length": getattr(snap, "length", None),
                "posted_at_unix": getattr(snap, "posted_at_unix", None),
            }
        )
    return out
