"""Map approved PreprintArtifact lifecycle facts to public-event records.

The publish orchestrator remains the dispatch, audit, and idempotency owner:
``publish/log/{slug}.{surface}.json`` records are still the source of truth for
retry and terminal state. This adapter only projects those facts onto the
canonical ``ResearchVehiclePublicEvent`` stream so downstream public apertures
can make policy decisions without scraping the publish inbox or logs.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.governance.publication_allowlist import check as allowlist_check
from shared.preprint_artifact import OMG_WEBLOG_DIRECT_FANOUT_SURFACES, PreprintArtifact
from shared.research_vehicle_public_event import (
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    Surface,
)

TASK_ANCHOR = "publication-artifact-public-event-adapter"
PRODUCER = "shared.publication_artifact_public_event"
SOURCE_SUBSTRATE_ID = "publication_artifact"
STATE_KIND = "publication.artifact"
AUDIT_OWNER = "publish_orchestrator:publish/log/{slug}.{surface}.json"
IDEMPOTENCY_OWNER = "publish_orchestrator:artifact_fingerprint+surface_result"

type PublicationArtifactEventStage = Literal["inbox", "surface_log", "published", "failed"]
type PublicationArtifactDecisionStatus = Literal["emitted", "held", "refused"]

_SURFACE_BY_PUBLISH_SURFACE: dict[str, Surface] = {
    "arena-post": "arena",
    "bluesky-post": "bluesky",
    "discord-webhook": "discord",
    "mastodon-post": "mastodon",
    "omg-weblog": "omg_weblog",
    "oudepode-omg-weblog": "omg_weblog",
    "zenodo-doi": "zenodo",
    "zenodo-refusal-deposit": "zenodo",
}
_PUBLICATION_CONTRACT_BY_PUBLISH_SURFACE: dict[str, str] = {
    "arena-post": "arena-post",
    "bluesky-post": "bluesky-post",
    "discord-webhook": "discord-webhook",
    "mastodon-post": "mastodon-post",
    "omg-weblog": "omg-lol-weblog",
    "oudepode-omg-weblog": "omg-lol-weblog",
    "osf-preprint": "osf-preprint",
    "zenodo-doi": "zenodo-doi",
    "zenodo-refusal-deposit": "zenodo-refusal-deposit",
}
_BASE_ALLOWED_SURFACES: tuple[Surface, ...] = ("archive", "health")
_PUBLICATION_ARTIFACT_DENIED_SURFACES: tuple[Surface, ...] = (
    "youtube_description",
    "youtube_cuepoints",
    "youtube_chapters",
    "youtube_captions",
    "youtube_shorts",
    "youtube_channel_sections",
    "arena",
    "omg_statuslog",
    "omg_weblog",
    "omg_now",
    "mastodon",
    "bluesky",
    "discord",
    "replay",
    "github_readme",
    "github_profile",
    "github_release",
    "github_package",
    "github_pages",
    "captions",
    "cuepoints",
    "monetization",
)
_TERMINAL_SUCCESS = {"ok"}
_TERMINAL_FAILURE = {
    "denied",
    "auth_error",
    "no_credentials",
    "error",
    "dropped",
    "surface_unwired",
}
DIRECT_DISPATCH_SECONDARY_FANOUT_HOLD_REASON = (
    "direct_dispatch_surface_result:secondary_public_event_fanout_not_claimed"
)
_DIRECT_DISPATCH_PUBLIC_EVENT_HOLD_SURFACES = frozenset(OMG_WEBLOG_DIRECT_FANOUT_SURFACES)


class PublicationArtifactPublicEventModel(BaseModel):
    """Strict immutable base for adapter audit records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PublicationArtifactPolicyCheck(PublicationArtifactPublicEventModel):
    """One allowlist/public-policy check that shaped the public event."""

    surface: str
    canonical_surface: Surface | None
    state_kind: Literal["publication.artifact"] = STATE_KIND
    decision: Literal["allow", "redact", "deny"]
    reason: str


