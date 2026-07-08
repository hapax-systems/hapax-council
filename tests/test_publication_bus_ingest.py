"""Tests for the publication-bus surface_registry ingestion adapter (producer layer slice 9)."""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from agents.publication_bus.surface_registry import AutomationStatus
from shared.capability_harness_descriptor import (
    AuthorityCeiling,
    CapabilityAction,
    CapabilityDomain,
    CapabilityShape,
    FreshnessState,
)
from shared.publication_bus_ingest import ingest_publication_bus_surfaces


@dataclass(frozen=True)
class _FakeSpec:
    automation_status: object
    dispatch_entry: str
    scope_note: str
    api: str = "webhook"


_FIXTURE = {
    "omg-weblog": _FakeSpec(
        AutomationStatus.FULL_AUTO, "agents.omg_weblog_publisher:publish_artifact", "weblog"
    ),
    "github-create-pr": _FakeSpec(
        AutomationStatus.FULL_AUTO, "agents.github_publisher:create", "github PR"
    ),
    "ko-fi-receiver": _FakeSpec(
        AutomationStatus.FULL_AUTO, "agents.ko_fi_publisher:receive", "ko-fi donations"
    ),
    "philarchive-deposit": _FakeSpec(
        AutomationStatus.CONDITIONAL_ENGAGE,
        "agents.philarchive_adapter:publish_artifact",
        "philarchive",
    ),
    "discord-webhook": _FakeSpec(AutomationStatus.REFUSED, "", "discord (refused)"),
    "wise-direct-debit-active-reception": _FakeSpec(
        AutomationStatus.REFUSED, "", "wise direct debit refused"
    ),
}


class PublicationBusIngestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.descs = {d.capability_id: d for d in ingest_publication_bus_surfaces(_FIXTURE)}

    def test_weblog_maps_to_public_egress(self) -> None:
        d = self.descs["publication_bus.omg-weblog"]
        self.assertEqual(d.shape, CapabilityShape.PUBLIC_EGRESS)
        self.assertEqual(d.domain, CapabilityDomain.PUBLICATION)
        self.assertEqual(d.actions, [CapabilityAction.PUBLISH])
        self.assertEqual(d.authority_ceiling, AuthorityCeiling.PUBLIC_PUBLISH)
        self.assertTrue(d.public_egress_authority_required)

    def test_money_receiver_maps_to_money_rail(self) -> None:
        d = self.descs["publication_bus.ko-fi-receiver"]
        self.assertEqual(d.shape, CapabilityShape.MONEY_RAIL)
        self.assertEqual(d.domain, CapabilityDomain.PAYMENT)
        self.assertEqual(d.actions, [CapabilityAction.RECEIVE])
        self.assertEqual(d.authority_ceiling, AuthorityCeiling.RECEIVE_ONLY_MONEY)

    def test_refused_public_surface_maps_to_stale_read_only(self) -> None:
        d = self.descs["publication_bus.discord-webhook"]
        self.assertEqual(d.freshness_state, FreshnessState.STALE)
        self.assertEqual(d.authority_ceiling, AuthorityCeiling.READ_ONLY)
        self.assertEqual(d.actions, [])
        self.assertTrue(d.public_egress_authority_required)

    def test_refused_money_adjacent_surface_maps_to_read_only(self) -> None:
        d = self.descs["publication_bus.wise-direct-debit-active-reception"]
        self.assertEqual(d.shape, CapabilityShape.MONEY_RAIL)
        self.assertEqual(d.domain, CapabilityDomain.PAYMENT)
        self.assertEqual(d.freshness_state, FreshnessState.STALE)
        self.assertEqual(d.authority_ceiling, AuthorityCeiling.READ_ONLY)
        self.assertEqual(d.actions, [])

    def test_full_auto_maps_to_fresh(self) -> None:
        self.assertEqual(
            self.descs["publication_bus.omg-weblog"].freshness_state, FreshnessState.FRESH
        )

    def test_conditional_engage_enum_does_not_match_automation_prefix(self) -> None:
        self.assertEqual(
            self.descs["publication_bus.philarchive-deposit"].freshness_state,
            FreshnessState.DARK,
        )

    def test_dispatch_entry_mapped(self) -> None:
        self.assertEqual(
            self.descs["publication_bus.omg-weblog"].execution_harness_id,
            "agents.omg_weblog_publisher:publish_artifact",
        )

    def test_one_per_surface(self) -> None:
        self.assertEqual(len(self.descs), len(_FIXTURE))


if __name__ == "__main__":
    unittest.main()
