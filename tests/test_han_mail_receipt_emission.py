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
import smtplib
from datetime import UTC, datetime
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


class EmptyKV:
    """A KV namespace with nothing in it, for the pull-lifecycle tests."""

    def list_keys(self, cursor):
        return [], ""

    def get_value(self, key):
        return None

    def delete_value(self, key):
        pass


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


# --- deferred from #5032 (dev1 stamp 23:16Z, gemini-1): unparseable headers ------------------------
# loop_indicated when the header block is missing or begins beyond 32768 bytes — the only thing
# between an unbounded header block and an auto-reply to a stranger. Shipped untested.
def unparseable_no_boundary() -> bytes:
    """Headers never terminate: no blank line anywhere in the message."""
    return b"Subject: self-authored\r\n" + b"X-Filler: " + b"a" * 200 + b"\r\nbody without a break"


def unparseable_boundary_beyond_limit() -> bytes:
    """A real boundary, but it starts past the 32768-byte header cap."""
    return b"Subject: self-authored\r\n" + b"a" * 33000 + b"\r\n\r\nBODY_SENTINEL_DO_NOT_SURFACE"


@pytest.mark.parametrize("build", [unparseable_no_boundary, unparseable_boundary_beyond_limit])
def test_intake_signals_unparseable_is_loop_indicated(build):
    signals = pull.intake_signals(build())
    assert signals == {"message_id": "", "loop_indicated": True}


@pytest.mark.parametrize("build", [unparseable_no_boundary, unparseable_boundary_beyond_limit])
def test_unparseable_message_is_suppressed_and_never_sent(root, build):
    key = store(root, build(), sender="a@example.invalid")
    sender, persist = FakeSender(), FakePersist()

    assert emit(root, sender, persist) == 0
    assert sender.calls == []
    assert persist.records == {}
    item = read_item(root, key)
    assert item["loop_indicated"] is True
    assert item["receipt_suppressed"] == "loop-indicated"
    assert item["receipt_issued"] is False
    # Terminal: a re-pull does not reconsider it, and still never sends.
    assert emit(root, sender, persist) == 0
    assert sender.calls == []


def test_two_unparseable_messages_do_not_collide(root):
    """Both carry message_id "" — neither may suppress or overwrite the other's record."""
    k0 = store(root, unparseable_boundary_beyond_limit(), sender="a@example.invalid")
    k1 = store(root, unparseable_no_boundary(), sender="b@example.invalid")
    assert k0 != k1

    sender, persist = FakeSender(), FakePersist()
    assert emit(root, sender, persist) == 0
    assert sender.calls == [] and persist.records == {}

    first, second = read_item(root, k0), read_item(root, k1)
    for item in (first, second):
        assert item["message_id"] == ""
        assert item["receipt_suppressed"] == "loop-indicated"
    # Each record still describes its own message: the empty message_id is not an identity.
    assert first["sha256"] == k0 and second["sha256"] == k1
    assert first["raw_file"] == f"{k0}.eml" and second["raw_file"] == f"{k1}.eml"
    assert (root / first["raw_file"]).read_bytes() != (root / second["raw_file"]).read_bytes()


def test_receipt_and_create_once_never_key_on_an_empty_message_id(root):
    """Two messages with NO Message-ID must each get their own receipt and record.

    Keying on message_id would collapse both onto "" — one receipt for two inbounds.
    """
    k0 = store(root, make_raw(0, sender=b"a@example.invalid"), sender="a@example.invalid")
    k1 = store(root, make_raw(1, sender=b"b@example.invalid"), sender="b@example.invalid")
    sender, persist = FakeSender(), FakePersist()

    assert emit(root, sender, persist) == 2
    assert len(sender.calls) == 2
    assert set(persist.records) == {k0, k1}
    for key in (k0, k1):
        item = read_item(root, key)
        assert item["message_id"] == ""
        assert item["receipt_issued"] is True
    assert len({read_item(root, k)["handle"] for k in (k0, k1)}) == 2


# --- the keeper key resolves at run time, fail CLOSED (seat ruling 2026-10-05T00:19:27Z) -----------
def test_emitter_is_disarmed_unless_the_runtime_switch_is_set(root, monkeypatch):
    """Merging slice B must not arm live sending: the switch is the separate runtime act."""
    monkeypatch.delenv(pull.RECEIPT_ARM_ENV, raising=False)
    monkeypatch.setattr(pull, "keeper_key", lambda: KEY)
    assert (
        pull.build_receipt_emitter(
            root,
            lambda: NOW,
            terms_digest=TERMS_DIGEST,
            withdrawal_instructions=WITHDRAWAL,
        )
        is None
    )


