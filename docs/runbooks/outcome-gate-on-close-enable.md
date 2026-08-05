# Runbook: enable close → outcome-gate learning emits (N1)

## What this is

When a governed cc-task **closes** with a complete `requirement_vector` and an
accept/reject verdict path, `scripts/cc-task-closure-check.py` can append a
**witnessed** learning `GateEvent` via `emit_outcome_gate_event`.

That write is **off by default**.

| Control | Default | Effect |
|---------|---------|--------|
| `HAPAX_OUTCOME_GATE_ON_CLOSE` | unset / `0` | No emit on close (today’s behavior) |
| `HAPAX_OUTCOME_GATE_ON_CLOSE=1` | — | Emit witnessed accept on permitted close when requirement_vector is complete |
| Incomplete requirement_vector | — | No learning emit; `incomplete_technical` ledgered |
| Emit failure when flag on | — | **Close refused** (fail-closed) |

This does **not**:

- Change live route selection (WSJF / coordinator still select)
- Set `HAPAX_ROUTE_ENVELOPE_GATE=enforce`
- Activate agentic-trust as supply
- Touch G20 / podium

## Enable (appendix, reversible)

**One shell session (lowest risk):**

```bash
export HAPAX_OUTCOME_GATE_ON_CLOSE=1
# then run governed work that closes with complete route_metadata / requirement_vector
```

**User unit drop-in (persistent for a specific service only — prefer narrow scope):**

```ini
# ~/.config/systemd/user/<unit>.d/outcome-gate-on-close.conf
[Service]
Environment=HAPAX_OUTCOME_GATE_ON_CLOSE=1
```

```bash
systemctl --user daemon-reload
systemctl --user restart <unit>
```

**Killswitch:**

```bash
# Shell-only enable:
export HAPAX_OUTCOME_GATE_ON_CLOSE=0

# If a systemd drop-in was used — remove it AND restart the unit (daemon-reload alone is not enough):
rm -f ~/.config/systemd/user/<unit>.d/outcome-gate-on-close.conf
systemctl --user daemon-reload
systemctl --user restart <unit>
systemctl --user show <unit> -p Environment   # confirm flag absent

# Recheck from tooling:
uv run python scripts/hapax-sdlc-gate-event-drain --status --json
# expect outcome_gate_on_close_enabled_now: false
```

## Observe / drain (no selection)

After events exist (or to inspect an empty log):

```bash
# Report-only: how many witnessed learning events would move posteriors?
uv run python scripts/hapax-sdlc-gate-event-drain --status --json

# Explicit apply: move posteriors + save router-state.json (still no live selection)
uv run python scripts/hapax-sdlc-gate-event-drain --apply --json
```

Defaults:

| Path | Env override |
|------|----------------|
| `~/.cache/hapax/sdlc-routing/gate-events.jsonl` | `HAPAX_GATE_LOG` |
| `~/.cache/hapax/sdlc-routing/router-state.json` | `HAPAX_SDLC_ROUTER_STATE` |

## Proof checklist (forest A no longer zero under enable)

1. Flag on for one session.
2. Close a task with complete 8-dim `requirement_vector` (or valid route_metadata that derives one).
3. Confirm a new line in the gate log (`provenance=witnessed`, learning gate_type).
4. `hapax-sdlc-gate-event-drain --status --json` shows `total_events > 0` and/or `would_apply > 0`.
5. Optional: `--apply` once; confirm `state_written=true` and `dispatch_selection_changed=false`.

## Next throughline after traffic exists

**N2** — thin SdlcRouter shadow compare (log-only router vs WSJF), not full per-class cutover.
See `30-areas/hapax/throughline-reeval-next-climb-2026-08-05.md`.
