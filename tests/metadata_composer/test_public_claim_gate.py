"""Tests for ``agents.metadata_composer.public_claim_gate``.

Per cc-task ``metadata-public-claim-gate`` (WSJF 9.4). The gate is the
load-bearing predicate for every public-claim emission across YouTube,
cross-surface posts, and (via the reusable surface) GitHub README /
profile / repo metadata. These tests pin each claim kind's
fail-CLOSED behavior and the ALLOW path's evidence requirements.

Coverage maps directly to the cc-task acceptance criteria:

  - live update / VOD boundary scenarios → TestLiveNow + TestArchive
  - cross-surface posts → TestCrossSurface (combinations)
  - stale broadcast id → TestLiveNow.test_stale_broadcast_id_refuses
  - missing egress evidence → TestLiveNow.test_missing_egress_active_refuses
  - missing rights evidence → TestArchive.test_rights_clear_false_refuses
  - missing monetization readiness → TestMonetization.test_inactive_refuses
"""

from __future__ import annotations

from agents.metadata_composer.public_claim_gate import (
    DEFAULT_BROADCAST_FRESHNESS_S,
    DEFAULT_PROGRAMME_FRESHNESS_S,
    ClaimEvidence,
    ClaimKind,
    Decision,
    PublicClaimGateDecision,
    evaluate_public_claim,
)

# ── Sanity / module surface ──────────────────────────────────────────


class TestModuleSurface:
    def test_default_freshness_constants_are_seconds(self) -> None:
        # Pin the module's freshness ceilings; downstream callers tune
        # via kwargs but the documented defaults must stay stable.
        assert DEFAULT_BROADCAST_FRESHNESS_S == 30.0
        assert DEFAULT_PROGRAMME_FRESHNESS_S == 10.0

    def test_claim_kind_taxonomy(self) -> None:
        # The 10-kind taxonomy is the cc-task contract; expansion
        # requires explicit test addition so unrelated additions
        # don't sneak in.
        kinds = {k.value for k in ClaimKind}
        assert kinds == {
            "live_now",
            "current_activity",
            "programme_role",
            "archive",
            "replay",
            "support",
            "monetization",
            "license_class",
            "publication_state",
            "disabled_issues",
        }

    def test_decision_enum_has_three_verdicts(self) -> None:
        verdicts = {d.value for d in Decision}
        assert verdicts == {"allow", "refuse", "correct"}

    def test_allows_emission_property(self) -> None:
        allow = PublicClaimGateDecision(
            decision=Decision.ALLOW, kind=ClaimKind.LIVE_NOW, reason="ok"
        )
        refuse = PublicClaimGateDecision(
            decision=Decision.REFUSE, kind=ClaimKind.LIVE_NOW, reason="no"
        )
        correct = PublicClaimGateDecision(
            decision=Decision.CORRECT,
            kind=ClaimKind.LICENSE_CLASS,
            reason="drift",
            correction="see status doc",
        )
        assert allow.allows_emission is True
        assert refuse.allows_emission is False
        assert correct.allows_emission is False


# ── live_now ──────────────────────────────────────────────────────────


class TestLiveNow:
    def test_no_broadcast_id_refuses(self) -> None:
        result = evaluate_public_claim(ClaimKind.LIVE_NOW, ClaimEvidence())
        assert result.decision is Decision.REFUSE
        assert "broadcast_id" in result.reason
        assert "not currently broadcasting" in result.correction

    def test_stale_broadcast_id_refuses(self) -> None:
        # Stale-broadcast-id scenario from the cc-task acceptance.
        result = evaluate_public_claim(
            ClaimKind.LIVE_NOW,
            ClaimEvidence(
                broadcast_id="bcast-1",
                broadcast_age_s=120.0,  # 4× the freshness ceiling
                egress_active=True,
            ),
        )
        assert result.decision is Decision.REFUSE
        assert "stale" in result.reason

    def test_missing_egress_active_refuses(self) -> None:
        # Missing-egress-evidence scenario from the cc-task acceptance.
        result = evaluate_public_claim(
            ClaimKind.LIVE_NOW,
            ClaimEvidence(
                broadcast_id="bcast-1",
                broadcast_age_s=5.0,
                egress_active=False,
            ),
        )
        assert result.decision is Decision.REFUSE
        assert "egress_active" in result.reason

    def test_fresh_broadcast_id_with_egress_allows(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.LIVE_NOW,
            ClaimEvidence(
                broadcast_id="bcast-live-2026",
                broadcast_age_s=2.0,
                egress_active=True,
            ),
        )
        assert result.decision is Decision.ALLOW

    def test_freshness_ceiling_kwarg_override(self) -> None:
        # Per-surface tuning: a stricter ceiling fails a borderline-fresh id.
        result = evaluate_public_claim(
            ClaimKind.LIVE_NOW,
            ClaimEvidence(
                broadcast_id="bcast-1",
                broadcast_age_s=10.0,
                egress_active=True,
            ),
            broadcast_freshness_s=5.0,
        )
        assert result.decision is Decision.REFUSE


