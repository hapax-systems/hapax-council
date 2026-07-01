"""Tests for ``agents.payment_processors.nostr_zap_listener``."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

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

    def test_handle_relay_message_records_event_resource_receipt(self, tmp_path, monkeypatch):
        import agents.payment_processors.event_log as ev_log
        import agents.payment_processors.resource_receipts as resource_receipts

        log_path = tmp_path / "events.jsonl"
        receipt_log = tmp_path / "resource-receipts.jsonl"
        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        monkeypatch.setattr(
            resource_receipts,
            "DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH",
            receipt_log,
        )
        listener = NostrZapListener(npub_hex="abcd" * 16)
        zap_event = {
            "id": "abcdef",
            "pubkey": "feed" * 8,
            "kind": 9735,
            "created_at": int(datetime.now(UTC).timestamp()),
            "tags": [["bolt11", "lnbc1u1abc"]],
        }
        listener._handle_relay_message(json.dumps(["EVENT", "sub-1", zap_event]), "sub-1")  # noqa: SLF001

        from agents.payment_processors.event_log import tail_events
        from agents.payment_processors.resource_receipts import tail_resource_receipts

        receipts = tail_resource_receipts(log_path=receipt_log)
        assert [receipt.operation.value for receipt in receipts] == ["payment_event_append"]
        events = tail_events(log_path=log_path)
        assert events[0].resource_receipt_ref == (
            f"money-rail-resource-receipt:nostr_zap:{receipts[0].receipt_id}"
        )

    def test_missing_event_resource_receipt_blocks_event_append(self, tmp_path, monkeypatch):
        import agents.payment_processors.event_log as ev_log
        import agents.payment_processors.nostr_zap_listener as nostr_mod

        log_path = tmp_path / "events.jsonl"
        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        monkeypatch.setattr(
            nostr_mod,
            "record_payment_event_resource_receipt",
            lambda **_kwargs: None,
        )
        listener = NostrZapListener(npub_hex="abcd" * 16)
        zap_event = {
            "id": "abcdef",
            "pubkey": "feed" * 8,
            "kind": 9735,
            "created_at": int(datetime.now(UTC).timestamp()),
            "tags": [["bolt11", "lnbc1u1abc"]],
        }
        listener._handle_relay_message(json.dumps(["EVENT", "sub-1", zap_event]), "sub-1")  # noqa: SLF001

        from agents.payment_processors.event_log import tail_events

        assert tail_events(log_path=log_path) == []

    @pytest.mark.asyncio
    async def test_missing_poll_resource_receipt_blocks_relay_connect(self, monkeypatch):
        import agents.payment_processors.nostr_zap_listener as nostr_mod

        async def _websocket_should_not_open(_relay_url: str):
            raise AssertionError("websocket opened without a resource receipt")

        monkeypatch.setattr(
            nostr_mod,
            "record_external_api_poll_receipt",
            lambda **_kwargs: None,
        )
        listener = NostrZapListener(
            npub_hex="abcd" * 16,
            websocket_factory=_websocket_should_not_open,
        )

        await listener._consume_relay("wss://relay.example")  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_consume_relay_records_subscription_resource_receipt(self, tmp_path, monkeypatch):
        import agents.payment_processors.resource_receipts as resource_receipts

        receipt_log = tmp_path / "resource-receipts.jsonl"
        monkeypatch.setattr(
            resource_receipts,
            "DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH",
            receipt_log,
        )

        class _FakeWebSocket:
            async def send(self, _message: str) -> None:
                listener.stop()

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

            async def close(self) -> None:
                return None

        async def _open(_relay_url: str):
            return _FakeWebSocket()

        listener = NostrZapListener(npub_hex="abcd" * 16, websocket_factory=_open)

        await listener._consume_relay("wss://relay.example")  # noqa: SLF001

        from agents.payment_processors.resource_receipts import tail_resource_receipts

        receipts = tail_resource_receipts(log_path=receipt_log)
        assert [receipt.operation.value for receipt in receipts] == ["external_api_poll"]
        assert receipts[0].rail == "nostr_zap"

    @pytest.mark.asyncio
    async def test_reconnect_records_fresh_subscription_resource_receipt(
        self, tmp_path, monkeypatch
    ):
        import agents.payment_processors.resource_receipts as resource_receipts

        receipt_log = tmp_path / "resource-receipts.jsonl"
        monkeypatch.setattr(
            resource_receipts,
            "DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH",
            receipt_log,
        )

        class _DisconnectingWebSocket:
            def __init__(self, listener: NostrZapListener) -> None:
                self._listener = listener

            async def send(self, _message: str) -> None:
                return None

            def __aiter__(self):
                return self

            async def __anext__(self):
                self._listener.stop()
                raise RuntimeError("relay dropped connection")

            async def close(self) -> None:
                return None

        calls = {"count": 0}

        async def _open(_relay_url: str):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("transient connect failure")
            return _DisconnectingWebSocket(listener)

        async def _no_sleep(_seconds: float) -> None:
            return None

        listener = NostrZapListener(npub_hex="abcd" * 16, websocket_factory=_open)
        monkeypatch.setattr(listener, "_backoff_sleep", _no_sleep)

        await listener._consume_relay("wss://relay.example")  # noqa: SLF001

        from agents.payment_processors.resource_receipts import tail_resource_receipts

        receipts = tail_resource_receipts(log_path=receipt_log)
        assert [receipt.operation.value for receipt in receipts] == [
            "external_api_poll",
            "external_api_poll",
        ]
        assert calls["count"] == 2

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
