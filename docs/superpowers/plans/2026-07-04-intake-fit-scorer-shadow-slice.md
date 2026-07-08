# Intake Fit-Scorer Shadow Slice (iter 2)

**Branch:** `spine/sdlc-router-intake-shadow-20260704`
**Predecessor:** iter 1 `5d7af5a4c` (demand plumb — `requirement_vector`/`routing_class` → `Task`/`QueueTask`).
**Convergence contract:** reins is the single SDLC engagement surface; this slice emits
fit_score observability to the ledger plane reins already reads (`gate-events.jsonl` via
`shared.gate_log.append_gate_event`). No parallel file.

## Goal

Wire the (1)↔(2) loop's first half: a **shadow** intake fit-scorer that ranks offered tasks
by their demand-shape alongside WSJF, behind a default-off blend flag, with a byte-identical
flag-off golden guarantee. The scorer shadows the engine's `requirement_fit` concept (mean of
scored non-`quality_floor` dims) at the task level.

## Design (locked)

### `shared/intake_fit_scorer.py` (new, pure)

- `fit_score(requirement_vector: Mapping[str, int] | None) -> float`
  - Mean of dims where `key != "quality_floor"` and value is a strict int (reject bool) in `0..5`.
  - `None` / empty / partial / any-invalid → `0.0` (honest-DARK; never raises, never NaN).
  - Range `[0.0, 5.0]` — directly comparable to the engine's `requirement_fit`.
- `composite_rank_key(wsjf_eff: float, fit: float, *, blend: float) -> float`
  - `blend == 0.0` → return `wsjf_eff` **exactly** (short-circuit; the golden guarantee).
  - else → `wsjf_eff + blend * fit`.

### Rank-key sites (both patched — the no-spin invariant needs both)

- `shared/dispatch_service_time.py:443` (`plan_dispatches`)
- `agents/coordinator/core.py:531` (`_repair_cooled_plan`)
- Replace `wsjf_effective(t.wsjf, t.age_s, age_norm_s)` with
  `composite_rank_key(wsjf_effective(...), fit_score(t.requirement_vector), blend=fit_blend)`.

### Flag (mirrors `SCHEDULER_LEGACY_ENV`)

- `INTAKE_FIT_BLEND_ENV = "HAPAX_INTAKE_FIT_BLEND"` (default `0.0`).
- Read in `tick()`, passed as `fit_blend=` to `plan_dispatches` and `_repair_cooled_plan`.

### The 3 verify corrections

1. **blend=0 short-circuit** → bit-identical to `wsjf_effective` (no `+ 0.0 * x` float wobble).
2. **fit_score never raises/NaN** on `None`/partial/non-int/bool → `0.0`.
3. **Both sites use the composite** (plan + repair) — else the repair pass reorders relative to
   the plan and breaks the no-spin law.

(Bonus) `quality_floor` excluded (consistent with the engine's
`_scored_requirement_dimensions`).

### Convergence contract

- `GateEvent.fit_score: float | None = None` (additive; default None = spine has not scored).
- `INTAKE_FIT_OBSERVE_ENV = "HAPAX_INTAKE_FIT_OBSERVE"` (default off) gates a thin fail-open
  admission-gate emit in the dispatch loop: reuse `shared.gate_event_producer.build_gate_event`
  (the designated admission assembler — no parallel logic); stamp `fit_score` (None unless the
  vector is measured-complete, mirroring reins' `_measured_reqvec_or_absent`); `append_gate_event`.
  Fail-open (logged, never raises) — a lost measurement must not crash the tick.
- **One ledger plane only: `gate-events.jsonl`.** `dispatch-events.jsonl` is NOT touched by this
  slice — it is a contested three-way fork (a reader cites a phantom module; the operator profile
  overstates it as live) owned by `cc-task-ccef-reins-substrate-unification` (retire-vs-write is
  theirs to decide). This slice emits fit_score observability solely via `append_gate_event`.

## Tests (~13)

Scorer: valid-full / valid-partial / None / empty / bool-rejected / non-int-rejected /
all-zero-is-neutral / quality_floor-excluded.
Composite: blend=0 byte-identical / blend>0 reorders / both-sites-use-composite.
Convergence: GateEvent.fit_score round-trip / emit flag-off writes nothing / emit flag-on
writes reqvec+routing_class+fit_score / emit fail-open on unwritable path.

## Out of scope (follow-on PRs)

- Full admission-producer wiring at dispatch (demand_vector plumbing, async cost resolution).
- `dispatch-events.jsonl` — contested fork owned by `cc-task-ccef-reins-substrate-unification`;
  not this slice's to claim (one ledger plane = `gate-events.jsonl`).
- reins-side consumption of `fit_score` (separate repo).
