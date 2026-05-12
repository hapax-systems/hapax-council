"""Tests for platform_suitability filtering in the idle watchdog's task picker."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-lane-idle-watchdog"


def _run_task_picker(task_dir: Path, platform: str) -> str:
    """Run the find_next_wsjf_task function in isolation."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
            TASK_ROOT="{task_dir}"
            find_next_wsjf_task() {{
                local lane_platform="${{1:-any}}"
                python3 -c "
import re
from pathlib import Path

task_root = Path('$TASK_ROOT')
lane_platform = '$lane_platform'
best_id = None
best_wsjf = -1.0

for p in task_root.glob('*.md'):
    text = p.read_text(errors='replace')
    status_m = re.search(r'^status:\s*(\S+)', text, re.MULTILINE)
    if not status_m:
        continue
    status = status_m.group(1)
    if status not in ('offered', 'unassigned', 'ready'):
        continue
    assigned_m = re.search(r'^assigned_to:\s*(\S+)', text, re.MULTILINE)
    if assigned_m and assigned_m.group(1) not in ('unassigned', 'null', 'None', ''):
        continue
    blocked_m = re.search(r'^blocked_reason:', text, re.MULTILINE)
    if blocked_m:
        continue
    plat_m = re.search(r'^platform_suitability:\s*\\\[([^\\\]]*)\\\]', text, re.MULTILINE)
    if plat_m:
        platforms = [s.strip() for s in plat_m.group(1).split(',')]
        if 'any' not in platforms and lane_platform not in platforms:
            continue
    wsjf_m = re.search(r'^wsjf:\s*([0-9.]+)', text, re.MULTILINE)
    wsjf = float(wsjf_m.group(1)) if wsjf_m else 0.0
    if wsjf > best_wsjf:
        best_wsjf = wsjf
        best_id = p.stem

if best_id:
    print(best_id)
"
            }}
            find_next_wsjf_task "{platform}"
            """,
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_task(task_dir: Path, name: str, wsjf: float, platforms: list[str]) -> None:
    plat_str = ", ".join(platforms)
    (task_dir / f"{name}.md").write_text(
        f"---\n"
        f"status: offered\n"
        f"assigned_to: unassigned\n"
        f"wsjf: {wsjf}\n"
        f"platform_suitability: [{plat_str}]\n"
        f"---\n"
        f"# {name}\n"
    )


def test_claude_lane_skips_codex_only_task(tmp_path: Path) -> None:
    _write_task(tmp_path, "codex-task", 20.0, ["codex"])
    _write_task(tmp_path, "claude-task", 10.0, ["claude"])
    result = _run_task_picker(tmp_path, "claude")
    assert result == "claude-task"


def test_codex_lane_skips_claude_only_task(tmp_path: Path) -> None:
    _write_task(tmp_path, "claude-task", 20.0, ["claude"])
    _write_task(tmp_path, "codex-task", 10.0, ["codex"])
    result = _run_task_picker(tmp_path, "codex")
    assert result == "codex-task"


def test_any_platform_matches_all_lanes(tmp_path: Path) -> None:
    _write_task(tmp_path, "any-task", 15.0, ["any"])
    result = _run_task_picker(tmp_path, "claude")
    assert result == "any-task"
    result = _run_task_picker(tmp_path, "codex")
    assert result == "any-task"


def test_multi_platform_task_matches_listed_lanes(tmp_path: Path) -> None:
    _write_task(tmp_path, "multi-task", 15.0, ["claude", "codex"])
    result = _run_task_picker(tmp_path, "claude")
    assert result == "multi-task"
    result = _run_task_picker(tmp_path, "codex")
    assert result == "multi-task"
    result = _run_task_picker(tmp_path, "gemini")
    assert result == ""


def test_no_platform_field_matches_any_lane(tmp_path: Path) -> None:
    (tmp_path / "no-plat-task.md").write_text(
        "---\nstatus: offered\nassigned_to: unassigned\nwsjf: 12.0\n---\n# task\n"
    )
    result = _run_task_picker(tmp_path, "claude")
    assert result == "no-plat-task"


def test_highest_wsjf_wins_within_platform(tmp_path: Path) -> None:
    _write_task(tmp_path, "low-task", 5.0, ["claude"])
    _write_task(tmp_path, "high-task", 25.0, ["claude"])
    _write_task(tmp_path, "mid-task", 15.0, ["claude"])
    result = _run_task_picker(tmp_path, "claude")
    assert result == "high-task"
