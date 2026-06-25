from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.route_metadata_schema import (
    AuthorityLevel,
    ClassificationEnvelope,
    FreshnessState,
    HardeningIntensity,
    LearningEligibility,
    MutationSurface,
    QualityFloor,
    RouteAdmissionAction,
    RouteMetadata,
    RouteMetadataStatus,
    assess_route_metadata,
    build_demand_vector,
    check_demand_vector_freshness,
    validate_route_metadata,
)


def _explicit_metadata() -> dict[str, object]:
    return {
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["isap:CASE-CAPACITY-ROUTING-001/ROUTE-METADATA-SCHEMA"],
        "risk_flags": {
            "governance_sensitive": True,
            "privacy_or_secret_sensitive": False,
            "public_claim_sensitive": False,
            "aesthetic_theory_sensitive": False,
            "audio_or_live_egress_sensitive": False,
            "provider_billing_sensitive": False,
        },
        "context_shape": {
            "codebase_locality": "module",
            "vault_context_required": True,
            "external_docs_required": False,
            "currentness_required": False,
        },
        "verification_surface": {
            "deterministic_tests": ["uv run pytest tests/shared/test_route_metadata_schema.py"],
            "static_checks": ["uv run ruff check shared/route_metadata_schema.py"],
            "runtime_observation": [],
            "operator_only": False,
        },
        "route_constraints": {
            "preferred_platforms": ["codex"],
            "allowed_platforms": [],
            "prohibited_platforms": ["jr"],
            "required_mode": "headless",
            "required_profile": "full",
        },
        "review_requirement": {
            "support_artifact_allowed": False,
            "independent_review_required": False,
            "authoritative_acceptor_profile": None,
        },
    }


def _valid_classification_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "label": "source_python",
        "classifier": "test.deterministic",
        "source_kind": "deterministic",
        "confidence": 0.92,
        "evidence_refs": ["test:classification-evidence"],
        "freshness": "fresh",
        "authority_ceiling": "authoritative",
        "validity_mask": {
            "label": True,
            "source": True,
            "confidence": True,
            "freshness": True,
            "authority_ceiling": True,
        },
        "deterministic_facts_used": ["mutation_surface:source", "quality_floor:frontier_required"],
        "consumer_floor": "frontier_required",
    }
    payload.update(overrides)
    return payload


def test_full_explicit_route_metadata_validates() -> None:
    metadata = validate_route_metadata(_explicit_metadata())

    assert metadata.quality_floor == QualityFloor.FRONTIER_REQUIRED
    assert metadata.authority_level == AuthorityLevel.AUTHORITATIVE
    assert metadata.mutation_surface == MutationSurface.SOURCE
    assert metadata.risk_flags.governance_sensitive is True


def test_conservative_derivation_from_existing_task_fields() -> None:
    assessment = assess_route_metadata(
        {
            "type": "cc-task",
            "task_id": "source-task",
            "title": "Source Task",
            "kind": "implementation",
            "risk_tier": "T1",
            "authority_case": "CASE-TEST-001",
            "parent_spec": "/tmp/spec.md",
            "tags": ["governance"],
        }
    )

    assert assessment.status == RouteMetadataStatus.DERIVED
    assert assessment.metadata is not None
    assert assessment.metadata.quality_floor == QualityFloor.FRONTIER_REQUIRED
    assert assessment.metadata.mutation_surface == MutationSurface.SOURCE
    assert assessment.metadata.risk_flags.governance_sensitive is True


def test_cloud_burst_derives_spike_workload_thresholds() -> None:
    assessment = assess_route_metadata(
        {
            "type": "cc-task",
            "task_id": "spike-task",
            "title": "CI matrix release fanout",
            "kind": "implementation",
            "risk_tier": "T1",
            "authority_case": "CASE-TEST-001",
            "parent_spec": "/tmp/spec.md",
            "estimated_parallel_jobs": 12,
            "agent_fanout": 5,
            "public_repo_only": True,
            "read_mostly": True,
            "cloud_burst_budget_ref": "tb-test-cloud-burst",
        }
    )

    assert assessment.status == RouteMetadataStatus.DERIVED
    assert assessment.metadata is not None
    cloud_burst = assessment.metadata.cloud_burst
    assert cloud_burst.eligible is True
    assert "high_parallelism:12" in cloud_burst.spike_reasons
    assert "multi_agent_fanout:5" in cloud_burst.spike_reasons
    assert cloud_burst.public_repo_only is True
    assert cloud_burst.read_mostly is True
    assert cloud_burst.provider_budget_ref == "tb-test-cloud-burst"


