#!/usr/bin/env python3
"""hapax-orphan-spawn-reaper — reap agent spawn-trees the lane-reaper cannot see.

WHY THIS EXISTS (2026-06-27 pileup root cause)
----------------------------------------------
`hapax-lane-reaper` only iterates *existing* tmux sessions
(`tmux list-sessions | grep '^hapax-(codex-cx-|claude-)'`). When a lane dies
*ungracefully* — its tmux session/pane is gone but its `fish -c .../run-*.sh`
spawn shell and the MCP servers it started (node/playwright/chrome-devtools/
context7/mcp-gemini, plus `docker run` github-mcp containers) survive — the
lane-reaper never iterates it, so those processes leak forever. Each leaked
tree keeps its `cwd` parked inside the lane's worktree, which makes
`hapax-worktree-gc`'s live-PID guard (correctly, post the F1 release-ghost
incident) REFUSE to remove the now-merged worktree. The worktrees then pile up
unbounded: on 2026-06-27 the GC reported `removable=7 removed=0 live_refused=7`
against 79 worktrees, 80 leaked processes, and 9 leaked docker containers.

This reaper closes that class. It runs as a pre-pass to the GC (see
hapax-worktree-gc.sh) so the GC's next scan finds the freed worktrees reapable.

SAFETY MODEL
------------
PRIMARY guard: any process reachable from a LIVE tmux pane is protected. We
build the descendant closure of every `tmux list-panes -a` pane pid; the
operator's attached sessions (dev/dev2/dev3) and any actively-supervised codex
lane (which the supervisor RESPAWNS under its live pane) are therefore never
touched — even immediately after a respawn.

We reap only:
  1. SPAWN-SHELL TREES — a `*-spawns/run-*.sh` shell (and its descendants)
     that is NOT under any live tmux pane and is older than --min-age. The
     spawn-shell signature scopes kills to agent lanes; nothing else matches.
  2. DELETED-CWD COUNCIL ORPHANS — any process whose cwd is a *deleted*
     directory referencing a hapax-council worktree (the worktree was already
     removed out from under it). Definitionally orphaned.

NEVER touched: production/infra paths (source-activation deploy tree + release
snapshots, rebuild/worktree, llm-data/runtime, health-monitor) and this
reaper's own process tree. Killing a process never loses committed work
(branches/PRs persist); a false positive at worst triggers a clean supervisor
respawn. Best-effort: always exits 0 so it can never block the GC.

Usage:
  hapax-orphan-spawn-reaper.py [--dry-run] [--min-age SECONDS] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from collections import defaultdict

# Spawn-shell signature: ~/.cache/hapax/<kind>-spawns/run-<ts>-<role>.sh, and the
# relocated /<mnt>/cache/hapax/ form. Matches claude/codex/vibe/antigrav/gemini.
SPAWN_RE = re.compile(r"/(?:\.)?cache/hapax/[a-z0-9]+-spawns/run-[^/\s]*\.sh")
# Marker for a worktree path (used for the deleted-cwd orphan rule).
COUNCIL_MARKER = "hapax-council"
# Production / infrastructure paths that must NEVER be reaped by this tool.
PROTECT_SUBSTRINGS = (
    "/source-activation/",  # deploy tree + pinned release snapshots
    "/rebuild/worktree",  # rebuild-scratch (deployed hooks run from here)
    "/llm-data/runtime/",  # runtime source trees (health-monitor-source, …)
    "/health-monitor",
)
DEFAULT_MIN_AGE_S = 3600  # anti-race margin; the live-pane closure is the real guard


def _is_protected(path: str, protect=PROTECT_SUBSTRINGS) -> bool:
    return any(s in path for s in protect)


def classify_orphans(
    procs,
    live_pids,
    *,
    now,
    min_age_s=DEFAULT_MIN_AGE_S,
    spawn_re=SPAWN_RE,
    council_marker=COUNCIL_MARKER,
    protect=PROTECT_SUBSTRINGS,
):
    """Pure classifier. Returns the set of pids to reap.

    procs: iterable of dicts with keys pid, ppid, cwd (deleted suffix stripped),
           deleted (bool), cmdline (str), age_s (int).
    live_pids: set of pids reachable from a live tmux pane (protected).
    """
    by_pid = {p["pid"]: p for p in procs}
    children = defaultdict(list)
    for p in procs:
        children[p["ppid"]].append(p["pid"])

    kill: set[int] = set()

    # Rule 1: orphaned spawn-shell trees (no live tmux pane ancestor).
    for p in procs:
        if p["pid"] in live_pids:
            continue
        if not spawn_re.search(p["cmdline"]):
            continue
        if p["age_s"] < min_age_s:
            continue
        # Reap the whole subtree, skipping anything live or production-pinned.
        stack = [p["pid"]]
        while stack:
            pid = stack.pop()
            pr = by_pid.get(pid)
            if pr is None or pid in live_pids or pid in kill:
                continue
            if _is_protected(pr["cwd"], protect):
                continue
            kill.add(pid)
            stack.extend(children.get(pid, ()))

    # Rule 2: processes parked in an already-deleted council worktree.
    for p in procs:
        if p["pid"] in live_pids or p["pid"] in kill:
            continue
        if not p["deleted"]:
            continue
        if council_marker not in p["cwd"] or _is_protected(p["cwd"], protect):
            continue
        if p["age_s"] < min_age_s:
            continue
        kill.add(p["pid"])

    return kill


# ─────────────────────────── real-system gathering ───────────────────────────


def _read(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None


def _boot_epoch():
    stat = _read("/proc/stat") or ""
    for line in stat.splitlines():
        if line.startswith("btime"):
            return int(line.split()[1])
    return None


def gather_procs(now, proc_root="/proc"):
    btime = _boot_epoch()
    clk = os.sysconf("SC_CLK_TCK")
    out = []
    try:
        pids = [p for p in os.listdir(proc_root) if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        base = os.path.join(proc_root, pid)
        try:
            cwd_raw = os.readlink(os.path.join(base, "cwd"))
        except OSError:
            continue
        deleted = cwd_raw.endswith(" (deleted)")
        cwd = cwd_raw.removesuffix(" (deleted)")
        stat = _read(os.path.join(base, "stat"))
        if stat is None or btime is None:
            continue
        try:
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
            starttime = int(stat.rsplit(")", 1)[1].split()[19])
        except (IndexError, ValueError):
            continue
        age_s = max(0, int(now - (btime + starttime / clk)))
        cmd = _read(os.path.join(base, "cmdline")) or ""
        cmd = cmd.replace("\0", " ").strip()
        out.append(
            {
                "pid": int(pid),
                "ppid": ppid,
                "cwd": cwd,
                "deleted": deleted,
                "cmdline": cmd,
                "age_s": age_s,
            }
        )
    return out


def live_pane_closure(procs):
    """Pids reachable (as descendants) from any live tmux pane. Never reaped."""
    import subprocess

    children = defaultdict(list)
    for p in procs:
        children[p["ppid"]].append(p["pid"])
    try:
        res = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_pid}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        roots = [int(x) for x in res.stdout.split() if x.isdigit()]
    except (OSError, subprocess.SubprocessError, ValueError):
        # tmux absent/unreadable → FAIL SAFE: protect everything, reap nothing
        # via rule 1 (return all pids as "live"). Rule 2 (deleted cwd) is still
        # safe to run, but we conservatively protect all here.
        return {p["pid"] for p in procs}
    live = set()
    stack = list(roots)
    while stack:
        pid = stack.pop()
        if pid in live:
            continue
        live.add(pid)
        stack.extend(children.get(pid, ()))
    return live


def main(argv=None):
    ap = argparse.ArgumentParser(description="Reap orphaned agent spawn-trees.")
    ap.add_argument("--dry-run", action="store_true", help="list, do not kill")
    ap.add_argument(
        "--min-age",
        type=int,
        default=DEFAULT_MIN_AGE_S,
        help=f"min process age seconds (default {DEFAULT_MIN_AGE_S})",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable summary")
    args = ap.parse_args(argv)

    now = time.time()
    procs = gather_procs(now)
    live = live_pane_closure(procs)
    # Never reap our own tree.
    me = os.getpid()
    live.add(me)
    try:
        live.add(os.getppid())
    except OSError:
        pass

    kill = classify_orphans(procs, live, now=now, min_age_s=args.min_age)
    by_pid = {p["pid"]: p for p in procs}

    actions = []
    for pid in sorted(kill):
        pr = by_pid.get(pid, {})
        actions.append(
            {
                "pid": pid,
                "cwd": pr.get("cwd", "?"),
                "cmd": pr.get("cmdline", "?")[:80],
                "age_s": pr.get("age_s"),
            }
        )

    if not args.json:
        for a in actions:
            verb = "would reap" if args.dry_run else "reaping"
            print(
                f"orphan-reaper: {verb} pid={a['pid']} age={a['age_s']}s "
                f"cwd={a['cwd']} :: {a['cmd']}"
            )

    reaped = 0
    if not args.dry_run:
        for pid in sorted(kill):
            try:
                os.kill(pid, signal.SIGTERM)
                reaped += 1
            except (ProcessLookupError, PermissionError):
                pass
        # Give trees a moment to exit on SIGTERM, then SIGKILL stragglers.
        if kill:
            time.sleep(3)
            for pid in sorted(kill):
                if os.path.isdir(f"/proc/{pid}"):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass

    summary = {"candidates": len(kill), "reaped": reaped, "dry_run": args.dry_run}
    if args.json:
        print(json.dumps(summary))
    else:
        print(
            f"orphan-reaper: candidates={summary['candidates']} "
            f"reaped={summary['reaped']} dry_run={summary['dry_run']}"
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # best-effort: never block the GC pre-pass
        print(f"orphan-reaper: non-fatal error: {exc}", file=sys.stderr)
        sys.exit(0)
