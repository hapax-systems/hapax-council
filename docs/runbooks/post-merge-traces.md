# Post-Merge Traces

`scripts/hapax-post-merge-deploy` writes a durable JSONL trace for each
post-merge deploy dry-run and completed deploy run. The trace records the merge
commit, status, changed files, classified deploy groups, whether manual deploy
work was needed, and whether it actually ran.

Default storage:

```bash
~/.cache/hapax/post-merge-traces/post-merge-traces.jsonl
```

Retention is bounded by record count. The default is 200 records. Override it
for tests or one-off diagnostics:

```bash
HAPAX_POST_MERGE_TRACE_MAX_RECORDS=50 scripts/hapax-post-merge-deploy --dry-run <merge-sha>
```

Use `HAPAX_POST_MERGE_TRACE_PATH` to redirect the trace file during tests:

```bash
HAPAX_POST_MERGE_TRACE_PATH=/tmp/post-merge-traces.jsonl \
  scripts/hapax-post-merge-deploy --dry-run <merge-sha>
```

Agent handoff inspection:

```bash
tail -n 20 ~/.cache/hapax/post-merge-traces/post-merge-traces.jsonl | jq .
```

For a specific merge commit:

```bash
jq 'select(.event == "post_merge_deploy" and .sha == "<merge-sha>")' \
  ~/.cache/hapax/post-merge-traces/post-merge-traces.jsonl
```

## Auto-invocation

As of 2026-05-03 the deploy script is fired automatically by
`hapax-post-merge-deploy.path` whenever the canonical local main ref
(`~/projects/hapax-council/.git/refs/heads/main`) advances. The `.service`
unit resolves the new HEAD via `git rev-parse main` and hands it to the
script — see `systemd/README.md` § "Post-Merge Auto-Deploy".

Confirm a fire landed in the trace after a merge:

```bash
systemctl --user status hapax-post-merge-deploy.path
journalctl --user -u hapax-post-merge-deploy.service -n 50 --no-pager
tail -n 5 ~/.cache/hapax/post-merge-traces/post-merge-traces.jsonl | jq .
```
