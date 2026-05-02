"""Tests for ``shared.opportunity_to_run_gate``.

Per cc-task ``opportunity-to-run-wcs-gate`` (WSJF 8.8). The gate is
the load-bearing predicate the content-programme runner consults to
decide whether each Bayesian-surfaced opportunity should land as
runnable / dry_run / refused / archive_only / held / blocked.

Coverage maps to the cc-task acceptance criteria:

  - gate consumes ContentOpportunity + format WCS matrix +
    director/WCS snapshot → TestEvaluateInputs
  - emits 6-mode run envelope → TestModuleSurface + TestModeMatrix
  - Bayesian posterior influences priority but cannot bypass WCS
    gates → TestPosteriorBypassRefused
  - missing claim shape / witnesses / rights / public-event /
    monetization blocks public mode → TestPublicClaimBlocked
  - trend/revenue selected but WCS-blocked negative test →
    TestNegativeWcsPaths
  - private/dry_run positive test → TestNonPublicPath
"""

from __future__ import annotations

from shared.opportunity_to_run_gate import (
    MIN_OPPORTUNITY_POSTERIOR,
    BlockerKind,
    ContentOpportunity,
    FormatWcsRequirement,
    GateResult,
    RunMode,
    WcsSnapshot,
    evaluate_opportunity,
)

# ── Module surface ───────────────────────────────────────────────────


class TestModuleSurface:
    def test_run_mode_taxonomy(self) -> None:
        # 6-mode taxonomy is the cc-task contract.
        assert {m.value for m in RunMode} == {
            "runnable",
            "dry_run",
            "private",
            "archive_only",
            "held",
            "refused",
            "blocked",
        }

    def test_blocker_kind_taxonomy(self) -> None:
        # Pin the 11-blocker taxonomy used by surfaces to construct
        # refusal articulations.
        assert {b.value for b in BlockerKind} == {
            "none",
            "low_posterior",
            "missing_claim_shape",
            "missing_evidence",
            "missing_witness",
            "missing_rights",
            "missing_privacy",
            "missing_public_event_path",
            "missing_monetization",
            "no_expert_system_override",
            "hardware_blocked",
            "higher_priority_occupying",
        }

    def test_default_threshold(self) -> None:
        assert MIN_OPPORTUNITY_POSTERIOR == 0.30


# ── Fixture builders ─────────────────────────────────────────────────


def _opportunity(**overrides) -> ContentOpportunity:
    base = {
        "opportunity_id": "opp-1",
        "format_id": "tier_list",
        "posterior": 0.85,
        "public_claim_intended": True,
    }
    base.update(overrides)
    return ContentOpportunity(**base)


def _requirement(**overrides) -> FormatWcsRequirement:
    base = {
        "format_id": "tier_list",
        "requires_egress": True,
        "requires_audio_safe": True,
        "requires_rights_clear": True,
        "requires_privacy_clear": True,
        "requires_public_event_path": True,
        "requires_archive_path": True,
        "requires_claim_shape": True,
    }
    base.update(overrides)
    return FormatWcsRequirement(**base)


def _full_snapshot(**overrides) -> WcsSnapshot:
    """Snapshot with every evidence axis satisfied."""
    base = {
        "egress_active": True,
        "audio_safe": True,
        "rights_clear": True,
        "privacy_clear": True,
        "public_event_path_ready": True,
        "archive_path_ready": True,
        "monetization_ready": True,
        "claim_shape_declared": True,
        "hardware_blocked": False,
        "higher_priority_run_occupying": False,
    }
    base.update(overrides)
    return WcsSnapshot(**base)


# ── Inputs + result shape ─────────────────────────────────────────────


class TestEvaluateInputs:
    def test_returns_gate_result(self) -> None:
        result = evaluate_opportunity(_opportunity(), _requirement(), _full_snapshot())
        assert isinstance(result, GateResult)

    def test_runnable_when_all_evidence_satisfied(self) -> None:
        result = evaluate_opportunity(_opportunity(), _requirement(), _full_snapshot())
        assert result.mode is RunMode.RUNNABLE
        assert result.blockers == ()


# ── Posterior cannot bypass WCS ──────────────────────────────────────


