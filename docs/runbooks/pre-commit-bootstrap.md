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

Every detector invocation sees exactly one staged file. In the inspected detect-secrets
1.5.0 source, `SecretsCollection.scan_files` creates a multiprocessing pool for two or
more files, even with one requested processor. Its initializer calls
`Settings.configure_filters`, which reinstates `DEFAULT_FILTERS`, including the extension
filter; serialized settings cannot represent its removal. The hook therefore stages,
scans, and removes each file before staging the next. CSS/SVG/lockfile coverage must hold
with clean companion files as well as when scanned alone.

The same source inspection found that YAML and INI transformers omit comments, keys, and
other raw text. Each file receives both its normal scan and a supplemental raw scan with
the same filename and a first-line `@hapax-prepush-raw@` marker. In 1.5.0 this marker makes
both parsers (including eager INI parsing) reject the format and scan the raw lines. All
original bytes remain after the marker; its one-line offset is removed before checking
added Git lines. Findings from both views are combined. Filename-specific pragma rules
and generated-path entropy exemptions apply to both views. This costs two detector
processes per file; it never falls back to a batch scan.

The `uvx` invocation pins 1.5.0, and results from an executable on PATH must also report
1.5.0. Missing or different versions produce exit 3, `REFUSED [detector-version]`, with
an installation remedy. An unavailable detector, nonzero exit (including rejected filter
configuration), or invalid result produces a typed refusal, including if an earlier file
or the normal view scanned successfully. There is no retry with weaker configuration.

Detector line numbers are translated back to Git's LF-delimited lines, including files with
bare carriage returns or CRLF endings. Every scanned file must be valid UTF-8: detect-secrets
can silently skip other encodings. The scanner refuses such files by name without printing
their contents. Convert them to UTF-8 or remove them, then amend/rebase the affected commits
before retrying; changing only the branch tip leaves the earlier commits unscannable.

Filenames containing a backslash are refused with exit 3 and
`REFUSED [unsupported-filename]`: detect-secrets 1.5.0 rewrites that character into a
directory separator when scanning a single file and can silently skip its content.
The refusal applies to clean files and multiple-file scans too. Staging also refuses
absolute paths and empty, `.` or `..` components that could alias another path. The
diagnostic prints each affected filename with escaped control characters. Rename the
files to canonical relative paths without backslashes, then amend/rebase every affected
commit before retrying. Leading dashes, newlines, and other literal separators are scanned.
Recheck: `uv run pytest tests/scripts/test_hapax_prepush_secret_scan.py -q -k
'backslash or unmappable or supported_filename_separators'`.

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
AWS and keyword findings, clean text, and explicit pragmas with one, two, and five staged
files. Two fixtures use a local detector
extension through the real CLI to exercise dollar-prefixed candidates and a deterministic
negative verification result without network calls.

Skip-class recheck: `uv run pytest tests/scripts/test_hapax_prepush_secret_scan.py -q -k
'companion or multifile or filters_cannot or transformers or raw_scan or later_file or
backslash or unmappable or supported_filename or non_utf8 or binary_classification or
symlink or carriage_returns or staging_preserves or content_status'`.

| Potential omission in the inspected source | Guard and regression |
| --- | --- |
| Multiprocessing restores the extension filter | One staged file per call; `test_clean_companion_cannot_hide_css_aws_key`, `test_multifile_scan_reports_every_secret_file` |
| Extension, lockfile, Swagger, candidate, or verification filter | Explicit disabling; `test_real_detector_filename_filters_cannot_exempt_text`, `test_real_detector_content_filters_cannot_exempt_findings`, `test_real_detector_filters_cannot_discard_plugin_findings` |
| YAML/INI transformation discards source text | Supplemental raw view; `test_real_detector_transformers_cannot_hide_comments`, `test_real_detector_transformers_preserve_all_added_content` |
| Scratch directory lacks tracked files; symlink or path normalization omits a file | `--all-files`, regular-file staging, literal Git paths, and unsupported-name refusal; filename, staging, and symlink regressions |
| Non-UTF-8 decoding or Git binary classification omits content | Explicit refusal; `test_real_detector_refuses_non_utf8_text`, `test_git_binary_classification_refuses_and_names_unscannable_file` |
| CR/CRLF or the raw marker shifts added-line attribution | Explicit line mapping; carriage-return regressions and `test_raw_scan_preserves_added_line_and_pragma_policy` |
| Detector failure or unsupported version after earlier successful files | Exit 3 without retry; `test_later_file_detector_failure_refuses_without_retry`, installed-hook failure regressions |

Intentional exclusions remain verified destination history, deleted/unchanged content,
explicit pragmas, and the declared entropy/home-path exceptions; the full suite covers
these separately. File extension and file count are never exemptions.

Exempting a whole private mirror: `git config --add
hapax.prepushScan.skipRemote <remote-name>`. There is no environment-variable bypass; if the hook refuses a
line the remote already has, the hook is wrong — fix it, do not `--no-verify`.
