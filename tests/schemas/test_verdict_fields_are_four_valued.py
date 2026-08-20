"""A control that cannot say "unknown" says "failed", and a human becomes the measurement.

`_stale_supply_metadata` already knows which of two very different things happened —
`observed_at is None` (no producer has ever written this) versus a computed expiry (a producer
wrote it and it aged out) — and then threw the distinction away, emitting one veto code
`stale_supply_field` with the message "is stale **or** missing".

They are not the same defect and they do not have the same repair: absent means *build or wire
a producer*, expired means *refresh one*. Collapsing them is how a 94-day gap between the live
capability-receipt store (six producers, refreshed continuously) and the registry the veto
actually reads (`quota_checked_at` NULL on 15/15 routes) stayed invisible while both artifacts
looked healthy in isolation. It surfaced as 15/15 routes blocked and
`no_eligible_dimensional_candidates` on 516 of 548 route decisions.

Six independent investigations converged on this one repair inside 24 hours, in six
vocabularies: four-valued verdicts; a typed unknown/unable-to-observe state distinct from
verified-failing; `DARK_UNSUPPLIED`; typed `Unknown` in every predicate result;
kube-scheduler's `Unschedulable` vs `UnschedulableAndUnresolvable`; and 42 of 44 capability
registry reason codes being absence rendered as a routing verdict.

## Why this pins the reason codes and not the schema's boolean verdict fields

The schema declares nine `type: boolean` verdict keys (`launch_allowed`, `route_policy_green`,
`quality_floor_satisfied`, …) against enum outcome keys. Converting those to enums looks like
the obvious fix and is a trap: 18 call sites read them for truthiness, and `if
decision.launch_allowed:` where the value became `"viol"` is **truthy**, silently inverting
nine vetoes. A refactor that introduces a silent inversion to fix a silent collapse is not
progress. Those nine need a derived-companion design and a separate, reviewed change.

The reason codes are where the information was actually destroyed, they carry no truthiness
semantics, and the branch that knows the answer already exists. That is what this pins.

The nine schema fields are deferred, not dropped. The design they need — an additive
four-valued companion per field with the boolean *derived* from it, so the 18 read sites keep
working and the two cannot disagree — is carried by cc-task
`schema-verdict-booleans-need-derived-companions-20260820`, together with the ordering note
that `registry_freshness_green` / `quota_freshness_green` / `resource_freshness_green` have
one assignment site each while `quality_floor_satisfied` and `authority_allowed` have 37 and
28. This pointer lives here as well as in the task note so the deferral is visible from the
code, not only from the vault.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shared.dispatcher_policy import (
    LEGACY_STALE_SUPPLY_FIELD_CODE,
    STALE_SUPPLY_FIELD_CODES,
    SUPPLY_FIELD_ABSENT_CODE,
    SUPPLY_FIELD_EXPIRED_CODE,
    CandidateStatus,
    DimensionalCandidateReceipt,
    DimensionalVeto,
    StaleMetadataReceipt,
    _has_unknown_supply_veto,
    _receipt_stale_metadata,
    _supply_field_veto,
)


def _receipt(kind: str) -> StaleMetadataReceipt:
    return StaleMetadataReceipt(
        source_id="claude.headless.full",
        field="capability_scores.context_tools_execution_fit.observed_at",
        effect="veto",
        kind=kind,  # type: ignore[arg-type]
    )


def test_emission_maps_absent_and_expired_to_different_codes() -> None:
    """The mutation guard. This is the assertion that reddens if the branch is removed.

    The constants can all be correct while the emitter still sends one code for both, which
    is exactly the state this change repairs. Testing the constants alone would have been
    documentation, not verification.
    """
    absent = _supply_field_veto(_receipt("absent"))
    expired = _supply_field_veto(_receipt("expired"))
    assert absent.code == SUPPLY_FIELD_ABSENT_CODE
    assert expired.code == SUPPLY_FIELD_EXPIRED_CODE
    assert absent.code != expired.code, (
        "the emitter collapsed both unknowns to one code again — 'no producer exists' and "
        "'the producer is stale' are different repairs and this is where that was lost"
    )


def test_both_unknowns_drive_the_stale_classification() -> None:
    """Found by mutation testing: asserting the constant's contents was not enough.

    Narrowing the classification site back to a single code left every other test green
    while silently reclassifying an absent-supply candidate from STALE to VETOED. The
    membership assertion passes whether or not the consumer consults the membership, so the
    consumer itself has to be exercised.
    """
    for kind in ("absent", "expired"):
        veto = _supply_field_veto(_receipt(kind))
        assert _has_unknown_supply_veto([veto]), (
            f"a {kind}-supply veto no longer classifies as unknown; candidates that were "
            "STALE become VETOED, which is a dispatch behaviour change disguised as a "
            "diagnostics change"
        )


def test_a_measured_failure_is_not_classified_as_unknown() -> None:
    """The other direction: unknown must not swallow genuine measured vetoes."""
    measured = DimensionalVeto(
        code="requirement_floor_not_satisfied",
        field="capability_scores.reasoning_depth",
        evidence_ref="claude.headless.full",
        message="supply 2 < demand 4",
    )
    assert not _has_unknown_supply_veto([measured])


def test_serialized_receipt_preserves_absent_through_reconstruction() -> None:
    """Raised as unresolved-critical by codex-1 and it was a real bug in this change.

    `_receipt_stale_metadata` rebuilds `StaleMetadataReceipt` from the candidate's vetoes to
    populate `stale_metadata`, which `write_route_decision_receipt` then serializes. It set no
    `kind`, so the default applied — and because this change *widened* the filter to accept
    `supply_field_absent`, an absent veto came out of reconstruction labelled `expired`.

    That is worse than the defect being fixed: the old single code was ambiguous, this was
    affirmatively wrong, and it pointed consumers at "refresh the producer" for a field no
    producer has ever written.

    The earlier tests all exercised the extracted helpers and never this path, which is why
    the mutation pass did not catch it either. This one round-trips the real reconstruction.
    """
    candidate = DimensionalCandidateReceipt(
        route_id="glmcp.review.direct",
        platform="glmcp",
        status=CandidateStatus.STALE,
        freshness_state="stale",
        vetoes=(
            _supply_field_veto(_receipt("absent")),
            _supply_field_veto(_receipt("expired")),
        ),
    )
    by_kind = {r.kind for r in _receipt_stale_metadata(candidate)}
    assert by_kind == {"absent", "expired"}, (
        f"reconstruction collapsed the kinds to {by_kind}; a serialized route receipt would "
        "name the wrong repair for one of them"
    )


def test_emitted_messages_name_their_repair() -> None:
    """A reason code a human cannot act on sends them to read source."""
    absent = _supply_field_veto(_receipt("absent")).message
    expired = _supply_field_veto(_receipt("expired")).message
    assert "never been written" in absent and "build" in absent
    assert "expired" in expired and "refresh" in expired
    assert absent != expired
    assert "stale or missing" not in absent, "the old ambiguous message is back"


def test_the_two_unknowns_have_distinct_codes() -> None:
    """If these ever collapse again, 'build a producer' and 'refresh one' become one word."""
    assert SUPPLY_FIELD_ABSENT_CODE != SUPPLY_FIELD_EXPIRED_CODE


def test_both_unknowns_still_classify_as_stale() -> None:
    """The repair must not silently reclassify candidates from STALE to VETOED.

    `STALE_SUPPLY_FIELD_CODES` has two consumers and they do **different** things, which is
    worth stating precisely because conflating them is how the reconstruction bug got missed:

    - `_candidate_receipt` gates on this membership to choose `CandidateStatus.STALE`. That
      is the classification path, covered here.
    - `_receipt_stale_metadata` uses the same membership only as a *filter*, then
      **reconstructs** `StaleMetadataReceipt` objects for the serialized receipt. That is a
      separate path with its own failure mode — it is where `absent` was silently relabelled
      `expired` — and it is covered by
      `test_serialized_receipt_preserves_absent_through_reconstruction`, not by this test.

    Splitting the code without widening the classification consumer would have changed
    dispatch behaviour as a side effect of a diagnostics change.
    """
    assert SUPPLY_FIELD_ABSENT_CODE in STALE_SUPPLY_FIELD_CODES
    assert SUPPLY_FIELD_EXPIRED_CODE in STALE_SUPPLY_FIELD_CODES


def test_historical_receipts_still_classify() -> None:
    """`route-decisions.jsonl` holds records written under the old single code."""
    assert LEGACY_STALE_SUPPLY_FIELD_CODE in STALE_SUPPLY_FIELD_CODES


def test_receipt_kind_defaults_to_expired_not_absent() -> None:
    """Absent is the stronger claim; a caller that forgets must not accidentally assert it.

    Defaulting the other way would let an unmarked receipt claim "no producer has ever
    written this", which routes a human to build a producer that already exists.
    """
    receipt = StaleMetadataReceipt(source_id="r", field="f", effect="veto")
    assert receipt.kind == "expired"


def test_absent_and_expired_are_both_expressible() -> None:
    now = datetime.now(UTC)
    absent = StaleMetadataReceipt(source_id="r", field="f", effect="veto", kind="absent")
    expired = StaleMetadataReceipt(
        source_id="r",
        field="f",
        effect="veto",
        kind="expired",
        observed_at=now - timedelta(days=94),
        stale_after="24h",
    )
    assert absent.kind == "absent"
    assert absent.observed_at is None, "an absent field cannot carry an observation time"
    assert expired.kind == "expired"
    assert expired.observed_at is not None, "an expired field must carry when it was measured"
