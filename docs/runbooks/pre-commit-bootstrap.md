# pre-commit bootstrap

The pre-commit *framework* (the `pre-commit` CLI) is installed, but the
per-clone git hooks under the common git directory are **not** version-controlled.
Until they are installed in a given clone, the entire
`.pre-commit-config.yaml` (ruff, conflict-markers, claim-registry,
experiment-freeze, audio-conf gates, ...) never fires at commit time — only
CI catches violations, minutes later. The same bootstrap installs the
scan-before-push hook. This runbook closes both gaps without one hook masking the other.

Migration state (2026-09-04): any clone configured by the superseded
`core.hooksPath=scripts` instructions must clear that setting and re-run this installer. An
executable common-directory hook is not active while another `core.hooksPath` is configured. New
clones, repaired worktrees, or rewritten git directories also need this bootstrap because the
common hook directory is local state.

## One-time install (per clone)

```bash
scripts/install-git-hooks.sh
```

The installer composes `pre-commit` and `pre-push` in
`$(git rev-parse --git-common-dir)/hooks`. To perform the equivalent steps directly:

```bash
git config --unset-all core.hooksPath || true
pre-commit install --install-hooks
hooks_dir="$(git rev-parse --path-format=absolute --git-common-dir)/hooks"
install -d "$hooks_dir"
install -m 0755 scripts/pre-push "$hooks_dir/pre-push"
```

Re-running is safe and idempotent.

## `core.hooksPath` caveat (council)

Some council clones set `core.hooksPath`, including to `scripts` under the superseded
pre-push instructions. That setting replaces Git's entire hook lookup directory and would make
one of these hooks mask the other. Pre-commit also refuses to install while it is set:

> [ERROR] Cowardly refusing to install hooks with `core.hooksPath` set.

Resolve by clearing the setting, then re-running:

```bash
git config --unset-all core.hooksPath || true
scripts/install-git-hooks.sh
```

Worktrees share the common git dir, so this only needs doing once per
underlying repository.

## Verify

```bash
(
# An unset value returns 1. Any configured value, including an empty one, masks hooks.
if git config --show-origin core.hooksPath; then
  echo "core.hooksPath masks the shared hooks. Clear it at the reported origin and re-run the installer." >&2
  exit 1
fi
git rev-parse --git-path hooks
hooks_dir="$(git rev-parse --path-format=absolute --git-common-dir)/hooks"
effective_hooks="$(git rev-parse --path-format=absolute --git-path hooks)"
test "$effective_hooks" = "$hooks_dir" || exit 1
test -x "$hooks_dir/pre-commit" || exit 1
test -x "$hooks_dir/pre-push" || exit 1
sed -n '1,12p' "$hooks_dir/pre-commit"
)
```

Repeat these checks from each linked worktree: worktree-specific configuration can change
Git's effective hook directory even though the executable files exist in the common directory.

Exercise actual Git hook dispatch with the hermetic integration tests below. They create a local
bare remote and temporary clone under `/store-fast/tmp`, install the versioned wrapper, and run
`git push` from both the clone and a linked worktree. They assert the hook's exit via Git trace2,
the push status, and whether the remote ref moved: clean pushes pass and dirty pushes refuse.
The fallback and failure tests also check the named recovery action. No network or changes to
this checkout's installed hooks are involved; pre-commit and detector failure cases use test tools.

```bash
env -u HAPAX_GLMCP_MODEL -u HAPAX_GLMCP_REVIEW_MODEL \
  -u HAPAX_GLMCP_REVIEW_PAYG_FALLBACK -u HAPAX_GLMCP_REVIEW_ALLOW_NON_CODING_PLAN_MODEL \
  UV_CACHE_DIR=/store-fast/tmp/uv-cache-verify TMPDIR=/store-fast/tmp \
  uv run pytest -q -p no:cacheprovider tests/scripts/test_hapax_prepush_secret_scan.py \
  -k 'installed_hook or installer_refuses_conflicting_hooks_path or runbook_verification'
```

For a task-scoped verification, run pre-commit on the files you touched:

```bash
pre-commit run --files path/to/changed-file.py path/to/changed-doc.md
```

Avoid `pre-commit run --all-files` in a dirty or peer-owned worktree unless the
active task explicitly authorizes broad source rewrites. Some hooks auto-format
files; an all-files run can create unrelated diffs outside your mutation
scope.

## Why installation is still a bootstrap step

The active common hook directory is per-clone and outside version control. The pre-push source
ships as `scripts/pre-push`, but the bootstrap must copy it beside the generated pre-commit hook.
Run the install once per clone, after updating the versioned pre-push source, and after any
`git config` change that affects hook resolution.

## Scan before push (`scripts/pre-push`) — installed once per clone

Added 2026-09-02 (operator-accepted rule: no push leaves a clone without a detect-secrets
scan plus a `/home/` grep over the new commits). `scripts/pre-push` is the repo-versioned source;
`scripts/install-git-hooks.sh` copies it into the common hook directory beside `pre-commit`, and
every worktree of that clone shares both hooks.

Do not point `core.hooksPath` at `scripts`: Git would stop consulting the common directory and
silently disable the pre-commit hook. Re-run the installer when `scripts/pre-push` changes.

What it does: for each ref being pushed, it enumerates every commit not reachable from the remote
tip (or the known remote default branch for a new ref) and scans the lines each commit ADDS against
its first parent. Root commits are compared with the empty tree. The detectors are detect-secrets
`--all-files`, a vendor-key prefix regex (Anthropic, xAI, Hugging Face, GitLab, …), and an
absolute-home-path check; the hook prints finding TYPES and counts, never values, and refuses with
a remedy. Entropy-only findings on the codebase-derived
`docs/architecture/system-dynamics-map*` files are not secrets and are skipped there.

There is no path-based exemption from the absolute-home-path check, including under
`systemd/units/`, and neither the vendor-key nor home-path detector has a line-level allowlist. A
unit that needs an operator-specific path must be parameterized. Recheck all predicates,
per-commit behavior, and installed hook dispatch with the same pytest command above, omitting
the `-k` filter. The full suite also runs the real detect-secrets CLI. For an offline run with
cached tools, add `UV_TOOL_DIR=/store-fast/tmp/uv-tools-verify UV_OFFLINE=1` to that command's
environment.

Exempting a private mirror (the only sanctioned exemption): `git config --add
hapax.prepushScan.skipRemote <remote-name>`. There is no in-script bypass; if the hook refuses a
line the remote already has, the hook is wrong — fix it, do not `--no-verify`.
