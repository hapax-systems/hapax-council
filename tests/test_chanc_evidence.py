"""CHANC build 1, component 2 — han.mail.* evidence events, keyed digests only (SPEC §4).

§4 is a privacy invariant, not a formatting preference: the events are institutional records and
are permanent, so a bare hash of low-entropy personal content is dictionary-reversible. Every
payload therefore carries the KEYED digest — HMAC of the content digest under the keeper key — and
nothing subject-specific: no plain content digest, no sender address, no subject.

Self-authored fixtures only; never the production coord log.
"""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from shared import chanc, chanc_evidence
from shared.coord_event_log import AppendReceipt, CoordEventLog, DuplicateEventError

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
    assert event.payload == {"keyed_digest": KEYED, "terms_digest": TERMS}
    # §4: the plain content digest never enters the log, and no subject-specific content at all —
    # not the sender's withdrawal handle, and not the 16-hex prefix the receipt id embeds.
    serialized = json.dumps(event.to_record(), sort_keys=True)
    assert PLAIN not in serialized
    assert HANDLE[:16] not in serialized
    for forbidden in ("sender", "from_address", "subject", "recipient", "body"):
        assert forbidden not in event.payload


def test_emit_receipt_issued_carries_the_keyed_digest_only():
    log = FakeLog()
    chanc_evidence.emit_receipt_issued(keyed_digest=KEYED, receipt_id=RECEIPT_ID, event_log=log)
    event, _ = log.appended[0]
    assert event.event_type == chanc_evidence.CANON_CHANC_RECEIPT_ISSUED
    assert event.event_id == chanc_evidence.receipt_issued_event_id(keyed_digest=KEYED)
    assert event.payload == {"keyed_digest": KEYED}
    serialized = json.dumps(event.to_record(), sort_keys=True)
    assert PLAIN not in serialized
    assert RECEIPT_ID not in serialized and HANDLE[:16] not in serialized


def test_event_ids_are_deterministic_and_distinct():
    assert chanc_evidence.intake_event_id(keyed_digest=KEYED) == chanc_evidence.intake_event_id(
        keyed_digest=KEYED
    )
    assert chanc_evidence.intake_event_id(keyed_digest=KEYED) != chanc_evidence.intake_event_id(
        keyed_digest="b" * 64
    )
    # An intake and its receipt are distinct events even for the same message.
    assert chanc_evidence.intake_event_id(keyed_digest=KEYED) != (
        chanc_evidence.receipt_issued_event_id(keyed_digest=KEYED)
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


# --- review fixes (claude-cloud exact-head review of d1a32c64) -------------------------------------
KEEPER = b"test-keeper-key-0123456789abcdef"  # not a real keeper key
NOW = 1789808400.0


def _load_pull(name):
    source = Path(__file__).resolve().parents[1] / "scripts/han_mail_pull.py"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _store(pull, root, *, index=0):
    raw = (
        b"From: a@example.invalid\r\nMessage-ID: <abc@example.invalid>\r\n"
        b"Subject: self-authored\r\n\r\nBODY_SENTINEL_DO_NOT_SURFACE "
        + str(index).encode()
        + b"\r\n"
    )
    digest = hashlib.sha256(raw).hexdigest()
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
    return digest


def _pull(pull, root, *, send, persist=None):
    return pull.emit_receipts(
        root,
        pull.Budget(root, lambda: NOW),
        lambda: NOW,
        send_receipt=send,
        persist_intake=persist if persist is not None else (lambda **kw: None),
        key=KEEPER,
        terms_digest=TERMS,
        withdrawal_instructions="Reply to this message quoting your reference.",
    )


def _ledger_types(coord):
    path = coord / "ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["event_type"] for line in path.read_text().splitlines() if line]


@pytest.fixture
def armed_pull(tmp_path, monkeypatch):
    """The pull module with the mirror armed into an isolated coord dir, and a private root."""
    coord = tmp_path / "coord"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(coord))
    monkeypatch.setenv(chanc_evidence.CHANC_EVIDENCE_ENV, "1")
    pull = _load_pull("han_mail_pull_review_fixes_target")
    root = tmp_path / "quarantine"
    pull.private_directory(root)
    return pull, root, coord


