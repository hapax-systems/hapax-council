"""CHANC build 1, component 2 — han.mail.* evidence events, keyed digests only (SPEC §4).

§4 is a privacy invariant, not a formatting preference: the events are institutional records and
are permanent, so a bare hash of low-entropy personal content is dictionary-reversible. Every
payload therefore carries the KEYED digest — HMAC of the content digest under the keeper key — and
nothing subject-specific: no plain content digest, no sender address, no subject.

Self-authored fixtures only; never the production coord log.
"""

import hashlib
import json

import pytest

from shared import chanc, chanc_evidence

PLAIN = hashlib.sha256(b"self-authored").hexdigest()
KEYED = chanc.keyed_digest(PLAIN, key=b"x" * 32)
HANDLE = "a" * 64
RECEIPT_ID = "20261005T045000Z-aaaaaaaaaaaaaaaa"
TERMS = hashlib.sha256(b"correction terms").hexdigest()
ISSUED = "2026-10-05T04:50:00+00:00"


class FakeLog:
    """A stand-in for CoordEventLog: records the append and the writer kind."""

    def __init__(self):
        self.appended = []

    def append(self, event, *, writer):
        self.appended.append((event, writer))
        return "receipt"


class RaisingLog:
    def append(self, event, *, writer):
        raise RuntimeError("ledger down")


@pytest.fixture(autouse=True)
def _no_production_mirror(monkeypatch):
    monkeypatch.delenv(chanc_evidence.CHANC_EVIDENCE_ENV, raising=False)


def test_emitters_are_off_by_default(monkeypatch):
    """No injected log and no env: the mirror is silent. It is load-bearing for no invariant."""
    monkeypatch.delenv(chanc_evidence.CHANC_EVIDENCE_ENV, raising=False)
    assert (
        chanc_evidence.emit_intake(
            keyed_digest=KEYED, handle=HANDLE, terms_digest=TERMS, issued_at=ISSUED
        )
        is None
    )
    assert chanc_evidence.emit_receipt_issued(keyed_digest=KEYED, receipt_id=RECEIPT_ID) is None


def test_emit_intake_carries_the_keyed_digest_and_nothing_subject_specific():
    log = FakeLog()
    chanc_evidence.emit_intake(
        keyed_digest=KEYED,
        handle=HANDLE,
        terms_digest=TERMS,
        issued_at=ISSUED,
        event_log=log,
    )
    assert len(log.appended) == 1
    event, writer = log.appended[0]
    assert event.event_type == chanc_evidence.CANON_CHANC_INTAKE
    assert event.event_id == chanc_evidence.intake_event_id(keyed_digest=KEYED)
    assert writer.kind == "daemon"
    assert event.payload["keyed_digest"] == KEYED
    assert event.payload["handle"] == HANDLE
    assert event.payload["terms_digest"] == TERMS
    # §4: the plain content digest never enters the log, and no subject-specific content at all.
    serialized = json.dumps(event.payload, sort_keys=True)
    assert PLAIN not in serialized
    for forbidden in ("sender", "from_address", "subject", "recipient", "body"):
        assert forbidden not in event.payload


def test_emit_receipt_issued_carries_the_keyed_digest_only():
    log = FakeLog()
    chanc_evidence.emit_receipt_issued(keyed_digest=KEYED, receipt_id=RECEIPT_ID, event_log=log)
    event, _ = log.appended[0]
    assert event.event_type == chanc_evidence.CANON_CHANC_RECEIPT_ISSUED
    assert event.event_id == chanc_evidence.receipt_issued_event_id(
        keyed_digest=KEYED, receipt_id=RECEIPT_ID
    )
    assert event.payload == {"keyed_digest": KEYED, "receipt_id": RECEIPT_ID}
    assert PLAIN not in json.dumps(event.payload, sort_keys=True)


def test_event_ids_are_deterministic_and_distinct():
    assert chanc_evidence.intake_event_id(keyed_digest=KEYED) == chanc_evidence.intake_event_id(
        keyed_digest=KEYED
    )
    assert chanc_evidence.intake_event_id(keyed_digest=KEYED) != chanc_evidence.intake_event_id(
        keyed_digest="b" * 64
    )
    # An intake and its receipt are distinct events even for the same message.
    assert chanc_evidence.intake_event_id(keyed_digest=KEYED) != (
        chanc_evidence.receipt_issued_event_id(keyed_digest=KEYED, receipt_id=RECEIPT_ID)
    )


