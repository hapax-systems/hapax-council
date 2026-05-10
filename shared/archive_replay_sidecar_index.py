"""Durable archive/replay sidecar index contracts.

The archive replay public-event adapter decides whether one HLS sidecar can
become a public replay event. This module is the durable read model downstream
conversion, dataset, grant, demo, and artifact surfaces can cite without
walking raw archive directories.

The index is intentionally conservative: public replay claims are allowed only
when archive refs, rights/privacy, provenance, and verification state all pass.
Blocked, private, and dry-run entries remain addressable for accounting, but
they cannot be promoted into public-safe replay objects by downstream surfaces.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal, Self

from prometheus_client import REGISTRY, CollectorRegistry, Counter
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.research_vehicle_public_event import PrivacyClass, RightsClass

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_REPLAY_SIDECAR_INDEX_FIXTURES = (
    REPO_ROOT / "config" / "archive-replay-sidecar-index-fixtures.json"
)

TASK_ANCHOR = "archive-replay-sidecar-index"
PRODUCER = "shared.archive_replay_sidecar_index"

REQUIRED_ARTIFACT_KINDS = frozenset(
    {
        "public_safe_run",
        "refusal_artifact",
        "correction_artifact",
        "rights_blocked_run",
    }
)
REQUIRED_INDEX_STATES = frozenset({"blocked", "private", "dry-run", "public"})
REQUIRED_METRIC_STATES = frozenset({"available", "blocked", "stale", "public_safe"})
FAIL_CLOSED_POLICY = {
    "missing_archive_refs_allow_public_replay": False,
    "stale_archive_refs_allow_public_replay": False,
    "private_archive_refs_allow_public_replay": False,
    "rights_held_archive_refs_allow_public_replay": False,
    "unverified_archive_refs_allow_public_replay": False,
    "non_public_index_state_allows_public_replay": False,
}
PUBLIC_SAFE_RIGHTS: frozenset[RightsClass] = frozenset(
    {"operator_original", "operator_controlled", "third_party_attributed"}
)
PUBLIC_SAFE_PRIVACY: frozenset[PrivacyClass] = frozenset({"public_safe", "aggregate_only"})

type ArchiveReplayIndexState = Literal["blocked", "private", "dry-run", "public"]
type ArchiveReplayArtifactKind = Literal[
    "public_safe_run",
    "refusal_artifact",
    "correction_artifact",
    "rights_blocked_run",
]
type ArchiveRefState = Literal[
    "available", "missing", "stale", "private", "rights_held", "unverified"
]
type ReplayObjectMetricState = Literal["available", "blocked", "stale", "public_safe"]

_ARCHIVE_REF_BLOCKERS: dict[ArchiveRefState, str] = {
    "missing": "archive_refs_missing",
    "stale": "archive_refs_stale",
    "private": "archive_refs_private",
    "rights_held": "archive_refs_rights_held",
    "unverified": "archive_refs_unverified",
    "available": "",
}
_STATE_PUBLIC_BLOCKERS: dict[ArchiveReplayIndexState, str] = {
    "blocked": "blocked_state",
    "private": "private_state",
    "dry-run": "dry_run_only",
    "public": "",
}


class ArchiveReplaySidecarIndexError(ValueError):
    """Raised when archive replay sidecar index fixtures fail closed."""


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ArchiveReplayIndexProvenance(FrozenModel):
    """Provenance attached to one index row."""

    token: str | None
    generated_at: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    rights_basis: str = Field(min_length=1)
    citation_refs: tuple[str, ...] = Field(default_factory=tuple)


class ArchiveReplaySidecarIndexEntry(FrozenModel):
    """One addressable archive/replay sidecar object for downstream citation."""

    schema_version: Literal[1] = 1
    index_ref: str = Field(pattern=r"^archive-replay-index:[a-z0-9_.:-]+$")
    artifact_kind: ArchiveReplayArtifactKind
    state: ArchiveReplayIndexState
    run_refs: tuple[str, ...] = Field(min_length=1)
    public_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    archive_refs: tuple[str, ...] = Field(default_factory=tuple)
    sidecar_refs: tuple[str, ...] = Field(default_factory=tuple)
    frame_refs: tuple[str, ...] = Field(default_factory=tuple)
    chapter_refs: tuple[str, ...] = Field(default_factory=tuple)
    caption_refs: tuple[str, ...] = Field(default_factory=tuple)
    temporal_span_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_decision_refs: tuple[str, ...] = Field(default_factory=tuple)
    rights_class: RightsClass
    privacy_class: PrivacyClass
    provenance: ArchiveReplayIndexProvenance
    archive_ref_state: ArchiveRefState
    archive_verified: bool
    public_url: str | None = None
    public_safe_replay_claim_allowed: bool
    blocker_reasons: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_fail_closed_public_claim(self) -> Self:
        intrinsic_blockers = self.fail_closed_blockers()
        missing_blockers = tuple(
            reason for reason in intrinsic_blockers if reason not in self.blocker_reasons
        )
        if missing_blockers:
            raise ValueError(
                f"{self.index_ref} missing fail-closed blocker_reasons: "
                + ", ".join(missing_blockers)
            )
        if self.public_safe_replay_claim_allowed and intrinsic_blockers:
            raise ValueError(
                f"{self.index_ref} public-safe replay cannot pass with blockers: "
                + ", ".join(intrinsic_blockers)
            )
        if self.public_safe_replay_claim_allowed and self.state != "public":
            raise ValueError(f"{self.index_ref} public-safe replay requires public state")
        if self.state == "public" and not self.public_safe_replay_claim_allowed:
            raise ValueError(f"{self.index_ref} public state must allow public-safe replay")
        if self.state == "public" and not self.public_event_refs:
            raise ValueError(f"{self.index_ref} public state requires public_event_refs")
        if self.state == "public" and not self.public_url:
            raise ValueError(f"{self.index_ref} public state requires public_url")
        if self.public_safe_replay_claim_allowed and not (
            self.frame_refs or self.chapter_refs or self.caption_refs
        ):
            raise ValueError(
                f"{self.index_ref} public-safe replay requires frame/chapter/caption refs"
            )
        return self

    def fail_closed_blockers(self) -> tuple[str, ...]:
        """Return reasons this row cannot be promoted to public replay."""

        reasons: list[str] = []
        state_blocker = _STATE_PUBLIC_BLOCKERS[self.state]
        if state_blocker:
            reasons.append(state_blocker)
        if not self.archive_refs:
            reasons.append("archive_refs_missing")
        archive_blocker = _ARCHIVE_REF_BLOCKERS[self.archive_ref_state]
        if archive_blocker:
            reasons.append(archive_blocker)
        if not self.archive_verified:
            reasons.append("archive_refs_unverified")
        if self.rights_class not in PUBLIC_SAFE_RIGHTS:
            reasons.append("rights_blocked")
        if self.privacy_class not in PUBLIC_SAFE_PRIVACY:
            reasons.append("privacy_blocked")
        if not self.provenance.token or not self.provenance.evidence_refs:
            reasons.append("provenance_unverified")
        return _dedupe(reasons)

    def metric_states(self) -> tuple[ReplayObjectMetricState, ...]:
        """Return Prometheus object-state labels emitted for this row."""

        states: list[ReplayObjectMetricState] = []
        if self.archive_refs and self.archive_ref_state == "available" and self.archive_verified:
            states.append("available")
        if self.archive_ref_state == "stale":
            states.append("stale")
        if self.public_safe_replay_claim_allowed:
            states.append("public_safe")
        if not self.public_safe_replay_claim_allowed or self.fail_closed_blockers():
            states.append("blocked")
        return _dedupe(states)


class ArchiveReplaySidecarIndex(FrozenModel):
    """Durable sidecar index packet loaded by replay/artifact consumers."""

    schema_version: Literal[1] = 1
    index_id: str = Field(min_length=1)
    schema_ref: Literal["schemas/archive-replay-sidecar-index.schema.json"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    declared_at: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    fail_closed_policy: dict[str, bool]
    entries: tuple[ArchiveReplaySidecarIndexEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_index_contract(self) -> Self:
        if self.fail_closed_policy != FAIL_CLOSED_POLICY:
            raise ValueError("fail_closed_policy must pin archive replay sidecar gates false")
        artifact_kinds = {entry.artifact_kind for entry in self.entries}
        missing_artifact_kinds = REQUIRED_ARTIFACT_KINDS - artifact_kinds
        if missing_artifact_kinds:
            raise ValueError(
                "sidecar index missing artifact kinds: " + ", ".join(sorted(missing_artifact_kinds))
            )
        states = {entry.state for entry in self.entries}
        missing_states = REQUIRED_INDEX_STATES - states
        if missing_states:
            raise ValueError("sidecar index missing states: " + ", ".join(sorted(missing_states)))
        index_refs = [entry.index_ref for entry in self.entries]
        duplicates = sorted({ref for ref in index_refs if index_refs.count(ref) > 1})
        if duplicates:
            raise ValueError(
                "duplicate archive replay sidecar index refs: " + ", ".join(duplicates)
            )
        metric_states = set(self.metric_counts())
        missing_metric_states = REQUIRED_METRIC_STATES - metric_states
        if missing_metric_states:
            raise ValueError(
                "sidecar index missing metric states: " + ", ".join(sorted(missing_metric_states))
            )
        return self

    def by_index_ref(self) -> dict[str, ArchiveReplaySidecarIndexEntry]:
        """Return index entries keyed by durable index ref."""

        return {entry.index_ref: entry for entry in self.entries}

    def require_entry(self, index_ref: str) -> ArchiveReplaySidecarIndexEntry:
        """Return one entry or raise KeyError."""

        try:
            return self.by_index_ref()[index_ref]
        except KeyError as exc:
            raise KeyError(f"unknown archive replay sidecar index ref: {index_ref}") from exc

    def entries_for_run(self, run_ref: str) -> tuple[ArchiveReplaySidecarIndexEntry, ...]:
        """Return rows that cite a programme/content run ref."""

        return tuple(entry for entry in self.entries if run_ref in entry.run_refs)

    def public_safe_entries(self) -> tuple[ArchiveReplaySidecarIndexEntry, ...]:
        """Return entries cleared for public-safe replay citation."""

        return tuple(entry for entry in self.entries if entry.public_safe_replay_claim_allowed)

    def metric_counts(self) -> dict[ReplayObjectMetricState, int]:
        """Return index object counts by metric state."""

        counts: dict[ReplayObjectMetricState, int] = {}
        for entry in self.entries:
            for state in entry.metric_states():
                counts[state] = counts.get(state, 0) + 1
        return counts


class ArchiveReplaySidecarIndexMetrics:
    """Prometheus counters for replay index availability/readiness."""

    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self.objects_total = Counter(
            "hapax_archive_replay_sidecar_index_objects_total",
            "Archive replay sidecar index objects by replay availability/readiness.",
            ["object_state", "index_state", "artifact_kind"],
            registry=registry,
        )

    def record_entry(self, entry: ArchiveReplaySidecarIndexEntry) -> None:
        """Emit metrics for one index entry."""

        for state in entry.metric_states():
            self.objects_total.labels(
                object_state=state,
                index_state=entry.state,
                artifact_kind=entry.artifact_kind,
            ).inc()

    def record_index(self, index: ArchiveReplaySidecarIndex) -> None:
        """Emit metrics for every entry in an index packet."""

        for entry in index.entries:
            self.record_entry(entry)


def build_archive_replay_sidecar_index(
    entries: Iterable[ArchiveReplaySidecarIndexEntry],
    *,
    index_id: str,
    declared_at: str,
    generated_from: Iterable[str],
    producer: str = PRODUCER,
) -> ArchiveReplaySidecarIndex:
    """Build and validate one durable archive replay sidecar index packet."""

    return ArchiveReplaySidecarIndex(
        index_id=index_id,
        schema_ref="schemas/archive-replay-sidecar-index.schema.json",
        generated_from=tuple(generated_from),
        declared_at=declared_at,
        producer=producer,
        fail_closed_policy=FAIL_CLOSED_POLICY,
        entries=tuple(entries),
    )


def load_archive_replay_sidecar_index_fixtures(
    path: Path = ARCHIVE_REPLAY_SIDECAR_INDEX_FIXTURES,
) -> ArchiveReplaySidecarIndex:
    """Load and validate archive replay sidecar index fixture contracts."""

    try:
        return ArchiveReplaySidecarIndex.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ArchiveReplaySidecarIndexError(
            f"invalid archive replay sidecar index fixtures at {path}: {exc}"
        ) from exc


def _dedupe(values: Iterable[ReplayObjectMetricState]) -> tuple[ReplayObjectMetricState, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ArchiveReplaySidecarIndexError(f"{path} did not contain a JSON object")
    return payload


__all__ = [
    "ARCHIVE_REPLAY_SIDECAR_INDEX_FIXTURES",
    "FAIL_CLOSED_POLICY",
    "PRODUCER",
    "PUBLIC_SAFE_PRIVACY",
    "PUBLIC_SAFE_RIGHTS",
    "REQUIRED_ARTIFACT_KINDS",
    "REQUIRED_INDEX_STATES",
    "REQUIRED_METRIC_STATES",
    "TASK_ANCHOR",
    "ArchiveRefState",
    "ArchiveReplayArtifactKind",
    "ArchiveReplayIndexProvenance",
    "ArchiveReplayIndexState",
    "ArchiveReplaySidecarIndex",
    "ArchiveReplaySidecarIndexEntry",
    "ArchiveReplaySidecarIndexError",
    "ArchiveReplaySidecarIndexMetrics",
    "ReplayObjectMetricState",
    "build_archive_replay_sidecar_index",
    "load_archive_replay_sidecar_index_fixtures",
]
