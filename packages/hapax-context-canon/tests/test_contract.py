from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import hapax.context_canon as canon
from hapax.context_canon.contract import _domain_hash

FIXTURES = Path(__file__).parent / "fixtures"


def _address(prefix: str, value: object) -> tuple[str, str]:
    digest = hashlib.sha256(canon.canonical_json_bytes(value)).hexdigest()
    return f"{prefix}@sha256:{digest}", digest


def _selection_entries(frame: canon.ContextFrame) -> tuple[canon.ContextSelectionEntry, ...]:
    entries = []
    for fact in frame.facts:
        if fact.fact_id == "fact:capability-gap":
            entries.append(
                canon.ContextSelectionEntry(
                    fact_ref=fact.fact_id,
                    requiredness="optional",
                    classes=("loss_bearing", "selected"),
                    reason_codes=("independent_measurement_missing",),
                )
            )
        elif fact.fact_id == "fact:private-canary":
            entries.append(
                canon.ContextSelectionEntry(
                    fact_ref=fact.fact_id,
                    requiredness="optional",
                    classes=("redacted",),
                    reason_codes=("audience_policy_redaction",),
                )
            )
        else:
            entries.append(
                canon.ContextSelectionEntry(
                    fact_ref=fact.fact_id,
                    requiredness="required",
                    classes=("selected",),
                    reason_codes=(),
                )
            )
    return tuple(sorted(entries, key=lambda entry: entry.fact_ref))


def _build_selection(
    *,
    entries: tuple[canon.ContextSelectionEntry, ...] | None = None,
    checked_at: str = "2026-07-10T16:06:00Z",
    stale_after: str = "2026-07-10T18:00:00Z",
) -> canon.ContextSelection:
    frame = canon.ContextFrame.model_validate_json((FIXTURES / "gate0-frame.json").read_bytes())
    fact_refs = tuple(sorted(fact.fact_id for fact in frame.facts))
    event_refs = tuple(sorted(event.event_ref for event in frame.events))
    frontier_ref, frontier_hash = _address(
        "fact-frontier", {"event_refs": event_refs, "fact_refs": fact_refs}
    )
    seal_ref, seal_hash = _address(
        "audience-seal-receipt",
        {
            "audience": "hapax_substrate",
            "audience_policy_generation": frame.audience_policy_generation,
            "privacy_policy_generation": frame.privacy_policy_generation,
        },
    )
    policy_ref, policy_hash = _address(
        "context-selection-policy", {"generation": "selection-policy:g1"}
    )
    return canon.build_context_selection(
        frame.position,
        fact_frontier_ref=frontier_ref,
        fact_frontier_hash=frontier_hash,
        frontier_fact_refs=fact_refs,
        event_frontier_refs=event_refs,
        audience="hapax_substrate",
        audience_seal_receipt_ref=seal_ref,
        audience_seal_receipt_hash=seal_hash,
        audience_policy_generation=frame.audience_policy_generation,
        privacy_policy_generation=frame.privacy_policy_generation,
        selection_policy_ref=policy_ref,
        selection_policy_hash=policy_hash,
        selection_policy_generation="selection-policy:g1",
        entries=entries or _selection_entries(frame),
        checked_at=checked_at,
        stale_after=stale_after,
    )


def _rehash_selection(payload: dict) -> None:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"selection_ref", "selection_hash"}
    }
    digest = _domain_hash("hapax.context-selection.v1", body)
    payload["selection_hash"] = digest
    payload["selection_ref"] = f"context-selection@sha256:{digest}"


def test_frozen_frame_round_trips_byte_identically() -> None:
    raw = (FIXTURES / "gate0-frame.json").read_bytes()
    hashes = json.loads((FIXTURES / "gate0-hashes.json").read_text())
    frame = canon.ContextFrame.model_validate_json(raw)
    assert canon.canonical_json_bytes(frame.model_dump(mode="json", by_alias=True)) + b"\n" == raw
    assert frame.frame_hash == hashes["semantic_ids"]["frame_hash"]
    assert hashlib.sha256(raw).hexdigest() == hashes["gate0-frame.json"]["sha256"]


