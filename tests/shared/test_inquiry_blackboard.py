from __future__ import annotations

import os
from unittest.mock import patch

from shared.inquiry_blackboard import (
    ActionGap,
    AuthorityGap,
    Bid,
    BlackboardState,
    Challenge,
    ClaimGap,
    Commitment,
    ExhaustionAttestation,
    FormProposal,
    LayoutGap,
    Lead,
    NoCandidateReason,
    PersonageGap,
    ReviewGap,
    SourceGap,
    detect_quiescence,
    detect_source_theater,
    resolve_gap,
)


class TestBlackboardObjects:
    def test_lead_creation(self) -> None:
        lead = Lead(
            lead_id="lead-001",
            topic="zram swap pressure",
            source_pressure="operator observation of high swap usage",
        )
        assert lead.lead_id == "lead-001"
        assert lead.resolved is False

    def test_source_gap(self) -> None:
        gap = SourceGap(
            gap_id="sg-001",
            description="Missing zram metrics for compositor peak",
            tried_sources=["vault:system-logs"],
            claim_it_changes="claim:seg1:001",
        )
        assert gap.status == "open"
        assert gap.claim_it_changes == "claim:seg1:001"

    def test_claim_gap(self) -> None:
        gap = ClaimGap(
            gap_id="cg-001",
            description="Unsupported assertion about RLHF ceiling",
            claim_id="claim:seg1:002",
        )
        assert gap.severity == "blocking"

    def test_all_10_classes_instantiate(self) -> None:
        objs = [
            Lead(lead_id="l1", topic="t", source_pressure="p"),
            SourceGap(gap_id="sg1", description="d", claim_it_changes="c1"),
            ClaimGap(gap_id="cg1", description="d", claim_id="c1"),
            FormProposal(gap_id="fp1", form_id="f1", grounding_question="q?"),
            ActionGap(gap_id="ag1", description="d", action_id="a1"),
            LayoutGap(gap_id="lg1", description="d", layout_need="visual"),
            PersonageGap(gap_id="pg1", description="d", violation_type="first_person"),
            AuthorityGap(gap_id="authg1", description="d", transition_blocked="selected_release"),
            ReviewGap(gap_id="rg1", description="d", review_type="canary"),
            NoCandidateReason(reason_id="nc1", description="d", lead_ids=["l1"]),
        ]
        assert len(objs) == 10


class TestBidding:
    def test_bid_creation(self) -> None:
        bid = Bid(
            bidder="source_recruiter",
            target_gap_id="sg-001",
            expected_value=0.7,
            budget_cost=30.0,
            authority_boundary="research_only",
            what_it_changes="claim:seg1:001 — adds fresh zram metrics",
        )
        assert bid.expected_value == 0.7

    def test_bid_without_what_it_changes_is_theater(self) -> None:
        bid = Bid(
            bidder="source_recruiter",
            target_gap_id="sg-001",
            expected_value=0.5,
            budget_cost=10.0,
            authority_boundary="research_only",
            what_it_changes="",
        )
        assert detect_source_theater([bid]) == ["sg-001"]


class TestQuiescence:
    def test_quiescent_when_no_open_gaps(self) -> None:
        state = BlackboardState(leads=[], gaps=[], bids=[])
        assert detect_quiescence(state, risk_threshold=0.5) is True

    def test_not_quiescent_with_open_gap_above_threshold(self) -> None:
        state = BlackboardState(
            leads=[],
            gaps=[SourceGap(gap_id="sg1", description="d", claim_it_changes="c1", risk=0.8)],
            bids=[],
        )
        assert detect_quiescence(state, risk_threshold=0.5) is False

    def test_quiescent_with_gap_below_threshold(self) -> None:
        state = BlackboardState(
            leads=[],
            gaps=[SourceGap(gap_id="sg1", description="d", claim_it_changes="c1", risk=0.3)],
            bids=[],
        )
        assert detect_quiescence(state, risk_threshold=0.5) is True

    def test_not_quiescent_with_positive_value_bid(self) -> None:
        state = BlackboardState(
            leads=[],
            gaps=[SourceGap(gap_id="sg1", description="d", claim_it_changes="c1", risk=0.3)],
            bids=[
                Bid(
                    bidder="recruiter",
                    target_gap_id="sg1",
                    expected_value=0.6,
                    budget_cost=10.0,
                    authority_boundary="research_only",
                    what_it_changes="c1 — fresh source",
                )
            ],
        )
        assert detect_quiescence(state, risk_threshold=0.5) is False


