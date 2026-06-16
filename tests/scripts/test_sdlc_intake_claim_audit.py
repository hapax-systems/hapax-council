from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "sdlc-intake-claim-audit"


def _audit_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("sdlc_intake_claim_audit", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def _task(tasks_dir: Path, task_id: str, frontmatter: str) -> None:
    (tasks_dir / f"{task_id}.md").write_text(f"---\n{frontmatter}---\nbody\n", encoding="utf-8")


def test_report_counts_flow_states_and_stranded_items(tmp_path: Path) -> None:
    audit = _audit_module()
    tasks = tmp_path / "tasks"
    cache = tmp_path / "cache"
    pid_dir = tmp_path / "pids"
    tasks.mkdir()
    cache.mkdir()
    pid_dir.mkdir()
    _task(
        tasks,
        "p0-offered",
        "task_id: p0-offered\nstatus: offered\nassigned_to: unassigned\npriority: p0\n",
    )
    _task(
        tasks,
        "p0-claimed-unowned",
        "task_id: p0-claimed-unowned\nstatus: claimed\nassigned_to: unassigned\npriority: p0\n",
    )
    _task(
        tasks,
        "remediation-blocked",
        (
            "task_id: remediation-blocked\n"
            "title: Repair request decomposition admission\n"
            "status: blocked\nassigned_to: unassigned\npriority: p2\nkind: remediation\n"
        ),
    )
    _task(
        tasks,
        "pr-open",
        "task_id: pr-open\nstatus: pr_open\nassigned_to: cx-red\npriority: p0\n",
    )
    missing_claim = cache / "cc-active-task-delta"
    blocked_claim = cache / "cc-active-task-gamma-session"
    missing_claim.write_text("missing-task\n", encoding="utf-8")
    blocked_claim.write_text("remediation-blocked\n", encoding="utf-8")
    os.utime(missing_claim, (1, 1))
    os.utime(blocked_claim, (1, 1))

    report = audit.build_report(tasks, cache, tmp_path / "missing-state.json", pid_dir)

    assert report["counts"]["offered"] == 1
    assert report["counts"]["claimed"] == 1
    assert report["counts"]["blocked"] == 1
    assert report["counts"]["pr_open"] == 1
    assert report["counts"]["remediation"] == 1
    assert report["counts"]["stale_claim"] == 2
    assert report["counts"]["silent_stranded_p0_or_remediation"] == 1
    assert report["silent_stranded_p0_or_remediation"][0]["task_id"] == "p0-claimed-unowned"
    assert report["silent_stranded_p0_or_remediation"][0]["reason"] == "missing_assigned_lane"
    reasons = {item["task_id"]: item["reason"] for item in report["stale_claims"]}
    assert reasons["missing-task"] == "task_not_active"
    assert reasons["remediation-blocked"] == "blocked-unassigned"


def test_report_keeps_fresh_claim_churn_in_grace_bucket(tmp_path: Path) -> None:
    audit = _audit_module()
    tasks = tmp_path / "tasks"
    cache = tmp_path / "cache"
    tasks.mkdir()
    cache.mkdir()
    (cache / "cc-active-task-delta").write_text("missing-task\n", encoding="utf-8")

    report = audit.build_report(tasks, cache, tmp_path / "missing-state.json")

    assert report["counts"]["stale_claim"] == 0
    assert report["counts"]["claim_grace"] == 1


def test_assigned_p0_without_live_lane_pickup_is_silent_stranded(tmp_path: Path) -> None:
    audit = _audit_module()
    tasks = tmp_path / "tasks"
    cache = tmp_path / "cache"
    pid_dir = tmp_path / "pids"
    tasks.mkdir()
    cache.mkdir()
    pid_dir.mkdir()
    _task(
        tasks,
        "assigned-p0",
        "task_id: assigned-p0\nstatus: claimed\nassigned_to: gamma\npriority: p0\n",
    )
    (cache / "cc-active-task-gamma").write_text("assigned-p0\n", encoding="utf-8")

    report = audit.build_report(tasks, cache, tmp_path / "missing-state.json", pid_dir)

    assert report["counts"]["silent_stranded_p0_or_remediation"] == 1
    stranded = report["silent_stranded_p0_or_remediation"][0]
    assert stranded["task_id"] == "assigned-p0"
    assert stranded["reason"] == "assigned_lane_not_live"
    assert stranded["pickup_evidence"][0]["kind"] == "claim_file"


def test_coordinator_live_lane_claim_satisfies_pickup(tmp_path: Path) -> None:
    audit = _audit_module()
    tasks = tmp_path / "tasks"
    cache = tmp_path / "cache"
    pid_dir = tmp_path / "pids"
    state = tmp_path / "state.json"
    tasks.mkdir()
    cache.mkdir()
    pid_dir.mkdir()
    _task(
        tasks,
        "assigned-p0",
        "task_id: assigned-p0\nstatus: in_progress\nassigned_to: gamma\npriority: p0\n",
    )
    state.write_text(
        json.dumps({"lanes": {"gamma": {"alive": True, "claimed_task": "assigned-p0"}}}),
        encoding="utf-8",
    )

    report = audit.build_report(tasks, cache, state, pid_dir)

    assert report["counts"]["silent_stranded_p0_or_remediation"] == 0


def test_stale_coordinator_lane_claim_does_not_satisfy_pickup(tmp_path: Path) -> None:
    audit = _audit_module()
    tasks = tmp_path / "tasks"
    cache = tmp_path / "cache"
    pid_dir = tmp_path / "pids"
    state = tmp_path / "state.json"
    tasks.mkdir()
    cache.mkdir()
    pid_dir.mkdir()
    _task(
        tasks,
        "assigned-p0",
        "task_id: assigned-p0\nstatus: in_progress\nassigned_to: gamma\npriority: p0\n",
    )
    state.write_text(
        json.dumps(
            {"timestamp": 1, "lanes": {"gamma": {"alive": True, "claimed_task": "assigned-p0"}}}
        ),
        encoding="utf-8",
    )
    os.utime(state, (1, 1))

    report = audit.build_report(
        tasks,
        cache,
        state,
        pid_dir,
        coordinator_state_max_age_seconds=60,
    )

    assert report["counts"]["silent_stranded_p0_or_remediation"] == 1
    assert report["coordinator_state_status"]["fresh"] is False
    assert "file_mtime_stale" in report["coordinator_state_status"]["reasons"]
    stranded = report["silent_stranded_p0_or_remediation"][0]
    assert stranded["task_id"] == "assigned-p0"
    assert stranded["pickup_evidence"] == [
        {"kind": "stale_coordinator_lane_claim", "role": "gamma"}
    ]


def test_live_headless_launcher_satisfies_pickup_without_coordinator_state(
    tmp_path: Path,
) -> None:
    audit = _audit_module()
    tasks = tmp_path / "tasks"
    cache = tmp_path / "cache"
    pid_dir = tmp_path / "pids"
    tasks.mkdir()
    cache.mkdir()
    pid_dir.mkdir()
    _task(
        tasks,
        "assigned-p0",
        "task_id: assigned-p0\nstatus: in_progress\nassigned_to: ut-audit-live\npriority: p0\n",
    )
    proc = subprocess.Popen(
        [
            "bash",
            "-c",
            "exec -a hapax-claude-headless python3 -c 'import time; time.sleep(60)' --task assigned-p0 ut-audit-live",
        ]
    )
    try:
        time.sleep(0.2)
        report = audit.build_report(tasks, cache, tmp_path / "missing-state.json", pid_dir)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    assert report["counts"]["silent_stranded_p0_or_remediation"] == 0


def test_offered_notification_p0_counts_as_undrained_not_silent(tmp_path: Path) -> None:
    audit = _audit_module()
    tasks = tmp_path / "tasks"
    cache = tmp_path / "cache"
    pid_dir = tmp_path / "pids"
    tasks.mkdir()
    cache.mkdir()
    pid_dir.mkdir()
    _task(
        tasks,
        "p0-incident-demo",
        (
            "task_id: p0-incident-demo\nstatus: offered\nassigned_to: unassigned\n"
            "priority: p0\nkind: recovery_triage\ntags: [incident-intake, technical-alert]\n"
        ),
    )

    report = audit.build_report(tasks, cache, tmp_path / "missing-state.json", pid_dir)

    assert report["counts"]["silent_stranded_p0_or_remediation"] == 0
    assert report["counts"]["undrained_p0_incident_intake"] == 1
    assert report["undrained_p0_incident_intake"][0]["reason"] == "offered_not_picked_up"


def test_failed_decompose_remediation_has_first_class_undrained_path(tmp_path: Path) -> None:
    audit = _audit_module()
    tasks = tmp_path / "tasks"
    cache = tmp_path / "cache"
    pid_dir = tmp_path / "pids"
    tasks.mkdir()
    cache.mkdir()
    pid_dir.mkdir()
    _task(
        tasks,
        "request-decompose-admission-blocked-req-x-abcd1234",
        (
            "task_id: request-decompose-admission-blocked-req-x-abcd1234\n"
            "title: Repair request decomposition admission\n"
            "status: offered\nassigned_to: unassigned\npriority: p1\n"
            "kind: recovery_triage\n"
            "parent_request: REQ-X.md\n"
            "decompose_failure_class: admission_blocked\n"
            "decompose_failure_reasons: [missing_cctv_intake_receipt]\n"
            "tags: [request-decompose-remediation, auto-remediation]\n"
        ),
    )

    report = audit.build_report(tasks, cache, tmp_path / "missing-state.json", pid_dir)

    assert report["counts"]["decompose_remediation"] == 1
    assert report["decompose_remediation_by_status"] == {"offered": 1}
    assert report["counts"]["undrained_decompose_remediation"] == 1
    item = report["undrained_decompose_remediation"][0]
    assert item["task_id"] == "request-decompose-admission-blocked-req-x-abcd1234"
    assert item["parent_request"] == "REQ-X.md"
    assert item["decompose_failure_class"] == "admission_blocked"
    assert item["reason"] == "offered_not_picked_up"


def test_claim_file_may_reference_note_stem_alias(tmp_path: Path) -> None:
    audit = _audit_module()
    tasks = tmp_path / "tasks"
    cache = tmp_path / "cache"
    tasks.mkdir()
    cache.mkdir()
    _task(
        tasks,
        "long-filename-descriptor",
        "task_id: short-task\nstatus: claimed\nassigned_to: gamma\npriority: p0\n",
    )
    (cache / "cc-active-task-gamma").write_text("long-filename-descriptor\n", encoding="utf-8")

    report = audit.build_report(tasks, cache, tmp_path / "missing-state.json")

    assert report["counts"]["stale_claim"] == 0
    assert report["counts"]["claim_grace"] == 0


def test_claim_role_preserves_hyphenated_lane_names(tmp_path: Path) -> None:
    audit = _audit_module()

    assert audit.claim_role(tmp_path / "cc-active-task-cx-red") == "cx-red"
    assert (
        audit.claim_role(tmp_path / "cc-active-task-cx-red-9b6ba5ca-513c-41aa-9900-d3026b42aad1")
        == "cx-red"
    )


def test_cli_writes_report(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    cache = tmp_path / "cache"
    out = tmp_path / "report.json"
    tasks.mkdir()
    cache.mkdir()
    _task(
        tasks,
        "claimed",
        "task_id: claimed\nstatus: claimed\nassigned_to: alpha\npriority: p1\n",
    )

    subprocess.run(
        [
            str(SCRIPT),
            "--tasks-dir",
            str(tasks),
            "--cache-dir",
            str(cache),
            "--output",
            str(out),
        ],
        check=True,
    )

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["counts"]["claimed"] == 1
    assert report["counts"]["active_total"] == 1
