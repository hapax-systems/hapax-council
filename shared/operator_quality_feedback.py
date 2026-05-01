"""Private operator quality-rating JSONL sink for SS2/QM5 calibration.

The records written here are a private research signal. They are not public
claims, chat messages, attribution records, or viewer-facing feedback.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

QUALITY_FEEDBACK_PATH_ENV = "HAPAX_OPERATOR_QUALITY_FEEDBACK_PATH"
DEFAULT_QUALITY_FEEDBACK_PATH = Path.home() / "hapax-state/operator-quality-feedback/ratings.jsonl"
QUALITY_FEEDBACK_MAX_NOTE_LEN = 1000
QUALITY_FEEDBACK_MAX_LINE_BYTES = 32 * 1024

RatingAxis = Literal[
    "overall",
    "substantive",
    "grounded",
    "stimmung_coherence",
    "programme_respecting",
    "listenable",
]
SourceSurface = Literal["cli", "streamdeck", "kdeconnect", "voice", "test"]

RATING_AXES: tuple[str, ...] = (
    "overall",
    "substantive",
    "grounded",
    "stimmung_coherence",
    "programme_respecting",
    "listenable",
)
SOURCE_SURFACES: tuple[str, ...] = ("cli", "streamdeck", "kdeconnect", "voice", "test")

log = logging.getLogger(__name__)


class OperatorQualityRatingEvent(BaseModel):
    """One private subjective quality rating from the operator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_type: Literal["operator_quality_rating"] = "operator_quality_rating"
    event_id: str = Field(default_factory=lambda: f"oqr-{uuid.uuid4().hex[:12]}")
    idempotency_key: str
    occurred_at: datetime
    rating: int = Field(..., ge=1, le=5)
    rating_axis: RatingAxis = "overall"
    rating_scale: Literal["1_5_subjective_quality"] = "1_5_subjective_quality"
    source_surface: SourceSurface = "cli"
    programme_id: str | None = None
    condition_id: str | None = None
    run_id: str | None = None
    emission_ref: str | None = None
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    note: str | None = Field(default=None, max_length=QUALITY_FEEDBACK_MAX_NOTE_LEN)
    handoff_refs: tuple[str, ...] = ("ytb-QM1", "ytb-SS2", "ytb-SS3")

    @field_validator("rating", mode="before")
    @classmethod
    def _rating_must_not_be_bool(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("rating must be an integer 1..5, not a bool")
        return value

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include timezone information")
        return value.astimezone(UTC)

    @field_validator(
        "event_id",
        "idempotency_key",
        "programme_id",
        "condition_id",
        "run_id",
        "emission_ref",
        "note",
        mode="before",
    )
    @classmethod
    def _strip_optional_strings(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("event_id", "idempotency_key")
    @classmethod
    def _required_strings_non_empty(cls, value: str | None) -> str:
        if not value:
            raise ValueError("event_id and idempotency_key must be non-empty")
        return value

    @field_validator("evidence_refs", "handoff_refs")
    @classmethod
    def _refs_non_empty(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("reference entries must be non-empty strings")
            cleaned.append(stripped)
        return tuple(cleaned)


def quality_feedback_path() -> Path:
    """Return the canonical JSONL sink path, honoring the test/operator override."""

    override = os.environ.get(QUALITY_FEEDBACK_PATH_ENV)
    if override:
        return Path(override).expanduser()
    return DEFAULT_QUALITY_FEEDBACK_PATH


def parse_occurred_at(value: datetime | str | None) -> datetime:
    """Parse an operator-supplied timestamp, defaulting to current UTC."""

    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_operator_quality_rating(
    *,
    rating: int,
    rating_axis: str = "overall",
    source_surface: str = "cli",
    occurred_at: datetime | str | None = None,
    event_id: str | None = None,
    idempotency_key: str | None = None,
    programme_id: str | None = None,
    condition_id: str | None = None,
    run_id: str | None = None,
    emission_ref: str | None = None,
    evidence_refs: Sequence[str] = (),
    note: str | None = None,
) -> OperatorQualityRatingEvent:
    """Build one validated event without writing it."""

    resolved_event_id = event_id or f"oqr-{uuid.uuid4().hex[:12]}"
    return OperatorQualityRatingEvent(
        event_id=resolved_event_id,
        idempotency_key=idempotency_key or resolved_event_id,
        occurred_at=parse_occurred_at(occurred_at),
        rating=rating,
        rating_axis=rating_axis,
        source_surface=source_surface,
        programme_id=programme_id,
        condition_id=condition_id,
        run_id=run_id,
        emission_ref=emission_ref,
        evidence_refs=tuple(evidence_refs),
        note=note,
    )


def build_operator_quality_rating_from_args(
    args: dict[str, Any],
    *,
    default_source_surface: str = "streamdeck",
) -> OperatorQualityRatingEvent:
    """Build an event from command-registry style args."""

    if "rating" not in args:
        raise ValueError("operator.quality.rate requires rating")

    return build_operator_quality_rating(
        rating=args["rating"],
        rating_axis=_optional_str(args.get("rating_axis")) or "overall",
        source_surface=(
            _optional_str(args.get("source_surface"))
            or _optional_str(args.get("surface"))
            or default_source_surface
        ),
        occurred_at=args.get("occurred_at"),
        event_id=_optional_str(args.get("event_id")),
        idempotency_key=_optional_str(args.get("idempotency_key")),
        programme_id=_optional_str(args.get("programme_id")),
        condition_id=_optional_str(args.get("condition_id")),
        run_id=_optional_str(args.get("run_id")),
        emission_ref=_optional_str(args.get("emission_ref")),
        evidence_refs=_normalise_refs(args.get("evidence_refs", args.get("evidence_ref", ()))),
        note=_optional_str(args.get("note")),
    )


def append_operator_quality_rating(
    event: OperatorQualityRatingEvent,
    *,
    path: Path | None = None,
) -> OperatorQualityRatingEvent:
    """Append one event to the private JSONL sink with O_APPEND semantics."""

    target = path if path is not None else quality_feedback_path()
    line = event.model_dump_json() + "\n"
    encoded = line.encode("utf-8")
    if len(encoded) > QUALITY_FEEDBACK_MAX_LINE_BYTES:
        raise ValueError(
            f"operator quality rating line exceeds {QUALITY_FEEDBACK_MAX_LINE_BYTES} bytes"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, encoded)
    finally:
        os.close(fd)
    return event


def append_operator_quality_rating_from_args(
    args: dict[str, Any],
    *,
    path: Path | None = None,
    default_source_surface: str = "streamdeck",
) -> OperatorQualityRatingEvent:
    """Build and append one command-registry quality rating event."""

    event = build_operator_quality_rating_from_args(
        args,
        default_source_surface=default_source_surface,
    )
    return append_operator_quality_rating(event, path=path)


def iter_operator_quality_ratings(
    *, path: Path | None = None
) -> Iterator[OperatorQualityRatingEvent]:
    """Yield parseable quality-rating events from the JSONL sink."""

    target = path if path is not None else quality_feedback_path()
    if not target.exists():
        return
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        log.debug("failed to read operator quality feedback path %s", target, exc_info=True)
        return

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            yield OperatorQualityRatingEvent.model_validate_json(stripped)
        except Exception:
            log.debug("malformed operator quality feedback line skipped: %s", stripped[:80])
            continue


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _normalise_refs(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    raise ValueError(f"evidence_refs must be a string or sequence, got {type(value).__name__}")