# ── current_activity ─────────────────────────────────────────────────


class TestCurrentActivity:
    def test_empty_activity_refuses(self) -> None:
        result = evaluate_public_claim(ClaimKind.CURRENT_ACTIVITY, ClaimEvidence())
        assert result.decision is Decision.REFUSE
        assert "current_activity" in result.reason

    def test_set_activity_allows(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.CURRENT_ACTIVITY,
            ClaimEvidence(current_activity="coding"),
        )
        assert result.decision is Decision.ALLOW
        assert "coding" in result.reason

    def test_private_sentinel_refuses(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.CURRENT_ACTIVITY,
            ClaimEvidence(
                current_activity="side note: PRIVATE_SENTINEL_DO_NOT_PUBLISH_20260505_XSURF_9F4C2A"
            ),
        )
        assert result.decision is Decision.REFUSE
        assert "PRIVATE_SENTINEL" in result.reason
        assert result.correction == "activity not currently witnessed"

    def test_arbitrary_sentinel_suffix_refuses(self) -> None:
        """Sentinel pattern must match any future-suffix ID, not just the
        seed token from PR #2526."""
        result = evaluate_public_claim(
            ClaimKind.CURRENT_ACTIVITY,
            ClaimEvidence(current_activity="PRIVATE_SENTINEL_DO_NOT_PUBLISH_FUTURE_DEADBEEF"),
        )
        assert result.decision is Decision.REFUSE


# ── programme_role ───────────────────────────────────────────────────


class TestProgrammeRole:
    def test_empty_refuses(self) -> None:
        result = evaluate_public_claim(ClaimKind.PROGRAMME_ROLE, ClaimEvidence())
        assert result.decision is Decision.REFUSE

    def test_stale_role_refuses(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.PROGRAMME_ROLE,
            ClaimEvidence(
                programme_role="research",
                programme_role_age_s=60.0,  # 6× the ceiling
            ),
        )
        assert result.decision is Decision.REFUSE
        assert "stale" in result.reason

    def test_fresh_role_allows(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.PROGRAMME_ROLE,
            ClaimEvidence(
                programme_role="research",
                programme_role_age_s=2.0,
            ),
        )
        assert result.decision is Decision.ALLOW

    def test_private_sentinel_refuses(self) -> None:
        """Programme role is the other free-text claim kind; sentinel
        scan must REFUSE before the freshness check applies."""
        result = evaluate_public_claim(
            ClaimKind.PROGRAMME_ROLE,
            ClaimEvidence(
                programme_role="research PRIVATE_SENTINEL_DO_NOT_PUBLISH_20260505_XSURF_9F4C2A",
                programme_role_age_s=1.0,
            ),
        )
        assert result.decision is Decision.REFUSE
        assert "PRIVATE_SENTINEL" in result.reason


# ── archive / replay ─────────────────────────────────────────────────


class TestArchive:
    def test_no_archive_url_refuses(self) -> None:
        result = evaluate_public_claim(ClaimKind.ARCHIVE, ClaimEvidence())
        assert result.decision is Decision.REFUSE
        assert "archive_url" in result.reason

    def test_rights_clear_false_refuses(self) -> None:
        # Missing-rights-evidence scenario from the cc-task acceptance.
        result = evaluate_public_claim(
            ClaimKind.ARCHIVE,
            ClaimEvidence(archive_url="https://youtu.be/abc", rights_clear=False),
        )
        assert result.decision is Decision.REFUSE
        assert "rights_clear" in result.reason
        assert "rights pending" in result.correction

    def test_url_with_rights_allows(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.ARCHIVE,
            ClaimEvidence(
                archive_url="https://youtu.be/abc",
                rights_clear=True,
            ),
        )
        assert result.decision is Decision.ALLOW

    def test_replay_uses_same_evidence_shape(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.REPLAY,
            ClaimEvidence(archive_url="https://replay.example", rights_clear=True),
        )
        assert result.decision is Decision.ALLOW
        assert result.kind is ClaimKind.REPLAY


# ── support / monetization ───────────────────────────────────────────


class TestSupport:
    def test_inactive_refuses(self) -> None:
        result = evaluate_public_claim(ClaimKind.SUPPORT, ClaimEvidence())
        assert result.decision is Decision.REFUSE

    def test_active_allows(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.SUPPORT, ClaimEvidence(support_surface_active=True)
        )
        assert result.decision is Decision.ALLOW


class TestMonetization:
    def test_inactive_refuses(self) -> None:
        result = evaluate_public_claim(ClaimKind.MONETIZATION, ClaimEvidence())
        assert result.decision is Decision.REFUSE
        assert "monetization_active" in result.reason

    def test_active_allows(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.MONETIZATION, ClaimEvidence(monetization_active=True)
        )
        assert result.decision is Decision.ALLOW


# ── license_class (CORRECT verdict path) ─────────────────────────────


