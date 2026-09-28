# pre-commit bootstrap

The pre-commit *framework* (the `pre-commit` CLI) is installed, but the
per-clone git hook at `.git/hooks/pre-commit` is **not** version-controlled.
Without a hook path or per-clone install, the entire
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

For a clone without the shared activation hook path, resolve by clearing the
redundant setting, then re-running:

```bash
git config --unset-all core.hooksPath || true
scripts/install-git-hooks.sh
```

Worktrees share the common git dir, so this only needs doing once per
underlying repository.

## Shared hooks (council)

The tracked `scripts/pre-commit` delegates to the framework using the
activation worktree's `.pre-commit-config.yaml`. The pushing branch's config
does not select the checks: the hook passes an absolute config path from its
own directory. `scripts/pre-push` runs both scanners, looking in that same
hook directory first, then the pushing worktree, then the primary checkout.
It refuses when a scanner is absent everywhere.

After this change merges, the seat records the previous absolute value and
sets the shared path to the activation worktree, which follows merged main:

```bash
previous_hooks_path="$(git config --get core.hooksPath)"
activation_hooks="$HOME/.cache/hapax/source-activation/worktree/scripts"
git config core.hooksPath "$activation_hooks"
git config --get core.hooksPath   # absolute path through the moving worktree symlink
```

## Verify

```bash
activation_hooks="$(git config --get core.hooksPath)"
test -x "$activation_hooks/pre-commit"
test -x "$activation_hooks/pre-push"
```

Recheck hook resolution from a linked worktree:

```bash
git -C /path/to/linked-worktree rev-parse --git-path hooks/pre-commit
git -C /path/to/linked-worktree rev-parse --git-path hooks/pre-push
```

Both paths must resolve under `activation_hooks`, including from a Codex
worktree whose branch predates the tracked hooks. Verify a test push from that
worktree invokes the name scanner before treating this activation as complete.
If activation fails, restore the recorded previous absolute value:

```bash
git config core.hooksPath "$previous_hooks_path"
git config --get core.hooksPath
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
The council shared path selects the activation wrappers. Other clones without
that setting still need the per-clone install.
