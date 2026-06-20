"""Tests for the HKP -> Alliant bridge adapter (PR-C)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from shared.evidence_ledger import (
    HkpBridgeRefusal,
    build_hkp_determination_packet,
    collect_hkp_evidence,
    validate_determination_exchange_packet,
)


def _concept(
    *,
    concept_uid: str = "hkp:cc-task:example",
    ctype: str = "cc_task",
    title: str = "Example governance primitive",
    description: str = "A portable, non-authoritative projection.",
    rights_state: str = "operator_controlled",
    privacy_class: str = "internal",
    egress_state: str = "private",
    may_authorize: bool = False,
    freshness: str = "fresh",
    producer: str = "hapax-hkp-exporter",
) -> SimpleNamespace:
    """A duck-typed HKP concept (the adapter type hint is TYPE_CHECKING-only)."""
    return SimpleNamespace(
        concept_uid=concept_uid,
        type=ctype,
        title=title,
        description=description,
        posture=SimpleNamespace(
            rights_state=rights_state,
            privacy_class=privacy_class,
            egress_state=egress_state,
        ),
        authority=SimpleNamespace(may_authorize=may_authorize),
        freshness=SimpleNamespace(state=freshness),
        projection_provenance=SimpleNamespace(producer=producer),
    )


def test_internal_concept_drops_title_and_is_not_public_safe() -> None:
    rec = collect_hkp_evidence(_concept(privacy_class="internal", egress_state="private"))
    assert rec.kind == "hkp_projection"
    assert not rec.public_safe
    assert rec.privacy_class == "operator_private"
    assert "concept_uid=hkp:cc-task:example" in rec.value_summary
    assert "Example governance primitive" not in rec.value_summary
    assert "may_authorize:False" in rec.value_summary


def test_public_concept_includes_title_and_is_public_safe() -> None:
    rec = collect_hkp_evidence(_concept(privacy_class="public", egress_state="public"))
    assert rec.public_safe
    assert rec.privacy_class == "public"
    assert "title=Example governance primitive" in rec.value_summary


def test_collect_refuses_non_operator_controlled() -> None:
    with pytest.raises(HkpBridgeRefusal):
        collect_hkp_evidence(_concept(rights_state="third_party"))


def test_collect_refuses_authority_claim() -> None:
    with pytest.raises(HkpBridgeRefusal):
        collect_hkp_evidence(_concept(may_authorize=True))


def test_build_packet_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Jane Q. Operator")
    packet = build_hkp_determination_packet(
        [_concept(), _concept(concept_uid="hkp:cc-task:two")],
        reviewer="operator",
        reviewed_at="2026-06-20T00:00:00Z",
        purpose="Pilot: share an HKP SDLC projection digest with Alliant.",
        portability_ledger_ref="hkp/13",
    )
    assert packet.from_system == "hapax"
    assert packet.to_system == "alliant_sandbox"
    assert validate_determination_exchange_packet(packet).allowed


def test_build_packet_requires_ledger_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Jane Q. Operator")
    with pytest.raises(HkpBridgeRefusal):
        build_hkp_determination_packet(
            [_concept()],
            reviewer="operator",
            reviewed_at="2026-06-20T00:00:00Z",
            purpose="x",
            portability_ledger_ref="",
        )


def test_build_packet_requires_legal_name_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HAPAX_OPERATOR_NAME", raising=False)
    with pytest.raises(HkpBridgeRefusal):
        build_hkp_determination_packet(
            [_concept()],
            reviewer="operator",
            reviewed_at="2026-06-20T00:00:00Z",
            purpose="x",
            portability_ledger_ref="hkp/13",
        )


def test_build_packet_blocks_pii_in_public_title(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Jane Q. Operator")
    leaky = _concept(
        privacy_class="public", egress_state="public", title="contact devops@example.org"
    )
    with pytest.raises(HkpBridgeRefusal):
        build_hkp_determination_packet(
            [leaky],
            reviewer="operator",
            reviewed_at="2026-06-20T00:00:00Z",
            purpose="x",
            portability_ledger_ref="hkp/13",
        )


def test_build_packet_blocks_operator_mental_state_in_public_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Jane Q. Operator")
    affect = _concept(
        privacy_class="public", egress_state="public", title="the operator was overwhelmed here"
    )
    with pytest.raises(HkpBridgeRefusal):
        build_hkp_determination_packet(
            [affect],
            reviewer="operator",
            reviewed_at="2026-06-20T00:00:00Z",
            purpose="x",
            portability_ledger_ref="hkp/13",
        )


def test_public_concept_content_crosses_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    # Positive cross path: a clean public title/description IS allowed across and
    # appears in the packet's evidence_summaries (the review flagged the absence
    # of a positive content-crossing assertion).
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Jane Q. Operator")
    concept = _concept(
        privacy_class="public",
        egress_state="public",
        title="Portable governance primitive",
        description="A reusable, non-authoritative adoption pattern.",
    )
    packet = build_hkp_determination_packet(
        [concept],
        reviewer="operator",
        reviewed_at="2026-06-20T00:00:00Z",
        purpose="Pilot: share a public HKP capability.",
        portability_ledger_ref="hkp/13",
    )
    assert validate_determination_exchange_packet(packet).allowed
    assert any("Portable governance primitive" in s for s in packet.evidence_summaries)


def test_collect_non_fresh_freshness_marks_failed() -> None:
    assert collect_hkp_evidence(_concept(freshness="missing")).status == "failed"
    assert collect_hkp_evidence(_concept(freshness="stale")).status == "ok"
    assert collect_hkp_evidence(_concept(freshness="fresh")).status == "ok"


def test_collect_refuses_public_export_concept() -> None:
    concept = _concept()
    concept.posture.public_export_allowed = True
    with pytest.raises(HkpBridgeRefusal):
        collect_hkp_evidence(concept)


def test_claim_gate_is_load_bearing_distinct_from_packet_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Defense-in-depth proof (review finding): the ClaimRecord enterprise-audience
    # gate catches an enterprise-forbidden inference ("certified") that the
    # determination-packet content scan does NOT — so the gate is load-bearing,
    # not a no-op duplicating the packet validator. The refusal must come from the
    # claim-audience layer.
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Jane Q. Operator")
    concept = _concept(
        privacy_class="public",
        egress_state="public",
        title="certified production-ready by the enterprise",
    )
    with pytest.raises(HkpBridgeRefusal) as exc:
        build_hkp_determination_packet(
            [concept],
            reviewer="operator",
            reviewed_at="2026-06-20T00:00:00Z",
            purpose="x",
            portability_ledger_ref="hkp/13",
        )
    assert "enterprise-audience validation" in str(exc.value)
