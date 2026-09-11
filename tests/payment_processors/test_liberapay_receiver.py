"""Tests for ``agents.payment_processors.liberapay_receiver``."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import httpx

from agents.payment_processors import event_log as ev_log
from agents.payment_processors import liberapay_receiver as liberapay_mod
from agents.payment_processors import resource_receipts


def _make_response(*, status_code: int = 200, body: Any = None) -> httpx.Response:
    return httpx.Response(status_code, content=json.dumps(body or []).encode("utf-8"))


def _make_client(response: httpx.Response) -> httpx.Client:
    mock = MagicMock(spec=httpx.Client)
    mock.get = MagicMock(return_value=response)
    return mock  # type: ignore[return-value]


class TestIsCompleted:
    def test_succeeded(self):
        assert liberapay_mod._is_completed({"status": "succeeded"})
        assert liberapay_mod._is_completed({"status": "SUCCEEDED"})

    def test_executed(self):
        assert liberapay_mod._is_completed({"state": "executed"})

    def test_pending(self):
        assert not liberapay_mod._is_completed({"status": "pending"})


class TestPayinToEvent:
    def test_eur_amount(self):
        payin = {
            "id": "payin-1",
            "amount": {"amount": "10.00", "currency": "EUR"},
            "ctime": "2026-04-25T12:00:00Z",
            "description": "monthly sponsorship",
        }
        event = liberapay_mod._liberapay_payin_to_event(payin, "payin-1")
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
        event = liberapay_mod._liberapay_payin_to_event(payin, "payin-2")
        assert event is not None
        assert event.amount_eur is None  # non-EUR not auto-converted

    def test_long_description_truncated(self):
        payin = {
            "id": "payin-3",
            "amount": {"amount": "1.00", "currency": "EUR"},
            "description": "x" * 200,
        }
        event = liberapay_mod._liberapay_payin_to_event(payin, "payin-3")
        assert event is not None
        assert len(event.sender_excerpt) <= 80


class TestPollOnce:
    def test_no_credentials_disables_rail(self):
        receiver = liberapay_mod.LiberapayReceiver(credentials=None)
        emitted = receiver.poll_once()
        assert emitted == 0
        assert receiver.disabled

    def test_401_disables_rail(self, tmp_path, monkeypatch):

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", tmp_path / "ev.jsonl")
        client = _make_client(_make_response(status_code=401))
        receiver = liberapay_mod.LiberapayReceiver(credentials=("u", "p"), http_client=client)
        emitted = receiver.poll_once()
        assert emitted == 0
        assert receiver.disabled

    def test_403_kyc_disables_rail(self, tmp_path, monkeypatch):

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", tmp_path / "ev.jsonl")
        client = _make_client(_make_response(status_code=403))
        receiver = liberapay_mod.LiberapayReceiver(credentials=("u", "p"), http_client=client)
        emitted = receiver.poll_once()
        assert emitted == 0
        assert receiver.disabled

    def test_200_emits_event(self, tmp_path, monkeypatch, _durable_chronicle):
        log_path = tmp_path / "events.jsonl"

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
        receiver = liberapay_mod.LiberapayReceiver(credentials=("u", "p"), http_client=client)
        assert receiver.poll_once() == 1
        client.get.assert_called_with("/u/public.json", auth=("u", "p"), timeout=15.0)
        events = ev_log.tail_events(log_path=log_path)
        assert len(events) == 1
        assert events[0].rail == "liberapay"
        assert events[0].amount_eur == 5.0
        # Idempotent re-poll
        assert receiver.poll_once() == 0

    def test_200_records_poll_and_event_resource_receipts(self, tmp_path, monkeypatch):
        log_path = tmp_path / "events.jsonl"
        receipt_log = tmp_path / "resource-receipts.jsonl"

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        monkeypatch.setenv(
            resource_receipts.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
            str(receipt_log),
        )
        body = [
            {
                "id": "p1",
                "status": "succeeded",
                "amount": {"amount": "5.00", "currency": "EUR"},
                "description": "thanks!",
            }
        ]
        client = _make_client(_make_response(status_code=200, body=body))
        sentinel_username = "pass-loaded-user-sentinel"
        receiver = liberapay_mod.LiberapayReceiver(
            credentials=(sentinel_username, "p"), http_client=client
        )

        assert receiver.poll_once() == 1
        client.get.assert_called_with(
            f"/{sentinel_username}/public.json",
            auth=(sentinel_username, "p"),
            timeout=15.0,
        )

        receipts = resource_receipts.tail_resource_receipts(log_path=receipt_log)
        assert [receipt.operation.value for receipt in receipts] == [
            "external_api_poll",
            "payment_event_append",
        ]
        assert sentinel_username not in receipts[0].model_dump_json()
        assert (
            "external_api:GET /{liberapay_username}/public.json" in receipts[0].resource_provenance
        )
        events = ev_log.tail_events(log_path=log_path)
        assert events[0].resource_receipt_ref == (
            f"money-rail-resource-receipt:liberapay:{receipts[1].receipt_id}"
        )

    def test_missing_poll_resource_receipt_blocks_external_get(self, monkeypatch):

        monkeypatch.setattr(
            liberapay_mod,
            "record_external_api_poll_receipt",
            lambda **_kwargs: None,
        )
        client = _make_client(_make_response(status_code=200, body=[]))
        receiver = liberapay_mod.LiberapayReceiver(credentials=("u", "p"), http_client=client)

        assert receiver.poll_once() == 0
        client.get.assert_not_called()

    def test_missing_event_resource_receipt_blocks_event_append(self, tmp_path, monkeypatch):
        log_path = tmp_path / "events.jsonl"

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        monkeypatch.setattr(
            liberapay_mod,
            "commit_prepared_resource_receipt",
            lambda _receipt, **_kwargs: None,
        )
        body = [
            {
                "id": "p1",
                "status": "succeeded",
                "amount": {"amount": "5.00", "currency": "EUR"},
            }
        ]
        client = _make_client(_make_response(status_code=200, body=body))
        receiver = liberapay_mod.LiberapayReceiver(credentials=("u", "p"), http_client=client)

        assert receiver.poll_once() == 0
        assert ev_log.tail_events(log_path=log_path) == []

    def test_failed_event_append_preserves_payment_event_receipt(self, tmp_path, monkeypatch):
        log_path = tmp_path / "events.jsonl"
        receipt_log = tmp_path / "resource-receipts.jsonl"

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        monkeypatch.setenv(
            resource_receipts.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
            str(receipt_log),
        )
        monkeypatch.setattr(liberapay_mod, "append_event", lambda _event: False)
        body = [
            {
                "id": "p1",
                "status": "succeeded",
                "amount": {"amount": "5.00", "currency": "EUR"},
            }
        ]
        client = _make_client(_make_response(status_code=200, body=body))
        receiver = liberapay_mod.LiberapayReceiver(credentials=("u", "p"), http_client=client)

        assert receiver.poll_once() == 0
        assert ev_log.tail_events(log_path=log_path) == []
        assert [
            receipt.operation.value
            for receipt in resource_receipts.tail_resource_receipts(log_path=receipt_log)
        ] == ["external_api_poll", "payment_event_append"]

    def test_skips_pending(self, tmp_path, monkeypatch):
        log_path = tmp_path / "events.jsonl"

        monkeypatch.setattr(ev_log, "DEFAULT_PAYMENT_LOG_PATH", log_path)
        body = [
            {
                "id": "p1",
                "status": "pending",
                "amount": {"amount": "5.00", "currency": "EUR"},
            }
        ]
        client = _make_client(_make_response(status_code=200, body=body))
        receiver = liberapay_mod.LiberapayReceiver(credentials=("u", "p"), http_client=client)
        assert receiver.poll_once() == 0
        assert ev_log.tail_events(log_path=log_path) == []


def test_module_has_no_payment_initiation_calls():
    """Static guard: liberapay module makes no POST/PUT/DELETE calls."""
    src = liberapay_mod.__loader__.get_source(liberapay_mod.__name__) or ""  # type: ignore[union-attr]
    assert ".post(" not in src
    assert ".put(" not in src
    assert ".delete(" not in src