# F1: the intake event is an evidence ref (IntakeRecord.intake_event_id), so it is part of the binding.
def test_receipt_waits_for_the_intake_event_and_a_later_pull_repairs_it(armed_pull, monkeypatch):
    """Ledger down at mint: no receipt goes out citing an event that does not exist. Next pull,
    ledger healthy: the intake event is recorded first, then the one receipt is sent."""
    pull, root, coord = armed_pull
    digest = _store(pull, root)
    sent = []
    send = lambda **kw: (sent.append(kw), True)[1]  # noqa: E731

    real = chanc_evidence.default_event_log
    monkeypatch.setattr(chanc_evidence, "default_event_log", lambda: RaisingLog())
    assert _pull(pull, root, send=send) == 0
    assert sent == []
    item = json.loads((root / f"{digest}.json").read_text())
    assert item["handle"] and not item.get("intake_event_recorded")
    assert item["receipt_issued"] is False

    monkeypatch.setattr(chanc_evidence, "default_event_log", real)
    assert _pull(pull, root, send=send) == 1
    assert len(sent) == 1
    assert _ledger_types(coord) == [
        chanc_evidence.CANON_CHANC_INTAKE,
        chanc_evidence.CANON_CHANC_RECEIPT_ISSUED,
    ]
    item = json.loads((root / f"{digest}.json").read_text())
    assert item["intake_event_recorded"] is True
    assert _pull(pull, root, send=send) == 0  # no second receipt, no second event
    assert len(sent) == 1 and len(_ledger_types(coord)) == 2


def test_intake_event_retried_after_a_failed_send(armed_pull):
    """A failed send leaves the recorded intake event in place; the retry does not re-append."""
    pull, root, coord = armed_pull
    _store(pull, root)
    assert _pull(pull, root, send=lambda **kw: False) == 0
    assert _ledger_types(coord) == [chanc_evidence.CANON_CHANC_INTAKE]
    assert _pull(pull, root, send=lambda **kw: True) == 1
    assert _ledger_types(coord) == [
        chanc_evidence.CANON_CHANC_INTAKE,
        chanc_evidence.CANON_CHANC_RECEIPT_ISSUED,
    ]


def test_main_wiring_arms_the_mirror_with_the_receipt_switch(tmp_path, monkeypatch):
    """The emitter main() builds always carries an event log: an armed receipt path can never send
    a receipt whose intake event was silently skipped because a second switch was unset."""
    monkeypatch.delenv(chanc_evidence.CHANC_EVIDENCE_ENV, raising=False)
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    pull = _load_pull("han_mail_pull_review_wiring_target")
    monkeypatch.setenv(pull.RECEIPT_ARM_ENV, "1")
    monkeypatch.setattr(pull, "keeper_key", lambda: KEEPER)
    monkeypatch.setattr(pull, "chanc_terms", lambda: (TERMS, "withdraw by reply"))
    emitter = pull._armed_emitter()
    assert emitter is not None
    assert isinstance(emitter.keywords["event_log"], CoordEventLog)
    assert emitter.keywords["event_log"].db_path == tmp_path / "coord" / "ledger.db"


def test_injected_dead_ledger_blocks_the_send(tmp_path, monkeypatch):
    """Armed by injection (the main() path), with no env switch: a dead ledger means no receipt."""
    monkeypatch.delenv(chanc_evidence.CHANC_EVIDENCE_ENV, raising=False)
    pull = _load_pull("han_mail_pull_review_inject_target")
    root = tmp_path / "quarantine"
    pull.private_directory(root)
    _store(pull, root)
    sent = []
    monkeypatch.setenv(pull.RECEIPT_ARM_ENV, "1")
    emitter = pull.build_receipt_emitter(
        root,
        lambda: NOW,
        terms_digest=TERMS,
        withdrawal_instructions="w",
        send=lambda **kw: (sent.append(kw), True)[1],
        persist=lambda **kw: None,
        key_resolver=lambda: KEEPER,
        event_log=RaisingLog(),
    )
    assert emitter(root, pull.Budget(root, lambda: NOW), lambda: NOW) == 0
    assert sent == []


# F2: the permanent log holds neither the handle nor the receipt id that embeds its prefix.
def test_ledger_holds_no_handle_and_no_receipt_id(armed_pull):
    pull, root, coord = armed_pull
    digest = _store(pull, root)
    assert _pull(pull, root, send=lambda **kw: True) == 1
    item = json.loads((root / f"{digest}.json").read_text())
    handle, receipt_id = item["handle"], item["receipt_id"]
    for name in ("ledger.jsonl", "ledger.db"):
        data = (coord / name).read_bytes()
        assert handle.encode() not in data
        assert handle[:16].encode() not in data
        assert receipt_id.encode() not in data
    records = [json.loads(line) for line in (coord / "ledger.jsonl").read_text().splitlines()]
    assert [sorted(r["payload"]) for r in records] == [
        ["keyed_digest", "terms_digest"],
        ["keyed_digest"],
    ]


