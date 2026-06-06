"""Tests for shared.host_provenance — the host-scoped-claim primitive.

Pins the 2026-06-06 WD_BLACK SN7100 host-context-drift failure as a
construction-time ValidationError. Self-contained (no conftest, no live host).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.host_provenance import (
    ClaimKind,
    EvidenceClass,
    EvidenceWitness,
    HostScopedClaim,
    LocalityClass,
    RecencyClass,
    StorageReceipt,
    Transport,
)

PODIUM = "hapax-podium"
APPENDIX = "hapax-appendix"


def _live_local(host: str) -> StorageReceipt:
    return StorageReceipt(
        evidence_host=host,
        command_host=host,
        transport=Transport.LOCAL,
        recency_class=RecencyClass.LIVE,
        locality_class=LocalityClass.SAME_HOST,
        witness=EvidenceWitness(hostname=host, root_disk_serial="ANCHOR", anchor_verified=True),
    )


def _live_ssh(evidence_host: str, command_host: str) -> StorageReceipt:
    return StorageReceipt(
        evidence_host=evidence_host,
        command_host=command_host,
        transport=Transport.SSH,
        recency_class=RecencyClass.LIVE,
        locality_class=LocalityClass.CROSS_HOST_SSH,
    )


# ── The SN7100 guard (the keystone regression) ──────────────────────────────


def test_absent_claim_about_appendix_with_only_podium_evidence_rejected():
    """podium evidence cannot ground an absence claim about appendix."""
    with pytest.raises(ValidationError) as exc:
        HostScopedClaim(
            target_host=APPENDIX,
            kind=ClaimKind.ABSENT,
            statement="WD_BLACK SN7100 absent on hapax-appendix",
            receipts=[_live_local(PODIUM)],
        )
    msg = str(exc.value)
    assert APPENDIX in msg and "evidence_host" in msg


def test_absent_claim_about_appendix_with_live_appendix_evidence_ok():
    claim = HostScopedClaim(
        target_host=APPENDIX,
        kind=ClaimKind.ABSENT,
        statement="device serial X absent on hapax-appendix",
        receipts=[_live_local(APPENDIX)],
    )
    assert claim.kind is ClaimKind.ABSENT


def test_present_claim_via_ssh_evidence_of_target_ok():
    """A cross-host SSH receipt whose evidence_host == target is valid."""
    claim = HostScopedClaim(
        target_host=APPENDIX,
        kind=ClaimKind.PRESENT,
        statement="SN7100 present on hapax-appendix",
        receipts=[_live_ssh(evidence_host=APPENDIX, command_host=PODIUM)],
    )
    assert claim.kind is ClaimKind.PRESENT


def test_property_claim_is_also_host_guarded():
    """PROPERTY (e.g. fullness) is the unguarded-majority class — it must be guarded too."""
    with pytest.raises(ValidationError):
        HostScopedClaim(
            target_host=APPENDIX,
            kind=ClaimKind.PROPERTY,
            statement="/store is 22% used on hapax-appendix",
            receipts=[_live_local(PODIUM)],
        )


# ── Prose must name the host (the bare-verb guard) ──────────────────────────


def test_absent_statement_without_host_name_rejected():
    with pytest.raises(ValidationError):
        HostScopedClaim(
            target_host=APPENDIX,
            kind=ClaimKind.ABSENT,
            statement="device not visible",  # no host subscript
            receipts=[_live_local(APPENDIX)],
        )


# ── UNKNOWN is first-class (not absence) ────────────────────────────────────


def test_unknown_claim_needs_no_receipt():
    claim = HostScopedClaim(
        target_host=APPENDIX,
        kind=ClaimKind.UNKNOWN,
        statement="not yet witnessed on hapax-appendix",
    )
    assert claim.kind is ClaimKind.UNKNOWN


# ── Dispatch trust (requested == actual, with alias normalization) ──────────


def test_dispatch_requested_ne_actual_rejected():
    with pytest.raises(ValidationError):
        HostScopedClaim(
            target_host=PODIUM,
            kind=ClaimKind.DISPATCH,
            statement="ran",
            requested_host="appendix",
            actual_host="hapax-podium",  # fell back to podium
        )


def test_dispatch_requested_eq_actual_after_normalization_ok():
    claim = HostScopedClaim(
        target_host=APPENDIX,
        kind=ClaimKind.DISPATCH,
        statement="ran",
        requested_host="appendix",
        actual_host="hapax-appendix",  # normalizes equal
    )
    assert claim.kind is ClaimKind.DISPATCH


def test_dispatch_host_misroute_rejected():
    with pytest.raises(ValidationError):
        HostScopedClaim(
            target_host=APPENDIX,
            kind=ClaimKind.DISPATCH,
            statement="ran",
            requested_host="hapax-appendix",
            actual_host="hapax-appendix",
            dispatch_host="hapax-podium",  # configured wrong
        )


# ── Receipt transport consistency (I3) ──────────────────────────────────────


def test_local_receipt_requires_command_eq_evidence():
    with pytest.raises(ValidationError):
        StorageReceipt(
            evidence_host=APPENDIX,
            command_host=PODIUM,
            transport=Transport.LOCAL,
            recency_class=RecencyClass.LIVE,
            locality_class=LocalityClass.SAME_HOST,
        )


def test_ssh_receipt_requires_command_ne_evidence():
    with pytest.raises(ValidationError):
        StorageReceipt(
            evidence_host=PODIUM,
            command_host=PODIUM,  # remote hostname not actually captured
            transport=Transport.SSH,
            recency_class=RecencyClass.LIVE,
            locality_class=LocalityClass.CROSS_HOST_SSH,
        )


# ── evidence_class derivation ───────────────────────────────────────────────


def test_evidence_class_live_same_host_is_live():
    assert _live_local(PODIUM).evidence_class is EvidenceClass.LIVE


def test_evidence_class_live_cross_host_is_recent():
    assert _live_ssh(APPENDIX, PODIUM).evidence_class is EvidenceClass.RECENT


def test_evidence_class_stale_is_historical():
    r = StorageReceipt(
        evidence_host=APPENDIX,
        command_host=PODIUM,
        transport=Transport.SSH,
        recency_class=RecencyClass.STALE,
        locality_class=LocalityClass.CROSS_HOST_SSH,
    )
    assert r.evidence_class is EvidenceClass.HISTORICAL
