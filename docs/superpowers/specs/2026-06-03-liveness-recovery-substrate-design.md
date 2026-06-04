# Liveness + Recovery Substrate — design

- **Date:** 2026-06-03
- **Authority:** CASE-SDLC-REFORM-001
- **Task:** `reform-liveness-recovery-substrate-20260601`
- **Status:** design + reference substrate + first surfaces migrated (proof)

## The class behind the whole reform wave

Every stuck-state incident this wave fixed is one instance of a single class:

> A long-running operation enters an intermediate state, has **no liveness
> signal**, **no staleness watchdog**, and **no automatic recovery** → it sits
> wedged until a human intervenes.

Instances patched surface-by-surface:

| Surface | PR | Heartbeat (today) | Recovery (today) |
|---|---|---|---|
| deploy-chain froze silently | #3840 | `last-deployed-sha` mtime | re-arm `--since` |
| merge/autoqueue armed-but-stranded | #3849 | PR `updated_at` | re-arm `--auto`, ntfy |
| dead-lane-after-PR teardown | #3831 | turn-complete + PR-merged | release claim, reap flock |
| stale launcher lock | ops | `*.launcher.pid` + lifetime | SIGTERM exact pid |
| cross-role stale CLAIM | offered | claim-file vs note `status` | archive claim, re-offer |
| in_progress output-stall | #3852 | `output.jsonl` mtime + lines | FIFO-nudge / relaunch / reoffer |

Each was bolted on independently with its own loop, its own state files, and its
own bound. There is **no shared contract**, so the *next* stuck-state surface
needs yet another bespoke watchdog. This substrate unifies them.

## What already exists (reuse, do not reinvent)

The recovery *machinery* is already built and shared — only the *connective
tissue* is missing. The substrate is deliberately thin because it composes:

- **`shared.recovery_governor.RecoveryGovernor`** (#3860) — the single bounding
  engine: per-target AIMD backoff × global token bucket × in-flight concurrency
  cap × PSI throttle, with a critical reserve and automatic escalation (mints a
  `recovery-escalation-<id>` cc-task + ntfy at `max_attempts`). `permit(target)`
  / `record_outcome(target, ok)`. **Bounding, pressure-gating, and escalation
  are entirely owned here** — the substrate never re-implements a bound.
- **`shared.sdlc_pressure_gate.admission_state()`** — `open|paced|closed` from
  PSI/load. The governor already consults it, so routing recovery through the
  governor *is* the pressure-gate.
- **`shared.dispatch_service_time`** — the measured staleness oracle:
  `tau_for_lineage(report, lineage)` gives a lineage's progress-timeout from its
  own measured p99 inter-tool gap (clamped `[1800s, 7200s]`). A threshold becomes
  *measured*, not hard-coded.
- **`shared.coord_event_log`** — the immutable ledger (`CoordEvent` +
  `CoordWriter.lane(...)`, spool-fail-open for lane writers).
- **`shared.notify.send_notification`** — the deduped escalation channel.

The **gap** the substrate fills: (1) a canonical heartbeat convention, (2) an op
registry, (3) the one scan that ties heartbeat → staleness → governor → ledger.

## The contract

Three parts. An operation gets liveness by **registering** (declaring) and
**beating** — never by writing a loop.

### 1. Heartbeat

`~/.cache/hapax/liveness/beats/<op_id>.beat` — atomic JSON `{op_id, ts, token, meta}`:

- `ts` — epoch seconds of last observed progress.
- `token` — a **monotonic progress token** (line count, byte offset, sequence,
  deploy-sha, …). The token is what separates *stalled* from *legitimately
  long-quiet*: a turn silent for an hour but whose token advanced since the last
  scan is **progressing**, not stalled (the Gittins move — rank by elapsed
  *silence against the hazard*, never raw wall-clock).

`emit_heartbeat(op_id, token, meta=...)` or CLI `python -m shared.liveness --beat
<op_id> --token <t>` (so a bash surface beats with one line).

### 2. Registry — `LivenessSpec`

Declarative, persisted to `~/.cache/hapax/liveness/registry/<op_id>.json`:

```
LivenessSpec(
    op_id:        str            # "lane:epsilon:progress", "deploy:post-merge"
    recovery_cmd: list[str]      # argv run on confirmed stall (the recovery)
    max_quiet_s:  float | None   # explicit threshold; None ⇒ measured tau
    lineage:      str | None     # tau lookup + governor target grouping
    critical:     bool = False   # routes to the governor critical reserve
    recover_when_missing: bool = False
    description:  str = ""
)
```

The spec declares **what is alive** and **how to recover it**. It deliberately
carries **no bound** — `max_attempts`/backoff/concurrency/pressure are the
governor's, the one source of truth. `recovery_cmd` is an argv (not an in-process
callable) because the surfaces are independent processes/timers; this matches the
fleet's existing command/timer model and keeps the watchdog decoupled.

