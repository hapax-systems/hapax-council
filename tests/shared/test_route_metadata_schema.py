from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from shared.route_metadata_schema import (
    AuthorityLevel,
    FreshnessState,
    MutationSurface,
    QualityFloor,
    RouteMetadata,
    RouteMetadataStatus,
    assess_route_metadata,
    build_demand_vector,
    check_demand_vector_freshness,
    validate_route_metadata,
    verification_contract_structure_blockers,
    verification_contract_summary,
    verification_failure_blockers,
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


def test_verification_contract_accepts_auditable_safety_net_waiver() -> None:
    metadata = validate_route_metadata(
        {
            **_explicit_metadata(),
            "verification_surface": {
                "focused_checks": [
                    {
                        "name": "focused adapter tests",
                        "command": "uv run pytest tests/test_capability_adapter_protocol.py -q",
                    }
                ],
                "required_ci_checks": [{"name": "all-green", "contexts": ["all-green"]}],
                "full_safety_net_checks": [
                    {
                        "name": "pyright-safety-net",
                        "command": "uv run pyright",
                        "blocking": False,
                    }
                ],
                "baseline_waivers": [
                    {
                        "waiver_id": "baseline-pyright-20260625",
                        "check_name": "pyright-safety-net",
                        "witness": "/tmp/pyright-baseline.yaml",
                        "observed_at": "2026-06-25T18:19:00Z",
                        "expires_at": "2026-07-02T18:19:00Z",
                        "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline",
                        "affected_scope": ["agents/coordination_tui/**"],
                        "rationale": "Known pyright baseline outside the adapter mutation scope.",
                    }
                ],
                "allocation": {
                    "request_hardening": "targeted",
                    "review_intensity": "standard",
                    "verifier_intensity": "targeted",
                    "opportunity_cost": "full-suite baseline remediation is separate work",
                },
            },
        }
    )

    surface = metadata.verification_surface
    assert surface.required_ci_checks[0].contexts == ["all-green"]
    assert surface.full_safety_net_checks[0].blocking is False
    assert surface.baseline_waivers[0].tracking_ref.endswith("pyright-baseline")
    assert surface.allocation.request_hardening.value == "targeted"


def test_baseline_waiver_missing_witness_fails_schema_validation() -> None:
    assessment = assess_route_metadata(
        {
            **_explicit_metadata(),
            "verification_surface": {
                "full_safety_net_checks": [{"name": "pyright-safety-net"}],
                "baseline_waivers": [
                    {
                        "waiver_id": "baseline-pyright-20260625",
                        "check_name": "pyright-safety-net",
                        "observed_at": "2026-06-25T18:19:00Z",
                        "expires_at": "2026-07-02T18:19:00Z",
                        "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline",
                        "affected_scope": ["agents/coordination_tui/**"],
                        "rationale": "Known baseline outside this mutation scope.",
                    }
                ],
            },
        }
    )

    assert assessment.status == RouteMetadataStatus.MALFORMED
    assert any("baseline_waivers.0.witness" in error for error in assessment.validation_errors)


def test_baseline_waiver_mapping_scope_fails_schema_validation() -> None:
    assessment = assess_route_metadata(
        {
            **_explicit_metadata(),
            "verification_surface": {
                "full_safety_net_checks": [{"name": "pyright-safety-net"}],
                "baseline_waivers": [
                    {
                        "waiver_id": "baseline-pyright-20260625",
                        "check_name": "pyright-safety-net",
                        "witness": "/tmp/pyright-baseline.yaml",
                        "observed_at": "2026-06-25T18:19:00Z",
                        "expires_at": "2026-07-02T18:19:00Z",
                        "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline",
                        "affected_scope": {"path": "tests/test_demo.py"},
                        "rationale": "Known baseline outside this mutation scope.",
                    }
                ],
            },
        }
    )

    assert assessment.status == RouteMetadataStatus.MALFORMED
    assert any("affected_scope" in error for error in assessment.validation_errors)


def test_explicit_scalar_verification_surface_fails_closed() -> None:
    blockers = verification_contract_structure_blockers({"verification_surface": "full pyright"})

    assert blockers == ("verification_contract_malformed:verification_surface must be a mapping",)


def test_nested_scalar_verification_surface_fails_closed() -> None:
    blockers = verification_contract_structure_blockers(
        {"route_metadata": {"verification_surface": ["full pyright"]}}
    )

    assert blockers == (
        "verification_contract_malformed:route_metadata.verification_surface must be a mapping",
    )


def test_verification_failure_blockers_fail_closed_for_explicit_malformed_surface() -> None:
    blockers = verification_failure_blockers(
        {"verification_surface": ["full pyright"]},
        failed_checks=("pyright-safety-net",),
        touched_paths=("tests/test_capability_adapter_protocol.py",),
        now=datetime.fromisoformat("2026-06-25T19:00:00+00:00"),
    )

    assert blockers == ("verification_contract_malformed:verification_surface must be a mapping",)


def test_verification_failure_blockers_allow_current_out_of_scope_safety_net_waiver() -> None:
    frontmatter = {
        "verification_surface": {
            "full_safety_net_checks": [{"name": "pyright-safety-net", "blocking": False}],
            "baseline_waivers": [
                {
                    "waiver_id": "baseline-pyright-20260625",
                    "check_name": "pyright-safety-net",
                    "witness": "/tmp/pyright-baseline.yaml",
                    "observed_at": "2026-06-25T18:19:00Z",
                    "expires_at": "2026-07-02T18:19:00Z",
                    "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline",
                    "affected_scope": ["agents/coordination_tui/**"],
                    "rationale": "Known baseline outside this mutation scope.",
                }
            ],
        }
    }

    blockers = verification_failure_blockers(
        frontmatter,
        failed_checks=("pyright-safety-net",),
        touched_paths=("tests/test_capability_adapter_protocol.py",),
        now=datetime.fromisoformat("2026-06-25T19:00:00+00:00"),
    )

    assert blockers == ()


def test_verification_failure_blockers_ignore_non_safety_net_blocking_false() -> None:
    blockers = verification_failure_blockers(
        {
            "verification_surface": {
                "required_ci_checks": [
                    {"name": "all-green", "contexts": ["all-green"], "blocking": False}
                ],
            }
        },
        failed_checks=("all-green",),
        touched_paths=("tests/test_capability_adapter_protocol.py",),
        now=datetime.fromisoformat("2026-06-25T19:00:00+00:00"),
    )

    assert blockers == ("verification_failed_check:all-green",)


def test_verification_failure_blockers_fail_closed_for_future_dated_waiver() -> None:
    blockers = verification_failure_blockers(
        {
            "verification_surface": {
                "full_safety_net_checks": [{"name": "pyright-safety-net", "blocking": False}],
                "baseline_waivers": [
                    {
                        "waiver_id": "baseline-pyright-20260625",
                        "check_name": "pyright-safety-net",
                        "witness": "/tmp/pyright-baseline.yaml",
                        "observed_at": "2026-06-26T18:19:00Z",
                        "expires_at": "2026-07-02T18:19:00Z",
                        "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline",
                        "affected_scope": ["agents/coordination_tui/**"],
                        "rationale": "Known baseline outside this mutation scope.",
                    }
                ],
            }
        },
        failed_checks=("pyright-safety-net",),
        touched_paths=("tests/test_capability_adapter_protocol.py",),
        now=datetime.fromisoformat("2026-06-25T19:00:00+00:00"),
    )

    assert blockers == (
        "verification_safety_net_unwaived:"
        "pyright-safety-net:not_yet_observed:baseline-pyright-20260625",
    )


def test_verification_failure_blockers_fail_closed_for_opted_in_safety_net() -> None:
    blockers = verification_failure_blockers(
        {
            "verification_surface": {
                "full_safety_net_checks": [{"name": "pyright-safety-net", "blocking": True}],
                "baseline_waivers": [
                    {
                        "waiver_id": "baseline-pyright-20260625",
                        "check_name": "pyright-safety-net",
                        "witness": "/tmp/pyright-baseline.yaml",
                        "observed_at": "2026-06-25T18:19:00Z",
                        "expires_at": "2026-07-02T18:19:00Z",
                        "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline",
                        "affected_scope": ["agents/coordination_tui/**"],
                        "rationale": "Known baseline outside this mutation scope.",
                    }
                ],
            }
        },
        failed_checks=("pyright-safety-net",),
        touched_paths=("tests/test_capability_adapter_protocol.py",),
        now=datetime.fromisoformat("2026-06-25T19:00:00+00:00"),
    )

    assert blockers == ("verification_safety_net_opted_in:pyright-safety-net",)


def test_verification_failure_blockers_fail_closed_for_unknown_touched_scope() -> None:
    blockers = verification_failure_blockers(
        {
            "verification_surface": {
                "full_safety_net_checks": [{"name": "pyright-safety-net", "blocking": False}],
                "baseline_waivers": [
                    {
                        "waiver_id": "baseline-pyright-20260625",
                        "check_name": "pyright-safety-net",
                        "witness": "/tmp/pyright-baseline.yaml",
                        "observed_at": "2026-06-25T18:19:00Z",
                        "expires_at": "2026-07-02T18:19:00Z",
                        "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline",
                        "affected_scope": ["agents/coordination_tui/**"],
                        "rationale": "Known baseline outside this mutation scope.",
                    }
                ],
            }
        },
        failed_checks=("pyright-safety-net",),
        touched_paths=None,
        now=datetime.fromisoformat("2026-06-25T19:00:00+00:00"),
    )

    assert blockers == ("verification_safety_net_scope_unknown:pyright-safety-net",)


def test_verification_failure_blockers_fail_closed_for_implicated_safety_net_scope() -> None:
    frontmatter = {
        "verification_surface": {
            "full_safety_net_checks": [{"name": "pyright-safety-net", "blocking": False}],
            "baseline_waivers": [
                {
                    "waiver_id": "baseline-pyright-20260625",
                    "check_name": "pyright-safety-net",
                    "witness": "/tmp/pyright-baseline.yaml",
                    "observed_at": "2026-06-25T18:19:00Z",
                    "expires_at": "2026-07-02T18:19:00Z",
                    "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline",
                    "affected_scope": ["agents/coordination_tui/**"],
                    "rationale": "Known baseline outside this mutation scope.",
                }
            ],
        }
    }

    blockers = verification_failure_blockers(
        frontmatter,
        failed_checks=("pyright-safety-net",),
        touched_paths=("agents/coordination_tui/app.py",),
        now=datetime.fromisoformat("2026-06-25T19:00:00+00:00"),
    )

    assert blockers == (
        "verification_safety_net_implicated:pyright-safety-net:baseline-pyright-20260625",
    )


def test_verification_failure_blockers_fail_closed_for_any_implicated_current_waiver() -> None:
    blockers = verification_failure_blockers(
        {
            "verification_surface": {
                "full_safety_net_checks": [{"name": "pyright-safety-net", "blocking": False}],
                "baseline_waivers": [
                    {
                        "waiver_id": "baseline-pyright-out-of-scope",
                        "check_name": "pyright-safety-net",
                        "witness": "/tmp/pyright-baseline-out-of-scope.yaml",
                        "observed_at": "2026-06-25T18:19:00Z",
                        "expires_at": "2026-07-02T18:19:00Z",
                        "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline-a",
                        "affected_scope": ["agents/coordination_tui/**"],
                        "rationale": "Known baseline outside this mutation scope.",
                    },
                    {
                        "waiver_id": "baseline-pyright-touched-scope",
                        "check_name": "pyright-safety-net",
                        "witness": "/tmp/pyright-baseline-touched-scope.yaml",
                        "observed_at": "2026-06-25T18:20:00Z",
                        "expires_at": "2026-07-02T18:20:00Z",
                        "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline-b",
                        "affected_scope": ["tests/test_capability_adapter_protocol.py"],
                        "rationale": "Known baseline that overlaps this mutation scope.",
                    },
                ],
            }
        },
        failed_checks=("pyright-safety-net",),
        touched_paths=("tests/test_capability_adapter_protocol.py",),
        now=datetime.fromisoformat("2026-06-25T19:00:00+00:00"),
    )

    assert blockers == (
        "verification_safety_net_implicated:pyright-safety-net:baseline-pyright-touched-scope",
    )


@pytest.mark.parametrize(
    ("observed_at", "expires_at", "expected_state"),
    (
        (
            "2026-06-25T18:20:00Z",
            "2026-06-25T18:30:00Z",
            "expired",
        ),
        (
            "2026-06-25T20:20:00Z",
            "2026-07-02T18:20:00Z",
            "not_yet_observed",
        ),
    ),
)
def test_verification_failure_blockers_fail_closed_for_implicated_stale_waiver(
    observed_at: str,
    expires_at: str,
    expected_state: str,
) -> None:
    blockers = verification_failure_blockers(
        {
            "verification_surface": {
                "full_safety_net_checks": [{"name": "pyright-safety-net", "blocking": False}],
                "baseline_waivers": [
                    {
                        "waiver_id": "baseline-pyright-current-out-of-scope",
                        "check_name": "pyright-safety-net",
                        "witness": "/tmp/pyright-baseline-current-out-of-scope.yaml",
                        "observed_at": "2026-06-25T18:19:00Z",
                        "expires_at": "2026-07-02T18:19:00Z",
                        "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline-current",
                        "affected_scope": ["agents/coordination_tui/**"],
                        "rationale": "Known current baseline outside this mutation scope.",
                    },
                    {
                        "waiver_id": "baseline-pyright-stale-touched-scope",
                        "check_name": "pyright-safety-net",
                        "witness": "/tmp/pyright-baseline-stale-touched-scope.yaml",
                        "observed_at": observed_at,
                        "expires_at": expires_at,
                        "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline-stale",
                        "affected_scope": ["tests/test_capability_adapter_protocol.py"],
                        "rationale": "Stale evidence overlaps this mutation scope.",
                    },
                ],
            }
        },
        failed_checks=("pyright-safety-net",),
        touched_paths=("tests/test_capability_adapter_protocol.py",),
        now=datetime.fromisoformat("2026-06-25T19:00:00+00:00"),
    )

    assert blockers == (
        "verification_safety_net_unwaived:"
        f"pyright-safety-net:{expected_state}:baseline-pyright-stale-touched-scope",
    )


@pytest.mark.parametrize(
    "touched_path",
    ("agents/config.yaml", "agents/foo/bar/config.yaml"),
)
def test_verification_failure_blockers_match_recursive_globstar_scope(
    touched_path: str,
) -> None:
    blockers = verification_failure_blockers(
        {
            "verification_surface": {
                "full_safety_net_checks": [{"name": "pyright-safety-net", "blocking": False}],
                "baseline_waivers": [
                    {
                        "waiver_id": "baseline-pyright-recursive-scope",
                        "check_name": "pyright-safety-net",
                        "witness": "/tmp/pyright-baseline-recursive-scope.yaml",
                        "observed_at": "2026-06-25T18:20:00Z",
                        "expires_at": "2026-07-02T18:20:00Z",
                        "tracking_ref": ("CASE-CAPACITY-ROUTING-001#pyright-baseline-recursive"),
                        "affected_scope": ["agents/**/config.yaml"],
                        "rationale": "Known baseline that overlaps recursive config paths.",
                    }
                ],
            }
        },
        failed_checks=("pyright-safety-net",),
        touched_paths=(touched_path,),
        now=datetime.fromisoformat("2026-06-25T19:00:00+00:00"),
    )

    assert blockers == (
        "verification_safety_net_implicated:pyright-safety-net:baseline-pyright-recursive-scope",
    )


def test_verification_failure_blockers_ignore_nonmatching_recursive_globstar_scope() -> None:
    blockers = verification_failure_blockers(
        {
            "verification_surface": {
                "full_safety_net_checks": [{"name": "pyright-safety-net", "blocking": False}],
                "baseline_waivers": [
                    {
                        "waiver_id": "baseline-pyright-recursive-scope",
                        "check_name": "pyright-safety-net",
                        "witness": "/tmp/pyright-baseline-recursive-scope.yaml",
                        "observed_at": "2026-06-25T18:20:00Z",
                        "expires_at": "2026-07-02T18:20:00Z",
                        "tracking_ref": ("CASE-CAPACITY-ROUTING-001#pyright-baseline-recursive"),
                        "affected_scope": ["agents/**/config.yaml"],
                        "rationale": "Known baseline that overlaps recursive config paths.",
                    }
                ],
            }
        },
        failed_checks=("pyright-safety-net",),
        touched_paths=("tests/foo.py",),
        now=datetime.fromisoformat("2026-06-25T19:00:00+00:00"),
    )

    assert blockers == ()


def test_verification_contract_summary_preserves_waiver_and_check_audit_fields() -> None:
    summary = verification_contract_summary(
        {
            "verification_surface": {
                "required_ci_checks": [{"name": "all-green", "contexts": ["all-green"]}],
                "full_safety_net_checks": [
                    {
                        "name": "pyright-safety-net",
                        "command": "uv run pyright",
                        "blocking": False,
                        "touched_path_patterns": ["agents/coordination_tui/**"],
                    }
                ],
                "baseline_waivers": [
                    {
                        "waiver_id": "baseline-pyright-20260625",
                        "check_name": "pyright-safety-net",
                        "witness": "/tmp/pyright-baseline.yaml",
                        "observed_at": "2026-06-25T18:19:00Z",
                        "expires_at": "2026-07-02T18:19:00Z",
                        "tracking_ref": "CASE-CAPACITY-ROUTING-001#pyright-baseline",
                        "affected_scope": ["agents/coordination_tui/**"],
                        "rationale": "Known pyright baseline outside this task.",
                    }
                ],
            }
        }
    )

    assert summary["baseline_waivers"][0]["observed_at"] == "2026-06-25T18:19:00Z"
    assert summary["baseline_waivers"][0]["rationale"] == (
        "Known pyright baseline outside this task."
    )
    safety_net = summary["check_details"]["full_safety_net_checks"][0]
    assert safety_net["command"] == "uv run pyright"
    assert safety_net["effective_blocking"] is False
    assert safety_net["touched_path_patterns"] == ["agents/coordination_tui/**"]
    assert summary["check_details"]["required_ci_checks"][0]["effective_blocking"] is True


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
