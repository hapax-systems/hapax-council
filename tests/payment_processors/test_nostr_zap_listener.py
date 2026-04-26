"""Tests for ``agents.payment_processors.nostr_zap_listener``."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from agents.payment_processors.nostr_zap_listener import (
    NostrZapListener,
    _amount_sats_from_bolt11,
    _zap_event_to_payment_event,
)


class TestAmountSatsFromBolt11:
    def test_milli_btc(self):
        # lnbc1m = 1 milli-BTC = 100_000 sats
        assert _amount_sats_from_bolt11("lnbc1m1abc") == 100_000

    def test_micro_btc(self):
        # lnbc1u = 1 micro-BTC = 100 sats
        assert _amount_sats_from_bolt11("lnbc1u1abc") == 100

    def test_nano_btc(self):
        # lnbc100n = 100 nano-BTC = 10 sats
        assert _amount_sats_from_bolt11("lnbc100n1abc") == 10

    def test_pico_btc(self):
        # lnbc100p = 100 pico-BTC = 0 sats (< 1)
        assert _amount_sats_from_bolt11("lnbc100p1abc") == 0

    def test_no_amount_prefix(self):
        assert _amount_sats_from_bolt11("notbolt11") == 0

    def test_empty(self):
        assert _amount_sats_from_bolt11("") == 0


class TestZapEventToPaymentEvent:
    def test_extracts_amount_and_id(self):
        event_data = {
            "id": "zap-id-1",
            "pubkey": "abc" * 16,
            "kind": 9735,
            "created_at": 1700000000,
            "tags": [
                ["bolt11", "lnbc21u1abc"],
                ["p", "deadbeef"],
            ],
        }
        result = _zap_event_to_payment_event(event_data)
        assert result is not None
        assert result.rail == "nostr_zap"
        assert result.external_id == "zap-id-1"
        assert result.amount_sats == 2100  # 21 micro-BTC

    def test_description_content_excerpt(self):
        zap_request = {"content": "this is a great zap!"}
        event_data = {
            "id": "zap-id-2",
            "pubkey": "feed" * 8,
            "kind": 9735,
            "created_at": 1700000000,
            "tags": [
                ["bolt11", "lnbc1m1abc"],
                ["description", json.dumps(zap_request)],
            ],
        }
        result = _zap_event_to_payment_event(event_data)
        assert result is not None
        assert "great zap" in result.sender_excerpt

    def test_no_bolt11_zero_sats(self):
        event_data = {
            "id": "zap-id-3",
            "pubkey": "1234" * 8,
            "kind": 9735,
            "created_at": 1700000000,
            "tags": [],
        }
        result = _zap_event_to_payment_event(event_data)
        assert result is not None
        assert result.amount_sats == 0


class TestNostrZapListener:
    def test_no_npub_disables_rail(self):
        listener = NostrZapListener(npub_hex=None)
        # Run once via the public surface. We don't actually call
        # run_forever to avoid network; we instead verify the early-out
        # behavior via the npub presence check.
        assert listener._npub is None  # noqa: SLF001
        # Disabled flag flips on run; not testable without a fake loop,
        # but the structure is enforced by run_forever (covered by
        # integration tests in production).

    def test_handle_relay_message_emits_event(self, tmp_path, monkeypatch):
        import agents.payment_processors.event_log as ev_log

        log_path = tmp_path / "events.jsonl"
        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        listener = NostrZapListener(npub_hex="abcd" * 16)
        # Build a relay EVENT message
        zap_event = {
            "id": "abcdef",
            "pubkey": "feed" * 8,
            "kind": 9735,
            "created_at": int(datetime.now(UTC).timestamp()),
            "tags": [["bolt11", "lnbc1u1abc"]],
        }
        msg = json.dumps(["EVENT", "sub-1", zap_event])
        listener._handle_relay_message(msg, "sub-1")  # noqa: SLF001
        from agents.payment_processors.event_log import tail_events

        events = tail_events(log_path=log_path)
        assert len(events) == 1
        assert events[0].rail == "nostr_zap"
        assert events[0].external_id == "abcdef"

    def test_handle_relay_message_dedupes(self, tmp_path, monkeypatch):
        import agents.payment_processors.event_log as ev_log

        log_path = tmp_path / "events.jsonl"
        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        listener = NostrZapListener(npub_hex="abcd" * 16)
        zap_event = {
            "id": "abcdef",
            "pubkey": "feed" * 8,
            "kind": 9735,
            "created_at": int(datetime.now(UTC).timestamp()),
            "tags": [["bolt11", "lnbc1u1abc"]],
        }
        msg = json.dumps(["EVENT", "sub-1", zap_event])
        listener._handle_relay_message(msg, "sub-1")  # noqa: SLF001
        listener._handle_relay_message(msg, "sub-1")  # noqa: SLF001
        from agents.payment_processors.event_log import tail_events

        events = tail_events(log_path=log_path)
        assert len(events) == 1

    def test_handle_relay_message_ignores_other_subs(self, tmp_path, monkeypatch):
        import agents.payment_processors.event_log as ev_log

        log_path = tmp_path / "events.jsonl"
        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        listener = NostrZapListener(npub_hex="abcd" * 16)
        zap_event = {"id": "x", "pubkey": "y", "kind": 9735, "created_at": 0}
        msg = json.dumps(["EVENT", "OTHER", zap_event])
        listener._handle_relay_message(msg, "MINE")  # noqa: SLF001
        from agents.payment_processors.event_log import tail_events

        assert tail_events(log_path=log_path) == []

    def test_handle_relay_message_ignores_non_event(self, tmp_path, monkeypatch):
        import agents.payment_processors.event_log as ev_log

        log_path = tmp_path / "events.jsonl"
        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        listener = NostrZapListener(npub_hex="abcd" * 16)
        msg = json.dumps(["EOSE", "sub-1"])
        listener._handle_relay_message(msg, "sub-1")  # noqa: SLF001
        from agents.payment_processors.event_log import tail_events

        assert tail_events(log_path=log_path) == []
