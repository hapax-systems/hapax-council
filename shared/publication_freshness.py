"""Witness-only freshness envelopes for public publication surfaces.

The publication bus records dispatch attempts and per-surface outcomes. This
module records a stricter question: whether a public surface was independently
read back, whether that readback is still fresh, and whether current public
claims must be held until a correction or refresh lands.

Freshness rows are evidence only. They do not grant truth, rights, privacy,
egress, support, monetization, or research-validity authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.github_publication_log import GitHubPublicationLogEvent

DEFAULT_FRESHNESS_EVENTS = Path.home() / "hapax-state/publication/freshness-events.jsonl"
DEFAULT_FRESHNESS_STATE = Path.home() / "hapax-state/publication/freshness-state.json"
PRODUCER = "shared.publication_freshness"
CLAIM_CEILING = "freshness_witness_only"
ANTI_OVERCLAIM_REASON = (
    "freshness_witness_does_not_grant_truth_rights_privacy_egress_support_"
    "monetization_or_research_validity"
)
DEFAULT_GITHUB_TTL_S = 1_800

type PublicationFreshnessEventType = Literal[
    "publication.intent_registered",
    "publication.rendered",
    "publication.dispatch_attempted",
    "publication.surface_readback",
    "publication.claim.validated",
    "publication.freshness_assessed",
    "publication.surface.hold",
    "publication.correction_required",
    "publication.withdrawn",
    "publication.activation_bound",
]

type PublicationFreshnessResult = Literal[
    "match",
    "observed",
    "mismatch",
    "missing",
    "stale",
    "blocked",
    "rate_limited",
    "auth_error",
    "held",
    "unknown",
]

type PublicationFreshnessStaleBehavior = Literal[
    "fail_closed",
    "hold_for_review",
    "mark_unverified",
    "correction_task",
    "no_public_claim",
]

type PublicationFanoutDecision = Literal[
    "allow",
    "redact",
    "hold",
    "deny",
    "not_publication_fanout",
]

BLOCKING_RESULTS: frozenset[PublicationFreshnessResult] = frozenset(
    {"mismatch", "missing", "stale", "blocked", "rate_limited", "auth_error"}
)


class PublicationFreshnessModel(BaseModel):
    """Strict immutable base for public-surface freshness records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PublicSurfaceFreshnessEnvelope(PublicationFreshnessModel):
    """Machine-readable freshness envelope for one public surface."""

    schema_version: Literal[1] = 1
    surface_id: str = Field(min_length=1)
    surface_type: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    target_ref: str | None = None
    source_of_truth: str = Field(min_length=1)
    owner_task: str = ""
    audience_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    source_hash: str | None = None
    rendered_hash: str | None = None
    published_hash: str | None = None
    readback_hash: str | None = None
    license_posture: str = ""
    claim_ceiling: str = ""
    implementation_maturity: str = ""
    privacy_rights_state: str = ""
    style_register: str = ""
    fanout_decision: PublicationFanoutDecision = "not_publication_fanout"
    checked_at: str
    ttl_s: int = Field(gt=0)
    expires_at: str
    freshness_result: PublicationFreshnessResult = "unknown"
    stale_behavior: PublicationFreshnessStaleBehavior = "hold_for_review"
    blocks: tuple[str, ...] = ()
    truth_authority: Literal[False] = False
    rights_authority: Literal[False] = False
    privacy_authority: Literal[False] = False
    egress_authority: Literal[False] = False
    support_authority: Literal[False] = False
    monetization_authority: Literal[False] = False
    research_validity_authority: Literal[False] = False
    value_braid_authority: Literal["freshness_witness_only"] = "freshness_witness_only"

    @model_validator(mode="after")
    def _hash_claims_are_coherent(self) -> PublicSurfaceFreshnessEnvelope:
        expected_expires_at = parse_iso_z(self.checked_at) + timedelta(seconds=self.ttl_s)
        if self.expires_datetime() != expected_expires_at:
            raise ValueError("expires_at must equal checked_at plus ttl_s")
        if self.freshness_result == "match" and not self.readback_hash:
            raise ValueError("match freshness requires a readback_hash")
        if (
            self.freshness_result == "match"
            and self.rendered_hash
            and self.readback_hash
            and self.rendered_hash != self.readback_hash
        ):
            raise ValueError("match freshness cannot carry unequal rendered/readback hashes")
        return self

    def expires_datetime(self) -> datetime:
        """Return the envelope expiry time as a timezone-aware datetime."""

        return parse_iso_z(self.expires_at)

    def is_expired(self, now: datetime | str | None = None) -> bool:
        """Return whether the envelope is beyond its declared freshness TTL."""

        current = parse_iso_z(now) if isinstance(now, str) else now
        current = current or datetime.now(tz=UTC)
        return current > self.expires_datetime()

    @property
    def blocks_public_current(self) -> bool:
        """Whether this envelope blocks public-current/release claims."""

        return self.freshness_result in BLOCKING_RESULTS


