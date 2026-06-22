"""Phase-1 deontic-ledger population loop: project a Commitment per composed claim.

The producer reads each entry of ``segment_prep_contract['claim_map']`` and projects a
``Commitment`` off its CONTENT (purport, rebuttal_condition, qualifier). The board is
OBSERVE-ONLY in Phase 1: ``HAPAX_INVERTED_QUIESCENCE`` stays OFF and nothing gates on it;
the projected ledger is recorded in the released artifact for observability and to seed
the later R2/R3 phases. Self-contained per council test conventions (no shared conftest,
``unittest.mock`` only).
"""

from __future__ import annotations

import json
import os
from unittest import mock

from agents.hapax_daimonion.daily_segment_prep import (
    _build_deontic_ledger,
    _project_commitments_from_contract,
)
from shared.inquiry_blackboard import Commitment


def _claim(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "claim_id": "claim:prog:beat-1:1",
        "beat_id": "beat-1",
        "claim_text": "the attribution log's blank field unattributes every downstream license",
        "claim_kind": "livestream_segment_claim",
        "grounds": ["src:0"],
        "warrant": "source packet and beat plan must change the public claim",
        "qualifier_or_limit": "prep prior only pending runtime readback",
        "source_consequence": "source must alter scope, rank, confidence, contrast, or visible action",
        "visible_object_ids": ["object:prog:beat-1"],
    }
    base.update(overrides)
    return base


def test_projects_one_commitment_per_claim_map_entry() -> None:
    contract = {"claim_map": [_claim(), _claim(claim_id="claim:prog:beat-2:1", beat_id="beat-2")]}
    commitments = _project_commitments_from_contract(contract)
    assert len(commitments) == 2
    assert all(isinstance(c, Commitment) for c in commitments)
    assert [c.claim_id for c in commitments] == ["claim:prog:beat-1:1", "claim:prog:beat-2:1"]


def test_commitment_fields_map_from_claim_entry() -> None:
    contract = {"claim_map": [_claim()]}
    (commitment,) = _project_commitments_from_contract(contract)
    assert commitment.discharge_route == "undischarged"
    # No rival/incompatibility field exists on claim_map — Phase 1 never fabricates one.
    assert commitment.incompatibilities == ()
    assert (
        commitment.rebuttal_condition == "source packet and beat plan must change the public claim"
    )
    assert commitment.qualifier == "prep prior only pending runtime readback"


def test_purport_reads_text_grounds_and_consequence_off_content() -> None:
    contract = {"claim_map": [_claim()]}
    (commitment,) = _project_commitments_from_contract(contract)
    joined = " || ".join(commitment.purport)
    assert "unattributes every downstream license" in joined  # the assertion itself
    # The grounds element records a DEFERRAL fact (the claim cites these grounds), NOT an
    # intrinsic empirical commitment — grounds is recruitment-backfilled in the live
    # pipeline, so it must never be labelled "evidence existing" (that is R3's content read).
    assert "carries recruited grounds: src:0" in joined
    assert "commits to mind-independent evidence existing" not in joined
    assert "alter scope, rank" in joined  # the licensed consequence


def test_purport_omits_grounds_element_when_no_grounds() -> None:
    contract = {"claim_map": [_claim(grounds=[])]}
    (commitment,) = _project_commitments_from_contract(contract)
    joined = " || ".join(commitment.purport)
    assert "carries recruited grounds" not in joined  # no grounds → no deferral element
    assert "unattributes every downstream license" in joined  # the assertion still projects


def test_bare_string_grounds_is_one_ground_not_chars() -> None:
    # A model emitting grounds="src:0" (not ["src:0"]) must be read as ONE ground, never
    # iterated per-character into fabricated tokens.
    contract = {"claim_map": [_claim(grounds="src:0")]}
    (commitment,) = _project_commitments_from_contract(contract)
    joined = " || ".join(commitment.purport)
    assert "carries recruited grounds: src:0" in joined


