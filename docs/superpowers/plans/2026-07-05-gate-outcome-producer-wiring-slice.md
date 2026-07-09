# Gate Outcome-Producer Wiring Slice (the measurement loop's outcome half)

**Branch:** follow-on to `spine/sdlc-router-intake-shadow-20260704` (PR #4423). Spawns its own
branch once #4423 merges (the `no-stale-branches` hook forbids a new branch while #4423 is open).
**Predecessor:** the intake fit-scorer shadow slice (iters 1–3) — the loop's ADMISSION half
(`docs/superpowers/plans/2026-07-04-intake-fit-scorer-shadow-slice.md`).
**Convergence contract:** one ledger plane only — `~/.cache/hapax/sdlc-routing/gate-events.jsonl`.
`dispatch-events.jsonl` is NOT touched (contested three-way fork owned by
`cc-task-ccef-reins-substrate-unification`). Reins consumes the spine via HTTP `/read/*` only
(consume-never-fork, L2-10). `provenance="witnessed"` is the only value that moves a posterior.
HOLD `HAPAX_INTAKE_FIT_BLEND > 0` until this slice's shadow-run validates the scorer.

## Goal

Light up the loop's OUTCOME half: wire the first WITNESSED caller of
`shared/gate_outcome_producer.emit_outcome_gate_event` so a real accept|reject verdict at a
dispatched task's resolution seam appends a LEARNING `GateEvent` that, once
`SdlcRouter.ingest_gate_events` drains the log, moves the Thompson posterior for
`(routing_class, route)`. Today the admission half is live (`agents/coordinator/core.py:633-660`,
`scripts/hapax-methodology-dispatch:_emit_gate_event`) but every emitted event is
`gate_type="none"` / `provenance!="witnessed"` / `thompson_update_allowed=False`, so
`record_gate_event` drops all of them and no posterior has ever moved. The registry's 168
capability scores remain 100% self-referential and asserted; `historical_performance.class_posteriors`
is empty for all 12 routes. This slice converts the first of those scores from asserted to measured.

The mechanism is already PROVEN end-to-end in tests
(`tests/shared/test_gate_outcome_producer.py::test_emit_then_ingest_closes_the_loop` writes to the
log, ingests, asserts the Beta moves; `::test_non_witnessed_event_does_not_move_the_posterior`
asserts fixtures poison nothing). Only the LIVE caller is missing.

## The Gap (verified)

| Loop side | Site | Status |
|---|---|---|
| WRITE admission | `agents/coordinator/core.py:644-658` `_emit_admission_gate_event` | LIVE — stamps `provenance="admission"`, `gate_type="none"` |
| WRITE admission | `scripts/hapax-methodology-dispatch:1655-1678` `_emit_gate_event` | LIVE — leaves `provenance` at the `GateEvent` default `"unknown"` |
| WRITE outcome | `shared/gate_outcome_producer.py:130` `emit_outcome_gate_event` | **ZERO non-test callers** (whitelisted at `scripts/vulture_whitelist.py:4239-4249`) |
| READ/UPDATE | `shared/sdlc_router.py:465` `ingest_gate_events` | **ZERO non-test callers** (whitelisted at `vulture_whitelist.py:4322`); every `SdlcRouter` reference in coordinator/dispatch/intake_fit_scorer is a comment |
| Beta move | `shared/sdlc_router.py:457-461` `record_gate_event` → `posterior.record_success/record_failure` | reachable, never reached live |

`record_gate_event` (`shared/sdlc_router.py:435`) drops an event unless ALL hold:
`gate_type in LEARNING_GATE_TYPES` (`:56` = `deterministic|gold_verifier|llm_acceptor|frontier_review`),
`gate_result in LEARNING_GATE_RESULTS` (`:59` = `accept|reject`),
`provenance == "witnessed"` (`:450` — the explicit guard), and
`gate_event_thompson_update_allowed(event)` (`:451`). The last requires a complete 8-dim
`requirement_vector` matching `REQUIREMENT_VECTOR_DIMENSIONS` plus non-empty `task_hash`, `route`,
`routing_class` (`:517-544`). An `llm_acceptor` verdict additionally requires
`judge_promotion.allowed` (`:438-446`, cost-capture phase 0 — the unvalidated local judge moves
nothing in either direction). The admission events fail on the first three grounds simultaneously;
the fix is a NEW event that satisfies all of them, not a relaxation.

## Design (locked)

### The route-recovery crux

`build_gate_event` takes `route` as a **required** parameter (`gate_event_producer.py:286`); the
admission callers supply it because they MADE the dispatch decision
(`core.py` passes the dispatched route; `hapax-methodology-dispatch:1669` reads
`route_decision.selected_descriptor_leaf or route_decision.route_id`). An outcome caller at a later
verdict seam (CI / review / merge) did not make the dispatch decision, so it must RECOVER the route.
The clean, consume-never-fork way: **join the admission event on `task_hash`**. Both producers
compute `task_hash` identically (`demand_vector.work_item.frontmatter_hash` if a demand vector is
present, else `stable_payload_hash(dict(task_fields))` — `gate_event_producer.py:289-291` and
`gate_outcome_producer.py:109-113`), so the same `task_fields` at the verdict site recomputes the
same hash and joins cleanly. The admission event already carries the route, routing_class, and
requirement_vector the outcome event must mirror.

**Verified against the live log** (`~/.cache/hapax/sdlc-routing/gate-events.jsonl`, point-in-time
recheck during 2026-07-09 PR recovery): the log had 812 rows, all `gate_type="none"` /
`provenance!="witnessed"` (808 `"unknown"` from the hapax-methodology-dispatch path + 4 null), and
zero witnessed outcomes. The number will drift because the SDLC loop is always running; the durable
claim is that the plane is producing admission observations but no learning-eligible outcome events
yet. That recheck also found 790 full join contexts and 22 legacy/incomplete admission rows with an
empty requirement vector (2 of those also lack `task_hash`), so the helper must tolerate incomplete
rows and recover only full join contexts instead of assuming every live row is usable.

Recheck the live-log census with:

```
python - <<'PY'
import json
from collections import Counter
from pathlib import Path

rows = [
    json.loads(line)
    for line in Path("~/.cache/hapax/sdlc-routing/gate-events.jsonl").expanduser().read_text().splitlines()
    if line.strip()
]
print("events", len(rows))
print("gate_type", Counter(row.get("gate_type") for row in rows))
print("provenance", Counter(row.get("provenance") for row in rows))
print("witnessed", sum(row.get("provenance") == "witnessed" for row in rows))
incomplete = Counter(
    tuple(
        field
        for field in ("route", "routing_class", "requirement_vector", "task_hash")
        if not row.get(field)
    )
    for row in rows
)
print("full_join_contexts", incomplete.pop((), 0))
print("incomplete_join_contexts", incomplete)
PY
```

Recheck the producer caller surface with:

```
rg -n "emit_witnessed_outcome|build_outcome_gate_event|emit_outcome_gate_event" \
  --glob '*.py' --glob '!tests/**'
```

**The admission↔outcome discriminator (pinned from the live data):** once the outcome producer is
live, BOTH event kinds share the same `task_hash`, so `recover_admission_context` cannot match on
hash alone. The discriminator is `provenance`: admission events are `provenance in {None,
"unknown", "admission"}` (the dispatch-time stamp); the outcome event this slice writes is
`provenance="witnessed"`. So the recovery scan is: **the latest event with `task_hash == X` AND
`provenance != "witnessed"`**, returning its `route`/`routing_class`/`requirement_vector`. (Equivalent
discriminator: `gate_type not in LEARNING_GATE_TYPES`, since admission events are `"none"`. Use
`provenance != "witnessed"` as the primary — it names the semantic distinction directly.)

### STEP-0 plumbing — `shared/gate_event_join.py` (new, pure)

```
@dataclass(frozen=True)
class AdmissionContext:
    route: str
    routing_class: str
    requirement_vector: dict[str, int]
    admitted_at: str            # the admission event's timestamp (recency/audit)

def recover_admission_context(
    task_hash: str, *, path: Path | str | None = None,
) -> AdmissionContext | None:
    """Scan gate-events.jsonl for the latest ADMISSION event with this task_hash.

    Admission = ``provenance != "witnessed"`` (the dispatch-time stamp; see the discriminator
    note above). Returns None if no admission event is found (the task predates the admission
    producer, or its dispatch went through a path that does not emit). Pure, synchronous,
    side-effect-free READ of the one ledger plane. Honest-DARK: never raises — a malformed line
    is skipped (mirroring read_gate_events' tolerance).
    """

def emit_witnessed_outcome(
    task_fields: Mapping[str, Any],
    *,
    gate_result: GateResult,           # "accept" | "reject"
    gate_type: GateType,               # caller-chosen per the verdict source
    p_correct: float | None = None,
    path: Path | str | None = None,
) -> GateEvent | None:
    """Resolve route via admission-context join, then delegate to emit_outcome_gate_event.

    Returns None (and writes nothing) when no admission context is found — a verdict with no
    dispatch admission is a lost join, not a learning signal. Provenance stays "witnessed"
    (the default); task_hash recomputes from the SAME task_fields the admission used.
    """
```

This is the keystone: it makes the outcome half callable from any verdict site that knows the
task's `task_fields`, with zero route plumbing at the verdict site. It is pure, additive
(no live caller = no behavior change), and fully tested in isolation. **This is the only code
the first sub-slice ships**; the caller + consumer-wiring are the sub-slices that follow.

### First caller — the PR-resolution seam (sub-slice 2)

The first LIVE caller is the verdict site with the strongest correctness signal AND both
polarities: the **review-team dossier resolution** on a dispatched task's PR (the same quorum
accept/request-changes/reject that arms `release_authorized`). Mapping:

