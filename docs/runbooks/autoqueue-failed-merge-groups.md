# Failed merge-group admission

A queue admission decision belongs to a source commit. A failed integration
run belongs to a synthetic commit built against a base commit. These identities
must be joined by observed evidence before a failure can be attributed to a
source head.

`scripts/cc-pr-autoqueue.py` reads one page of at most 100 `merge_group` runs
and one batched query of the last 20 removal events per examined PR. Reads use
the existing GitHub rate governors, without sleep, pagination, alternate
transport fallback, or retry-count exceptions. This is a bounded observation,
not a complete repository history. The normal rotating PR window still applies.
If the run page is truncated, all examined PRs have unknown history and are
held. A truncated removal timeline holds that PR. PRs beyond the 100 aliases in
the observation query receive `pr_query_limit`; they are never silently cleared.
The bounded ledger alone cannot establish coverage of omitted history. In a
repository with more than 100 retained merge-group runs this can hold every
examined PR indefinitely: waiting for a new tick or publishing a new source
head does not establish the missing coverage. Release must account for this
constraint; do not represent the observation as complete or raise an exception
to admission just to drain the queue.

The `gh-readonly-queue/<base>/pr-<number>-<sha>` suffix is a base SHA; the run's
`head_sha` and a removal event's `beforeCommit.oid` identify the synthetic
commit. Neither identifies the source head. Source attribution is retained
only after the same query observes the live queue entry's synthetic commit
alongside its PR source head. The existing lineage record carries this binding
in `lifecycle_reasons`, scoped to repository, PR, and source SHA. Older records
that filled `pr_head_sha` from a current PR or the branch suffix do not establish
that binding.

An observed failed run at the same bound source head produces
`queue_refused:merge_group_failed_at_head:<run_id>` and the existing admission
status says `cc-pr-autoqueue held: merge_group_failed_at_head:<run_id>`. A new
source head is evaluated afresh against all ordinary admission requirements.
Every positive enqueue uses `--match-head-commit` to bind the mutation to the
examined head. A successful rerun does not erase an already observed failure.
Completed runs require a recognized terminal conclusion; nonterminal runs must
have a recognized status and no conclusion. Malformed entries hold admission
while valid later entries still contribute observed failures.

Queue-bot `failed_checks` removal events join runs by synthetic SHA. The existing
JSONL lineage records retain the removal time, source binding when known, run
ID, and conclusion. Failed runs count in the existing storm report regardless
of the PR's current readiness or presence in the examination window. The
existing failure-rate throttle and bisection recommendation consume these
records; this change introduces no threshold waiver or new store.
The shared JSONL writer preserves source bindings, queue-bot removal evidence
and failed attempts across ordinary collection and autoqueue observation. Both
writers use the existing path lock for their read/merge/replace transaction.
Conflicting run identities refuse the write instead of replacing evidence.

`merge_group_observation` in the existing report describes query limits,
truncation, and unresolved evidence. When observation is incomplete,
`storm_mode.failed_recent_merge_group_run_count` is null, and
`observed_failed_recent_merge_group_run_count` retains the known lower bound.
Consumers must not turn null into a healthy zero. Otherwise admissible PRs with
unresolved evidence receive `merge_group_evidence_unknown:<reason>` and a
pending admission status. Existing definitive blockers remain visible.

Historical source bindings that were never captured cannot be reconstructed
from today's PR head. Such a failure remains unknown and held; publishing a new
head alone cannot prove which source an unbound historical group tested.
Repair requires independent evidence of that historical source/group binding
through the existing lineage producer. There is no manual retry waiver. Missing
runs outside the bounded page are also reported as unresolved, not absent.

Verification is offline with injected GitHub responses:

```sh
TMPDIR=/store-fast/tmp uv run pytest tests/test_cc_pr_autoqueue.py -q -p no:cacheprovider
```

Release requires independent review and installed timer/report readback. Unit
tests establish behavior against fixtures; they do not establish current live
capture or activation. Source authors do not supply independent acceptance.

The existing emergency controls stop automation. An operator may stop the timer
and any current invocation with:

```sh
systemctl --user stop hapax-cc-pr-autoqueue.timer hapax-cc-pr-autoqueue.service
```

The existing `HAPAX_CC_PR_AUTOQUEUE_OFF=1` or `HAPAX_CC_HYGIENE_OFF=1` binding
also makes the reconciler exit before queue mutations. Apply bindings through
the normal service configuration process; a variable exported only in a shell
does not change an already configured systemd service. These controls do not
grant manual enqueue authority or bypass failed-head admission. This task's
source owner has no runtime mutation or release authority.

A low REST budget holds merge-group observation even if GraphQL can still read
queue rules: those rules do not contain workflow-run outcomes. Keep the hold,
allow the existing budget governor to recover, and check the next report.
For truncated or missing history, recovery instead requires independently
verified coverage/source-binding evidence through the existing producer and
reviewed reader contract. A successful API response, empty page, head change or
operator retry count is not that evidence. After the cause is repaired and the
release owner authorizes resumption, restart the existing timer. There is no
fallback transport or retry-count waiver.

Read back the installed invocation and source without printing service secrets:

```sh
systemctl --user show hapax-cc-pr-autoqueue.service -p FragmentPath -p DropInPaths -p ExecStart
systemctl --user show hapax-cc-pr-autoqueue.timer -p ActiveState -p NextElapseUSecRealtime
git -C ~/.cache/hapax/source-activation/worktree rev-parse HEAD
sha256sum ~/.cache/hapax/source-activation/worktree/scripts/cc-pr-autoqueue.py \
  ~/.cache/hapax/source-activation/worktree/shared/merge_queue_lineage.py
```

At the 2026-10-12 15:09Z readback the installed override still supplied
`--limit 5`; active source `a4768d88429639e13701fba474901990e3f945b5` already had
persistent PR rotation. The source unit uses the default limit of 100. The
historical starvation concern is covered by the existing rotation tests,
including multiple sweeps with a repeatedly failing PR. This source repair does
not widen the runtime override; that requires the release owner's authority.

Inspect the current report and retained bindings (the paths below are the
default bindings; reconcile any installed CLI overrides first):

```sh
stat ~/.cache/hapax/orchestration/cc-pr-autoqueue-report.json
jq '{merge_group_observation, storm_mode: (.storm_mode | {
  failed_recent_merge_group_run_count, observed_failed_recent_merge_group_run_count,
  failed_recent_merge_group_runs}), decisions: [.decisions[]? | {pr, action, reasons}]}' \
  ~/.cache/hapax/orchestration/cc-pr-autoqueue-report.json
jq -c '{merge_group_run_id, pr_number, pr_head_sha, synthetic_queue_sha,
  run_attempt, run_conclusion, cancellation_requeue_reason,
  source_bindings: [.lifecycle_reasons[]? | select(startswith("autoqueue_source_head:"))]}' \
  ~/.cache/hapax/post-merge-traces/merge-queue-lineage.jsonl
```

Retain before/after readbacks around a normal lineage-collector tick and check
the same run IDs: bindings, failure and removal must survive collection. Compare
source and synthetic identities separately. An absent observation field means
the installed reader has not demonstrated this contract; incomplete observation
must retain a null exact failure count and a separate known lower bound. These
commands observe runtime state; they do not themselves activate this PR.

References: [GitHub merge-queue behavior](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue),
[removal-event fields](https://docs.github.com/en/graphql/reference/pulls#removedfrommergequeueevent).
