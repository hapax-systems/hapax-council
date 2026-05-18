# CI Setup-Cost Elimination Prototype

Task: `ci-setup-cost-elimination-prototype-20260518`

## Implemented Path

The merge-group `test-title-cards` check remains present, but it no longer
does its own checkout, uv setup, apt install, or `uv sync`. The serial title-card
pytest command now runs inside `test-full-shard` shard 4 after that shard's
normal full-pytest work. The `test-title-cards` job is a sentinel that reports
the shard-matrix result, so the stable aggregate `test` check still requires
full pytest shards and serial title-card coverage before merge.

The aggregate `test` job also skips checkout on merge-group runs. In that mode
it only inspects `needs.test-full-shard.result` and
`needs.test-title-cards.result`, so repository checkout was redundant.

Merge-group matrix shards now restore uv cache with an explicit
`pyproject.toml` plus `uv.lock` dependency key and `save-cache: false`.
Every shard still runs `uv sync --extra ci --frozen`, so cache hits are only an
accelerator and cannot mask missing dependency setup.

## Expected Setup Seconds

Expected per merge-group run:

- Removed `test-title-cards` setup: 55-95 seconds.
- Removed aggregate `test` checkout: 4-8 seconds.
- Added sentinel overhead: 1-3 seconds.
- Net expected setup reduction: 58-103 seconds.

The restore-only matrix shard cache change should also avoid duplicate
post-job cache save, prune, and upload attempts when lockfile changes miss the
cache. That gain is not included in the seconds above because it depends on
cache-hit state and GitHub cache service timing.

## Deferred Runner/Image Path

No prebuilt CI container or self-hosted runner is adopted in this prototype.
Those paths remain deferred until a governed slice pins image provenance or
runner isolation, patching cadence, secret minimization, cache bounds,
teardown, and live-service resource contention. The existing self-hosted runner
experiment policy stays the adoption gate.