def test_emitters_never_raise_when_the_ledger_refuses():
    """Best-effort: a dead ledger must not break the pull or the receipt path."""
    log = RaisingLog()
    assert (
        chanc_evidence.emit_intake(
            keyed_digest=KEYED,
            handle=HANDLE,
            terms_digest=TERMS,
            issued_at=ISSUED,
            event_log=log,
        )
        is None
    )
    assert (
        chanc_evidence.emit_receipt_issued(keyed_digest=KEYED, receipt_id=RECEIPT_ID, event_log=log)
        is None
    )


@pytest.mark.parametrize("bad", ["", "nothex", "A" * 64, None, 64])
def test_emitters_reject_a_non_keyed_digest_without_raising(bad):
    """Only a 64-lowercase-hex keyed digest may enter the log.

    Anything else is skipped: never an exception, and never a fallback that would put a non-keyed
    or plain value into a permanent record.
    """
    log = FakeLog()
    assert (
        chanc_evidence.emit_intake(
            keyed_digest=bad, handle=HANDLE, terms_digest=TERMS, issued_at=ISSUED, event_log=log
        )
        is None
    )
    assert (
        chanc_evidence.emit_receipt_issued(keyed_digest=bad, receipt_id=RECEIPT_ID, event_log=log)
        is None
    )
    assert log.appended == []


# --- the wiring: the receipt path actually emits both events, keyed digests only ------------------
def test_emit_receipts_mirrors_intake_and_issued_into_the_coord_log(tmp_path, monkeypatch):
    """End-to-end through the real coord log, isolated to a temp HAPAX_COORD_DIR.

    Proves the two §4 events are produced by the receipt path itself, and that what lands in the
    permanent log carries the KEYED digest and never the plain one.
    """
    import hashlib as _hashlib
    import importlib.util
    import json as _json
    import os as _os
    from pathlib import Path as _Path

    coord = tmp_path / "coord"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(coord))
    monkeypatch.setenv(chanc_evidence.CHANC_EVIDENCE_ENV, "1")

    source = _Path(__file__).resolve().parents[1] / "scripts/han_mail_pull.py"
    spec = importlib.util.spec_from_file_location("han_mail_pull_component2_target", source)
    pull = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pull)

    keeper = b"test-keeper-key-0123456789abcdef"
    raw = (
        b"From: a@example.invalid\r\nMessage-ID: <abc@example.invalid>\r\n"
        b"Subject: self-authored\r\n\r\nBODY_SENTINEL_DO_NOT_SURFACE\r\n"
    )
    digest = _hashlib.sha256(raw).hexdigest()
    root = tmp_path / "quarantine"
    pull.private_directory(root)
    pull.store_item(
        root,
        digest,
        raw,
        {
            "schema": 1,
            "sender": "a@example.invalid",
            "recipient": "hrl-han@hapaxresearch.com",
            "received_at": "2026-09-19T09:00:00Z",
            "size": len(raw),
            "auth": {"spf": "pass", "dkim": "none", "dmarc": "none"},
        },
    )
    sent = []
    persisted = []
    assert (
        pull.emit_receipts(
            root,
            pull.Budget(root, lambda: 1789808400.0),
            lambda: 1789808400.0,
            send_receipt=lambda **kw: (sent.append(kw), True)[1],
            persist_intake=lambda **kw: persisted.append(kw),
            key=keeper,
            terms_digest=TERMS,
            withdrawal_instructions="Reply to this message quoting your reference.",
        )
        == 1
    )
    assert len(sent) == 1 and len(persisted) == 1

    records = [
        _json.loads(line)
        for line in (coord / "ledger.jsonl").read_text().splitlines()
        if line.strip()
    ]
    types = {record["event_type"] for record in records}
    assert types == {chanc_evidence.CANON_CHANC_INTAKE, chanc_evidence.CANON_CHANC_RECEIPT_ISSUED}
    keyed = chanc.keyed_digest(digest, key=keeper)
    for record in records:
        assert record["payload"]["keyed_digest"] == keyed
        assert record["subject"] == keyed
        # §4: the plain digest and any subject-specific content are absent from the permanent log.
        serialized = _json.dumps(record, sort_keys=True)
        assert digest not in serialized
        for forbidden in ("a@example.invalid", "BODY_SENTINEL_DO_NOT_SURFACE", "self-authored"):
            assert forbidden not in serialized
    assert _os.path.exists(coord / "ledger.jsonl")
