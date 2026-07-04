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

## Dispatch redemption governor recovery

External-project launches, including Reins worktrees, require the fixed
`hapax-dispatch-redemption.service` governor. `HAPAX_METHODOLOGY_EMERGENCY=1`
does not create or bypass a redemption token, because that would turn emergency
mode into an unwitnessed external-launch path.

The governor is a governed-path and witnessability boundary, not same-UID user
authentication. Its process-image checks reject ordinary requester mismatches
and native-loader injection, and its token-free ledger witnesses every
mint/redeem/refusal, but it does not claim cryptographic non-forgeability
against the single operator account.

If the governor is unavailable or wedged during an incident:

1. Set `HAPAX_METHODOLOGY_EMERGENCY=1` and `HAPAX_EMERGENCY_REASON` with the
   incident reason.
2. Do the recovery from a council worktree, which does not require external
   launch redemption:
   `scripts/hapax-dispatch-redemption-service-install --install`
3. Verify the fixed socket and protocol:
   `scripts/hapax-dispatch-redemption-authority --receipt`
   This receipt performs a live protocol probe; a present socket alone is not
   sufficient evidence that the governor is serving.
4. Verify the runtime namespace owner/mode independently:
   `stat -c '%U:%G %a %n' /run/hapax/coord /run/hapax/coord/dispatch-redemption.sock`
5. Retry the external launch through `scripts/hapax-methodology-dispatch`.

If an external project itself needs emergency edits before the governor can be
repaired, perform that manual work only under the same emergency ledger and open
the required retrospective AuthorityCase within the post-emergency windows
below. Do not mint or hand-edit redemption tokens.

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
