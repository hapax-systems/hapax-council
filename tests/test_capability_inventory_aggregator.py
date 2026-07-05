"""Tests for the unified capability inventory aggregator."""

from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from shared.capability_harness_descriptor import validate_descriptor
from shared.capability_inventory_aggregator import (
    _read_models_dict_literal,
    aggregate_all_capabilities,
    full_inventory_delta,
)


class AggregateAllCapabilitiesTest(unittest.TestCase):
    """The aggregator ingests all available vocabularies (skips missing gracefully)."""

    def test_returns_descriptors(self) -> None:
        descs = aggregate_all_capabilities()
        # in the live repo, at least the platform-capability-registry should yield descriptors
        self.assertGreater(len(descs), 0)

    def test_covers_multiple_shapes(self) -> None:
        from shared.capability_harness_descriptor import CapabilityShape

        descs = aggregate_all_capabilities()
        shapes = {d.shape for d in descs}
        # the platform registry has agent harnesses + review seats + local tools
        self.assertIn(CapabilityShape.EXISTING_AGENT_HARNESS, shapes)
        self.assertIn(CapabilityShape.REVIEW_SEAT, shapes)

    def test_capabilities_have_route_or_capability_ids(self) -> None:
        descs = aggregate_all_capabilities()
        for d in descs:
            self.assertTrue(d.capability_id, f"descriptor missing capability_id: {d}")

    def test_no_duplicate_capability_ids(self) -> None:
        descs = aggregate_all_capabilities()
        ids = [d.capability_id for d in descs]
        duplicates = sorted(cid for cid, count in Counter(ids).items() if count > 1)
        self.assertEqual(duplicates, [])

    def test_aggregate_descriptors_validate(self) -> None:
        descs = aggregate_all_capabilities()
        invalid = {d.capability_id: validate_descriptor(d) for d in descs if validate_descriptor(d)}
        self.assertEqual(invalid, {})

    def test_reads_models_literal_from_annotated_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.py"
            path.write_text(
                "MODELS: dict[str, str] = {'fast': 'gemini-flash'}\n",
                encoding="utf-8",
            )
            self.assertEqual(_read_models_dict_literal(path), {"fast": "gemini-flash"})

    def test_reads_models_literal_from_plain_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.py"
            path.write_text("MODELS = {'balanced': 'claude-sonnet'}\n", encoding="utf-8")
            self.assertEqual(_read_models_dict_literal(path), {"balanced": "claude-sonnet"})

    def test_missing_models_literal_is_reported_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.py"
            path.write_text("OTHER = {'fast': 'gemini-flash'}\n", encoding="utf-8")
            self.assertIsNone(_read_models_dict_literal(path))

    def test_aggregate_warns_when_models_literal_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "shared").mkdir()
            (root / "shared" / "config.py").write_text(
                "OTHER = {'fast': 'gemini-flash'}\n",
                encoding="utf-8",
            )
            with self.assertLogs("shared.capability_inventory_aggregator", level="WARNING") as cm:
                aggregate_all_capabilities(root=root)
            self.assertTrue(
                any("missing MODELS literal" in message for message in cm.output),
                cm.output,
            )

    def test_aggregate_warns_when_models_literal_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "shared").mkdir()
            (root / "shared" / "config.py").write_text("MODELS = {}\n", encoding="utf-8")
            with self.assertLogs("shared.capability_inventory_aggregator", level="WARNING") as cm:
                aggregate_all_capabilities(root=root)
            self.assertTrue(
                any("MODELS literal is empty" in message for message in cm.output),
                cm.output,
            )

    def test_aggregate_warns_when_models_config_is_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "shared").mkdir()
            (root / "shared" / "config.py").write_text("MODELS = {\n", encoding="utf-8")
            with self.assertLogs("shared.capability_inventory_aggregator", level="WARNING") as cm:
                aggregate_all_capabilities(root=root)
            self.assertTrue(
                any("source unavailable" in message for message in cm.output),
                cm.output,
            )

    def test_aggregate_warns_when_publication_bus_import_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "shared").mkdir()
            (root / "shared" / "config.py").write_text(
                "MODELS = {'fast': 'gemini-flash'}\n",
                encoding="utf-8",
            )
            with (
                patch(
                    "shared.capability_inventory_aggregator.ingest_publication_bus_from_module",
                    side_effect=ImportError("missing publication bus"),
                ),
                self.assertLogs("shared.capability_inventory_aggregator", level="WARNING") as cm,
            ):
                aggregate_all_capabilities(root=root)
            self.assertTrue(
                any("publication_bus" in message for message in cm.output),
                cm.output,
            )


class FullInventoryDeltaTest(unittest.TestCase):
    """The full delta (observed vs an empty baseline = everything is NEW)."""

    def test_empty_baseline_all_new(self) -> None:
        observed, delta = full_inventory_delta(registered={})
        self.assertEqual(len(observed), len(delta.new_capability_ids))
        self.assertEqual(len(delta.changed_capability_ids), 0)
        self.assertEqual(len(delta.missing_capability_ids), 0)

    def test_delta_is_not_empty(self) -> None:
        _, delta = full_inventory_delta(registered={})
        self.assertFalse(delta.is_empty)

    def test_known_baseline_produces_changed(self) -> None:
        observed, _ = full_inventory_delta(registered={})
        # register the current fingerprints, then mutate one + re-discover
        from shared.capability_harness_descriptor import (
            AuthorityCeiling,
            descriptor_fingerprint,
            discover,
        )

        registered = {d.capability_id: descriptor_fingerprint(d) for d in observed}
        if not observed:
            self.skipTest("no observed capabilities")
        # mutate the first descriptor's authority ceiling (a material change)
        original = observed[0].authority_ceiling
        new_ceiling = (
            AuthorityCeiling.PUBLIC_PUBLISH
            if original != AuthorityCeiling.PUBLIC_PUBLISH
            else AuthorityCeiling.REPO_MUTATION
        )
        mutated = observed[0].model_copy(update={"authority_ceiling": new_ceiling})
        rest = observed[1:]
        new_delta = discover([mutated] + rest, registered)
        self.assertGreater(len(new_delta.changed_capability_ids), 0)


if __name__ == "__main__":
    unittest.main()