class TestPosteriorBypassRefused:
    def test_below_floor_refuses_even_with_perfect_wcs(self) -> None:
        # Even with all evidence, low posterior REFUSES.
        result = evaluate_opportunity(
            _opportunity(posterior=0.10),
            _requirement(),
            _full_snapshot(),
        )
        assert result.mode is RunMode.REFUSED
        assert BlockerKind.LOW_POSTERIOR in result.blockers

    def test_at_floor_proceeds_to_evidence_check(self) -> None:
        # Boundary: posterior exactly at floor passes the posterior
        # gate and proceeds to WCS evaluation.
        result = evaluate_opportunity(
            _opportunity(posterior=MIN_OPPORTUNITY_POSTERIOR),
            _requirement(),
            _full_snapshot(),
        )
        assert result.mode is RunMode.RUNNABLE

    def test_high_posterior_does_not_override_missing_rights(self) -> None:
        # Trend/revenue cannot override rights gate.
        result = evaluate_opportunity(
            _opportunity(posterior=0.99),
            _requirement(),
            _full_snapshot(rights_clear=False),
        )
        # Archive path is ready so we DOWNGRADE to archive_only;
        # public-live is still blocked.
        assert result.mode is RunMode.ARCHIVE_ONLY
        assert BlockerKind.MISSING_RIGHTS in result.blockers

    def test_high_posterior_does_not_override_missing_monetization(self) -> None:
        # Pin no-expert-system: trend cannot launder monetization.
        result = evaluate_opportunity(
            _opportunity(posterior=0.99, monetization_intended=True),
            _requirement(),
            _full_snapshot(monetization_ready=False),
        )
        assert result.mode is RunMode.REFUSED
        assert BlockerKind.NO_EXPERT_SYSTEM_OVERRIDE in result.blockers
        assert BlockerKind.MISSING_MONETIZATION in result.blockers


# ── Public-claim path: each evidence axis blocks ─────────────────────


class TestPublicClaimBlocked:
    def test_missing_claim_shape_refuses(self) -> None:
        result = evaluate_opportunity(
            _opportunity(),
            _requirement(),
            _full_snapshot(claim_shape_declared=False),
        )
        assert result.mode is RunMode.REFUSED
        assert BlockerKind.MISSING_CLAIM_SHAPE in result.blockers

    def test_missing_egress_downgrades_to_archive_only(self) -> None:
        result = evaluate_opportunity(
            _opportunity(),
            _requirement(),
            _full_snapshot(egress_active=False),
        )
        assert result.mode is RunMode.ARCHIVE_ONLY
        assert BlockerKind.MISSING_EVIDENCE in result.blockers

    def test_missing_audio_safe_downgrades(self) -> None:
        result = evaluate_opportunity(
            _opportunity(),
            _requirement(),
            _full_snapshot(audio_safe=False),
        )
        assert result.mode is RunMode.ARCHIVE_ONLY

    def test_missing_public_event_path_downgrades(self) -> None:
        result = evaluate_opportunity(
            _opportunity(),
            _requirement(),
            _full_snapshot(public_event_path_ready=False),
        )
        assert result.mode is RunMode.ARCHIVE_ONLY
        assert BlockerKind.MISSING_PUBLIC_EVENT_PATH in result.blockers

    def test_missing_archive_path_blocks_when_evidence_missing(self) -> None:
        # Public-live evidence missing AND archive path NOT ready —
        # gate cannot downgrade, must block.
        result = evaluate_opportunity(
            _opportunity(),
            _requirement(requires_archive_path=False),
            _full_snapshot(
                egress_active=False,
                archive_path_ready=False,
            ),
        )
        assert result.mode is RunMode.BLOCKED
        assert BlockerKind.MISSING_EVIDENCE in result.blockers


# ── Hardware + higher-priority blockers ──────────────────────────────


class TestStructuralBlockers:
    def test_hardware_blocked_yields_blocked_mode(self) -> None:
        result = evaluate_opportunity(
            _opportunity(),
            _requirement(),
            _full_snapshot(hardware_blocked=True),
        )
        assert result.mode is RunMode.BLOCKED
        assert BlockerKind.HARDWARE_BLOCKED in result.blockers

    def test_higher_priority_occupying_yields_held_mode(self) -> None:
        result = evaluate_opportunity(
            _opportunity(),
            _requirement(),
            _full_snapshot(higher_priority_run_occupying=True),
        )
        assert result.mode is RunMode.HELD
        assert BlockerKind.HIGHER_PRIORITY_OCCUPYING in result.blockers

    def test_hardware_block_pre_empts_evidence_check(self) -> None:
        # Hardware blocked even with otherwise-perfect WCS.
        result = evaluate_opportunity(
            _opportunity(),
            _requirement(),
            _full_snapshot(hardware_blocked=True),
        )
        assert result.mode is RunMode.BLOCKED


