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

Either is sufficient, and the second supersedes the first:

1. `systemctl --user stop hapax-cc-pr-merge-watcher.timer`
2. Refresh `~/.cache/hapax/source-activation/worktree` to `origin/main`

## The deploy dependency is the actual point

**A code change to `scripts/cc-pr-merge-watcher.py` cannot fix this.** The fix
is already on `main` and has been for some time; it simply never reached the
running unit. Patching the script again would produce a green PR and change
nothing about the behaviour in production.

This is the same shape as the `Security Extras` outage fixed in the same PR:
a component was *configured* as active and *observed* as fine, while the thing
that actually runs had been dead or stale for weeks, because nothing checked the
gap between declared state and running state. The workflow half of that blindness
is now covered by `audit_workflow_health` in
`scripts/hapax-github-repo-standards-audit.py`. **The deploy half is not** — no
check compares the source-activation worktree's HEAD against `origin/main`. That
gap is what let both outages persist, and it remains open after this PR.
