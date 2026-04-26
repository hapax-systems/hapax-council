"""Tests for ``agents.payment_processors.lightning_receiver``."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import httpx

from agents.payment_processors.event_log import (
    tail_events,
)
from agents.payment_processors.lightning_receiver import (
    LightningReceiver,
    _alby_invoice_to_event,
    _is_settled,
)


def _make_response(*, status_code: int = 200, body: Any = None) -> httpx.Response:
    if body is None:
        body = []
    return httpx.Response(status_code, content=json.dumps(body).encode("utf-8"))


def _make_client(response: httpx.Response) -> httpx.Client:
    """Construct a fully-mocked httpx.Client returning the given response."""
    mock = MagicMock(spec=httpx.Client)
    mock.get = MagicMock(return_value=response)
    return mock  # type: ignore[return-value]


class TestIsSettled:
    def test_state_settled(self):
        assert _is_settled({"state": "SETTLED"})
        assert _is_settled({"state": "settled"})

    def test_settled_bool(self):
        assert _is_settled({"settled": True})

    def test_unsettled(self):
        assert not _is_settled({"state": "open"})
        assert not _is_settled({})


class TestAlbyInvoiceToEvent:
    def test_amount_msat_to_sats(self):
        invoice = {
            "amount": 5000,  # msat
            "settled_at": 1700000000,
            "memo": "hello",
            "payment_hash": "abc123",
        }
        event = _alby_invoice_to_event(invoice, "abc123")
        assert event is not None
        assert event.rail == "lightning"
        assert event.amount_sats == 5
        assert event.external_id == "abc123"
        assert event.sender_excerpt == "hello"

    def test_truncates_long_memo(self):
        invoice = {
            "amount": 1000,
            "memo": "x" * 200,
            "payment_hash": "abc",
        }
        event = _alby_invoice_to_event(invoice, "abc")
        assert event is not None
        assert len(event.sender_excerpt) <= 80

    def test_fiat_in_cents_to_usd(self):
        invoice = {
            "amount": 10000,
            "fiat_in_cents": 1234,
            "payment_hash": "abc",
        }
        event = _alby_invoice_to_event(invoice, "abc")
        assert event is not None
        assert event.amount_usd == 12.34


class TestPollOnce:
    def test_no_token_disables_rail(self, tmp_path, monkeypatch):
        """Receiver disables itself when token is absent."""
        receiver = LightningReceiver(token=None)
        emitted = receiver.poll_once()
        assert emitted == 0
        assert receiver.disabled

    def test_401_disables_rail(self, tmp_path, monkeypatch):
        """Alby 401 → refusal annex + rail disabled."""
        monkeypatch.setattr(
            "agents.payment_processors.event_log.DEFAULT_PAYMENT_LOG_PATH",
            tmp_path / "events.jsonl",
        )
        client = _make_client(_make_response(status_code=401, body={}))
        receiver = LightningReceiver(token="fake-token", http_client=client)
        emitted = receiver.poll_once()
        assert emitted == 0
        assert receiver.disabled
        # Subsequent polls are no-ops
        assert receiver.poll_once() == 0

    def test_200_emits_event(self, tmp_path, monkeypatch):
        log_path = tmp_path / "events.jsonl"
        monkeypatch.setattr(
            "agents.payment_processors.event_log.DEFAULT_PAYMENT_LOG_PATH",
            log_path,
        )
        # The Lightning receiver writes via the module-level
        # `append_event` which closes over the default path lazily;
        # patch by re-importing or by passing log_path. The event_log
        # module uses DEFAULT_PAYMENT_LOG_PATH at call time, so the
        # monkeypatch above is sufficient if `append_event` is
        # called with the patched default.
        import agents.payment_processors.event_log as ev_log

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        body = [
            {
                "state": "settled",
                "amount": 21000,  # msat = 21 sats
                "memo": "thanks",
                "payment_hash": "h1",
            }
        ]
        client = _make_client(_make_response(status_code=200, body=body))
        receiver = LightningReceiver(token="fake-token", http_client=client)
        emitted = receiver.poll_once()
        assert emitted == 1
        events = tail_events(log_path=log_path)
        assert len(events) == 1
        assert events[0].external_id == "h1"
        # Idempotent: second poll with same payload emits nothing
        emitted_2 = receiver.poll_once()
        assert emitted_2 == 0

    def test_skips_unsettled(self, tmp_path, monkeypatch):
        log_path = tmp_path / "events.jsonl"
        import agents.payment_processors.event_log as ev_log

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        body = [{"state": "open", "amount": 1000, "payment_hash": "h1"}]
        client = _make_client(_make_response(status_code=200, body=body))
        receiver = LightningReceiver(token="fake-token", http_client=client)
        emitted = receiver.poll_once()
        assert emitted == 0
        assert tail_events(log_path=log_path) == []

    def test_500_logged_no_emit(self, tmp_path, monkeypatch):
        log_path = tmp_path / "events.jsonl"
        import agents.payment_processors.event_log as ev_log

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        client = _make_client(_make_response(status_code=503, body={}))
        receiver = LightningReceiver(token="fake-token", http_client=client)
        assert receiver.poll_once() == 0
        # Rail is NOT disabled on transient server errors
        assert not receiver.disabled


def test_module_has_no_payments_send_function():
    """Static guard: the lightning module must not import POST/payment senders."""
    import agents.payment_processors.lightning_receiver as mod

    src = mod.__loader__.get_source(mod.__name__) or ""  # type: ignore[union-attr]
    # No httpx.post / httpx.put — the module is read-only.
    assert ".post(" not in src
    assert ".put(" not in src
    assert ".delete(" not in src
