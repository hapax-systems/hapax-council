# Worktree and Concurrent-Session Awareness for session-context.sh

**Date:** 2026-03-13
**Status:** Draft
**Hook:** `/home/operator/projects/hapax-council/hooks/scripts/session-context.sh`

## 1. Current State

The SessionStart hook injects a `## System Context` block covering: axioms, git branch/commit, health, drift, Docker, GPU, operator profile, cycle mode, governance nudge, and scout recommendations.

**What's missing:**

- No distinction between primary worktree (`~/projects/hapax-council` on `main`) and linked worktrees (`~/projects/hapax-council--fix-foo` on `fix/foo`).
- No awareness of other Claude Code sessions running against the same repo.
- The git context line shows branch and last commit but doesn't indicate *which copy* of the repo the session is in.
- The axiom/health/drift/profile reads are hardcoded to `$HOME/projects/hapax-council`, so worktree sessions read the primary's data regardless of their own branch state.

## 2. Worktree Detection

### Mechanism

`git rev-parse` provides two values that differ only in worktrees:

| Command | Primary | Worktree |
|---|---|---|
| `git rev-parse --git-dir` | `.git` | `/path/to/primary/.git/worktrees/<name>` |
| `git rev-parse --git-common-dir` | `.git` | `/path/to/primary/.git` |

**Detection rule:** If `--git-dir` and `--git-common-dir` resolve to different absolute paths, CWD is a linked worktree. The primary worktree's root can be derived from `--git-common-dir` by stripping the trailing `/.git`.

### Branch and primary linkage

```bash
GIT_DIR="$(git rev-parse --git-dir 2>/dev/null)"
GIT_COMMON="$(git rev-parse --git-common-dir 2>/dev/null)"
BRANCH="$(git branch --show-current 2>/dev/null || echo 'detached')"

if [ "$GIT_DIR" != "$GIT_COMMON" ]; then
  # Linked worktree
  PRIMARY_ROOT="$(cd "$GIT_COMMON" && git rev-parse --show-toplevel 2>/dev/null)"
  echo "Worktree: $BRANCH (linked to $PRIMARY_ROOT)"
else
  echo "Primary worktree ($BRANCH)"
fi
```

### Active worktrees listing

```bash
echo "Worktrees:"
git worktree list --porcelain 2>/dev/null | awk '
  /^worktree / { wt=$2 }
  /^branch /   { sub(/^refs\/heads\//, "", $2); printf "  %s [%s]\n", wt, $2 }
'
```

This outputs something like:

```
Worktrees:
  /home/operator/projects/hapax-council [main]
  /home/operator/projects/hapax-council--fix-foo [fix/foo]
```

## 3. Concurrent Session Detection

### How Claude Code processes appear

Running Claude Code sessions are visible as `/opt/claude-code/bin/claude` processes. Their working directory is readable via `/proc/<pid>/cwd`:

```
$ pgrep -a claude
77766 /opt/claude-code/bin/claude --dangerously-skip-permissions --resume
579228 /opt/claude-code/bin/claude --dangerously-skip-permissions
```

```
$ readlink /proc/77766/cwd
/home/operator/projects/hapax-council
```

### Detection script

Find all Claude Code sessions, resolve their CWD, and determine which share the same `--git-common-dir` (same repo, possibly different worktrees):

```bash
detect_concurrent_sessions() {
  local my_pid=$$
  local my_common
  my_common="$(git rev-parse --git-common-dir 2>/dev/null)" || return
  my_common="$(realpath "$my_common" 2>/dev/null)"

  local concurrent=()
  while IFS= read -r pid; do
    # Skip our own process tree
    [ "$pid" = "$my_pid" ] && continue

    local cwd
    cwd="$(readlink /proc/"$pid"/cwd 2>/dev/null)" || continue

    local their_common
    their_common="$(cd "$cwd" && git rev-parse --git-common-dir 2>/dev/null)" || continue
    their_common="$(realpath "$their_common" 2>/dev/null)"

    if [ "$their_common" = "$my_common" ]; then
      local their_branch
      their_branch="$(cd "$cwd" && git branch --show-current 2>/dev/null || echo 'detached')"
      concurrent+=("PID $pid in $cwd [$their_branch]")
    fi
  done < <(pgrep -x claude 2>/dev/null)

  if [ ${#concurrent[@]} -gt 0 ]; then
    echo "WARNING: ${#concurrent[@]} other Claude session(s) in this repo:"
    printf "  %s\n" "${concurrent[@]}"
  fi
}
```

