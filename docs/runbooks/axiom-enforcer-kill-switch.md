# Axiom Enforcer Kill Switch

The runtime output enforcer blocks T0 axiom violations by default. The
emergency kill switch is `AXIOM_ENFORCE_BLOCK=0`; it changes enforcement to
audit-only and still records violations in `profiles/.enforcement-audit.jsonl`.

Use this only when a production path is blocked incorrectly and the safer fix
cannot be made immediately.

## Disable Blocking

For a single command:

```bash
AXIOM_ENFORCE_BLOCK=0 uv run python -m agents.briefing --save
```

For a systemd user unit, add a temporary override:

```bash
systemctl --user edit daily-briefing.service
```

Then set:

```ini
[Service]
Environment=AXIOM_ENFORCE_BLOCK=0
```

Reload and restart the affected unit:

```bash
systemctl --user daemon-reload
systemctl --user restart daily-briefing.service
```

## Verify Audit-Only Mode

Check that the run did not silently bypass governance:

```bash
tail -n 20 ~/projects/hapax-council/profiles/.enforcement-audit.jsonl
ls -la ~/projects/hapax-council/profiles/.quarantine
```

Audit-only mode should show `audit_only: true` for matching violations and
should not create a new quarantine file for allowed output.

## Re-Enable Blocking

Remove the override:

```bash
systemctl --user revert daily-briefing.service
systemctl --user daemon-reload
systemctl --user restart daily-briefing.service
```

For shell sessions, unset the variable or set it to `1`:

```bash
unset AXIOM_ENFORCE_BLOCK
# or
export AXIOM_ENFORCE_BLOCK=1
```

## Closeout

Record the reason for using the kill switch, the matching pattern IDs, and the
follow-up fix. Do not leave `AXIOM_ENFORCE_BLOCK=0` in committed units,
watchdogs, shell profiles, or secret env files.
