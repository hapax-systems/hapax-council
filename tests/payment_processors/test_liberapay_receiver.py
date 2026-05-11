"""Tests for ``agents.payment_processors.liberapay_receiver``."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import httpx

from agents.payment_processors.event_log import tail_events
from agents.payment_processors.liberapay_receiver import (
    LiberapayReceiver,
    _is_completed,
    _liberapay_payin_to_event,
)


def _make_response(*, status_code: int = 200, body: Any = None) -> httpx.Response:
    return httpx.Response(status_code, content=json.dumps(body or []).encode("utf-8"))


def _make_client(response: httpx.Response) -> httpx.Client:
    mock = MagicMock(spec=httpx.Client)
    mock.get = MagicMock(return_value=response)
    return mock  # type: ignore[return-value]


class TestIsCompleted:
    def test_succeeded(self):
        assert _is_completed({"status": "succeeded"})
        assert _is_completed({"status": "SUCCEEDED"})

    def test_executed(self):
        assert _is_completed({"state": "executed"})

    def test_pending(self):
        assert not _is_completed({"status": "pending"})


class TestPayinToEvent:
    def test_eur_amount(self):
        payin = {
            "id": "payin-1",
            "amount": {"amount": "10.00", "currency": "EUR"},
            "ctime": "2026-04-25T12:00:00Z",
            "description": "monthly sponsorship",
        }
        event = _liberapay_payin_to_event(payin, "payin-1")
        assert event is not None
        assert event.rail == "liberapay"
        assert event.amount_eur == 10.0
        assert event.external_id == "payin-1"
        assert event.sender_excerpt == "monthly sponsorship"

    def test_usd_amount_no_eur(self):
        payin = {
            "id": "payin-2",
            "amount": {"amount": "5.00", "currency": "USD"},
            "ctime": "2026-04-25T12:00:00Z",
        }
        event = _liberapay_payin_to_event(payin, "payin-2")
        assert event is not None
        assert event.amount_eur is None  # non-EUR not auto-converted

    def test_long_description_truncated(self):
        payin = {
            "id": "payin-3",
            "amount": {"amount": "1.00", "currency": "EUR"},
            "description": "x" * 200,
        }
        event = _liberapay_payin_to_event(payin, "payin-3")
        assert event is not None
        assert len(event.sender_excerpt) <= 80


class TestPollOnce:
    def test_no_credentials_disables_rail(self):
        receiver = LiberapayReceiver(credentials=None)
        emitted = receiver.poll_once()
        assert emitted == 0
        assert receiver.disabled

    def test_401_disables_rail(self, tmp_path, monkeypatch):
        import agents.payment_processors.event_log as ev_log

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", tmp_path / "ev.jsonl")
        client = _make_client(_make_response(status_code=401))
        receiver = LiberapayReceiver(credentials=("u", "p"), http_client=client)
        emitted = receiver.poll_once()
        assert emitted == 0
        assert receiver.disabled

    def test_403_kyc_disables_rail(self, tmp_path, monkeypatch):
        import agents.payment_processors.event_log as ev_log

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", tmp_path / "ev.jsonl")
        client = _make_client(_make_response(status_code=403))
        receiver = LiberapayReceiver(credentials=("u", "p"), http_client=client)
        emitted = receiver.poll_once()
        assert emitted == 0
        assert receiver.disabled

    def test_200_emits_event(self, tmp_path, monkeypatch):
        log_path = tmp_path / "events.jsonl"
        import agents.payment_processors.event_log as ev_log

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        body = [
            {
                "id": "p1",
                "status": "succeeded",
                "amount": {"amount": "5.00", "currency": "EUR"},
                "description": "thanks!",
            }
        ]
        client = _make_client(_make_response(status_code=200, body=body))
        receiver = LiberapayReceiver(credentials=("u", "p"), http_client=client)
        assert receiver.poll_once() == 1
        client.get.assert_called_with("/u/public.json", auth=("u", "p"), timeout=15.0)
        events = tail_events(log_path=log_path)
        assert len(events) == 1
        assert events[0].rail == "liberapay"
        assert events[0].amount_eur == 5.0
        # Idempotent re-poll
        assert receiver.poll_once() == 0

    def test_skips_pending(self, tmp_path, monkeypatch):
        log_path = tmp_path / "events.jsonl"
        import agents.payment_processors.event_log as ev_log

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        body = [
            {
                "id": "p1",
                "status": "pending",
                "amount": {"amount": "5.00", "currency": "EUR"},
            }
        ]
        client = _make_client(_make_response(status_code=200, body=body))
        receiver = LiberapayReceiver(credentials=("u", "p"), http_client=client)
        assert receiver.poll_once() == 0
        assert tail_events(log_path=log_path) == []


def test_module_has_no_payment_initiation_calls():
    """Static guard: liberapay module makes no POST/PUT/DELETE calls."""
    import agents.payment_processors.liberapay_receiver as mod

    src = mod.__loader__.get_source(mod.__name__) or ""  # type: ignore[union-attr]
    assert ".post(" not in src
    assert ".put(" not in src
    assert ".delete(" not in src
