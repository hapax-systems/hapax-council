"""The CI gate — the capability_surface_delta failing-check.

If a capability is added, changed, or removed from any of the 7 vocabularies without updating the
committed baseline (config/capability-inventory-baseline.json), this test FAILS. That is the
meta-priority enforcement: every boutique/missing/unregistered capability surface becomes a build
failure, not a manual find. To update after an intentional change, regenerate the baseline.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from shared.capability_harness_descriptor import (
    descriptor_fingerprint,
    validate_descriptor,
)
from shared.capability_inventory import _load_inventory_baseline
from shared.capability_inventory_aggregator import aggregate_capability_inventory
from shared.capability_inventory_contract import (
    CapabilityInventoryBaselineV2,
    discover_inventory,
    inventory_baseline,
    wrap_supply_descriptor_fingerprint,
)

ROOT = Path(__file__).resolve().parent.parent
HISTORICAL_V1_BASELINE = ROOT / "tests" / "fixtures" / "capability-inventory-baseline-v1.json"
BASELINE_SCHEMA = ROOT / "schemas" / "capability-inventory-baseline.schema.json"
GATE = ROOT / "scripts" / "hapax-capability-surface-delta-gate"
CI_GATE_COMMAND = [
    "uv",
    "run",
    "--no-project",
    "--with",
    "pydantic==2.13.4",
    "--with",
    "pyyaml==6.0.3",
    "python",
    str(GATE),
]


class CapabilityCIGateTest(unittest.TestCase):
    """The delta between the live aggregation and the committed baseline must be empty."""

    def setUp(self) -> None:
        self.baseline_path = (
            Path(__file__).resolve().parent.parent / "config" / "capability-inventory-baseline.json"
        )

    def _run_ci_gate(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*CI_GATE_COMMAND, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def test_delta_is_empty(self) -> None:
        """Every capability in the live aggregation must match the committed baseline."""
        self.assertTrue(
            self.baseline_path.is_file(),
            "capability-inventory-baseline.json is required; deleting it disables the gate",
        )
        payload = json.loads(self.baseline_path.read_text(encoding="utf-8"))
        baseline = CapabilityInventoryBaselineV2.model_validate(payload)
        snapshot = aggregate_capability_inventory()
        invalid = {
            descriptor.capability_id: validate_descriptor(descriptor)
            for descriptor in snapshot.admitted_supply_descriptors()
            if validate_descriptor(descriptor)
        }
        if invalid:
            details = [
                f"{capability_id}: {', '.join(gaps)}"
                for capability_id, gaps in sorted(invalid.items())
            ]
            self.fail(
                "capability inventory has shape-validation gaps; the baseline must not bless "
                "schema-invalid descriptors. Gaps:\n  " + "\n  ".join(details[:20])
            )
        delta = discover_inventory(snapshot, baseline.records)
        if not delta.is_empty:
            details: list[str] = []
            for cid in delta.new_capability_ids:
                details.append(f"NEW: {cid}")
            for cid in delta.changed_capability_ids:
                details.append(f"CHANGED: {cid}")
            for cid in delta.missing_capability_ids:
                details.append(f"MISSING: {cid}")
            self.fail(
                f"capability_inventory_delta is non-empty ({len(details)} changes). "
                "Update config/capability-inventory-baseline.json if the change is intentional. "
                "Changes:\n  " + "\n  ".join(details[:20])
            )

    def test_delta_ci_entrypoint_green_path_uses_minimal_ci_environment(self) -> None:
        """The exact CI invocation succeeds on the committed baseline."""
        proc = self._run_ci_gate()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("capability_inventory_delta: 0 new, 0 changed, 0 missing", proc.stdout)

    def test_delta_cli_red_fixture_fails_through_ci_entrypoint(self) -> None:
        """RED fixture: new/changed/missing capability surfaces fail the CI entrypoint."""
        snapshot = aggregate_capability_inventory()
        payload = inventory_baseline(snapshot).model_dump(mode="json")
        records = payload["records"]
        newly_observed_route = "api.headless.openrouter"
        changed_route = "codex.headless.full"
        missing_registered_route = "boutique.unregistered.launcher"
        self.assertIn(newly_observed_route, records)
        self.assertIn(changed_route, records)
        records.pop(newly_observed_route)
        records[changed_route]["fingerprint"] = "0" * 64
        records[missing_registered_route] = {
            "inventory_disposition": "admitted_supply",
            "fingerprint": "1" * 64,
        }
        payload["count"] = len(records)

        with tempfile.TemporaryDirectory() as tmpdir:
            baseline = Path(tmpdir) / "capability-inventory-baseline-red.json"
            baseline.write_text(
                json.dumps(payload, sort_keys=True),
                encoding="utf-8",
            )

            proc = self._run_ci_gate("--baseline", str(baseline))

        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        output = proc.stdout
        self.assertIn("capability_inventory_delta: 1 new, 1 changed, 1 missing", output)
        self.assertIn(f"new: {newly_observed_route}", output)
        self.assertIn(f"changed: {changed_route}", output)
        self.assertIn(f"missing: {missing_registered_route}", output)
        self.assertIn("NEXT: repair the descriptor source or regenerate", output)

    def test_committed_baseline_is_tagged_v2(self) -> None:
        payload = json.loads(self.baseline_path.read_text(encoding="utf-8"))

        baseline = CapabilityInventoryBaselineV2.model_validate(payload)

        self.assertEqual(baseline.schema_version, 2)
        self.assertEqual(baseline.count, 191)
        evaluator = baseline.records["local_compute.agentic_trust_evaluator_surface"]
        self.assertEqual(evaluator.inventory_disposition.value, "evidence_only_non_supply")

    def test_v1_baseline_surfaces_only_omitted_shapes_as_new(self) -> None:
        snapshot = aggregate_capability_inventory()
        raw = HISTORICAL_V1_BASELINE.read_bytes()
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            "e926961181f3ecae11674c6eaa01d47f6e17759e12bb6ca51429129e180acd45",
        )
        legacy = json.loads(raw)
        self.assertEqual(legacy["count"], 179)
        self.assertEqual(
            legacy["fingerprints"],
            {
                descriptor.capability_id: descriptor_fingerprint(descriptor)
                for descriptor in snapshot.admitted_supply_descriptors()
            },
        )
        registered = _load_inventory_baseline(HISTORICAL_V1_BASELINE)

        delta = discover_inventory(snapshot, registered)

        self.assertEqual(
            set(delta.new_capability_ids),
            {descriptor.shape_id for descriptor in snapshot.evidence_only_non_supply_descriptors()},
        )
        self.assertEqual(delta.changed_capability_ids, [])
        self.assertEqual(delta.missing_capability_ids, [])

    def test_v1_to_v2_wrapper_has_a_fixed_known_answer(self) -> None:
        legacy_hash = "623fdb606d2fa7c7f92b969e951a1367fe58d06a46c57c29ac91402457eeaa6b"

        self.assertEqual(
            wrap_supply_descriptor_fingerprint(legacy_hash),
            "4ea797143ee0282ae82de6de2fa3a874990802f455005825b9eaf48a87da9e68",
        )

    def test_baseline_json_schema_accepts_committed_v2_and_rejects_extra_fields(self) -> None:
        schema = json.loads(BASELINE_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        payload = json.loads(self.baseline_path.read_text(encoding="utf-8"))

        self.assertEqual(list(validator.iter_errors(payload)), [])
        poisoned = json.loads(json.dumps(payload))
        first = next(iter(poisoned["records"].values()))
        first["admission_score"] = 1
        self.assertTrue(list(validator.iter_errors(poisoned)))

        retagged = json.loads(json.dumps(payload))
        retagged["records"]["local_compute.agentic_trust_evaluator_surface"][
            "inventory_disposition"
        ] = "admitted_supply"
        self.assertTrue(list(validator.iter_errors(retagged)))
        with self.assertRaisesRegex(ValueError, "permanently non-supply"):
            CapabilityInventoryBaselineV2.model_validate(retagged)

        for forbidden_id in (
            "ROUTE/local_compute/agentic_trust_evaluator_surface",
            "AgenticTrustEvidenceReceiptV1",
            "agentic-trust-evidence-receipt-v1",
        ):
            with self.subTest(forbidden_id=forbidden_id):
                aliased = json.loads(json.dumps(payload))
                aliased["records"][forbidden_id] = {
                    "inventory_disposition": "admitted_supply",
                    "fingerprint": "a" * 64,
                }
                aliased["count"] += 1
                self.assertTrue(list(validator.iter_errors(aliased)))
                with self.assertRaisesRegex(ValueError, "cannot be admitted"):
                    CapabilityInventoryBaselineV2.model_validate(aliased)

        child = json.loads(json.dumps(payload))
        child["records"]["AgenticTrustEvidenceReceiptV1Child"] = {
            "inventory_disposition": "admitted_supply",
            "fingerprint": "b" * 64,
        }
        child["count"] += 1
        self.assertEqual(list(validator.iter_errors(child)), [])
        CapabilityInventoryBaselineV2.model_validate(child)

    def test_legacy_baseline_parser_rejects_malformed_and_future_documents(self) -> None:
        cases = {
            "array": [],
            "null": None,
            "scalar": 7,
            "future-version": {"schema_version": 3, "count": 0, "records": {}},
            "missing-key": {"count": 0},
            "bad-hash": {"count": 1, "fingerprints": {"route": "not-a-digest"}},
            "bool-count": {"count": False, "fingerprints": {}},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, payload in cases.items():
                with self.subTest(name=name):
                    baseline = Path(tmpdir) / f"{name}.json"
                    baseline.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        _load_inventory_baseline(baseline)

    def test_legacy_baseline_cannot_implicitly_admit_observation_identities(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for inventory_id in (
                "local_compute.agentic_trust_evaluator_surface",
                "AgenticTrustEvidenceReceiptV1",
            ):
                with self.subTest(inventory_id=inventory_id):
                    baseline = Path(tmpdir) / "legacy.json"
                    baseline.write_text(
                        json.dumps({"count": 1, "fingerprints": {inventory_id: "a" * 64}}),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ValueError, "evidence_only_non_supply"):
                        _load_inventory_baseline(baseline)

    def test_baseline_count_mismatch_fails_closed(self) -> None:
        payload = inventory_baseline(aggregate_capability_inventory()).model_dump(mode="json")
        payload["count"] += 1
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline = Path(tmpdir) / "capability-inventory-baseline-bad-count.json"
            baseline.write_text(json.dumps(payload), encoding="utf-8")

            proc = self._run_ci_gate("--baseline", str(baseline))

        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("capability_inventory_baseline_invalid", proc.stdout)
        self.assertIn("count", proc.stdout)

    def test_baseline_rejects_unknown_inventory_disposition(self) -> None:
        payload = inventory_baseline(aggregate_capability_inventory()).model_dump(mode="json")
        first = next(iter(payload["records"].values()))
        first["inventory_disposition"] = "observed_but_ambiguous"
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline = Path(tmpdir) / "capability-inventory-baseline-bad-tag.json"
            baseline.write_text(json.dumps(payload), encoding="utf-8")

            proc = self._run_ci_gate("--baseline", str(baseline))

        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("capability_inventory_baseline_invalid", proc.stdout)
        self.assertIn("inventory_disposition", proc.stdout)


if __name__ == "__main__":
    unittest.main()
