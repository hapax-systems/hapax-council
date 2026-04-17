"""Tests for agents.attention_bids.bidder (Phase 8 item 8)."""

from __future__ import annotations

import pytest


class TestScoreBid:
    def test_base_score_no_modifiers(self):
        from agents.attention_bids.bidder import AttentionBid, score_bid

        bid = AttentionBid(source="briefing", salience=0.5)
        assert score_bid(bid, stimmung={}, active_objective_ids=frozenset()) == pytest.approx(0.5)

    def test_objective_alignment_boost(self):
        from agents.attention_bids.bidder import (
            OBJECTIVE_ALIGNMENT_BOOST,
            AttentionBid,
            score_bid,
        )

        bid = AttentionBid(source="goal-advance", salience=0.4, objective_id="obj-001")
        score = score_bid(bid, stimmung={}, active_objective_ids=frozenset({"obj-001"}))
        assert score == pytest.approx(0.4 + OBJECTIVE_ALIGNMENT_BOOST)

    def test_objective_not_active_no_boost(self):
        from agents.attention_bids.bidder import AttentionBid, score_bid

        bid = AttentionBid(source="goal-advance", salience=0.4, objective_id="obj-999")
        assert score_bid(
            bid, stimmung={}, active_objective_ids=frozenset({"obj-001"})
        ) == pytest.approx(0.4)

    def test_stress_attenuates(self):
        from agents.attention_bids.bidder import (
            OPERATOR_STRESS_ATTENUATION,
            AttentionBid,
            score_bid,
        )

        bid = AttentionBid(source="nudge", salience=1.0)
        high = score_bid(
            bid, stimmung={"operator_stress": {"value": 1.0}}, active_objective_ids=frozenset()
        )
        assert high == pytest.approx(1.0 - OPERATOR_STRESS_ATTENUATION)
        low = score_bid(
            bid, stimmung={"operator_stress": {"value": 0.0}}, active_objective_ids=frozenset()
        )
        assert low == pytest.approx(1.0)

    def test_capped_at_one(self):
        from agents.attention_bids.bidder import AttentionBid, score_bid

        bid = AttentionBid(source="goal-advance", salience=1.0, objective_id="obj-001")
        score = score_bid(bid, stimmung={}, active_objective_ids=frozenset({"obj-001"}))
        assert score <= 1.0


class TestSelectWinner:
    def test_empty(self):
        from agents.attention_bids.bidder import select_winner

        r = select_winner([], stimmung={})
        assert r.winner is None and r.reason == "no_bids"

    def test_single_accepted(self):
        from agents.attention_bids.bidder import AttentionBid, select_winner

        b = AttentionBid(source="briefing", salience=0.5)
        r = select_winner([b], stimmung={})
        assert r.winner is b and r.reason == "accepted"

    def test_highest_wins(self):
        from agents.attention_bids.bidder import AttentionBid, select_winner

        low = AttentionBid(source="briefing", salience=0.3)
        high = AttentionBid(source="nudge", salience=0.8)
        r = select_winner([low, high], stimmung={})
        assert r.winner is high

    def test_tie_broken_by_source_priority(self):
        from agents.attention_bids.bidder import AttentionBid, select_winner

        a = AttentionBid(source="briefing", salience=0.5)
        b = AttentionBid(source="nudge", salience=0.5)
        r = select_winner([a, b], stimmung={})
        assert r.winner is b  # nudge > briefing in priority

    def test_below_threshold(self):
        from agents.attention_bids.bidder import ACCEPT_THRESHOLD, AttentionBid, select_winner

        bid = AttentionBid(source="briefing", salience=ACCEPT_THRESHOLD / 2)
        r = select_winner([bid], stimmung={})
        assert r.winner is None and r.reason == "below_threshold"

    def test_broadcast_consent_missing_filters(self):
        from agents.attention_bids.bidder import AttentionBid, select_winner

        bid = AttentionBid(
            source="briefing", salience=0.9, requires_broadcast_consent=True, objective_id="wife"
        )
        r = select_winner(
            [bid], stimmung={}, stream_mode="public", broadcast_contract_holders=frozenset()
        )
        assert r.winner is None and r.reason == "all_filtered"
        assert r.filtered["briefing"] == "broadcast_consent_missing"

    def test_broadcast_consent_with_contract(self):
        from agents.attention_bids.bidder import AttentionBid, select_winner

        bid = AttentionBid(
            source="briefing",
            salience=0.9,
            requires_broadcast_consent=True,
            objective_id="guest-1",
        )
        r = select_winner(
            [bid],
            stimmung={},
            stream_mode="public",
            broadcast_contract_holders=frozenset({"guest-1"}),
        )
        assert r.winner is bid

    def test_private_stream_no_consent_filter(self):
        from agents.attention_bids.bidder import AttentionBid, select_winner

        bid = AttentionBid(
            source="briefing", salience=0.9, requires_broadcast_consent=True, objective_id="wife"
        )
        r = select_winner(
            [bid], stimmung={}, stream_mode="private", broadcast_contract_holders=frozenset()
        )
        assert r.winner is bid

    def test_objective_aligned_wins(self):
        from agents.attention_bids.bidder import AttentionBid, select_winner

        unaligned = AttentionBid(source="briefing", salience=0.5)
        aligned = AttentionBid(source="goal-advance", salience=0.4, objective_id="obj-001")
        r = select_winner(
            [unaligned, aligned], stimmung={}, active_objective_ids=frozenset({"obj-001"})
        )
        assert r.winner is aligned

    def test_scores_dict_observability(self):
        from agents.attention_bids.bidder import AttentionBid, select_winner

        live = AttentionBid(source="nudge", salience=0.5)
        gated = AttentionBid(
            source="briefing",
            salience=0.9,
            requires_broadcast_consent=True,
            objective_id="stranger",
        )
        r = select_winner(
            [live, gated],
            stimmung={},
            stream_mode="public",
            broadcast_contract_holders=frozenset(),
        )
        assert "nudge" in r.scores and "briefing" in r.scores
        assert r.scores["briefing"] == 0.0
        assert r.filtered["briefing"] == "broadcast_consent_missing"
