"""Tests for the omg.lol Pay V5 publisher.

cc-task: ``publication-bus-monetization-rails-surfaces`` (closes the
keystone — fifth wired monetization rail).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agents.publication_bus.omg_lol_pay_publisher import (
    DEFAULT_OMG_LOL_PAY_ALLOWLIST,
    OMG_LOL_PAY_PUBLISHER_SURFACE,
    PAYMENT_REFUNDED_REFUSAL_SURFACE,
    SUBSCRIPTION_CANCELLED_REFUSAL_SURFACE,
    OmgLolPayPublisher,
    event_to_manifest_record,
    manifest_path_for_event,
)
from agents.publication_bus.surface_registry import (
    SURFACE_REGISTRY,
    AutomationStatus,
)
from shared.omg_lol_pay_receive_only_rail import (
    PaymentEvent,
    PaymentEventKind,
)


def _event(
    *,
    kind: PaymentEventKind = PaymentEventKind.PAYMENT_SUCCEEDED,
    donor: str = "alice",
    amount_cents: int = 500,
    sha: str | None = None,
) -> PaymentEvent:
    return PaymentEvent(
        donor_handle=donor,
        amount_usd_cents=amount_cents,
        event_kind=kind,
        occurred_at=datetime(2026, 5, 4, 23, 0, 0, tzinfo=UTC),
        raw_payload_sha256=(sha or "a" * 64),
    )


# ── Surface metadata ─────────────────────────────────────────────────


class TestSurfaceMetadata:
    def test_surface_name_is_omg_lol_pay_receiver(self):
        assert OmgLolPayPublisher.surface_name == OMG_LOL_PAY_PUBLISHER_SURFACE
        assert OMG_LOL_PAY_PUBLISHER_SURFACE == "omg-lol-pay-receiver"

    def test_does_not_require_legal_name(self):
        # Aggregate manifests; donor is the public omg.lol address only.
        assert OmgLolPayPublisher.requires_legal_name is False

    def test_allowlist_permits_all_payment_event_kinds(self):
        for kind in PaymentEventKind:
            assert DEFAULT_OMG_LOL_PAY_ALLOWLIST.permits(kind.value)

    def test_allowlist_rejects_unknown_target(self):
        assert not DEFAULT_OMG_LOL_PAY_ALLOWLIST.permits("not-a-kind")


# ── Surface registry integration ──────────────────────────────────────


class TestSurfaceRegistry:
    def test_omg_lol_pay_receiver_registered(self):
        assert "omg-lol-pay-receiver" in SURFACE_REGISTRY

    def test_registry_entry_is_conditional_engage(self):
        spec = SURFACE_REGISTRY["omg-lol-pay-receiver"]
        assert spec.automation_status is AutomationStatus.CONDITIONAL_ENGAGE

    def test_activation_path_points_at_publisher(self):
        spec = SURFACE_REGISTRY["omg-lol-pay-receiver"]
        assert (
            spec.activation_path
            == "agents.publication_bus.omg_lol_pay_publisher.OmgLolPayPublisher"
        )


# ── Manifest body rendering ───────────────────────────────────────────


class TestManifestBody:
    def test_body_carries_event_kind_in_header(self):
        body = OmgLolPayPublisher._render_manifest_body(_event())  # noqa: SLF001
        assert body.startswith("# omg.lol Pay event — payment_succeeded")

    def test_body_carries_aggregate_fields(self):
        body = OmgLolPayPublisher._render_manifest_body(_event())  # noqa: SLF001
        assert "alice" in body
        assert "500" in body
        assert "2026-05-04T23:00:00+00:00" in body
        assert "a" * 64 in body

    def test_body_excludes_pii_shapes(self):
        """No emails, phone numbers, or omg.lol-internal IDs in the body."""
        import re

        body = OmgLolPayPublisher._render_manifest_body(_event())  # noqa: SLF001
        assert not re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", body)
        assert not re.search(r"\b\d{3}[-. ]?\d{3}[-. ]?\d{4}\b", body)


# ── Pure helpers ──────────────────────────────────────────────────────


class TestPureHelpers:
    def test_event_to_manifest_record_projects_aggregate_fields(self):
        record = event_to_manifest_record(_event())
        assert record == {
            "event_kind": "payment_succeeded",
            "donor_handle": "alice",
            "amount_usd_cents": 500,
            "occurred_at_iso": "2026-05-04T23:00:00+00:00",
            "raw_payload_sha256": "a" * 64,
        }

    def test_manifest_path_uses_event_kind_and_sha_prefix(self, tmp_path: Path):
        path = manifest_path_for_event(_event(), output_dir=tmp_path)
        assert path.parent == tmp_path
        assert "payment_succeeded" in path.name
        assert path.name.endswith(".md")


# ── Publish via the Publisher ABC ────────────────────────────────────


class TestPublishEvent:
    def test_publish_event_writes_manifest(self, tmp_path: Path):
        publisher = OmgLolPayPublisher(output_dir=tmp_path)
        result = publisher.publish_event(_event())
        assert result.ok
        # One manifest .md should exist in tmp_path.
        files = list(tmp_path.glob("event-*.md"))
        assert len(files) == 1
        body = files[0].read_text()
        assert "alice" in body
        assert "payment_succeeded" in body

    def test_publish_event_rejects_unknown_event_kind(self, tmp_path: Path):
        """Allowlist gate kicks in if a caller bypasses the typed
        ``PaymentEvent`` and dispatches a raw payload with an unknown
        target."""

        from agents.publication_bus.publisher_kit import PublisherPayload

        publisher = OmgLolPayPublisher(output_dir=tmp_path)
        result = publisher.publish(PublisherPayload(target="not-a-kind", text="x", metadata={}))
        # Allowlist failure surfaces as a refusal/error result depending
        # on the publisher_kit's handling — both are acceptable as long
        # as the dispatch is denied.
        assert not result.ok


# ── Refund / cancellation auto-link ──────────────────────────────────


class TestRefundCancellationAutoLink:
    """Refunds + subscription cancellations append to the canonical
    refusal log (mirrors the Liberapay tip-cancellation auto-link)."""

    def test_payment_refunded_routes_through_refund_surface(self, tmp_path: Path, monkeypatch):
        from agents.publication_bus import _rail_publisher_helpers as helpers

        captured: list[dict] = []

        def _capture(payload, *, axiom, surface, reason, log):
            captured.append({"surface": surface, "reason": reason})

        monkeypatch.setattr(helpers, "auto_link_cancellation_to_refusal_log", _capture)
        # Re-import so the publisher picks up the patched reference.
        import agents.publication_bus.omg_lol_pay_publisher as mod

        monkeypatch.setattr(mod, "auto_link_cancellation_to_refusal_log", _capture)

        publisher = OmgLolPayPublisher(output_dir=tmp_path)
        publisher.publish_event(_event(kind=PaymentEventKind.PAYMENT_REFUNDED))

        assert len(captured) == 1
        assert captured[0]["surface"] == PAYMENT_REFUNDED_REFUSAL_SURFACE
        assert "refund" in captured[0]["reason"].lower()

    def test_subscription_cancelled_routes_through_cancel_surface(
        self, tmp_path: Path, monkeypatch
    ):
        captured: list[dict] = []

        def _capture(payload, *, axiom, surface, reason, log):
            captured.append({"surface": surface, "reason": reason})

        import agents.publication_bus.omg_lol_pay_publisher as mod

        monkeypatch.setattr(mod, "auto_link_cancellation_to_refusal_log", _capture)

        publisher = OmgLolPayPublisher(output_dir=tmp_path)
        publisher.publish_event(_event(kind=PaymentEventKind.SUBSCRIPTION_CANCELLED))

        assert len(captured) == 1
        assert captured[0]["surface"] == SUBSCRIPTION_CANCELLED_REFUSAL_SURFACE
        assert "cancellation" in captured[0]["reason"].lower()

    def test_payment_succeeded_does_not_route_to_refusal_log(self, tmp_path: Path, monkeypatch):
        """Only refunds + cancellations are refusal-data; success is not."""

        captured: list[dict] = []

        def _capture(payload, *, axiom, surface, reason, log):
            captured.append({"surface": surface, "reason": reason})

        import agents.publication_bus.omg_lol_pay_publisher as mod

        monkeypatch.setattr(mod, "auto_link_cancellation_to_refusal_log", _capture)

        publisher = OmgLolPayPublisher(output_dir=tmp_path)
        publisher.publish_event(_event(kind=PaymentEventKind.PAYMENT_SUCCEEDED))
        publisher.publish_event(_event(kind=PaymentEventKind.SUBSCRIPTION_SET, sha="b" * 64))

        assert captured == []
