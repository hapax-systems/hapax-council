"""The CI gate — the capability_surface_delta failing-check.

If a capability is added, changed, or removed from any of the 7 vocabularies without updating the
committed baseline (config/capability-inventory-baseline.json), this test FAILS. That is the
meta-priority enforcement: every boutique/missing/unregistered capability surface becomes a build
failure, not a manual find. To update after an intentional change, regenerate the baseline.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from shared.capability_harness_descriptor import (
    descriptor_fingerprint,
    discover,
    validate_descriptor,
)
from shared.capability_inventory import main as inventory_main
from shared.capability_inventory_aggregator import aggregate_all_capabilities


class CapabilityCIGateTest(unittest.TestCase):
    """The delta between the live aggregation and the committed baseline must be empty."""

    def setUp(self) -> None:
        self.baseline_path = (
            Path(__file__).resolve().parent.parent / "config" / "capability-inventory-baseline.json"
        )

    def test_delta_is_empty(self) -> None:
        """Every capability in the live aggregation must match the committed baseline."""
        self.assertTrue(
            self.baseline_path.is_file(),
            "capability-inventory-baseline.json is required; deleting it disables the gate",
        )
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

    def test_delta_cli_red_fixture_fails_when_route_missing_from_baseline(self) -> None:
        """RED fixture: an observed dispatch route omitted from the baseline fails CI."""
        observed = aggregate_all_capabilities()
        fingerprints = {d.capability_id: descriptor_fingerprint(d) for d in observed}
        missing_route = "api.headless.openrouter"
        self.assertIn(missing_route, fingerprints)
        fingerprints.pop(missing_route)

        with tempfile.TemporaryDirectory() as tmpdir:
            baseline = Path(tmpdir) / "capability-inventory-baseline-red.json"
            baseline.write_text(
                json.dumps(
                    {"count": len(fingerprints), "fingerprints": fingerprints},
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = inventory_main(["--delta", "--baseline", str(baseline)])

        self.assertEqual(rc, 1)
        output = stdout.getvalue()
        self.assertIn("capability_surface_delta: 1 new, 0 changed, 0 missing", output)
        self.assertIn(f"new: {missing_route}", output)


if __name__ == "__main__":
    unittest.main()
