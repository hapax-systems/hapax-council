# R-3 systemd user-units deploy-path reconcile (2026-05-01)

**cc-task:** `r3-systemd-user-units-reconcile` (P3, WSJF 4.8)
**Author:** epsilon
**Source:** `~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md` §R-3 (P0-3 / P0-4 in the audit corpus)

## Premise

The 2026-04-26 absence-bugs synthesis flagged that four unit files
under `systemd/user/` were silently invisible to the deploy chain
because `scripts/hapax-post-merge-deploy`'s glob-match cases cover
`systemd/*.{service,timer,path}` and `systemd/units/*.{service,timer,path,target}`
but **not** `systemd/user/*`. The CLAUDE.md guidance is explicit:

> **Canonical path for new systemd units: `systemd/units/`** —
> `scripts/hapax-post-merge-deploy` matches `systemd/units/*.service|*.timer`
> only; files placed elsewhere (e.g., `systemd/user/`) are silently
> invisible to the deploy chain.

The four files at `systemd/user/` had been carrying real, production-relevant
unit definitions but would never deploy via the post-merge automation.

## State at 2026-05-01 (pre-fix)

The `systemd/user/` directory contained:

| File | Status | Rationale |
|---|---|---|
| `hapax-assets-publisher.service` | **stale duplicate** | Older draft of the same unit; PR #1957 shipped the canonical version at `systemd/units/hapax-assets-publisher.service` (with cleaner `Restart=on-failure` + `RestartSec=30s` semantics) |
| `hapax-refusal-brief-rotate.service` | **orphaned** | No counterpart at `systemd/units/`; deploy chain skipped silently |
| `hapax-refusal-brief-rotate.timer` | **orphaned** | Same; the daily-at-midnight UTC rotation timer never deployed |
| `hapax-thumbnail-rotator.service` | **orphaned** | Same; the YouTube thumbnail rotation daemon never deployed |

None of these are tracked by the frozen `systemd/expected-timers.yaml`
baseline (which covers the 11 pre-registry-migration timers; new
timers go through `agents/manifests/*.yaml` per
`shared.agent_registry`).

## Action (this PR)

Three moves + one delete:

```
git mv systemd/user/hapax-thumbnail-rotator.service        systemd/units/
git mv systemd/user/hapax-refusal-brief-rotate.service     systemd/units/
git mv systemd/user/hapax-refusal-brief-rotate.timer       systemd/units/
git rm systemd/user/hapax-assets-publisher.service
rmdir systemd/user/  # removed by the moves; verifying empty
```

After the moves, `systemd/user/` no longer exists in the tree. All
unit files now live under the canonical `systemd/units/` glob the
deploy script case-matches. Future drops to `systemd/user/` are
guarded structurally by the CI `hapax-post-merge-deploy
--report-coverage` check (P-4 in the absence-bugs synthesis), which
fails when a `systemd/**` change lands at an unrecognized glob.

## What was the assets-publisher duplication?

`systemd/user/hapax-assets-publisher.service` predated the
hapax-assets CDN recovery work I shipped this morning in PR #1957.
The user/ version had:

```
Restart=on-failure
RestartSec=30
EnvironmentFile=-%h/.config/hapax/env
```

The canonical units/ version (PR #1957) has:

```
Environment=HOME=%h
Environment=PYTHONPATH=%h/projects/hapax-council
Restart=on-failure
RestartSec=30s
```

Functionally equivalent, but the units/ version uses the same
ExecStart+Environment shape as every other Python service in
`systemd/units/`, and the deploy chain actually picks it up. The
user/ version was the original draft from before the canonical-path
discipline shipped; deleting it removes the last gap-state where
the operator might enable "the wrong copy" by name.

## Acceptance status

- [x] Inventory repo unit files, install scripts, and deployed user
  units → §"State at 2026-05-01" matrix; deploy script glob-match
  cases enumerated.
- [x] Identify stale deploy paths or prove the concern is already
  resolved → 4 files at `systemd/user/` were silently invisible:
  1 stale duplicate (assets-publisher), 3 orphans
  (refusal-brief-rotate × 2, thumbnail-rotator).
- [x] Patch docs/scripts/tests if stale paths remain → 3 moves +
  1 delete; `systemd/user/` directory is removed.
- [x] Record closure evidence in the relay/vault task → this doc;
  the cc-task `r3-systemd-user-units-reconcile` close note
  references this PR.

## Why these were specifically dangerous

The orphaned units carried production-relevant behavior the operator
expected to be running:

- `hapax-thumbnail-rotator.service` rotates YouTube thumbnails from
  compositor snapshots (ytb-003). With this unit invisible to deploy,
  every post-merge cycle would have left the rotator at whatever
  state the operator had hand-installed — drift between repo and
  deployed state.
- `hapax-refusal-brief-rotate.{service,timer}` performs the daily
  midnight-UTC archive of `/dev/shm/hapax-refusals/log.jsonl` to
  the operator's permanent record at `~/hapax-state/refusals/`.
  Constitutional "append-only is the spec" rotation. With this
  invisible, the operator would have to remember to re-install
  on reboot — not impossible but a footgun.

The stale duplicate (`hapax-assets-publisher.service` at user/)
would have been the more confusing failure: if the operator
`systemctl --user enable`'d "the one I see," they could land on
the user/ version that the post-merge deploy never updates,
leaving the CDN publisher pinned to an early-draft definition
across upgrades.

Removing all four resolves R-3 cleanly.

## Pointers

- Deploy script: `scripts/hapax-post-merge-deploy` (glob-match cases lines ~50–60)
- CLAUDE.md governance: workspace-level CLAUDE.md § "Infrastructure" / "Canonical path for new systemd units"
- Frozen baseline: `systemd/expected-timers.yaml` (none of the moved units appear here; no regression risk)
- Source synthesis: `~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md` §R-3 (P0-3 / P0-4)
- Related cc-task (different scope, broader): `systemd-deploy-path-rationalize` per the synthesis (covers 23 top-level `systemd/*` files; this PR addresses the 4 `systemd/user/` files only)
- Predecessor PR for the canonical assets-publisher unit: #1957 (`feat(hapax-assets): scheme-agnostic remote check + missing systemd unit (CDN recovery)`)
