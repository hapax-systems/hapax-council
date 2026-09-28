# pre-commit bootstrap

The pre-commit *framework* (the `pre-commit` CLI) is installed, but the
per-clone git hook at `.git/hooks/pre-commit` is **not** version-controlled.
Until it is installed in a given clone/worktree, the entire
`.pre-commit-config.yaml` (ruff, conflict-markers, claim-registry,
experiment-freeze, audio-conf gates, ...) never fires at commit time — only
CI catches violations, minutes later. This runbook closes that gap.

Current workstation state (2026-05-29): the hook is installed and executable
in the active council clone (`~/projects/hapax-council`) and the
active constitution clone (`~/projects/hapax-constitution`). New
clones, repaired worktrees, or rewritten git directories still need this
bootstrap because `.git/hooks/` is local state.

## One-time install (per clone)

```bash
scripts/install-git-hooks.sh
```

or directly:

```bash
pre-commit install --install-hooks
```

Re-running is safe and idempotent.

## `core.hooksPath` caveat (council)

Some council clones set `core.hooksPath` (redundantly) to the default
`.git/hooks`. pre-commit refuses to install while it is set:

> [ERROR] Cowardly refusing to install hooks with `core.hooksPath` set.

Resolve by clearing the redundant setting, then re-running:

```bash
git config --unset-all core.hooksPath || true
scripts/install-git-hooks.sh
```

Worktrees share the common git dir, so this only needs doing once per
underlying repository.

## Shared hooks (council)

The tracked `scripts/pre-commit` delegates to the framework; `scripts/pre-push`
runs both scanners and refuses if either is missing. After merge, the seat
enables the relative setting below. It resolves per worktree; update branches
missing the tracked hooks before relying on it.

```bash
git config core.hooksPath scripts
git config --get core.hooksPath   # scripts
```

## Verify

```bash
git config --get core.hooksPath   # scripts
test -x "$(git rev-parse --show-toplevel)/scripts/pre-commit"
test -x "$(git rev-parse --show-toplevel)/scripts/pre-push"
```

Recheck hook resolution from a linked worktree:

```bash
git -C /path/to/linked-worktree config --show-origin core.hooksPath
git -C /path/to/linked-worktree rev-parse --git-path hooks/pre-commit
git -C /path/to/linked-worktree rev-parse --git-path hooks/pre-push
```

For a task-scoped verification, run pre-commit on the files you touched:

```bash
pre-commit run --files path/to/changed-file.py path/to/changed-doc.md
```

Avoid `pre-commit run --all-files` in a dirty or peer-owned worktree unless the
active task explicitly authorizes broad source rewrites. Some hooks auto-format
files; an all-files run can create unrelated diffs outside your mutation
scope.

## Why this is a bootstrap step, not a committed hook

The framework's `.git/hooks/` hook is local; tracked wrappers ship in the repo.
Install the framework per clone so the pre-commit wrapper can delegate to it.
