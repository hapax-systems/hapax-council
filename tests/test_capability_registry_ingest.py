"""Tests for the platform-capability-registry ingestion adapter (the producer layer, slice 3)."""

from __future__ import annotations

import unittest
from pathlib import Path

from shared.capability_harness_descriptor import (
    AuthorityCeiling,
    CapabilityDomain,
    CapabilityShape,
    CostSource,
    FreshnessState,
    QuotaSource,
    validate_descriptor,
)
from shared.capability_registry_ingest import (
    ingest_platform_capability_registry,
    ingest_routes,
)

# A minimal fixture covering the shape inferences (agent / review / local_tool / gateway / hosted).
_FIXTURE_ROUTES = [
    {
        "route_id": "claude.headless.full",
        "platform": "claude",
        "mode": "headless",
        "profile": "full",
        "route_state": "blocked",
        "summary": "Claude headless",
        "model_or_engine": "claude",
        "execution_descriptor": {"model_id": "claude-opus-4-8", "effort": "xhigh"},
        "authority_ceiling": "authoritative",
        "capacity_pool": "subscription_quota",
        "mutability": {"source": True, "public": False},
    },
    {
        "route_id": "glmcp.review.direct",
        "platform": "glmcp",
        "mode": "headless",
        "profile": "review",
        "route_state": "live",
        "summary": "GLMCP review",
        "execution_descriptor": {"model_id": "claude-opus-4-8", "effort": "none"},
        "authority_ceiling": "read_only",
        "capacity_pool": "subscription_quota",
        "mutability": {"source": False},
    },
    {
        "route_id": "local_tool.local.worker",
        "platform": "local_tool",
        "mode": "local",
        "profile": "worker",
        "route_state": "available",
        "summary": "local worker",
        "execution_descriptor": {"model_id": "command-r-08-2024"},
        "authority_ceiling": "read_only",
        "mutability": {"source": False},
    },
    {
        "route_id": "api.headless.provider_gateway",
        "platform": "api",
        "mode": "headless",
        "profile": "provider_gateway",
        "route_state": "blocked",
        "summary": "API gateway",
        "execution_descriptor": {"model_id": "litellm-router"},
        "authority_ceiling": "read_only",
        "capacity_pool": "api_paid_spend",
        "mutability": {"source": False, "runtime": True, "provider_spend": True},
        "telemetry": {"quota_source": "ledger", "cost_source": "ledger"},
    },
    {
        "route_id": "api.headless.api_frontier",
        "platform": "api",
        "mode": "headless",
        "profile": "api_frontier",
        "route_state": "live",
        "summary": "API frontier",
        "execution_descriptor": {"model_id": "claude-sonnet-5"},
        "authority_ceiling": "read_only",
        "capacity_pool": "paid_spend",
        "mutability": {"source": False},
    },
]