# F3: the mirror switch uses the same truthy rule as the receipt switch.
@pytest.mark.parametrize("value", ["0", "false", "no", "off", " ", "", "False"])
def test_falsy_switch_spellings_keep_the_mirror_off(monkeypatch, value):
    log = FakeLog()
    monkeypatch.setattr(chanc_evidence, "default_event_log", lambda: log)
    monkeypatch.setenv(chanc_evidence.CHANC_EVIDENCE_ENV, value)
    assert not chanc_evidence.evidence_armed()
    assert (
        chanc_evidence.emit_intake(
            keyed_digest=KEYED, handle=HANDLE, terms_digest=TERMS, issued_at=ISSUED
        )
        is None
    )
    assert chanc_evidence.emit_receipt_issued(keyed_digest=KEYED, receipt_id=RECEIPT_ID) is None
    assert log.appended == []


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_truthy_switch_spellings_arm_the_mirror(monkeypatch, value):
    log = FakeLog()
    monkeypatch.setattr(chanc_evidence, "default_event_log", lambda: log)
    monkeypatch.setenv(chanc_evidence.CHANC_EVIDENCE_ENV, value)
    assert chanc_evidence.evidence_armed()
    chanc_evidence.emit_receipt_issued(keyed_digest=KEYED, receipt_id=RECEIPT_ID)
    assert len(log.appended) == 1


# F4: the emitter checks the shape of every field it is handed (keyedness stays the caller's duty).
@pytest.mark.parametrize(
    "overrides",
    [
        {"terms_digest": "a@example.invalid"},
        {"terms_digest": "A" * 64},
        {"issued_at": "whenever"},
        {"issued_at": "2026-10-05T04:50:00"},  # naive: no offset, refused
        {"handle": "a@example.invalid"},
        {"handle": "self-authored subject"},
    ],
)
def test_emit_intake_refuses_malformed_fields(overrides):
    log = FakeLog()
    kwargs = {"keyed_digest": KEYED, "handle": HANDLE, "terms_digest": TERMS, "issued_at": ISSUED}
    kwargs.update(overrides)
    assert chanc_evidence.emit_intake(**kwargs, event_log=log) is None
    assert log.appended == []


@pytest.mark.parametrize("bad", ["", "free text", "20261005T045000Z-AAAAAAAAAAAAAAAA", None])
def test_emit_receipt_issued_refuses_a_malformed_receipt_id(bad):
    log = FakeLog()
    assert (
        chanc_evidence.emit_receipt_issued(keyed_digest=KEYED, receipt_id=bad, event_log=log)
        is None
    )
    assert log.appended == []


# F5: ordering against the send and the persist.
def test_failed_send_emits_no_receipt_issued(armed_pull):
    pull, root, coord = armed_pull
    _store(pull, root)
    assert _pull(pull, root, send=lambda **kw: False) == 0
    assert chanc_evidence.CANON_CHANC_RECEIPT_ISSUED not in _ledger_types(coord)


def test_refused_persist_emits_no_intake_event(armed_pull):
    pull, root, coord = armed_pull
    _store(pull, root)

    def refuse(**kwargs):
        raise pull.IntakeError("Intake receipt record already exists; preserve it and reconcile")

    with pytest.raises(pull.IntakeError):
        _pull(pull, root, send=lambda **kw: True, persist=refuse)
    assert _ledger_types(coord) == []


# F6: one clock format across both events, matching the rest of the coord log.
def test_intake_timestamp_uses_the_coord_log_z_form():
    log = FakeLog()
    chanc_evidence.emit_intake(
        keyed_digest=KEYED, handle=HANDLE, terms_digest=TERMS, issued_at=ISSUED, event_log=log
    )
    event, _ = log.appended[0]
    assert event.timestamp == "2026-10-05T04:50:00Z"


# F7: an already-recorded event is a receipt, not the failure value.
class DuplicateLog:
    def __init__(self, tmp_path):
        self.db_path = tmp_path / "ledger.db"
        self.jsonl_path = tmp_path / "ledger.jsonl"

    def append(self, event, *, writer):
        raise DuplicateEventError(f"coord event already exists: {event.event_id}")


def test_duplicate_append_returns_a_receipt(tmp_path):
    receipt = chanc_evidence.emit_intake(
        keyed_digest=KEYED,
        handle=HANDLE,
        terms_digest=TERMS,
        issued_at=ISSUED,
        event_log=DuplicateLog(tmp_path),
    )
    assert isinstance(receipt, AppendReceipt)
    assert receipt.appended is True
    assert receipt.event_id == chanc_evidence.intake_event_id(keyed_digest=KEYED)


class SpoolingLog:
    """A ledger that only spooled the event: it is not in the canonical log yet."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path

    def append(self, event, *, writer):
        return AppendReceipt(
            event_id=event.event_id,
            appended=False,
            spooled=True,
            sequence=None,
            db_path=self.tmp_path / "ledger.db",
            jsonl_path=self.tmp_path / "ledger.jsonl",
        )


def test_a_spooled_intake_is_not_a_recorded_one(tmp_path):
    """Only a canonical append (or an event already there) may stand behind a cited evidence ref."""
    assert (
        chanc_evidence.emit_intake(
            keyed_digest=KEYED,
            handle=HANDLE,
            terms_digest=TERMS,
            issued_at=ISSUED,
            event_log=SpoolingLog(tmp_path),
        )
        is None
    )
