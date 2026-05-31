"""Tests for the coordination capability/grant substrate (Phase 4 slice 1).

Coordination reform Phase 4 §4.4 (NEW-2 — the daemon-independent escape, the
audit's central safety correction). Generalizes the constitutional ``GateToken``
pattern to two HMAC-signed capabilities:

- ``DispatchCapability`` — single-use ocap bound to (task_id, lane); replay is
  rejected by a consumption ledger.
- ``EscapeGrant`` — a signed FILE the bash shim reads directly (never an RPC), so
  a grant is picked up regardless of daemon liveness and the operator can
  hand-write one with the kernel down.

The unforgeability property: a record verifies iff its HMAC over the canonical
payload matches under the operator key — so any tampered field (widened scope,
re-bound lane) fails verification.
"""

import json
from dataclasses import replace

from shared.governance.coord_capabilities import (
    CapabilityConsumptionLedger,
    main,
    mint_dispatch_capability,
    mint_escape_grant,
    read_capability_file,
    read_grant_file,
    serialize_capability,
    serialize_grant,
    verify_dispatch_capability,
    verify_escape_grant,
    write_grant_file,
)

KEY = b"operator-secret-key-0123456789abcdef"
WRONG_KEY = b"attacker-key-0000000000000000000000"


# --- DispatchCapability -------------------------------------------------------


class TestDispatchCapability:
    def test_mint_and_verify_roundtrip(self):
        cap = mint_dispatch_capability(task_id="t1", lane="theta", ttl_s=600, key=KEY, now=1000.0)
        assert verify_dispatch_capability(cap, key=KEY, now=1100.0, task_id="t1", lane="theta")

    def test_tampered_binding_rejected(self):
        cap = mint_dispatch_capability(task_id="t1", lane="theta", ttl_s=600, key=KEY, now=1000.0)
        forged = replace(cap, lane="alpha")  # re-bind without re-signing
        assert not verify_dispatch_capability(
            forged, key=KEY, now=1100.0, task_id="t1", lane="alpha"
        )

    def test_wrong_key_rejected(self):
        cap = mint_dispatch_capability(task_id="t1", lane="theta", ttl_s=600, key=KEY, now=1000.0)
        assert not verify_dispatch_capability(
            cap, key=WRONG_KEY, now=1100.0, task_id="t1", lane="theta"
        )

    def test_expired_rejected(self):
        cap = mint_dispatch_capability(task_id="t1", lane="theta", ttl_s=600, key=KEY, now=1000.0)
        assert not verify_dispatch_capability(cap, key=KEY, now=2000.0, task_id="t1", lane="theta")

    def test_wrong_task_binding_rejected(self):
        cap = mint_dispatch_capability(task_id="t1", lane="theta", ttl_s=600, key=KEY, now=1000.0)
        assert not verify_dispatch_capability(cap, key=KEY, now=1100.0, task_id="t2", lane="theta")

    def test_serialize_read_roundtrip(self, tmp_path):
        cap = mint_dispatch_capability(task_id="t1", lane="theta", ttl_s=600, key=KEY, now=1000.0)
        path = tmp_path / "cap.json"
        path.write_text(serialize_capability(cap))
        loaded = read_capability_file(path)
        assert loaded is not None
        assert verify_dispatch_capability(loaded, key=KEY, now=1100.0, task_id="t1", lane="theta")


# --- consumption ledger (single-use) ------------------------------------------


class TestConsumptionLedger:
    def test_first_consume_ok_replay_rejected(self, tmp_path):
        led = CapabilityConsumptionLedger(tmp_path / "consumed.jsonl")
        assert led.consume("cap-1") is True
        assert led.consume("cap-1") is False  # replay rejected
        assert led.consume("cap-2") is True

    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "consumed.jsonl"
        assert CapabilityConsumptionLedger(path).consume("cap-1") is True
        assert CapabilityConsumptionLedger(path).consume("cap-1") is False

    def test_never_raises_on_bad_path(self):
        led = CapabilityConsumptionLedger("/this/does/not/exist/consumed.jsonl")
        assert led.consume("cap-x") in (True, False)


# --- EscapeGrant (NEW-2: daemon-independent, signed file) ---------------------


