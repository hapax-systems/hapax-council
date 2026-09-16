"""Claimed-task resolution in the idle watchdog.

The watchdog once decided "no active claimed task" from the FIRST row that
``grep -rl "^assigned_to: <lane>$" | head -1`` returned and never read a claim
sidecar (measured 2026-09-16: dev kicked on a live claimed row, epsilon on a
pr_open PR). These tests run the REAL script through its
``--resolve-active-task`` inspection mode (no tmux scan, no kick) against a
fixture vault and a fixture claim directory — not a copy of the function.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(
    os.environ.get(
        "HAPAX_IDLE_WATCHDOG_SCRIPT",
        Path(__file__).resolve().parents[2] / "scripts" / "hapax-lane-idle-watchdog",
    )
)
LANE = "epsilon"


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    task_dir = tmp_path / "active"
    claim_dir = tmp_path / "claims"
    task_dir.mkdir()
    claim_dir.mkdir()
    return task_dir, claim_dir


def _write_row(task_dir: Path, name: str, status: str, assigned_to: str = LANE) -> None:
    (task_dir / f"{name}.md").write_text(
        f"---\ntask_id: {name}\nstatus: {status}\nassigned_to: {assigned_to}\n---\n\n"
        f"# {name}\n\nstatus: claimed  <- a body line that must never be read as frontmatter\n",
        encoding="utf-8",
    )


def _write_sidecar(claim_dir: Path, task_id: str, sid: str | None = None, age_s: int = 0) -> Path:
    path = claim_dir / (f"cc-active-task-{LANE}" + (f"-{sid}" if sid else ""))
    path.write_text(f"{task_id}\n", encoding="utf-8")
    if age_s:
        then = time.time() - age_s
        os.utime(path, (then, then))
    return path


def _resolve(tmp_path: Path) -> tuple[str, str, str, str, int, int]:
    env = {
        **os.environ,
        "HAPAX_IDLE_TASK_ROOT": str(tmp_path / "active"),
        "HAPAX_CLAIM_DIR": str(tmp_path / "claims"),
        "HAPAX_IDLE_STATE_DIR": str(tmp_path / "state"),
        "HAPAX_IDLE_THRESHOLD_S": "600",
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), "--resolve-active-task", LANE],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    fields = result.stdout.rstrip("\n").split("\t")
    assert len(fields) == 6, result.stdout
    kind, task, status, source, rows, sidecars = fields
    return kind, task, status, source, int(rows), int(sidecars)


def test_a_claimed_row_wins_over_a_blocked_row_that_sorts_first(tmp_path: Path) -> None:
    """(a) Directory order must not decide. The pre-fix lookup judged the lane by
    its first grep hit — here the blocked row — and reported no claim."""
    task_dir, _ = _dirs(tmp_path)
    _write_row(task_dir, "aaa-blocked-row", "blocked")
    _write_row(task_dir, "zzz-claimed-row", "claimed")
    kind, task, status, source, rows, sidecars = _resolve(tmp_path)
    assert (kind, task, status, source) == ("active", "zzz-claimed-row", "claimed", "rows")
    assert (rows, sidecars) == (2, 0)


def test_b_pr_open_only_is_a_typed_hold_not_a_kick(tmp_path: Path) -> None:
    """(b) A lane waiting on the plane is held, never kicked as idle-without-task."""
    task_dir, _ = _dirs(tmp_path)
    _write_row(task_dir, "reins-pr-row", "pr_open")
    kind, task, status, source, rows, _ = _resolve(tmp_path)
    assert (kind, task, status, source) == ("hold", "reins-pr-row", "pr_open", "rows")
    assert rows == 1


def test_c_live_sidecar_beats_a_stale_claimed_row(tmp_path: Path) -> None:
    """(c) Claim plane first: two claimed rows; the newest sidecar names the one
    that sorts second, and that one wins."""
    task_dir, claim_dir = _dirs(tmp_path)
    _write_row(task_dir, "aaa-stale-claimed", "claimed")
    _write_row(task_dir, "bbb-live-claimed", "claimed")
    _write_sidecar(claim_dir, "aaa-stale-claimed", age_s=7200)  # older role pointer
    _write_sidecar(claim_dir, "bbb-live-claimed", sid="c9cd87ba-live")  # newest lease
    kind, task, status, source, _, sidecars = _resolve(tmp_path)
    assert (kind, task, status) == ("active", "bbb-live-claimed", "claimed")
    assert source == "sidecar:cc-active-task-epsilon-c9cd87ba-live"
    assert sidecars == 2


def test_d_no_row_no_sidecar_reports_the_scan_it_did(tmp_path: Path) -> None:
    """(d) 'No active row' is said only after the full scan, and names its size."""
    task_dir, _ = _dirs(tmp_path)
    for i in range(3):
        _write_row(task_dir, f"gamma-row-{i}", "claimed", assigned_to="gamma")
    _write_row(task_dir, "epsilon-offered", "offered")
    kind, task, status, source, rows, sidecars = _resolve(tmp_path)
    assert (kind, task, status, source) == ("none", "-", "-", "-")
    assert (rows, sidecars) == (4, 0)


def test_e_sidecar_naming_another_lanes_row_is_ignored(tmp_path: Path) -> None:
    """(e) A sidecar counts only when the row it names is this lane's; otherwise
    the rows decide."""
    task_dir, claim_dir = _dirs(tmp_path)
    _write_row(task_dir, "foreign-claimed", "claimed", assigned_to="gamma")
    _write_row(task_dir, "mine-in-progress", "in_progress")
    _write_sidecar(claim_dir, "foreign-claimed")
    kind, task, status, source, _, sidecars = _resolve(tmp_path)
    assert (kind, task, status, source) == ("active", "mine-in-progress", "in_progress", "rows")
    assert sidecars == 1
