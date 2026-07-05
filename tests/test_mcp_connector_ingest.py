"""Tests for the MCP connector manifest ingestion adapter (producer layer slice 6)."""

from __future__ import annotations

import unittest
from pathlib import Path

from shared.capability_harness_descriptor import (
    AuthorityCeiling,
    CapabilityAction,
    CapabilityShape,
)
from shared.mcp_connector_ingest import ingest_mcp_connector_manifest, ingest_mcp_connector_routes

_FIXTURE = [
    {"canonical_name": "context7.resolve_library_id", "effect_classes": ["read_only_evidence"]},
    {
        "canonical_name": "github.create_pull_request",
        "effect_classes": ["external_mutation", "public_egress", "governance_mutation"],
    },
    {
        "canonical_name": "github.merge_pull_request",
        "effect_classes": ["external_mutation", "public_egress"],
    },
    {
        "canonical_name": "hapax.nudge_act",
        "effect_classes": ["local_mutation", "governance_mutation"],
    },
]


class McpConnectorIngestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.descs = {d.capability_id: d for d in ingest_mcp_connector_routes(_FIXTURE)}

    def test_read_only_maps_to_local_tool(self) -> None:
        self.assertEqual(
            self.descs["context7.resolve_library_id"].shape, CapabilityShape.LOCAL_TOOL
        )
        self.assertEqual(
            self.descs["context7.resolve_library_id"].authority_ceiling, AuthorityCeiling.READ_ONLY
        )

    def test_external_mutation_maps_to_public_egress(self) -> None:
        self.assertEqual(
            self.descs["github.create_pull_request"].shape, CapabilityShape.PUBLIC_EGRESS
        )
        self.assertEqual(
            self.descs["github.create_pull_request"].authority_ceiling,
            AuthorityCeiling.PUBLIC_PUBLISH,
        )
        self.assertTrue(self.descs["github.create_pull_request"].public_egress_authority_required)

    def test_local_mutation_has_mutate_action(self) -> None:
        self.assertIn(CapabilityAction.MUTATE, self.descs["hapax.nudge_act"].actions)

    def test_one_per_tool(self) -> None:
        self.assertEqual(len(ingest_mcp_connector_routes(_FIXTURE)), len(_FIXTURE))

    def test_unknown_effect_class_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown MCP effect_classes"):
            ingest_mcp_connector_routes(
                [{"canonical_name": "tool.unknown", "effect_classes": ["network_mystery"]}]
            )

    def test_malformed_effect_classes_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "effect_classes must be a list"):
            ingest_mcp_connector_routes(
                [{"canonical_name": "tool.malformed", "effect_classes": "external_mutation"}]
            )


class McpConnectorSmokeTest(unittest.TestCase):
    def test_ingests_real_manifest(self) -> None:
        config = (
            Path(__file__).resolve().parent.parent / "config" / "mcp-connector-tool-manifest.json"
        )
        if not config.is_file():
            self.skipTest(f"{config} not present")
        descs = ingest_mcp_connector_manifest(config)
        self.assertGreater(len(descs), 0)
        shapes = {d.shape for d in descs}
        self.assertIn(CapabilityShape.LOCAL_TOOL, shapes)


if __name__ == "__main__":
    unittest.main()
