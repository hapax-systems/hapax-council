"""State contract for the private Operator Now current-state surface."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "HAPAX_OPERATOR_CURRENT_STATE_PATH",
        str(Path.home() / ".cache" / "hapax" / "operator-current-state.json"),
    )
)
DEFAULT_TTL_S = int(os.environ.get("HAPAX_OPERATOR_CURRENT_STATE_TTL_S", "900"))

PredicateFamily = Literal[
    "liveness",
    "health",
    "readiness",
    "authorization",
    "dependency",
    "freshness",
    "release",
    "methodology",
]


class ReadinessBlocker(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    reason: str
    predicate_family: PredicateFamily
    predicate_value: str


class Readiness(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: str = "operator_current_state_render"
    value: Literal["ready", "not_ready", "blocked", "unknown"] = "unknown"
    blockers: list[ReadinessBlocker] = Field(default_factory=list)


class SourceStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    required: bool
    authority: Literal["authoritative", "derived", "advisory", "historical"]
    predicate_family: Literal["freshness"] = "freshness"
    predicate_value: Literal["fresh", "stale", "missing", "unknown"] = "unknown"
    evaluated_at: datetime
    stale_after: datetime
    error: str | None = None


class Conflict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_ref: str
    predicate_value: str
    note: str


class OperatorCurrentStateItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    class_: Literal["know", "do", "decide", "expect", "watch"] = Field(alias="class")
    summary: str
    details: str = ""
    owner: Literal["operator", "lane", "system", "external", "unknown"] = "unknown"
    operator_required: bool = False
    urgency: Literal["immediate", "today", "scheduled", "routine", "blocked", "unknown"] = "unknown"
    due_at: datetime | None = None
    next_check_at: datetime | None = None
    stale_after: datetime
    source_ref: str
    evidence_ref: str
    predicate_family: PredicateFamily
    predicate_value: str
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    escalation_policy: Literal[
        "none",
        "dashboard",
        "relay",
        "kde_connect",
        "operator_interrupt",
    ] = "none"
    privacy_class: Literal["private_operator", "internal_coordination", "public_safe"] = (
        "private_operator"
    )
    status: Literal["active", "pending", "blocked", "stale", "resolved", "unknown"] = "unknown"
    conflicts: list[Conflict] = Field(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        if self.operator_required and self.class_ not in {"do", "decide"}:
            raise ValueError("operator_required=true is only valid for do/decide items")


class Counts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    know: int = 0
    do: int = 0
    decide: int = 0
    expect: int = 0
    watch: int = 0


class PrivacyFilter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    default: Literal["private_operator"] = "private_operator"
    public_projection_authorized: bool = False


class OperatorCurrentState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_version: int = 1
    generated_at: datetime
    generated_by: str = "operator-current-state-render"
    ttl_seconds: int = DEFAULT_TTL_S
    readiness: Readiness
    source_status: dict[str, SourceStatus]
    items: list[OperatorCurrentStateItem]
    counts: Counts
    privacy_filter: PrivacyFilter = Field(default_factory=PrivacyFilter)


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def write_state_atomic(state: OperatorCurrentState, path: Path = DEFAULT_STATE_PATH) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".json.tmp.{os.getpid()}")
        tmp.write_text(state.model_dump_json(by_alias=True), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        log.warning("operator current-state write failed at %s", path, exc_info=True)
        return False
