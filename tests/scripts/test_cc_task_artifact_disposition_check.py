"""Tests for scripts/cc-task-artifact-disposition-check.py — artifact disposition gate."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

# Import the module under test by path
import importlib.util
from datetime import UTC

import yaml

_spec = importlib.util.spec_from_file_location(
    "disposition_check",
    Path(__file__).resolve().parents[2] / "scripts" / "cc-task-artifact-disposition-check.py",
)
assert _spec and _spec.loader
disposition_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(disposition_check)


def _make_entry(
    artifact_id: str = "test-artifact",
    cls: str = "design",
    ceiling: str | None = None,
    disposition: str = "produced",
    task_id: str = "test-task",
) -> dict:
    ceiling = ceiling or disposition_check.CLASS_TO_CEILING.get(cls, "receipt")
    return {
        "artifact_id": artifact_id,
        "class": cls,
        "authority_ceiling": ceiling,
        "disposition": disposition,
        "disposition_at": "2026-05-09T21:00:00Z",
        "producer": "beta",
        "task_id": task_id,
        "authority_case": "CASE-TEST",
        "canonical_location": None,
        "debt": None,
    }


class TestGateLogic(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_path = Path(self.tmpdir) / "artifact-ledger.yaml"
        self.note_path = Path(self.tmpdir) / "test-task.md"
        self.note_path.write_text("---\nstatus: in_progress\n---\n# Test Task\n", encoding="utf-8")
        self._clear_env()

    def _clear_env(self) -> None:
        os.environ.pop("HAPAX_ARTIFACT_DISPOSITION_GATE_OFF", None)

    def _write_ledger(self, entries: list[dict]) -> None:
        self.ledger_path.write_text(
            yaml.dump(entries, default_flow_style=False, sort_keys=False), encoding="utf-8"
        )

    def test_no_ledger_file_passes(self) -> None:
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)

    def test_empty_ledger_passes(self) -> None:
        self.ledger_path.write_text("", encoding="utf-8")
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)

    def test_malformed_ledger_passes(self) -> None:
        self.ledger_path.write_text(":::not yaml{{{", encoding="utf-8")
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)

    def test_no_entries_for_task_passes(self) -> None:
        self._write_ledger([_make_entry(task_id="other-task")])
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)

    def test_gate_ceiling_promoted_passes(self) -> None:
        self._write_ledger([_make_entry(cls="design", disposition="promoted")])
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)

    def test_gate_ceiling_superseded_passes(self) -> None:
        self._write_ledger([_make_entry(cls="specification", disposition="superseded")])
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)

    def test_gate_ceiling_produced_blocks(self) -> None:
        self._write_ledger([_make_entry(cls="design", disposition="produced")])
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 2)

    def test_gate_ceiling_triaged_blocks(self) -> None:
        self._write_ledger([_make_entry(cls="research", disposition="triaged")])
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 2)

    def test_gate_ceiling_needs_normalization_blocks(self) -> None:
        self._write_ledger([_make_entry(cls="audit", disposition="needs_normalization")])
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 2)

    def test_gate_ceiling_debt_recorded_blocks(self) -> None:
        self._write_ledger([_make_entry(cls="design", disposition="debt_recorded")])
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 2)

    def test_advisory_ceiling_produced_warns(self) -> None:
        self._write_ledger([_make_entry(cls="evaluation", disposition="produced")])
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)

    def test_advisory_ceiling_promoted_passes(self) -> None:
        self._write_ledger([_make_entry(cls="planning", disposition="promoted")])
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)

    def test_advisory_ceiling_receipt_only_passes(self) -> None:
        self._write_ledger([_make_entry(cls="evaluation", disposition="receipt_only")])
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)

    def test_advisory_ceiling_refused_passes(self) -> None:
        self._write_ledger([_make_entry(cls="lab-journal", disposition="refused")])
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)

    def test_receipt_ceiling_produced_debt_record(self) -> None:
        self._write_ledger([_make_entry(cls="agent-return", disposition="produced")])
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)
        ledger = yaml.safe_load(self.ledger_path.read_text(encoding="utf-8"))
        self.assertIsNotNone(ledger[0].get("debt"))

    def test_receipt_ceiling_any_terminal_passes(self) -> None:
        for disp in ("promoted", "receipt_only", "refused", "superseded", "expired"):
            self._write_ledger([_make_entry(cls="relay-receipt", disposition=disp)])
            rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
            self.assertEqual(rc, 0, f"terminal disposition '{disp}' should pass")

    def test_mixed_ceilings_gate_blocks_wins(self) -> None:
        entries = [
            _make_entry(artifact_id="a1", cls="design", disposition="produced"),
            _make_entry(artifact_id="a2", cls="evaluation", disposition="produced"),
        ]
        self._write_ledger(entries)
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 2)

    def test_mixed_ceilings_no_gate_block_passes(self) -> None:
        entries = [
            _make_entry(artifact_id="a1", cls="evaluation", disposition="produced"),
            _make_entry(artifact_id="a2", cls="agent-return", disposition="produced"),
        ]
        self._write_ledger(entries)
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)


class TestDebtBypass(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_path = Path(self.tmpdir) / "artifact-ledger.yaml"
        self.note_path = Path(self.tmpdir) / "test-task.md"
        self.note_path.write_text("---\nstatus: in_progress\n---\n# Test Task\n", encoding="utf-8")
        os.environ.pop("HAPAX_ARTIFACT_DISPOSITION_GATE_OFF", None)

    def _write_ledger(self, entries: list[dict]) -> None:
        self.ledger_path.write_text(
            yaml.dump(entries, default_flow_style=False, sort_keys=False), encoding="utf-8"
        )

    def test_debt_bypass_gate_ceiling(self) -> None:
        self._write_ledger([_make_entry(cls="design", disposition="produced")])
        rc = disposition_check.gate(
            self.note_path,
            "test-task",
            debt_reason="emergency recovery",
            ledger_path=self.ledger_path,
            role="beta",
        )
        self.assertEqual(rc, 0)

    def test_debt_bypass_writes_ledger(self) -> None:
        self._write_ledger([_make_entry(cls="design", disposition="produced")])
        disposition_check.gate(
            self.note_path,
            "test-task",
            debt_reason="emergency",
            ledger_path=self.ledger_path,
            role="beta",
        )
        ledger = yaml.safe_load(self.ledger_path.read_text(encoding="utf-8"))
        debt = ledger[0].get("debt")
        self.assertIsNotNone(debt)
        self.assertEqual(debt["reason"], "emergency")
        self.assertEqual(debt["owner"], "beta")
        self.assertFalse(debt["resolved"])

    def test_debt_bypass_writes_task_note(self) -> None:
        self._write_ledger([_make_entry(cls="design", disposition="produced")])
        disposition_check.gate(
            self.note_path,
            "test-task",
            debt_reason="service outage",
            ledger_path=self.ledger_path,
            role="beta",
        )
        text = self.note_path.read_text(encoding="utf-8")
        self.assertIn("## Document pipeline debt", text)
        self.assertIn("service outage", text)

    def test_debt_expiry_defaults_72h(self) -> None:
        self._write_ledger([_make_entry(cls="design", disposition="produced")])
        disposition_check.gate(
            self.note_path,
            "test-task",
            debt_reason="test",
            ledger_path=self.ledger_path,
            role="beta",
        )
        ledger = yaml.safe_load(self.ledger_path.read_text(encoding="utf-8"))
        debt = ledger[0]["debt"]
        from datetime import datetime, timedelta

        created = datetime.strptime(debt["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        expires = datetime.strptime(debt["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        self.assertEqual(expires - created, timedelta(hours=72))

    def test_debt_owner_from_role(self) -> None:
        self._write_ledger([_make_entry(cls="design", disposition="produced")])
        disposition_check.gate(
            self.note_path,
            "test-task",
            debt_reason="test",
            ledger_path=self.ledger_path,
            role="gamma",
        )
        ledger = yaml.safe_load(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(ledger[0]["debt"]["owner"], "gamma")

    def test_debt_recovery_action_by_class(self) -> None:
        for cls, expected in disposition_check.DEFAULT_RECOVERY_ACTIONS.items():
            self._write_ledger([_make_entry(cls=cls, disposition="produced")])
            disposition_check.gate(
                self.note_path,
                "test-task",
                debt_reason="test",
                ledger_path=self.ledger_path,
                role="beta",
            )
            ledger = yaml.safe_load(self.ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(
                ledger[0]["debt"]["recovery_action"],
                expected,
                f"class={cls}",
            )


class TestBypassEnv(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_path = Path(self.tmpdir) / "artifact-ledger.yaml"
        self.note_path = Path(self.tmpdir) / "test-task.md"
        self.note_path.write_text("---\nstatus: in_progress\n---\n# Test\n", encoding="utf-8")

    def tearDown(self) -> None:
        os.environ.pop("HAPAX_ARTIFACT_DISPOSITION_GATE_OFF", None)

    def test_env_bypass_disables_gate(self) -> None:
        self.ledger_path.write_text(
            yaml.dump(
                [_make_entry(cls="design", disposition="produced")], default_flow_style=False
            ),
            encoding="utf-8",
        )
        os.environ["HAPAX_ARTIFACT_DISPOSITION_GATE_OFF"] = "1"
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)


class TestMultipleArtifacts(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.ledger_path = Path(self.tmpdir) / "artifact-ledger.yaml"
        self.note_path = Path(self.tmpdir) / "test-task.md"
        self.note_path.write_text("---\nstatus: in_progress\n---\n# Test\n", encoding="utf-8")
        os.environ.pop("HAPAX_ARTIFACT_DISPOSITION_GATE_OFF", None)

    def _write_ledger(self, entries: list[dict]) -> None:
        self.ledger_path.write_text(
            yaml.dump(entries, default_flow_style=False, sort_keys=False), encoding="utf-8"
        )

    def test_multiple_gate_artifacts_all_promoted(self) -> None:
        entries = [
            _make_entry(artifact_id="a1", cls="design", disposition="promoted"),
            _make_entry(artifact_id="a2", cls="specification", disposition="promoted"),
        ]
        self._write_ledger(entries)
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 0)

    def test_multiple_gate_artifacts_one_blocked(self) -> None:
        entries = [
            _make_entry(artifact_id="a1", cls="design", disposition="promoted"),
            _make_entry(artifact_id="a2", cls="specification", disposition="produced"),
        ]
        self._write_ledger(entries)
        rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 2)

    def test_error_message_lists_all_blocked(self) -> None:
        entries = [
            _make_entry(artifact_id="blocked-1", cls="design", disposition="produced"),
            _make_entry(artifact_id="blocked-2", cls="research", disposition="triaged"),
        ]
        self._write_ledger(entries)
        import io
        from contextlib import redirect_stderr

        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = disposition_check.gate(self.note_path, "test-task", ledger_path=self.ledger_path)
        self.assertEqual(rc, 2)
        stderr = buf.getvalue()
        self.assertIn("blocked-1", stderr)
        self.assertIn("blocked-2", stderr)


if __name__ == "__main__":
    unittest.main()
