# Health History File Descriptor Crash — Root Cause Investigation

**Date:** 2026-05-21
**Author:** epsilon
**Task:** 202605181934-disconfirm-health-phase0-investigate-fd-crash
**Parent request:** REQ-202605181934-disconfirm-health-telemetry-file-descriptor-fix
**Source:** CCTV Disconfirmation mode adversarial analysis (2026-05-18)
**Severity:** Critical (P0)

## Verdict: DISCONFIRMED (partially false, with minor defensive coding gaps)

The claim that "/data/cache/hapax/rebuild/worktree path missing" causes a "file descriptor crash" that "totally compromises observability" is **incorrect on all three counts**:

1. The rebuild worktree path is irrelevant to the health history subsystem
2. No file descriptor crash occurs or has evidence of ever having occurred
3. Observability is working — 484 history entries exist, 15-min timer is active

## Investigation Findings

### The `/data/cache/hapax/rebuild/worktree` path is unrelated

Zero references to `/data/cache/hapax/rebuild/worktree`, `rebuild`, or `/data/cache` exist in any health monitor code:

- `agents/health_monitor/` — 0 matches across 30+ Python files
- `agents/_health_history.py` — 0 matches
- `shared/health_history.py` — 0 matches
- `systemd/watchdogs/health-watchdog` — 0 matches

The rebuild worktree is a git worktree used by `scripts/hapax-source-activate` for deployment builds. It has no relationship to health telemetry.

### No file descriptor crash exists

The health history write path has three components:

**1. Watchdog bash script** (`systemd/watchdogs/health-watchdog:106-127`)

Hardcoded path to main worktree profiles. Cannot crash — errors are caught. The `2>/dev/null` suppresses errors silently (minor concern, see below).

**2. Python rotation** (`agents/health_monitor/output.py:191-209`)

- Line 193 guard (`if not HISTORY_FILE.is_file(): return`) prevents execution when no history file exists
- `tempfile.mkstemp()` at line 200 could theoretically leak FD if parent dir missing, but:
  - `profiles/` directory exists and is tracked in git
  - The caller in `__main__.py:114-117` wraps in try/except with warning log

**3. Rollup function** (`agents/_health_history.py:167-243`)

- `rotate_with_rollup()` calls `write_text()` at lines 233-237 without ensuring parent dirs exist
- However, this function has **zero callers from the health watchdog pipeline**
- Only imported by `agents/briefing.py:781` for `get_recurring_issues` and `get_uptime_trend`

### Observability is working

The health monitor runs on a 15-minute timer, most recent run was minutes ago. The history file has 484 entries. All health checks execute and log normally.

### No crash evidence in logs

Searching `journalctl --user -u health-monitor` for "descriptor", "crash", "history", "rotate" returned zero matches.

## Minor Defensive Coding Gaps (real but non-critical)

While the finding is false, the investigation identified three minor concerns:

### Gap 1: Silent write suppression in watchdog script

`systemd/watchdogs/health-watchdog:126`: The `2>/dev/null` redirect hides the specific error (ENOENT, EACCES, etc.) before the fallback warning fires. The warning message is generic. This is defense-in-depth (not a crash) but degrades debuggability.

### Gap 2: No mkdir_p in rotate_with_rollup

`agents/_health_history.py:233-237`: Three `Path.write_text()` calls assume parent directories exist. If called with a non-existent path (e.g., from tests or a future caller), this would raise `FileNotFoundError`. Currently safe because all paths default to `PROFILES_DIR` which is a git-tracked directory.

### Gap 3: FD leak window in rotate_history

`agents/health_monitor/output.py:200-202`: Between `tempfile.mkstemp()` returning the fd and `os.fdopen(fd, "w")` consuming it, a crash would leak one file descriptor. The except block at line 206-209 cleans up the temp file but not the fd. This is a theoretical edge case — the guard at line 193 and the try/except in `__main__.py:114-117` make this practically unreachable.

## Root Cause of False Finding

The disconfirmation probe likely conflated two separate facts:
1. `/data/cache/hapax/rebuild/worktree` is a git worktree that occasionally shows in health-adjacent contexts (e.g., worktree listings, git status)
2. The health history subsystem writes files to `profiles/`

The probe concluded that a missing rebuild worktree would crash health history, but these are independent systems with no shared code paths.

## Downstream Impact

The phase 1 task (`202605181934-disconfirm-health-phase1-fix-path-creation`) should be re-scoped. There is no path creation fix needed for the rebuild worktree. The three minor gaps above could be addressed but are non-critical.

## File Reference

| File | Lines | Role |
|------|-------|------|
| `systemd/watchdogs/health-watchdog` | 106-127 | Bash history append (runs from main worktree) |
| `agents/health_monitor/output.py` | 182-209 | Python rotation with mkstemp |
| `agents/health_monitor/__main__.py` | 113-117 | Rotation caller with try/except |
| `agents/_health_history.py` | 167-243 | Rollup function (no callers from watchdog) |
| `agents/_config.py` | 48 | PROFILES_DIR definition |
| `shared/config.py` | 47 | PROFILES_DIR definition |
