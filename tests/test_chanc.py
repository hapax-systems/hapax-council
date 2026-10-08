"""CHANC core §9 test battery, red-first (c1-chanc-build1-20261004, SPEC §9).

Each test pins a §9 invariant of the withdrawal classifier / handle model. Synthetic digests and
addresses only — no personal content. (The §9 case "two inbound messages trigger at most one
receipt" is a property of receipt EMISSION in han_mail_pull, build-1 component 1, and is pinned in
that slice's tests, not here.)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shared import chanc

_KEY = b"keeper-key-under-test"
_DIGEST = "a" * 64  # a synthetic content digest (64 hex)
_OTHER_DIGEST = "b" * 64
_NOW = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)


def _record(**overrides) -> chanc.IntakeRecord:
    base = dict(
        handle=chanc.generate_handle(),
        from_address="sender@example.org",
        receipt_id="rcpt-001",
        intake_event_id="han.mail.intake:001",
    )
    base.update(overrides)
    return chanc.IntakeRecord(**base)


def _request(record: chanc.IntakeRecord | None = None, **overrides) -> chanc.WithdrawalRequest:
    base = dict(
        cited_handle=record.handle if record is not None else chanc.generate_handle(),
        from_address="sender@example.org",
        transport_aligned=True,
    )
    base.update(overrides)
    return chanc.WithdrawalRequest(**base)


# --- handle model (D4: RANDOM, not the content digest) + §4 keyed digest ----------------------


def test_handle_is_random_and_not_the_content_digest():
    h1, h2 = chanc.generate_handle(), chanc.generate_handle()
    assert chanc.is_valid_handle(h1) and len(h1) == 64
    assert h1 != h2, "handles must be random, not constant"
    assert h1 != _DIGEST, "the handle must not be derived from the message content (D4)"


def test_invalid_handles_are_rejected_syntactically():
    for bad in ("", "xyz", "A" * 64, "a" * 63, 1234, None):
        assert not chanc.is_valid_handle(bad)


def test_keyed_digest_hides_the_plain_hash_and_depends_on_the_key():
    keyed = chanc.keyed_digest(_DIGEST, key=_KEY)
    assert keyed != _DIGEST, "the event must carry a keyed digest, never the plain content hash"
    assert len(keyed) == 64
    assert chanc.keyed_digest(_DIGEST, key=b"other-key") != keyed, "keying must depend on the key"


def test_salted_commitment_binds_and_verifies():
    salt = b"per-record-salt"
    commitment = chanc.salted_commitment(_DIGEST, salt=salt, key=_KEY)
    assert commitment != _DIGEST
    assert chanc.verify_commitment(_DIGEST, commitment, salt=salt, key=_KEY)
    assert not chanc.verify_commitment(_OTHER_DIGEST, commitment, salt=salt, key=_KEY)
    assert not chanc.verify_commitment(_DIGEST, commitment, salt=b"wrong-salt", key=_KEY)


# --- §9 withdrawal classifier battery ---------------------------------------------------------


def test_unknown_handle_is_no_record():
    d = chanc.classify_withdrawal(_request(), None, now=_NOW)
    assert d.code == chanc.NO_RECORD


def test_syntactically_invalid_handle_is_no_record():
    d = chanc.classify_withdrawal(_request(cited_handle="not-a-handle"), _record(), now=_NOW)
    assert d.code == chanc.NO_RECORD


def test_replayed_withdrawal_is_no_record_constant_shape():
    rec = _record(withdrawn=True, bytes_present=False)
    d = chanc.classify_withdrawal(_request(rec), rec, now=_NOW)
    # An already-withdrawn handle resolves to no LIVE intake: the same constant reply as an
    # unknown handle, so a replay cannot tell a real past intake from a guess.
    assert d.code == chanc.NO_RECORD


def test_no_record_reply_is_rate_limited_when_the_limiter_says_so():
    allowed = chanc.classify_withdrawal(_request(), None, now=_NOW, no_record_allowed=True)
    throttled = chanc.classify_withdrawal(_request(), None, now=_NOW, no_record_allowed=False)
    assert allowed.code == throttled.code == chanc.NO_RECORD
    assert allowed.rate_limited is False and throttled.rate_limited is True


def test_published_with_permission_is_no_published():
    rec = _record(published_with_permission=True, permission_record="perm-handle-001")
    d = chanc.classify_withdrawal(_request(rec), rec, now=_NOW)
    assert d.code == chanc.NO_PUBLISHED
    assert "perm-handle-001" in d.evidence_refs


def test_published_with_permission_but_missing_record_is_no_pending():
    rec = _record(published_with_permission=True, permission_record=None)
    d = chanc.classify_withdrawal(_request(rec), rec, now=_NOW)
    assert d.code == chanc.NO_PENDING


def test_open_correction_is_retention_live():
    rec = _record(correction_ref="corr-2026-0003", correction_resolved=False)
    d = chanc.classify_withdrawal(_request(rec), rec, now=_NOW)
    assert d.code == chanc.RETENTION_LIVE
    assert "corr-2026-0003" in d.evidence_refs


def test_contradictory_store_state_is_unresolved():
    rec = _record(bytes_present=True, withdrawn=True)
    d = chanc.classify_withdrawal(_request(rec), rec, now=_NOW)
    assert d.code == chanc.UNRESOLVED


def test_spoofed_from_address_is_pending_on_corroboration_never_yes():
    rec = _record()
    d = chanc.classify_withdrawal(_request(rec, from_address="attacker@evil.test"), rec, now=_NOW)
    assert d.code == chanc.PENDING
    assert "corroboration" in d.reason, "must be held on corroboration, not merely on confirmation"


def test_replayed_handle_from_wrong_address_is_pending_on_corroboration():
    rec = _record()
    # correct handle, correct transport flag, but a different sending address → corroboration fails.
    req = _request(rec, from_address="elsewhere@example.net")
    d = chanc.classify_withdrawal(req, rec, now=_NOW)
    assert d.code == chanc.PENDING
    assert "corroboration" in d.reason


def test_unaligned_transport_is_pending_on_corroboration():
    rec = _record()
    d = chanc.classify_withdrawal(_request(rec, transport_aligned=False), rec, now=_NOW)
    assert d.code == chanc.PENDING
    assert "corroboration" in d.reason


def test_shared_mailbox_still_requires_confirmation_not_auto_yes():
    # Corroboration passes (recorded address + aligned) but a sending address alone never deletes:
    # the answer is pending on CONFIRMATION (not corroboration) until confirmation + grace, even
    # from the recorded (shared) mailbox.
    rec = _record()
    d = chanc.classify_withdrawal(_request(rec), rec, now=_NOW)
    assert d.code == chanc.PENDING
    assert "confirmation" in d.reason and "corroboration" not in d.reason


def test_confirmed_within_grace_is_pending_then_yes_after_grace():
    rec = _record()
    confirmed = _NOW
    within = chanc.classify_withdrawal(
        _request(rec, confirmed_at=confirmed), rec, now=confirmed + timedelta(days=6)
    )
    assert within.code == chanc.PENDING
    after = chanc.classify_withdrawal(
        _request(rec, confirmed_at=confirmed), rec, now=confirmed + timedelta(days=8)
    )
    assert after.code == chanc.YES
    assert after.evidence_refs == (rec.receipt_id, rec.intake_event_id)
