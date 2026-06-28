# Worktree Cap Policy & Cleanup Runbook

**Status:** Normative. Enforced by
`hooks/scripts/no-stale-branches.sh` (PreToolUse on Bash).
**CVS Task:** #153 (worktree cap workflow fix).
**Audit tool:** `scripts/worktree-cap-audit.sh`.
**Owner:** operator; beta + delta propose cleanup, alpha resolves.

---

## 1. Policy — the cap is twenty

The workspace runs a cap of **twenty visible session worktrees**, matching
the threshold enforced by `hooks/scripts/no-stale-branches.sh`. The floor is
~15 steady-state slots (1 primary + 4 Claude peers + 7 Codex lanes + 2 Vibe +
1 Antigrav = 15), leaving ~5 spontaneous slots. (An earlier draft of this doc
and the audit tool said "eight"; that transition target diverged from the
enforced hook and is retired — the two MUST stay in sync.)

| Interface / slot | Path convention | Permanence | Role |
|------|-----------------|------------|------|
| primary | `hapax-council/` (top-level) | permanent | integrator / primary workstation-resident session |
| Claude legacy | `hapax-council--beta/`, `--delta*`, `--epsilon*`, `--main-red` | transition-permanent | existing Claude Code lanes |
| Codex | `hapax-council--cx-<color>/` | session-owned | first-class Codex lanes |
| spontaneous | `hapax-council--<slug>/` | temporary | ONE short-lived non-session worktree for a specific task |

**Hard rules:**

- At most one spontaneous non-session worktree exists at any time.
- Codex sessions must not default into Claude legacy paths. Greek slot
  names are coordination lanes; Codex worktree names are `cx-*`.
