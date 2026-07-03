"""Tests for the classification-inventory ingestion adapter (producer layer slice 7)."""

from __future__ import annotations

import unittest
from pathlib import Path

from shared.capability_harness_descriptor import (
    AuthorityCeiling,
    CapabilityShape,
    FreshnessState,
)
from shared.classification_inventory_ingest import (
    ingest_classification_inventory,
    ingest_classification_routes,
)

_FIXTURE = [
    {
        "row_id": "capability.affordance.env_weather",
        "direction": "observe",
        "recruitable": True,
        "authority_ceiling": "read_only",
        "availability_state": "live",
        "semantic_description": "Sense weather for grounding",
    },
    {
        "row_id": "capability.audio.broadcast_master",
        "direction": "communicate",
        "recruitable": True,
        "authority_ceiling": "public_publish",
        "availability_state": "blocked",
    },
    {
        "row_id": "capability.observation.non_recruitable",
        "direction": "observe",
        "recruitable": False,
    },
]


class ClassificationInventoryIngestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.descs = {d.capability_id: d for d in ingest_classification_routes(_FIXTURE)}

    def test_recruitable_observation_maps_to_background_service(self) -> None:
        d = self.descs["capability.affordance.env_weather"]
        self.assertEqual(d.shape, CapabilityShape.BACKGROUND_SERVICE)
        self.assertEqual(d.freshness_state, FreshnessState.FRESH)

    def test_communicate_maps_to_public_egress(self) -> None:
        d = self.descs["capability.audio.broadcast_master"]
        self.assertEqual(d.shape, CapabilityShape.PUBLIC_EGRESS)
        self.assertEqual(d.authority_ceiling, AuthorityCeiling.PUBLIC_PUBLISH)

    def test_non_recruitable_excluded(self) -> None:
        self.assertNotIn("capability.observation.non_recruitable", self.descs)

    def test_only_recruitable_returned(self) -> None:
        self.assertEqual(len(self.descs), 2)


class ClassificationSmokeTest(unittest.TestCase):
    def test_ingests_real_inventory(self) -> None:
        config = (
            Path(__file__).resolve().parent.parent
            / "config"
            / "capability-classification-inventory.json"
        )
        if not config.is_file():
            self.skipTest(f"{config} not present")
        descs = ingest_classification_inventory(config)
        # some rows should be recruitable
        self.assertGreater(len(descs), 0)


if __name__ == "__main__":
    unittest.main()
