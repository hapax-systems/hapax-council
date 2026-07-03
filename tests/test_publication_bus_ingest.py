"""Tests for the publication-bus surface_registry ingestion adapter (producer layer slice 9)."""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from shared.capability_harness_descriptor import (
    AuthorityCeiling,
    CapabilityDomain,
    CapabilityShape,
    FreshnessState,
)
from shared.publication_bus_ingest import ingest_publication_bus_surfaces


@dataclass(frozen=True)
class _FakeSpec:
    automation_status: str
    dispatch_entry: str
    scope_note: str
    api: str = "webhook"


_FIXTURE = {
    "omg-weblog": _FakeSpec("FULL_AUTO", "agents.omg_weblog_publisher:publish_artifact", "weblog"),
    "github-create-pr": _FakeSpec("FULL_AUTO", "agents.github_publisher:create", "github PR"),
    "ko-fi-receiver": _FakeSpec(
        "CONDITIONAL_ENGAGE", "agents.ko_fi_publisher:receive", "ko-fi donations"
    ),
    "discord-webhook": _FakeSpec("REFUSED", "", "discord (refused)"),
}


class PublicationBusIngestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.descs = {d.capability_id: d for d in ingest_publication_bus_surfaces(_FIXTURE)}

    def test_weblog_maps_to_public_egress(self) -> None:
        d = self.descs["publication_bus.omg-weblog"]
        self.assertEqual(d.shape, CapabilityShape.PUBLIC_EGRESS)
        self.assertEqual(d.domain, CapabilityDomain.PUBLICATION)
        self.assertEqual(d.authority_ceiling, AuthorityCeiling.PUBLIC_PUBLISH)
        self.assertTrue(d.public_egress_authority_required)

    def test_money_receiver_maps_to_money_rail(self) -> None:
        d = self.descs["publication_bus.ko-fi-receiver"]
        self.assertEqual(d.shape, CapabilityShape.MONEY_RAIL)
        self.assertEqual(d.domain, CapabilityDomain.PAYMENT)
        self.assertEqual(d.authority_ceiling, AuthorityCeiling.RECEIVE_ONLY_MONEY)

    def test_refused_maps_to_stale(self) -> None:
        self.assertEqual(
            self.descs["publication_bus.discord-webhook"].freshness_state, FreshnessState.STALE
        )

    def test_full_auto_maps_to_fresh(self) -> None:
        self.assertEqual(
            self.descs["publication_bus.omg-weblog"].freshness_state, FreshnessState.FRESH
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
