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
  -k 'installed_hook or installer_refuses or runbook_verification'
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

What it does: for each ref being pushed, it enumerates every commit not reachable from any
verified ref on the actual push destination. It uses the push protocol's advertised tips plus
locally available commits advertised by `git ls-remote` on the push URL, including branches and
commit tags. Cached remote-tracking refs alone never exclude history: changing a remote URL or
using a different push URL must not hide unpublished content. If the destination cannot be
queried, the scan conservatively excludes only the push protocol's tips; fetch missing history
before retrying a refusal. New refs with no verified remote history scan every reachable commit.

Each commit is scanned, including intermediate commits whose content is removed later. Ordinary
commits are compared with their parent; roots with the empty tree. For merges, added positions
are intersected across **all parents**. Inherited lines were either already published or are
scanned at their introducing ancestor; a new conflict-resolution line remains in the scan.
This allows a published branch to merge main's existing fixtures without suppressing new content.
Text conversion is disabled so diff drivers cannot hide additions. The detectors are detect-secrets
`--all-files` with implicit filters disabled, a vendor-key prefix regex
(Anthropic, xAI, Hugging Face, GitLab, …), and a
`/home/<user>/` path check; the hook prints finding TYPES and counts, never values, and refuses
with a remedy. The installed policy's entropy-only exemptions are preserved for
`docs/architecture/system-dynamics-map*` and `config/capability-inventory-baseline.json*`.
Keyword and vendor detectors still apply on those paths.

`--all-files` alone does not prevent detect-secrets from skipping files. The hook disables
the extension (`is_non_text_file`), lockfile-name (`is_lock_file`), and Swagger-path
(`is_swagger_file`) filters. UTF-8 content in `.css`, `.svg`, `.lock`, or even `.png` files
is scanned. It also disables `is_indirect_reference`, `is_sequential_string`,
`is_potential_uuid`, `is_likely_id_string`, `is_templated_secret`,
`is_prefixed_with_dollar_sign`, and `is_not_alphanumeric_string`: apparent references,
IDs, templates, and candidate shapes are not implicit exemptions. The network verification
filter (`is_ignored_due_to_verification_policies`) is disabled too; matching strings are
not sent to providers and verification cannot suppress a finding. Only explicit inline
pragmas and the generated-path entropy policy suppress secret findings. Genuine false
positives require a declared pragma.

Detector line numbers are translated back to Git's LF-delimited lines, including files with
bare carriage returns or CRLF endings. Every scanned file must be valid UTF-8: detect-secrets
can silently skip other encodings. The scanner refuses such files by name without printing
their contents. Convert them to UTF-8 or remove them, then amend/rebase the affected commits
before retrying; changing only the branch tip leaves the earlier commits unscannable.

The installed policy's `systemd/units/` home-path exemption and inline
`pragma: allowlist secret` exemption for vendor findings are preserved. Home paths outside
that directory have no inline exemption. These are explicit policy exceptions, separate from
the remote-history exclusion. Git-binary changes are refused by path because no added text can
be scanned; remove them from the pushed history and obtain independent review.
Recheck all predicates,
per-commit behavior, and installed hook dispatch with the same pytest command above, omitting
the `-k` filter. The full suite also runs the real detect-secrets CLI. For an offline run with
cached tools, add `UV_TOOL_DIR=/store-fast/tmp/uv-tools-verify UV_OFFLINE=1` to that command's
environment.

Filter regressions alone: `uv run pytest tests/scripts/test_hapax_prepush_secret_scan.py
-q -k filters_cannot`. Each disabled filter has a refusal fixture. Filename fixtures cover
AWS and keyword findings, clean text, and explicit pragmas. Two fixtures use a local detector
extension through the real CLI to exercise dollar-prefixed candidates and a deterministic
negative verification result without network calls.

Exempting a whole private mirror: `git config --add
hapax.prepushScan.skipRemote <remote-name>`. There is no environment-variable bypass; if the hook refuses a
line the remote already has, the hook is wrong — fix it, do not `--no-verify`.