def test_public_boundary_excludes_compiler_and_execution_surfaces() -> None:
    forbidden = {
        "CanonSource",
        "CanonImage",
        "CanonBundle",
        "CanonCorpus",
        "build_corpus",
        "build_canon_bundle",
        "build_context_frame",
        "materialize_bundle",
        "load_materialized_bundle",
        "dispatch",
        "execute",
    }
    assert forbidden.isdisjoint(canon.__all__)
    assert (
        canon.LOCKED_CONTEXT_BUNDLE_CONTRACT_SHA256
        == "8204a2b2804aa41ac95f75414b58fa88ae1e76a48e6ef731807f544f4148fbd9"
    )


def _rehash_image(image: dict) -> None:
    body = {key: value for key, value in image.items() if key != "image_hash"}
    image["image_hash"] = hashlib.sha256(canon.canonical_json_bytes(body)).hexdigest()


@pytest.mark.parametrize("tamper", ["rendered_strata", "reference_token_count"])
def test_rehashed_intrinsic_image_tampering_is_rejected(tamper: str) -> None:
    payload = json.loads((FIXTURES / "gate0-frame.json").read_text())
    image = copy.deepcopy(payload["canon_image"])
    if tamper == "rendered_strata":
        image["rendered_strata"]["what"] = "forged rendered WHAT"
        image["rendered_payload"] = (
            f"FSM WHAT\n{image['rendered_strata']['what']}\n"
            f"FSM HOW\n{image['rendered_strata']['how']}\n"
            f"FSM MUST\n{image['rendered_strata']['must']}"
        )
    else:
        image["reference_token_count"] = 1
    _rehash_image(image)
    payload["canon_image"] = image
    with pytest.raises(
        ValidationError,
        match="rendered_strata do not bind|reference_token_count does not bind",
    ):
        canon.ContextFrame.model_validate(payload)


def test_context_selection_round_trips_without_changing_frozen_frame() -> None:
    frozen_frame = (FIXTURES / "gate0-frame.json").read_bytes()
    hashes = json.loads((FIXTURES / "gate0-hashes.json").read_text())
    selection = _build_selection()
    rebuilt = canon.ContextSelection.model_validate_json(
        canon.canonical_json_bytes(selection.model_dump(mode="json", by_alias=True))
    )

    assert rebuilt == selection
    assert selection.selection_ref == f"context-selection@sha256:{selection.selection_hash}"
    assert selection.state == canon.ContextState(value_state="present", reason_codes=())
    assert selection.audience == "hapax_substrate"
    assert selection.audience_seal_receipt_ref.endswith(
        f"@sha256:{selection.audience_seal_receipt_hash}"
    )
    assert selection.no_effect is True
    assert selection.may_authorize is False
    assert hashlib.sha256(frozen_frame).hexdigest() == hashes["gate0-frame.json"]["sha256"]


@pytest.mark.parametrize(
    ("classes", "reason_codes", "expected"),
    [
        (("rejected", "selected"), ("conflict",), "exactly one primary"),
        (("loss_bearing", "selected"), (), "require WHY"),
        (("selected",), ("spurious",), "clean selections have none"),
        (("missing", "stale"), ("unavailable",), "cannot also be stale"),
    ],
)
def test_context_selection_entry_partition_and_why_fail_closed(
    classes: tuple[str, ...], reason_codes: tuple[str, ...], expected: str
) -> None:
    with pytest.raises(ValidationError, match=expected):
        canon.ContextSelectionEntry(
            fact_ref="fact:test",
            requiredness="required",
            classes=classes,
            reason_codes=reason_codes,
        )


