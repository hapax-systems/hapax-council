"""G12 — crow-chat-origin attestation substrate (the positive capability).

The negative-constraint half of "outside-Reins dispatch is operationally
impossible except via signed breakglass" (G12; cc-task-reins-g12-parallel-
dispatch-retirement-20260705). A dispatch may transit any of the 4 parallel
paths ONLY if the caller presents:

  (P) a signed crow-chat-origin attestation — a positive capability proving the
      dispatch originated at the crow-chat witnessed apply-seam and was approved
      there; OR
  (N) a signed ``EscapeGrant`` scoped to ``PARALLEL_DISPATCH_RETIREMENT_GATE``.

This module ships (P) + the unifying predicate ``attestation_or_breakglass_allows``.
(N) reuses the proven EscapeGrant substrate verbatim (``coord_capabilities.py``);
this module IMPORTS its HMAC core and ``EscapeGrant`` — no reimplementation
(audit F: re-use the linear-token discipline).

Same discipline as EscapeGrant: HMAC-signed over a canonical payload (any
tampered field fails verification), pure file-read + signature/expiry/binding
check (never an RPC), daemon-independent (INV-4). Degrades CLOSED on missing
substrate (mirrors ``read_grant_file``).
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from .coord_capabilities import (
    _sign,
    _verify_sig,
    read_grant_file,
    verify_escape_grant,
)

#: The gate name every G12 site checks. Lives here (the substrate SSOT).
PARALLEL_DISPATCH_RETIREMENT_GATE = "parallel-dispatch-retirement"

#: The attestation covers the dispatch MOMENT, not a long-lived session — the
#: lane's claim lease is the long-lived surface. (G12 spec Q4: TTL-bounded, 600s.)
ATTESTATION_DEFAULT_TTL_S = 600.0

#: Default attestation dir (sibling of the EscapeGrant grants dir).
DEFAULT_ATTESTATION_DIR = Path.home() / ".cache" / "hapax" / "coord" / "attestations"

#: Default EscapeGrant dir (reused — the breakglass half scans here).
DEFAULT_GRANT_DIR = Path.home() / ".cache" / "hapax" / "coord" / "grants"


@dataclass(frozen=True)
class CrowChatOriginAttestation:
    """A signed positive capability: a dispatch originated at the crow-chat
    apply-seam and was approved there. Bound to ``(task_id, lane)``, TTL-bounded.

    Structurally symmetric to ``EscapeGrant`` (the negative escape) so the
    substrate is one coherent capability pair. Minted BY THE CROW-CHAT APPLY-SEAM
    at ``approve_with_changes`` — Reins mints nothing; it carries the operator's
    approval (the never-mint invariant, unchanged).
    """

    attestation_id: str
    origin_surface: str  # literal "crow_chat"
    message_id: str  # binds to the dispatcher's mq_message_id / the durable-MQ row
    task_id: str
    lane: str
    authority_packet_ref: str  # the spine/methodology authority packet this discharges
    operator_attestation_ref: (
        str  # loopback/operator attestation reference (NOT a new authority grant)
    )
    idempotency_key: str
    issued_at: float
    expires_at: float
    signing_key_id: str  # opaque key id only; no key material in the artifact
    signature: str

    def _signing_payload(self) -> dict[str, object]:
        return {
            "kind": "crow_chat_origin_attestation",
            "attestation_id": self.attestation_id,
            "origin_surface": self.origin_surface,
            "message_id": self.message_id,
            "task_id": self.task_id,
            "lane": self.lane,
            "authority_packet_ref": self.authority_packet_ref,
            "operator_attestation_ref": self.operator_attestation_ref,
            "idempotency_key": self.idempotency_key,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signing_key_id": self.signing_key_id,
        }

    def is_expired(self, now: float) -> bool:
        return now > self.expires_at


def mint_origin_attestation(
    *,
    message_id: str,
    task_id: str,
    lane: str,
    authority_packet_ref: str,
    operator_attestation_ref: str,
    idempotency_key: str,
    key: bytes,
    now: float,
    signing_key_id: str = "default",
    ttl_s: float = ATTESTATION_DEFAULT_TTL_S,
) -> CrowChatOriginAttestation:
    """Mint a signed crow-chat-origin attestation. Caller mints ONLY at the
    crow-chat apply-seam ``approve_with_changes`` (never-mint invariant: Reins
    presents, never mints).
    """
    fields = {
        "attestation_id": secrets.token_hex(16),
        "origin_surface": "crow_chat",
        "message_id": message_id,
        "task_id": task_id,
        "lane": lane,
        "authority_packet_ref": authority_packet_ref,
        "operator_attestation_ref": operator_attestation_ref,
        "idempotency_key": idempotency_key,
        "issued_at": now,
        "expires_at": now + ttl_s,
        "signing_key_id": signing_key_id,
    }
    payload = {"kind": "crow_chat_origin_attestation", **fields}
    return CrowChatOriginAttestation(signature=_sign(payload, key), **fields)


def verify_origin_attestation(
    att: CrowChatOriginAttestation | None,
    *,
    key: bytes,
    now: float,
    task_id: str,
    lane: str,
) -> bool:
    """True iff the signature matches, it is unexpired, ``origin_surface`` is
    ``crow_chat``, AND it is bound to ``(task_id, lane)``. Pure (no RPC); never
    raises. An absent/empty ``key`` fails closed (never HMAC under ``b""``)."""
    if att is None:
        return False
    if not key:  # absent/empty key must fail closed, never HMAC under b"".
        return False
    if not _verify_sig(att._signing_payload(), att.signature, key):
        return False
    if att.is_expired(now):
        return False
    if att.origin_surface != "crow_chat":
        return False
    return att.task_id == task_id and att.lane == lane


def serialize_attestation(att: CrowChatOriginAttestation) -> str:
    data = dict(att._signing_payload())
    data["signature"] = att.signature
    return json.dumps(data)


def write_attestation_file(att: CrowChatOriginAttestation, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialize_attestation(att), encoding="utf-8")


def read_attestation_file(path: str | Path) -> CrowChatOriginAttestation | None:
    """Parse a serialized attestation FILE. Never raises; returns None on error."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("kind") != "crow_chat_origin_attestation":
            return None
        return CrowChatOriginAttestation(
            attestation_id=str(data["attestation_id"]),
            origin_surface=str(data["origin_surface"]),
            message_id=str(data["message_id"]),
            task_id=str(data["task_id"]),
            lane=str(data["lane"]),
            authority_packet_ref=str(data["authority_packet_ref"]),
            operator_attestation_ref=str(data["operator_attestation_ref"]),
            idempotency_key=str(data["idempotency_key"]),
            issued_at=float(data["issued_at"]),
            expires_at=float(data["expires_at"]),
            signing_key_id=str(data.get("signing_key_id", "default")),
            signature=str(data["signature"]),
        )
    except Exception:  # noqa: BLE001 — malformed/missing input must never raise.
        return None


