"""Tests for Continuous-Loop Research Cadence §3.5 — attention-bid collector."""

from __future__ import annotations

import json
from pathlib import Path


def _bid(**overrides):
    from agents.attention_bids.bidder import AttentionBid

    return AttentionBid(
        source=overrides.get("source", "briefing"),
        salience=overrides.get("salience", 0.6),
        summary=overrides.get("summary", "pay attention"),
        objective_id=overrides.get("objective_id"),
    )


class TestCollectorState:
    def test_empty_state_round_trip(self, tmp_path: Path):
        from agents.attention_bids.collector import (
            CollectorState,
            load_state,
            save_state,
        )

        p = tmp_path / "state.json"
        save_state(CollectorState(), path=p)
        restored = load_state(p)
        assert restored.last_delivered_at == {}

    def test_populated_round_trip(self, tmp_path: Path):
        from agents.attention_bids.collector import (
            CollectorState,
            load_state,
            save_state,
        )

        p = tmp_path / "state.json"
        save_state(
            CollectorState(last_delivered_at={"ntfy": 100.0, "visual_flash": 200.0}),
            path=p,
        )
        restored = load_state(p)
        assert restored.last_delivered_at == {"ntfy": 100.0, "visual_flash": 200.0}

    def test_missing_file_yields_empty_state(self, tmp_path: Path):
        from agents.attention_bids.collector import load_state

        state = load_state(tmp_path / "absent.json")
        assert state.last_delivered_at == {}

    def test_malformed_json_yields_empty_state(self, tmp_path: Path):
        from agents.attention_bids.collector import load_state

        p = tmp_path / "bad.json"
        p.write_text("{not valid", encoding="utf-8")
        assert load_state(p).last_delivered_at == {}

    def test_malformed_timestamps_are_dropped(self, tmp_path: Path):
        from agents.attention_bids.collector import load_state

        p = tmp_path / "state.json"
        p.write_text(
            json.dumps(
                {
                    "last_delivered_at": {
                        "ntfy": 100.0,
                        "visual_flash": "not-a-number",
                        "tts": None,
                    }
                }
            ),
            encoding="utf-8",
        )
        assert load_state(p).last_delivered_at == {"ntfy": 100.0}


class TestBidCollector:
    def test_submit_and_drain(self):
        from agents.attention_bids.collector import BidCollector

        c = BidCollector()
        c.submit(_bid(source="a"))
        c.submit(_bid(source="b"))
        assert c.pending_count() == 2

        bids = c.drain()
        assert [b.source for b in bids] == ["a", "b"]
        assert c.pending_count() == 0

    def test_drain_empty(self):
        from agents.attention_bids.collector import BidCollector

        assert BidCollector().drain() == []

    def test_thread_safety(self):
        import threading

        from agents.attention_bids.collector import BidCollector

        c = BidCollector()

        def push_n(n: int):
            for i in range(n):
                c.submit(_bid(source=f"t-{i}"))

        threads = [threading.Thread(target=push_n, args=(50,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert c.pending_count() == 200
        bids = c.drain()
        assert len(bids) == 200
        assert c.pending_count() == 0


class TestAttentionBidTick:
    def test_no_bids_returns_no_winner(self, tmp_path: Path):
        from agents.attention_bids.collector import BidCollector, attention_bid_tick

        state = tmp_path / "state.json"
        result = attention_bid_tick(BidCollector(), state_path=state)
        assert result.bid_result.winner is None
        assert result.bid_result.reason == "no_bids"
        assert result.dispatch_result is None

    def test_winner_dispatched_and_state_persisted(self, tmp_path: Path):
        from agents.attention_bids.collector import BidCollector, attention_bid_tick
        from agents.attention_bids.dispatcher import ChannelConfig

        c = BidCollector()
        c.submit(_bid(source="briefing", salience=0.9))

        state_path = tmp_path / "state.json"
        trigger_dir = tmp_path / "trigger"
        config = ChannelConfig(enabled_channels=("visual_flash",), hysteresis_minutes=15)

        # Inject trigger dir via monkey-patch on the dispatcher default
        from agents.attention_bids import dispatcher as dispatcher_mod

        original = dispatcher_mod.TRIGGER_DIR
        original_log = dispatcher_mod.LOG_PATH
        dispatcher_mod.TRIGGER_DIR = trigger_dir
        dispatcher_mod.LOG_PATH = tmp_path / "log.jsonl"
        try:
            result = attention_bid_tick(
                c,
                stimmung={"stance": "nominal"},
                config=config,
                state_path=state_path,
                now_epoch=1000.0,
            )
        finally:
            dispatcher_mod.TRIGGER_DIR = original
            dispatcher_mod.LOG_PATH = original_log

        assert result.bid_result.winner is not None
        assert result.dispatch_result is not None
        assert result.dispatch_result.delivered == ("visual_flash",)

        # State file persisted with last-delivered timestamp
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        assert "last_delivered_at" in persisted
        assert persisted["last_delivered_at"]["visual_flash"] == 1000.0

    def test_hysteresis_across_ticks(self, tmp_path: Path):
        """Two successive ticks within hysteresis → second is throttled."""
        from agents.attention_bids import dispatcher as dispatcher_mod
        from agents.attention_bids.collector import BidCollector, attention_bid_tick
        from agents.attention_bids.dispatcher import ChannelConfig

        state_path = tmp_path / "state.json"
        trigger_dir = tmp_path / "trigger"
        config = ChannelConfig(enabled_channels=("visual_flash",), hysteresis_minutes=15)

        original = dispatcher_mod.TRIGGER_DIR
        original_log = dispatcher_mod.LOG_PATH
        dispatcher_mod.TRIGGER_DIR = trigger_dir
        dispatcher_mod.LOG_PATH = tmp_path / "log.jsonl"
        try:
            c1 = BidCollector()
            c1.submit(_bid(salience=0.9))
            first = attention_bid_tick(
                c1,
                stimmung={"stance": "nominal"},
                config=config,
                state_path=state_path,
                now_epoch=1000.0,
            )

            c2 = BidCollector()
            c2.submit(_bid(salience=0.9))
            second = attention_bid_tick(
                c2,
                stimmung={"stance": "nominal"},
                config=config,
                state_path=state_path,
                now_epoch=1000.0 + 60 * 5,  # 5 min later, within 15-min window
            )
        finally:
            dispatcher_mod.TRIGGER_DIR = original
            dispatcher_mod.LOG_PATH = original_log

        assert first.dispatch_result.delivered == ("visual_flash",)
        assert second.dispatch_result.delivered == ()
        assert second.dispatch_result.throttled == ("visual_flash",)

    def test_below_threshold_no_dispatch(self, tmp_path: Path):
        from agents.attention_bids.collector import BidCollector, attention_bid_tick

        c = BidCollector()
        c.submit(_bid(salience=0.01))  # way below ACCEPT_THRESHOLD
        result = attention_bid_tick(c, state_path=tmp_path / "state.json")
        assert result.bid_result.winner is None
        assert result.bid_result.reason == "below_threshold"
        assert result.dispatch_result is None

    def test_default_state_path_is_shm(self):
        from agents.attention_bids.collector import STATE_PATH

        assert str(STATE_PATH).startswith("/dev/shm/")
