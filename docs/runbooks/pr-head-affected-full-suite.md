# PR-head affected full-suite tests

PR CI checks out the pinned `github.event.pull_request.head.sha`, uses the
pinned `github.event.pull_request.base.sha`, and follows the existing
`git diff --no-renames --name-only BASE...HEAD` convention. The four full-suite
shards collect the same test surface used by merge groups, then run collected
test files that consume changed paths. A direct test edit runs that file;
deleted tests, unknown bases, unreadable consumer files and unclassified runtime
paths run the full suite. The selector logs each chosen test and causing path.
The required `test` check aggregates all four shards and the PR admission slice.
Merge-group shards and required context names remain unchanged.

Before calling a local PR head green, run the hosted lint equivalents from
`.github/workflows/ci.yml` at the exact head and state which you observed:

```bash
uv run python scripts/check-unused-functions.py --diff-range "$PR_BASE_SHA..HEAD"
uv run python scripts/system_dynamics_map_materialize.py
git diff --quiet -- 'docs/architecture/system-dynamics-map*' 'schemas/system-dynamics-map'
```

The first command is the CI unused-function gate. The second materializes the
architecture map, and the third is its freshness assertion. Materialization can
change generated files; inspect and commit authorized generated output before
claiming freshness.