@pytest.mark.parametrize("mutation", ["missing_frontier_entry", "duplicate_entry", "false_missing"])
def test_context_selection_entries_exactly_cover_frontier_and_missing(mutation: str) -> None:
    payload = _build_selection().model_dump(mode="json", by_alias=True)
    if mutation == "missing_frontier_entry":
        payload["entries"].pop()
    elif mutation == "duplicate_entry":
        payload["entries"].append(copy.deepcopy(payload["entries"][0]))
    else:
        payload["entries"][0]["classes"] = ["missing"]
        payload["entries"][0]["reason_codes"] = ["forged_missing"]
    _rehash_selection(payload)

    with pytest.raises(ValidationError, match="sorted and unique|exactly classify"):
        canon.ContextSelection.model_validate(payload)


@pytest.mark.parametrize(
    ("entry", "reason_code"),
    [
        (
            canon.ContextSelectionEntry(
                fact_ref="fact:required-missing",
                requiredness="required",
                classes=("missing",),
                reason_codes=("source_unavailable",),
            ),
            "required_context_missing",
        ),
        (
            canon.ContextSelectionEntry(
                fact_ref="fact:required-missing",
                requiredness="required",
                classes=("loss_bearing", "missing"),
                reason_codes=("source_unavailable",),
            ),
            "required_context_loss_bearing",
        ),
    ],
)
def test_required_context_loss_derives_explicit_hold(
    entry: canon.ContextSelectionEntry, reason_code: str
) -> None:
    selection = _build_selection(entries=(*_build_selection().entries, entry))

    assert selection.state.value_state == "hold"
    assert "required_context_missing" in selection.state.reason_codes
    assert reason_code in selection.state.reason_codes


def test_context_selection_rejects_rehashed_forged_present_state() -> None:
    missing = canon.ContextSelectionEntry(
        fact_ref="fact:required-missing",
        requiredness="required",
        classes=("missing",),
        reason_codes=("source_unavailable",),
    )
    payload = _build_selection(entries=(*_build_selection().entries, missing)).model_dump(
        mode="json", by_alias=True
    )
    payload["state"] = {"value_state": "present", "reason_codes": []}
    _rehash_selection(payload)

    with pytest.raises(ValidationError, match="state must derive exactly"):
        canon.ContextSelection.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("audience", "operator_private"),
        ("audience_policy_generation", "audience:forged"),
        ("privacy_policy_generation", "privacy:forged"),
        ("selection_policy_generation", "selection-policy:forged"),
    ],
)
def test_context_selection_hash_binds_audience_and_policy(field: str, replacement: str) -> None:
    payload = _build_selection().model_dump(mode="json", by_alias=True)
    payload[field] = replacement

    with pytest.raises(ValidationError, match="selection_hash"):
        canon.ContextSelection.model_validate(payload)


@pytest.mark.parametrize(
    ("ref_field", "hash_field", "expected"),
    [
        ("position_ref", "position_hash", "context position"),
        ("fact_frontier_ref", "fact_frontier_hash", "fact frontier"),
        (
            "audience_seal_receipt_ref",
            "audience_seal_receipt_hash",
            "audience seal receipt",
        ),
        ("selection_policy_ref", "selection_policy_hash", "selection policy"),
    ],
)
def test_context_selection_rejects_rehashed_unbound_addresses(
    ref_field: str, hash_field: str, expected: str
) -> None:
    payload = _build_selection().model_dump(mode="json", by_alias=True)
    payload[hash_field] = "0" * 64
    _rehash_selection(payload)

    with pytest.raises(ValidationError, match=expected):
        canon.ContextSelection.model_validate(payload)


@pytest.mark.parametrize(
    ("checked_at", "stale_after", "expected"),
    [
        ("2026-07-10T18:00:00Z", "2026-07-10T18:00:00Z", "strictly precede"),
        ("2026-07-10T18:00:01Z", "2026-07-10T18:00:00Z", "strictly precede"),
        ("2026-07-10T16:06:00.000000Z", "2026-07-10T18:00:00Z", "canonical UTC"),
    ],
)
def test_context_selection_temporal_validity_fails_closed(
    checked_at: str, stale_after: str, expected: str
) -> None:
    with pytest.raises(ValidationError, match=expected):
        _build_selection(checked_at=checked_at, stale_after=stale_after)