- The spontaneous slot must be cleaned up (merged / PR'd / removed)
  before a second spontaneous worktree can be created.
- Infrastructure worktrees are NOT counted against the cap. This covers the
  legacy `~/.cache/hapax/` layout AND the relocated dev substrate on the data
  mount. The full infra set (kept in sync across the hook, the audit tool, and
  the classification tree in §3):
  - `~/.cache/` and `/<mnt>/cache/hapax/` — rebuild-scratch (e.g.
    `rebuild/worktree` managed by `scripts/rebuild-logos.sh` via `flock`) and
    agent scratch. After the dev→appendix relocation these live under
    `/data2/data/cache/hapax/`, NOT `~/.cache/`.
  - `.claude/worktrees/` and `.codex/worktrees/` — tool-owned scratch.
  - `source-activation/` — the deploy tree + pinned release snapshots
    (`source-activation/releases/<sha>`), managed by `hapax-worktree-gc.sh`'s
    release retention, not by session hygiene.
  - `/<mnt>/llm-data/runtime/` — runtime source trees (e.g.
    `health-monitor-source` on `/store`).

  Until 2026-06-27 only the dotted `~/.cache/` form matched, so the 7
  production/infra worktrees on `/data2` + `/store` counted as session
  worktrees AND were flagged "UNKNOWN — likely leak", producing a false
  over-cap (78 reported against a cap of 20).
- Gamma is a reserved session name (see `scripts/hapax-whoami-audit.sh`)
  but does not currently claim a permanent worktree slot. An epic that
  activates it must amend this table and adjust the cap.

**The cap exists because:**

- More than five concurrent worktrees produces cross-session stomp
  (one agent'''s rebase breaks another'''s dev server).
- The rebuild-logos.sh auto-detach pattern (feedback
  `feedback_rebuild_logos_worktree_detach`) requires knowing which
  worktrees are session vs infrastructure; ambiguity causes data
  loss.
- Subagent worktree-cleanup has historically lost entire
  implementation phases (feedback `feedback_worktree_persistence`).
  A small finite slot set makes it possible to audit every
  worktree before cleanup.

## 2. Enforcement path

Three surfaces enforce the cap:

1. **`scripts/worktree-cap-audit.sh`** — run on demand. Produces a
   classified inventory (primary / secondary / spontaneous / infra
   / unknown) and exits non-zero when the cap is exceeded or an
   unknown worktree is present.
2. **`hooks/scripts/no-stale-branches.sh`** — PreToolUse hook on
   Bash. Blocks `git worktree add` when the session worktree count
   is already at the cap. Uses the same infrastructure filters as
   the audit tool so the numbers match.
3. **Operator discretion** — the operator reviews
   `worktree-cap-audit.sh` output before approving a spontaneous
   worktree request.

If the cap-enforcement logic in `no-stale-branches.sh` ever drifts
from the policy table above, fix the hook (grep for the session-wt
counter and the `-ge N` threshold). The audit tool and the hook
MUST agree on the count.

## 3. Classification decision tree

Given a worktree path, classify via:

    path contains /.cache/             -> INFRASTRUCTURE (not counted)
    path contains /cache/hapax/        -> INFRASTRUCTURE (not counted)  # relocated
    path contains .claude/worktrees/   -> INFRASTRUCTURE (not counted)
    path contains .codex/worktrees/    -> INFRASTRUCTURE (not counted)
    path contains /source-activation/  -> INFRASTRUCTURE (not counted)  # deploy + releases
    path contains /llm-data/runtime/   -> INFRASTRUCTURE (not counted)  # runtime source
    path == .../hapax-council          -> PRIMARY (alpha)
    path == .../hapax-council--beta*   -> SECONDARY permanent (beta)
    path == .../hapax-council--delta*  -> SECONDARY permanent (delta)
    path == .../hapax-council--epsilon* -> SECONDARY permanent (epsilon)
    path == .../hapax-council--cx-*    -> CODEX first-class
    path matches .../hapax-council--*  -> SPONTANEOUS
    anything else                      -> UNKNOWN (likely leak; investigate)

The `hapax-council--cascade-YYYY-MM-DD/` pattern is classified as
SPONTANEOUS. When a cascade session runs as delta'''s workspace
(common pattern during task-indexed cascades), the worktree
itself is still a spontaneous slot — the session identity is
delta, but the worktree occupies the spontaneous slot. This is
by design: the spontaneous slot is allowed to be named arbitrarily
so a cascade can carry a descriptive label without the path
needing to match `--delta*`.

Note: if the same cascade runs long enough to overlap with
another spontaneous request, close the cascade worktree first
(commit + PR + worktree removal).

## 4. Cleanup procedure — safe steps

When the audit reports OVER CAP or UNKNOWN, clean up in this order:

### 4.1. Identify the target worktrees

    scripts/worktree-cap-audit.sh
    # Review the SPONTANEOUS + UNKNOWN sections.

### 4.2. Ensure work is preserved

For each target worktree, verify with standard git inspection
commands (status, log range origin/main..HEAD).

If there are untracked or uncommitted changes:

- Preferred: commit them; create a PR.
- If the changes were abandoned intentionally: the operator
  explicitly approves discarding them (this is a destructive
  action, not a default).

If there are unpushed commits on a feature branch:

- Push the branch to origin.
- Create a PR; wait for merge (do not remove the worktree before
  the PR is merged — doing so risks losing the branch ref if the
  branch isn'''t pushed).

### 4.3. Remove the worktree

From alpha (or any other preserved worktree), run the standard
`git worktree remove` targeting the leaked path. If the command
complains about uncommitted changes after step 4.2 confirmed
there were none, something has changed in the interim — re-run
step 4.2 before forcing.

`git worktree remove --force` is destructive and blocked by
`no-stale-branches.sh` when the worktree'''s branch has commits
ahead of main. Never override the hook without the operator'''s
explicit approval per invocation.

### 4.4. Verify

    scripts/worktree-cap-audit.sh
    # Expect STATUS: OK

### 4.5. Prune dangling refs

Use the standard `git worktree prune` and delete merged branches
with the regular branch-delete flag (only for MERGED branches).

## 5. Leaked worktrees — what counts, how to recover

A "leaked" worktree is any entry in the worktree list that:

- Is not one of the primary, legacy Claude, Codex `cx-*`, or current
  spontaneous slots.
