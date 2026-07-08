"""Tests for the CapabilityHarnessDescriptor — the authoritative 12-shape capability schema.

Covers: the 12-shape vocabulary, per-shape required-facts validation, descriptor fingerprint stability
(+ material vs cosmetic), and the discover() capability_surface_delta (new/changed/missing).
"""

from __future__ import annotations

import unittest

from shared.capability_harness_descriptor import (
    SHAPE_REQUIRED_FACTS,
    AuthorityCeiling,
    CapabilityAction,
    CapabilityDomain,
    CapabilityHarnessDescriptor,
    CapabilityShape,
    CostSource,
    DeltaKind,
    FreshnessState,
    QuotaSource,
    descriptor_fingerprint,
    discover,
    validate_descriptor,
)


def _descriptor(
    shape: CapabilityShape,
    *,
    capability_id: str | None = None,
    **overrides: object,
) -> CapabilityHarnessDescriptor:
    """Build a descriptor for a shape, seeding the shape's required facts so it validates by default."""
    cid = capability_id or f"test.{shape.value}"
    required = SHAPE_REQUIRED_FACTS.get(shape, ())
    seed: dict[str, object] = {
        "capability_id": cid,
        "display_name": cid,
        "shape": shape,
        "domain": CapabilityDomain.LLM_WORKER,
    }
    # seed every required fact with a non-empty placeholder so the default descriptor validates
    for fact in required:
        if fact in {
            "actions",
        }:
            seed[fact] = [CapabilityAction.REASON]
        elif fact in {"mutation_surfaces", "resource_pools"}:
            seed[fact] = ["seed-surface"]
        elif fact in {"spend_authority_required", "public_egress_authority_required"}:
            seed[fact] = True
        elif fact in {"authority_ceiling"}:
            seed[fact] = AuthorityCeiling.RECEIVE_ONLY_MONEY
        elif fact in {"effort"}:
            seed[fact] = "xhigh"
        else:
            seed[fact] = f"seed-{fact}"
    seed.update(overrides)
    return CapabilityHarnessDescriptor(**seed)  # type: ignore[arg-type]


class ShapeVocabularyTest(unittest.TestCase):
    """The 12-shape vocabulary is the authoritative capability taxonomy."""

    def test_twelve_shapes_enumerated(self) -> None:
        self.assertEqual(len(CapabilityShape), 12)

    def test_expected_shapes_present(self) -> None:
        expected = {
            "raw_model",
            "hosted_model",
            "model_effort_slice",
            "existing_agent_harness",
            "review_seat",
            "local_tool",
            "provider_gateway",
            "public_egress",
            "money_rail",
            "background_service",
            "orchestrator",
            "capability_aggregator",
        }
        self.assertEqual({s.value for s in CapabilityShape}, expected)


class ValidateDescriptorTest(unittest.TestCase):
    """Per-shape required-facts validation."""

    def test_every_shape_validates_when_required_facts_present(self) -> None:
        for shape in CapabilityShape:
            with self.subTest(shape=shape.value):
                desc = _descriptor(shape)
                self.assertEqual(validate_descriptor(desc), [], f"{shape} should validate")

    def test_missing_required_fact_surfaced(self) -> None:
        # A hosted_model missing the provider fact -> validation surfaces it.
        desc = _descriptor(CapabilityShape.HOSTED_MODEL, provider=None)
        missing = validate_descriptor(desc)
        self.assertIn("provider", missing)

    def test_empty_list_required_fact_treated_as_absent(self) -> None:
        # A public_egress with empty mutation_surfaces -> absent.
        desc = _descriptor(CapabilityShape.PUBLIC_EGRESS, mutation_surfaces=[])
        missing = validate_descriptor(desc)
        self.assertIn("mutation_surfaces", missing)

    def test_defaulted_authority_fact_must_be_explicit(self) -> None:
        desc = CapabilityHarnessDescriptor(
            capability_id="hosted.defaulted",
            display_name="hosted.defaulted",
            shape=CapabilityShape.HOSTED_MODEL,
            domain=CapabilityDomain.LLM_WORKER,
            provider="provider",
            model="model",
        )
        self.assertIn("spend_authority_required", validate_descriptor(desc))

    def test_explicit_false_authority_fact_is_present(self) -> None:
        desc = CapabilityHarnessDescriptor(
            capability_id="hosted.explicit-free",
            display_name="hosted.explicit-free",
            shape=CapabilityShape.HOSTED_MODEL,
            domain=CapabilityDomain.LLM_WORKER,
            provider="provider",
            model="model",
            spend_authority_required=False,
        )
        self.assertEqual(validate_descriptor(desc), [])

    def test_shape_with_no_required_facts_always_validates(self) -> None:
        # Any shape not in SHAPE_REQUIRED_FACTS validates regardless.
        desc = CapabilityHarnessDescriptor(
            capability_id="bare",
            display_name="bare",
            shape=CapabilityShape.CAPABILITY_AGGREGATOR,
            domain=CapabilityDomain.ORCHESTRATION,
            actions=[CapabilityAction.ORCHESTRATE],
        )
        self.assertEqual(validate_descriptor(desc), [])


