"""CHANC build 1, component 1 — the §5 receipt-emission discipline in han_mail_pull.

Self-authored foreign-data fixtures only; never the production quarantine, never a real address.
The two terminal effects (the keeper-signed create-once record and the SMTP send) are injected and
faked here — this battery pins the DISCIPLINE: one receipt per inbound, idempotent across re-pulls
and failed sends, anti-loop suppression, the spend cap, and the §5/§10 receipt content.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from shared import chanc

SOURCE = Path(__file__).resolve().parents[1] / "scripts/han_mail_pull.py"
_spec = importlib.util.spec_from_file_location(
    "han_mail_pull_receipt_target", os.environ.get("HAN_MAIL_PULL_UNDER_TEST", SOURCE)
)
pull = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pull)

NOW = 1789808400.0
KEY = b"test-keeper-key-0123456789abcdef"  # not a real keeper key
TERMS_DIGEST = hashlib.sha256(b"corrections-terms-v1").hexdigest()
WITHDRAWAL = "Reply to this message quoting your reference to withdraw it."


def make_raw(
    index: int, *, sender: bytes = b"fixture@example.invalid", extra: bytes = b""
) -> bytes:
    """A self-authored message with a unique body (so each sha256 key differs)."""
    return (
        b"From: " + sender + b"\r\n" + extra + b"Subject: self-authored test\r\n\r\n"
        b"BODY_SENTINEL_DO_NOT_SURFACE " + str(index).encode() + b"\r\n"
    )


def store(root: Path, raw: bytes, *, sender: str = "fixture@example.invalid") -> str:
    key = hashlib.sha256(raw).hexdigest()
    metadata = {
        "schema": 1,
        "sender": sender,
        "recipient": "hrl-han@hapaxresearch.com",
        "received_at": "2026-09-19T09:00:00Z",
        "size": len(raw),
        "auth": {"spf": "pass", "dkim": "none", "dmarc": "none"},
    }
    pull.store_item(root, key, raw, metadata)
    return key


def read_item(root: Path, key: str) -> dict:
    return json.loads((root / f"{key}.json").read_bytes())


@pytest.fixture
def root(tmp_path):
    directory = tmp_path / "quarantine"
    pull.private_directory(directory)
    return directory


class FakeSender:
    """Records each injected send; ``result`` is the accepted/declined verdict."""

    def __init__(self, result=True):
        self.calls = []
        self.result = result

    def __call__(self, *, to, subject, body, headers):
        self.calls.append({"to": to, "subject": subject, "body": body, "headers": headers})
        return self.result(len(self.calls)) if callable(self.result) else self.result


class FakePersist:
    """Records each create-once intake persistence and fails a second call for the same digest."""

    def __init__(self):
        self.records = {}

    def __call__(self, *, handle, content_digest, commitment, salt_hex, from_address, receipt):
        assert content_digest not in self.records, "intake persisted twice for one message"
        self.records[content_digest] = {
            "handle": handle,
            "commitment": commitment,
            "salt_hex": salt_hex,
            "from_address": from_address,
            "receipt": receipt,
        }


def emit(root, sender, persist, *, clock=lambda: NOW, budget=None):
    budget = budget if budget is not None else pull.Budget(root, clock)
    return pull.emit_receipts(
        root,
        budget,
        clock,
        send_receipt=sender,
        persist_intake=persist,
        key=KEY,
        terms_digest=TERMS_DIGEST,
        withdrawal_instructions=WITHDRAWAL,
    )


# --- §9: two inbound messages trigger at most one receipt each -----------------------------------
def test_two_inbound_messages_one_receipt_each(root):
    k0 = store(root, make_raw(0), sender="a@example.invalid")
    k1 = store(root, make_raw(1), sender="b@example.invalid")
    sender, persist = FakeSender(), FakePersist()

    assert emit(root, sender, persist) == 2
    assert len(sender.calls) == 2
    assert {c["to"] for c in sender.calls} == {"a@example.invalid", "b@example.invalid"}
    handles = {read_item(root, k)["handle"] for k in (k0, k1)}
    assert len(handles) == 2  # distinct random handles
    assert set(persist.records) == {k0, k1}
    for k in (k0, k1):
        assert read_item(root, k)["receipt_issued"] is True


def test_re_pull_sends_no_second_receipt(root):
    store(root, make_raw(0))
    sender, persist = FakeSender(), FakePersist()
    assert emit(root, sender, persist) == 1
    # A second pull of the same quarantine must not re-send (idempotent / replay).
    assert emit(root, sender, persist) == 0
    assert len(sender.calls) == 1
    assert len(persist.records) == 1


def test_failed_send_retries_the_same_handle_once(root):
    key = store(root, make_raw(0))
    persist = FakePersist()
    # First pull: the send is declined; the item keeps its minted handle, unissued.
    assert emit(root, FakeSender(result=False), persist) == 0
    first = read_item(root, key)
    assert first["receipt_issued"] is False
    assert chanc.is_valid_handle(first["handle"])
    # Second pull: a working send reuses the SAME handle; the intake is not persisted again.
    sender = FakeSender(result=True)
    assert emit(root, sender, persist) == 1
    assert read_item(root, key)["handle"] == first["handle"]
    assert len(persist.records) == 1
    assert len(sender.calls) == 1


# --- §9: anti-loop suppression (auto-generated / bulk mail) and no-reply-address ------------------
@pytest.mark.parametrize(
    "extra,sender_addr,reason",
    [
        (b"Auto-Submitted: auto-generated\r\n", "a@example.invalid", "loop-indicated"),
        (b"Auto-Submitted: auto-replied\r\n", "a@example.invalid", "loop-indicated"),
        (b"Precedence: bulk\r\n", "a@example.invalid", "loop-indicated"),
        (b"List-Id: <x.example.invalid>\r\n", "a@example.invalid", "loop-indicated"),
        (b"X-Autoreply: yes\r\n", "a@example.invalid", "loop-indicated"),
        (b"", "(unknown)", "no-reply-address"),
    ],
)
def test_suppressed_without_sending(root, extra, sender_addr, reason):
    key = store(root, make_raw(0, extra=extra), sender=sender_addr)
    sender, persist = FakeSender(), FakePersist()
    assert emit(root, sender, persist) == 0
    assert sender.calls == []
    assert persist.records == {}
    item = read_item(root, key)
    assert item["receipt_suppressed"] == reason
    assert item["receipt_issued"] is False
    # Suppression is terminal: a re-pull does not reconsider it.
    assert emit(root, sender, persist) == 0
    assert sender.calls == []


def test_auto_submitted_no_is_not_suppressed(root):
    # "Auto-Submitted: no" is explicitly NOT an auto-reply; it must still receive a receipt.
    key = store(root, make_raw(0, extra=b"Auto-Submitted: no\r\n"))
    sender, persist = FakeSender(), FakePersist()
    assert emit(root, sender, persist) == 1
    assert read_item(root, key)["receipt_issued"] is True


# --- §5: the send rides the spend cap ------------------------------------------------------------
def test_spend_cap_defers_the_rest(root, monkeypatch):
    monkeypatch.setitem(pull.LIMITS, "receipts", 1)
    k0 = store(root, make_raw(0), sender="a@example.invalid")
    k1 = store(root, make_raw(1), sender="b@example.invalid")
    sender, persist = FakeSender(), FakePersist()
    assert emit(root, sender, persist) == 1
    issued = [k for k in (k0, k1) if read_item(root, k)["receipt_issued"]]
    deferred = [k for k in (k0, k1) if not read_item(root, k)["receipt_issued"]]
    assert len(issued) == 1 and len(deferred) == 1
    # The deferred item is neither suppressed nor given an orphan intake record.
    deferred_item = read_item(root, deferred[0])
    assert deferred_item["receipt_suppressed"] is None
    assert "handle" not in deferred_item
    assert set(persist.records) == set(issued)


# --- §5/§10/D4: the receipt content ---------------------------------------------------------------
def test_receipt_content_and_headers(root):
    key = store(root, make_raw(0, extra=b"Message-ID: <abc@example.invalid>\r\n"))
    sender, persist = FakeSender(), FakePersist()
    emit(root, sender, persist)
    call = sender.calls[0]
    item = read_item(root, key)
    handle = item["handle"]

    assert handle in call["body"]
    assert item["receipt_id"] in call["body"]
    assert TERMS_DIGEST in call["body"]
    assert WITHDRAWAL in call["body"]
    assert chanc.RECEIPT_CLAIM_CEILING in call["body"]
    # §10 claim ceiling: no over-claim anywhere in the reply.
    lowered = call["body"].lower()
    for forbidden in ("immutable", "tamper-proof", "tamper proof", "anchored"):
        assert forbidden not in lowered
    # Q1 seat ruling: the header is auto-replied, and the inbound Message-ID rides In-Reply-To.
    assert call["headers"]["Auto-Submitted"] == "auto-replied"
    assert call["headers"]["In-Reply-To"] == "<abc@example.invalid>"
    # D4: the handle the sender cites is random, NOT the content digest.
    assert handle != key
    assert chanc.is_valid_handle(handle)


def test_run_once_without_emit_is_unchanged(root, monkeypatch):
    # The default (no emitter) keeps the legacy result shape — nothing is sent until slice B wires it.
    class EmptyKV:
        def list_keys(self, cursor):
            return [], ""

        def get_value(self, key):
            return None

        def delete_value(self, key):
            pass

    result = pull.run_once(EmptyKV(), root, lambda *a, **k: True, lambda: NOW)
    assert result == {"pulled": 0, "notified": 0}
    assert "receipts" not in result


# --- pure §5 builder ------------------------------------------------------------------------------
def test_build_intake_receipt_shape():
    handle = chanc.generate_handle()
    digest = hashlib.sha256(b"bytes").hexdigest()
    from datetime import UTC, datetime

    receipt = chanc.build_intake_receipt(
        handle=handle,
        content_digest=digest,
        issued_at=datetime(2026, 10, 4, 19, 0, tzinfo=UTC),
        terms_digest=TERMS_DIGEST,
    )
    assert receipt["witness"] == "SEEN"
    assert receipt["act_type"] == "intake"
    assert receipt["handle"] == handle and receipt["content_digest"] == digest
    assert receipt["interaction"] == {
        "protocol": "email",
        "channel": "hrl-han@",
        "purpose": "correction",
    }
    assert receipt["receipt_id"].startswith("20261004T190000Z-")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"handle": "nothex", "content_digest": "a" * 64, "terms_digest": "b" * 64},
        {"handle": "a" * 64, "content_digest": "nothex", "terms_digest": "b" * 64},
        {"handle": "a" * 64, "content_digest": "a" * 64, "terms_digest": "nothex"},
    ],
)
def test_build_intake_receipt_rejects_malformed(kwargs):
    from datetime import UTC, datetime

    with pytest.raises(ValueError):
        chanc.build_intake_receipt(issued_at=datetime(2026, 1, 1, tzinfo=UTC), **kwargs)
