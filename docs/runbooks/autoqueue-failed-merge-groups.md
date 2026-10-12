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

Queue-bot `failed_checks` removal events join runs by synthetic SHA. The existing
JSONL lineage records retain the removal time, source binding when known, run
ID, and conclusion. Failed runs count in the existing storm report regardless
of the PR's current readiness or presence in the examination window. The
existing failure-rate throttle and bisection recommendation consume these
records; this change introduces no threshold waiver or new store.

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

References: [GitHub merge-queue behavior](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue),
[removal-event fields](https://docs.github.com/en/graphql/reference/pulls#removedfrommergequeueevent).
