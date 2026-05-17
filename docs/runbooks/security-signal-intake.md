# Security Signal Intake

`scripts/security-signal-intake` converts GitHub security/remediation signals
into governed Hapax request notes. It writes only intake artifacts; remediation
still goes through request planning, WSJF, cc-task creation, implementation,
review, and merge.

Default sources:

- open Dependabot alerts
- open code scanning alerts
- open secret scanning alerts, with secret values omitted

Recurring GitHub Actions failures are supported but throttled and opt-in:

```bash
scripts/security-signal-intake --include-actions-failures
```

Dry run:

```bash
scripts/security-signal-intake
```

Write request notes:

```bash
scripts/security-signal-intake --write
```

The systemd timer runs the write mode every 30 minutes and records a state file
at `~/.cache/hapax/security-signal-intake-state.json`. Generated requests use a
stable `source_signal_id`, so active or closed requests suppress duplicates.

Secret-scanning payloads can contain raw secret values. The generator does not
read those fields into request evidence and includes an explicit omission line
instead. Do not paste secret values into follow-up requests, tasks, commits, or
logs.