- Is not under `~/.cache/`, `.claude/worktrees/`, or `.codex/worktrees/`.
- Has a path that no longer exists on disk (git'''s internal
  registry is stale).

The audit tool classifies these as UNKNOWN. Recovery procedure:

- For a stale registry entry (path deleted but git still lists it):
  run the standard worktree-prune command.
- For a ghost worktree with a feature branch: check the branch for
  unpushed commits; if unpushed, reattach the worktree to a
  recovery path, push the branch, then clean up.

Do not force-delete a worktree whose branch has unpushed commits
without first pushing the branch. The worktree removal deletes
the reflog; the commits become unreachable and are eventually
garbage-collected.

## 5a. Automated hygiene & the orphaned-spawn-tree class

Two timers keep the count bounded without manual cleanup:

- **`hapax-worktree-gc.timer`** (every 6h) → `scripts/hapax-worktree-gc.sh`. The
  cleanup is governed by EXPLICIT lifecycle STATUS, not age+merge inference (PR
  #4337). Two cooperating passes:
  - **Registry pre-pass.** `hapax-worktree-register backfill` (register every
    worktree) → capture the **protected set** → `reap --apply --min-idle-hours 48`.
    The registry (`~/.cache/hapax/worktree-registry/<slug>.json`, one record per
    worktree) gives each worktree a status — `infra`/`active`/`merging`/`abandoned`/
    `done` — derived from liveness + heartbeat + open-PR + merge, with explicit
    `set_status` pins authoritative. `reap` removes ONLY **registered**, non-live,
    clean, `done`/`abandoned` checkouts (branches always kept).
  - **Legacy merged/age sweep, now SUBORDINATE to the registry.** The same
    age+clean+merged remover still deletes stale merged worktrees + their merged
    branches, but it now **skips every registry-protected lane** (pins +
    `infra`/`active`/`merging`), so inference can never override an explicit status.
    If the registry pre-pass *fails* (Python import error / corrupt record), the
    legacy sweep **fails CLOSED** — reaps nothing by inference that cycle — and
    ntfy-alerts, rather than silently reverting to pure inference. (`done`/
    `abandoned` are intentionally NOT protected, so the sweep can still reap a merged
    checkout + delete its merged branch.) The release-snapshot cleanup
    (`source-activation/releases/<sha>`, keeping active+candidate from `current.json`)
    and the stale-*unmerged* alerts are separate and not registry-gated.
  - **Idle window.** The module default `abandoned` threshold is 12h, but the timer
    passes `--min-idle-hours 48` — so the automatic cycle reaps `abandoned` lanes
    only after ~48h idle, not 12h. The open-PR signal needs `gh`; when the timer
    runs without it the classify fails CLOSED (only `done`/merged reaped). This 48h
    lives in the SCRIPT, not the unit — verify it with
    `grep REGISTRY_IDLE_HOURS scripts/hapax-worktree-gc.sh` (the
    `HAPAX_WORKTREE_GC_REGISTRY_IDLE_HOURS:-48` default) and the schedule with
    `systemctl --user cat hapax-worktree-gc.timer`. If a future edit changes either,
    re-sync this doc.
  - **Corrupt records fail closed.** A present-but-unparseable
    `worktree-registry/<slug>.json` is treated as registered + protected (it may hold
    a pin we can't read): `backfill` leaves it untouched (never overwrites with a
    derived status), `reap` keeps it (`KEEP corrupt …`), and it is emitted by
    `protected-paths`. Repair: `rm` the named file, then `backfill`.
  - **Unregistered worktrees (until P4).** `reap` KEEPS unregistered worktrees (flags,
    never removes); `backfill` (which the timer runs first) registers every git-visible
    worktree with a derived status, so after one GC cycle every worktree has an explicit
    status. Registration *at creation time* is P4 (`hapax-worktree-create` + dispatch
    wiring); until it lands, a freshly dispatch-created lane is unregistered only until
    the next backfill.
  - **Rechecks.** `hapax-worktree-register list` (per-worktree status; shows `corrupt`),
    `hapax-worktree-register protected-paths` (what the legacy sweep will NOT touch),
    and `hapax-worktree-gc.sh --dry-run` (the actual removal decisions, including the
    registry-gate `keep … registry-protected` / `fail-closed` lines).
  - A live-PID guard refuses to remove any worktree a running process maps via
    `/proc/<pid>/cwd|exe` (the F1 release-ghost incident).
- **`hapax-lane-reaper.timer`** (every 30m) → reaps *dead lanes that still have
  a live tmux session*.

**The 2026-06-27 pileup (root cause).** The lane-reaper only iterates EXISTING
tmux sessions. When a lane dies *ungracefully* — its tmux session/pane is gone
but its `*-spawns/run-*.sh` spawn shell and the MCP servers it started
(node/playwright/chrome-devtools/context7/mcp-gemini + `docker run` github-mcp
containers) survive — nothing reaps them. Each leaked tree keeps its `cwd`
parked in the lane's (now-merged) worktree, so the GC's live-PID guard refuses
removal *forever*. The result was 79 worktrees, 80 leaked processes, 9 leaked
docker containers, and a GC reporting `removable=7 removed=0 live_refused=7`.

**The fix.** `scripts/hapax-orphan-spawn-reaper.py` runs as a GC pre-pass
(invoked from `hapax-worktree-gc.sh`; disable with
`HAPAX_WORKTREE_GC_REAP_ORPHANS=0`). It SIGTERMs (then SIGKILLs stragglers):

1. orphaned spawn-shell trees (`*-spawns/run-*.sh` + descendants) NOT reachable
   from any live `tmux list-panes -a` pane and older than `--min-age` (3600s);
2. processes whose `cwd` is an already-deleted `hapax-council` worktree.

Safety: anything reachable from a live tmux pane is protected (operator sessions
+ any actively-respawned lane), production/infra paths are never touched, and
killing a process never loses committed work — a false positive at worst
triggers a clean supervisor respawn. If tmux cannot be queried it FAILS CLOSED
(protects every spawn-tree, reaps nothing via the orphan rule).

**Recheck commands** (these are host-state-dependent — run them on the live
podium host, where `/proc` and the tmux server are present; off-host they return
a meaningless empty result):

    # orphan reaper: what would it reap right now (expect 0 on a clean host)?
    scripts/hapax-orphan-spawn-reaper.py --dry-run

    # timer chain wired + scheduled?
    systemctl --user list-timers hapax-worktree-gc.timer hapax-lane-reaper.timer

    # GC's own view (removable vs removed vs live_refused) without mutating:
    scripts/hapax-worktree-gc.sh --dry-run --no-fetch

    # cap accounting (relocated infra must show as INFRASTRUCTURE, unknown: 0):
    scripts/worktree-cap-audit.sh --json

## 6. Cap adjustment — governance process

Changing the cap number (e.g. activating epsilon as a permanent
slot) requires:

1. Spec amendment under `docs/superpowers/specs/` stating the new
   session role, why the slot is needed, and the cleanup
   procedure for the existing state.
2. Update to the Policy table in this document.
3. Update to the `-ge N` threshold in
   `hooks/scripts/no-stale-branches.sh`.
4. Update to the approved-names list in
   `scripts/hapax-whoami-audit.sh` (if adding a new session name).
5. Update to the classification dispatch in
   `scripts/worktree-cap-audit.sh`.
6. Re-run `scripts/worktree-cap-audit.sh` and commit the result
   as evidence the new cap is honored.

The five-surface coupling is intentional — the cap is a load-bearing
invariant on four other subsystems (session naming, rebuild-logos
flock, session-conductor spawn, branch discipline hook). Changing
it in one place without the others produces silent drift.

## 7. Quick reference

Commands operators run most often:

- `scripts/worktree-cap-audit.sh` — inventory
- `scripts/worktree-cap-audit.sh --json` — JSON summary
- `scripts/hapax-whoami-audit.sh` — identity verification

To add a spontaneous worktree, use the standard worktree-add
command with a new branch; the hook enforces the cap. To remove
one, leave the spontaneous worktree first, then remove it from
alpha + prune.

## 8. Cross-references

- **Hook:** `hooks/scripts/no-stale-branches.sh` (session-wt cap)
- **Audit tool:** `scripts/worktree-cap-audit.sh`
- **Session-name audit:** `scripts/hapax-whoami-audit.sh`
- **Hooks README:** `hooks/scripts/README.md`
- **Workspace CLAUDE.md:** `CLAUDE.md` § Git Workflow
- **Feedback:** `feedback_worktree_persistence`,
  `feedback_rebuild_logos_worktree_detach`
- **Rebuild-logos flock contract:**
  `scripts/rebuild-logos.sh` (infrastructure worktree owner)
