"""The CI gate — the capability_surface_delta failing-check.

If a capability is added, changed, or removed from any of the 7 vocabularies without updating the
committed baseline (config/capability-inventory-baseline.json), this test FAILS. That is the
meta-priority enforcement: every boutique/missing/unregistered capability surface becomes a build
failure, not a manual find. To update after an intentional change, regenerate the baseline.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from shared.capability_harness_descriptor import discover, validate_descriptor
from shared.capability_inventory_aggregator import aggregate_all_capabilities


class CapabilityCIGateTest(unittest.TestCase):
    """The delta between the live aggregation and the committed baseline must be empty."""

    def setUp(self) -> None:
        self.baseline_path = (
            Path(__file__).resolve().parent.parent / "config" / "capability-inventory-baseline.json"
        )
        if not self.baseline_path.is_file():
            self.skipTest("baseline not committed yet")

    def test_delta_is_empty(self) -> None:
        """Every capability in the live aggregation must match the committed baseline."""
        payload = json.loads(self.baseline_path.read_text(encoding="utf-8"))
        registered = payload.get("fingerprints", {})
        observed = aggregate_all_capabilities()
        invalid = {
            descriptor.capability_id: validate_descriptor(descriptor)
            for descriptor in observed
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
        delta = discover(observed, registered)
        if not delta.is_empty:
            details: list[str] = []
            for cid in delta.new_capability_ids:
                details.append(f"NEW: {cid}")
            for cid in delta.changed_capability_ids:
                details.append(f"CHANGED: {cid}")
            for cid in delta.missing_capability_ids:
                details.append(f"MISSING: {cid}")
            self.fail(
                f"capability_surface_delta is non-empty ({len(details)} changes). "
                "Update config/capability-inventory-baseline.json if the change is intentional. "
                "Changes:\n  " + "\n  ".join(details[:20])
            )


if __name__ == "__main__":
    unittest.main()
