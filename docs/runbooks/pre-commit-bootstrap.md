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

## Verify

```bash
test -x .git/hooks/pre-commit
sed -n '1,12p' .git/hooks/pre-commit
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

`.git/hooks/` is per-clone and outside version control, so the active hook
cannot ship in a PR — only the config and this bootstrap can. Run the
install once per clone, and again after any `git config` change that affects
hook resolution.