class TestSourceTheater:
    def test_detects_empty_what_it_changes(self) -> None:
        bids = [
            Bid(
                bidder="x",
                target_gap_id="sg1",
                expected_value=0.5,
                budget_cost=5.0,
                authority_boundary="research_only",
                what_it_changes="",
            ),
        ]
        assert detect_source_theater(bids) == ["sg1"]

    def test_passes_with_named_change(self) -> None:
        bids = [
            Bid(
                bidder="x",
                target_gap_id="sg1",
                expected_value=0.5,
                budget_cost=5.0,
                authority_boundary="research_only",
                what_it_changes="claim:seg1:001 — adds missing metric",
            ),
        ]
        assert detect_source_theater(bids) == []


class TestResolveGap:
    def test_resolve_marks_status(self) -> None:
        gap = SourceGap(gap_id="sg1", description="d", claim_it_changes="c1")
        resolved = resolve_gap(gap, resolution="source recruited successfully")
        assert resolved.status == "resolved"
        assert resolved.resolution == "source recruited successfully"


_INVERT_ON = {"HAPAX_INVERTED_QUIESCENCE": "1"}


class TestInvertedQuiescence:
    """Keystone: silence is not rest. Rest requires POSITIVE attestation, not the
    absence of gaps. The legacy silence-passes behavior survives behind the flag."""

    def _discharged_attested(self) -> BlackboardState:
        return BlackboardState(
            commitments=[Commitment(claim_id="c1", discharge_route="deferral")],
            attestations=[ExhaustionAttestation(claim_id="c1", attester_family="anthropic")],
        )

    def test_empty_board_is_not_quiescent(self) -> None:
        # INVERSION CANARY: an empty/thin board can never rest (silence made loud).
        with patch.dict(os.environ, _INVERT_ON):
            assert detect_quiescence(BlackboardState()) is False

    def test_open_undischarged_challenge_blocks_rest(self) -> None:
        # FORWARD-PATH-OBSTACLE CANARY: a vindication-attempted challenge that still
        # stands is a RED between producer and rest, even on an otherwise-clean claim.
        state = self._discharged_attested().model_copy(
            update={
                "challenges": [
                    Challenge(
                        challenge_id="ch1",
                        target_claim_id="c1",
                        counter_position="the source does not actually say this",
                        challenger_family="openai",
                        status="open",
                        vindication_attempted=True,
                    )
                ]
            }
        )
        with patch.dict(os.environ, _INVERT_ON):
            assert detect_quiescence(state) is False

    def test_discharged_and_attested_board_rests(self) -> None:
        # POSITIVE: discharged + independently attested + no standing challenge -> rest.
        with patch.dict(os.environ, _INVERT_ON):
            assert detect_quiescence(self._discharged_attested()) is True

    def test_undischarged_unattested_commitment_blocks_rest(self) -> None:
        state = BlackboardState(commitments=[Commitment(claim_id="c1")])  # undischarged, unattested
        with patch.dict(os.environ, _INVERT_ON):
            assert detect_quiescence(state) is False

    def test_unattested_claim_blocks_rest(self) -> None:
        # A discharged claim with NO independent attestation is still a standing gap.
        state = BlackboardState(commitments=[Commitment(claim_id="c1", discharge_route="deferral")])
        with patch.dict(os.environ, _INVERT_ON):
            assert detect_quiescence(state) is False

    def test_under_projection_attestation_blocks_rest(self) -> None:
        # A rival found a STRONGER un-declared commitment (under-projection) -> no rest,
        # even though the commitment is discharged. Reading thinly buys nothing.
        state = BlackboardState(
            commitments=[Commitment(claim_id="c1", discharge_route="deferral")],
            attestations=[
                ExhaustionAttestation(
                    claim_id="c1", attester_family="anthropic", found_stronger_commitment=True
                )
            ],
        )
        with patch.dict(os.environ, _INVERT_ON):
            assert detect_quiescence(state) is False

    def test_flag_off_preserves_legacy_silence_passes(self) -> None:
        # Legacy path UNCHANGED: flag off -> empty board is quiescent (the behavior
        # the live refusal path at daily_segment_prep.py relies on).
        with patch.dict(os.environ, {"HAPAX_INVERTED_QUIESCENCE": ""}):
            assert detect_quiescence(BlackboardState()) is True
