"""CHANC build 1, component 3 — the withdrawal resolver and disposition responder (§6).

The reply SURFACING (pulling a withdrawal request out of an inbound reply) is owned by
han-mail-correction-intake-extension-20260924, which is unstarted; this module is built against
``chanc.IntakeRecord`` and a reply-path seam of its own, and the composition point is flagged
provisional in the PR body.

Self-authored fixtures only: never the production intake store, never a real address.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared import chanc, chanc_withdrawal

NOW = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
HANDLE = "a" * 64
KEYED = hashlib.sha256(b"keyed").hexdigest()
FROM = "sender@example.invalid"
RECEIPT_ID = "20261005T070000Z-aaaaaaaaaaaaaaaa"


def write_record(
    root: Path,
    *,
    handle: str = HANDLE,
    from_address: str = FROM,
    receipt_id: str = RECEIPT_ID,
    keyed: str = KEYED,
    raw: str | None = None,
) -> Path:
    """The create-once record shape han_mail_pull.persist_intake writes."""
    root.mkdir(parents=True, exist_ok=True)
    payload = raw or json.dumps(
        {
            "type": "han.mail.intake-record",
            "schema": 1,
            "handle": handle,
            "keyed_digest": keyed,
            "from_address": from_address,
            "receipt": {"receipt_id": receipt_id},
            "authority_signature": "hmac-sha256:deadbeef",
        }
    )
    path = root / f"{keyed}.json"
    path.write_text(payload)
    return path


def request(handle=HANDLE, from_address=FROM, aligned=True, confirmed_at=None):
    return chanc.WithdrawalRequest(
        cited_handle=handle,
        from_address=from_address,
        transport_aligned=aligned,
        confirmed_at=confirmed_at,
    )


@pytest.fixture
def records(tmp_path):
    return tmp_path / "intake"


# --- the resolver --------------------------------------------------------------------------------
def test_resolve_intake_finds_the_record_by_handle(records):
    write_record(records)
    resolution = chanc_withdrawal.resolve_intake(HANDLE, records_root=records)
    assert resolution.indeterminate is False
    record = resolution.record
    assert isinstance(record, chanc.IntakeRecord)
    assert record.handle == HANDLE
    assert record.from_address == FROM
    assert record.receipt_id == RECEIPT_ID
    # The evidence ref is the SAME id the §4 emitter used, not a second scheme.
    from shared import chanc_evidence

    assert record.intake_event_id == chanc_evidence.intake_event_id(keyed_digest=KEYED)


def test_resolve_intake_returns_nothing_for_a_malformed_or_unknown_handle(records):
    write_record(records)
    assert chanc_withdrawal.resolve_intake("nothex", records_root=records).record is None
    assert chanc_withdrawal.resolve_intake("A" * 64, records_root=records).record is None
    assert chanc_withdrawal.resolve_intake("b" * 64, records_root=records).record is None


def test_a_malformed_handle_never_consults_the_store(records):
    """A syntactically invalid handle is refused before any read, not scanned-and-not-found.

    The store here is corrupt, which would make any real scan indeterminate. A malformed handle must
    still come back as a clean "nothing", proving the store was never touched.
    """
    write_record(records, raw="{not json")
    resolution = chanc_withdrawal.resolve_intake("nothex", records_root=records)
    assert resolution.record is None
    assert resolution.indeterminate is False


def test_resolve_intake_flags_a_matched_but_unreadable_record(records):
    """A store fault must NOT be indistinguishable from 'no such handle'.

    An unparseable record cannot be attributed to a handle at all, so the resolver cannot prove the
    cited handle does NOT resolve to it. The answer is therefore indeterminate, never "no record".
    """
    write_record(records, raw="{not json")
    resolution = chanc_withdrawal.resolve_intake(HANDLE, records_root=records)
    assert resolution.record is None
    assert resolution.indeterminate is True


def test_resolve_intake_flags_a_contradictory_store(records):
    """Two records claiming the same handle is a contradictory store: indeterminate, not a guess."""
    write_record(records)
    write_record(records, keyed=hashlib.sha256(b"other").hexdigest())
    resolution = chanc_withdrawal.resolve_intake(HANDLE, records_root=records)
    assert resolution.record is None
    assert resolution.indeterminate is True


def test_resolve_intake_ignores_files_that_do_not_match(records):
    write_record(records, handle="c" * 64)
    assert chanc_withdrawal.resolve_intake(HANDLE, records_root=records).record is None


# --- the classifier + responder ------------------------------------------------------------------
def test_unknown_handle_gets_one_constant_shape_reply(records):
    write_record(records)
    first, _ = chanc_withdrawal.classify_reply(
        request(handle="b" * 64), records_root=records, now=NOW
    )
    second, _ = chanc_withdrawal.classify_reply(
        request(handle="c" * 64), records_root=records, now=NOW
    )
    assert first.code == chanc.NO_RECORD and second.code == chanc.NO_RECORD
    # Byte-identical to the module's one constant shape, whatever was cited: the reply cannot be
    # used to probe which handles exist.
    expected = (chanc_withdrawal.NO_RECORD_SUBJECT, chanc_withdrawal.NO_RECORD_BODY)
    assert chanc_withdrawal.format_disposition_reply(first) == expected
    assert chanc_withdrawal.format_disposition_reply(second) == expected


def test_a_store_fault_is_unresolved_never_no_record(records):
    write_record(records, raw="{not json")
    disposition, record = chanc_withdrawal.classify_reply(request(), records_root=records, now=NOW)
    assert record is None
    assert disposition.code == chanc.UNRESOLVED
    assert disposition.code != chanc.NO_RECORD


def test_spoofed_address_is_pending_never_yes(records):
    write_record(records)
    disposition, _ = chanc_withdrawal.classify_reply(
        request(from_address="someone-else@example.invalid"), records_root=records, now=NOW
    )
    assert disposition.code == chanc.PENDING


def test_corroborated_withdrawal_needs_confirmation_then_the_grace_window(records):
    write_record(records)
    unresolved, _ = chanc_withdrawal.classify_reply(request(), records_root=records, now=NOW)
    assert unresolved.code == chanc.PENDING  # no confirmation yet

    inside, _ = chanc_withdrawal.classify_reply(
        request(confirmed_at=NOW - timedelta(days=1)), records_root=records, now=NOW
    )
    assert inside.code == chanc.PENDING  # confirmed, still inside the grace window

    elapsed, _ = chanc_withdrawal.classify_reply(
        request(confirmed_at=NOW - timedelta(days=8)), records_root=records, now=NOW
    )
    assert elapsed.code == chanc.YES  # confirmed and past the 7-day grace


def test_no_record_is_rate_limited_when_the_limiter_says_so(records):
    write_record(records)
    disposition, _ = chanc_withdrawal.classify_reply(
        request(handle="b" * 64), records_root=records, now=NOW, no_record_allowed=False
    )
    assert disposition.code == chanc.NO_RECORD
    assert disposition.rate_limited is True  # the responder throttles it


# --- the reply itself ----------------------------------------------------------------------------
def test_reply_never_claims_beyond_the_ceiling_and_carries_no_submitter_content(records):
    write_record(records)
    disposition, _ = chanc_withdrawal.classify_reply(request(), records_root=records, now=NOW)
    subject, body = chanc_withdrawal.format_disposition_reply(disposition)
    lowered = (subject + "\n" + body).lower()
    for forbidden in ("immutable", "tamper-proof", "tamper proof", "anchored", "guarantee"):
        assert forbidden not in lowered
    assert (
        chanc_withdrawal.REPLY_CLAIM_CEILING in body
    )  # the ceiling is stated, not just not-exceeded
    # No submitter content, and not even the handle they cited (the receipt id is theirs to hold).
    assert HANDLE not in subject + body
    assert FROM not in subject + body
    assert RECEIPT_ID in body  # the evidence ref the sender can check


def test_the_unresolved_reply_carries_no_submitter_content_either(records):
    """The store-fault answer is not an exception: no handle, and the ceiling is still stated."""
    write_record(records, raw="{not json")
    disposition, _ = chanc_withdrawal.classify_reply(request(), records_root=records, now=NOW)
    assert disposition.code == chanc.UNRESOLVED
    subject, body = chanc_withdrawal.format_disposition_reply(disposition)
    assert HANDLE not in subject + body
    assert FROM not in subject + body
    assert chanc_withdrawal.REPLY_CLAIM_CEILING in body  # the exit predicate requires the ceiling
    assert "reply to this message" in body  # and a next action when no record can be attributed


def test_the_contradictory_store_reply_states_the_senders_own_receipt_id(records):
    """The exit predicate requires the store-fault answer to name the sender's own receipt id.

    A contradictory store still holds records for the cited handle, so the answer names them; only an
    unattributable record leaves no receipt id in existence to cite.
    """
    second_receipt = "20261005T070000Z-bbbbbbbbbbbbbbbb"
    write_record(records)
    write_record(records, keyed=hashlib.sha256(b"other").hexdigest(), receipt_id=second_receipt)
    disposition, _ = chanc_withdrawal.classify_reply(request(), records_root=records, now=NOW)
    assert disposition.code == chanc.UNRESOLVED
    subject, body = chanc_withdrawal.format_disposition_reply(disposition)
    assert RECEIPT_ID in body  # the sender's own receipt id IS stated
    assert second_receipt in body
    assert chanc_withdrawal.REPLY_CLAIM_CEILING in body
    assert HANDLE not in subject + body and FROM not in subject + body
