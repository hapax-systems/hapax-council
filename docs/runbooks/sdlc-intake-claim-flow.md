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
coordinator lane evidence or an exact live `hapax-claude-headless` launcher for
the assigned lane. Claim files alone are routing hints, not proof of lane
ownership.

## Count Meanings

`undrained_p0_incident_intake` counts notification-fed P0 incident tasks in
`offered`, `claimed`, or `in_progress` that have not reached a live governed lane
owner. Non-zero means the notification path is producing tasks, but the downstream
offer/claim/lane-pickup flow is not landing them.

`silent_stranded_p0_or_remediation` counts active P0 or remediation tasks in
`claimed` or `in_progress` without live pickup evidence. Non-zero means the work
is no longer just visible queue backlog; it is assigned or claimed without a
current lane owner.

`stale_claim` counts old claim files that point to no active task, or to an active
blocked/unassigned task. Treat these as cleanup or routing repair inputs unless a
fresh lane launcher also proves ownership.

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
