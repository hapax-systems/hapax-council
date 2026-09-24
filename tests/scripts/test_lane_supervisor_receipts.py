"""Claim receipts and the runbook recheck must preserve the observed file identity."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.scripts.test_lane_supervisor_session_liveness import (
    ROOT,
    SID,
    assert_no_recovery,
    claims_snapshot,
    run,
    setup_lane,
)

RUNBOOK = ROOT / "docs/runbooks/lane-death-forensics.md"


def recheck(env, receipt_path):
    # Execute the published command, so documentation and the producer cannot
    # independently pass while disagreeing about the file being hashed.
    command = RUNBOOK.read_text().split("python3 - '<receipt-path>' <<'PY'\n", 1)[1]
    command = command.split("\nPY\n", 1)[0]
    return subprocess.run(
        [sys.executable, "-", str(receipt_path)],
        input=command,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.parametrize("suffix", ["", f"-{SID}", "-12345"])
def test_observed_claim_path_round_trips_through_runbook(tmp_path, suffix):
    env, calls = setup_lane(tmp_path, pane=True)
    cache = Path(env["HOME"]) / ".cache/hapax"
    marker = cache / f"cc-active-task-delta{suffix}"
    if suffix:
        (cache / "cc-active-task-delta").rename(marker)
    epoch = cache / f"cc-claim-epoch-delta{suffix}"
    epoch.write_text("17|preserve-epoch\n")
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    receipts = list((tmp_path / "lanebus/delta").glob("*claim-holder*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["session_id"] == (SID if suffix == f"-{SID}" else None)
    assert receipt["claim_path"] == str(marker)
    assert receipt["claim_sha256"] == hashlib.sha256(marker.read_bytes()).hexdigest()
    assert receipt["epoch_sha256"] == hashlib.sha256(epoch.read_bytes()).hexdigest()
    checked = recheck(env, receipts[0])
    assert checked.returncode == 0, checked.stderr
    assert f"claim_sha256 match {marker}" in checked.stdout
    assert f"epoch_sha256 match {epoch}" in checked.stdout
    assert "note_sha256 match " in checked.stdout
    assert "changed/missing" not in checked.stdout


@pytest.mark.parametrize(
    "invalid",
    ["missing", "outside", "relative", "traversal", "sibling", "claim_symlink", "epoch_symlink"],
)
def test_runbook_refuses_unbounded_receipt_path(tmp_path, invalid):
    env, _ = setup_lane(tmp_path)
    cache = Path(env["HOME"]) / ".cache/hapax"
    marker = cache / "cc-active-task-delta-12345"
    marker.write_text("session-task\n")
    target = tmp_path / "outside-claim"
    target.write_text("unrelated file\n")
    supplied = str(marker)
    if invalid == "outside":
        supplied = str(target)
    elif invalid == "relative":
        supplied = marker.name
    elif invalid == "traversal":
        supplied = str(cache / ".." / "hapax" / marker.name)
    elif invalid == "sibling":
        supplied = str(cache / "cc-active-task-epsilon-12345")
    elif invalid == "claim_symlink":
        marker.unlink()
        marker.symlink_to(target)
    elif invalid == "epoch_symlink":
        (cache / "cc-claim-epoch-delta-12345").symlink_to(target)
    receipt = dict(lane="delta", session_id=None, task_id=None, claim_path=supplied)
    if invalid == "missing":
        del receipt["claim_path"]
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    result = recheck(env, receipt_path)
    assert result.returncode != 0
    assert "receipt_path_unresolved" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("sidecar", ["claim", "epoch"])
def test_symlinked_receipt_input_holds_without_redirecting_evidence(tmp_path, sidecar):
    env, calls = setup_lane(tmp_path, pane=True)
    cache = Path(env["HOME"]) / ".cache/hapax"
    marker = cache / "cc-active-task-delta-12345"
    (cache / "cc-active-task-delta").rename(marker)
    target = tmp_path / "outside-input"
    target.write_text("session-task\n")
    if sidecar == "claim":
        marker.unlink()
        marker.symlink_to(target)
    else:
        (cache / "cc-claim-epoch-delta-12345").symlink_to(target)
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    assert "claim_orphan_unresolved:observation_failed:ValueError" in result.stdout
    assert not list((tmp_path / "lanebus/delta").glob("*claim-holder*.json"))


@pytest.mark.parametrize("task", ["missing", None, "../outside"])
def test_runbook_partial_task_is_typed_hold(tmp_path, task):
    env, _ = setup_lane(tmp_path)
    marker = Path(env["HOME"]) / ".cache/hapax/cc-active-task-delta"
    receipt = dict(lane="delta", claim_path=str(marker))
    if task != "missing":
        receipt["task_id"] = task
    path = tmp_path / "partial-receipt.json"
    path.write_text(json.dumps(receipt))
    result = recheck(env, path)
    assert result.returncode != 0
    assert "receipt_task_unresolved:" in result.stderr
    assert "Traceback" not in result.stderr
