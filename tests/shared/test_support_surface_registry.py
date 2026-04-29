"""Tests for the support surface registry model."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError

from shared.support_surface_registry import (
    REQUIRED_REFUSAL_CONVERSIONS,
    REQUIRED_SURFACE_IDS,
    SupportReceiptEvent,
    build_aggregate_receipt_projection,
    load_support_surface_registry,
    public_prompt_allowed,
    surfaces_by_decision,
)


def test_registry_loads_required_surfaces() -> None:
    registry = load_support_surface_registry()
    surfaces = registry.by_id()

    assert set(surfaces) >= REQUIRED_SURFACE_IDS
    assert {surface.surface_id for surface in surfaces_by_decision(registry, "allowed")} == {
        "liberapay_recurring",
        "lightning_invoice_receive",
        "nostr_zaps",
    }
    assert {
        surface.surface_id for surface in surfaces_by_decision(registry, "refusal_conversion")
    } >= REQUIRED_REFUSAL_CONVERSIONS


def test_no_perk_support_doctrine_is_explicit() -> None:
    registry = load_support_surface_registry()
    doctrine = registry.no_perk_support_doctrine

    assert doctrine.support_buys_access is False
    assert doctrine.support_buys_requests is False
    assert doctrine.support_buys_private_advice is False
    assert doctrine.support_buys_priority is False
    assert doctrine.support_buys_shoutouts is False
    assert doctrine.support_buys_guarantees is False
    assert doctrine.support_buys_client_service is False
    assert doctrine.support_buys_deliverables is False
    assert doctrine.support_buys_control is False
    assert doctrine.work_continues_regardless is True

    copy = " ".join(doctrine.allowed_copy_clauses)
    assert "No access, requests, private advice" in copy
    assert "Work continues regardless" in copy


def test_all_active_surfaces_require_no_perk_and_aggregate_receipts() -> None:
    registry = load_support_surface_registry()

    for surface in registry.surfaces:
        assert surface.no_perk_required is True
        assert surface.aggregate_only_receipts is True
        if surface.decision != "refusal_conversion":
            assert surface.allowed_public_copy
            assert surface.buildable_conversion is None


def test_required_refusal_conversions_are_closed_to_public_prompts() -> None:
    registry = load_support_surface_registry()
    readiness = {
        "MonetizationReadiness.safe_to_monetize": True,
        "support_surface_registry.no_perk_copy_valid": True,
        "payment_aggregator_v2.aggregate_only_projection": True,
    }

    for surface_id in REQUIRED_REFUSAL_CONVERSIONS:
        surface = registry.by_id()[surface_id]
        assert surface.refusal_brief_refs
        assert surface.buildable_conversion
        assert public_prompt_allowed(registry, surface_id, readiness) is False


def test_public_prompt_gate_fails_closed_until_all_readiness_refs_are_true() -> None:
    registry = load_support_surface_registry()
    surface = registry.by_id()["youtube_supers"]

    assert public_prompt_allowed(registry, surface.surface_id, {}) is False
    partial = {gate: True for gate in surface.readiness_gates[:-1]}
    assert public_prompt_allowed(registry, surface.surface_id, partial) is False
    complete = {gate: True for gate in surface.readiness_gates}
    assert public_prompt_allowed(registry, surface.surface_id, complete) is True


def test_aggregate_receipt_projection_contains_no_per_receipt_state() -> None:
    registry = load_support_surface_registry()
    events = [
        SupportReceiptEvent(
            surface_id="lightning_invoice_receive",
            rail="lightning",
            currency="USD",
            amount=5.0,
            occurred_at=datetime(2026, 4, 29, 13, 0, tzinfo=UTC),
        ),
        SupportReceiptEvent(
            surface_id="liberapay_recurring",
            rail="liberapay",
            currency="USD",
            amount=7.0,
            occurred_at=datetime(2026, 4, 29, 14, 0, tzinfo=UTC),
        ),
    ]

    projection = build_aggregate_receipt_projection(
        registry,
        events,
        readiness_state="safe_to_accept_payment",
    )

    assert projection.receipt_count == 2
    assert projection.gross_amount_by_currency == {"USD": 12.0}
    assert projection.rail_counts == {"lightning": 1, "liberapay": 1}
    assert projection.surface_counts == {
        "lightning_invoice_receive": 1,
        "liberapay_recurring": 1,
    }
    assert projection.public_state_aggregate_only is True
    assert projection.per_receipt_public_state_allowed is False
    public_dump = projection.model_dump()
    for forbidden in (
        "identity",
        "handle",
        "email",
        "comment_text",
        "message_text",
        "per_receipt_history",
        "supporter_list",
        "leaderboard",
    ):
        assert forbidden not in public_dump


def test_receipt_events_reject_identity_and_comment_fields() -> None:
    try:
        SupportReceiptEvent.model_validate(
            {
                "surface_id": "nostr_zaps",
                "rail": "nostr",
                "currency": "USD",
                "amount": 1.0,
                "occurred_at": "2026-04-29T13:00:00Z",
                "handle": "not allowed",
                "message_text": "not allowed",
            }
        )
    except ValidationError as exc:
        assert "handle" in str(exc)
        assert "message_text" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("receipt identity/comment fields should be rejected")


def test_refused_surfaces_cannot_emit_support_receipts() -> None:
    registry = load_support_surface_registry()
    event = SupportReceiptEvent(
        surface_id="patreon",
        rail="patreon",
        currency="USD",
        amount=10.0,
        occurred_at=datetime(2026, 4, 29, 13, 0, tzinfo=UTC),
    )

    try:
        build_aggregate_receipt_projection(registry, [event])
    except ValueError as exc:
        assert "patreon is refused" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("refused support surface should not emit receipts")
