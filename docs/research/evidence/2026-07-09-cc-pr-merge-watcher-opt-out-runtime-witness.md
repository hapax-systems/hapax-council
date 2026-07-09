# cc-pr-merge-watcher opt-out runtime witness

Date: 2026-07-09

Scope: PR #4472 / `cc-task-sdlc-wave3d-20260709`

Purpose: provide a durable live-runtime-composition witness for the merge-watcher
`close_on_pr_merge: false` path. The production reconciliation function was invoked
against an isolated temporary vault fixture copied from the active task note. The GitHub
runner was stubbed to report PR #4472 as `MERGED`; the run used `dry_run=True` and a
temporary repo root, so it could not mutate the real vault or execute the real
`scripts/cc-close`.

Command shape:

```bash
uv run python - <<'PY'
# import scripts/cc-pr-merge-watcher.py with importlib
# copy $VAULT_ROOT/active/cc-task-sdlc-wave3d-20260709.md into $TMPDIR/vault/active/
# stub gh api repos/hapax-systems/hapax-council/pulls/4472 -> MERGED
# call watcher.reconcile_stale_pr_states(vault_root=$TMPDIR/vault, dry_run=True, runner=stub)
PY
```

Observed output:

```text
INFO:cc-pr-merge-watcher:task cc-task-sdlc-wave3d-20260709 declares close_on_pr_merge: false - lane owner closes explicitly
fixture_frontmatter_pr 4472
fixture_frontmatter_close_on_pr_merge false
stubbed_pr_state MERGED
dry_run True
counters {"closed": 0, "repaired": 0, "scanned": 1, "stale": 0}
gh_calls 1
cc_close_invocations 0
note_still_active_contains_pr_open True
```

Interpretation:

- The production stale-PR reconciliation path reached the merged-PR closure branch.
- The task note's `close_on_pr_merge: false` frontmatter declined the close.
- No `cc-close` command was invoked.
- The fixture note remained `status: pr_open`.

Limit: this is an isolated dry-run witness, not a post-merge systemd timer witness. That is intentional for PR #4472 because the real PR is not merged yet; the evidence demonstrates the runtime path that would otherwise auto-close the multi-PR lane.
