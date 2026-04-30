"""Fixture-backed WCS health drift rules for claim-bearing text."""

from __future__ import annotations

import json
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.world_surface_health import HealthDimensionState, HealthStatus, PublicPrivatePosture

REPO_ROOT = Path(__file__).resolve().parents[1]
WORLD_SURFACE_HEALTH_DRIFT_FIXTURES = (
    REPO_ROOT / "config" / "world-surface-health-drift-fixtures.json"
)

REQUIRED_ARTIFACT_KINDS = frozenset(
    {
        "doc",
        "cc_task_note",
        "prompt",
        "public_copy",
        "dashboard_label",
        "grant_support_copy",
    }
)

REQUIRED_FINDING_CLASSES = frozenset(
    {
        "stale",
        "missing",
        "unsupported",
        "wrong_route",
        "false_live",
        "false_monetization",
    }
)


class WorldSurfaceHealthDriftError(ValueError):
    """Raised when WCS health drift fixtures cannot be evaluated safely."""


class ArtifactKind(StrEnum):
    DOC = "doc"
    CC_TASK_NOTE = "cc_task_note"
    PROMPT = "prompt"
    PUBLIC_COPY = "public_copy"
    DASHBOARD_LABEL = "dashboard_label"
    GRANT_SUPPORT_COPY = "grant_support_copy"


class ClaimIntent(StrEnum):
    LIVE = "live"
    PUBLIC = "public"
    GROUNDED = "grounded"
    OPERATOR_ACTIONABLE = "operator_actionable"
    MONETIZATION = "monetization"


class DriftFindingClass(StrEnum):
    STALE = "stale"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"
    WRONG_ROUTE = "wrong_route"
    FALSE_LIVE = "false_live"
    FALSE_MONETIZATION = "false_monetization"


class DriftSeverity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ClaimFixture(BaseModel):
    """One claim-bearing text fixture to evaluate for WCS health drift."""

    model_config = ConfigDict(extra="forbid")

    fixture_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    artifact_kind: ArtifactKind
    source_path: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    claim_intents: list[ClaimIntent] = Field(min_length=1)
    surface_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    health_status: HealthStatus | None = None
    public_private_posture: PublicPrivatePosture | None = None
    public_claim_allowed: bool = False
    monetization_allowed: bool = False
    route_binding_state: HealthDimensionState | None = None
    marked_planned_or_historical: bool = False
    expected_findings: list[DriftFindingClass] = Field(default_factory=list)

    def is_public_or_live_claim(self) -> bool:
        """Return true when the fixture implies public/live/grounded/action truth."""

        return any(
            intent
            in {
                ClaimIntent.LIVE,
                ClaimIntent.PUBLIC,
                ClaimIntent.GROUNDED,
                ClaimIntent.OPERATOR_ACTIONABLE,
            }
            for intent in self.claim_intents
        )


class WorldSurfaceHealthDriftFinding(BaseModel):
    """Machine-readable drift finding for dashboard/API consumers."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    fixture_id: str
    artifact_kind: ArtifactKind
    source_path: str
    classification: DriftFindingClass
    severity: DriftSeverity
    surface_id: str | None
    evidence_refs: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(min_length=1)
    blocks_public_escalation: Literal[True] = True
    suggestion: str


class WorldSurfaceHealthDriftSummary(BaseModel):
    """Summary counts for a drift report."""

    model_config = ConfigDict(extra="forbid")

    total_fixtures: int = Field(ge=0)
    total_findings: int = Field(ge=0)
    by_artifact_kind: dict[str, int]
    by_classification: dict[str, int]
    blocks_public_escalation_count: int = Field(ge=0)


class WorldSurfaceHealthDriftReport(BaseModel):
    """Deterministic report produced by the WCS health drift rules."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    report_id: str
    generated_at: str
    source_refs: list[str] = Field(min_length=1)
    findings: list[WorldSurfaceHealthDriftFinding]
    summary: WorldSurfaceHealthDriftSummary
    dashboard_api_contract: dict[str, str]


