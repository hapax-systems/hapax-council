# Emergency Bypass Procedure

## When to use

Emergency bypass is for imminent service-down, data-loss, or safety
situations where the normal AuthorityCase pipeline would cause harm
by delaying the fix. It is NOT for convenience, deadline pressure,
or skipping review.

## How to activate

Set the environment variable before the mutation:

```bash
export HAPAX_METHODOLOGY_EMERGENCY=1
```

This bypasses:
- `cc-task-gate.sh` — allows file mutations without a claimed task
- `authorization-packet-validator.sh` — allows git push/PR without an ISAP

All bypassed actions are logged to:
`~/.cache/hapax/methodology-emergency-ledger.jsonl`

Each log entry records: timestamp, session, tool call, paths affected,
and the bypass reason (if provided via `HAPAX_EMERGENCY_REASON`).

## Post-emergency requirements

1. **Within 1 hour**: create a retrospective AuthorityCase at stage S0
   documenting what was done and why.
2. **Within 24 hours**: the retrospective case must reach S7 (verification)
   with evidence that the emergency fix is correct and the bypass was
   justified.
3. **Review**: the next RTE/coordinator tick must check the emergency ledger
   for unresolved entries and escalate any that lack a retrospective case.

## Audit trail

The emergency ledger at `~/.cache/hapax/methodology-emergency-ledger.jsonl`
is append-only. Each entry:

```json
{
  "timestamp_utc": 1715187600.0,
  "session": "zeta",
  "tool": "Write",
  "path": "shared/some_file.py",
  "reason": "Service crash in production, hotfix required"
}
```

## Abuse detection

The RTE sweep and SessionStart preamble check for:
- Emergency entries without a linked retrospective case
- More than 3 emergency bypasses in 24 hours (triggers escalation)
- Emergency bypass used for non-emergency work (flagged by coordinator)

## Rollback

To disable emergency mode:

```bash
unset HAPAX_METHODOLOGY_EMERGENCY
```

Normal gates resume immediately.