| Dossier verdict | `gate_result` | `gate_type` |
|---|---|---|
| accept / accept-with-findings | `accept` | `frontier_review` |
| request-changes / reject | `reject` | `frontier_review` |

`frontier_review` (not `llm_acceptor`) is chosen deliberately: it sidesteps the
`judge_promotion` cost-capture gate (`sdlc_router.py:438-446`) that would otherwise drop the
verdict, while remaining a LEARNING gate type. `p_correct` is the dossier's quorum confidence
(reviewer agreement fraction); if absent, the producer's `_CERTAIN_GATE_TYPES` default does not
apply (frontier_review is not in it), so `p_correct` MUST be supplied or the producer defaults
confidence to 0.0 — and 0.0 < 0.8 fails the `LearningEligibility` validator. **Caller contract:
pass the dossier's confidence; fall back to 0.8 (the floor) if the dossier reports none.**

The caller is gated default-off behind `HAPAX_OUTCOME_GATE_OBSERVE` (mirrors `INTAKE_FIT_OBSERVE_ENV`)
and is fail-open (a measurement write must never break the review/merge path).

### Consumer wiring — `ingest_gate_events` drain (sub-slice 3)

`ingest_gate_events` (`sdlc_router.py:465`) is the log-draining entrypoint but has no live caller.
Sub-slice 3 wires a periodic drain: a thin systemd-user timer / coordinator tick calls
`SdlcRouter.load()` → `ingest_gate_events()` → `SdlcRouter.save()` (the router state persists to
`~/.cache/hapax/sdlc-routing/router-state.json` via `SdlcRouter.save` at `sdlc_router.py:338-345`).
Idempotency is already handled: `record_gate_event` dedupes by `gate_event_hash`
(`sdlc_router.py:464` / `applied_gate_event_hashes`), so a re-drain is a no-op.