def test_cloud_burst_eligibility_fails_closed_on_secret_egress() -> None:
    assessment = assess_route_metadata(
        {
            **_explicit_metadata(),
            "cloud_burst": {
                "eligible": True,
                "spike_reasons": ["high_parallelism:12"],
                "no_secret_egress": False,
                "public_repo_only": True,
                "read_mostly": True,
                "provider_budget_ref": "tb-test-cloud-burst",
            },
        }
    )

    assert assessment.status == RouteMetadataStatus.MALFORMED
    assert any("no_secret_egress" in error for error in assessment.validation_errors)


def _derived_risk_flags(title: str, tags: list[str] | None = None):
    assessment = assess_route_metadata(
        {
            "type": "cc-task",
            "task_id": "risk-flag-token-task",
            "title": title,
            "kind": "implementation",
            "risk_tier": "T1",
            "authority_case": "CASE-TEST-001",
            "parent_spec": "/tmp/spec.md",
            "tags": tags or [],
        }
    )
    assert assessment.metadata is not None
    return assessment.metadata.risk_flags


def test_risk_flag_derivation_matches_whole_words_not_substrings() -> None:
    # 'egress' is a substring of 'regression' and 'live' of 'deliver'. A raw
    # substring match false-flags routine titles as audio/live/egress
    # sensitive, vetoing system auto-arm and stranding their green PRs.
    flags = _derived_risk_flags("fix regression in deliver path")
    assert flags.audio_or_live_egress_sensitive is False


def test_risk_flag_derivation_still_flags_genuine_tokens() -> None:
    flags = _derived_risk_flags("live egress stream", tags=["audio"])
    assert flags.audio_or_live_egress_sensitive is True


def test_risk_flag_derivation_matches_token_inside_hyphenated_tag() -> None:
    # Hyphens delimit tokens, so a marker word inside a compound tag still
    # counts (audio-egress -> {'audio', 'egress'}).
    flags = _derived_risk_flags("routine task", tags=["audio-egress"])
    assert flags.audio_or_live_egress_sensitive is True


def test_risk_flag_derivation_does_not_treat_go_live_as_live_egress() -> None:
    flags = _derived_risk_flags(
        "Go-live D2 bootstrap: stable recovery bundle machinery",
        tags=["go-live", "detection-plane", "recovery", "systemd"],
    )
    assert flags.audio_or_live_egress_sensitive is False


def test_risk_flag_derivation_still_flags_go_live_with_real_egress_marker() -> None:
    flags = _derived_risk_flags("Go-live broadcast egress guard", tags=["go-live"])
    assert flags.audio_or_live_egress_sensitive is True


def test_risk_flag_derivation_governance_substring_does_not_false_trip() -> None:
    # 'policy' must not match inside an unrelated compound like 'policyholder'.
    flags = _derived_risk_flags("policyholder records cleanup")
    assert flags.governance_sensitive is False


def test_missing_quality_floor_is_hold_not_permissive() -> None:
    assessment = assess_route_metadata(
        {
            "type": "cc-task",
            "task_id": "underspecified",
            "title": "Underspecified Task",
            "authority_case": "CASE-TEST-001",
        }
    )

    assert assessment.status == RouteMetadataStatus.HOLD
    assert "quality_floor" in assessment.missing_fields
    assert "missing_quality_floor" in assessment.hold_reasons
    assert assessment.dispatchable is False


def test_mutation_surface_unknown_is_hold_condition() -> None:
    assessment = assess_route_metadata(
        {
            "type": "cc-task",
            "task_id": "risk-known-surface-unknown",
            "title": "Risk Known Surface Unknown",
            "risk_tier": "T1",
            "authority_case": "CASE-TEST-001",
        }
    )

    assert assessment.status == RouteMetadataStatus.HOLD
    assert "mutation_surface" in assessment.missing_fields
    assert "missing_mutation_surface" in assessment.hold_reasons


