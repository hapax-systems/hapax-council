"""Tests for the MonDLC G2 legal venue gate."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from shared.capdlc_lifecycle import GateResult, GateStatus
from shared.legal_posture_registry import G2GateInput, LegalPostureRegistry
from shared.mdlc_g2_legal import (
    MONDLC_G2_LEGAL_NAME,
    MONDLC_G2_LEGAL_VERSION,
    G2LegalRefusal,
    G2LegalRefusalReason,
    G2LegalVerification,
    require_g2_legal,
    verify_g2_legal,
)

TODAY = date(2026, 7, 1)
TARGET = G2GateInput(
    surface="bug_bounty",
    venue="hackerone",
    instrument="universal_jailbreak_bounty",
)


def _row(
    *,
    surface: str = TARGET.surface,
    venue: str = TARGET.venue,
    instrument: str = TARGET.instrument,
    verdict: str = "DARK",
    review_date: str = "2026-07-01",
    ttl: int = 90,
    operator_signed: bool = False,
    open_questions: list[str] | None = None,
    authority_basis: str | None = None,
    source_task: str = "20260628-registry-phase7-mdlc-g2-gate-wire",
) -> dict[str, Any]:
    return {
        "surface": surface,
        "venue": venue,
        "instrument": instrument,
        "g2_verdict": verdict,
        "citation": "test fixture citation",
        "authority_basis": authority_basis
        or ("legal_opinion" if verdict != "DARK" else "no_research"),
        "review_date": review_date,
        "freshness_ttl_days": ttl,
        "operator_signed": operator_signed,
        "operator_sign_date": "2026-07-01" if operator_signed else None,
        "notes": "fixture row",
        "open_questions": open_questions or [],
        "blocks_surfaces": [surface],
        "source_task": source_task,
    }


def _registry(*rows: dict[str, Any]) -> LegalPostureRegistry:
    return LegalPostureRegistry.from_mapping(
        {
            "schema_version": "1.0.0",
            "schema_doc": "docs/monetization/legal-posture-registry-schema.md",
            "rows": list(rows),
        }
    )


def test_g2_missing_target_refuses_before_commit() -> None:
    result = verify_g2_legal(None, registry=_registry(), today=TODAY)

    assert result.status is GateStatus.DARK
    assert result.ok is False
    assert result.refusal_reason is G2LegalRefusalReason.MISSING_TARGET
    assert result.gate_result.verdict is None
    assert result.next_action == "attach a surface, venue, and instrument target before M2 commit"


@pytest.mark.parametrize(
    "target",
    (
        object(),
        {"surface": "", "venue": TARGET.venue, "instrument": TARGET.instrument},
        {"surface": TARGET.surface, "venue": None, "instrument": TARGET.instrument},
        {"surface": TARGET.surface, "venue": TARGET.venue, "instrument": " "},
    ),
)
def test_g2_invalid_target_refuses_before_commit(target: object) -> None:
    result = verify_g2_legal(target, registry=_registry(), today=TODAY)  # type: ignore[arg-type]

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G2LegalRefusalReason.INVALID_TARGET
    assert result.row is None


def test_g2_verification_truthiness_is_not_allowed() -> None:
    result = verify_g2_legal(TARGET, registry=_registry(_row()), today=TODAY)

    with pytest.raises(TypeError, match="truthiness is undefined"):
        bool(result)


def test_g2_no_exact_row_blocks_commit() -> None:
    result = verify_g2_legal(TARGET, registry=_registry(), today=TODAY)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G2LegalRefusalReason.NO_EXACT_ROW
    assert result.target == TARGET
    assert result.row is None


def test_g2_dark_row_blocks_commit() -> None:
    result = verify_g2_legal(TARGET, registry=_registry(_row()), today=TODAY)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G2LegalRefusalReason.DARK_ROW
    assert result.row is not None
    assert result.row.instrument == TARGET.instrument
    assert f"legal-posture-row:{TARGET.surface}:{TARGET.venue}:{TARGET.instrument}" in (
        result.evidence_refs
    )


def test_g2_partial_row_blocks_commit() -> None:
    result = verify_g2_legal(
        TARGET,
        registry=_registry(_row(verdict="PARTIAL", operator_signed=True)),
        today=TODAY,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G2LegalRefusalReason.PARTIAL_NOT_COMMITTABLE


def test_g2_stale_lit_row_blocks_commit() -> None:
    result = verify_g2_legal(
        TARGET,
        registry=_registry(
            _row(verdict="LIT", review_date="2026-01-01", ttl=30, operator_signed=True)
        ),
        today=TODAY,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G2LegalRefusalReason.STALE_NON_DARK
    assert result.stale is True


def test_g2_unsigned_non_dark_row_blocks_commit() -> None:
    result = verify_g2_legal(
        TARGET,
        registry=_registry(_row(verdict="LIT", operator_signed=False)),
        today=TODAY,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G2LegalRefusalReason.UNSIGNED_NON_DARK


@pytest.mark.parametrize("authority_basis", ["no_research", "operator_judgment"])
def test_g2_weak_lit_authority_blocks_commit(authority_basis: str) -> None:
    result = verify_g2_legal(
        TARGET,
        registry=_registry(
            _row(verdict="LIT", operator_signed=True, authority_basis=authority_basis)
        ),
        today=TODAY,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G2LegalRefusalReason.LIT_AUTHORITY_NOT_COMMITTABLE


def test_g2_lit_row_with_open_questions_blocks_commit() -> None:
    result = verify_g2_legal(
        TARGET,
        registry=_registry(
            _row(
                verdict="LIT",
                operator_signed=True,
                open_questions=["operator signature scope unresolved"],
            )
        ),
        today=TODAY,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G2LegalRefusalReason.LIT_HAS_OPEN_QUESTIONS


def test_g2_fresh_lit_row_admits_only_named_tuple() -> None:
    registry = _registry(_row(verdict="LIT", operator_signed=True))

    exact = verify_g2_legal(TARGET, registry=registry, today=TODAY)
    other_surface = verify_g2_legal(
        G2GateInput("prediction_market", TARGET.venue, TARGET.instrument),
        registry=registry,
        today=TODAY,
    )
    other_venue = verify_g2_legal(
        G2GateInput(TARGET.surface, "anthropic", TARGET.instrument),
        registry=registry,
        today=TODAY,
    )
    other_instrument = verify_g2_legal(
        G2GateInput(TARGET.surface, TARGET.venue, "brokered_vulnerability_resale"),
        registry=registry,
        today=TODAY,
    )

    assert exact.status is GateStatus.LIT
    assert exact.ok is True
    assert exact.refusal_reason is None
    assert exact.gate_result.verdict is True
    assert {
        other_surface.refusal_reason,
        other_venue.refusal_reason,
        other_instrument.refusal_reason,
    } == {G2LegalRefusalReason.NO_EXACT_ROW}


def test_require_g2_success_returns_exact_row() -> None:
    row = require_g2_legal(
        TARGET,
        registry=_registry(_row(verdict="LIT", operator_signed=True)),
        today=TODAY,
    )

    assert row.key == TARGET.key
    assert row.operator_signed is True


def test_require_g2_refusal_carries_verification() -> None:
    with pytest.raises(G2LegalRefusal) as exc_info:
        require_g2_legal(TARGET, registry=_registry(_row()), today=TODAY)

    assert exc_info.value.verification.refusal_reason is G2LegalRefusalReason.DARK_ROW


def test_g2_mapping_ignores_g1_counterparty_and_m_measurement_fields() -> None:
    target = {
        "surface": TARGET.surface,
        "venue": TARGET.venue,
        "instrument": TARGET.instrument,
        "counterparty_class": "retail_person",
        "measurement_value": None,
        "ruler_hash": "",
    }

    result = verify_g2_legal(
        target,
        registry=_registry(_row(verdict="LIT", operator_signed=True)),
        today=TODAY,
    )

    assert result.status is GateStatus.LIT
    assert result.target == TARGET
    assert set(G2GateInput.__dataclass_fields__) == {"surface", "venue", "instrument"}


def test_g2_to_dict_records_exact_row_and_gate_result() -> None:
    result = verify_g2_legal(
        TARGET,
        registry=_registry(_row(verdict="LIT", operator_signed=True)),
        today=TODAY,
    )

    payload = result.to_dict()

    assert payload["status"] == "lit"
    assert payload["target"] == {
        "surface": TARGET.surface,
        "venue": TARGET.venue,
        "instrument": TARGET.instrument,
    }
    assert payload["row"]["g2_verdict"] == "LIT"
    assert payload["gate_result"]["verdict"] is True


def test_g2_to_dict_records_unsigned_dark_row_without_operator_sign_date() -> None:
    result = verify_g2_legal(TARGET, registry=_registry(_row()), today=TODAY)

    payload = result.to_dict()

    assert payload["status"] == "dark"
    assert payload["row"]["g2_verdict"] == "DARK"
    assert payload["row"]["operator_sign_date"] is None
    assert payload["gate_result"]["verdict"] is None


@pytest.mark.parametrize(
    "overrides",
    (
        {"status": "lit"},
        {"gate_result": object()},
        {"refusal_reason": "dark_row"},
        {"target": object()},
    ),
)
def test_g2_verification_rejects_malformed_direct_fields(
    overrides: dict[str, object],
) -> None:
    kwargs: dict[str, object] = {
        "validator": MONDLC_G2_LEGAL_NAME,
        "validator_version": MONDLC_G2_LEGAL_VERSION,
        "status": GateStatus.DARK,
        "gate_result": GateResult(status=GateStatus.DARK, verdict=None),
        "reason": "dark_row",
        "refusal_reason": G2LegalRefusalReason.DARK_ROW,
        "target": TARGET,
    }
    kwargs.update(overrides)

    with pytest.raises(TypeError):
        G2LegalVerification(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "evidence_refs",
    (
        "legal-posture-row:bug_bounty:hackerone:universal_jailbreak_bounty",
        ["legal-posture-row:bug_bounty:hackerone:universal_jailbreak_bounty"],
        ("legal-posture-row:bug_bounty:hackerone:universal_jailbreak_bounty", object()),
        (" ",),
    ),
)
def test_g2_verification_rejects_malformed_direct_evidence_refs(
    evidence_refs: object,
) -> None:
    with pytest.raises(TypeError, match="evidence refs"):
        G2LegalVerification(
            validator=MONDLC_G2_LEGAL_NAME,
            validator_version=MONDLC_G2_LEGAL_VERSION,
            status=GateStatus.DARK,
            gate_result=GateResult(status=GateStatus.DARK, verdict=None),
            reason="dark_row",
            refusal_reason=G2LegalRefusalReason.DARK_ROW,
            target=TARGET,
            evidence_refs=evidence_refs,  # type: ignore[arg-type]
        )


def test_g2_missing_registry_file_fails_closed(tmp_path: Path) -> None:
    result = verify_g2_legal(
        TARGET,
        registry_path=tmp_path / "missing-registry.yaml",
        today=TODAY,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is G2LegalRefusalReason.REGISTRY_UNREADABLE


def test_default_registry_blocks_minnesota_trading_and_keeps_ndcvb_distinct() -> None:
    trading = verify_g2_legal(
        G2GateInput(
            "prediction_market",
            "US-MN",
            "operator_prediction_market_trading",
        ),
        today=date(2026, 6, 30),
    )
    ndcvb = verify_g2_legal(
        G2GateInput(
            "prediction_market",
            "US-MN",
            "ndcvb_manipulation_detection_feed_non_trading",
        ),
        today=date(2026, 6, 30),
    )

    assert trading.status is GateStatus.DARK
    assert trading.refusal_reason is G2LegalRefusalReason.DARK_ROW
    assert trading.row is not None
    assert trading.row.instrument == "operator_prediction_market_trading"
    assert "automated_prediction_market_trading" in trading.row.blocks_surfaces

    assert ndcvb.status is GateStatus.DARK
    assert ndcvb.refusal_reason is G2LegalRefusalReason.DARK_ROW
    assert ndcvb.row is not None
    assert ndcvb.row.instrument == "ndcvb_manipulation_detection_feed_non_trading"
    assert ndcvb.row.instrument != trading.row.instrument
    assert "not a wager" in ndcvb.row.notes
    assert "REQ-ndcvb-as-a-service" in ndcvb.row.blocks_surfaces