## Verification (the loop closes)

1. **Unit (sub-slice 1):** `recover_admission_context` returns the route/routing_class/requirement_vector
   of the latest matching admission event; None on no match; never raises on a malformed line.
   `emit_witnessed_outcome` writes nothing when no admission context exists; writes a witnessed
   event that joins (identical task_hash) when it does.
2. **Integration (sub-slice 1, the closed loop):** write an admission event, then call
   `emit_witnessed_outcome`, then `ingest_gate_events`, then assert
   `posterior_for_update(routing_class, route).ts_alpha/ts_beta` mutated — reusing the existing
   `test_emit_then_ingest_closes_the_loop` pattern but with the admission-context join in between.
3. **Live shadow-run (sub-slice 3, the HOLD-release gate for blend>0):** with
   `HAPAX_OUTCOME_GATE_OBSERVE=1`, one dispatched task whose PR receives a dossier verdict produces
   one witnessed `frontier_review` event in `gate-events.jsonl`; the next drain moves one Beta; the
   registry's `class_posteriors` for that `(routing_class, route)` goes from empty to one recorded
   trial. **No posterior moves = the loop is not closed; do not release blend>0.**

## Tests

- `tests/shared/test_gate_event_join.py` (new): admission-context recovery (match / no-match /
  latest-wins on duplicate task_hash / malformed-line tolerance / never-raises);
  `emit_witnessed_outcome` join-on-match + write-nothing-on-miss; provenance stays "witnessed";
  task_hash identical to the admission event's.
- Extend `tests/shared/test_gate_outcome_producer.py`: the join helper + a drain closes the loop
  through the real log path (not just an in-memory event handoff).
- Caller test (sub-slice 2): patch the dossier-verdict site, assert `emit_witnessed_outcome` fires
  exactly once per verdict with the mapped gate_result/gate_type, flag-off writes nothing, fail-open
  on an unwritable path.

## Out of scope (follow-on slices)

- Wiring additional verdict sources (CI deterministic green/red, gold-verifier receipts). The
  frontier_review dossier caller is the FIRST; CI/gold are later sub-slices once the join + drain
  are live.
- `dispatch-events.jsonl` — contested fork owned by `cc-task-ccef-reins-substrate-unification`.
- EDT STEP-0 schema plumbing (`cc-task-edt-schema-plumbing-20260626`, status `offered`, blocked on
  workflow `wf_ff057885-a5e`). EDT and the measurement loop are sibling workstreams; EDT's
  `_BUILD_DEFENSE_CAVEATS` (`shared/edt_measure.py:158-164`) flags what is inert until STEP-0, but
  the outcome-producer loop does not BLOCK on EDT — it moves the Thompson term
  (`thompson_sample`), not the EDT-fed `historical_fit` term.
- Releasing `HAPAX_INTAKE_FIT_BLEND > 0`. Held until the live shadow-run (verification 3) moves a
  posterior.
