"""Tests for scripts/document-pipeline-triage — artifact ledger triage CLI."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml

_triage_path = Path(__file__).resolve().parents[2] / "scripts" / "document-pipeline-triage"
_loader = importlib.machinery.SourceFileLoader("triage", str(_triage_path))
_spec = importlib.util.spec_from_loader("triage", _loader)
assert _spec and _spec.loader
triage_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(triage_mod)


class TestTriageCommand(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_path = Path(self.tmpdir) / "artifact-ledger.yaml"

    def test_create_new_entry(self) -> None:
        triage_mod.triage(
            artifact_id="test-design-001",
            artifact_class="design",
            disposition="produced",
            task_id="task-1",
            authority_case="CASE-1",
            producer="beta",
            canonical_location="30-areas/hapax/test.md",
            ledger_path=self.ledger_path,
        )
        ledger = yaml.safe_load(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(len(ledger), 1)
        entry = ledger[0]
        self.assertEqual(entry["artifact_id"], "test-design-001")
        self.assertEqual(entry["class"], "design")
        self.assertEqual(entry["authority_ceiling"], "gate")
        self.assertEqual(entry["disposition"], "produced")
        self.assertEqual(entry["task_id"], "task-1")
        self.assertEqual(entry["producer"], "beta")

    def test_update_existing_entry(self) -> None:
        triage_mod.triage(
            artifact_id="test-design-001",
            artifact_class="design",
            disposition="produced",
            task_id="task-1",
            ledger_path=self.ledger_path,
        )
        triage_mod.triage(
            artifact_id="test-design-001",
            artifact_class="design",
            disposition="promoted",
            ledger_path=self.ledger_path,
        )
        ledger = yaml.safe_load(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["disposition"], "promoted")

    def test_merge_fields_no_overwrite(self) -> None:
        triage_mod.triage(
            artifact_id="test-001",
            artifact_class="design",
            disposition="produced",
            task_id="task-1",
            producer="gamma",
            ledger_path=self.ledger_path,
        )
        triage_mod.triage(
            artifact_id="test-001",
            artifact_class="design",
            disposition="promoted",
            task_id="task-2",
            ledger_path=self.ledger_path,
        )
        ledger = yaml.safe_load(self.ledger_path.read_text(encoding="utf-8"))
        # task_id should NOT be overwritten because existing is non-None
        self.assertEqual(ledger[0]["task_id"], "task-1")
        # producer should still be gamma
        self.assertEqual(ledger[0]["producer"], "gamma")

    def test_creates_directory_if_missing(self) -> None:
        nested = Path(self.tmpdir) / "a" / "b" / "artifact-ledger.yaml"
        triage_mod.triage(
            artifact_id="test-001",
            artifact_class="design",
            disposition="produced",
            ledger_path=nested,
        )
        self.assertTrue(nested.is_file())

    def test_atomic_write(self) -> None:
        triage_mod.triage(
            artifact_id="test-001",
            artifact_class="design",
            disposition="produced",
            ledger_path=self.ledger_path,
        )
        # No .tmp file should remain after write
        tmp = self.ledger_path.with_suffix(".yaml.tmp")
        self.assertFalse(tmp.exists())
        # Ledger should be valid YAML
        data = yaml.safe_load(self.ledger_path.read_text(encoding="utf-8"))
        self.assertIsInstance(data, list)

    def test_invalid_class_rejected(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            triage_mod.triage(
                artifact_id="test-001",
                artifact_class="bogus",
                disposition="produced",
                ledger_path=self.ledger_path,
            )
        self.assertEqual(cm.exception.code, 1)

    def test_invalid_disposition_rejected(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            triage_mod.triage(
                artifact_id="test-001",
                artifact_class="design",
                disposition="bogus",
                ledger_path=self.ledger_path,
            )
        self.assertEqual(cm.exception.code, 1)

    def test_authority_ceiling_derived(self) -> None:
        for cls, expected_ceiling in triage_mod.CLASS_TO_CEILING.items():
            self.ledger_path.unlink(missing_ok=True)
            triage_mod.triage(
                artifact_id=f"test-{cls}",
                artifact_class=cls,
                disposition="produced",
                ledger_path=self.ledger_path,
            )
            ledger = yaml.safe_load(self.ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(
                ledger[0]["authority_ceiling"],
                expected_ceiling,
                f"class={cls}",
            )

    def test_roundtrip_preserves_entries(self) -> None:
        for i in range(3):
            triage_mod.triage(
                artifact_id=f"artifact-{i}",
                artifact_class="design",
                disposition="produced",
                task_id="task-1",
                ledger_path=self.ledger_path,
            )
        # Update the second one
        triage_mod.triage(
            artifact_id="artifact-1",
            artifact_class="design",
            disposition="promoted",
            ledger_path=self.ledger_path,
        )
        ledger = yaml.safe_load(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(len(ledger), 3)
        ids = [e["artifact_id"] for e in ledger]
        self.assertEqual(ids, ["artifact-0", "artifact-1", "artifact-2"])
        self.assertEqual(ledger[1]["disposition"], "promoted")


if __name__ == "__main__":
    unittest.main()
