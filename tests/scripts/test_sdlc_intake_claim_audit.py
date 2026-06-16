from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
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
    tasks.mkdir()
    cache.mkdir()
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

    report = audit.build_report(tasks, cache, tmp_path / "missing-state.json")

    assert report["counts"]["offered"] == 1
    assert report["counts"]["claimed"] == 1
    assert report["counts"]["blocked"] == 1
    assert report["counts"]["pr_open"] == 1
    assert report["counts"]["remediation"] == 1
    assert report["counts"]["stale_claim"] == 2
    assert report["counts"]["silent_stranded_p0_or_remediation"] == 1
    assert report["silent_stranded_p0_or_remediation"][0]["task_id"] == "p0-claimed-unowned"
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
