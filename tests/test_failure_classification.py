"""Tests for the shared failure-classification vocabulary (measurement-spine root)."""

from __future__ import annotations

from shared.failure_classification import (
    FALLBACK_LADDER_ERROR_CLASSES,
    STRUCTURED_PROVIDER_OUTAGE_ACTIONS,
    STRUCTURED_PROVIDER_OUTAGE_ERROR_CLASSES,
    STRUCTURED_QUOTA_ACTIONS,
    STRUCTURED_QUOTA_ERROR_CLASSES,
    ZAI_ERROR_CLASS_BY_CODE,
    FailureCode,
    FailureReceipt,
    failure_code_for_zai,
)


def test_failure_code_has_exactly_the_nine_members() -> None:
    assert {c.value for c in FailureCode} == {
        "quota_exhaustion",
        "provider_outage",
        "auth_failure",
        "claim_conflict",
        "route_unavailable",
        "fair_use_restricted",
        "invalid_output",
        "transient",
        "unknown",
    }


def test_failure_receipt_is_lossless_and_defaults_to_unknown() -> None:
    bare = FailureReceipt(raw_signal="some ambiguous text")
    assert bare.code is FailureCode.UNKNOWN  # no auto-degrade
    assert bare.platform is None and bare.route_id is None

    full = FailureReceipt(
        code=FailureCode.QUOTA_EXHAUSTION,
        raw_signal="HTTP 429 ...",
        platform="zai",
        route_id="glm-5",
        zai_code="1310",
        error_class="quota_exhausted",
        action="hold_until_reset",
        resets_at="2026-06-20T07:00:00Z",
        message="quota exceeded",
        http_status=429,
    )
    assert full.raw_signal == "HTTP 429 ..."  # nothing dropped
    assert full.platform == "zai" and full.route_id == "glm-5"
    assert full.zai_code == "1310" and full.http_status == 429


def test_failure_receipt_is_frozen_and_extra_forbid() -> None:
    import pytest
    from pydantic import ValidationError

    r = FailureReceipt(raw_signal="x")
    with pytest.raises(ValidationError):
        FailureReceipt(raw_signal="x", not_a_field=1)  # extra=forbid
    with pytest.raises((TypeError, ValidationError)):
        r.code = FailureCode.TRANSIENT  # frozen


def test_cc_task_pinned_zai_code_mappings() -> None:
    """The cc-task pins 1310/1312/1313 -> QUOTA_EXHAUSTION/PROVIDER_OUTAGE/FAIR_USE_RESTRICTED."""
    for code, expected in (
        ("1310", FailureCode.QUOTA_EXHAUSTION),
        ("1312", FailureCode.PROVIDER_OUTAGE),
        ("1313", FailureCode.FAIR_USE_RESTRICTED),
    ):
        error_class = ZAI_ERROR_CLASS_BY_CODE[code][0]
        assert failure_code_for_zai(error_class) is expected


def test_every_produced_error_class_maps_to_a_code_only_api_error_is_unknown() -> None:
    """Every error_class the codebase can produce (the code table + the fallback ladder) has a
    non-UNKNOWN FailureCode — except api_error, the deliberate no-auto-degrade terminal default."""
    produced = {v[0] for v in ZAI_ERROR_CLASS_BY_CODE.values()} | FALLBACK_LADDER_ERROR_CLASSES
    for error_class in produced:
        mapped = failure_code_for_zai(error_class)
        if error_class == "api_error":
            assert mapped is FailureCode.UNKNOWN
        else:
            assert mapped is not FailureCode.UNKNOWN, f"{error_class} unmapped"


def test_failure_code_for_zai_defaults_unknown_on_unmapped() -> None:
    assert failure_code_for_zai("not-a-real-class") is FailureCode.UNKNOWN


def test_structured_allowlists_are_covered_by_code_map_or_fallback_ladder() -> None:
    """SYNC GUARD (a TEST, never an import-time assert — a bare assert vs the code-map alone would be
    FALSE because provider_error is fallback-only, and would brick `import review_team`). Every class
    in the structured allowlists is produced somewhere (code table OR fallback ladder)."""
    code_map_classes = {v[0] for v in ZAI_ERROR_CLASS_BY_CODE.values()}
    producible = code_map_classes | FALLBACK_LADDER_ERROR_CLASSES
    class_allowlists = STRUCTURED_QUOTA_ERROR_CLASSES | STRUCTURED_PROVIDER_OUTAGE_ERROR_CLASSES
    missing = class_allowlists - producible
    assert not missing, f"structured allowlist classes not producible anywhere: {sorted(missing)}"


def test_quota_and_provider_outage_allowlists_are_disjoint() -> None:
    """The QUOTA and PROVIDER_OUTAGE class buckets must not overlap — a class in both would make
    is_quota_wall and is_provider_outage fight over the same signal and the dispatch verdict ambiguous."""
    assert STRUCTURED_QUOTA_ERROR_CLASSES.isdisjoint(STRUCTURED_PROVIDER_OUTAGE_ERROR_CLASSES)


def test_zai_table_has_twenty_one_entries() -> None:
    # the verbatim table sourced from hapax-glmcp-reviewer (21 codes); guards an accidental edit
    assert len(ZAI_ERROR_CLASS_BY_CODE) == 21


def test_action_allowlists_are_nonempty_frozensets() -> None:
    assert STRUCTURED_QUOTA_ACTIONS and STRUCTURED_PROVIDER_OUTAGE_ACTIONS
    assert isinstance(STRUCTURED_QUOTA_ACTIONS, frozenset)
