"""Tests for the world-capability-registry ingestion adapter (producer layer slice 4)."""

from __future__ import annotations

import unittest
from pathlib import Path

from shared.capability_harness_descriptor import (
    AuthorityCeiling,
    CapabilityDomain,
    CapabilityShape,
    FreshnessState,
)
from shared.world_capability_ingest import (
    ingest_world_capability_registry,
    ingest_world_capability_routes,
)

_FIXTURE = [
    {
        "capability_id": "audio.broadcast_voice",
        "capability_name": "Broadcast voice route",
        "realm": "world_expression",
        "domain": "audio",
        "direction": "communicate",
        "daemon": "hapax-daimonion",
        "authority_ceiling": "public_publish",
        "public_claim_policy": "publish_allowed",
        "availability_state": "live",
    },
    {
        "capability_id": "visual.surface_health",
        "capability_name": "Visual surface health",
        "realm": "world_state",
        "domain": "camera",
        "direction": "observe",
        "daemon": "studio-compositor",
        "authority_ceiling": "read_only",
        "availability_state": "blocked",
    },
    {
        "capability_id": "audio.broadcast_voice_gated",
        "capability_name": "Broadcast voice route gated",
        "realm": "world_expression",
        "domain": "audio",
        "direction": "communicate",
        "daemon": "hapax-daimonion",
        "authority_ceiling": "public_gate_required",
        "public_claim_policy": {"requires_egress_public_claim": True},
        "availability_state": "live",
    },
    {
        "capability_id": "mobile.watch_biometrics",
        "capability_name": "Mobile watch biometrics",
        "realm": "world_state",
        "domain": "mobile_watch",
        "direction": "receive",
        "daemon": "watch-receiver",
        "authority_ceiling": "read_only",
        "health_signal": "healthy",
    },
]


class WorldCapabilityIngestTest(unittest.TestCase):
    """The world-capability-registry record → descriptor mapping."""

    def setUp(self) -> None:
        self.descs = {d.capability_id: d for d in ingest_world_capability_routes(_FIXTURE)}

    def test_audio_expression_maps_to_background_service(self) -> None:
        d = self.descs["audio.broadcast_voice"]
        self.assertEqual(d.shape, CapabilityShape.BACKGROUND_SERVICE)
        self.assertEqual(d.domain, CapabilityDomain.DEVICE)

    def test_public_expression_has_public_publish_authority(self) -> None:
        d = self.descs["audio.broadcast_voice"]
        self.assertEqual(d.authority_ceiling, AuthorityCeiling.PUBLIC_PUBLISH)

    def test_public_gate_required_is_not_granted_public_publish_authority(self) -> None:
        d = self.descs["audio.broadcast_voice_gated"]
        self.assertEqual(d.shape, CapabilityShape.BACKGROUND_SERVICE)
        self.assertEqual(d.authority_ceiling, AuthorityCeiling.READ_ONLY)
        self.assertTrue(d.public_egress_authority_required)

    def test_world_state_maps_to_background_service(self) -> None:
        d = self.descs["visual.surface_health"]
        self.assertEqual(d.shape, CapabilityShape.BACKGROUND_SERVICE)
        self.assertEqual(d.domain, CapabilityDomain.DEVICE)
        self.assertEqual(d.authority_ceiling, AuthorityCeiling.READ_ONLY)

    def test_freshness_from_availability(self) -> None:
        self.assertEqual(self.descs["audio.broadcast_voice"].freshness_state, FreshnessState.FRESH)
        self.assertEqual(self.descs["visual.surface_health"].freshness_state, FreshnessState.STALE)

    def test_daemon_mapped_to_execution_harness(self) -> None:
        self.assertEqual(
            self.descs["audio.broadcast_voice"].execution_harness_id, "hapax-daimonion"
        )

    def test_one_per_record(self) -> None:
        self.assertEqual(len(ingest_world_capability_routes(_FIXTURE)), len(_FIXTURE))


class WorldCapabilityRealSmokeTest(unittest.TestCase):
    """Smoke test: ingest the real config."""

    def test_ingests_real_world_registry(self) -> None:
        config = (
            Path(__file__).resolve().parent.parent / "config" / "world-capability-registry.json"
        )
        if not config.is_file():
            self.skipTest(f"{config} not present")
        descs = ingest_world_capability_registry(config)
        self.assertGreater(len(descs), 0)
        domains = {d.domain for d in descs}
        self.assertIn(CapabilityDomain.DEVICE, domains)


if __name__ == "__main__":
    unittest.main()
