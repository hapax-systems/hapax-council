# First Run Guide

Your cockpit has infrastructure, agents, and a deep passive profile (1,103 facts from configs, shell history, git, transcripts). What it doesn't have yet is **your direct input** — the interview-sourced neurocognitive data that makes the system actually adaptive.

This guide gets you from build-and-test to daily use.

## Before you launch

### 1. Flush the in-progress interview

You have ~40 neurocognitive facts and 16 insights sitting in `~/.cache/cockpit/chat-session.json` from an earlier interview session exploring `task_initiation_patterns`. These haven't been merged into your profile yet.

```bash
uv run cockpit
# press 'c' for chat
```

If the old session loads with interview state:
```
/interview end
```

This flushes facts to `profiles/operator-profile.json`. If the session is gone or empty, the facts are already lost — not a disaster, you'll re-explore task_initiation through probes and the next interview.

### 2. Run the profiler

The profiler regenerates `operator.json` (the structured representation agents consume) from `operator-profile.json` (the raw fact store). Right now, `operator.json` has `"neurocognitive": {}` — empty.

```bash
uv run python -m agents.profiler --auto
```

This detects new facts, re-extracts if needed, and rebuilds `operator.json` including the neurocognitive section.

### 3. Verify

Back in the cockpit chat:
```
/profile
/profile neurocognitive_profile
```

You should see facts from the interview flush. If neurocognitive_profile shows 0 facts, the profiler didn't pick them up — run `uv run python -m agents.profiler` (full extraction, not `--auto`).

## What you'll see on first launch

**Copilot greeting:**
```
evening, operator — all clear. no interview conducted.
```

The copilot knows the system is in bootstrap mode and says so directly.

**Action items** (the "what to do now" panel):
```
[!!] No interview conducted yet          → /interview
[! ] Profile incomplete (X/11 dims)      → /interview
[..] No briefing available               → uv run python -m agents.briefing --save
```

These are real nudges from the unified attention system. They point you at the critical path: interview first, then briefing.

**Sidebar:** Readiness shows "bootstrapping" with your top gap.

**Goals:** If operator.json has goals (it does — 4 active, 2 stale), stale goals appear as nudges.

## The first week

### Day 1 (tonight)

1. Flush interview, run profiler (above)
2. Launch cockpit, scan the dashboard — get oriented
3. Open chat, run `/interview` — the interview agent will plan topics based on your profile gaps
4. Explore 2-3 topics. Don't force it. `/interview end` when done
5. Run `uv run python -m agents.profiler --auto` after ending

### Days 2-7

The system bootstraps itself through normal use:

- **Micro-probes** surface during idle time (5+ minutes quiet). Single experiential questions. Answer in chat or ignore — no pressure. One probe every 10 minutes max.
- **Conversational learning** picks up durable facts from normal chat. The `record_observation` tool fires when you reveal preferences or patterns organically. These land in `~/.cache/cockpit/pending-facts.jsonl` and flush to the profile on the next `profiler --auto` run (every 12h via timer, or manually).
- **Decision capture** records which action items you engage with. Over time this builds a behavioral signal for the profiler.
- **Daily briefing** generates at 07:00 automatically. Check it from the dashboard or `/briefing`.

### When accommodations appear

After the profiler processes neurocognitive facts, the accommodation engine can propose adaptations. Currently, proposals exist for 4 pattern categories:

| Pattern discovered | Accommodation proposed |
|---|---|
| time_perception | Show elapsed session time in copilot messages |
| demand_sensitivity | Use observational framing instead of imperatives |
| energy_cycles | Reduce non-urgent nudge priority during low-energy hours |
| task_initiation | Surface smallest possible next step for stalled items |

Proposals are **inert until you confirm them**. Check and manage via:
```
/accommodate              # list proposals and active accommodations
/accommodate confirm <id> # activate one
/accommodate disable <id> # deactivate one
```

## What won't self-correct

**The accommodation catalog is static.** `_PROPOSALS` in `cockpit/accommodations.py` is a hardcoded dict mapping pattern categories to specific system behaviors. If the interview reveals patterns in categories not in that dict (e.g., `task_persistence`, `decision_making`, `motivation`), no accommodations will be proposed for them.

This is a deliberate design choice — accommodations should be concrete system behavior changes, not vague suggestions. But it means the catalog needs manual expansion as your neurocognitive profile fills in. The data flows through; the behavioral adaptations don't generate themselves.

**What does self-correct:**
- Profile gaps drive probe selection (highest-priority gap = next probe topic)
- Readiness level advances automatically as dimensions fill in
- Nudge priorities adjust based on what's stale, what's missing, what's urgent
- The copilot shifts from "bootstrap" messaging to operational messaging as readiness improves
- Interview topic planning adapts to current profile gaps
- Decision capture feeds back into the profiler for behavioral pattern extraction

**What needs manual intervention:**
- Expanding `_PROPOSALS` with new accommodation types
- Wiring `propose_accommodation()` into the probe/interview pipeline (currently only callable via tests — never triggered automatically)
- Adding system behaviors for new accommodation IDs (the copilot only acts on `time_anchor`, `soft_framing`, `energy_aware`)

## Commands reference

| Command | Where | What |
|---|---|---|
| `/interview` | chat | Start guided profile interview |
| `/interview end` | chat | End interview, flush facts to profile |
| `/interview status` | chat | Show interview progress |
| `/profile` | chat | Profile summary (dimensions, fact counts) |
| `/profile <dim>` | chat | Facts for a specific dimension |
| `/profile correct <dim> <key> <value>` | chat | Correct a fact (confidence 1.0) |
| `/profile delete <dim> <key>` | chat | Remove a fact |
| `/accommodate` | chat | List accommodations |
| `/accommodate confirm <id>` | chat | Activate an accommodation |
| `/accommodate disable <id>` | chat | Deactivate an accommodation |
| `/pending` | chat | Show pending conversational facts |
| `/flush` | chat | Manually flush pending facts to profile |
| `/export` | chat | Export conversation to markdown |

## Key files

| File | What it holds |
|---|---|
| `profiles/operator-profile.json` | Raw profile (1000+ facts, 10+ dimensions) |
| `profiles/operator.json` | Structured operator context (agents consume this) |
| `profiles/accommodations.json` | Active/proposed accommodations (created on first confirm) |
| `profiles/briefing.md` | Latest daily briefing |
| `~/.cache/cockpit/chat-session.json` | Chat state including interview progress |
| `~/.cache/cockpit/probe-state.json` | Which micro-probes have been asked |
| `~/.cache/cockpit/pending-facts.jsonl` | Conversational facts awaiting profiler flush |
| `~/.cache/cockpit/decisions.jsonl` | Operator action log on nudges |
