"""Tests for scripts/cc-stage-advance — the council-side AVSDLC stage-setter.

Self-contained (no shared conftest): each test builds a synthetic vault under a
pinned HOME and invokes the script via subprocess. Coordination reform Phase 2.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "cc-stage-advance"


def _make_task(
    home: Path,
    task_id: str,
    *,
    stage: str | None = "S6_IMPLEMENTATION",
    authority_case: str | None = "CASE-TEST-001",
    status: str = "in_progress",
) -> Path:
    active = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    active.mkdir(parents=True, exist_ok=True)
    note = active / f"{task_id}-x.md"
    stage_line = f"stage: {stage}\n" if stage else ""
    ac_line = f"authority_case: {authority_case}\n" if authority_case else ""
    note.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "T"
status: {status}
assigned_to: alpha
{ac_line}{stage_line}updated_at: 2026-01-01T00:00:00Z
---

# T

## Session log
""",
        encoding="utf-8",
    )
    return note


def _run(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "alpha"
    # Redirect the coord SSOT log under the test HOME so emitting a stage event
    # never touches /var/lib/hapax/coord during the test.
    env["HAPAX_COORD_DIR"] = str(home / ".cache" / "hapax" / "coord")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def _note(home: Path, task_id: str) -> Path:
    active = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    return next(iter(active.glob(f"{task_id}-*.md")))


class TestStageAdvance:
    def test_forward_advance_sets_stage_and_ledgers(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t1")
        r = _run(tmp_path, "t1", "S7_RELEASE")
        assert r.returncode == 0, r.stderr
        assert "stage: S7_RELEASE" in _note(tmp_path, "t1").read_text()
        ledger = tmp_path / ".cache" / "hapax" / "authority-case-ledger.jsonl"
        assert ledger.exists()
        rec = json.loads(ledger.read_text().splitlines()[-1])
        assert rec["kind"] == "stage_transition"
        assert rec["from_stage"] == "S6_IMPLEMENTATION"
        assert rec["to_stage"] == "S7_RELEASE"
        assert rec["authority_case"] == "CASE-TEST-001"

    def test_backward_refused_without_flag(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t2", stage="S7_RELEASE")
        r = _run(tmp_path, "t2", "S6_IMPLEMENTATION")
        assert r.returncode == 2
        assert "backward" in r.stderr.lower()

    def test_backward_allowed_with_flag(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t3", stage="S7_RELEASE")
        r = _run(tmp_path, "t3", "S6_IMPLEMENTATION", "--allow-backward")
        assert r.returncode == 0, r.stderr

    def test_invalid_stage_refused(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t4")
        r = _run(tmp_path, "t4", "PHASE_SEVEN")
        assert r.returncode == 2

    def test_missing_authority_case_refused(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t5", authority_case=None)
        r = _run(tmp_path, "t5", "S7_RELEASE")
        assert r.returncode == 2
        assert "authority_case" in r.stderr

    def test_backfill_stage_when_absent(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t6", stage=None)
        r = _run(tmp_path, "t6", "S6_IMPLEMENTATION")
        assert r.returncode == 0, r.stderr
        assert "stage: S6_IMPLEMENTATION" in _note(tmp_path, "t6").read_text()

    def test_not_found_is_error(self, tmp_path: Path) -> None:
        (tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active").mkdir(
            parents=True
        )
        r = _run(tmp_path, "nope", "S7_RELEASE")
        assert r.returncode == 3


# M78: run from the release by its PATH name, the script used the system python3,
# which lacks the `hapax` package that coord_projection imports. The ledger was written,
# the coord event was lost, and the loss was only a WARNING (dev7, dev12 2026-09-24).

SYSTEM_PYTHON = "/usr/bin/python3"


def _run_with(
    home: Path, interpreter: str, script: Path, *args: str
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "HAPAX_AGENT_ROLE": "alpha",
            "HAPAX_COORD_DIR": str(home / ".cache" / "hapax" / "coord"),
        }
    )
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    return subprocess.run(
        [interpreter, str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _repo_layout(tmp_path: Path, *, with_venv: bool) -> Path:
    """A release-shaped tree: scripts/cc-stage-advance plus shared/, and optionally the
    pinned .venv/bin/python (a wrapper that records it ran, then runs the real venv python)."""
    repo = tmp_path / "release"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "cc-stage-advance").write_bytes(SCRIPT.read_bytes())
    (repo / "shared").symlink_to(SCRIPT.parent.parent / "shared", target_is_directory=True)
    if with_venv:
        venv_bin = repo / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        wrapper = venv_bin / "python"
        wrapper.write_text(
            f'#!/usr/bin/env bash\ntouch "{tmp_path}/venv-python-ran"\nexec {sys.executable} "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
    return repo


def test_lost_coord_event_is_an_error_not_a_warning(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _make_task(home, "t1")
    repo = _repo_layout(tmp_path, with_venv=False)

    r = _run_with(home, SYSTEM_PYTHON, repo / "scripts" / "cc-stage-advance", "t1", "S7_RELEASE")

    assert r.returncode == 5, r.stderr
    assert "stage: S7_RELEASE" in _note(home, "t1").read_text()
    assert "ERROR" in r.stderr and "coord event NOT emitted" in r.stderr
    assert "next action" in r.stderr
    assert "WARNING" not in r.stderr


def test_runs_under_the_pinned_project_interpreter_and_emits(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _make_task(home, "t1")
    repo = _repo_layout(tmp_path, with_venv=True)

    r = _run_with(home, SYSTEM_PYTHON, repo / "scripts" / "cc-stage-advance", "t1", "S7_RELEASE")

    assert r.returncode == 0, r.stderr
    assert (tmp_path / "venv-python-ran").exists()
    assert "coord event" not in r.stderr
    assert "stage: S7_RELEASE" in _note(home, "t1").read_text()