def attestation_or_breakglass_allows(
    gate: str,
    task_id: str,
    lane: str,
    *,
    key: bytes,
    now: float,
    attestation_dir: str | Path = DEFAULT_ATTESTATION_DIR,
    grant_dir: str | Path = DEFAULT_GRANT_DIR,
) -> bool:
    """The single predicate every G12 site calls. True iff a valid crow-chat-origin
    attestation bound to ``(task_id, lane)`` OR a valid ``EscapeGrant`` covering
    ``gate`` is present.

    Degrades CLOSED: a missing substrate (no dirs, no files, empty key) → False
    (mirrors ``escape_grant_allows`` / ``read_grant_file``). Scans freshest-first
    (newest mtime wins, mirroring the EscapeGrant scan). This predicate is PURE;
    the call site ledgers the honor (``origin_attestation_honored`` /
    ``escape_grant_honored``) — the substrate never writes a ledger line itself.
    """
    if not key:
        return False
    att_dir = Path(attestation_dir)
    if att_dir.is_dir():
        for path in sorted(
            att_dir.glob("*.attestation"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            att = read_attestation_file(path)
            if verify_origin_attestation(att, key=key, now=now, task_id=task_id, lane=lane):
                return True
    g_dir = Path(grant_dir)
    if g_dir.is_dir():
        for path in sorted(g_dir.glob("*.grant"), key=lambda p: p.stat().st_mtime, reverse=True):
            grant = read_grant_file(path)
            if verify_escape_grant(grant, key=key, now=now, gate=gate):
                return True
    return False
