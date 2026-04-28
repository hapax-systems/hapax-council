---
type: research-drop
date: 2026-04-26
title: Session-Discipline Handoff-Then-Compact — Reliability Analysis & Refusal
agent_id: session-discipline-shaper
status: REFUSED — 100% reliability bar cannot be met with current Claude Code primitives
---

# Session-Discipline Handoff-Then-Compact — Reliability Analysis & Refusal

## §0 — Verdict

**REFUSED.** The requested mechanism — *(a) at the next "wait" boundary
write a self-handoff brief, (b) trigger self-compaction, (c) ensure the
post-compaction self reads that handoff first* — cannot be assembled to
**100% reliability** from the hooks Claude Code currently exposes.

The load-bearing failure is **step (b)**. No hook can invoke `/compact`,
no hook can inject a TUI keystroke, and no hook payload field triggers
compaction as a side effect. Hooks are strictly one-way (process input
JSON → emit output JSON); they cannot drive the harness's command
parser. This is confirmed by the public hooks reference and by an open
feature request (anthropics/claude-code#43733) that has had no
implementation since it was filed.

Per the operator's hard rule — *"must be 100% reliable or not done at
all"* — shipping a partial implementation that depends on the operator
typing `/compact` after seeing a notification is exactly the
flaky-version case the brief forbids. This document records the
investigation, names the gap precisely, and stops there.

## §1 — What was tried

### §1.1 Step (a) — write handoff at wait boundary

**Reliable.** The `Stop` hook fires after every assistant turn. With
`decision: "block"` plus a `reason`, the hook can prevent the assistant
from idling and inject the reason text as feedback that the model reads
on the next loop iteration. The reason can carry an instruction like
"context is at 84% — write a self-handoff brief to
`~/.cache/hapax/relay/<role>-self-handoff-<timestamp>.md` covering current
work item, open PRs, decision state, and what to do next, then return".
The model then writes the brief in-conversation.

Token-count introspection at the wait boundary is also reliable. The
`transcript_path` field in every hook payload points at a JSONL file
under `~/.claude/projects/<slug>/<session-uuid>.jsonl`. Each
assistant-message line carries a `usage` block with
`input_tokens` + `cache_read_input_tokens` +
`cache_creation_input_tokens` + `output_tokens`. Summing the most
recent assistant turn's input-side fields gives a tight estimate of
loaded-context size. A `Stop` hook can compute this in shell with
`tail -n 50 "$transcript_path" | jq` in O(ms).

### §1.2 Step (b) — programmatic compaction

**Not reachable.** Three independent attempts fail:

1. **No hook invokes `/compact`.** The `PreCompact` hook (matchers
   `manual` / `auto`) fires *before* compaction starts and can only
   `decision: "block"` to cancel it; there is no symmetric "trigger"
   primitive. Hook output JSON has no `triggerCompaction` field, no
   `injectCommand` field, no `slashCommand` field.

2. **No hook injects keystrokes into the TUI.** Hooks run as
   subprocesses with stdin (input JSON) and stdout (output JSON) wired
   to the harness's JSON channel. There is no PTY back-channel. Writing
   to `/dev/tty` from a hook does not reach the Claude Code input
   buffer; it lands on the operator's terminal screen as bystander
   text.

3. **No hook drives the auto-compact threshold.** Auto-compact fires
   around 95% context use; that threshold is internal to the harness
   and is not configurable from settings.json (no
   `autoCompactThreshold` field exists in the schema). A hook that
   computes context usage cannot lower the harness's trigger to, say,
   80%.

GitHub issue **anthropics/claude-code#43733** ("PreCompact hook: allow
Claude to take actions before context compaction") is the canonical
record of this gap. Filed 2026-04-05, status OPEN, no Anthropic
response, no PR linked, no implementation. The same issue documents
that the *workaround* — `PreCompact` printing a stderr nudge plus
`SessionStart:compact` injecting a "read SESSION.md" reminder —
"results in significant context loss still occurring regularly". That
is the upstream's own characterization, not ours.

### §1.3 Step (c) — post-compaction self reads handoff

**Reliable.** The `SessionStart` hook with `matcher: "compact"` fires
after compaction completes and can return
`hookSpecificOutput.additionalContext` which is injected into the
post-compaction model's context before its next turn. A hook can:

- glob `~/.cache/hapax/relay/<role>-self-handoff-*.md` for the most
  recent file,
- read it,
- emit `additionalContext` containing the handoff text plus an
  imperative ("Read the self-handoff above before responding to the
  operator").

This works. We use the same pattern today for relay onboarding.

### §1.4 What's *almost* reliable but isn't

**Operator-prompted compaction.** A `Stop` hook can detect high context
use, force the model to write the handoff, then `systemMessage` the
operator with "context at 84% — please type `/compact` now". This is
the workaround everyone reaches for. It fails the bar because:

- The operator may be away from the keyboard (the canonical case for
  this workflow — sessions run autonomously between ScheduleWakeup
  ticks every 270s).
- If the operator does not type `/compact` within ~10% more context
  growth, auto-compact fires at 95% and races the handoff. Auto-compact
  uses Claude's default summarization; the bespoke handoff we wrote is
  in the now-compacted history but the post-compact self has no signal
  that one specific .md file matters more than the auto-summary.
- "Operator must press a key" is exactly the
  `feedback_no_operator_approval_waits` /
  `feedback_never_stall_revert_acceptable` anti-pattern: it inserts a
  human in the critical path of an autonomous loop. Even if the
  operator is present, latency variance blows the reliability claim.

**Ralph-style external orchestrator.** A long-running daemon outside
Claude Code could monitor the transcript file, detect high token use,
write a handoff via Logos API, then SIGTERM the Claude Code process and
relaunch with `--resume <session-id>`. This decouples from hook
primitives entirely. It is *probably* reliable but: (i) `--resume`
re-loads the full transcript (no compaction happens, no context is
freed), (ii) killing the process mid-turn corrupts the JSONL, (iii)
this is a parallel control plane that the operator did not ask for and
that breaks the session-continuity invariants the relay protocol
depends on. Out of scope under the brief's "do not modify the active
session's settings while it's running in a way that would break this
very session" constraint.

**Stop-hook spinlock until threshold drops.** `Stop` with
`decision: "block"` + reason "you are over budget; do nothing useful
until the operator compacts" prevents the session from reporting idle,
but does not free context. The model burns tokens on the
spinlock-feedback messages, which makes the situation worse, and it
violates `feedback_never_stall_revert_acceptable` (this *is* a stall).

## §2 — The irreducible gap

The chain has three steps. Step (b) — compaction-firing — is the only
state transition in the chain that is **owned by the harness, not by
the model and not by hooks**. Until Anthropic exposes one of:

1. A hook output field like `hookSpecificOutput.triggerCompaction: true`,
2. A CLI/IPC endpoint the host can call to request compaction on a
   running session,
3. A configurable `autoCompactThreshold` in settings.json that lets
   the operator pull the trigger forward to e.g. 80%,

…there is no path from "hook detects high context" to "compaction
fires" that doesn't route through a human keystroke. None of those
three primitives exist as of 2026-04-26.

## §3 — Why the available pieces add up to <100%, not 100%

Reliability of the chain is `P(a) × P(b) × P(c)`. With current primitives:

- `P(a)` ≈ 1.0 (Stop hook + transcript-path token math + model writes
  file)
- `P(b)` ≈ `P(operator types /compact within window)` — empirically
  variable, certainly not 1.0 for an autonomous-loop session
- `P(c)` ≈ 1.0 (SessionStart:compact + additionalContext)

The operator-keystroke dependency in `P(b)` is the entire failure
mode. Even at `P(b) = 0.95` per long session, across the four
concurrent relay sessions over a single research day this aggregates to
multiple lost handoffs per week. That is not the operator's bar.

## §4 — What was *not* tried, and why

- **Modifying Claude Code source / patching the binary.** Out of scope;
  the operator runs the upstream npm-shipped binary, and patching it
  would entangle this work with every Claude Code update.
- **MCP-side compaction.** No MCP server has authority over the host's
  compaction state; MCP is tool-execution, not session-control.
- **`continue: false` from a Stop hook to "soft-end" the session.**
  This stops the agent across all hook events but doesn't compact —
  the next operator turn either resumes the same context or starts a
  fresh session with no handoff bridge.
- **Writing handoff via PreCompact hook then letting auto-compact
  happen.** PreCompact fires with `compaction_trigger=auto` *and* the
  handoff hook can call out to a Python helper that reads the
  transcript and writes the brief. But auto-compact only fires at
  ~95%, which is exactly where the brief warned us not to race; and
  the PreCompact hook's wall-clock budget is small (the model is about
  to be paused for compaction; long-running shell-outs from the hook
  block the harness). This is also what the upstream issue calls out
  as insufficient.

## §5 — Recommendation

### §5.1 What to file upstream

Open a feature request (or +1 the existing #43733) requesting **one of
these three minimal additions**, in order of preference:

1. **`autoCompactThreshold` in settings.json** (operator-configurable
   percent, default 0.95 = current behavior). Pulls the harness's own
   trigger forward; preserves all existing semantics. Lowest blast
   radius. Combined with PreCompact-hook handoff write, this gives
   100% reliability with zero operator interaction.
2. **`hookSpecificOutput.triggerCompaction: true` from `Stop` and
   `UserPromptSubmit` hook returns.** Lets the hook explicitly request
   compaction at a wait boundary. Slightly more invasive (new
   side-effect channel from hook output).
3. **CLI `claude compact <session-id>` subcommand** that an external
   process can call. Heavier; needs a stable session-control IPC
   surface.

### §5.2 What NOT to ship in the meantime

Do not deploy a "best-effort" version. Specifically:

- Do **not** add a `Stop` hook that nudges the operator to compact —
  it inserts a human in the autonomous loop and silently drops handoffs
  when the operator is away.
- Do **not** add a daemon that kills+resumes the session — it does not
  free context, may corrupt transcripts, and creates a parallel control
  plane.
- Do **not** add a `PreCompact` hook that writes a handoff *only* on
  auto-compact at 95% — it races the auto-summary and provides no
  benefit over current behavior for sessions that compact early.

The right move is to wait for the upstream primitive and ship the full
chain in one stroke. The handoff-write code from §1.1 and the
SessionStart:compact reader from §1.3 are both small (<50 lines of
shell each) and can be built in <30 min once the trigger primitive
lands.

### §5.3 If the operator relaxes the bar later

If the operator decides at some future point that **best-effort with
operator-keystroke completion** is acceptable (i.e. relaxes from "100%
reliable" to "fires the handoff write at the right moment, ask the
operator to press one key, accept that some handoffs are lost"), the
build is:

| Component | Hook | Purpose |
|-----------|------|---------|
| `session-budget-monitor.sh` | `Stop` matcher `""` | Reads `transcript_path`, sums `input_tokens + cache_read + cache_creation` from the last assistant turn. If ≥ ceiling, returns `decision: "block"` with reason "context at NN% — write handoff to ~/.cache/hapax/relay/$role-self-handoff-$ts.md covering [list], then output one line `HANDOFF_WRITTEN: <path>` and stop". Also emits a `systemMessage` to the operator: "context at NN% — type /compact when you're ready". |
| `session-handoff-reader.sh` | `SessionStart` matcher `compact` | Globs `~/.cache/hapax/relay/$role-self-handoff-*.md` for the newest file with mtime within the last 10 minutes. Reads it. Emits `hookSpecificOutput.additionalContext` containing the handoff text prefixed with "READ THIS FIRST: it is your handoff brief from your pre-compaction self. It supersedes the auto-compact summary on points of conflict." |

**Optimal ceiling for the relaxed-bar version: 80%** of the model's
context window. Justification:
- Anthropic's prompt cache TTL is 5 minutes; the cache-warm window
  defines how aggressively we can compact without paying re-warm
  costs. At 80% we are well clear of auto-compact (95%) and have ~15%
  headroom to *actually write the handoff* (3-5K tokens) plus retain
  a buffer for the trigger mechanism's own overhead.
- 80% is also high enough that we don't compact prematurely — the
  session has done 80% of one window's worth of real work, which is a
  meaningful unit (a single research drop, a multi-PR sequence, a
  livestream cycle). Lower thresholds (60-70%) shorten the mean
  effective-work window and starve productive sessions.
- For a 200K-token Sonnet 4.5 session that's ~160K loaded; for the
  current 1M-token Opus 4.7 session that's ~800K loaded.

This document is the spec for that future build. It is **not**
authorization to ship it now.

## §6 — Self-test

This refusal-doc was itself produced by a subagent reading the relevant
hook documentation, settings, and protocol files. The investigation
covered:

- `~/.claude/settings.json` (existing hooks, no compact-related
  hook registered)
- `~/projects/.claude/settings.local.json` (no override)
- `~/.cache/hapax/relay/PROTOCOL.md` (handoff conventions:
  `~/.cache/hapax/relay/*.md`)
- `https://code.claude.com/docs/en/hooks` (full hook event reference)
- `anthropics/claude-code#43733` (open PreCompact-action feature request)
- existing hook scripts under `~/projects/hapax-council/hooks/scripts/`
- transcript JSONL format under `~/.claude/projects/`

No code was written. No settings.json was modified. No commit was
created. The deliverable is this analysis.

## §7 — File index for the future build

When the upstream primitive lands, these are the files to create:

- `~/projects/hapax-council/hooks/scripts/session-budget-monitor.sh`
  — Stop hook, computes context %, writes handoff via model, optionally
  emits compact-trigger output field.
- `~/projects/hapax-council/hooks/scripts/session-handoff-reader.sh`
  — SessionStart:compact hook, reads newest handoff, emits
  additionalContext.
- Settings registration in `~/.claude/settings.json` under
  `hooks.Stop[]` and `hooks.SessionStart[]` (matcher `compact`).
- A test under `tests/hooks/` invoking each script with a fixture
  transcript and asserting output JSON shape.

The handoff filename convention `~/.cache/hapax/relay/$role-self-handoff-$ts.md`
matches the existing post-compaction-handoff family
(`alpha-post-compaction-handoff-*.md` etc.) so the operator's existing
mental model and grep patterns continue to work.
