# SDLC Intake Claim Flow

Use this runbook when notification-fed P0 intake, request decomposition, or
ready-to-offered promotion appears to be draining slowly or silently stranding
work.

## Recheck

```bash
scripts/sdlc-intake-claim-audit \
  --require-no-silent-stranding \
  --output ~/.cache/hapax/intake-claim-audit.json
jq '.counts' ~/.cache/hapax/intake-claim-audit.json
```

The audit follows active cc-tasks through visible intake states and governed lane
pickup evidence. A task is considered picked up only when it has fresh
coordinator lane evidence, a live tmux/session owner for the assigned lane, or
an exact live `hapax-claude-headless` launcher. Claim files alone are routing
hints, not proof of lane ownership.

## Count Meanings

`undrained_p0_incident_intake` counts notification-fed P0 incident tasks in
`offered`, `claimed`, or `in_progress` that have not reached a live governed lane
owner. Non-zero means the notification path is producing tasks, but the downstream
offer/claim/lane-pickup flow is not landing them.

`silent_stranded_p0_or_remediation` counts active P0 or remediation tasks in
`claimed` or `in_progress` without live pickup evidence. Non-zero means the work
is no longer just visible queue backlog; it is assigned or claimed without a
current lane owner.

`offered_not_picked_up` items in `undrained_*` buckets are visible queue backlog,
not silent orphaning. They are pressure and capacity signals. The hard fail-fast
predicate for this runbook is `--require-no-silent-stranding`, which fails only
when active P0/remediation work has left visible queue backlog and is
claimed/in-progress without live owner evidence.

`stale_claim` counts old claim files that point to no active task, or to an active
blocked/unassigned task. Treat these as cleanup or routing repair inputs unless a
fresh lane launcher also proves ownership.

## Incident Memory

Notification-fed P0 incidents are fingerprinted. Repeated alerts update the
active incident task and append `~/.cache/hapax/p0-incident-intake/events.jsonl`.
If the matching task is already in `closed/`, intake must mint a new active
recurrence task instead of silently editing the closed note. The recurrence task
links `recurrence_of_task_id` / `recurrence_of_task_path` and carries the prior
Resolution/Post-mortem excerpt into `## Prior Incident Context`.

P0 incident tasks include `## Acceptance criteria` and `## Post-mortem`; closure
should document root cause, remediation/refusal, verification evidence,
recurrence prevention, and follow-up tasks. A flow that drains notifications but
forgets its own prior failures is not healthy flow.

## Runtime Gates

These user units are part of the governed intake drain and must be installed.
Timers and long-running services must be active; oneshot services may be
inactive between timer firings:

```bash
systemctl --user status \
  hapax-request-decompose.timer \
  hapax-request-decompose.service \
  hapax-cc-task-offer-ready.timer \
  hapax-cc-task-offer-ready.service \
  hapax-coordinator.service \
  hapax-lane-supervisor.timer
systemctl --user cat notify-failure@.service
```

If a timer is missing after a merge that changed `systemd/user-preset.d/hapax.preset`,
run the post-merge deploy for the landed SHA and recheck:

```bash
scripts/hapax-post-merge-deploy <merge-sha>
scripts/audit-runtime-activation-drift.py --json | jq '.findings[]?'
```

If `coordinator_state_status.fresh` is false in the intake audit, coordinator-only
lane claims are stale evidence. Restart or repair `hapax-coordinator.service`,
then rerun the audit before deciding that assigned P0/remediation work is live.