def test_malformed_explicit_route_metadata_reports_validation_errors() -> None:
    assessment = assess_route_metadata(
        {
            "route_metadata_schema": 1,
            "quality_floor": "spark_is_fine",
            "authority_level": "authoritative",
            "mutation_surface": "source",
        }
    )

    assert assessment.status == RouteMetadataStatus.MALFORMED
    assert assessment.validation_errors


def test_support_artifact_requires_independent_frontier_review() -> None:
    payload = {
        "route_metadata_schema": 1,
        "quality_floor": "frontier_review_required",
        "authority_level": "support_non_authoritative",
        "mutation_surface": "vault_docs",
        "review_requirement": {
            "support_artifact_allowed": True,
            "independent_review_required": True,
            "authoritative_acceptor_profile": "frontier_full",
        },
    }

    metadata = RouteMetadata.model_validate(payload)
    assert metadata.quality_floor == QualityFloor.FRONTIER_REVIEW_REQUIRED

    payload["authority_level"] = "authoritative"
    with pytest.raises(ValidationError, match="cannot be authoritative directly"):
        RouteMetadata.model_validate(payload)


def test_missing_route_envelope_defaults_fail_closed_without_breaking_flat_metadata() -> None:
    metadata = RouteMetadata.model_validate(_explicit_metadata())

    envelope = metadata.route_envelope
    assert envelope.classification_envelope.label == "unknown"
    assert envelope.admission.admission_action is RouteAdmissionAction.HOLD
    assert "route_envelope_missing" in envelope.admission.reason_codes
    assert envelope.learning_eligibility.thompson_update_allowed is False
    assert envelope.learning_eligibility.local_posterior_update_allowed is False


def test_low_confidence_classification_can_only_hold_or_shadow() -> None:
    payload = {
        **_explicit_metadata(),
        "route_envelope": {
            "classification_envelope": _valid_classification_payload(confidence=0.4),
            "admission": {"admission_action": "route", "reason_codes": ["bad"]},
        },
    }

    with pytest.raises(ValidationError, match="low-confidence classification"):
        RouteMetadata.model_validate(payload)

    payload["route_envelope"] = {
        "classification_envelope": _valid_classification_payload(confidence=0.4),
        "admission": {"admission_action": "shadow", "reason_codes": ["low_confidence"]},
    }
    metadata = RouteMetadata.model_validate(payload)
    assert metadata.route_envelope.admission.admission_action is RouteAdmissionAction.SHADOW


def test_high_confidence_classification_requires_justifying_evidence() -> None:
    with pytest.raises(ValidationError, match="high-confidence classification"):
        ClassificationEnvelope.model_validate(
            _valid_classification_payload(
                evidence_refs=[],
                deterministic_facts_used=[],
                validity_mask={"label": True},
            )
        )


def test_classification_validity_mask_must_contain_required_keys_for_dispatch() -> None:
    with pytest.raises(ValidationError, match="fully valid mask"):
        ClassificationEnvelope.model_validate(
            _valid_classification_payload(validity_mask={"label": True})
        )

    envelope = ClassificationEnvelope.model_validate(
        _valid_classification_payload(confidence=0.4, validity_mask={"label": True})
    )
    assert envelope.valid_for_dispatch is False


def test_benchmark_gap_and_public_projection_round_trip_through_demand_vector() -> None:
    demand = build_demand_vector(
        {
            **_explicit_metadata(),
            "task_id": "benchmark-public-projection",
            "authority_case": "CASE-TEST-001",
            "route_envelope": {
                "classification_envelope": _valid_classification_payload(),
                "admission": {"admission_action": "route", "reason_codes": ["fresh"]},
                "benchmark_gap": {
                    "coverage": {
                        "coverage_state": "absent",
                        "gap_refs": ["eval-ledger:missing-slice"],
                        "evidence_refs": ["eval-ledger:gap-review"],
                    },
                    "public_candidate": True,
                    "meaningful_sdlc_slice": True,
                    "public_benchmarks_absent_or_stale": True,
                    "hapax_operational_value": True,
                    "external_utility": True,
                    "exposes_llm_failure_mode": True,
                    "gap_summary": "No public benchmark covers governed SDLC routing envelopes.",
                    "evidence_refs": ["eval-ledger:gap-review"],
                },
                "public_release_projection": {
                    "projection_state": "candidate",
                    "may_create_public_claim": True,
                    "publication_authorized": False,
                    "evidence_refs": ["research-export-ledger:pending"],
                },
            },
        }
    )

    envelope = demand.route_envelope
    assert envelope.benchmark_gap.public_candidate is True
    assert envelope.public_release_projection.public_projection_forbidden is True
    assert envelope.model_dump(mode="json")["benchmark_gap"]["coverage"]["coverage_state"] == (
        "absent"
    )


