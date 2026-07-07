"""Tests for the grounding-providers ingestion adapter (producer layer slice 5)."""

from __future__ import annotations

import unittest
from pathlib import Path

from shared.capability_harness_descriptor import (
    CapabilityDomain,
    CapabilityShape,
    CostSource,
)
from shared.grounding_provider_ingest import (
    ingest_grounding_provider_routes,
    ingest_grounding_providers,
)

_FIXTURE = [
    {
        "provider_id": "local_command_r_tabbyapi",
        "adapter_id": "local_command_r_tabbyapi",
        "provider_family": "cohere_command_r_local_tabbyapi",
        "provider_kind": "source_conditioned",
        "model_id": "command-r-08-2024-exl3-5.0bpw",
        "cloud_route": False,
        "requires_supplied_evidence": True,
    },
    {
        "provider_id": "cloud_gemini_pro",
        "provider_family": "google_gemini_cloud",
        "model_id": "gemini-3-pro-preview",
        "cloud_route": True,
        "requires_supplied_evidence": False,
    },
]


class GroundingProviderIngestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.descs = {d.capability_id: d for d in ingest_grounding_provider_routes(_FIXTURE)}

    def test_local_tabbyapi_maps_to_raw_model(self) -> None:
        d = self.descs["local_command_r_tabbyapi"]
        self.assertEqual(d.shape, CapabilityShape.RAW_MODEL)
        self.assertEqual(d.domain, CapabilityDomain.LOCAL_COMPUTE)
        self.assertEqual(d.backend, "tabbyapi")

    def test_cloud_maps_to_hosted_model(self) -> None:
        d = self.descs["cloud_gemini_pro"]
        self.assertEqual(d.shape, CapabilityShape.HOSTED_MODEL)
        self.assertTrue(d.spend_authority_required)
        self.assertEqual(d.cost_source, CostSource.PROVIDER)

    def test_requires_evidence_adds_ground_action(self) -> None:
        from shared.capability_harness_descriptor import CapabilityAction

        d = self.descs["local_command_r_tabbyapi"]
        self.assertIn(CapabilityAction.GROUND, d.actions)  # type: ignore[attr-defined]

    def test_local_has_no_spend(self) -> None:
        d = self.descs["local_command_r_tabbyapi"]
        self.assertFalse(d.spend_authority_required)


class GroundingProviderSmokeTest(unittest.TestCase):
    def test_ingests_real_grounding_providers(self) -> None:
        config = Path(__file__).resolve().parent.parent / "config" / "grounding-providers.json"
        if not config.is_file():
            self.skipTest(f"{config} not present")
        descs = ingest_grounding_providers(config)
        self.assertGreater(len(descs), 0)


if __name__ == "__main__":
    unittest.main()
