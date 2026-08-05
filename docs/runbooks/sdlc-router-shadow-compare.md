# Runbook: SdlcRouter shadow-compare (N2, log-only)

## What this is

`hapax-sdlc-router-shadow-compare` runs `SdlcRouter.route` against a candidate
set and records whether the **live path** (frontier/WSJF incumbent under the
default inactive-class SHADOW gate, or the ROUTE winner when a class is active)
matches what the router would **prefer**.

Output is append-only JSONL. It does **not**:

- Change coordinator / methodology-dispatch selection
- Flip class activation
- Set `HAPAX_ROUTE_ENVELOPE_GATE=enforce`
- Enable `HAPAX_OUTCOME_GATE_ON_CLOSE`
- Touch G20 / K0 / podium

## Run (appendix)

```bash
# Demo: two synthetic candidates (strong local vs weaker frontier)
uv run python scripts/hapax-sdlc-router-shadow-compare --task-id demo --json

# Use live Thompson state (e.g. after N1b --apply) without writing the log
uv run python scripts/hapax-sdlc-router-shadow-compare \
  --task-id observe-1 \
  --router-state ~/.cache/hapax/sdlc-routing/router-state.json \
  --no-write --json

# Default log path
# ~/.cache/hapax/sdlc-routing/shadow-compare.jsonl
# override: HAPAX_SDLC_SHADOW_COMPARE_LOG or --log
```

## Fields (v1)

| Field | Meaning |
|-------|---------|
| `action` | `shadow` \| `route` \| `hold` from SdlcRouter |
| `live_selected_route_id` | What live path would keep (frontier under shadow) |
| `router_would_prefer` | Shadow alternative or ROUTE winner |
| `agree` | live == prefer |
| `dispatch_mutated` | Always `false` for this tool |

## Non-goals / next

- Full shadow-wire into coordinator (over-dep'd offered task) — later slice
- Per-class cutover — only after measured agree/disagree rates + activation evidence
- N1c source re-activation (blocked on activation HOLD) — separate integrity case