def test_hardening_allocation_derives_from_public_ambiguous_source_work() -> None:
    assessment = assess_route_metadata(
        {
            "type": "cc-task",
            "task_id": "hardening-task",
            "title": "Ambiguous public routing claim",
            "kind": "implementation",
            "risk_tier": "T1",
            "authority_case": "CASE-TEST-001",
            "parent_spec": "/tmp/spec.md",
            "tags": ["public", "ambiguous"],
        }
    )

    assert assessment.metadata is not None
    hardening = assessment.metadata.route_envelope.hardening_allocation
    assert hardening.hardening_intensity is HardeningIntensity.TARGETED
    assert set(hardening.axes) >= {"public_release", "ambiguity", "implementation"}
    assert hardening.request_claims_as_priors is True


def test_learning_updates_reject_stale_inferred_redacted_support_hkp_and_public_projection() -> (
    None
):
    allowed = {
        "thompson_update_allowed": True,
        "local_posterior_update_allowed": True,
        "evidence_kind": "witnessed",
        "evidence_freshness": "fresh",
        "confidence": 0.9,
        "envelope_valid": True,
        "support_only": False,
        "hkp_only": False,
        "public_projection_forbidden": False,
        "evidence_refs": ["witness:route-success"],
    }
    disallowed_cases = (
        {"evidence_freshness": "stale"},
        {"evidence_kind": "inferred"},
        {"evidence_kind": "supplied_only"},
        {"evidence_kind": "redacted"},
        {"confidence": 0.7},
        {"envelope_valid": False},
        {"support_only": True},
        {"hkp_only": True},
        {"public_projection_forbidden": True},
    )

    LearningEligibility.model_validate(allowed)
    for update in disallowed_cases:
        with pytest.raises(ValidationError):
            LearningEligibility.model_validate({**allowed, **update})


def test_hkp_classification_is_non_authoritative_support_only() -> None:
    with pytest.raises(ValidationError, match="HKP cache classification"):
        ClassificationEnvelope.model_validate(
            _valid_classification_payload(
                source_kind="hkp_cache",
                authority_ceiling="authoritative",
            )
        )

    hkp = ClassificationEnvelope.model_validate(
        _valid_classification_payload(
            source_kind="hkp_cache",
            authority_ceiling="support_only",
        )
    )
    assert hkp.authority_ceiling.value == "support_only"


def test_supply_history_projects_benchmark_calibration_and_bounded_overhead_score() -> None:
    from shared.dispatcher_policy import _fixed_route_overhead_fit_score
    from shared.platform_capability_registry import (
        build_supply_vector,
        load_platform_capability_registry,
    )
    from shared.route_metadata_schema import BenchmarkCoverage, FixedRouteOverhead

    registry = load_platform_capability_registry()
    route = registry.require("codex.headless.full")
    history = route.historical_performance.model_copy(
        update={
            "benchmark_coverage": BenchmarkCoverage(
                coverage_state="partial",
                benchmark_refs=["benchmark:capacity-routing"],
                evidence_refs=["eval-ledger:capacity-routing"],
            ),
            "fixed_route_overhead": FixedRouteOverhead(
                fixed_cost_score=5,
                setup_seconds=120,
                context_tokens=8000,
                coordination_steps=3,
                evidence_refs=["route-history:codex-full-overhead"],
            ),
        }
    )
    supply = build_supply_vector(route.model_copy(update={"historical_performance": history}))

    assert supply.historical_performance.benchmark_coverage.coverage_state.value == "partial"
    assert supply.historical_performance.fixed_route_overhead.fixed_cost_score == 5
    assert _fixed_route_overhead_fit_score(5, 5) == 1.0
    assert _fixed_route_overhead_fit_score(5, 0) == 5.0