### 3. Watchdog — `LivenessWatchdog.scan()`

One timer replaces N bespoke loops. Per registered spec:

1. Read the beat; `quiet_s = now - ts`; `threshold = max_quiet_s or
   tau_for_lineage(lineage)`.
2. `classify()` (pure) → one of:
   - `alive` — token advanced since last scan ⇒ progressing, never recover.
   - `quiet` — token unchanged but `quiet_s ≤ threshold` ⇒ within budget.
   - `stalled` — token unchanged **and** `quiet_s > threshold` ⇒ recover.
   - `missing` — no beat (never-started / torn down); recovered only if
     `recover_when_missing` (default off — absent ops do not storm).
3. For `stalled`: `grant = governor.permit(target_id, critical=spec.critical)`.
   If `grant.permitted`: `exec_fn(recovery_cmd)` → `governor.record_outcome(
   target_id, ok)` → ledger a `recovery-action` event. Escalation (mint + ntfy)
   fires automatically inside the governor at `max_attempts`.
4. Persist this scan's tokens (`scan-state.json`) for next-scan advance detection.

Every leg is an existing component; the substrate owns only *when/whether*, the
governor owns *how-bounded*, and `dispatch_service_time` owns *how-stale*.

```
beat ─▶ classify ─(stalled)─▶ governor.permit ─(ok)─▶ exec recovery_cmd
   │                              │                         │
 token                     pressure+AIMD+bound        record_outcome ─▶ ledger
   └──────── alive/quiet: no-op ──┘                   (escalate@max → mint+ntfy)
```

## Migration / cutover plan (all 6 surfaces)

Each cutover is a behavior-preserving swap, verified by a regression test that
asserts the substrate's verdict equals the legacy watchdog's decision on
representative inputs, then the bespoke loop is deleted.

| op_id | heartbeat source | threshold | recovery_cmd | stage |
|---|---|---|---|---|
| `lane:<role>:progress` | `output.jsonl` mtime + line count | `STALL_T` (or tau) | resume/nudge | **proof** |
| `reaper:<role>` | progress-age | measured tau | `recovery_governor --kill` | **proof** |
| `deploy:post-merge` | `last-deployed-sha` | deploy-lag budget | re-arm `--since` | **proof** |
| `merge-queue:autoqueue` | PR `updated_at` | eject window | re-arm `--auto` | next |
| `claim:<role>` | claim-file vs note status | coherence window | archive + re-offer | next |
| `deadlane:<role>` | turn-complete + PR-merged | teardown window | release + reap | next |

**This PR delivers** the substrate (`shared/liveness.py`), the registrations +
heartbeat adapters for the three `proof` surfaces (`shared/liveness_surfaces.py`),
regression tests proving identical classification, and the unified scan entrypoint
`python -m shared.liveness --scan` (plus `--beat` for the bash surfaces to emit
heartbeats with one line). Wiring that scan to a systemd timer and cutting the
live bash surfaces over to emit beats is the operational rollout — tracked as a
follow-up because `systemd/` is outside this task's `shared/docs/scripts/tests`
mutation scope. The remaining three surfaces follow the same recipe; each bespoke
bash loop is retired only once its surface's regression test is green (no silent
dual-run).

## Invariants

- **NEVER-FREEZE:** the substrate can only *slow* recovery (governor throttle),
  never *halt* it; a `closed` gate suspends non-critical recovery but the
  critical reserve + auto-escalation keep safety recovery alive.
- **No new bound:** every limit is the governor's. A surface cannot set its own
  `max_attempts` and drift from the fleet bound.
- **Ledger-or-it-didn't-happen:** every recovery action appends a `CoordEvent`.
- **Progress-token, not wall-clock:** a progressing op is never recovered.
