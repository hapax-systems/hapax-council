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
                "start_ticks": starttime,
            }
        )
    return out


def current_start_ticks(pid, proc_root="/proc"):
    """The process's start-time in clock ticks, or None if it's gone/unreadable.

    Used as a PID-reuse guard: before SIGKILLing a straggler we re-confirm the
    pid still names the SAME process we SIGTERM'd (same start time), so a pid
    recycled during the grace window is never killed.
    """
    stat = _read(os.path.join(proc_root, str(pid), "stat"))
    if stat is None:
        return None
    try:
        return int(stat.rsplit(")", 1)[1].split()[19])
    except (IndexError, ValueError):
        return None


def signal_if_same(pid, expected_start_ticks, sig, *, start_ticks_fn=None, kill_fn=os.kill):
    """Send ``sig`` to ``pid`` ONLY if it still names the same process.

    The PID-reuse guard applies to BOTH phases (SIGTERM and SIGKILL), not just
    the SIGKILL escalation: a pid recycled between the /proc snapshot and the
    signal must never receive EITHER signal (review-team finding 2026-06-27).
    Re-reads the live start-time and compares it to the snapshot's; a mismatch
    (process exited, or pid reused) means skip. Returns True iff the signal was
    actually sent. (The residual stat-read→kill window is microseconds — the
    finding was the unguarded snapshot→SIGTERM window, which this closes.)
    """
    fn = start_ticks_fn or current_start_ticks
    if fn(pid) != expected_start_ticks:
        return False
    try:
        kill_fn(pid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def pane_roots_from_tmux(run=None):
    """Pane pids of all live tmux sessions, or None if tmux cannot be queried.

    Returns None — meaning "unknown, fail CLOSED" — when tmux is absent, errors,
    or exits nonzero. A nonzero exit (server/socket error) does NOT raise from
    subprocess.run, so it must be checked explicitly: treating an erroring tmux
    as "no live panes" would clear the protection set and let the reaper kill
    live trees (the review-team critical, 2026-06-27). An empty list (returncode
    0, genuinely no sessions) is a real, trusted answer and is NOT None.
    """
    import subprocess

    if run is None:
        run = subprocess.run
    try:
        res = run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_pid}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if getattr(res, "returncode", 1) != 0:
        return None
    return [int(x) for x in res.stdout.split() if x.isdigit()]


def live_pane_closure(procs, roots):
    """Pids reachable (as descendants) from any live tmux pane. Never reaped.

    roots is the output of pane_roots_from_tmux: a list of pane pids, or None.
    None ⇒ tmux unqueryable ⇒ FAIL CLOSED: protect EVERY pid (reap nothing via
    rule 1). This is the single most safety-critical branch in the tool.
    """
    if roots is None:
        return {p["pid"] for p in procs}
    children = defaultdict(list)
    for p in procs:
        children[p["ppid"]].append(p["pid"])
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
    roots = pane_roots_from_tmux()
    live = live_pane_closure(procs, roots)
    if roots is None and not args.json:
        print(
            "orphan-reaper: tmux unqueryable — failing CLOSED (protecting all spawn-trees)",
            file=sys.stderr,
        )
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
        # Snapshot each target's start-time; BOTH the SIGTERM and the SIGKILL
        # pass confirm the pid still names the SAME process before signalling,
        # so a pid recycled after the /proc snapshot never receives either signal.
        expected_start = {p["pid"]: p.get("start_ticks") for p in procs if p["pid"] in kill}
        for pid in sorted(kill):
            if signal_if_same(pid, expected_start.get(pid), signal.SIGTERM):
                reaped += 1
        # Give trees a moment to exit on SIGTERM, then SIGKILL the stragglers
        # (same PID-reuse guard).
        if kill:
            time.sleep(3)
            for pid in sorted(kill):
                signal_if_same(pid, expected_start.get(pid), signal.SIGKILL)

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
        print(
            f"orphan-reaper: non-fatal error: {exc}\n"
            "  next: re-run `scripts/hapax-orphan-spawn-reaper.py --dry-run` on the live host "
            "(needs /proc + tmux); if it persists, file it — the GC pre-pass continues regardless.",
            file=sys.stderr,
        )
        sys.exit(0)
