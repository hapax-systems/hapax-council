# Merge-watcher runs a stale deploy — containment request

**Date:** 2026-08-08
**Task:** post-crossing-runtime-hardening-20260808 (finding 1)
**AuthorityCase:** CASE-CAPACITY-ROUTING-001
**Status:** contained-by-request — the acting session could not execute the containment

## What is wrong

`hapax-cc-pr-merge-watcher.service` runs out of the source-activation worktree,
not out of a checkout of `main`:

```
ExecStart=%h/.local/bin/uv --directory %h/.cache/hapax/source-activation/worktree \
  run python scripts/cc-pr-merge-watcher.py --repo-root %h/.cache/hapax/source-activation/worktree
```

That worktree is pinned at `48aac035e`, which predates the `pr_repo` fix:

| copy | `grep -c pr_repo scripts/cc-pr-merge-watcher.py` |
|---|---|
| deployed worktree (`48aac035e`) | 0 |
| `origin/main` (`158e746bf`) | 20 |

So the running watcher still matches cc-tasks by **bare PR number**. That is the
failure recorded in CLAUDE.md as closing the wrong task, measured twice on
2026-08-04. Any PR number that collides across repos closes the wrong task.

## Correction to the task note

The task note states "Timer stopped as containment." That was not true when this
was checked on 2026-08-08:

```
$ systemctl --user is-active hapax-cc-pr-merge-watcher.timer
active
$ systemctl --user is-enabled hapax-cc-pr-merge-watcher.timer
enabled
```

Last trigger: 2026-08-08T06:28:46Z. The containment was never applied, so the
hazard has been live continuously.

## Why this session did not fix it

```
cc-task-gate: BLOCKED — AuthorityCase 'CASE-CAPACITY-ROUTING-001' does not
authorize runtime mutation.
```

This is the gate behaving correctly. Stopping a systemd unit is runtime
mutation; this task's AuthorityCase covers source only. The action needs the
runtime-activation task.

## Requested action

These are **not** equivalent and the order matters. Stopping the timer prevents the
next launch; it does not stop an invocation already running, and refreshing the
worktree does not change code already loaded into a running process.

Immediate containment, in sequence:

1. `systemctl --user stop hapax-cc-pr-merge-watcher.timer` — stops future launches only.
2. `systemctl --user stop hapax-cc-pr-merge-watcher.service` — stops an in-flight run.
3. Verify it is actually down before believing step 1 or 2:
   `systemctl --user is-active hapax-cc-pr-merge-watcher.service` must print `inactive`.

Durable fix, which requires the runtime-activation task's authority (see above):

4. Refresh `~/.cache/hapax/source-activation/worktree` to `origin/main`, then restart
   the unit. Until the restart, the refreshed source is on disk and not in the process.

## Recheck

Every state claim above is a one-off observation from 2026-08-08 and may no
longer hold. These reproduce all of them. The last one is the check whose
absence this document is about, written out so a reader can run the comparison
that no automation currently makes:

```bash
# Which tree does the unit actually run from?
systemctl --user cat hapax-cc-pr-merge-watcher.service | grep ExecStart

# Is the containment applied?
systemctl --user is-active hapax-cc-pr-merge-watcher.timer
systemctl --user is-enabled hapax-cc-pr-merge-watcher.timer
systemctl --user show hapax-cc-pr-merge-watcher.timer -p LastTriggerUSec

# Does the deployed copy carry the pr_repo fix?
# A substring count is NOT the check: `grep -c pr_repo` matches comments and string
# literals, so it can certify a copy that still closes the wrong task. Ask whether the
# deployed find_linked_tasks actually reads the task's repo and compares it.
python3 - <<'PY'
import ast, pathlib
src = pathlib.Path.home() / ".cache/hapax/source-activation/worktree/scripts/cc-pr-merge-watcher.py"
tree = ast.parse(src.read_text())
fn = next((n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "find_linked_tasks"), None)
if fn is None:
    print("STALE: find_linked_tasks is absent")
else:
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)} | \
            {c.value for c in ast.walk(fn) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    print("FIXED" if "pr_repo" in names else "STALE",
          "- find_linked_tasks", "compares" if "pr_repo" in names else "does NOT compare",
          "the task repository")
PY

# THE GAP: deployed source vs the real origin/main.
# rev-parse alone is not proof: it ignores staged, unstaged and untracked changes, and a
# local remote-tracking ref can be arbitrarily stale. Fetch first, and require a clean tree.
DEPLOY=~/.cache/hapax/source-activation/worktree
git -C "$DEPLOY" fetch --quiet origin main
test -z "$(git -C "$DEPLOY" status --porcelain)" \
  || echo "DIRTY: deployed worktree has uncommitted changes; HEAD does not describe what runs"
test "$(git -C "$DEPLOY" rev-parse HEAD)" = "$(git -C "$DEPLOY" rev-parse FETCH_HEAD)" \
  && echo "deploy is current" || echo "STALE: deployed HEAD != origin/main"
```

Fetch inside the deployed worktree itself, not a third clone. `~/projects/hapax-council`
is the wrong reference point: its local `main` is orphaned, so reading `origin/main` there
can report parity against a branch that is months behind.

A reader who finds the deploy stale, or the tree dirty, is looking at the same class of
staleness this document reports, whatever the current commits happen to be.

## The deploy dependency is the actual point

**A code change to `scripts/cc-pr-merge-watcher.py` cannot fix this.** The fix
is already on `main` and has been for some time; it simply never reached the
running unit. Patching the script again would produce a green PR and change
nothing about the behaviour in production.

This is the same shape as the `Security Extras` outage fixed in the same PR:
a component was *configured* as active and *observed* as fine, while the thing
that actually runs had been dead or stale for weeks, because nothing checked the
gap between declared state and running state.

Neither half is enforced. `audit_workflow_health` in
`scripts/hapax-github-repo-standards-audit.py` gives the workflow half **advisory**
coverage only: it is not a GitHub check, not a required merge gate, and not on any
timer or manifest — it runs when a person runs it. Calling that "covered" would
repeat the exact mistake this document reports, which is treating a declared
capability as a running one.

**The deploy half has no coverage at all** — no check compares the source-activation
worktree's HEAD against `origin/main`. That gap is what let both outages persist, and
it remains open after this PR.