class FingerprintTest(unittest.TestCase):
    """Descriptor fingerprint stability + material vs cosmetic."""

    def test_identical_descriptors_same_fingerprint(self) -> None:
        a = _descriptor(CapabilityShape.HOSTED_MODEL)
        b = _descriptor(CapabilityShape.HOSTED_MODEL)
        self.assertEqual(descriptor_fingerprint(a), descriptor_fingerprint(b))

    def test_material_change_changes_fingerprint(self) -> None:
        a = _descriptor(CapabilityShape.HOSTED_MODEL)
        b = _descriptor(
            CapabilityShape.HOSTED_MODEL, authority_ceiling=AuthorityCeiling.PUBLIC_PUBLISH
        )
        self.assertNotEqual(descriptor_fingerprint(a), descriptor_fingerprint(b))

    def test_governance_material_fields_change_fingerprint(self) -> None:
        base = _descriptor(CapabilityShape.HOSTED_MODEL)
        updates = {
            "provider": "other-provider",
            "backend": "other-backend",
            "mutation_surfaces": ["other-surface"],
            "quota_source": QuotaSource.LEDGER,
            "cost_source": CostSource.LEDGER,
            "freshness_state": FreshnessState.FRESH,
            "freshness_evidence": ["receipt://fresh"],
        }
        for field, value in updates.items():
            with self.subTest(field=field):
                changed = base.model_copy(update={field: value})
                self.assertNotEqual(descriptor_fingerprint(base), descriptor_fingerprint(changed))

    def test_cosmetic_change_preserves_fingerprint(self) -> None:
        a = _descriptor(CapabilityShape.HOSTED_MODEL)
        b = _descriptor(CapabilityShape.HOSTED_MODEL, display_name="different display name")
        self.assertEqual(descriptor_fingerprint(a), descriptor_fingerprint(b))


class DiscoverDeltaTest(unittest.TestCase):
    """discover() — the capability_surface_delta."""

    def test_new_capability_surfaced(self) -> None:
        observed = [_descriptor(CapabilityShape.LOCAL_TOOL, capability_id="tool.new")]
        delta = discover(observed, registered={})
        self.assertEqual(delta.new_capability_ids, ["tool.new"])
        self.assertEqual(delta.changed_capability_ids, [])
        self.assertEqual(delta.missing_capability_ids, [])
        self.assertFalse(delta.is_empty)

    def test_changed_capability_surfaced(self) -> None:
        desc = _descriptor(CapabilityShape.HOSTED_MODEL, capability_id="cap.changed")
        registered = {"cap.changed": descriptor_fingerprint(desc)}
        # mutate a material field -> fingerprint changes
        changed = desc.model_copy(update={"authority_ceiling": AuthorityCeiling.REPO_MUTATION})
        delta = discover([changed], registered)
        self.assertEqual(delta.changed_capability_ids, ["cap.changed"])

    def test_missing_capability_surfaced(self) -> None:
        desc = _descriptor(CapabilityShape.HOSTED_MODEL)
        registered = {desc.capability_id: descriptor_fingerprint(desc)}
        delta = discover(observed=[], registered=registered)
        self.assertEqual(delta.missing_capability_ids, [desc.capability_id])

    def test_no_delta_is_empty(self) -> None:
        desc = _descriptor(CapabilityShape.HOSTED_MODEL)
        fp = descriptor_fingerprint(desc)
        delta = discover([desc], registered={desc.capability_id: fp})
        self.assertTrue(delta.is_empty)
        self.assertEqual(delta.kinds(), [])

    def test_duplicate_observed_capability_ids_are_rejected(self) -> None:
        desc = _descriptor(CapabilityShape.LOCAL_TOOL, capability_id="cap.duplicate")
        with self.assertRaisesRegex(ValueError, "duplicate capability_id"):
            discover([desc, desc.model_copy()], registered={})

    def test_kinds_emits_all_deltas(self) -> None:
        unchanged = _descriptor(CapabilityShape.LOCAL_TOOL, capability_id="cap.same")
        new = _descriptor(CapabilityShape.REVIEW_SEAT, capability_id="cap.new")
        gone_fp = "registered-but-not-observed"
        registered = {
            unchanged.capability_id: descriptor_fingerprint(unchanged),
            "cap.gone": gone_fp,
        }
        delta = discover([unchanged, new], registered)
        kinds = dict(delta.kinds())
        self.assertEqual(kinds["cap.new"], DeltaKind.NEW)
        self.assertEqual(kinds["cap.gone"], DeltaKind.MISSING)
        self.assertNotIn("cap.same", kinds)


if __name__ == "__main__":
    unittest.main()