def test_demand_vector_hashes_frontmatter_and_source_refs(tmp_path) -> None:
    task_note = tmp_path / "task.md"
    parent_spec = tmp_path / "spec.md"
    parent_spec.write_text("---\ncase_id: CASE-TEST-001\n---\n", encoding="utf-8")
    task_note.write_text("---\ntask_id: source-task\n---\n", encoding="utf-8")
    frontmatter = {
        **_explicit_metadata(),
        "task_id": "source-task",
        "authority_case": "CASE-TEST-001",
        "parent_spec": str(parent_spec),
        "priority": "p0",
        "wsjf": 14.0,
    }

    demand = build_demand_vector(frontmatter, note_path=task_note)

    assert demand.demand_vector_schema == 1
    assert demand.routing_model_version == "capacity-dimensional-v1"
    assert demand.work_item.frontmatter_hash.startswith("sha256:")
    assert demand.work_item.authority_case == "CASE-TEST-001"
    assert demand.task_demand.authority_class == "source_mutation"
    assert {ref.source_id for ref in demand.source_refs} >= {"task_note", "parent_spec"}


def test_demand_vector_freshness_stales_when_frontmatter_changes(tmp_path) -> None:
    task_note = tmp_path / "task.md"
    task_note.write_text("---\ntask_id: source-task\n---\n", encoding="utf-8")
    frontmatter = {
        **_explicit_metadata(),
        "task_id": "source-task",
        "authority_case": "CASE-TEST-001",
        "title": "Original",
    }
    demand = build_demand_vector(frontmatter, note_path=task_note)

    freshness = check_demand_vector_freshness(
        demand,
        {**frontmatter, "title": "Changed"},
        note_path=task_note,
    )

    assert freshness.freshness_state is FreshnessState.STALE
    assert "frontmatter_hash_changed" in freshness.stale_reasons


# --------------------------------------------------------------------------------------
# Execution-axis demands (effort_demand / context_mode_demand) — the dispatcher-dims slice
# --------------------------------------------------------------------------------------
def test_demand_axis_vocabulary_pins_the_registry_enums() -> None:
    """FORK 1 closed without an import cycle: the lower module's demand value tuples MUST track
    the supply-side Effort/ContextMode enums exactly (drift either way fails this pin)."""
    from shared.platform_capability_registry import ContextMode, Effort
    from shared.route_metadata_schema import (
        _CONTEXT_MODE_DEMAND_VALUES,
        _EFFORT_DEMAND_VALUES,
    )

    assert {e.value for e in Effort} == set(_EFFORT_DEMAND_VALUES)
    assert {c.value for c in ContextMode} == set(_CONTEXT_MODE_DEMAND_VALUES)


def _demand_frontmatter(**task_demand: object) -> dict[str, object]:
    payload = _explicit_metadata()
    payload["task_id"] = "demand-axis-test"
    payload["authority_case"] = "CASE-TEST-001"
    if task_demand:
        payload["task_demand"] = dict(task_demand)
    return payload


def test_task_demand_execution_axes_default_to_none() -> None:
    demand = build_demand_vector(_demand_frontmatter())
    assert demand.task_demand.effort_demand is None
    assert demand.task_demand.context_mode_demand is None


def test_task_demand_accepts_valid_execution_axis_demands() -> None:
    demand = build_demand_vector(
        _demand_frontmatter(effort_demand="low", context_mode_demand="extended_1m")
    )
    assert demand.task_demand.effort_demand == "low"
    assert demand.task_demand.context_mode_demand == "extended_1m"


def test_task_demand_rejects_out_of_vocab_execution_axis_demand() -> None:
    with pytest.raises((ValidationError, ValueError)):
        build_demand_vector(_demand_frontmatter(effort_demand="galaxy"))
    with pytest.raises((ValidationError, ValueError)):
        build_demand_vector(_demand_frontmatter(context_mode_demand="hypercontext"))