def test_emitter_fails_closed_when_the_keeper_key_is_absent(root, monkeypatch):
    """Armed but keyless: no receipt is issued, nothing is sent, and the item is not suppressed."""
    monkeypatch.setenv(pull.RECEIPT_ARM_ENV, "1")
    monkeypatch.setattr(pull, "keeper_key", lambda: None)
    key = store(root, make_raw(0), sender="a@example.invalid")

    assert (
        pull.build_receipt_emitter(
            root,
            lambda: NOW,
            terms_digest=TERMS_DIGEST,
            withdrawal_instructions=WITHDRAWAL,
        )
        is None
    )
    item = read_item(root, key)
    assert item["receipt_issued"] is False
    assert item["receipt_suppressed"] is None  # not issued, and not a terminal suppression


def test_main_wiring_is_dark_by_default(monkeypatch):
    """The wiring main() uses passes no emitter unless the runtime switch is set.

    Both the terms copy and the keeper key are stubbed present, so this pins the SWITCH alone:
    merging slice B must change nothing live until the separate runtime act.
    """
    monkeypatch.delenv(pull.RECEIPT_ARM_ENV, raising=False)
    monkeypatch.setattr(pull, "keeper_key", lambda: KEY)
    monkeypatch.setattr(pull, "chanc_terms", lambda: (TERMS_DIGEST, WITHDRAWAL))
    assert pull._armed_emitter() is None


def test_armed_emitter_issues_through_injected_io(root, monkeypatch):
    """Armed with a key: the emitter wires the injected send + create-once persist end to end."""
    monkeypatch.setenv(pull.RECEIPT_ARM_ENV, "1")
    monkeypatch.setattr(pull, "keeper_key", lambda: KEY)
    key = store(root, make_raw(0, extra=b"Message-ID: <abc@example.invalid>\r\n"))
    sender, persist = FakeSender(), FakePersist()

    emitter = pull.build_receipt_emitter(
        root,
        lambda: NOW,
        terms_digest=TERMS_DIGEST,
        withdrawal_instructions=WITHDRAWAL,
        send=sender,
        persist=persist,
    )
    assert emitter is not None
    assert emitter(root, pull.Budget(root, lambda: NOW), lambda: NOW) == 1
    assert len(sender.calls) == 1 and set(persist.records) == {key}
    assert read_item(root, key)["receipt_issued"] is True


def test_persist_intake_writes_a_create_once_signed_record(tmp_path):
    """The receipt record is create-once, keyed to the KEYED digest, and HMAC-signed."""
    records = tmp_path / "intake"
    digest = hashlib.sha256(b"self-authored").hexdigest()
    handle = chanc.generate_handle()
    receipt = chanc.build_intake_receipt(
        handle=handle,
        content_digest=digest,
        issued_at=datetime.fromtimestamp(NOW, UTC),
        terms_digest=TERMS_DIGEST,
    )
    kwargs = {
        "handle": handle,
        "content_digest": digest,
        "commitment": chanc.salted_commitment(digest, salt=b"s" * 16, key=KEY),
        "salt_hex": (b"s" * 16).hex(),
        "from_address": "a@example.invalid",
        "receipt": receipt,
        "key": KEY,
        "root": records,
    }
    pull.persist_intake(**kwargs)
    keyed = chanc.keyed_digest(digest, key=KEY)
    written = json.loads((records / f"{keyed}.json").read_bytes())
    assert written["keyed_digest"] == keyed
    assert digest not in json.dumps(written)  # the plain digest is never in the record
    assert written["authority_signature"].startswith("hmac-sha256:")
    assert written["from_address"] == "a@example.invalid"

    # Create-once: a second write for the same message is refused, never overwritten.
    with pytest.raises(pull.IntakeError):
        pull.persist_intake(**kwargs)
    assert json.loads((records / f"{keyed}.json").read_bytes()) == written


def test_send_receipt_refuses_without_the_submission_credential(tmp_path, monkeypatch):
    monkeypatch.setattr(pull, "smtp_credential", lambda: None)
    sent = []

    def transport(sender, token, message):
        sent.append(sender)
        raise AssertionError("no connection may be opened without a credential")

    assert (
        pull.send_receipt(
            to="a@example.invalid",
            subject="s",
            body="b",
            headers={},
            root=tmp_path,
            transport=transport,
        )
        is False
    )
    assert sent == []
    assert list(tmp_path.glob("*.json")) == []


