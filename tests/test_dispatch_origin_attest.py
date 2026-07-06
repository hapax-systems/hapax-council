"""Tests for the G12 crow-chat-origin attestation substrate.

Mirrors the G12 spec test plan (cc-task-reins-g12-parallel-dispatch-retirement-20260705):
refuses without attestation/breakglass; accepts with a valid attestation bound to
(task_id, lane); refuses on tampered/expired/wrong-task_id/wrong-lane; accepts
with a breakglass covering the gate; refuses with a breakglass scoped to a
different gate; degrades CLOSED on missing substrate.
"""

from __future__ import annotations

import json

from shared.governance.coord_capabilities import mint_escape_grant, write_grant_file
from shared.governance.dispatch_origin_attest import (
    ATTESTATION_DEFAULT_TTL_S,
    PARALLEL_DISPATCH_RETIREMENT_GATE,
    attestation_or_breakglass_allows,
    mint_origin_attestation,
    read_attestation_file,
    serialize_attestation,
    verify_origin_attestation,
    write_attestation_file,
)

KEY = b"test-signing-key-0123456789"
NOW = 1_700_000_000.0
TASK = "cc-task-example-20260705"
LANE = "cx-blue"
OTHER_TASK = "cc-task-other-20260705"
OTHER_LANE = "cx-green"
OTHER_GATE = "some-other-gate"


def _mint(**overrides):
    base = dict(
        message_id="msg-1",
        task_id=TASK,
        lane=LANE,
        authority_packet_ref="auth-packet-1",
        operator_attestation_ref="op-attest-1",
        idempotency_key="idem-1",
        key=KEY,
        now=NOW,
    )
    base.update(overrides)
    return mint_origin_attestation(**base)


def _write_att(att, tmp_path):
    d = tmp_path / "att"
    d.mkdir()
    write_attestation_file(att, d / f"{att.attestation_id}.attestation")
    return d


def _write_grant(grant, tmp_path):
    d = tmp_path / "grants"
    d.mkdir()
    write_grant_file(grant, d / f"{grant.grant_id}.grant")
    return d


# --- round-trip + structure --------------------------------------------------


def test_attestation_roundtrips_through_file(tmp_path):
    att = _mint()
    p = tmp_path / "a.attestation"
    write_attestation_file(att, p)
    parsed = read_attestation_file(p)
    assert parsed is not None
    assert parsed.attestation_id == att.attestation_id
    assert verify_origin_attestation(parsed, key=KEY, now=NOW, task_id=TASK, lane=LANE)


def test_origin_surface_is_crow_chat():
    assert _mint().origin_surface == "crow_chat"


def test_default_ttl_is_600s():
    att = _mint()
    assert att.expires_at - att.issued_at == ATTESTATION_DEFAULT_TTL_S


# --- verify refusals ---------------------------------------------------------


def test_verify_none_is_false():
    assert not verify_origin_attestation(None, key=KEY, now=NOW, task_id=TASK, lane=LANE)


def test_verify_empty_key_fails_closed():
    assert not verify_origin_attestation(_mint(), key=b"", now=NOW, task_id=TASK, lane=LANE)


def test_verify_wrong_key_is_false():
    assert not verify_origin_attestation(
        _mint(), key=b"different-key", now=NOW, task_id=TASK, lane=LANE
    )


def test_verify_tampered_field_is_false(tmp_path):
    att = _mint()
    data = json.loads(serialize_attestation(att))
    data["task_id"] = OTHER_TASK  # change WITHOUT re-signing
    p = tmp_path / "tampered.attestation"
    p.write_text(json.dumps(data))
    parsed = read_attestation_file(p)
    assert parsed is not None
    assert not verify_origin_attestation(parsed, key=KEY, now=NOW, task_id=OTHER_TASK, lane=LANE)


def test_verify_expired_is_false():
    att = _mint(ttl_s=10)
    assert not verify_origin_attestation(att, key=KEY, now=NOW + 100, task_id=TASK, lane=LANE)


def test_verify_wrong_task_id_is_false():
    assert not verify_origin_attestation(_mint(), key=KEY, now=NOW, task_id=OTHER_TASK, lane=LANE)


def test_verify_wrong_lane_is_false():
    assert not verify_origin_attestation(_mint(), key=KEY, now=NOW, task_id=TASK, lane=OTHER_LANE)


def test_read_malformed_returns_none(tmp_path):
    p = tmp_path / "bad.attestation"
    p.write_text("not json")
    assert read_attestation_file(p) is None


