"""Phase 6 audio routing policy contract helpers."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from shared import audio_loudness

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "audio-routing.yaml"

type RouteClass = Literal[
    "private",
    "notification",
    "broadcast_voice",
    "broadcast_content",
    "default_multimedia",
    "instrument",
    "monitor_bridge",
]
type ArtifactStatus = Literal["generated", "hand_mirrored", "non_round_trippable"]
type EligibilityBasis = Literal[
    "explicit_policy",
    "private_refused",
    "blocked_until_smoke",
    "non_round_trippable",
]

PRIVATE_ROUTE_CLASSES: frozenset[RouteClass] = frozenset(
    {"private", "notification", "monitor_bridge"}
)


class AudioRoutingPolicyError(ValueError):
    """Raised when audio route policy violates fail-closed invariants."""


class PolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GeneratedOutput(PolicyModel):
    output_dir: str
    manifest_path: str
    # Audit F#8 (2026-05-02): generator gained LADSPA loudnorm / duck /
    # usb-bias chain templates so generated_conf_writes_allowed = true
    # is now a supported (and live) configuration. live_reload_allowed
    # + dry_run_only stay locked — host-side PipeWire reload is still
    # operator-driven, the generator is no longer.
    generated_conf_writes_allowed: bool
    live_reload_allowed: Literal[False]
    dry_run_only: Literal[True]


class ConstantValue(PolicyModel):
    constant_ref: str
    value: float


class DuckConstantValue(PolicyModel):
    constant_ref: str
    value_db: float


class LoudnessConstants(PolicyModel):
    module: Literal["shared/audio_loudness.py"]
    pre_norm_target_lufs_i: ConstantValue
    pre_norm_true_peak_dbtp: ConstantValue
    egress_target_lufs_i: ConstantValue
    egress_true_peak_dbtp: ConstantValue


class DuckingConstants(PolicyModel):
    module: Literal["shared/audio_loudness.py"]
    operator_voice: DuckConstantValue
    tts: DuckConstantValue


class FailClosedPolicy(PolicyModel):
    unknown_source_broadcast_eligible: Literal[False]
    default_sink_fallback_broadcast_eligible: Literal[False]
    private_route_broadcast_eligible: Literal[False]
    notification_route_broadcast_eligible: Literal[False]
    missing_rights_broadcast_eligible: Literal[False]
    missing_provenance_broadcast_eligible: Literal[False]
    missing_generated_artifact_owner_broadcast_eligible: Literal[False]


class PreNormalizationPolicy(PolicyModel):
    target_lufs_i: float | None
    constant_ref: str | None


class RoutePolicy(PolicyModel):
    source_id: str
    producer: str
    role: str
    pipewire_node: str
    target_chain: tuple[str, ...]
    route_class: RouteClass
    broadcast_eligible: bool
    public_claim_allowed: bool
    broadcast_eligibility_basis: EligibilityBasis
    default_fallback_allowed: Literal[False]
    rights_required: bool
    provenance_required: bool
    provenance_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    pre_normalization: PreNormalizationPolicy
    ducked_by: tuple[Literal["operator_voice", "tts"], ...] = Field(default_factory=tuple)
    generated_artifact_owner: ArtifactStatus
    artifact_refs: tuple[str, ...]


class ArtifactMapping(PolicyModel):
    path: str
    status: ArtifactStatus
    owner: str
    reason: str


class FollowOn(PolicyModel):
    id: str
    reason: str


class AudioRoutingPolicy(PolicyModel):
    schema_version: Literal[1]
    policy_id: str
    description: str
    generated_output: GeneratedOutput
    loudness_constants: LoudnessConstants
    ducking_constants: DuckingConstants
    fail_closed_policy: FailClosedPolicy
    routes: tuple[RoutePolicy, ...]
    artifacts: tuple[ArtifactMapping, ...]
    follow_ons: tuple[FollowOn, ...]

    def broadcast_eligible_source_ids(self) -> tuple[str, ...]:
        return tuple(route.source_id for route in self.routes if route.broadcast_eligible)

    def artifact_paths(self) -> set[str]:
        return {artifact.path for artifact in self.artifacts}


def load_audio_routing_policy(path: Path | None = None) -> AudioRoutingPolicy:
    source = path or DEFAULT_POLICY_PATH
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    policy = AudioRoutingPolicy.model_validate(payload)
    assert_audio_routing_policy(policy)
    return policy


def assert_audio_routing_policy(policy: AudioRoutingPolicy) -> None:
    errors = list(audio_routing_policy_errors(policy))
    if errors:
        raise AudioRoutingPolicyError("; ".join(errors))


def audio_routing_policy_errors(policy: AudioRoutingPolicy) -> tuple[str, ...]:
    errors: list[str] = []
    seen_sources: set[str] = set()
    artifact_paths = policy.artifact_paths()

    for route in policy.routes:
        if route.source_id in seen_sources:
            errors.append(f"duplicate source_id: {route.source_id}")
        seen_sources.add(route.source_id)

        if route.default_fallback_allowed:
            errors.append(f"{route.source_id}: default fallback is not allowed")

        if route.route_class in PRIVATE_ROUTE_CLASSES and route.broadcast_eligible:
            errors.append(f"{route.source_id}: private route cannot be broadcast eligible")

        if route.broadcast_eligible:
            if route.broadcast_eligibility_basis != "explicit_policy":
                errors.append(f"{route.source_id}: broadcast eligibility must be explicit")
            if not route.rights_required:
                errors.append(f"{route.source_id}: broadcast eligibility requires rights gate")
            if not route.provenance_required:
                errors.append(f"{route.source_id}: broadcast eligibility requires provenance")
            if not route.provenance_refs:
                errors.append(f"{route.source_id}: broadcast eligibility needs provenance refs")
            if not route.evidence_refs:
                errors.append(f"{route.source_id}: broadcast eligibility needs evidence refs")

        missing_artifacts = set(route.artifact_refs) - artifact_paths
        if missing_artifacts:
            errors.append(
                f"{route.source_id}: artifact refs lack ownership rows: {sorted(missing_artifacts)}"
            )

        if route.pre_normalization.constant_ref is not None:
            expected = _constant_value(route.pre_normalization.constant_ref)
            if route.pre_normalization.target_lufs_i != expected:
                errors.append(
                    f"{route.source_id}: pre-normalization target does not match "
                    f"{route.pre_normalization.constant_ref}"
                )

    for name, constant in {
        "pre_norm_target_lufs_i": policy.loudness_constants.pre_norm_target_lufs_i,
        "pre_norm_true_peak_dbtp": policy.loudness_constants.pre_norm_true_peak_dbtp,
        "egress_target_lufs_i": policy.loudness_constants.egress_target_lufs_i,
        "egress_true_peak_dbtp": policy.loudness_constants.egress_true_peak_dbtp,
    }.items():
        if constant.value != _constant_value(constant.constant_ref):
            errors.append(f"{name}: value does not match {constant.constant_ref}")

    for name, constant in {
        "operator_voice": policy.ducking_constants.operator_voice,
        "tts": policy.ducking_constants.tts,
    }.items():
        if constant.value_db != _constant_value(constant.constant_ref):
            errors.append(f"{name}: value_db does not match {constant.constant_ref}")

    return tuple(errors)


def audio_routing_manifest(policy: AudioRoutingPolicy) -> dict[str, object]:
    artifact_status_counts = Counter(artifact.status for artifact in policy.artifacts)
    blocked_source_ids = sorted(
        route.source_id for route in policy.routes if not route.broadcast_eligible
    )
    private_source_ids = sorted(
        route.source_id for route in policy.routes if route.route_class in PRIVATE_ROUTE_CLASSES
    )

    return {
        "schema_version": 1,
        "policy_id": policy.policy_id,
        "generated_from": "config/audio-routing.yaml",
        "dry_run_only": policy.generated_output.dry_run_only,
        "generated_conf_writes_allowed": policy.generated_output.generated_conf_writes_allowed,
        "live_reload_allowed": policy.generated_output.live_reload_allowed,
        "broadcast_eligible_source_ids": sorted(policy.broadcast_eligible_source_ids()),
        "blocked_source_ids": blocked_source_ids,
        "private_source_ids": private_source_ids,
        "unknown_source_broadcast_eligible": False,
        "default_sink_fallback_broadcast_eligible": False,
        "artifact_status_counts": dict(sorted(artifact_status_counts.items())),
        "artifact_paths": sorted(policy.artifact_paths()),
    }


def audio_routing_manifest_json(policy: AudioRoutingPolicy) -> str:
    return json.dumps(audio_routing_manifest(policy), indent=2, sort_keys=True) + "\n"


def _constant_value(name: str) -> float:
    value = getattr(audio_loudness, name)
    if not isinstance(value, int | float):
        raise AudioRoutingPolicyError(f"{name}: loudness constant is not numeric")
    return float(value)