def test_send_receipt_is_one_send_per_message(tmp_path):
    sent = []

    def transport(sender, token, message):
        # The finding was that this fake only recorded a call. Assert the built message itself.
        assert message["From"] == "hrl-han@hapaxresearch.com"
        assert message["To"] == "a@example.invalid"
        assert message["Subject"] == "s"
        assert message["Auto-Submitted"] == "auto-replied"
        assert "b" in message.get_content()
        sent.append(sender)
        return True

    kwargs = {
        "to": "a@example.invalid",
        "subject": "s",
        "body": "b",
        "headers": {"Auto-Submitted": "auto-replied"},
        "root": tmp_path,
        "transport": transport,
        "credential": lambda: "token",
    }
    assert pull.send_receipt(**kwargs) is True
    assert len(sent) == 1
    # A second attempt for the SAME message never opens a second send.
    assert pull.send_receipt(**kwargs) is False
    assert len(sent) == 1


def test_send_receipt_ambiguous_result_is_not_retried(tmp_path):
    """A failure after the transaction started is ambiguous: recorded, never retried blind."""
    attempts = []

    def transport(sender, token, message):
        attempts.append(sender)
        raise pull.IntakeError("connection dropped after DATA")

    kwargs = {
        "to": "a@example.invalid",
        "subject": "s",
        "body": "b",
        "headers": {},
        "root": tmp_path,
        "transport": transport,
        "credential": lambda: "token",
    }
    assert pull.send_receipt(**kwargs) is False
    assert len(attempts) == 1
    assert pull.send_receipt(**kwargs) is False
    assert len(attempts) == 1  # the ambiguous attempt is not repeated


def test_send_receipt_pre_send_failure_stays_retryable(tmp_path):
    """Nothing submitted => outcome pre_send_failed => a later pull may try again."""
    attempts = []

    def transport(sender, token, message):
        attempts.append(sender)
        raise pull.ReceiptTransportError("connect refused")

    kwargs = {
        "to": "a@example.invalid",
        "subject": "s",
        "body": "b",
        "headers": {},
        "root": tmp_path,
        "transport": transport,
        "credential": lambda: "token",
    }
    assert pull.send_receipt(**kwargs) is False
    assert len(attempts) == 1
    # The intent is durable (the crash guard) but the outcome records that nothing was submitted.
    assert len(list(tmp_path.glob("*.intent.json"))) == 1
    outcomes = list(tmp_path.glob("*.outcome.json"))
    assert len(outcomes) == 1
    assert json.loads(outcomes[0].read_bytes())["outcome"] == "pre_send_failed"
    assert pull.send_receipt(**kwargs) is False
    assert len(attempts) == 2  # and the retry is allowed


# --- review findings on #5037: resolvers, the real transport, the crash guard ---------------------
class _Completed:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


