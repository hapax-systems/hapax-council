# Worktree Cap Policy & Cleanup Runbook

**Status:** Normative. Enforced by
`hooks/scripts/no-stale-branches.sh` (PreToolUse on Bash).
**CVS Task:** #153 (worktree cap workflow fix).
**Audit tool:** `scripts/worktree-cap-audit.sh`.
**Owner:** operator; beta + delta propose cleanup, alpha resolves.

---

## 1. Policy — the cap is four

The workspace runs a **maximum of four session worktrees**. The
four slots are:

| Slot | Path convention | Permanence | Role |
|------|-----------------|------------|------|
| alpha | `hapax-council/` (top-level) | permanent | primary workstation-resident session |
| beta | `hapax-council--beta/` | permanent | secondary, livestream perf support |
| delta | `hapax-council--delta/` or `hapax-council--delta-*/` | permanent | tertiary, first-class since 2026-04-12 |
| spontaneous | `hapax-council--<slug>/` | temporary | ONE short-lived worktree for a specific task |

**Hard rules:**

- At most one spontaneous worktree exists at any time.
- The spontaneous slot must be cleaned up (merged / PR'd / removed)
  before a second spontaneous worktree can be created.
- Infrastructure worktrees under `~/.cache/` (e.g.
  `~/.cache/hapax/rebuild/worktree` managed by
  `scripts/rebuild-logos.sh` via `flock`) are NOT counted against
  the cap. They are disposable and recreated on demand.
- Gamma and epsilon are reserved session names (see
  `scripts/hapax-whoami-audit.sh`) but do not currently claim
  permanent worktree slots. An epic that activates either name
  must amend this table and adjust the cap.

**The cap exists because:**

- More than four concurrent worktrees produces cross-session stomp
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
   is already at the cap. Uses the same `/.cache/` filter as the
   audit tool so the numbers match.
3. **Operator discretion** — the operator reviews
   `worktree-cap-audit.sh` output before approving a spontaneous
   worktree request.

If the cap-enforcement logic in `no-stale-branches.sh` ever drifts
from the policy table above, fix the hook (grep for the session-wt
counter and the `-ge N` threshold). The audit tool and the hook
MUST agree on the count.

## 3. Classification decision tree

Given a worktree path, classify via:

    path starts with ~/.cache/         -> INFRASTRUCTURE (not counted)
    path == .../hapax-council          -> PRIMARY (alpha)
    path == .../hapax-council--beta*   -> SECONDARY permanent (beta)
    path == .../hapax-council--delta*  -> SECONDARY permanent (delta)
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

- Is not one of alpha / beta / delta / the current spontaneous
  slot.
- Is not under `~/.cache/`.
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
