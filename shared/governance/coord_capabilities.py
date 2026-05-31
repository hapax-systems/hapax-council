"""Coordination capability/grant substrate (reform Phase 4 §4.4, NEW-2).

Generalizes the constitutional ``GateToken`` pattern (``gate_token.py`` —
unforgeable, frozen, nonce-bearing) to the two coordination capabilities the
reform needs, reusing the same linear-token discipline rather than reimplementing
(audit F).  Both are HMAC-signed over a canonical payload, so any tampered field
fails verification.

``DispatchCapability``
    A single-use object-capability bound to (task_id, lane), minted only when
    policy passes, consumed once.  Replaces the 10-min-stale ``subject==task_id``
    MQ query and kills confused-deputy ambiguity (FM-9).

``EscapeGrant`` — THE daemon-independent escape (NEW-2, the audit's central
    safety correction).  A signed FILE the bash shim reads directly: verification
    is a pure file read + signature/expiry/scope check, **never an RPC**.  So a
    grant is picked up on the next tool call regardless of daemon liveness, and
    the operator (root capability) can hand-write the grant file when the kernel
    is down — escape never depends on the process it governs (INV-4).

This slice ships ONLY the substrate (pure, dependency-light, its own tests).  The
shim/floor wiring, the Lisp ``coord.grant.mint`` verb, the single daemon-owned
event log, and the 17-ledger removal are subsequent Phase-4 sub-slices.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Default single-use consumption ledger (cache path; the durable daemon-owned
#: log replaces this in a later Phase-4 sub-slice).
DEFAULT_CONSUMPTION_LEDGER = Path.home() / ".cache" / "hapax" / "coord-capability-consumption.jsonl"


# --- HMAC core ----------------------------------------------------------------


def _sign(payload: Mapping[str, object], key: bytes) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, blob, hashlib.sha256).hexdigest()


def _verify_sig(payload: Mapping[str, object], signature: str, key: bytes) -> bool:
    try:
        return hmac.compare_digest(_sign(payload, key), signature)
    except Exception:  # noqa: BLE001 — verification must never raise; treat any error as invalid.
        return False


# --- DispatchCapability -------------------------------------------------------


@dataclass(frozen=True)
class DispatchCapability:
    """Single-use ocap bound to (task_id, lane). Unforgeable (HMAC), expiring."""

    capability_id: str
    task_id: str
    lane: str
    issued_at: float
    expires_at: float
    signature: str

    def _signing_payload(self) -> dict[str, object]:
        return {
            "kind": "dispatch",
            "capability_id": self.capability_id,
            "task_id": self.task_id,
            "lane": self.lane,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def is_expired(self, now: float) -> bool:
        return now > self.expires_at


def mint_dispatch_capability(
    *, task_id: str, lane: str, ttl_s: float, key: bytes, now: float
) -> DispatchCapability:
    """Mint a signed dispatch capability. Caller mints ONLY on a policy-pass."""
    fields = {
        "capability_id": secrets.token_hex(16),
        "task_id": task_id,
        "lane": lane,
        "issued_at": now,
        "expires_at": now + ttl_s,
    }
    payload = {"kind": "dispatch", **fields}
    return DispatchCapability(signature=_sign(payload, key), **fields)


def verify_dispatch_capability(
    cap: DispatchCapability | None, *, key: bytes, now: float, task_id: str, lane: str
) -> bool:
    """True iff the signature matches, it is unexpired, and bound to (task_id, lane)."""
    if cap is None:
        return False
    if not _verify_sig(cap._signing_payload(), cap.signature, key):
        return False
    if cap.is_expired(now):
        return False
    return cap.task_id == task_id and cap.lane == lane


def serialize_capability(cap: DispatchCapability) -> str:
    return json.dumps(
        {
            "kind": "dispatch",
            "capability_id": cap.capability_id,
            "task_id": cap.task_id,
            "lane": cap.lane,
            "issued_at": cap.issued_at,
            "expires_at": cap.expires_at,
            "signature": cap.signature,
        }
    )


def read_capability_file(path: str | Path) -> DispatchCapability | None:
    """Parse a serialized dispatch capability. Never raises; returns None on error."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("kind") != "dispatch":
            return None
        return DispatchCapability(
            capability_id=str(data["capability_id"]),
            task_id=str(data["task_id"]),
            lane=str(data["lane"]),
            issued_at=float(data["issued_at"]),
            expires_at=float(data["expires_at"]),
            signature=str(data["signature"]),
        )
    except Exception:  # noqa: BLE001 — malformed/missing input must never raise.
        return None


