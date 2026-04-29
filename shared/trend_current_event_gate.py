"""Deterministic gate for trend and current-event content candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "trend-current-event-constraint-gate.json"


class GateAction(StrEnum):
    """Public-surface action selected by the trend/current-event gate."""

    ALLOW_PUBLIC_CLAIM = "allow_public_claim"
    DOWNGRADE_TO_WATCH = "downgrade_to_watch"
    FORCE_REFUSAL_FORMAT = "force_refusal_format"
    BLOCK_PUBLIC_CLAIM = "block_public_claim"


class GateInfraction(StrEnum):
    """Named infractions emitted for downstream audit and evaluator use."""

    MISSING_FRESHNESS = "missing_freshness"
    STALE_SOURCE = "stale_source"
    MISSING_PRIMARY_OR_OFFICIAL_SOURCE = "missing_primary_or_official_source"
    UNDER_24H_DEFINITIVE_FORMAT = "under_24h_definitive_format"
    SENSITIVE_EVENT_EXPLOITATION = "sensitive_event_exploitation"
    MISSING_UNCERTAINTY_LANGUAGE = "missing_uncertainty_language"
    TREND_AS_TRUTH = "trend_as_truth"
    SOURCE_BIAS_UNTRACKED = "source_bias_untracked"


WATCH_FORMATS = frozenset({"watching", "audit", "refusal", "correction", "claim_audit"})


@dataclass(frozen=True)
class TrendCurrentEventCandidate:
    """Candidate facts available before a content opportunity can become public."""

    candidate_id: str
    claim_type: str
    proposed_format: str
    public_mode: str
    source_age_s: float | None
    source_ttl_s: float | None
    event_age_s: float | None
    primary_source_count: int = 0
    official_source_count: int = 0
    corroborating_source_count: int = 0
    recency_label_present: bool = False
    title_uncertainty_present: bool = False
    description_uncertainty_present: bool = False
    sensitivity_categories: tuple[str, ...] = ()
    edsa_context_present: bool = False
    monetized: bool = False
    trend_used_as_truth: bool = False
    trend_decay_score: float | None = None
    source_bias_score: float | None = None

    @property
    def has_primary_or_official_source(self) -> bool:
        return self.primary_source_count > 0 or self.official_source_count > 0

    @property
    def is_public(self) -> bool:
        return self.public_mode in {"public_live", "public_archive", "public_monetizable"}

    @property
    def is_sensitive(self) -> bool:
        return bool(self.sensitivity_categories)

    @property
    def is_under_24h(self) -> bool:
        return self.event_age_s is not None and self.event_age_s < 86_400

    @property
    def has_uncertainty_language(self) -> bool:
        return self.title_uncertainty_present and self.description_uncertainty_present


@dataclass(frozen=True)
class TrendCurrentEventGateResult:
    """Gate output consumed by candidate discovery and public adapters."""

    candidate_id: str
    action: GateAction
    public_claim_allowed: bool
    monetization_allowed: bool
    required_format_family: str | None
    blockers: tuple[str, ...] = ()
    infractions: tuple[GateInfraction, ...] = ()
    required_copy_fields: tuple[str, ...] = ()
    scoring_features: dict[str, float | None] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "action": self.action.value,
            "public_claim_allowed": self.public_claim_allowed,
            "monetization_allowed": self.monetization_allowed,
            "required_format_family": self.required_format_family,
            "blockers": list(self.blockers),
            "infractions": [infraction.value for infraction in self.infractions],
            "required_copy_fields": list(self.required_copy_fields),
            "scoring_features": self.scoring_features,
        }


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    """Load the trend/current-event gate policy JSON."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def validate_policy(payload: dict[str, Any]) -> list[str]:
    """Return human-readable policy contract violations."""

    errors: list[str] = []
    policy = payload.get("global_policy", {})
    required_true = {
        "trend_as_truth_allowed": False,
        "official_or_primary_source_required": True,
        "timestamped_freshness_required": True,
        "uncertainty_language_required": True,
        "under_24h_definitive_ranking_allowed": False,
        "sensitive_event_monetization_allowed": False,
    }
    for key, expected in required_true.items():
        if policy.get(key) is not expected:
            errors.append(f"global_policy.{key} must be {expected!r}")

    actions = {item.get("action") for item in payload.get("actions", []) if isinstance(item, dict)}
    for action in GateAction:
        if action.value not in actions:
            errors.append(f"missing action: {action.value}")

    infractions = set(payload.get("infractions", []))
    for infraction in GateInfraction:
        if infraction.value not in infractions:
            errors.append(f"missing infraction: {infraction.value}")

    feature_names = {
        item.get("feature_name")
        for item in payload.get("scoring_features", [])
        if isinstance(item, dict)
    }
    for feature_name in ("trend_decay_score", "source_bias_score"):
        if feature_name not in feature_names:
            errors.append(f"missing scoring feature: {feature_name}")

    return errors