class WorldSurfaceHealthDriftFixtureSet(BaseModel):
    """Fixture packet for WCS health drift rules."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fixture_set_id: str
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    producer: str
    artifact_kinds: list[ArtifactKind] = Field(min_length=1)
    finding_classes: list[DriftFindingClass] = Field(min_length=1)
    claim_fixtures: list[ClaimFixture] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]

    def validate_contract(self) -> None:
        """Validate fixture coverage and expected deterministic findings."""

        artifact_kinds = {kind.value for kind in self.artifact_kinds}
        missing_artifact_kinds = REQUIRED_ARTIFACT_KINDS - artifact_kinds
        if missing_artifact_kinds:
            raise ValueError(
                "missing WCS drift artifact kinds: " + ", ".join(sorted(missing_artifact_kinds))
            )
        fixture_artifact_kinds = {fixture.artifact_kind.value for fixture in self.claim_fixtures}
        missing_fixture_kinds = REQUIRED_ARTIFACT_KINDS - fixture_artifact_kinds
        if missing_fixture_kinds:
            raise ValueError(
                "drift fixtures do not cover artifact kinds: "
                + ", ".join(sorted(missing_fixture_kinds))
            )

        finding_classes = {finding.value for finding in self.finding_classes}
        missing_finding_classes = REQUIRED_FINDING_CLASSES - finding_classes
        if missing_finding_classes:
            raise ValueError(
                "missing WCS drift finding classes: " + ", ".join(sorted(missing_finding_classes))
            )

        if self.fail_closed_policy != {
            "missing_surface_id_allows_claim": False,
            "missing_evidence_refs_allows_claim": False,
            "stale_health_allows_public_live": False,
            "wrong_route_allows_action_claim": False,
            "private_or_blocked_posture_allows_public_claim": False,
            "monetization_without_readiness_allowed": False,
        }:
            raise ValueError("WCS drift fail_closed_policy must pin all gates false")

        seen_finding_classes: set[str] = set()
        for fixture in self.claim_fixtures:
            actual = {finding.classification for finding in evaluate_claim_fixture(fixture)}
            expected = set(fixture.expected_findings)
            if actual != expected:
                raise ValueError(
                    f"{fixture.fixture_id} expected findings "
                    f"{sorted(item.value for item in expected)} but got "
                    f"{sorted(item.value for item in actual)}"
                )
            seen_finding_classes.update(item.value for item in actual)

        missing_fixture_finding_classes = REQUIRED_FINDING_CLASSES - seen_finding_classes
        if missing_fixture_finding_classes:
            raise ValueError(
                "drift fixtures do not produce finding classes: "
                + ", ".join(sorted(missing_fixture_finding_classes))
            )


def evaluate_claim_fixture(fixture: ClaimFixture) -> list[WorldSurfaceHealthDriftFinding]:
    """Evaluate one claim fixture against fail-closed WCS drift rules."""

    findings: list[WorldSurfaceHealthDriftFinding] = []

    def add(
        classification: DriftFindingClass,
        *,
        reason_codes: list[str],
        suggestion: str,
    ) -> None:
        findings.append(
            WorldSurfaceHealthDriftFinding(
                finding_id=f"{fixture.fixture_id}:{classification.value}",
                fixture_id=fixture.fixture_id,
                artifact_kind=fixture.artifact_kind,
                source_path=fixture.source_path,
                classification=classification,
                severity=_severity_for(classification),
                surface_id=fixture.surface_id,
                evidence_refs=fixture.evidence_refs,
                reason_codes=reason_codes,
                suggestion=suggestion,
            )
        )

    if fixture.surface_id is None:
        add(
            DriftFindingClass.MISSING,
            reason_codes=["surface_id_missing"],
            suggestion="Attach a valid WCS surface_id or mark the claim planned/historical.",
        )

    if not fixture.evidence_refs and not fixture.marked_planned_or_historical:
        add(
            DriftFindingClass.UNSUPPORTED,
            reason_codes=["evidence_refs_missing"],
            suggestion="Attach WCS evidence refs or downgrade the text to planned/blocked.",
        )

    if fixture.health_status is HealthStatus.STALE:
        add(
            DriftFindingClass.STALE,
            reason_codes=["health_status_stale"],
            suggestion="Refresh the WCS health row before making live/public claims.",
        )

    if fixture.route_binding_state is HealthDimensionState.FAIL:
        add(
            DriftFindingClass.WRONG_ROUTE,
            reason_codes=["route_binding_failed"],
            suggestion="Do not claim actionability until route binding matches the target.",
        )

    if fixture.is_public_or_live_claim() and not fixture.marked_planned_or_historical:
        if (
            fixture.public_claim_allowed is False
            or fixture.public_private_posture is not PublicPrivatePosture.PUBLIC_LIVE
            or fixture.health_status is not HealthStatus.HEALTHY
        ):
            add(
                DriftFindingClass.FALSE_LIVE,
                reason_codes=["public_or_live_posture_not_allowed"],
                suggestion="Block claim escalation or rewrite as unavailable/dry-run/private-only.",
            )

    if ClaimIntent.MONETIZATION in fixture.claim_intents and not fixture.monetization_allowed:
        add(
            DriftFindingClass.FALSE_MONETIZATION,
            reason_codes=["monetization_readiness_missing"],
            suggestion="Remove monetization wording until readiness evidence and public policy pass.",
        )

    return findings


def build_world_surface_health_drift_report(
    fixture_set: WorldSurfaceHealthDriftFixtureSet,
) -> WorldSurfaceHealthDriftReport:
    """Build a deterministic machine-readable drift report from fixtures."""

    findings = [
        finding
        for fixture in fixture_set.claim_fixtures
        for finding in evaluate_claim_fixture(fixture)
    ]
    by_artifact = Counter(finding.artifact_kind.value for finding in findings)
    by_classification = Counter(finding.classification.value for finding in findings)
    return WorldSurfaceHealthDriftReport(
        report_id=f"world_surface_health_drift:{fixture_set.declared_at}",
        generated_at=fixture_set.declared_at,
        source_refs=fixture_set.generated_from,
        findings=findings,
        summary=WorldSurfaceHealthDriftSummary(
            total_fixtures=len(fixture_set.claim_fixtures),
            total_findings=len(findings),
            by_artifact_kind=dict(sorted(by_artifact.items())),
            by_classification=dict(sorted(by_classification.items())),
            blocks_public_escalation_count=sum(
                finding.blocks_public_escalation for finding in findings
            ),
        ),
        dashboard_api_contract={
            "primary_key": "finding_id",
            "classification_field": "classification",
            "blocking_field": "blocks_public_escalation",
            "source_field": "source_path",
        },
    )


def _severity_for(classification: DriftFindingClass) -> DriftSeverity:
    if classification in {
        DriftFindingClass.MISSING,
        DriftFindingClass.WRONG_ROUTE,
        DriftFindingClass.FALSE_LIVE,
        DriftFindingClass.FALSE_MONETIZATION,
    }:
        return DriftSeverity.HIGH
    if classification is DriftFindingClass.UNSUPPORTED:
        return DriftSeverity.MEDIUM
    return DriftSeverity.LOW


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise WorldSurfaceHealthDriftError(f"{path} did not contain a JSON object")
    return payload


def load_world_surface_health_drift_fixtures(
    path: Path = WORLD_SURFACE_HEALTH_DRIFT_FIXTURES,
) -> WorldSurfaceHealthDriftFixtureSet:
    """Load WCS health drift fixtures, failing closed on malformed data."""

    try:
        fixture_set = WorldSurfaceHealthDriftFixtureSet.model_validate(_load_json_object(path))
        fixture_set.validate_contract()
        return fixture_set
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise WorldSurfaceHealthDriftError(
            f"invalid WCS health drift fixtures at {path}: {exc}"
        ) from exc


def build_fixture_drift_report(
    path: Path = WORLD_SURFACE_HEALTH_DRIFT_FIXTURES,
) -> WorldSurfaceHealthDriftReport:
    """Load fixtures and produce the machine-readable drift report."""

    return build_world_surface_health_drift_report(load_world_surface_health_drift_fixtures(path))


__all__ = [
    "REQUIRED_ARTIFACT_KINDS",
    "REQUIRED_FINDING_CLASSES",
    "WORLD_SURFACE_HEALTH_DRIFT_FIXTURES",
    "ArtifactKind",
    "ClaimFixture",
    "ClaimIntent",
    "DriftFindingClass",
    "WorldSurfaceHealthDriftError",
    "WorldSurfaceHealthDriftFixtureSet",
    "WorldSurfaceHealthDriftFinding",
    "WorldSurfaceHealthDriftReport",
    "build_fixture_drift_report",
    "build_world_surface_health_drift_report",
    "evaluate_claim_fixture",
    "load_world_surface_health_drift_fixtures",
]
