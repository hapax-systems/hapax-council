from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cc-phase-advance.py"


def test_concurrent_phase_creator_is_not_truncated(tmp_path: Path) -> None:
    tasks = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks"
    active = tasks / "active"
    closed = tasks / "closed"
    requests = tmp_path / "Documents/Personal/20-projects/hapax-requests/active"
    active.mkdir(parents=True)
    closed.mkdir(parents=True)
    requests.mkdir(parents=True)
    request = requests / "REQ-phase.md"
    request.write_text("# Request\n\n## Phase 1\n\n## Phase 2\n", encoding="utf-8")
    current = closed / "demo-phase1.md"
    current.write_text(
        "---\n"
        "task_id: demo-phase1\n"
        'title: "Demo Phase 1"\n'
        "status: done\n"
        "priority: p1\n"
        "wsjf: 10\n"
        "kind: build\n"
        "parent_request: REQ-phase.md\n"
        "authority_case: CASE-TEST-001\n"
        "parent_spec: spec.md\n"
        "---\n",
        encoding="utf-8",
    )
    target = active / "demo-phase2.md"
    stage = active / ".hapax-transactions"
    stage.mkdir(mode=0o700)
    lock_path = stage / ".hapax-transaction.lock"
    lock_path.touch(mode=0o600)
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)

    with lock_path.open("r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        process = subprocess.Popen(
            [sys.executable, str(SCRIPT), str(current), "demo-phase1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        time.sleep(0.25)
        assert process.poll() is None, "phase advance did not wait on the task-note lock"
        target.write_text("concurrent authoritative task\n", encoding="utf-8")
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 0, stderr
    assert "lost identity race" in stdout
    assert target.read_text(encoding="utf-8") == "concurrent authoritative task\n"
    assert not (closed / "demo-phase2.md").exists()


def test_refused_next_phase_identity_is_not_recreated(tmp_path: Path) -> None:
    tasks = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks"
    closed = tasks / "closed"
    refused = tasks / "refused"
    requests = tmp_path / "Documents/Personal/20-projects/hapax-requests/active"
    for directory in (closed, refused, requests):
        directory.mkdir(parents=True)
    request = requests / "REQ-phase.md"
    request.write_text("# Request\n\n## Phase 1\n\n## Phase 2\n", encoding="utf-8")
    current = closed / "demo-phase1.md"
    current.write_text(
        "---\n"
        "task_id: demo-phase1\n"
        'title: "Demo Phase 1"\n'
        "status: done\n"
        "priority: p1\n"
        "wsjf: 10\n"
        "kind: build\n"
        "parent_request: REQ-phase.md\n"
        "authority_case: CASE-TEST-001\n"
        "parent_spec: spec.md\n"
        "---\n",
        encoding="utf-8",
    )
    refused_note = refused / "demo-phase2.md"
    refused_note.write_text(
        "---\ntask_id: demo-phase2\nstatus: refused\nparent_request: REQ-phase.md\n---\n",
        encoding="utf-8",
    )
    env = {**os.environ, "HOME": str(tmp_path)}

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(current), "demo-phase1"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "already exists" in result.stdout
    assert not (tasks / "active" / "demo-phase2.md").exists()
    assert refused_note.read_text(encoding="utf-8").startswith("---\n")
