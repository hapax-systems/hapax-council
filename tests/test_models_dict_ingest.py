"""Tests for the MODELS dict ingestion adapter (producer layer slice 8)."""

from __future__ import annotations

import unittest

from shared.capability_harness_descriptor import (
    CapabilityDomain,
    CapabilityShape,
    CostSource,
    QuotaSource,
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

    def test_local_alias_maps_to_raw_model_without_provider_spend(self) -> None:
        descs = ingest_models_dict({"local-fast": "local-fast"})
        desc = descs[0]
        self.assertEqual(desc.shape, CapabilityShape.RAW_MODEL)
        self.assertEqual(desc.domain, CapabilityDomain.LOCAL_COMPUTE)
        self.assertFalse(desc.spend_authority_required)
        self.assertEqual(desc.cost_source, CostSource.NONE)
        self.assertEqual(desc.quota_source, QuotaSource.NONE)
        self.assertEqual(desc.backend, "litellm-local")

    def test_appendix_alias_maps_to_raw_model_without_provider_spend(self) -> None:
        descs = ingest_models_dict({"appendix-fast": "appendix-fast"})
        self.assertEqual(descs[0].shape, CapabilityShape.RAW_MODEL)
        self.assertFalse(descs[0].spend_authority_required)

    def test_empty_dict_returns_empty(self) -> None:
        self.assertEqual(ingest_models_dict({}), [])

    def test_capability_ids_prefixed(self) -> None:
        descs = ingest_models_dict({"mistral": "mistral/mistral-large"})
        self.assertEqual(descs[0].capability_id, "litellm.mistral")


if __name__ == "__main__":
    unittest.main()