def evaluate_candidate(
    candidate: TrendCurrentEventCandidate,
    *,
    policy: dict[str, Any] | None = None,
) -> TrendCurrentEventGateResult:
    """Evaluate a trend/current-event candidate into a public-surface action."""

    policy = policy or load_policy()
    blockers: list[str] = []
    infractions: list[GateInfraction] = []
    required_copy_fields = ["recency_label", "freshness_checked_at", "uncertainty_language"]
    action = GateAction.ALLOW_PUBLIC_CLAIM
    required_format_family: str | None = None
    public_claim_allowed = candidate.is_public
    monetization_allowed = candidate.public_mode == "public_monetizable" and candidate.monetized

    if candidate.trend_used_as_truth:
        blockers.append("trend_currentness_is_not_truth_warrant")
        infractions.append(GateInfraction.TREND_AS_TRUTH)
        action = GateAction.BLOCK_PUBLIC_CLAIM
        public_claim_allowed = False
        monetization_allowed = False

    if candidate.source_age_s is None or candidate.source_ttl_s is None:
        blockers.append("timestamped_source_freshness_missing")
        infractions.append(GateInfraction.MISSING_FRESHNESS)
        action = GateAction.BLOCK_PUBLIC_CLAIM
        public_claim_allowed = False
        monetization_allowed = False
    elif candidate.source_age_s > candidate.source_ttl_s:
        blockers.append("source_freshness_ttl_exceeded")
        infractions.append(GateInfraction.STALE_SOURCE)
        action = GateAction.BLOCK_PUBLIC_CLAIM
        public_claim_allowed = False
        monetization_allowed = False

    if not candidate.has_primary_or_official_source or candidate.corroborating_source_count < 2:
        blockers.append("primary_or_official_corroboration_missing")
        infractions.append(GateInfraction.MISSING_PRIMARY_OR_OFFICIAL_SOURCE)
        action = GateAction.BLOCK_PUBLIC_CLAIM
        public_claim_allowed = False
        monetization_allowed = False

    if not candidate.recency_label_present or not candidate.has_uncertainty_language:
        blockers.append("public_copy_uncertainty_or_recency_missing")
        infractions.append(GateInfraction.MISSING_UNCERTAINTY_LANGUAGE)
        if action is GateAction.ALLOW_PUBLIC_CLAIM:
            action = GateAction.DOWNGRADE_TO_WATCH
            required_format_family = "watching_or_audit"
        public_claim_allowed = False
        monetization_allowed = False

    if candidate.is_under_24h and candidate.proposed_format not in WATCH_FORMATS:
        blockers.append("under_24h_event_requires_watch_audit_or_refusal")
        infractions.append(GateInfraction.UNDER_24H_DEFINITIVE_FORMAT)
        if action is GateAction.ALLOW_PUBLIC_CLAIM:
            action = GateAction.DOWNGRADE_TO_WATCH
        required_format_family = "watching_or_audit"
        public_claim_allowed = False
        monetization_allowed = False

    if candidate.is_sensitive and (
        candidate.proposed_format not in WATCH_FORMATS or not candidate.edsa_context_present
    ):
        blockers.append("sensitive_event_requires_refusal_audit_and_edsa_context")
        infractions.append(GateInfraction.SENSITIVE_EVENT_EXPLOITATION)
        if action is not GateAction.BLOCK_PUBLIC_CLAIM:
            action = GateAction.FORCE_REFUSAL_FORMAT
        required_format_family = "refusal_or_audit"
        public_claim_allowed = False
        monetization_allowed = False

    if candidate.source_bias_score is None:
        blockers.append("source_bias_score_missing")
        infractions.append(GateInfraction.SOURCE_BIAS_UNTRACKED)
        if action is GateAction.ALLOW_PUBLIC_CLAIM:
            action = GateAction.DOWNGRADE_TO_WATCH
            required_format_family = "watching_or_audit"
        public_claim_allowed = False
        monetization_allowed = False

    if candidate.trend_decay_score is None:
        blockers.append("trend_decay_score_missing")
        if action is GateAction.ALLOW_PUBLIC_CLAIM:
            action = GateAction.DOWNGRADE_TO_WATCH
            required_format_family = "watching_or_audit"
        public_claim_allowed = False
        monetization_allowed = False

    if policy.get("global_policy", {}).get("sensitive_event_monetization_allowed") is False:
        if candidate.is_sensitive:
            monetization_allowed = False

    return TrendCurrentEventGateResult(
        candidate_id=candidate.candidate_id,
        action=action,
        public_claim_allowed=public_claim_allowed,
        monetization_allowed=monetization_allowed,
        required_format_family=required_format_family,
        blockers=tuple(dict.fromkeys(blockers)),
        infractions=tuple(dict.fromkeys(infractions)),
        required_copy_fields=tuple(required_copy_fields),
        scoring_features={
            "trend_decay_score": candidate.trend_decay_score,
            "source_bias_score": candidate.source_bias_score,
        },
    )
