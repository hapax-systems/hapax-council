"""Rebinding admission boundary; constructing a basis does not authorize effects."""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

import shared.sdlc_claim as sdlc_claim
from shared.sdlc_claim import prospective_claim_publication_basis
from tests.shared.test_sdlc_claim import _active_admission_fixture, _fixture


@pytest.mark.parametrize("resume", [False, True])
def test_existing_claim_modes_keep_their_non_authorizing_basis(
    tmp_path: Path, resume: bool
) -> None:
    fixture = _fixture(tmp_path, resume=resume)
    basis = prospective_claim_publication_basis(fixture.intent)
    assert basis.claim_mode == ("resume" if resume else "claim")
    assert basis.may_authorize is False


def test_rebind_has_a_distinct_non_authorizing_admission_basis(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, resume=True)
    # This tests the representation boundary only. A valid ownership transfer
    # additionally needs predecessor, authorization and liveness checks inside
    # the admitted publication transaction; this basis grants none of them.
    intent = replace(fixture.intent, claim_mode="rebind")
    basis = prospective_claim_publication_basis(intent)
    assert basis.claim_mode == "rebind"
    assert basis.claim_publication_intent.sha256 == intent.intent_sha256
    assert basis.may_authorize is False


@pytest.mark.parametrize("mode", ["force", "release", "", "resume-or-steal"])
def test_unknown_modes_cannot_acquire_a_publication_basis(tmp_path: Path, mode: str) -> None:
    fixture = _fixture(tmp_path, resume=True)
    with pytest.raises(ValidationError):
        prospective_claim_publication_basis(replace(fixture.intent, claim_mode=mode))


def test_rebind_basis_and_publication_lease_cannot_replace_ownership_evidence(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, resume=True)
    fixture = replace(fixture, intent=replace(fixture.intent, claim_mode="rebind"))
    admission = _active_admission_fixture(tmp_path, fixture)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    # Even a five-proof publication lease has no exact incumbent or liveness
    # evidence here. Extending the non-authorizing vocabulary must not allow
    # this incomplete transfer to write a journal, note, or activation cache.
    with pytest.raises(sdlc_claim.ClaimPublicationError) as raised:
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            admission.consumption,
            transaction_root=fixture.transactions,
            lock_root=fixture.locks,
        )
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert raised.value.reason_code == "claim_rebind_attempt_domain_unqualified"
    assert "claim-bound" in raised.value.repair_action