class CapabilityConsumptionLedger:
    """File-backed single-use ledger. ``consume`` returns False on replay.

    Best-effort: on an IO error it returns True (availability) — the durable
    single-use enforcement is the daemon-owned log in a later sub-slice; this
    file ledger is the standalone fallback.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def _consumed_ids(self) -> set[str]:
        ids: set[str] = set()
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return ids
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(str(json.loads(line)["capability_id"]))
            except Exception:  # noqa: BLE001 — skip malformed ledger lines.
                continue
        return ids

    def consume(self, capability_id: str) -> bool:
        try:
            if capability_id in self._consumed_ids():
                return False
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "capability_id": capability_id,
                            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        }
                    )
                    + "\n"
                )
            return True
        except Exception:  # noqa: BLE001 — never block a dispatch on ledger IO failure.
            return True


# --- EscapeGrant (NEW-2: daemon-independent, signed file) ---------------------


@dataclass(frozen=True)
class EscapeGrant:
    """A signed escape grant the bash shim reads directly (no RPC). Scoped + expiring."""

    grant_id: str
    grantor: str
    scope: str  # a gate name, or "*" for all gates
    reason: str
    issued_at: float
    expires_at: float
    signature: str

    def _signing_payload(self) -> dict[str, object]:
        return {
            "kind": "escape",
            "grant_id": self.grant_id,
            "grantor": self.grantor,
            "scope": self.scope,
            "reason": self.reason,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def is_expired(self, now: float) -> bool:
        return now > self.expires_at

    def covers(self, gate: str) -> bool:
        return self.scope == "*" or self.scope == gate


def mint_escape_grant(
    *, grantor: str, scope: str, reason: str, ttl_s: float, key: bytes, now: float
) -> EscapeGrant:
    """Mint a signed escape grant. The operator (root) is the only legitimate grantor."""
    fields = {
        "grant_id": secrets.token_hex(16),
        "grantor": grantor,
        "scope": scope,
        "reason": reason,
        "issued_at": now,
        "expires_at": now + ttl_s,
    }
    payload = {"kind": "escape", **fields}
    return EscapeGrant(signature=_sign(payload, key), **fields)


def serialize_grant(grant: EscapeGrant) -> str:
    return json.dumps(
        {
            "kind": "escape",
            "grant_id": grant.grant_id,
            "grantor": grant.grantor,
            "scope": grant.scope,
            "reason": grant.reason,
            "issued_at": grant.issued_at,
            "expires_at": grant.expires_at,
            "signature": grant.signature,
        }
    )


def write_grant_file(grant: EscapeGrant, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialize_grant(grant), encoding="utf-8")


def read_grant_file(path: str | Path) -> EscapeGrant | None:
    """Parse a serialized escape grant FILE. Never raises; returns None on error."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("kind") != "escape":
            return None
        return EscapeGrant(
            grant_id=str(data["grant_id"]),
            grantor=str(data["grantor"]),
            scope=str(data["scope"]),
            reason=str(data["reason"]),
            issued_at=float(data["issued_at"]),
            expires_at=float(data["expires_at"]),
            signature=str(data["signature"]),
        )
    except Exception:  # noqa: BLE001 — a malformed/missing grant must never raise.
        return None