class IngestRoutesMappingTest(unittest.TestCase):
    """The route → descriptor mapping (shape/domain/authority/freshness inference)."""

    def setUp(self) -> None:
        self.descriptors = {d.capability_id: d for d in ingest_routes(_FIXTURE_ROUTES)}

    def test_agent_platform_maps_to_existing_agent_harness(self) -> None:
        desc = self.descriptors["claude.headless.full"]
        self.assertEqual(desc.shape, CapabilityShape.EXISTING_AGENT_HARNESS)
        self.assertEqual(desc.domain, CapabilityDomain.LLM_WORKER)

    def test_review_seat_shape(self) -> None:
        desc = self.descriptors["glmcp.review.direct"]
        self.assertEqual(desc.shape, CapabilityShape.REVIEW_SEAT)
        self.assertEqual(desc.domain, CapabilityDomain.REVIEW)

    def test_local_tool_shape(self) -> None:
        desc = self.descriptors["local_tool.local.worker"]
        self.assertEqual(desc.shape, CapabilityShape.LOCAL_TOOL)

    def test_provider_gateway_shape(self) -> None:
        desc = self.descriptors["api.headless.provider_gateway"]
        self.assertEqual(desc.shape, CapabilityShape.PROVIDER_GATEWAY)
        self.assertEqual(desc.provider, "api")
        self.assertEqual(desc.backend, "litellm-router")
        self.assertEqual(validate_descriptor(desc), [])
        self.assertTrue(desc.spend_authority_required)
        self.assertEqual(desc.cost_source, CostSource.LEDGER)
        self.assertEqual(desc.quota_source, QuotaSource.LEDGER)
        self.assertEqual(desc.mutation_surfaces, ["provider_spend", "runtime"])

    def test_hosted_model_shape_for_api_frontier(self) -> None:
        desc = self.descriptors["api.headless.api_frontier"]
        self.assertEqual(desc.shape, CapabilityShape.HOSTED_MODEL)
        self.assertEqual(desc.provider, "api")
        self.assertEqual(validate_descriptor(desc), [])

    def test_route_id_and_model_preserved(self) -> None:
        desc = self.descriptors["claude.headless.full"]
        self.assertEqual(desc.route_id, "claude.headless.full")
        self.assertEqual(desc.model, "claude-opus-4-8")
        self.assertEqual(desc.effort, "xhigh")

    def test_authority_ceiling_from_source_mutability(self) -> None:
        desc = self.descriptors["claude.headless.full"]
        self.assertEqual(desc.authority_ceiling, AuthorityCeiling.REPO_MUTATION)
        self.assertIn("source", desc.mutation_surfaces)

    def test_read_only_authority_for_non_mutating(self) -> None:
        desc = self.descriptors["glmcp.review.direct"]
        self.assertEqual(desc.authority_ceiling, AuthorityCeiling.READ_ONLY)

    def test_freshness_from_route_state(self) -> None:
        self.assertEqual(
            self.descriptors["claude.headless.full"].freshness_state, FreshnessState.STALE
        )
        self.assertEqual(
            self.descriptors["glmcp.review.direct"].freshness_state, FreshnessState.FRESH
        )
        self.assertEqual(
            self.descriptors["local_tool.local.worker"].freshness_state, FreshnessState.FRESH
        )

    def test_spend_authority_for_subscription_pool(self) -> None:
        self.assertTrue(self.descriptors["claude.headless.full"].spend_authority_required)
        self.assertTrue(self.descriptors["api.headless.api_frontier"].spend_authority_required)
        self.assertTrue(self.descriptors["api.headless.provider_gateway"].spend_authority_required)
        self.assertFalse(self.descriptors["local_tool.local.worker"].spend_authority_required)

    def test_one_descriptor_per_route(self) -> None:
        self.assertEqual(len(ingest_routes(_FIXTURE_ROUTES)), len(_FIXTURE_ROUTES))


class IngestRealConfigSmokeTest(unittest.TestCase):
    """Smoke test: ingest the real platform-capability-registry.json (skip if absent)."""

    def test_ingests_real_config_into_descriptors(self) -> None:
        config = (
            Path(__file__).resolve().parent.parent / "config" / "platform-capability-registry.json"
        )
        if not config.is_file():
            self.skipTest(f"{config} not present")
        descriptors = ingest_platform_capability_registry(config)
        self.assertGreater(len(descriptors), 0, "the real registry should yield descriptors")
        shapes = {d.shape for d in descriptors}
        # the real registry has agent platforms (claude/codex), a review seat, a local tool, an api gateway
        self.assertIn(CapabilityShape.EXISTING_AGENT_HARNESS, shapes)
        self.assertIn(CapabilityShape.REVIEW_SEAT, shapes)
        self.assertIn(CapabilityShape.LOCAL_TOOL, shapes)
        # every descriptor carries its route_id
        for desc in descriptors:
            self.assertTrue(desc.route_id)
            self.assertEqual(validate_descriptor(desc), [], f"{desc.capability_id} has gaps")


if __name__ == "__main__":
    unittest.main()
