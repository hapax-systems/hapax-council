"""Segment-observability wrapper for chat-ingestion poll cycles.

Bridges :class:`shared.segment_observability.SegmentRecorder` to the
chat-ingestion impingement pipeline so the operator's massive smoke
test can answer two questions about every chat poll cycle:

1. *Did it happen?* — handled by ``SegmentRecorder``'s lifecycle
   markers (``STARTED`` / ``HAPPENED`` / ``DIDNT_HAPPEN``).
2. *Did it happen well?* — handled here by
   :func:`assess_chat_reactivity`, which grades the impingement bus
   output against the operator's 4-level rubric:

   * **POOR** — zero impingements emitted when the input batch was
     non-empty. The pipeline is silent / broken / consent-gated.
   * **ACCEPTABLE** — partial flow (emit ratio < 0.7). Some drops or
     malformed inputs survived sanitisation skip-on-empty.
   * **GOOD** — consistent flow (emit ratio ≥ 0.7) but at least one
     emission failed the well-formed invariants.
   * **EXCELLENT** — emit ratio ≥ 0.95 AND every emitted record is
     well-formed: author token is hex-only (no plaintext channelIds
     leaking through), URLs are stripped, control chars stripped,
     length within :data:`agents.youtube_chat_reader.sanitize.MAX_LENGTH`.

The assessor reads the impingement bus directly — pure file
inspection, no API calls, no hidden dependencies on the reader's
internal state. That keeps the smoke test honest: if the bus on disk
shows what we want, downstream consumers (AffordancePipeline,
chat-ward compositor) will see the same.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from agents.youtube_chat_reader.sanitize import MAX_LENGTH
from shared.segment_observability import QualityRating, SegmentEvent, SegmentRecorder

__all__ = [
    "ChatReactivityAssessment",
    "assess_chat_reactivity",
    "record_chat_reactivity_segment",
]

CHAT_SOURCE_TAG = "youtube_chat"
EMIT_RATIO_ACCEPTABLE_FLOOR = 0.7
EMIT_RATIO_EXCELLENT_FLOOR = 0.95
PROGRAMME_ROLE_TAG = "chat_ingestion"


@dataclass(frozen=True)
class ChatReactivityAssessment:
    """Outcome of grading one poll cycle.

    Returned by :func:`assess_chat_reactivity` and copied into the
    :class:`SegmentEvent` quality + notes by
    :func:`record_chat_reactivity_segment`. Kept as a plain dataclass
    (not a Pydantic model) so the assessor stays callable without the
    segment-observability dependency for ad-hoc diagnostic use.
    """

    rating: QualityRating
    notes: str
    inputs_observed: int
    impingements_emitted: int
    well_formed: int


def assess_chat_reactivity(
    *,
    bus_path: Path,
    expected_inputs: int,
) -> ChatReactivityAssessment:
    """Grade the impingement bus output against the operator's rubric.

    Args:
        bus_path: Path to the impingement-bus JSONL the reader writes
            to (typically ``/dev/shm/hapax-dmn/impingements.jsonl``,
            but tests pass a tmp file).
        expected_inputs: Number of *non-blank* chat items the caller
            fed into the reader during the cycle. Blank items dropped
            by the sanitiser must not be counted — the reader is
            correct to suppress them, and including them would
            penalise correct behaviour.

    Returns:
        A :class:`ChatReactivityAssessment` with rating, notes, and
        the raw counts the rating was derived from.
    """

    chat_records = _read_chat_records(bus_path)
    emitted = len(chat_records)
    well_formed = sum(1 for r in chat_records if _is_well_formed(r))

    if expected_inputs <= 0:
        rating, base_notes = _grade_no_inputs(emitted)
        return ChatReactivityAssessment(
            rating=rating,
            notes=base_notes,
            inputs_observed=expected_inputs,
            impingements_emitted=emitted,
            well_formed=well_formed,
        )

    rating = _grade_with_inputs(
        emitted=emitted,
        well_formed=well_formed,
        expected_inputs=expected_inputs,
    )
    emit_ratio = emitted / expected_inputs
    well_formed_ratio = well_formed / emitted if emitted else 0.0
    notes = (
        f"emit_ratio={emit_ratio:.2f} ({emitted}/{expected_inputs}); "
        f"well_formed={well_formed}/{emitted} "
        f"({well_formed_ratio:.2f}); rating={rating.value}"
    )
    return ChatReactivityAssessment(
        rating=rating,
        notes=notes,
        inputs_observed=expected_inputs,
        impingements_emitted=emitted,
        well_formed=well_formed,
    )


@contextmanager
def record_chat_reactivity_segment(
    *,
    bus_path: Path,
    expected_inputs: int,
    topic_seed: str | None = None,
    log_path: Path | None = None,
) -> Iterator[SegmentEvent]:
    """Wrap a poll cycle in a :class:`SegmentRecorder`.

    Caller drives the reader (typically ``reader.tick_once()`` calls)
    inside the ``with`` block. On clean exit this helper assesses the
    bus output and writes the rating + notes onto ``event.quality``
    before the underlying recorder emits the ``HAPPENED`` event.
    Exceptions inside the block propagate normally; the recorder
    emits ``DIDNT_HAPPEN`` and does *not* run the assessor (a crashed
    poll cycle has no meaningful quality grade).

    Args:
        bus_path: Impingement-bus JSONL path. Same path the reader is
            configured to write to.
        expected_inputs: Non-blank chat items the cycle should produce
            impingements for. Drives the ratio thresholds.
        topic_seed: Optional topic seed forwarded to the underlying
            ``SegmentRecorder`` (audience-segmentation breadcrumb).
        log_path: Optional segments.jsonl override; defaults to
            ``$HAPAX_SEGMENTS_LOG`` or
            ``~/hapax-state/segments/segments.jsonl``.

    Yields:
        The mutable :class:`SegmentEvent` the caller can decorate
        further (e.g., ``event.quality.notes += ...``) before the
        block exits.
    """

    with SegmentRecorder(PROGRAMME_ROLE_TAG, topic_seed=topic_seed, log_path=log_path) as event:
        yield event
        result = assess_chat_reactivity(
            bus_path=bus_path,
            expected_inputs=expected_inputs,
        )
        event.quality.chat_reactivity = result.rating
        # Preserve any notes the caller already wrote, then append
        # the assessor's structured summary.
        existing = (event.quality.notes or "").strip()
        suffix = result.notes
        event.quality.notes = f"{existing} | {suffix}" if existing else suffix


# ── Internals ─────────────────────────────────────────────────────────


def _read_chat_records(bus_path: Path) -> list[dict]:
    """Return chat-source impingement records currently on the bus.

    Skips malformed JSON lines silently; the reader appends with
    ``default=str`` so corruption is rare but a single bad line must
    not poison the assessment. Filters to ``source=youtube_chat``
    so non-chat impingements written by other producers don't
    falsely inflate the count when the smoke test reuses a real bus
    path.
    """

    if not bus_path.exists():
        return []
    try:
        text = bus_path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("source") == CHAT_SOURCE_TAG:
            out.append(record)
    return out


def _is_well_formed(record: dict) -> bool:
    """Check the well-formed invariants on one impingement record.

    The invariants mirror outcome 4's consent + sanitisation contract:
    author tokens are hex-only (no plaintext YouTube channelIds), URLs
    are replaced with the ``[link]`` sentinel, control characters are
    stripped, and the visible text fits the sanitiser's length cap.
    """

    content = record.get("content") or {}
    text = content.get("text", "")
    author = content.get("author_token", "")

    if author != "anon":
        if len(author) != 12 or not all(c in "0123456789abcdef" for c in author):
            return False

    if any(ord(c) < 0x20 and c not in {"\n", "\t"} for c in text):
        return False
    if "https://" in text or "http://" in text:
        return False
    return len(text) <= MAX_LENGTH


def _grade_no_inputs(emitted: int) -> tuple[QualityRating, str]:
    """Grade a cycle that fed zero non-blank chat inputs.

    Two interesting outcomes: the bus is empty (POOR — pipeline silent
    and we did not exercise it either, the smoke test is degenerate)
    or the bus has unrelated noise from earlier runs (still POOR —
    this cycle did not contribute observable flow).
    """

    if emitted == 0:
        return (
            QualityRating.POOR,
            "no inputs and no emissions; pipeline did not run",
        )
    return (
        QualityRating.POOR,
        f"no expected inputs but {emitted} chat record(s) on bus — stale state?",
    )


def _grade_with_inputs(*, emitted: int, well_formed: int, expected_inputs: int) -> QualityRating:
    """Apply the operator's 4-level rubric for a cycle with inputs."""

    if emitted == 0:
        return QualityRating.POOR
    emit_ratio = emitted / expected_inputs
    if emit_ratio < EMIT_RATIO_ACCEPTABLE_FLOOR:
        return QualityRating.ACCEPTABLE
    well_formed_ratio = well_formed / emitted
    if emit_ratio >= EMIT_RATIO_EXCELLENT_FLOOR and well_formed_ratio == 1.0:
        return QualityRating.EXCELLENT
    return QualityRating.GOOD
