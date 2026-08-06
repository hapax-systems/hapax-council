"""Tests for the unified capability inventory aggregator."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from shared.capability_harness_descriptor import validate_descriptor
from shared.capability_inventory_aggregator import (
    _read_models_dict_literal,
    aggregate_all_capabilities,
    aggregate_capability_inventory,
    full_capability_inventory_delta,
    full_inventory_delta,
)
from shared.capability_inventory_contract import (
    AdmittedSupplyInventoryRecord,
    CapabilityInventoryBaselineV2,
    CapabilityInventorySnapshot,
    EvidenceOnlyNonSupplyInventoryRecord,
    InventoryDisposition,
    discover_inventory,
    inventory_baseline,
    inventory_record_fingerprint,
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


class TaggedCapabilityInventoryTest(unittest.TestCase):
    """The v2 inventory exposes non-supply without allowing supply projection."""

    def setUp(self) -> None:
        self.snapshot = aggregate_capability_inventory()

    def test_tagged_inventory_contains_both_dispositions(self) -> None:
        dispositions = {record.inventory_disposition for record in self.snapshot.records}

        self.assertEqual(
            dispositions,
            {
                InventoryDisposition.ADMITTED_SUPPLY,
                InventoryDisposition.EVIDENCE_ONLY_NON_SUPPLY,
            },
        )

    def test_every_omitted_platform_shape_is_inventory_visible(self) -> None:
        from shared.platform_capability_registry import load_platform_capability_registry

        registry = load_platform_capability_registry()
        expected = {shape.shape_id for shape in registry.omitted_capability_shapes}
        observed = {
            shape.shape_id for shape in self.snapshot.evidence_only_non_supply_descriptors()
        }

        self.assertEqual(observed, expected)

    def test_legacy_projection_contains_admitted_supply_only(self) -> None:
        legacy = aggregate_all_capabilities()
        projected = self.snapshot.admitted_supply_descriptors()

        self.assertEqual(
            {descriptor.capability_id for descriptor in legacy},
            {descriptor.capability_id for descriptor in projected},
        )
        self.assertNotIn(
            "local_compute.agentic_trust_evaluator_surface",
            {descriptor.capability_id for descriptor in projected},
        )

    def test_cross_plane_duplicate_inventory_id_fails_closed(self) -> None:
        supply = next(
            record
            for record in self.snapshot.records
            if isinstance(record, AdmittedSupplyInventoryRecord)
        )
        shape = next(
            record
            for record in self.snapshot.records
            if isinstance(record, EvidenceOnlyNonSupplyInventoryRecord)
        )
        duplicate_shape = shape.descriptor.model_copy(update={"shape_id": supply.inventory_id})
        duplicate_record = EvidenceOnlyNonSupplyInventoryRecord(
            inventory_id=supply.inventory_id,
            descriptor=duplicate_shape,
        )

        with self.assertRaisesRegex(ValueError, "across capability inventory planes"):
            CapabilityInventorySnapshot(records=(*self.snapshot.records, duplicate_record))

    def test_nested_non_supply_mutation_is_revalidated_before_projection(self) -> None:
        target = next(
            record
            for record in self.snapshot.records
            if record.inventory_id == "local_compute.agentic_trust_evaluator_surface"
        )
        target.descriptor.route_ids.append("codex.headless.full")

        with self.assertRaisesRegex(ValueError, "cannot carry route_ids"):
            self.snapshot.evidence_only_non_supply_descriptors()

    def test_nested_id_mutation_is_revalidated_before_fingerprinting(self) -> None:
        target = next(
            record
            for record in self.snapshot.records
            if record.inventory_id == "local_compute.agentic_trust_evaluator_surface"
        )
        target.descriptor.shape_id = "codex.headless.full"

        with self.assertRaisesRegex(ValueError, "inventory_id must equal"):
            inventory_baseline(self.snapshot)

    def test_nested_mutation_is_revalidated_before_any_snapshot_serialization(self) -> None:
        target = next(
            record
            for record in self.snapshot.records
            if record.inventory_id == "local_compute.agentic_trust_evaluator_surface"
        )
        target.descriptor.route_ids.append("codex.headless.full")

        with self.assertRaisesRegex(ValueError, "cannot carry route_ids"):
            self.snapshot.model_dump(mode="json")
        with self.assertRaisesRegex(ValueError, "cannot carry route_ids"):
            self.snapshot.model_dump_json()

    def test_valid_nested_mutation_cannot_redefine_a_frozen_snapshot(self) -> None:
        from shared.platform_capability_registry import AuthorityCeiling

        target = next(
            record
            for record in self.snapshot.records
            if record.inventory_id == "publication_bus.public_event_surface"
        )
        target.descriptor.authority_ceiling = AuthorityCeiling.READ_ONLY

        with self.assertRaisesRegex(ValueError, "mutated after admission"):
            inventory_baseline(self.snapshot)
        with self.assertRaisesRegex(ValueError, "mutated after admission"):
            CapabilityInventorySnapshot.model_validate(self.snapshot)

    def test_direct_record_serialization_rejects_nested_poison(self) -> None:
        target = next(
            record
            for record in self.snapshot.records
            if record.inventory_id == "local_compute.agentic_trust_evaluator_surface"
        )
        target.descriptor.route_ids.append("codex.headless.full")

        with self.assertRaisesRegex(ValueError, "cannot carry route_ids"):
            target.model_dump(mode="json")
        with self.assertRaisesRegex(ValueError, "cannot carry route_ids"):
            target.model_dump_json()

    def test_snapshot_serialization_preserves_include_exclude_and_schema(self) -> None:
        self.assertEqual(
            self.snapshot.model_dump(exclude={"records"}),
            {"inventory_schema": 2},
        )
        self.assertEqual(
            self.snapshot.model_dump(include={"inventory_schema"}),
            {"inventory_schema": 2},
        )
        schema = CapabilityInventorySnapshot.model_json_schema(mode="serialization")
        self.assertEqual(set(schema["properties"]), {"inventory_schema", "records"})
        self.assertEqual(set(schema["required"]), {"records"})

    def test_baseline_serialization_rejects_nested_mapping_mutation(self) -> None:
        baseline = inventory_baseline(self.snapshot)
        baseline.records.pop(next(iter(baseline.records)))

        with self.assertRaisesRegex(ValueError, "baseline mutated"):
            baseline.model_dump(mode="json")
        with self.assertRaisesRegex(ValueError, "baseline mutated"):
            CapabilityInventoryBaselineV2.model_validate(baseline)

    def test_snapshot_json_roundtrip_preserves_record_types_and_fingerprints(self) -> None:
        encoded = self.snapshot.model_dump_json()
        round_tripped = CapabilityInventorySnapshot.model_validate(json.loads(encoded))

        self.assertEqual(
            [type(record) for record in round_tripped.records],
            [type(record) for record in self.snapshot.records],
        )
        self.assertEqual(
            {
                record.inventory_id: inventory_record_fingerprint(record)
                for record in round_tripped.records
            },
            {
                record.inventory_id: inventory_record_fingerprint(record)
                for record in self.snapshot.records
            },
        )

    def test_non_supply_authority_change_is_changed(self) -> None:
        from shared.platform_capability_registry import AuthorityCeiling

        baseline = inventory_baseline(self.snapshot)
        target = next(
            record
            for record in self.snapshot.records
            if record.inventory_id == "publication_bus.public_event_surface"
        )
        changed_descriptor = target.descriptor.model_copy(
            update={"authority_ceiling": AuthorityCeiling.READ_ONLY}
        )
        changed = EvidenceOnlyNonSupplyInventoryRecord(
            inventory_id=target.inventory_id,
            descriptor=changed_descriptor,
        )
        mutated = CapabilityInventorySnapshot(
            records=tuple(
                changed if record.inventory_id == target.inventory_id else record
                for record in self.snapshot.records
            )
        )

        delta = discover_inventory(mutated, baseline.records)

        self.assertIn(target.inventory_id, delta.changed_capability_ids)

    def test_non_supply_freshness_change_is_changed(self) -> None:
        from shared.platform_capability_registry import CapabilityShapeFreshnessState

        baseline = inventory_baseline(self.snapshot)
        target = next(
            record
            for record in self.snapshot.records
            if record.inventory_id == "local_compute.agentic_trust_evaluator_surface"
        )
        changed_descriptor = target.descriptor.model_copy(
            update={"freshness_state": CapabilityShapeFreshnessState.STALE}
        )
        changed = EvidenceOnlyNonSupplyInventoryRecord(
            inventory_id=target.inventory_id,
            descriptor=changed_descriptor,
        )
        mutated = CapabilityInventorySnapshot(
            records=tuple(
                changed if record.inventory_id == target.inventory_id else record
                for record in self.snapshot.records
            )
        )

        delta = discover_inventory(mutated, baseline.records)

        self.assertIn(target.inventory_id, delta.changed_capability_ids)

    def test_permanent_evaluator_cannot_change_inventory_disposition(self) -> None:
        target = next(
            record
            for record in self.snapshot.records
            if record.inventory_id == "local_compute.agentic_trust_evaluator_surface"
        )
        supply_template = next(
            record
            for record in self.snapshot.records
            if isinstance(record, AdmittedSupplyInventoryRecord)
        )
        promoted_descriptor = supply_template.descriptor.model_copy(
            update={"capability_id": target.inventory_id}
        )
        with self.assertRaisesRegex(ValueError, "permanently non-supply"):
            AdmittedSupplyInventoryRecord(
                inventory_id=target.inventory_id,
                descriptor=promoted_descriptor,
            )

    def test_permanent_evaluator_cannot_hide_in_admitted_supply_route_identity(self) -> None:
        supply_template = next(
            record
            for record in self.snapshot.records
            if isinstance(record, AdmittedSupplyInventoryRecord)
            and record.descriptor.route_id is not None
        )
        for route_id in (
            "surface/local_compute.agentic_trust_evaluator_surface",
            "route.local_compute.agentic_trust_evaluator_surface",
            "ROUTE/local_compute/agentic_trust_evaluator_surface",
        ):
            with self.subTest(route_id=route_id):
                promoted_descriptor = supply_template.descriptor.model_copy(
                    update={"route_id": route_id}
                )
                with self.assertRaisesRegex(ValueError, "permanently non-supply"):
                    AdmittedSupplyInventoryRecord(
                        inventory_id=supply_template.inventory_id,
                        descriptor=promoted_descriptor,
                    )

    def test_permanent_evaluator_cannot_hide_in_admitted_execution_identity(self) -> None:
        supply_template = next(
            record
            for record in self.snapshot.records
            if isinstance(record, AdmittedSupplyInventoryRecord)
        )
        for field in (
            "platform_id",
            "execution_harness_id",
            "provider",
            "backend",
            "model",
        ):
            with self.subTest(field=field):
                promoted_descriptor = supply_template.descriptor.model_copy(
                    update={field: "local_compute.agentic_trust_evaluator_surface"}
                )
                with self.assertRaisesRegex(ValueError, "permanently non-supply"):
                    AdmittedSupplyInventoryRecord(
                        inventory_id=supply_template.inventory_id,
                        descriptor=promoted_descriptor,
                    )

    def test_native_receipt_cannot_hide_in_admitted_semantic_fields(self) -> None:
        supply_template = next(
            record
            for record in self.snapshot.records
            if isinstance(record, AdmittedSupplyInventoryRecord)
        )
        marker = "AgenticTrustEvidenceReceiptV1"
        poisoned_values = {
            "effort": marker,
            "context_window": marker,
            "mutation_surfaces": [marker],
            "quality_floors": [marker],
            "privacy_posture": marker,
            "public_claim_ceiling": marker,
            "resource_pools": [marker],
            "freshness_evidence": [marker],
            "receipt_classes": [marker],
            "failure_classes": [marker],
            "kill_switches": [marker],
            "fallback_policy": marker,
            "stale_after": marker,
        }
        for field, value in poisoned_values.items():
            with self.subTest(field=field):
                descriptor = supply_template.descriptor.model_copy(update={field: value})
                with self.assertRaisesRegex(ValueError, "permanently non-supply"):
                    AdmittedSupplyInventoryRecord(
                        inventory_id=supply_template.inventory_id,
                        descriptor=descriptor,
                    )

    def test_permanent_evaluator_child_is_not_the_reserved_identity(self) -> None:
        supply_template = next(
            record
            for record in self.snapshot.records
            if isinstance(record, AdmittedSupplyInventoryRecord)
        )
        child_id = "local_compute.agentic_trust_evaluator_surface.child"
        child_descriptor = supply_template.descriptor.model_copy(update={"capability_id": child_id})

        record = AdmittedSupplyInventoryRecord(
            inventory_id=child_id,
            descriptor=child_descriptor,
        )

        self.assertEqual(record.inventory_id, child_id)

    def test_non_supply_removal_is_missing(self) -> None:
        baseline = inventory_baseline(self.snapshot)
        target_id = "local_compute.agentic_trust_evaluator_surface"
        mutated = CapabilityInventorySnapshot(
            records=tuple(
                record for record in self.snapshot.records if record.inventory_id != target_id
            )
        )

        delta = discover_inventory(mutated, baseline.records)

        self.assertIn(target_id, delta.missing_capability_ids)

    def test_current_snapshot_round_trips_to_empty_delta(self) -> None:
        baseline = inventory_baseline(self.snapshot)

        observed, delta = full_capability_inventory_delta(baseline.records)

        self.assertEqual(len(observed.records), len(self.snapshot.records))
        self.assertTrue(delta.is_empty)


if __name__ == "__main__":
    unittest.main()
