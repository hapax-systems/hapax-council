# pre-commit bootstrap

The pre-commit *framework* (the `pre-commit` CLI) is installed, but the
per-clone git hook at `.git/hooks/pre-commit` is **not** version-controlled.
Until it is installed in a given clone/worktree, the entire
`.pre-commit-config.yaml` (ruff, conflict-markers, claim-registry,
experiment-freeze, audio-conf gates, ...) never fires at commit time — only
CI catches violations, minutes later. This runbook closes that gap.

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
git config --unset core.hooksPath
scripts/install-git-hooks.sh
```

Worktrees share the common git dir, so this only needs doing once per
underlying repository.

## Verify

```bash
pre-commit run --all-files   # first run is slow; it builds tool envs
```

## Why this is a bootstrap step, not a committed hook

`.git/hooks/` is per-clone and outside version control, so the active hook
cannot ship in a PR — only the config and this bootstrap can. Run the
install once per clone, and again after any `git config` change that affects
hook resolution.