def verify_escape_grant(
    grant: EscapeGrant | None, *, key: bytes, now: float, gate: str | None = None
) -> bool:
    """True iff the grant's signature matches, it is unexpired, and it covers ``gate``.

    Pure: signature + expiry + scope only — no network, no daemon. This is what
    makes the escape daemon-independent (NEW-2 / INV-4).
    """
    if grant is None:
        return False
    if not _verify_sig(grant._signing_payload(), grant.signature, key):
        return False
    if grant.is_expired(now):
        return False
    return gate is None or grant.covers(gate)


# --- Operator CLI (daemon-independent grant tool) -----------------------------


def _load_key_file(path: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError:
        return b""


def main(argv: list[str] | None = None) -> int:
    """Operator/kernel capability CLI.

    ``coord_capabilities mint-grant|verify-grant|mint-dispatch|verify-dispatch``.
    ``verify-*`` exit 0 (valid) / 1 (invalid) — the shim's interface. ``mint-*``
    write a signed file the shim/launcher reads. No daemon required.
    """
    parser = argparse.ArgumentParser(prog="coord_capabilities")
    sub = parser.add_subparsers(dest="cmd", required=True)

    mg = sub.add_parser("mint-grant")
    mg.add_argument("--scope", required=True)
    mg.add_argument("--reason", default="")
    mg.add_argument("--grantor", default="operator")
    mg.add_argument("--ttl", type=float, default=3600.0)
    mg.add_argument("--key-file", dest="key_file", required=True)
    mg.add_argument("--out", required=True)

    vg = sub.add_parser("verify-grant")
    vg.add_argument("--file", required=True)
    vg.add_argument("--gate", default=None)
    vg.add_argument("--key-file", dest="key_file", required=True)

    md = sub.add_parser("mint-dispatch")
    md.add_argument("--task", required=True)
    md.add_argument("--lane", required=True)
    md.add_argument("--ttl", type=float, default=600.0)
    md.add_argument("--key-file", dest="key_file", required=True)
    md.add_argument("--out", required=True)

    vd = sub.add_parser("verify-dispatch")
    vd.add_argument("--file", required=True)
    vd.add_argument("--task", required=True)
    vd.add_argument("--lane", required=True)
    vd.add_argument("--key-file", dest="key_file", required=True)
    vd.add_argument("--consume", action="store_true")
    vd.add_argument("--ledger", default=None)

    args = parser.parse_args(argv)
    now = time.time()
    key = _load_key_file(args.key_file)

    if args.cmd == "mint-grant":
        grant = mint_escape_grant(
            grantor=args.grantor,
            scope=args.scope,
            reason=args.reason,
            ttl_s=args.ttl,
            key=key,
            now=now,
        )
        write_grant_file(grant, args.out)
        print(grant.grant_id)
        return 0

    if args.cmd == "verify-grant":
        grant = read_grant_file(args.file)
        ok = verify_escape_grant(grant, key=key, now=now, gate=args.gate)
        print(json.dumps({"valid": ok, "grant_id": grant.grant_id if grant else None}))
        return 0 if ok else 1

    if args.cmd == "mint-dispatch":
        cap = mint_dispatch_capability(
            task_id=args.task, lane=args.lane, ttl_s=args.ttl, key=key, now=now
        )
        Path(args.out).write_text(serialize_capability(cap), encoding="utf-8")
        print(cap.capability_id)
        return 0

    if args.cmd == "verify-dispatch":
        cap = read_capability_file(args.file)
        ok = verify_dispatch_capability(cap, key=key, now=now, task_id=args.task, lane=args.lane)
        if ok and args.consume and cap is not None:
            ledger = CapabilityConsumptionLedger(args.ledger or DEFAULT_CONSUMPTION_LEDGER)
            if not ledger.consume(cap.capability_id):
                ok = False  # replay
        print(json.dumps({"valid": ok}))
        return 0 if ok else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