class TestEscapeGrant:
    def test_mint_serialize_file_read_verify_roundtrip(self, tmp_path):
        grant = mint_escape_grant(
            grantor="operator",
            scope="cc-task-gate",
            reason="incident",
            ttl_s=3600,
            key=KEY,
            now=1000.0,
        )
        path = tmp_path / "grant.json"
        write_grant_file(grant, path)
        loaded = read_grant_file(path)
        assert loaded is not None
        assert verify_escape_grant(loaded, key=KEY, now=1500.0, gate="cc-task-gate")

    def test_hand_written_grant_accepted(self, tmp_path):
        # With the kernel down the operator hand-writes the grant file; a valid
        # signature is all the shim needs (no RPC).
        grant = mint_escape_grant(
            grantor="operator", scope="*", reason="kernel down", ttl_s=3600, key=KEY, now=1000.0
        )
        path = tmp_path / "grant.json"
        path.write_text(serialize_grant(grant))  # hand-written
        loaded = read_grant_file(path)
        assert verify_escape_grant(loaded, key=KEY, now=1500.0, gate="any-gate")  # "*" covers all

    def test_tampered_scope_rejected(self):
        grant = mint_escape_grant(
            grantor="operator", scope="cc-task-gate", reason="x", ttl_s=3600, key=KEY, now=1000.0
        )
        forged = replace(grant, scope="*")  # widen scope without re-signing
        assert not verify_escape_grant(forged, key=KEY, now=1500.0, gate="other-gate")

    def test_expired_rejected(self):
        grant = mint_escape_grant(
            grantor="operator", scope="cc-task-gate", reason="x", ttl_s=60, key=KEY, now=1000.0
        )
        assert not verify_escape_grant(grant, key=KEY, now=2000.0, gate="cc-task-gate")

    def test_wrong_scope_rejected(self):
        grant = mint_escape_grant(
            grantor="operator", scope="cc-task-gate", reason="x", ttl_s=3600, key=KEY, now=1000.0
        )
        assert not verify_escape_grant(grant, key=KEY, now=1500.0, gate="pr-release-gate")

    def test_wrong_key_rejected(self):
        grant = mint_escape_grant(
            grantor="operator", scope="*", reason="x", ttl_s=3600, key=KEY, now=1000.0
        )
        assert not verify_escape_grant(grant, key=WRONG_KEY, now=1500.0, gate="x")

    def test_read_missing_file_returns_none(self, tmp_path):
        assert read_grant_file(tmp_path / "nope.json") is None

    def test_read_malformed_file_returns_none(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json")
        assert read_grant_file(path) is None

    def test_verify_none_is_false(self):
        assert verify_escape_grant(None, key=KEY, now=1.0, gate="x") is False


# --- CLI (the operator's daemon-independent grant tool) -----------------------


class TestCli:
    def _key_file(self, tmp_path):
        path = tmp_path / "coord.key"
        path.write_bytes(KEY)
        return path

    def test_mint_grant_then_verify_grant(self, tmp_path, capsys):
        key_file = self._key_file(tmp_path)
        out = tmp_path / "grant.json"
        rc = main(
            [
                "mint-grant",
                "--scope",
                "cc-task-gate",
                "--reason",
                "incident",
                "--ttl",
                "3600",
                "--key-file",
                str(key_file),
                "--out",
                str(out),
            ]
        )
        assert rc == 0
        capsys.readouterr()
        rc2 = main(
            [
                "verify-grant",
                "--file",
                str(out),
                "--gate",
                "cc-task-gate",
                "--key-file",
                str(key_file),
            ]
        )
        result = json.loads(capsys.readouterr().out)
        assert rc2 == 0
        assert result["valid"] is True

    def test_verify_grant_wrong_gate_exits_nonzero(self, tmp_path, capsys):
        key_file = self._key_file(tmp_path)
        out = tmp_path / "grant.json"
        main(
            [
                "mint-grant",
                "--scope",
                "cc-task-gate",
                "--reason",
                "x",
                "--ttl",
                "3600",
                "--key-file",
                str(key_file),
                "--out",
                str(out),
            ]
        )
        capsys.readouterr()
        rc = main(
            [
                "verify-grant",
                "--file",
                str(out),
                "--gate",
                "pr-release-gate",
                "--key-file",
                str(key_file),
            ]
        )
        assert rc != 0

    def test_mint_dispatch_then_verify_with_consume(self, tmp_path, capsys):
        key_file = self._key_file(tmp_path)
        out = tmp_path / "cap.json"
        ledger = tmp_path / "consumed.jsonl"
        main(
            [
                "mint-dispatch",
                "--task",
                "t1",
                "--lane",
                "theta",
                "--ttl",
                "600",
                "--key-file",
                str(key_file),
                "--out",
                str(out),
            ]
        )
        capsys.readouterr()
        rc = main(
            [
                "verify-dispatch",
                "--file",
                str(out),
                "--task",
                "t1",
                "--lane",
                "theta",
                "--key-file",
                str(key_file),
                "--consume",
                "--ledger",
                str(ledger),
            ]
        )
        assert rc == 0
        capsys.readouterr()
        # second consume of the same capability is a replay → rejected
        rc2 = main(
            [
                "verify-dispatch",
                "--file",
                str(out),
                "--task",
                "t1",
                "--lane",
                "theta",
                "--key-file",
                str(key_file),
                "--consume",
                "--ledger",
                str(ledger),
            ]
        )
        assert rc2 != 0
