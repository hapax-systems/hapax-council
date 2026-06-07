"""Host-provenance type primitive — one vocabulary for host-scoped claims.

This module makes the 2026-06-06 WD_BLACK SN7100 host-context-drift failure a
construction-time error rather than a discipline the reviewer must remember.
A presence/absence claim cannot be built without naming its ``target_host`` and
supplying a live receipt whose ``evidence_host`` is that same host.

It unifies the two pre-existing host vocabularies:

* dispatch route-evidence proofs — ``requested_host`` / ``actual_host``
* the host-storage identity contract — ``target_host`` / ``command_host``

into one model with the load-bearing addition of ``evidence_host`` (the host
whose kernel actually produced the bytes) and an orthogonal
``recency_class`` x ``locality_class`` provenance grading.

Single-user invariant: every field here is a *machine* identity (``hostname``),
never a user, account, role, or permission. Host scope is topology, not access
control (axiom ``single_user``).

Governed by ``host-storage-inventory-receipt-infra-20260606`` /
``infra-host-provenance-primitive-source-20260606``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

Hostname = str
"""Canonical machine identity — the output of ``hostname`` (e.g. ``hapax-podium``).
Never a user/role/account. A receipt that rests host identity on this *string*
alone is weak; pair it with a machine-rooted anchor (root-disk serial / ssh
host-key fingerprint / machine-id) captured in the same command stream."""


class EvidenceClass(StrEnum):
    """Derived grade = (recency, locality). Only ``LIVE`` discharges a destructive
    predicate; ``RECENT`` is a fresh cross-host (SSH) probe; the rest cannot."""

    LIVE = "live"  # recency=live AND locality=same_host
    RECENT = "recent"  # recency=live AND locality=cross_host_ssh
    HISTORICAL = "historical"
    BIOS = "bios"  # firmware-visible only; never proves a Linux fs/mount
    DOCUMENT = "document"


class RecencyClass(StrEnum):
    LIVE = "live"
    RECENT = "recent"
    STALE = "stale"


class LocalityClass(StrEnum):
    SAME_HOST = "same_host"
    CROSS_HOST_SSH = "cross_host_ssh"
    DOCUMENT = "document"
    BIOS = "bios"


class Transport(StrEnum):
    LOCAL = "local"  # probe ran on the target itself
    SSH = "ssh"  # probe ran remotely; evidence_host read inside the receipt


class ClaimKind(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    PROPERTY = "property"  # a non-presence attribute (e.g. "/store 37% used")
    DISPATCH = "dispatch"  # a routing/landing claim
    UNKNOWN = "unknown"  # not yet witnessed on the target host (NOT absent)


class EvidenceWitness(BaseModel):
    """Machine-rooted, non-secret identity captured *in the same command stream*
    as the device rows, so a wrong SSH destination is caught by mismatch rather
    than assumed away. ``hostname`` alone is not trusted as identity."""

    hostname: Hostname
    machine_id: str | None = None
    root_disk_serial: str | None = None  # device-intrinsic anchor; non-secret
    ssh_host_key_fp: str | None = None  # public host-key fingerprint
    captured_in_same_command: bool = True
    anchor_verified: bool = False


class StorageReceipt(BaseModel):
    """The bytes backing a claim. ``evidence_host`` is the host whose kernel
    produced the rows; for a remote probe it is read INSIDE the SSH session."""

    evidence_host: Hostname
    command_host: Hostname
    transport: Transport
    recency_class: RecencyClass
    locality_class: LocalityClass
    witness: EvidenceWitness | None = None

    @property
    def evidence_class(self) -> EvidenceClass:
        if self.recency_class == RecencyClass.LIVE:
            return (
                EvidenceClass.LIVE
                if self.locality_class == LocalityClass.SAME_HOST
                else EvidenceClass.RECENT
            )
        if self.locality_class == LocalityClass.BIOS:
            return EvidenceClass.BIOS
        if self.locality_class == LocalityClass.DOCUMENT:
            return EvidenceClass.DOCUMENT
        return EvidenceClass.HISTORICAL

    @model_validator(mode="after")
    def _transport_consistency(self) -> StorageReceipt:
        # I3: a remote (SSH) probe must read the target's own hostname, so its
        # command_host (the SSH client) differs from the evidence_host.
        if self.transport == Transport.SSH and self.command_host == self.evidence_host:
            raise ValueError(
                "SSH receipt has command_host == evidence_host; the remote `hostname` "
                "was not captured inside the receipt — cannot trust evidence_host."
            )
        if self.transport == Transport.LOCAL and self.command_host != self.evidence_host:
            raise ValueError("LOCAL receipt: command_host must equal evidence_host.")
        return self


class HostScopedClaim(BaseModel):
    """Every infrastructure assertion. A bare "visible"/"missing" verb is
    un-representable: you cannot construct PRESENT/ABSENT/PROPERTY without a
    ``target_host`` AND a receipt whose ``evidence_host`` is that host."""

    target_host: Hostname
    kind: ClaimKind
    statement: str
    receipts: list[StorageReceipt] = Field(default_factory=list)
    # dispatch provenance (proof schema v1 fields; "appendix" normalizes to "hapax-appendix"):
    requested_host: Hostname | None = None
    actual_host: Hostname | None = None
    dispatch_host: Hostname | None = None

    @model_validator(mode="after")
    def _enforce_provenance(self) -> HostScopedClaim:
        # I1/I3: a fact about target_host needs a LIVE receipt whose
        # evidence_host == target_host (podium evidence cannot prove appendix).
        if self.kind in (ClaimKind.PRESENT, ClaimKind.ABSENT, ClaimKind.PROPERTY):
            ok = any(
                r.recency_class == RecencyClass.LIVE and r.evidence_host == self.target_host
                for r in self.receipts
            )
            if not ok:
                raise ValueError(
                    f"{self.kind} claim about {self.target_host} has no LIVE receipt with "
                    f"evidence_host == {self.target_host}. "
                    "(SN7100 guard: one host's evidence cannot answer another host's question.)"
                )
        # I2: presence/absence/property prose must name the target host.
        if self.kind in (ClaimKind.ABSENT, ClaimKind.PROPERTY, ClaimKind.PRESENT):
            if self.target_host not in self.statement:
                raise ValueError(
                    f"{self.kind} statement must name target_host '{self.target_host}' "
                    "(no bare 'missing'/'visible')."
                )
        # I4/I5: a dispatch is trustworthy only if requested == actual (proof-backed).
        if self.kind == ClaimKind.DISPATCH:
            if self.requested_host is None or self.actual_host is None:
                raise ValueError("DISPATCH claim requires requested_host and actual_host.")
            if _norm(self.requested_host) != _norm(self.actual_host):
                raise ValueError(
                    f"Untrusted dispatch: requested_host={self.requested_host} != "
                    f"actual_host={self.actual_host} (fallback/mis-route)."
                )
            if self.dispatch_host is not None and _norm(self.dispatch_host) != _norm(
                self.actual_host
            ):
                raise ValueError(
                    f"Mis-route: dispatch_host={self.dispatch_host} "
                    f"!= actual_host={self.actual_host}."
                )
        return self


_HOST_ALIASES: dict[str, str] = {"podium": "hapax-podium", "appendix": "hapax-appendix"}


def _norm(host: str) -> str:
    """Normalize short dispatch forms (``appendix``) to canonical hostnames so
    ``requested_host == actual_host`` does not spuriously fail."""
    return _HOST_ALIASES.get(host, host)