class TestLicenseClass:
    def test_no_declared_license_refuses(self) -> None:
        result = evaluate_public_claim(ClaimKind.LICENSE_CLASS, ClaimEvidence())
        assert result.decision is Decision.REFUSE

    def test_inconsistent_license_returns_correct(self) -> None:
        # The license_class kind exercises the CORRECT verdict — claim
        # is partially supported (a license IS declared) but the
        # canonical surfaces disagree, so the gate emits replacement
        # copy pointing at the reconciliation status doc.
        result = evaluate_public_claim(
            ClaimKind.LICENSE_CLASS,
            ClaimEvidence(
                declared_license="PolyForm Strict 1.0.0",
                license_consistent=False,
            ),
        )
        assert result.decision is Decision.CORRECT
        assert "license-reconciliation-status" in result.correction

    def test_consistent_license_allows(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.LICENSE_CLASS,
            ClaimEvidence(
                declared_license="PolyForm Strict 1.0.0",
                license_consistent=True,
            ),
        )
        assert result.decision is Decision.ALLOW


# ── publication_state ────────────────────────────────────────────────


class TestPublicationState:
    def test_empty_refuses(self) -> None:
        result = evaluate_public_claim(ClaimKind.PUBLICATION_STATE, ClaimEvidence())
        assert result.decision is Decision.REFUSE

    def test_state_without_evidence_url_refuses(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.PUBLICATION_STATE,
            ClaimEvidence(publication_state="released"),
        )
        assert result.decision is Decision.REFUSE
        assert "publication_evidence_url" in result.reason

    def test_state_with_evidence_url_allows(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.PUBLICATION_STATE,
            ClaimEvidence(
                publication_state="released",
                publication_evidence_url="https://doi.org/10.5281/zenodo.123456",
            ),
        )
        assert result.decision is Decision.ALLOW


# ── disabled_issues ──────────────────────────────────────────────────


class TestDisabledIssues:
    def test_default_refuses(self) -> None:
        result = evaluate_public_claim(ClaimKind.DISABLED_ISSUES, ClaimEvidence())
        assert result.decision is Decision.REFUSE

    def test_witnessed_disabled_allows(self) -> None:
        result = evaluate_public_claim(
            ClaimKind.DISABLED_ISSUES,
            ClaimEvidence(issues_disabled=True),
        )
        assert result.decision is Decision.ALLOW


# ── Cross-surface scenarios (multi-claim composition) ────────────────


class TestCrossSurface:
    """Cross-surface metadata typically composes 2-3 claims at once.
    These tests pin the gate's combinatorial behavior — the surface
    must validate every claim independently and refuse the composition
    when any single claim is unsupported.
    """

    def test_live_update_with_fresh_evidence_all_allow(self) -> None:
        evidence = ClaimEvidence(
            broadcast_id="bcast-1",
            broadcast_age_s=2.0,
            egress_active=True,
            current_activity="coding",
            programme_role="research",
            programme_role_age_s=2.0,
        )
        live = evaluate_public_claim(ClaimKind.LIVE_NOW, evidence)
        activity = evaluate_public_claim(ClaimKind.CURRENT_ACTIVITY, evidence)
        role = evaluate_public_claim(ClaimKind.PROGRAMME_ROLE, evidence)
        assert all(d.decision is Decision.ALLOW for d in (live, activity, role))

    def test_vod_boundary_with_archive_evidence(self) -> None:
        # VOD-boundary scenario: live claim must REFUSE (broadcast just
        # ended); archive must ALLOW.
        evidence = ClaimEvidence(
            broadcast_id="bcast-just-ended",
            broadcast_age_s=120.0,  # past freshness window
            egress_active=False,  # broadcast pipeline shut down
            archive_url="https://youtu.be/just-ended",
            rights_clear=True,
        )
        live = evaluate_public_claim(ClaimKind.LIVE_NOW, evidence)
        archive = evaluate_public_claim(ClaimKind.ARCHIVE, evidence)
        assert live.decision is Decision.REFUSE
        assert archive.decision is Decision.ALLOW

    def test_cross_surface_post_with_partial_evidence(self) -> None:
        # Cross-surface post asserts both live + monetization; only
        # live is supported. The composer must drop the monetization
        # claim while keeping the live one.
        evidence = ClaimEvidence(
            broadcast_id="bcast-current",
            broadcast_age_s=5.0,
            egress_active=True,
            monetization_active=False,
        )
        live = evaluate_public_claim(ClaimKind.LIVE_NOW, evidence)
        monetization = evaluate_public_claim(ClaimKind.MONETIZATION, evidence)
        assert live.decision is Decision.ALLOW
        assert monetization.decision is Decision.REFUSE


# ── Unknown kind (defensive) ─────────────────────────────────────────


class TestEvaluatorRegistry:
    def test_every_claim_kind_has_an_evaluator(self) -> None:
        # Defensive: every member of ClaimKind must dispatch.
        # An evaluator omission would only surface as a runtime KeyError;
        # this test enforces full coverage at module-import time.
        sample = ClaimEvidence()
        for kind in ClaimKind:
            # Must not raise.
            result = evaluate_public_claim(kind, sample)
            assert isinstance(result, PublicClaimGateDecision)
            assert result.kind is kind