**Note on `pgrep -x claude`:** This matches processes named exactly "claude". The actual binary is `/opt/claude-code/bin/claude`, so the process name is `claude`. If the binary name changes, use `pgrep -f '/opt/claude-code/bin/claude'` instead.

**Note on `$$`:** Inside a SessionStart hook, `$$` is the hook's shell PID, not the Claude process PID. The hook is a child of the Claude process, so we should also skip our parent. Use `$PPID` or filter by checking if a PID is an ancestor of the current process.

## 4. Proposed Changes to session-context.sh

Replace the existing git context block (lines 25-28) with an expanded section. Add the concurrent session check after the git block.

### 4a. Worktree-aware git context (replaces lines 25-28)

```bash
# Git context (worktree-aware)
GIT_DIR="$(git rev-parse --git-dir 2>/dev/null || true)"
GIT_COMMON="$(git rev-parse --git-common-dir 2>/dev/null || true)"
BRANCH="$(git branch --show-current 2>/dev/null || echo 'detached')"
LAST_COMMIT="$(git log --oneline -1 2>/dev/null || echo 'N/A')"

if [ -n "$GIT_DIR" ] && [ -n "$GIT_COMMON" ]; then
  GIT_DIR_ABS="$(cd "$(dirname "$GIT_DIR")" && realpath "$(basename "$GIT_DIR")" 2>/dev/null || echo "$GIT_DIR")"
  GIT_COMMON_ABS="$(cd "$(dirname "$GIT_COMMON")" && realpath "$(basename "$GIT_COMMON")" 2>/dev/null || echo "$GIT_COMMON")"

  if [ "$GIT_DIR_ABS" != "$GIT_COMMON_ABS" ]; then
    PRIMARY_ROOT="$(dirname "$GIT_COMMON_ABS")"
    echo "Worktree: $BRANCH (linked to $PRIMARY_ROOT) | $LAST_COMMIT"
  else
    echo "Primary worktree ($BRANCH) | $LAST_COMMIT"
  fi
else
  echo "Branch: $BRANCH | Last commit: $LAST_COMMIT"
fi
```

### 4b. Active worktrees (new, after git context)

```bash
# Active worktrees (only if more than one exists)
WT_COUNT="$(git worktree list 2>/dev/null | wc -l)"
if [ "$WT_COUNT" -gt 1 ]; then
  echo "Worktrees ($WT_COUNT):"
  git worktree list 2>/dev/null | while read -r path commit branch; do
    # branch comes as [branchname] — strip brackets
    branch="${branch#[}"
    branch="${branch%]}"
    echo "  $path [$branch]"
  done
fi
```

### 4c. Concurrent session detection (new section)

```bash
# Concurrent Claude sessions in same repo
if [ -n "$GIT_COMMON_ABS" ]; then
  CONCURRENT=""
  CONCURRENT_COUNT=0
  MY_CLAUDE_PID="$PPID"  # hook is child of claude process

  while IFS= read -r pid; do
    [ "$pid" = "$MY_CLAUDE_PID" ] && continue
    cwd="$(readlink /proc/"$pid"/cwd 2>/dev/null)" || continue
    their_common="$(cd "$cwd" && git rev-parse --git-common-dir 2>/dev/null)" || continue
    their_common="$(realpath "$their_common" 2>/dev/null)"
    if [ "$their_common" = "$GIT_COMMON_ABS" ]; then
      their_branch="$(cd "$cwd" && git branch --show-current 2>/dev/null || echo 'detached')"
      CONCURRENT="${CONCURRENT}  PID $pid: $cwd [$their_branch]\n"
      CONCURRENT_COUNT=$((CONCURRENT_COUNT + 1))
    fi
  done < <(pgrep -f '/opt/claude-code/bin/claude' 2>/dev/null)

  if [ "$CONCURRENT_COUNT" -gt 0 ]; then
    echo "CONCURRENT SESSIONS ($CONCURRENT_COUNT other):"
    printf "$CONCURRENT"
  fi
fi
```