def test_read_wrong_kind_returns_none(tmp_path):
    p = tmp_path / "wrong.attestation"
    p.write_text(json.dumps({"kind": "escape", "grant_id": "x"}))
    assert read_attestation_file(p) is None


# --- the unifying predicate (the G12 gate) -----------------------------------


def test_predicate_refuses_with_no_substrate(tmp_path):
    assert not attestation_or_breakglass_allows(
        PARALLEL_DISPATCH_RETIREMENT_GATE,
        TASK,
        LANE,
        key=KEY,
        now=NOW,
        attestation_dir=tmp_path / "att",
        grant_dir=tmp_path / "grants",
    )


def test_predicate_accepts_valid_attestation(tmp_path):
    att_dir = _write_att(_mint(), tmp_path)
    assert attestation_or_breakglass_allows(
        PARALLEL_DISPATCH_RETIREMENT_GATE,
        TASK,
        LANE,
        key=KEY,
        now=NOW,
        attestation_dir=att_dir,
        grant_dir=tmp_path / "grants",
    )


def test_predicate_refuses_attestation_bound_to_other_task(tmp_path):
    att_dir = _write_att(_mint(), tmp_path)
    assert not attestation_or_breakglass_allows(
        PARALLEL_DISPATCH_RETIREMENT_GATE,
        OTHER_TASK,
        LANE,
        key=KEY,
        now=NOW,
        attestation_dir=att_dir,
        grant_dir=tmp_path / "grants",
    )


def test_predicate_refuses_attestation_bound_to_other_lane(tmp_path):
    att_dir = _write_att(_mint(), tmp_path)
    assert not attestation_or_breakglass_allows(
        PARALLEL_DISPATCH_RETIREMENT_GATE,
        TASK,
        OTHER_LANE,
        key=KEY,
        now=NOW,
        attestation_dir=att_dir,
        grant_dir=tmp_path / "grants",
    )


def test_predicate_accepts_breakglass_covering_gate(tmp_path):
    grant_dir = _write_grant(
        mint_escape_grant(
            grantor="operator",
            scope=PARALLEL_DISPATCH_RETIREMENT_GATE,
            reason="incident",
            ttl_s=3600,
            key=KEY,
            now=NOW,
        ),
        tmp_path,
    )
    assert attestation_or_breakglass_allows(
        PARALLEL_DISPATCH_RETIREMENT_GATE,
        TASK,
        LANE,
        key=KEY,
        now=NOW,
        attestation_dir=tmp_path / "att",
        grant_dir=grant_dir,
    )


def test_predicate_refuses_breakglass_scoped_to_other_gate(tmp_path):
    grant_dir = _write_grant(
        mint_escape_grant(
            grantor="operator", scope=OTHER_GATE, reason="incident", ttl_s=3600, key=KEY, now=NOW
        ),
        tmp_path,
    )
    assert not attestation_or_breakglass_allows(
        PARALLEL_DISPATCH_RETIREMENT_GATE,
        TASK,
        LANE,
        key=KEY,
        now=NOW,
        attestation_dir=tmp_path / "att",
        grant_dir=grant_dir,
    )


def test_predicate_wildcard_breakglass_covers_any_gate(tmp_path):
    grant_dir = _write_grant(
        mint_escape_grant(
            grantor="operator", scope="*", reason="ops", ttl_s=3600, key=KEY, now=NOW
        ),
        tmp_path,
    )
    assert attestation_or_breakglass_allows(
        PARALLEL_DISPATCH_RETIREMENT_GATE,
        TASK,
        LANE,
        key=KEY,
        now=NOW,
        attestation_dir=tmp_path / "att",
        grant_dir=grant_dir,
    )


def test_predicate_empty_key_degrades_closed(tmp_path):
    att_dir = _write_att(_mint(), tmp_path)
    assert not attestation_or_breakglass_allows(
        PARALLEL_DISPATCH_RETIREMENT_GATE,
        TASK,
        LANE,
        key=b"",
        now=NOW,
        attestation_dir=att_dir,
        grant_dir=tmp_path / "grants",
    )


def test_predicate_both_present_allows(tmp_path):
    att_dir = _write_att(_mint(), tmp_path)
    grant_dir = _write_grant(
        mint_escape_grant(
            grantor="operator",
            scope=PARALLEL_DISPATCH_RETIREMENT_GATE,
            reason="x",
            ttl_s=3600,
            key=KEY,
            now=NOW,
        ),
        tmp_path,
    )
    assert attestation_or_breakglass_allows(
        PARALLEL_DISPATCH_RETIREMENT_GATE,
        TASK,
        LANE,
        key=KEY,
        now=NOW,
        attestation_dir=att_dir,
        grant_dir=grant_dir,
    )
