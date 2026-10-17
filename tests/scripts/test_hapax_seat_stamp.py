"""Fail-closed tests for the seat's three-step stamp helper."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-seat-stamp"


@pytest.fixture
def stamp():
    spec = importlib.util.spec_from_loader(
        "hapax_seat_stamp", SourceFileLoader("hapax_seat_stamp", str(SCRIPT))
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def case(tmp_path, stamp, monkeypatch):
    note = tmp_path / "task.md"
    note.write_text(
        "---\ntype: cc-task\ntask_id: task\npr: 42\npr_repo: hapax-systems/hapax-council\n"
        "stage: S6_IMPLEMENTATION\nrelease_authorized: false\n"
        "authority_case: CASE-SDLC-REFORM-001\n---\nbody\n"
    )
    head = "a" * 40
    pr = {
        "number": 42,
        "headRefOid": head,
        "headRefName": "branch",
        "state": "OPEN",
        "isDraft": False,
        "labels": [{"name": "hold"}, {"name": "needs-human"}],
        "autoMergeRequest": None,
        "statusCheckRollup": [{"name": "all-green", "conclusion": "SUCCESS"}],
    }
    home = tmp_path / "fresh-home"
    home.mkdir()
    importers_xml = home / "importers.xml"
    importers_xml.write_text(
        '<testsuite><testcase classname="tests.shared.test_projected_path_writer_lock_coverage" name="test_lock"/>'
        '<testcase classname="tests.scripts.test_github_pr_status" name="test_status"/>'
        '<testcase classname="tests.scripts.test_hapax_seat_stamp" name="test_import"/></testsuite>'
    )
    inventory_xml = home / "inventory.xml"
    inventory_xml.write_text(
        '<testsuite><testcase classname="tests.test_inventory" name="test_inventory"/></testsuite>'
    )
    parent_xml = home / "parent.xml"
    parent_xml.write_text(
        '<testsuite><testcase classname="tests.test_parent" name="test_parent"/></testsuite>'
    )
    import hashlib

    def run_record(path):
        return {"junit_xml": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    evidence = tmp_path / "clean-home.json"
    evidence.write_text(
        json.dumps(
            {
                "pr": 42,
                "head_sha": head,
                "observed_at": datetime.now(UTC).isoformat(),
                "home": str(home),
                "uv_cache_dir": str(tmp_path / "uv-cache"),
                "importers": {"passed": 3, "failed_test_ids": [], **run_record(importers_xml)},
                "inventory": {"passed": 1, "failed_test_ids": [], **run_record(inventory_xml)},
                "parent": run_record(parent_xml),
                "parent_failed_test_ids": [],
                "named_test_files": [
                    "tests/shared/test_projected_path_writer_lock_coverage.py",
                    "tests/scripts/test_github_pr_status.py",
                ],
                "new_module_consumer_check": {
                    "name": "tests/scripts/test_hapax_seat_stamp.py::test_import",
                    "passed": True,
                },
            }
        )
    )
    monkeypatch.setattr(stamp, "review_blockers", lambda *_: ())
    monkeypatch.setattr(stamp, "receipt_blockers", lambda *_: ())
    return note, pr, evidence


@pytest.mark.parametrize(
    "change",
    [
        lambda p, e: p.update(headRefOid="b" * 40),
        lambda p, e: p.update(statusCheckRollup=[]),
        lambda p, e: p["labels"].clear(),
        lambda p, e: p.update(autoMergeRequest={"enabledAt": "now"}),
        lambda p, e: e.update(head_sha="b" * 40),
        lambda p, e: e.update(named_test_files=[]),
        lambda p, e: e.update(parent_failed_test_ids=["tests/x.py::test_fail"]),
        lambda p, e: e["new_module_consumer_check"].update(passed=False),
    ],
)
def test_preflight_refuses_partial_or_mismatched_evidence(case, stamp, change):
    note, pr, evidence = case
    data = json.loads(evidence.read_text())
    change(pr, data)
    evidence.write_text(json.dumps(data))
    with pytest.raises(stamp.StampRefusal):
        stamp.preflight(note, 42, pr, evidence)
    assert "release_authorized: false" in note.read_text()


def test_preflight_requires_canonical_review_and_receipt(case, stamp, monkeypatch):
    note, pr, evidence = case
    monkeypatch.setattr(stamp, "review_blockers", lambda *_: ("missing_review_dossier",))
    with pytest.raises(stamp.StampRefusal, match="missing_review_dossier"):
        stamp.preflight(note, 42, pr, evidence)
    monkeypatch.setattr(stamp, "review_blockers", lambda *_: ())
    monkeypatch.setattr(stamp, "receipt_blockers", lambda *_: ("missing_acceptance_receipt",))
    with pytest.raises(stamp.StampRefusal, match="missing_acceptance_receipt"):
        stamp.preflight(note, 42, pr, evidence)


def test_missing_hold_refused(case, stamp):
    note, pr, evidence = case
    pr["labels"] = []
    with pytest.raises(stamp.StampRefusal, match="hold_label_missing"):
        stamp.preflight(note, 42, pr, evidence)


def test_measured_junit_hash_and_receipt_head_required(case, stamp):
    note, pr, evidence = case
    data = json.loads(evidence.read_text())
    importers_xml = Path(data["importers"]["junit_xml"])
    original_xml = importers_xml.read_text()
    importers_xml.write_text("<testsuite/>")
    with pytest.raises(stamp.StampRefusal, match="junit_hash_mismatch"):
        stamp.preflight(note, 42, pr, evidence)
    importers_xml.write_text(original_xml)
    (note.parent / "task.acceptance.yaml").write_text("pr: 42\nhead_sha: " + "b" * 40 + "\n")
    with pytest.raises(stamp.StampRefusal, match="acceptance_exact_head_mismatch"):
        stamp.preflight(note, 42, pr, evidence)


def test_three_steps_read_back_and_stop_on_partial_failure(case, stamp, monkeypatch):
    note, pr, evidence = case
    plan = stamp.preflight(note, 42, pr, evidence)
    calls = []

    def runner(*args):
        calls.append(args)
        if args[:2] == ("cc-stage-advance", "task"):
            note.write_text(note.read_text().replace("S6_IMPLEMENTATION", "S7_RELEASE"))
        if args[:3] == ("gh", "pr", "edit"):
            pr["labels"] = []

    stamp.perform(plan, lambda: pr, runner)
    text = note.read_text()
    assert text.count("release_authorized: true") == 1
    assert "stage: S7_RELEASE" in text
    assert len(calls) == 2
    assert pr["labels"] == []

    # When stage advance claims success but does not change the row, labels stay held.
    note.write_text(note.read_text().replace("S7_RELEASE", "S6_IMPLEMENTATION"))
    note.write_text(
        note.read_text().replace("release_authorized: true", "release_authorized: false")
    )
    pr["labels"] = [{"name": "hold"}]
    plan = stamp.preflight(note, 42, pr, evidence)
    calls.clear()
    with pytest.raises(stamp.StampRefusal, match="stage_readback"):
        stamp.perform(plan, lambda: pr, lambda *args: calls.append(args))
    assert all(args[:3] != ("gh", "pr", "edit") for args in calls)


def test_duplicate_release_key_refused(case, stamp):
    note, pr, evidence = case
    note.write_text(
        note.read_text().replace(
            "release_authorized: false", "release_authorized: false\nrelease_authorized: null"
        )
    )
    with pytest.raises(stamp.StampRefusal, match="duplicate"):
        stamp.preflight(note, 42, pr, evidence)


def test_label_readback_refuses_claimed_success_without_removal(case, stamp):
    note, pr, evidence = case
    plan = stamp.preflight(note, 42, pr, evidence)

    def runner(*args):
        if args[0] == "cc-stage-advance":
            note.write_text(note.read_text().replace("S6_IMPLEMENTATION", "S7_RELEASE"))
        # gh reports success but does not remove hold.

    with pytest.raises(stamp.StampRefusal, match="label_readback_failed"):
        stamp.perform(plan, lambda: pr, runner)
    assert "release_authorized_head_sha: " + "a" * 40 in note.read_text()
    assert pr["labels"] == [{"name": "hold"}, {"name": "needs-human"}]