## 5. Conflict Detection

### Same-branch warning

The highest-risk scenario: two Claude sessions on the same branch (especially `main` in the primary worktree). The concurrent detection in 4c already surfaces this — if two entries show the same branch, that's the signal.

Add after the concurrent loop:

```bash
  # Explicit same-branch conflict warning
  if [ "$CONCURRENT_COUNT" -gt 0 ]; then
    SAME_BRANCH=0
    while IFS= read -r pid; do
      [ "$pid" = "$MY_CLAUDE_PID" ] && continue
      cwd="$(readlink /proc/"$pid"/cwd 2>/dev/null)" || continue
      their_branch="$(cd "$cwd" && git branch --show-current 2>/dev/null)"
      [ "$their_branch" = "$BRANCH" ] && SAME_BRANCH=$((SAME_BRANCH + 1))
    done < <(pgrep -f '/opt/claude-code/bin/claude' 2>/dev/null)
    if [ "$SAME_BRANCH" -gt 0 ]; then
      echo "WARNING: $SAME_BRANCH other session(s) on branch '$BRANCH' — high conflict risk"
    fi
  fi
```

### Shared-file detection (future consideration)

Detecting actual file-level overlap would require tracking which files each session has modified. Options:

- **Git-based:** Compare `git diff --name-only` across worktrees. Lightweight but only catches committed/staged changes.
- **Lock files:** Each Claude session could write a lock file listing touched files. Requires hook cooperation on both session start and end.
- **inotify:** A daemon watching the repo for writes. Heavyweight, not worth it for the hook.

**Recommendation:** Start with branch-level conflict detection (above). File-level tracking can be added later if branch-level proves insufficient.

## 6. Implementation Plan

### Phase 1: Worktree awareness (low risk, immediate value)

1. Replace lines 25-28 of `session-context.sh` with the worktree-aware git context (section 4a).
2. Add the active worktrees listing (section 4b) immediately after.
3. Test in both primary and a worktree directory.

### Phase 2: Concurrent session detection

1. Add the concurrent session block (section 4c) after the worktree listing.
2. Add the same-branch warning (section 5).
3. Test with two Claude sessions open against the same repo.

### Phase 3: Hardcoded path fix (separate PR)

The hook hardcodes `$HOME/projects/hapax-council` for axiom loading, health, drift, profile, and scout reads. In a worktree, the CWD is different but the data files live in the primary. This currently works by accident (the paths are absolute to primary). Document this explicitly with a comment, or derive the path from `GIT_COMMON_ABS`:

```bash
# Resolve to primary worktree for shared data files
if [ -n "$GIT_COMMON_ABS" ]; then
  REPO_PRIMARY="$(dirname "$GIT_COMMON_ABS")"
else
  REPO_PRIMARY="$(pwd)"
fi
```

### Performance budget

The hook runs at every session start. Current runtime is dominated by `docker ps`, `nvidia-smi`, and the Python axiom loader. The additions:

- `git rev-parse` (x2): ~5ms
- `git worktree list`: ~5ms
- `pgrep` + `/proc` reads: ~10ms per Claude process (typically 1-3)

Total added: ~25ms. Negligible.

### Example output

Primary worktree, no conflicts:

```
Primary worktree (main) | a1b2c3d feat: add voice daemon
Worktrees (2):
  /home/operator/projects/hapax-council [main]
  /home/operator/projects/hapax-council--fix-midi [fix/midi]
```

Linked worktree with concurrent session:

```
Worktree: fix/midi (linked to /home/operator/projects/hapax-council) | d4e5f6a fix: MIDI routing
Worktrees (2):
  /home/operator/projects/hapax-council [main]
  /home/operator/projects/hapax-council--fix-midi [fix/midi]
CONCURRENT SESSIONS (1 other):
  PID 77766: /home/operator/projects/hapax-council [main]
```

Same-branch conflict:

```
Primary worktree (main) | a1b2c3d feat: add voice daemon
CONCURRENT SESSIONS (1 other):
  PID 99999: /home/operator/projects/hapax-council--hotfix [main]
WARNING: 1 other session(s) on branch 'main' — high conflict risk
```