@pytest.mark.parametrize(
    "result,expected",
    [
        (_Completed(0, "  a-value\n"), "a-value"),
        (_Completed(1, "a-value"), None),  # nonzero returncode: fail closed
        (_Completed(0, "   \n"), None),  # empty value: fail closed
        (OSError("hapax-secret missing"), None),
    ],
)
def test_secret_resolution_and_its_error_paths(monkeypatch, result, expected):
    def fake_run(argv, **kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(pull.subprocess, "run", fake_run)
    assert pull._secret("some-name") == expected


def test_keeper_key_and_smtp_credential_resolve_by_name(monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        return _Completed(0, "resolved")

    monkeypatch.setattr(pull.subprocess, "run", fake_run)
    assert pull.keeper_key() == b"resolved"
    assert pull.smtp_credential() == "resolved"
    assert seen == [
        ["hapax-secret", pull.KEEPER_KEY_NAME],
        ["hapax-secret", pull.SUBMISSION_SECRET],
    ]
    monkeypatch.setattr(pull.subprocess, "run", lambda *a, **k: _Completed(1, "x"))
    assert pull.keeper_key() is None  # absent => None, so the caller fails closed


def test_chanc_terms_reads_the_copy_or_refuses(tmp_path, monkeypatch):
    terms = tmp_path / "terms.md"
    monkeypatch.setattr(pull, "CHANC_TERMS", terms)
    assert pull.chanc_terms() is None  # missing file
    terms.write_text("   \n\n")
    assert pull.chanc_terms() is None  # whitespace only
    terms.write_text("Ask to withdraw; never deleted on a sending address alone.")
    digest, text = pull.chanc_terms()
    assert digest == hashlib.sha256(terms.read_bytes()).hexdigest()
    assert text.startswith("Ask to withdraw")


def test_receipt_message_populates_headers_and_drops_empty_values():
    message = pull._receipt_message(
        sender="hrl-han@hapaxresearch.com",
        to="a@example.invalid",
        subject="Received — corrections channel [X]",
        body="body text",
        headers={"Auto-Submitted": "auto-replied", "In-Reply-To": "", "X-Kept": "yes"},
    )
    assert message["From"] == "hrl-han@hapaxresearch.com"
    assert message["To"] == "a@example.invalid"
    assert message["Subject"].startswith("Received")
    assert message["Auto-Submitted"] == "auto-replied"  # RFC 3834 §5, the loop-safety header
    assert message["X-Kept"] == "yes"
    assert message["In-Reply-To"] is None  # an empty header value is dropped, not sent blank
    assert "body text" in message.get_content()


class _FakeSMTP:
    """Stands in for smtplib.SMTP, with a settable failure stage."""

    def __init__(self, fail_at=None):
        self.calls = []
        self.messages = []
        self.fail_at = fail_at

    def close(self):
        self.calls.append("close")

    def _stage(self, name):
        self.calls.append(name)
        if self.fail_at == name:
            raise smtplib.SMTPException(f"{name} failed")

    def ehlo(self):
        self._stage("ehlo")
        return 250, b""

    def starttls(self, context=None):
        self._stage("starttls")

    def login(self, sender, token):
        self._stage("login")

    def send_message(self, message):
        self.messages.append(message)
        self._stage("send_message")


@pytest.mark.parametrize("fail_at", [None, "ehlo", "starttls", "login"])
def test_proton_transport_sequence_and_pre_send_boundary(monkeypatch, fail_at):
    fake = _FakeSMTP(fail_at=fail_at)
    monkeypatch.setattr(pull.smtplib, "SMTP", lambda *a, **k: fake)
    message = pull._receipt_message(sender="s", to="t", subject="x", body="b", headers={})
    if fail_at is None:
        pull._proton_transport("s", "token", message)
        assert fake.calls == ["ehlo", "starttls", "ehlo", "login", "send_message", "close"]
    else:
        # Connect/STARTTLS/login failures submitted nothing: they must map to the retryable class.
        with pytest.raises(pull.ReceiptTransportError):
            pull._proton_transport("s", "token", message)


def test_proton_transport_post_start_failure_is_not_pre_send(monkeypatch):
    """A failure in send_message is ambiguous, NOT the retryable pre-send class."""
    fake = _FakeSMTP(fail_at="send_message")
    monkeypatch.setattr(pull.smtplib, "SMTP", lambda *a, **k: fake)
    message = pull._receipt_message(sender="s", to="t", subject="x", body="b", headers={})
    with pytest.raises(smtplib.SMTPException) as excinfo:
        pull._proton_transport("s", "token", message)
    assert not isinstance(excinfo.value, pull.ReceiptTransportError)
    assert "close" in fake.calls  # the connection is closed even on a post-start failure


def test_proton_transport_connect_failure_is_pre_send(monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(pull.smtplib, "SMTP", boom)
    message = pull._receipt_message(sender="s", to="t", subject="x", body="b", headers={})
    with pytest.raises(pull.ReceiptTransportError):
        pull._proton_transport("s", "token", message)


def test_send_receipt_writes_the_intent_before_the_send(tmp_path):
    """The guard must exist at the moment the transaction starts, not after it returns."""
    observed = {}

    def transport(sender, token, message):
        observed["intents"] = sorted(p.name for p in tmp_path.glob("*.intent.json"))
        observed["outcomes_at_send"] = sorted(p.name for p in tmp_path.glob("*.outcome.json"))

    assert (
        pull.send_receipt(
            to="a@example.invalid",
            subject="s",
            body="b",
            headers={},
            root=tmp_path,
            transport=transport,
            credential=lambda: "token",
        )
        is True
    )
    assert len(observed["intents"]) == 1  # durable BEFORE the send
    assert observed["outcomes_at_send"] == []  # and the outcome only lands after
    assert len(list(tmp_path.glob("*.outcome.json"))) == 1


def test_send_receipt_crash_after_intent_still_refuses_a_replay(tmp_path):
    """The review's defect: a kill between intent and outcome must NOT permit a second send."""
    key = hashlib.sha256(
        b"\0".join(p.encode() for p in ("a@example.invalid", "s", "b"))
    ).hexdigest()
    (tmp_path / f"{key}.intent.json").write_text('{"type": "han.mail.receipt-intent"}\n')
    attempts = []

    def transport(sender, token, message):
        attempts.append(sender)

    assert (
        pull.send_receipt(
            to="a@example.invalid",
            subject="s",
            body="b",
            headers={},
            root=tmp_path,
            transport=transport,
            credential=lambda: "token",
        )
        is False
    )
    assert attempts == []  # no second receipt can reach the stranger


def test_armed_emitter_terms_missing_and_armed_paths(root, monkeypatch):
    monkeypatch.setenv(pull.RECEIPT_ARM_ENV, "1")
    monkeypatch.setattr(pull, "keeper_key", lambda: KEY)
    monkeypatch.setattr(pull, "chanc_terms", lambda: None)
    assert pull._armed_emitter() is None  # armed but no terms: fail closed
    monkeypatch.setattr(pull, "chanc_terms", lambda: (TERMS_DIGEST, WITHDRAWAL))
    assert pull._armed_emitter() is not None  # fully armed


def test_persist_intake_refusal_propagates_out_of_run_once(root, monkeypatch):
    """A create-once refusal must fail the pull loudly, carrying its reconcile instruction."""
    monkeypatch.setenv(pull.RECEIPT_ARM_ENV, "1")
    monkeypatch.setattr(pull, "keeper_key", lambda: KEY)

    def refuse(**kwargs):
        raise pull.IntakeError("Intake receipt record already exists; preserve it and reconcile")

    emitter = pull.build_receipt_emitter(
        root,
        lambda: NOW,
        terms_digest=TERMS_DIGEST,
        withdrawal_instructions=WITHDRAWAL,
        send=lambda **kw: True,
        persist=refuse,
    )
    assert emitter is not None
    store(root, make_raw(0, extra=b"Message-ID: <a@example.invalid>\r\n"))
    with pytest.raises(pull.IntakeError, match="reconcile"):
        pull.run_once(EmptyKV(), root, lambda *a, **k: True, lambda: NOW, emit=emitter)


# --- fix-first (dev1 ruling 2026-10-05T10:22:16Z): the REAL functions, end to end -----------------
def test_real_send_and_persist_drive_through_emit_receipts(root, tmp_path, monkeypatch):
    """Only the SMTP client object is stubbed; the real send_receipt and persist_intake run.

    The gemini major on #5037: (a) keyword compatibility, (b) the Auto-Submitted header on the
    message ACTUALLY emitted, and (c) the cross-pull one-send guard were all unverified.
    """
    monkeypatch.setenv(pull.RECEIPT_ARM_ENV, "1")
    monkeypatch.setattr(pull, "keeper_key", lambda: KEY)
    monkeypatch.setattr(pull, "chanc_terms", lambda: (TERMS_DIGEST, WITHDRAWAL))
    monkeypatch.setattr(pull, "smtp_credential", lambda: "token")
    records, outbound = tmp_path / "intake", tmp_path / "outbound"
    monkeypatch.setattr(pull, "INTAKE_RECORDS", records)
    monkeypatch.setattr(pull, "OUTBOUND_RECORDS", outbound)
    client = _FakeSMTP()
    monkeypatch.setattr(pull.smtplib, "SMTP", lambda *a, **k: client)

    key = store(
        root,
        make_raw(0, extra=b"Message-ID: <abc@example.invalid>\r\n"),
        sender="a@example.invalid",
    )
    emitter = pull.build_receipt_emitter(
        root, lambda: NOW, terms_digest=TERMS_DIGEST, withdrawal_instructions=WITHDRAWAL
    )
    assert emitter is not None
    assert emitter(root, pull.Budget(root, lambda: NOW), lambda: NOW) == 1

    # (a) the real persist_intake accepted emit_receipts' keywords and wrote to the redirected root.
    written = list(records.glob("*.json"))
    assert len(written) == 1
    assert json.loads(written[0].read_bytes())["handle"] == read_item(root, key)["handle"]

    # (b) the ACTUAL emitted message, through the real send_receipt and transport.
    assert len(client.messages) == 1
    sent = client.messages[0]
    assert sent["Auto-Submitted"] == "auto-replied"  # RFC 3834 §5, the loop-safety header
    assert sent["From"] == pull.RECEIPT_SENDER
    assert sent["To"] == "a@example.invalid"
    assert sent["In-Reply-To"] == "<abc@example.invalid>"
    assert read_item(root, key)["receipt_id"] in sent["Subject"] + sent.get_content()
    assert client.calls == ["ehlo", "starttls", "ehlo", "login", "send_message", "close"]

    # (c) simulate a crash after the send but before the item flag was durable, then pull again.
    item = read_item(root, key)
    item["receipt_issued"] = False
    (root / f"{key}.json").write_text(json.dumps(item))
    assert emitter(root, pull.Budget(root, lambda: NOW), lambda: NOW) == 0
    assert len(client.messages) == 1  # never a second receipt to the same stranger
    assert len(list(outbound.glob("*.intent.json"))) == 1
