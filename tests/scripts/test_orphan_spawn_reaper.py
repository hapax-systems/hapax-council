"""Tests for hapax-orphan-spawn-reaper's pure classifier.

The reaper closes the 2026-06-27 worktree-pileup class: lanes that die
ungracefully leave spawn-shell + MCP trees parked in their worktrees, which the
GC live-PID guard then refuses to remove forever. These tests pin the safety
model — live tmux panes protect their whole tree; production paths are never
reaped; only orphaned spawn-trees and deleted-cwd council processes are.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "hapax-orphan-spawn-reaper.py"

_spec = importlib.util.spec_from_file_location("orphan_spawn_reaper", MODULE_PATH)
reaper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reaper)

WT = "/home/hapax/projects/hapax-council--{}"
SPAWN = "fish -c /home/hapax/.cache/hapax/{}-spawns/run-20260623T010101Z-{}.sh"
OLD = 100_000  # well past the default 3600s min-age
YOUNG = 120


def _p(pid, ppid, cwd, *, cmd="python3 x", deleted=False, age=OLD):
    return {"pid": pid, "ppid": ppid, "cwd": cwd, "deleted": deleted, "cmdline": cmd, "age_s": age}


def test_orphaned_spawn_tree_is_reaped_whole():
    procs = [
        _p(100, 1, WT.format("delta"), cmd=SPAWN.format("claude", "delta")),
        _p(101, 100, WT.format("delta"), cmd="claude --effort max"),
        _p(102, 101, WT.format("delta"), cmd="node playwright-mcp"),
        _p(103, 101, WT.format("delta"), cmd="chrome-devtools-mcp"),
    ]
    kill = reaper.classify_orphans(procs, live_pids=set(), now=0)
    assert kill == {100, 101, 102, 103}


def test_live_tmux_pane_protects_its_whole_tree():
    # cx-p0 spawn shell + child are reachable from a live pane (pid 999) → protected,
    # even though the spawn shell is old (the respawn-under-live-pane case).
    procs = [
        _p(200, 999, WT.format("cx-p0"), cmd=SPAWN.format("codex", "cx-p0")),
        _p(201, 200, WT.format("cx-p0"), cmd="codex"),
    ]
    kill = reaper.classify_orphans(procs, live_pids={999, 200, 201}, now=0)
    assert kill == set()


def test_young_spawn_tree_is_not_reaped():
    procs = [_p(300, 1, WT.format("zeta"), cmd=SPAWN.format("claude", "zeta"), age=YOUNG)]
    kill = reaper.classify_orphans(procs, live_pids=set(), now=0)
    assert kill == set()


def test_deleted_cwd_council_orphan_is_reaped():
    procs = [_p(400, 1, WT.format("theta"), cmd="chrome-devtools-mcp", deleted=True)]
    kill = reaper.classify_orphans(procs, live_pids=set(), now=0)
    assert kill == {400}


def test_production_paths_are_never_reaped():
    rel = "/data2/data/cache/hapax/source-activation/releases/deadbeef"
    rebuild = "/data2/data/cache/hapax/rebuild/worktree"
    runtime = "/store/llm-data/runtime/health-monitor-source"
    procs = [
        # deleted + old + would otherwise match rule 2, but production-pinned:
        _p(500, 1, rel, cmd="uv run python -m agents.triage_officer", deleted=True),
        _p(501, 1, rebuild, cmd="python3 hook", deleted=True),
        _p(502, 1, runtime, cmd="python3 health", deleted=True),
        # a spawn shell whose tree dives into a release must not drag production down
        _p(510, 1, rel, cmd=SPAWN.format("claude", "ghost")),
    ]
    kill = reaper.classify_orphans(procs, live_pids=set(), now=0)
    assert kill == set()


def test_arbitrary_non_spawn_process_in_worktree_is_left_alone():
    # Not a spawn-shell tree, cwd exists (not deleted) → no rule matches.
    procs = [_p(600, 1, WT.format("crit"), cmd="python3 -m agents.something")]
    kill = reaper.classify_orphans(procs, live_pids=set(), now=0)
    assert kill == set()