class PublicationArtifactPublicEventDecision(PublicationArtifactPublicEventModel):
    """Projection outcome for one PreprintArtifact lifecycle fact."""

    schema_version: Literal[1] = 1
    decision_id: str
    idempotency_key: str
    status: PublicationArtifactDecisionStatus
    artifact_slug: str
    artifact_fingerprint: str
    stage: PublicationArtifactEventStage
    surface: str | None
    result: str | None
    public_event: ResearchVehiclePublicEvent | None
    policy_checks: tuple[PublicationArtifactPolicyCheck, ...] = Field(default_factory=tuple)
    audit_owner: Literal["publish_orchestrator:publish/log/{slug}.{surface}.json"] = AUDIT_OWNER
    idempotency_owner: Literal["publish_orchestrator:artifact_fingerprint+surface_result"] = (
        IDEMPOTENCY_OWNER
    )
    log_refs: tuple[str, ...] = Field(default_factory=tuple)
    notes: tuple[str, ...] = Field(default_factory=tuple)

    def to_json_line(self) -> str:
        """Serialize the decision for adapter-specific audit logs."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True) + "\n"


def build_publication_artifact_public_event(
    artifact: PreprintArtifact,
    *,
    artifact_fingerprint: str,
    state_root: Path,
    stage: PublicationArtifactEventStage,
    generated_at: datetime | str,
    source_path: Path | None = None,
    surface: str | None = None,
    result: str | None = None,
    result_timestamp: str | None = None,
) -> PublicationArtifactPublicEventDecision:
    """Project one approved artifact lifecycle fact to a canonical public event.

    The returned event is a policy-bearing witness, not a publisher. It never
    invokes surface clients; those remain behind the publish orchestrator and
    each publisher's own allowlist/public-policy gates.
    """

    generated = _normalise_iso(generated_at)
    source_ref = _source_ref(
        artifact,
        state_root=state_root,
        stage=stage,
        surface=surface,
        source_path=source_path,
    )
    log_refs = _log_refs(
        artifact,
        state_root=state_root,
        artifact_fingerprint=artifact_fingerprint,
        stage=stage,
        surface=surface,
        result=result,
    )
    payload = _allowlist_payload(
        artifact,
        artifact_fingerprint=artifact_fingerprint,
        generated_at=generated,
        stage=stage,
        source_ref=source_ref,
        surface=surface,
        result=result,
        log_refs=log_refs,
    )
    policy_checks = _policy_checks(artifact, payload, surface=surface)
    orchestrator_check = policy_checks[0]
    event_id = publication_artifact_public_event_id(
        artifact_slug=artifact.slug,
        artifact_fingerprint=artifact_fingerprint,
        stage=stage,
        surface=surface,
        result=result,
    )

    if orchestrator_check.decision == "deny":
        return PublicationArtifactPublicEventDecision(
            decision_id=f"paped:{event_id}",
            idempotency_key=event_id,
            status="refused",
            artifact_slug=artifact.slug,
            artifact_fingerprint=artifact_fingerprint,
            stage=stage,
            surface=surface,
            result=result,
            public_event=None,
            policy_checks=policy_checks,
            log_refs=log_refs,
            notes=(f"publish_orchestrator_allowlist_denied:{orchestrator_check.reason}",),
        )

    dry_run_reason = _dry_run_reason(
        artifact,
        stage=stage,
        surface=surface,
        result=result,
        policy_checks=policy_checks,
    )
    allowed_surfaces = _allowed_surfaces(policy_checks, dry_run_reason=dry_run_reason)
    denied_surfaces = _denied_surfaces(allowed_surfaces)
    occurred_at = _occurred_at(
        artifact,
        stage=stage,
        generated_at=generated,
        result_timestamp=result_timestamp,
    )
    public_event = ResearchVehiclePublicEvent(
        schema_version=1,
        event_id=event_id,
        event_type="publication.artifact",
        occurred_at=occurred_at,
        broadcast_id=None,
        programme_id=None,
        condition_id=None,
        source=PublicEventSource(
            producer=PRODUCER,
            substrate_id=SOURCE_SUBSTRATE_ID,
            task_anchor=TASK_ANCHOR,
            evidence_ref=source_ref,
            freshness_ref=None,
        ),
        salience=_salience(stage=stage, result=result),
        state_kind="archive_artifact",
        rights_class="operator_controlled",
        privacy_class="public_safe",
        provenance=PublicEventProvenance(
            token=f"publication_artifact:{event_id}",
            generated_at=generated,
            producer=PRODUCER,
            evidence_refs=[
                f"PreprintArtifact:{artifact.slug}",
                f"artifact_fingerprint:{artifact_fingerprint}",
                f"publish_orchestrator.stage:{stage}",
                "metric:hapax_publish_orchestrator_dispatches_total",
                *log_refs,
            ],
            rights_basis=(
                "operator-approved PreprintArtifact dispatch; per-surface publish logs "
                "remain the audit and idempotency source"
            ),
            citation_refs=_citation_refs(artifact),
        ),
        public_url=_public_url_for_surface(artifact, surface=surface, result=result),
        frame_ref=None,
        chapter_ref=None,
        attribution_refs=_attribution_refs(artifact),
        surface_policy=PublicEventSurfacePolicy(
            allowed_surfaces=list(allowed_surfaces),
            denied_surfaces=list(denied_surfaces),
            claim_live=False,
            claim_archive=dry_run_reason is None and stage != "failed",
            claim_monetizable=False,
            requires_egress_public_claim=False,
            requires_audio_safe=False,
            requires_provenance=True,
            requires_human_review=False,
            rate_limit_key=f"publication.artifact:{artifact.slug}",
            redaction_policy="operator_referent",
            fallback_action=_fallback_action(stage=stage, dry_run_reason=dry_run_reason),
            dry_run_reason=dry_run_reason,
        ),
    )
    return PublicationArtifactPublicEventDecision(
        decision_id=f"paped:{event_id}",
        idempotency_key=event_id,
        status="held" if dry_run_reason else "emitted",
        artifact_slug=artifact.slug,
        artifact_fingerprint=artifact_fingerprint,
        stage=stage,
        surface=surface,
        result=result,
        public_event=public_event,
        policy_checks=policy_checks,
        log_refs=log_refs,
        notes=_notes(artifact, stage=stage, surface=surface, dry_run_reason=dry_run_reason),
    )


def publication_artifact_public_event_id(
    *,
    artifact_slug: str,
    artifact_fingerprint: str,
    stage: PublicationArtifactEventStage,
    surface: str | None = None,
    result: str | None = None,
) -> str:
    """Stable idempotency key for one artifact lifecycle projection."""

    parts = ["rvpe", "publication_artifact", artifact_slug, artifact_fingerprint[:16], stage]
    if surface:
        parts.append(surface)
    if result:
        parts.append(result)
    return _sanitize_id(":".join(parts))


def github_public_material_surfaces() -> tuple[Surface, ...]:
    """Return GitHub material surfaces the event schema can now name."""

    return (
        "github_readme",
        "github_profile",
        "github_release",
        "github_package",
        "github_pages",
        "zenodo",
    )


def _policy_checks(
    artifact: PreprintArtifact,
    payload: dict[str, Any],
    *,
    surface: str | None,
) -> tuple[PublicationArtifactPolicyCheck, ...]:
    checks: list[PublicationArtifactPolicyCheck] = []
    orchestrator_verdict = allowlist_check("publish-orchestrator", STATE_KIND, payload)
    checks.append(
        PublicationArtifactPolicyCheck(
            surface="publish-orchestrator",
            canonical_surface=None,
            decision=orchestrator_verdict.decision,
            reason=orchestrator_verdict.reason,
        )
    )
    candidates = [surface] if surface else list(artifact.surfaces_targeted)
    for candidate in candidates:
        if candidate is None:
            continue
        contract_surface = _PUBLICATION_CONTRACT_BY_PUBLISH_SURFACE.get(candidate)
        canonical_surface = _SURFACE_BY_PUBLISH_SURFACE.get(candidate)
        if contract_surface is None:
            checks.append(
                PublicationArtifactPolicyCheck(
                    surface=candidate,
                    canonical_surface=canonical_surface,
                    decision="deny",
                    reason="no publication.artifact surface contract mapped",
                )
            )
            continue
        verdict = allowlist_check(contract_surface, STATE_KIND, payload)
        checks.append(
            PublicationArtifactPolicyCheck(
                surface=contract_surface,
                canonical_surface=canonical_surface,
                decision=verdict.decision,
                reason=verdict.reason,
            )
        )
    return tuple(checks)


def _allowlist_payload(
    artifact: PreprintArtifact,
    *,
    artifact_fingerprint: str,
    generated_at: str,
    stage: PublicationArtifactEventStage,
    source_ref: str,
    surface: str | None,
    result: str | None,
    log_refs: tuple[str, ...],
) -> dict[str, Any]:
    evidence_refs = [
        f"PreprintArtifact:{artifact.slug}",
        f"artifact_fingerprint:{artifact_fingerprint}",
        source_ref,
        *log_refs,
    ]
    return {
        "artifact": {
            "slug": artifact.slug,
            "schema_version": artifact.schema_version,
            "approval": str(artifact.approval),
            "approved_at": _optional_datetime(artifact.approved_at),
            "approved_by_referent": artifact.approved_by_referent,
            "surfaces_targeted": list(artifact.surfaces_targeted),
            "artifact_fingerprint": artifact_fingerprint,
        },
        "lifecycle": {
            "stage": stage,
            "surface": surface,
            "result": result,
        },
        "grounding_gate_result": _grounding_gate(
            evidence_refs=evidence_refs,
            generated_at=generated_at,
        ),
    }


def _grounding_gate(*, evidence_refs: list[str], generated_at: str) -> dict[str, Any]:
    refs = list(dict.fromkeys(ref for ref in evidence_refs if ref))
    return {
        "schema_version": 1,
        "public_private_mode": "public_archive",
        "gate_state": "pass",
        "claim": {
            "evidence_refs": refs,
            "provenance": {"source_refs": refs},
            "freshness": {"status": "not_applicable", "observed_at": generated_at},
            "rights_state": "operator_controlled",
            "privacy_state": "public_safe",
            "public_private_mode": "public_archive",
            "refusal_correction_path": {
                "refusal_reason": None,
                "correction_event_ref": None,
                "artifact_ref": refs[0] if refs else None,
            },
        },
        "gate_result": {
            "may_emit_claim": True,
            "may_publish_live": False,
            "may_publish_archive": True,
            "may_monetize": False,
        },
    }


def _allowed_surfaces(
    policy_checks: tuple[PublicationArtifactPolicyCheck, ...],
    *,
    dry_run_reason: str | None,
) -> tuple[Surface, ...]:
    if dry_run_reason:
        return ("health",)
    surfaces = list(_BASE_ALLOWED_SURFACES)
    for check in policy_checks[1:]:
        if check.decision in {"allow", "redact"} and check.canonical_surface is not None:
            surfaces.append(check.canonical_surface)
    return tuple(dict.fromkeys(surfaces))


def _denied_surfaces(allowed_surfaces: tuple[Surface, ...]) -> tuple[Surface, ...]:
    allowed = set(allowed_surfaces)
    return tuple(
        surface for surface in _PUBLICATION_ARTIFACT_DENIED_SURFACES if surface not in allowed
    )


def _dry_run_reason(
    artifact: PreprintArtifact,
    *,
    stage: PublicationArtifactEventStage,
    surface: str | None,
    result: str | None,
    policy_checks: tuple[PublicationArtifactPolicyCheck, ...],
) -> str | None:
    reasons: list[str] = []
    if stage == "inbox":
        reasons.append("pending_surface_dispatch")
    if result and result not in _TERMINAL_SUCCESS:
        if result in _TERMINAL_FAILURE:
            reasons.append(f"surface_terminal_failure:{result}")
        else:
            reasons.append(f"surface_non_terminal:{result}")
    target_surfaces = {surface} if surface else set(artifact.surfaces_targeted)
    if (
        artifact.slug.startswith("refusal-annex-")
        and "bridgy-webmention-publish" in target_surfaces
    ):
        reasons.append("refusal_annex_bridgy_fanout_not_claimed:dry_run_scaffold")
    if stage in {"surface_log", "published"} and (result is None or result in _TERMINAL_SUCCESS):
        if target_surfaces & _DIRECT_DISPATCH_PUBLIC_EVENT_HOLD_SURFACES:
            reasons.append(DIRECT_DISPATCH_SECONDARY_FANOUT_HOLD_REASON)
    for check in policy_checks[1:]:
        if check.decision == "deny":
            reasons.append(f"surface_policy_denied:{check.surface}")
    if not reasons:
        return None
    return ";".join(dict.fromkeys(reasons))


def _source_ref(
    artifact: PreprintArtifact,
    *,
    state_root: Path,
    stage: PublicationArtifactEventStage,
    surface: str | None,
    source_path: Path | None,
) -> str:
    path = source_path
    if path is None:
        if stage == "surface_log" and surface:
            path = artifact.log_path(surface, state_root=state_root)
        elif stage == "published":
            path = artifact.published_path(state_root=state_root)
        elif stage == "failed":
            path = artifact.failed_path(state_root=state_root)
        else:
            path = artifact.inbox_path(state_root=state_root)
    return str(path)


def _log_refs(
    artifact: PreprintArtifact,
    *,
    state_root: Path,
    artifact_fingerprint: str,
    stage: PublicationArtifactEventStage,
    surface: str | None,
    result: str | None,
) -> tuple[str, ...]:
    if stage == "inbox":
        return ()
    if surface:
        return (
            f"{artifact.log_path(surface, state_root=state_root)}"
            f"#artifact_fingerprint={artifact_fingerprint};result={result or 'unknown'}",
        )
    refs: list[str] = []
    for target in artifact.surfaces_targeted:
        path = artifact.log_path(target, state_root=state_root)
        if path.exists():
            refs.append(f"{path}#artifact_fingerprint={artifact_fingerprint}")
    return tuple(refs)


def _occurred_at(
    artifact: PreprintArtifact,
    *,
    stage: PublicationArtifactEventStage,
    generated_at: str,
    result_timestamp: str | None,
) -> str:
    if stage == "surface_log" and result_timestamp:
        return _normalise_iso(result_timestamp)
    if stage == "inbox" and artifact.approved_at is not None:
        return _normalise_iso(artifact.approved_at)
    return generated_at


def _salience(*, stage: PublicationArtifactEventStage, result: str | None) -> float:
    if stage == "published":
        return 0.74
    if stage == "failed" or (result and result in _TERMINAL_FAILURE):
        return 0.66
    if stage == "surface_log":
        return 0.62
    return 0.5


def _fallback_action(
    *,
    stage: PublicationArtifactEventStage,
    dry_run_reason: str | None,
) -> Literal["hold", "dry_run", "archive_only", "deny"]:
    if dry_run_reason is None:
        return "archive_only"
    if stage == "failed":
        return "deny"
    if "dry_run_scaffold" in dry_run_reason:
        return "dry_run"
    return "hold"


def _public_url_for_surface(
    artifact: PreprintArtifact,
    *,
    surface: str | None,
    result: str | None,
) -> str | None:
    if result != "ok":
        return None
    if surface == "omg-weblog":
        return f"https://hapax.omg.lol/weblog/{artifact.slug}"
    if surface == "oudepode-omg-weblog":
        return f"https://oudepode.omg.lol/weblog/{artifact.slug}"
    return None


def _citation_refs(artifact: PreprintArtifact) -> list[str]:
    refs: list[str] = []
    if artifact.doi:
        refs.append(f"doi:{artifact.doi}")
    return refs


def _attribution_refs(artifact: PreprintArtifact) -> list[str]:
    refs = [f"co_author:{author.name}" for author in artifact.co_authors]
    if artifact.doi:
        refs.append(f"doi:{artifact.doi}")
    return list(dict.fromkeys(refs))


def _notes(
    artifact: PreprintArtifact,
    *,
    stage: PublicationArtifactEventStage,
    surface: str | None,
    dry_run_reason: str | None,
) -> tuple[str, ...]:
    notes = [
        "publish_orchestrator_logs_remain_audit_and_idempotency_source",
        f"stage:{stage}",
    ]
    if surface:
        notes.append(f"surface:{surface}")
    if artifact.slug.startswith("refusal-annex-"):
        notes.append("refusal_annex_artifact")
    if dry_run_reason:
        notes.append(f"hold:{dry_run_reason}")
    return tuple(notes)


def _normalise_iso(value: datetime | str) -> str:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    text = value.strip()
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def _optional_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _normalise_iso(value)


def _sanitize_id(raw: str) -> str:
    result = re.sub(r"[^a-z0-9_:]+", "_", raw.lower()).strip("_:")
    if not result or not result[0].isalpha():
        return f"rvpe:{result}"
    return result


__all__ = [
    "AUDIT_OWNER",
    "IDEMPOTENCY_OWNER",
    "PRODUCER",
    "PublicationArtifactEventStage",
    "PublicationArtifactPolicyCheck",
    "PublicationArtifactPublicEventDecision",
    "DIRECT_DISPATCH_SECONDARY_FANOUT_HOLD_REASON",
    "build_publication_artifact_public_event",
    "github_public_material_surfaces",
    "publication_artifact_public_event_id",
]
