"""Chat ambient / keyword substrate adapter.

Projects aggregate chat health, salience, and keyword-class counts into
bounded research-vehicle event candidates for the chat ambient and keyword
ward substrates. The adapter accepts aggregate counters only: raw authors,
handles, viewer ids, and per-viewer text fields are rejected before any output
record is built.

Spec: ``docs/superpowers/specs/2026-04-28-livestream-substrate-registry-design.md``
Selection memo: ``config/adapter-tranche-selection-memo.json``
Cc-task: ``chat-ambient-keyword-substrate-adapter``
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from shared.research_vehicle_public_event import (
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
)

CHAT_AMBIENT_SUBSTRATE_ID: Literal["chat_ambient_aggregate"] = "chat_ambient_aggregate"
CHAT_KEYWORD_SUBSTRATE_ID: Literal["chat_keyword_consumer"] = "chat_keyword_consumer"
SUBSTRATE_REFS: tuple[Literal["chat_ambient_aggregate"], Literal["chat_keyword_consumer"]] = (
    CHAT_AMBIENT_SUBSTRATE_ID,
    CHAT_KEYWORD_SUBSTRATE_ID,
)
PRODUCER: Literal["shared.chat_ambient_keyword_substrate_adapter"] = (
    "shared.chat_ambient_keyword_substrate_adapter"
)
TASK_ANCHOR: Literal["chat-ambient-keyword-substrate-adapter"] = (
    "chat-ambient-keyword-substrate-adapter"
)
DEFAULT_FRESHNESS_TTL_S: float = float(
    os.environ.get("HAPAX_CHAT_AMBIENT_KEYWORD_FRESHNESS_TTL_S", "60.0")
)

ProjectionStatus = Literal["candidate", "dry_run"]
RenderTarget = Literal["chat_ambient", "chat_keyword_ward"]
RejectionReason = Literal["producer_absent", "raw_private_field", "invalid_aggregate"]

PrivacyFilterStatus = Literal["aggregate_only", "missing", "failed"]

_ALLOWED_MAPPING_KEYS = frozenset(
    {
        "window_seconds",
        "window_end_ts",
        "message_count_60s",
        "message_rate_per_min",
        "unique_authors_60s",
        "chat_entropy",
        "chat_novelty",
        "high_value_queue_depth",
        "audience_engagement",
        "t4_plus_rate_per_min",
        "unique_t4_plus_authors_60s",
        "t5_rate_per_min",
        "t6_rate_per_min",
        "keyword_class_counts",
        "aggregate_only_privacy_proof",
        "privacy_filter_status",
        "egress_public_claim",
        "health_evidence_refs",
        "provenance_token",
        "source_ref",
        "producer",
        "broadcast_id",
        "programme_id",
    }
)
_RAW_PRIVATE_KEYS = frozenset(
    {
        "author",
        "author_handle",
        "author_id",
        "authors",
        "handle",
        "handles",
        "raw_author",
        "raw_handle",
        "viewer",
        "viewer_id",
        "viewer_handle",
        "viewer_text",
        "per_viewer_text",
        "message_text",
        "message_body",
        "raw_text",
        "text",
        "body",
        "display_name",
        "username",
        "user_id",
    }
)
_KEYWORD_CLASS_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")


@dataclass(frozen=True)
class KeywordClassCount:
    """One aggregate keyword class count, never a raw chat phrase."""

    class_id: str
    count: int


@dataclass(frozen=True)
class ChatAggregateWindow:
    """Aggregate-only chat window consumed by this adapter."""

    window_seconds: float
    window_end_ts: float
    message_count_60s: int
    message_rate_per_min: float
    unique_authors_60s: int
    audience_engagement: float
    t4_plus_rate_per_min: float = 0.0
    unique_t4_plus_authors_60s: int = 0
    t5_rate_per_min: float = 0.0
    t6_rate_per_min: float = 0.0
    chat_entropy: float = 0.0
    chat_novelty: float = 0.0
    high_value_queue_depth: int = 0
    keyword_class_counts: tuple[KeywordClassCount, ...] = ()
    aggregate_only_privacy_proof: bool = False
    privacy_filter_status: PrivacyFilterStatus = "missing"
    egress_public_claim: bool = False
    health_evidence_refs: tuple[str, ...] = ()
    provenance_token: str | None = None
    source_ref: str = "substrate:chat_signals_aggregate"
    producer: str = "agents.studio_compositor.chat_signals"
    broadcast_id: str | None = None
    programme_id: str | None = None


@dataclass(frozen=True)
class ChatAmbientKeywordSubstrateCandidate:
    """One aggregate chat substrate projection record."""

    event: ResearchVehiclePublicEvent
    substrate_id: Literal["chat_ambient_aggregate", "chat_keyword_consumer"]
    render_target: RenderTarget
    projection_status: ProjectionStatus
    source_age_s: float
    dry_run_reasons: tuple[str, ...]
    public_live_claim_allowed: bool
    viewer_visible_claim_allowed: bool
    publication_claim_allowed: bool
    monetization_claim_allowed: Literal[False] = False


@dataclass(frozen=True)
class ChatAmbientKeywordSubstrateRejection:
    """Invalid input rejected before a public-event candidate is built."""

    reason: RejectionReason
    detail: str
    rejected_fields: tuple[str, ...] = ()


def project_chat_ambient_keyword_substrate(
    window: ChatAggregateWindow | Mapping[str, Any] | None,
    *,
    now: float,
    freshness_ttl_s: float = DEFAULT_FRESHNESS_TTL_S,
) -> tuple[
    list[ChatAmbientKeywordSubstrateCandidate],
    list[ChatAmbientKeywordSubstrateRejection],
]:
    """Split an aggregate chat window into substrate candidates/rejections.

    Raw author, handle, viewer-id, or message-text fields produce a rejection
    with field names only. Values are deliberately not copied into the
    rejection detail, provenance, or event payload.
    """

    if window is None:
        return [], [
            ChatAmbientKeywordSubstrateRejection(
                reason="producer_absent",
                detail="chat aggregate producer is absent",
            )
        ]

    if isinstance(window, ChatAggregateWindow):
        aggregate = window
    else:
        aggregate, rejection = _aggregate_from_mapping(window)
        if rejection is not None:
            return [], [rejection]

    source_age_s = max(0.0, now - aggregate.window_end_ts)
    dry_run_reasons = _dry_run_reasons(
        aggregate,
        source_age_s=source_age_s,
        freshness_ttl_s=freshness_ttl_s,
    )
    public_claim_ready = not dry_run_reasons
    status: ProjectionStatus = "candidate" if public_claim_ready else "dry_run"

    candidates = [
        _build_candidate(
            aggregate,
            substrate_id=CHAT_AMBIENT_SUBSTRATE_ID,
            render_target="chat_ambient",
            now=now,
            source_age_s=source_age_s,
            projection_status=status,
            dry_run_reasons=dry_run_reasons,
            public_claim_ready=public_claim_ready,
            freshness_ttl_s=freshness_ttl_s,
        ),
        _build_candidate(
            aggregate,
            substrate_id=CHAT_KEYWORD_SUBSTRATE_ID,
            render_target="chat_keyword_ward",
            now=now,
            source_age_s=source_age_s,
            projection_status=status,
            dry_run_reasons=dry_run_reasons,
            public_claim_ready=public_claim_ready,
            freshness_ttl_s=freshness_ttl_s,
        ),
    ]
    return candidates, []


def _aggregate_from_mapping(
    payload: Mapping[str, Any],
) -> tuple[ChatAggregateWindow, ChatAmbientKeywordSubstrateRejection | None]:
    raw_fields = _raw_private_fields(payload)
    if raw_fields:
        return _empty_window(), ChatAmbientKeywordSubstrateRejection(
            reason="raw_private_field",
            detail="raw author/handle/viewer/text fields are not accepted by chat aggregate adapter",
            rejected_fields=raw_fields,
        )

    unknown = tuple(sorted(str(key) for key in payload if str(key) not in _ALLOWED_MAPPING_KEYS))
    if unknown:
        return _empty_window(), ChatAmbientKeywordSubstrateRejection(
            reason="invalid_aggregate",
            detail="unknown aggregate fields; adapter schema is closed",
            rejected_fields=unknown,
        )

    try:
        aggregate = ChatAggregateWindow(
            window_seconds=_float(payload, "window_seconds", default=60.0, minimum=0.001),
            window_end_ts=_float(payload, "window_end_ts", required=True),
            message_count_60s=_int(payload, "message_count_60s", default=0),
            message_rate_per_min=_float(payload, "message_rate_per_min", default=0.0),
            unique_authors_60s=_int(payload, "unique_authors_60s", default=0),
            audience_engagement=_bounded_float(payload, "audience_engagement", default=0.0),
            t4_plus_rate_per_min=_float(payload, "t4_plus_rate_per_min", default=0.0),
            unique_t4_plus_authors_60s=_int(payload, "unique_t4_plus_authors_60s", default=0),
            t5_rate_per_min=_float(payload, "t5_rate_per_min", default=0.0),
            t6_rate_per_min=_float(payload, "t6_rate_per_min", default=0.0),
            chat_entropy=_float(payload, "chat_entropy", default=0.0),
            chat_novelty=_bounded_float(payload, "chat_novelty", default=0.0),
            high_value_queue_depth=_int(payload, "high_value_queue_depth", default=0),
            keyword_class_counts=_keyword_counts(payload.get("keyword_class_counts", {})),
            aggregate_only_privacy_proof=bool(payload.get("aggregate_only_privacy_proof", False)),
            privacy_filter_status=_privacy_filter_status(payload.get("privacy_filter_status")),
            egress_public_claim=bool(payload.get("egress_public_claim", False)),
            health_evidence_refs=_string_tuple(payload.get("health_evidence_refs", ())),
            provenance_token=_optional_string(payload.get("provenance_token")),
            source_ref=_string(payload.get("source_ref", "substrate:chat_signals_aggregate")),
            producer=_string(payload.get("producer", "agents.studio_compositor.chat_signals")),
            broadcast_id=_optional_string(payload.get("broadcast_id")),
            programme_id=_optional_string(payload.get("programme_id")),
        )
    except (TypeError, ValueError) as exc:
        return _empty_window(), ChatAmbientKeywordSubstrateRejection(
            reason="invalid_aggregate",
            detail=str(exc),
        )
    return aggregate, None


def _raw_private_fields(payload: Mapping[str, Any]) -> tuple[str, ...]:
    fields: list[str] = []
    for key in payload:
        key_s = str(key)
        key_l = key_s.lower()
        if key_l in _RAW_PRIVATE_KEYS:
            fields.append(key_s)
    return tuple(sorted(fields))


def _dry_run_reasons(
    aggregate: ChatAggregateWindow,
    *,
    source_age_s: float,
    freshness_ttl_s: float,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if source_age_s > freshness_ttl_s:
        reasons.append(
            f"stale_aggregate_window:age_s={source_age_s:.2f}>ttl_s={freshness_ttl_s:.2f}"
        )
    if not aggregate.aggregate_only_privacy_proof:
        reasons.append("missing_aggregate_only_privacy_proof")
    if aggregate.privacy_filter_status != "aggregate_only":
        reasons.append(f"privacy_filter_status:{aggregate.privacy_filter_status}")
    if not aggregate.egress_public_claim:
        reasons.append("missing_public_egress_evidence")
    if not aggregate.health_evidence_refs:
        reasons.append("missing_chat_aggregate_health_evidence")
    if not aggregate.provenance_token:
        reasons.append("missing_provenance_token")
    return tuple(reasons)


def _build_candidate(
    aggregate: ChatAggregateWindow,
    *,
    substrate_id: Literal["chat_ambient_aggregate", "chat_keyword_consumer"],
    render_target: RenderTarget,
    now: float,
    source_age_s: float,
    projection_status: ProjectionStatus,
    dry_run_reasons: tuple[str, ...],
    public_claim_ready: bool,
    freshness_ttl_s: float,
) -> ChatAmbientKeywordSubstrateCandidate:
    token = _event_token(aggregate, substrate_id)
    event = _build_event(
        aggregate,
        substrate_id=substrate_id,
        render_target=render_target,
        token=token,
        now=now,
        source_age_s=source_age_s,
        freshness_ttl_s=freshness_ttl_s,
        dry_run_reasons=dry_run_reasons,
        public_claim_ready=public_claim_ready,
    )
    return ChatAmbientKeywordSubstrateCandidate(
        event=event,
        substrate_id=substrate_id,
        render_target=render_target,
        projection_status=projection_status,
        source_age_s=source_age_s,
        dry_run_reasons=dry_run_reasons,
        public_live_claim_allowed=public_claim_ready,
        viewer_visible_claim_allowed=public_claim_ready,
        publication_claim_allowed=public_claim_ready,
    )


def _build_event(
    aggregate: ChatAggregateWindow,
    *,
    substrate_id: str,
    render_target: RenderTarget,
    token: str,
    now: float,
    source_age_s: float,
    freshness_ttl_s: float,
    dry_run_reasons: tuple[str, ...],
    public_claim_ready: bool,
) -> ResearchVehiclePublicEvent:
    evidence_ref = f"chat_aggregate:{substrate_id}:{token[:16]}"
    dry_run_reason = ";".join(dry_run_reasons) if dry_run_reasons else None
    return ResearchVehiclePublicEvent(
        event_id=f"chat.aggregate:{substrate_id}:{token}",
        event_type="chronicle.high_salience",
        occurred_at=_iso_from_epoch(aggregate.window_end_ts),
        broadcast_id=aggregate.broadcast_id,
        programme_id=aggregate.programme_id,
        condition_id=None,
        source=PublicEventSource(
            producer=PRODUCER,
            substrate_id=substrate_id,
            task_anchor=TASK_ANCHOR,
            evidence_ref=evidence_ref,
            freshness_ref=f"chat_aggregate.age_s={source_age_s:.2f};ttl_s={freshness_ttl_s:.2f}",
        ),
        salience=_salience_for(aggregate, render_target),
        state_kind="research_observation",
        rights_class="platform_embedded",
        privacy_class="aggregate_only",
        provenance=PublicEventProvenance(
            token=aggregate.provenance_token or token,
            generated_at=_iso_from_epoch(now),
            producer=PRODUCER,
            evidence_refs=[
                aggregate.source_ref,
                f"upstream_producer:{aggregate.producer}",
                evidence_ref,
                f"substrate:{substrate_id}",
                f"render_target:{render_target}",
                f"privacy_filter_status:{aggregate.privacy_filter_status}",
                f"aggregate_only_privacy_proof:{aggregate.aggregate_only_privacy_proof}",
                f"egress_public_claim:{aggregate.egress_public_claim}",
                f"message_count_60s:{aggregate.message_count_60s}",
                f"unique_authors_60s:{aggregate.unique_authors_60s}",
                f"keyword_class_counts:{_keyword_counts_ref(aggregate.keyword_class_counts)}",
                *[f"health:{ref}" for ref in aggregate.health_evidence_refs],
                *[f"dry_run:{reason}" for reason in dry_run_reasons],
            ],
            rights_basis=(
                "aggregate chat metrics only; no raw authors, handles, viewer ids, or "
                "message text retained"
            ),
            citation_refs=[],
        ),
        public_url=None,
        frame_ref=None,
        chapter_ref=None,
        attribution_refs=[],
        surface_policy=PublicEventSurfacePolicy(
            allowed_surfaces=["health", "replay", "archive"] if public_claim_ready else ["health"],
            denied_surfaces=[],
            claim_live=public_claim_ready,
            claim_archive=public_claim_ready,
            claim_monetizable=False,
            requires_egress_public_claim=True,
            requires_audio_safe=False,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key=f"chat.aggregate.{substrate_id}",
            redaction_policy="aggregate_only",
            fallback_action="hold" if public_claim_ready else "dry_run",
            dry_run_reason=dry_run_reason,
        ),
    )


def _event_token(aggregate: ChatAggregateWindow, substrate_id: str) -> str:
    payload = {
        "substrate_id": substrate_id,
        "window_end_ts": round(aggregate.window_end_ts, 3),
        "message_count_60s": aggregate.message_count_60s,
        "keyword_class_counts": [
            {"class_id": item.class_id, "count": item.count}
            for item in aggregate.keyword_class_counts
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _salience_for(aggregate: ChatAggregateWindow, render_target: RenderTarget) -> float:
    base = aggregate.audience_engagement
    if render_target == "chat_keyword_ward":
        keyword_total = sum(item.count for item in aggregate.keyword_class_counts)
        keyword_component = min(1.0, keyword_total / 12.0)
        base = max(
            base,
            keyword_component,
            min(1.0, (aggregate.t5_rate_per_min + aggregate.t6_rate_per_min) / 6.0),
        )
    return round(max(0.0, min(1.0, base)), 3)


def _keyword_counts_ref(items: tuple[KeywordClassCount, ...]) -> str:
    if not items:
        return "none"
    return ",".join(f"{item.class_id}={item.count}" for item in items)


def _keyword_counts(value: object) -> tuple[KeywordClassCount, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, Mapping):
        raise TypeError("keyword_class_counts must be an aggregate mapping")
    out: list[KeywordClassCount] = []
    for raw_key, raw_count in value.items():
        class_id = str(raw_key)
        if not _KEYWORD_CLASS_RE.match(class_id):
            raise ValueError(f"invalid keyword class id: {class_id!r}")
        count = _int_value(raw_count, f"keyword_class_counts.{class_id}")
        out.append(KeywordClassCount(class_id=class_id, count=count))
    return tuple(sorted(out, key=lambda item: item.class_id))


def _privacy_filter_status(value: object) -> PrivacyFilterStatus:
    if value is None:
        return "missing"
    status = str(value)
    if status not in {"aggregate_only", "missing", "failed"}:
        raise ValueError(f"invalid privacy_filter_status: {status!r}")
    return status  # type: ignore[return-value]


def _float(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: float | None = None,
    required: bool = False,
    minimum: float = 0.0,
) -> float:
    if key not in payload:
        if required or default is None:
            raise ValueError(f"missing required aggregate field: {key}")
        return default
    value = payload[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{key} must be numeric")
    out = float(value)
    if out < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    return out


def _bounded_float(payload: Mapping[str, Any], key: str, *, default: float) -> float:
    value = _float(payload, key, default=default)
    if value > 1.0:
        raise ValueError(f"{key} must be <= 1.0")
    return value


def _int(payload: Mapping[str, Any], key: str, *, default: int) -> int:
    if key not in payload:
        return default
    return _int_value(payload[key], key)


def _int_value(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    if value < 0:
        raise ValueError(f"{label} must be >= 0")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError("aggregate string fields must be non-empty strings")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Iterable):
        raise TypeError("health_evidence_refs must be a string or iterable of strings")
    out: list[str] = []
    for item in value:
        out.append(_string(item))
    return tuple(out)


def _empty_window() -> ChatAggregateWindow:
    return ChatAggregateWindow(
        window_seconds=60.0,
        window_end_ts=0.0,
        message_count_60s=0,
        message_rate_per_min=0.0,
        unique_authors_60s=0,
        audience_engagement=0.0,
    )


def _iso_from_epoch(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


__all__ = [
    "CHAT_AMBIENT_SUBSTRATE_ID",
    "CHAT_KEYWORD_SUBSTRATE_ID",
    "DEFAULT_FRESHNESS_TTL_S",
    "PRODUCER",
    "SUBSTRATE_REFS",
    "TASK_ANCHOR",
    "ChatAggregateWindow",
    "ChatAmbientKeywordSubstrateCandidate",
    "ChatAmbientKeywordSubstrateRejection",
    "KeywordClassCount",
    "ProjectionStatus",
    "RejectionReason",
    "RenderTarget",
    "project_chat_ambient_keyword_substrate",
]