def test_claim_with_only_id_records_under_projected_marker() -> None:
    # A claim that asserts nothing inspectable is a thin-reading fingerprint — recorded
    # visibly (an empty purport tuple would hide it).
    contract = {"claim_map": [{"claim_id": "claim:prog:beat-1:1"}]}
    (commitment,) = _project_commitments_from_contract(contract)
    assert commitment.purport != ()
    assert any("under-projected" in element for element in commitment.purport)


def test_skips_non_mapping_and_empty_claim_id_entries() -> None:
    contract = {"claim_map": [_claim(), 42, _claim(claim_id="  ")]}
    commitments = _project_commitments_from_contract(contract)
    # The junk (non-mapping) entry and the empty-claim_id entry are both skipped.
    assert len(commitments) == 1


def test_empty_claim_map_yields_no_commitments() -> None:
    assert _project_commitments_from_contract({"claim_map": []}) == []
    assert _project_commitments_from_contract({}) == []


def test_non_list_claim_map_yields_no_commitments_not_garbage() -> None:
    # A present-but-non-list claim_map must not iterate into chars/keys and silently
    # fabricate skipped entries — it is treated as "no claims".
    assert _project_commitments_from_contract({"claim_map": "abc"}) == []
    assert _project_commitments_from_contract({"claim_map": {"claim_id": "k"}}) == []


def test_build_deontic_ledger_is_observe_only_with_flag_off() -> None:
    contract = {"claim_map": [_claim(), _claim(claim_id="claim:prog:beat-2:1", beat_id="beat-2")]}
    with mock.patch.dict(os.environ):
        os.environ.pop("HAPAX_INVERTED_QUIESCENCE", None)
        ledger = _build_deontic_ledger(contract, segment_prep_contract_sha256="deadbeef")
    assert ledger["commitment_count"] == 2
    assert ledger["undischarged_count"] == 2
    assert ledger["inverted_quiescence_active"] is False
    # The inverted verdict is honestly False in Phase 1: claims exist but carry no
    # independent attestations yet, so the board cannot rest — silence is not rest.
    assert ledger["would_quiesce_inverted"] is False
    assert ledger["segment_prep_contract_sha256"] == "deadbeef"
    assert "schema_version" in ledger
    assert len(ledger["commitments"]) == 2
    assert all(c["discharge_route"] == "undischarged" for c in ledger["commitments"])


def test_deontic_ledger_is_json_round_trip_stable() -> None:
    # The ledger dict is hash-covered by artifact_sha256 and re-verified after a json
    # reload — every value MUST be JSON-native and round-trip-identical.
    contract = {"claim_map": [_claim(grounds=["src:0", "src:1"])]}
    ledger = _build_deontic_ledger(contract, segment_prep_contract_sha256="abc123")
    assert json.loads(json.dumps(ledger)) == ledger


def test_build_deontic_ledger_degrades_on_malformed_contract() -> None:
    # A non-dict contract makes projection raise; the ledger must degrade, never raise,
    # so an observe-only failure can never block an already-authorized release.
    ledger = _build_deontic_ledger(["not", "a", "contract"], segment_prep_contract_sha256="cafe")
    assert ledger["commitments"] == []
    assert ledger["commitment_count"] == 0
    assert ledger["would_quiesce_inverted"] is None
    assert "projection_error" in ledger
    assert ledger["segment_prep_contract_sha256"] == "cafe"


def test_build_deontic_ledger_never_raises_on_adversarial_inputs() -> None:
    # The observe-only invariant lives at this helper layer: it must NEVER raise, for ANY
    # input, so a ledger failure can at worst record a degraded stub.
    for bad in (None, ["x"], {"claim_map": 5}, 42, "string", {"claim_map": [42, None]}):
        ledger = _build_deontic_ledger(bad, segment_prep_contract_sha256="h")
        assert isinstance(ledger, dict)
        assert ledger["segment_prep_contract_sha256"] == "h"
        assert "schema_version" in ledger
