"""Tests for the seed capability descriptors + the read-only inventory command."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

import shared.capability_inventory as inventory_cli
from shared.capability_harness_descriptor import (
    CapabilityHarnessDescriptor,
    CapabilityShape,
    CapabilitySurfaceDelta,
    validate_descriptor,
)
from shared.capability_harness_seed import SEED_CAPABILITY_DESCRIPTORS, seed_descriptors_by_shape
from shared.capability_inventory import inventory_report, project_inventory


class SeedRegistryTest(unittest.TestCase):
    """The seed registry covers all 12 shapes + every descriptor validates."""

    def test_seed_covers_every_shape(self) -> None:
        shapes = {d.shape for d in SEED_CAPABILITY_DESCRIPTORS}
        self.assertEqual(shapes, set(CapabilityShape))
        self.assertGreaterEqual(len(SEED_CAPABILITY_DESCRIPTORS), len(CapabilityShape))

    def test_every_seed_descriptor_validates(self) -> None:
        for desc in SEED_CAPABILITY_DESCRIPTORS:
            with self.subTest(capability_id=desc.capability_id):
                gaps = validate_descriptor(desc)
                self.assertEqual(gaps, [], f"{desc.capability_id} ({desc.shape}) has gaps: {gaps}")

    def test_seed_by_shape_keys_all_twelve(self) -> None:
        by_shape = seed_descriptors_by_shape()
        self.assertEqual(set(by_shape), set(CapabilityShape))

    def test_seed_capability_ids_unique(self) -> None:
        ids = [d.capability_id for d in SEED_CAPABILITY_DESCRIPTORS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_fugu_descriptors_present_and_prioritized(self) -> None:
        """Fugu (the top model post-Fable) is modeled with its entitlement + harnessing flagged."""
        ids = {d.capability_id for d in SEED_CAPABILITY_DESCRIPTORS}
        self.assertIn("fugu.existing-agent-harness", ids)
        self.assertIn("fugu.ultra.highest-tier", ids)
        fugu_ultra = next(
            d for d in SEED_CAPABILITY_DESCRIPTORS if d.capability_id == "fugu.ultra.highest-tier"
        )
        self.assertEqual(fugu_ultra.shape, CapabilityShape.MODEL_EFFORT_SLICE)
        self.assertIn("fugu-ultra-entitlement", fugu_ultra.resource_pools)
        self.assertTrue(fugu_ultra.spend_authority_required)


class InventoryReportTest(unittest.TestCase):
    """The structured inventory report."""

    def test_report_totals(self) -> None:
        report = inventory_report(SEED_CAPABILITY_DESCRIPTORS)
        self.assertEqual(report["total"], len(SEED_CAPABILITY_DESCRIPTORS))
        self.assertEqual(report["with_validation_gaps"], 0)

    def test_report_shape_counts_cover_all(self) -> None:
        report = inventory_report(SEED_CAPABILITY_DESCRIPTORS)
        shape_counts = report["shape_counts"]
        self.assertEqual(set(shape_counts), {s.value for s in CapabilityShape})

    def test_report_flags_a_broken_descriptor(self) -> None:
        # a hosted_model missing provider -> a gap is surfaced in the report
        from shared.capability_harness_descriptor import CapabilityHarnessDescriptor

        broken = CapabilityHarnessDescriptor(
            capability_id="broken.hosted",
            display_name="broken",
            shape=CapabilityShape.HOSTED_MODEL,
            domain="llm_worker",  # type: ignore[arg-type]
            model="some-model",
            spend_authority_required=True,
            provider=None,  # missing required fact
        )
        report = inventory_report([broken])
        self.assertEqual(report["with_validation_gaps"], 1)
        gaps = report["rows"][0]["gaps"]
        self.assertIn("provider", gaps)

    def test_project_inventory_gaps_only(self) -> None:
        # the seed has no gaps -> gaps_only returns empty
        self.assertEqual(project_inventory(SEED_CAPABILITY_DESCRIPTORS, gaps_only=True), [])
        # all rows returned without the filter
        self.assertEqual(
            len(project_inventory(SEED_CAPABILITY_DESCRIPTORS)), len(SEED_CAPABILITY_DESCRIPTORS)
        )


class InventoryCliTest(unittest.TestCase):
    """The read-only inventory command (scripts/hapax-capability-inventory)."""

    def test_human_report_prints_inventory(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = inventory_cli.main([])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Capability inventory", out)
        self.assertIn("TOTAL:", out)
        self.assertIn("DARK", out)

    def test_json_report_is_valid_json(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = inventory_cli.main(["--json"])
        self.assertEqual(rc, 0)
        report = json.loads(buf.getvalue())
        self.assertEqual(report["total"], len(SEED_CAPABILITY_DESCRIPTORS))
        self.assertEqual(report["with_validation_gaps"], 0)

    def test_gaps_only_prints_nothing_for_clean_seed(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = inventory_cli.main(["--gaps-only"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "")

    def test_delta_report_fails_when_observed_descriptor_has_validation_gap(self) -> None:
        bad = CapabilityHarnessDescriptor(
            capability_id="bad.hosted",
            display_name="bad.hosted",
            shape=CapabilityShape.HOSTED_MODEL,
            domain="llm_worker",  # type: ignore[arg-type]
            model="model",
            spend_authority_required=True,
        )
        with patch(
            "shared.capability_inventory_aggregator.full_inventory_delta",
            return_value=([bad], CapabilitySurfaceDelta()),
        ):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = inventory_cli.main(["--delta"])
        self.assertEqual(rc, 1)
        self.assertIn("capability_inventory_validation_gaps", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
