# Runbook: surface_delta → onboarding discover (N3)

## What this is

`hapax-capability-onboarding-discover` maps **capability-surface delta** rows into
**onboarding disposition ledgers** via pure `classify_onboarding_surface` +
`classify_and_ledger`.

Default mode is **dry-run** (no ledger write). Pass `--apply` to append.

## Hard floors

| Floor | Value on this path |
|-------|--------------------|
| `demand_eligible_candidate` | always `false` |
| `equal_definition_complete` | always `false` |
| `admit_supply` | **never** (fail-closed if classify returns it) |
| Live route selection / envelope | untouched |
| G20 / K0 / source activation | out of scope |

## Run

```bash
# Dry-run against repo fixtures
uv run python scripts/hapax-capability-onboarding-discover --json

# Apply into a private ledger root (safe)
uv run python scripts/hapax-capability-onboarding-discover \
  --apply --ledger-root /tmp/onboarding-ledger --json

# Default live ledger root (only after intentional apply):
# ~/.cache/hapax/capability-onboarding/
```

## Relation to other tools

| Tool | Role |
|------|------|
| `hapax-capability-surface-delta-intake` | Mint **cc-tasks** from deltas |
| `hapax-capability-onboarding-intake` | Manual classify one surface |
| **This CLI** | Batch discover: deltas → disposition **ledgers** (EXPLORE first-class) |

## Non-goals

- Auto-admit supply or flip Thompson posteriors
- Replacing delta-intake task minting
- N1c source-activation (still HOLD-blocked)