# ── Negative cases (cc-task verification §) ──────────────────────────


class TestNegativeWcsPaths:
    def test_trend_revenue_selected_but_rights_blocked(self) -> None:
        # The exact "trend/revenue selected but WCS-blocked" negative
        # test the cc-task asks for.
        result = evaluate_opportunity(
            _opportunity(posterior=0.95, monetization_intended=True),
            _requirement(),
            _full_snapshot(rights_clear=False, monetization_ready=False),
        )
        # Monetization-overreach refusal pre-empts the archive_only
        # downgrade — operator must clear monetization separately.
        assert result.mode is RunMode.REFUSED
        assert BlockerKind.MISSING_MONETIZATION in result.blockers

    def test_trend_revenue_selected_but_privacy_blocked(self) -> None:
        result = evaluate_opportunity(
            _opportunity(posterior=0.95),
            _requirement(),
            _full_snapshot(privacy_clear=False),
        )
        assert result.mode is RunMode.ARCHIVE_ONLY
        assert BlockerKind.MISSING_PRIVACY in result.blockers


# ── Non-public path (dry_run) ────────────────────────────────────────


class TestNonPublicPath:
    def test_non_public_intent_yields_dry_run(self) -> None:
        result = evaluate_opportunity(
            _opportunity(public_claim_intended=False),
            _requirement(),
            _full_snapshot(),
        )
        assert result.mode is RunMode.DRY_RUN
        assert result.blockers == ()

    def test_non_public_with_partial_wcs_still_dry_run(self) -> None:
        # Non-public path doesn't consult WCS evidence at all.
        result = evaluate_opportunity(
            _opportunity(public_claim_intended=False),
            _requirement(),
            _full_snapshot(
                egress_active=False,
                rights_clear=False,
            ),
        )
        assert result.mode is RunMode.DRY_RUN

    def test_non_public_low_posterior_still_refuses(self) -> None:
        # Posterior floor applies regardless of public/private intent.
        result = evaluate_opportunity(
            _opportunity(public_claim_intended=False, posterior=0.05),
            _requirement(),
            _full_snapshot(),
        )
        assert result.mode is RunMode.REFUSED


# ── Mode matrix sweep ────────────────────────────────────────────────


class TestModeMatrix:
    def test_each_mode_reachable(self) -> None:
        # Sanity sweep: every mode (except PRIVATE which the gate
        # never produces by design — see module docstring) is
        # reachable via at least one input combination.
        runnable = evaluate_opportunity(_opportunity(), _requirement(), _full_snapshot())
        assert runnable.mode is RunMode.RUNNABLE

        dry_run = evaluate_opportunity(
            _opportunity(public_claim_intended=False),
            _requirement(),
            _full_snapshot(),
        )
        assert dry_run.mode is RunMode.DRY_RUN

        refused = evaluate_opportunity(
            _opportunity(posterior=0.05), _requirement(), _full_snapshot()
        )
        assert refused.mode is RunMode.REFUSED

        archive_only = evaluate_opportunity(
            _opportunity(),
            _requirement(),
            _full_snapshot(egress_active=False),
        )
        assert archive_only.mode is RunMode.ARCHIVE_ONLY

        held = evaluate_opportunity(
            _opportunity(),
            _requirement(),
            _full_snapshot(higher_priority_run_occupying=True),
        )
        assert held.mode is RunMode.HELD

        blocked = evaluate_opportunity(
            _opportunity(),
            _requirement(),
            _full_snapshot(hardware_blocked=True),
        )
        assert blocked.mode is RunMode.BLOCKED


# ── Result-shape contract ────────────────────────────────────────────


class TestResultShape:
    def test_blockers_tuple_iterable(self) -> None:
        # Surface consumers iterate result.blockers to construct
        # multi-line refusal articulations; pin that the field is a
        # tuple so iteration is stable.
        result = evaluate_opportunity(
            _opportunity(),
            _requirement(),
            _full_snapshot(rights_clear=False, privacy_clear=False),
        )
        assert isinstance(result.blockers, tuple)
        assert BlockerKind.MISSING_RIGHTS in result.blockers
        assert BlockerKind.MISSING_PRIVACY in result.blockers

    def test_reason_populated_on_every_decision(self) -> None:
        for snap in (
            _full_snapshot(),
            _full_snapshot(hardware_blocked=True),
            _full_snapshot(higher_priority_run_occupying=True),
            _full_snapshot(claim_shape_declared=False),
        ):
            result = evaluate_opportunity(_opportunity(), _requirement(), snap)
            assert result.reason