class PublicationFreshnessEvent(PublicationFreshnessModel):
    """Append-only publication freshness ledger event."""

    schema_version: Literal[1] = 1
    event_id: str = Field(pattern=r"^pubfresh:[a-z0-9_.:-]+$")
    event_type: PublicationFreshnessEventType
    generated_at: str
    occurred_at: str
    producer: Literal["shared.publication_freshness"] = PRODUCER
    surface_id: str = Field(min_length=1)
    surface_type: str = Field(min_length=1)
    envelope_hash: str = Field(min_length=16)
    source_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    result: PublicationFreshnessResult
    freshness_slo_s: int = Field(gt=0)
    expires_at: str
    blocks: tuple[str, ...] = ()
    notes: tuple[str, ...] = Field(default_factory=lambda: (ANTI_OVERCLAIM_REASON,))
    truth_authority: Literal[False] = False
    rights_authority: Literal[False] = False
    privacy_authority: Literal[False] = False
    egress_authority: Literal[False] = False
    support_authority: Literal[False] = False
    monetization_authority: Literal[False] = False
    research_validity_authority: Literal[False] = False
    value_braid_authority: Literal["freshness_witness_only"] = "freshness_witness_only"

    def to_json_line(self) -> str:
        """Serialize as a deterministic JSONL line."""

        return json.dumps(self.model_dump(mode="json"), sort_keys=True) + "\n"


