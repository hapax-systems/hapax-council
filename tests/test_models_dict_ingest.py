"""Tests for the MODELS dict ingestion adapter (producer layer slice 8)."""

from __future__ import annotations

import unittest

from shared.capability_harness_descriptor import (
    CapabilityDomain,
    CapabilityShape,
    CostSource,
)
from shared.models_dict_ingest import ingest_models_dict


class ModelsDictIngestTest(unittest.TestCase):
    def test_string_alias_maps_to_hosted_model(self) -> None:
        descs = ingest_models_dict(
            {"deepseek": "deepseek/deepseek-chat", "glm": "zhipuai/glm-4-plus"}
        )
        self.assertEqual(len(descs), 2)
        ds = next(d for d in descs if d.capability_id == "litellm.deepseek")
        self.assertEqual(ds.shape, CapabilityShape.HOSTED_MODEL)
        self.assertEqual(ds.domain, CapabilityDomain.LLM_WORKER)
        self.assertEqual(ds.model, "deepseek/deepseek-chat")
        self.assertTrue(ds.spend_authority_required)
        self.assertEqual(ds.cost_source, CostSource.PROVIDER)

    def test_dict_alias_extracts_route(self) -> None:
        descs = ingest_models_dict({"opus": {"route": "anthropic/claude-opus-4-8"}})
        self.assertEqual(descs[0].model, "anthropic/claude-opus-4-8")

    def test_empty_dict_returns_empty(self) -> None:
        self.assertEqual(ingest_models_dict({}), [])

    def test_capability_ids_prefixed(self) -> None:
        descs = ingest_models_dict({"mistral": "mistral/mistral-large"})
        self.assertEqual(descs[0].capability_id, "litellm.mistral")


if __name__ == "__main__":
    unittest.main()