class PublicationFreshnessSnapshot(PublicationFreshnessModel):
    """Derived current-state snapshot from freshness envelopes."""

    schema_version: Literal[1] = 1
    generated_at: str
    producer: Literal["shared.publication_freshness"] = PRODUCER
    claim_ceiling: Literal["freshness_witness_only"] = CLAIM_CEILING
    envelopes: tuple[PublicSurfaceFreshnessEnvelope, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    anti_overclaim: tuple[str, ...] = (ANTI_OVERCLAIM_REASON,)


def github_event_to_freshness_envelope(
    event: GitHubPublicationLogEvent,
    *,
    checked_at: str | None = None,
    ttl_s: int = DEFAULT_GITHUB_TTL_S,
    owner_task: str = "github-publication-log-value-braid-adapter",
) -> PublicSurfaceFreshnessEnvelope:
    """Build a freshness envelope from a witnessed GitHub publication row."""

    checked = checked_at or isoformat_z(datetime.now(tz=UTC))
    checked_dt = parse_iso_z(checked)
    expires = isoformat_z(checked_dt + timedelta(seconds=ttl_s))
    result: PublicationFreshnessResult
    if event.publication_state == "public":
        result = "match" if event.content_sha else "observed"
    elif event.publication_state == "missing_or_private":
        result = "missing"
    elif event.publication_state in {"withdrawn", "refusal"}:
        result = "held"
    elif event.publication_state == "correction":
        result = "mismatch"
    else:
        result = "unknown"
    blocks = _default_blocks(result)
    return PublicSurfaceFreshnessEnvelope(
        surface_id=event.surface_id,
        surface_type=f"github.{event.surface}",
        source_ref=event.source_refs[0],
        target_ref=event.live_url or event.ref,
        source_of_truth="github_public_surface_report",
        owner_task=owner_task,
        evidence_refs=event.evidence_refs,
        source_hash=event.commit_sha,
        rendered_hash=event.content_sha,
        published_hash=event.content_sha,
        readback_hash=event.content_sha,
        claim_ceiling=event.claim_ceiling,
        implementation_maturity="witnessed_publication_state",
        privacy_rights_state="witness_only",
        style_register="not_applicable",
        checked_at=checked,
        ttl_s=ttl_s,
        expires_at=expires,
        freshness_result=result,
        stale_behavior="hold_for_review",
        blocks=blocks,
    )


def github_events_to_freshness_envelopes(
    events: tuple[GitHubPublicationLogEvent, ...],
    *,
    checked_at: str | None = None,
    ttl_s: int = DEFAULT_GITHUB_TTL_S,
) -> tuple[PublicSurfaceFreshnessEnvelope, ...]:
    """Convert GitHub publication witness rows into freshness envelopes."""

    return tuple(
        github_event_to_freshness_envelope(event, checked_at=checked_at, ttl_s=ttl_s)
        for event in events
    )


def assess_public_surface_freshness(
    envelope: PublicSurfaceFreshnessEnvelope,
    *,
    now: datetime | str | None = None,
) -> PublicSurfaceFreshnessEnvelope:
    """Return an envelope with a deterministic freshness result and blockers."""

    current = parse_iso_z(now) if isinstance(now, str) else now
    result = envelope.freshness_result
    if envelope.is_expired(current):
        result = "stale"
    elif result in BLOCKING_RESULTS:
        result = envelope.freshness_result
    elif envelope.rendered_hash and envelope.readback_hash:
        result = "match" if envelope.rendered_hash == envelope.readback_hash else "mismatch"
    elif envelope.readback_hash:
        result = "observed"
    elif result == "unknown":
        result = "missing"

    blocks = envelope.blocks or _default_blocks(result)
    if result not in BLOCKING_RESULTS:
        blocks = ()
    return envelope.model_copy(update={"freshness_result": result, "blocks": blocks})


def build_publication_freshness_event(
    envelope: PublicSurfaceFreshnessEnvelope,
    *,
    event_type: PublicationFreshnessEventType = "publication.freshness_assessed",
    generated_at: str | None = None,
    occurred_at: str | None = None,
) -> PublicationFreshnessEvent:
    """Build one append-only freshness ledger event from an assessed envelope."""

    generated = generated_at or isoformat_z(datetime.now(tz=UTC))
    occurred = occurred_at or generated
    envelope_hash = digest_json(envelope.model_dump(mode="json"))
    return PublicationFreshnessEvent(
        event_id=publication_freshness_event_id(
            surface_id=envelope.surface_id,
            event_type=event_type,
            envelope_hash=envelope_hash,
            occurred_at=occurred,
        ),
        event_type=event_type,
        generated_at=generated,
        occurred_at=occurred,
        surface_id=envelope.surface_id,
        surface_type=envelope.surface_type,
        envelope_hash=envelope_hash,
        source_refs=(envelope.source_ref,),
        evidence_refs=envelope.evidence_refs,
        result=envelope.freshness_result,
        freshness_slo_s=envelope.ttl_s,
        expires_at=envelope.expires_at,
        blocks=envelope.blocks,
    )


def build_publication_freshness_snapshot(
    envelopes: tuple[PublicSurfaceFreshnessEnvelope, ...],
    *,
    generated_at: str | None = None,
) -> PublicationFreshnessSnapshot:
    """Build the derived current-state snapshot from freshness envelopes."""

    generated = generated_at or isoformat_z(datetime.now(tz=UTC))
    assessed = tuple(
        assess_public_surface_freshness(envelope, now=generated) for envelope in envelopes
    )
    blockers = tuple(
        f"{envelope.surface_id}:{envelope.freshness_result}:{','.join(envelope.blocks)}"
        for envelope in assessed
        if envelope.blocks_public_current
    )
    warnings = tuple(
        f"{envelope.surface_id}:unknown_freshness"
        for envelope in assessed
        if envelope.freshness_result == "unknown"
    )
    return PublicationFreshnessSnapshot(
        generated_at=generated,
        envelopes=assessed,
        blockers=blockers,
        warnings=warnings,
    )


def write_publication_freshness_events(
    events: tuple[PublicationFreshnessEvent, ...],
    *,
    log_path: Path = DEFAULT_FRESHNESS_EVENTS,
    dry_run: bool = False,
) -> tuple[str, ...]:
    """Serialize freshness events and optionally append new rows to the JSONL ledger."""

    lines = tuple(event.to_json_line() for event in events)
    if dry_run:
        return lines
    existing_ids = _existing_publication_freshness_event_ids(log_path)
    append_lines: list[str] = []
    for event, line in zip(events, lines, strict=True):
        if event.event_id in existing_ids:
            continue
        existing_ids.add(event.event_id)
        append_lines.append(line)
    if not append_lines:
        return ()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.writelines(append_lines)
    return tuple(append_lines)


def write_publication_freshness_snapshot(
    snapshot: PublicationFreshnessSnapshot,
    *,
    path: Path = DEFAULT_FRESHNESS_STATE,
    dry_run: bool = False,
) -> str:
    """Serialize a freshness snapshot and optionally write it as JSON."""

    text = json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    if dry_run:
        return text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def _existing_publication_freshness_event_ids(log_path: Path) -> set[str]:
    if not log_path.exists():
        return set()
    event_ids: set[str] = set()
    for line_number, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "publication freshness ledger is malformed at "
                f"{log_path}:{line_number}: invalid JSON; next action: repair or quarantine "
                "the ledger before appending freshness evidence"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(
                "publication freshness ledger is malformed at "
                f"{log_path}:{line_number}: expected JSON object; next action: repair or "
                "quarantine the ledger before appending freshness evidence"
            )
        event_id = payload.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError(
                "publication freshness ledger is malformed at "
                f"{log_path}:{line_number}: missing event_id; next action: repair or "
                "quarantine the ledger before appending freshness evidence"
            )
        event_ids.add(event_id)
    return event_ids


def publication_freshness_event_id(
    *,
    surface_id: str,
    event_type: PublicationFreshnessEventType,
    envelope_hash: str,
    occurred_at: str,
) -> str:
    """Return a stable schema-safe freshness event id."""

    return (
        f"pubfresh:{slug(event_type)}:{slug(surface_id)}:{slug(occurred_at)}:{envelope_hash[:16]}"
    )


def digest_json(payload: Any) -> str:
    """Return a stable sha256 digest for a JSON-like payload."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def parse_iso_z(value: datetime | str | None) -> datetime:
    """Parse UTC ISO strings with optional ``Z`` suffix."""

    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if value is None:
        return datetime.now(tz=UTC)
    normalised = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalised).astimezone(UTC)


def isoformat_z(value: datetime) -> str:
    """Return a UTC RFC3339 timestamp with ``Z`` suffix."""

    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slug(value: str) -> str:
    """Normalize an event-id component."""

    text = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", value.strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def _default_blocks(result: PublicationFreshnessResult) -> tuple[str, ...]:
    if result in BLOCKING_RESULTS:
        return ("public_current", "release_authorized")
    return ()


__all__ = [
    "ANTI_OVERCLAIM_REASON",
    "BLOCKING_RESULTS",
    "CLAIM_CEILING",
    "DEFAULT_FRESHNESS_EVENTS",
    "DEFAULT_FRESHNESS_STATE",
    "DEFAULT_GITHUB_TTL_S",
    "PRODUCER",
    "PublicationFreshnessEvent",
    "PublicationFreshnessSnapshot",
    "PublicSurfaceFreshnessEnvelope",
    "assess_public_surface_freshness",
    "build_publication_freshness_event",
    "build_publication_freshness_snapshot",
    "digest_json",
    "github_event_to_freshness_envelope",
    "github_events_to_freshness_envelopes",
    "publication_freshness_event_id",
    "write_publication_freshness_events",
    "write_publication_freshness_snapshot",
]
