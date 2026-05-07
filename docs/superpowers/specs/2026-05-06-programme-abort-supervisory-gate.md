# Programme Abort Supervisory Gate

**Status:** current_authority
**Checked at:** 2026-05-06T19:05:39-05:00
**Scope:** `ProgrammeManager`, `AbortEvaluator`, production abort snapshots, and operator veto impingements.

## Decision

Programme abort predicates are supervisory gates, not proof that the stream is normal. A predicate returning `False` because its required observation is absent means "no grounded abort evidence for this predicate right now." It does not mean the operator is present, consent is valid, pressure is low, the vinyl side is still playing, or the operator agrees with the programme.

The release-safe posture is:

- Do not abort on missing or malformed sensor data.
- Do not call missing data a success signal.
- Record missing-data coverage as a diagnostic and calibration target.
- Bind every pending abort to the programme id that produced it.
- Clear pending abort state on operator/planned/time-cap transitions so stale abort decisions cannot apply to a later programme.
- Commit an abort only after the veto window expires and only while the same programme remains active.

## Predicate Missing-Data Contract

| Predicate | Required snapshot fields | Missing-data posture | Current risk |
|---|---|---|---|
| `operator_left_room_for_10min` | `ir_present`, `ir_absent_since_s` | Non-firing. Missing IR data means absence is not grounded. | IR outage can hide a real absence unless separate sensor-health monitoring raises pressure. |
| `impingement_pressure_above_0.8_for_3min` | `vla_pressure`, `vla_pressure_above_threshold_since_s` | Non-firing. Missing pressure data means overload is not grounded. | Pressure gauge outage can hide persistent overload. |
| `consent_contract_expired` | `consent_contracts`, `now_epoch`, programme role | Non-firing. Missing contracts mean expiry is not grounded. | Production snapshot does not yet populate a robust consent-expiry map, so this registered predicate is currently inert unless another source fills it. |
| `vinyl_side_a_finished` | `vinyl_side`, `vinyl_tail_in` | Non-firing. Missing vinyl state means side completion is not grounded. | Vinyl state outage can miss a side-flip boundary. |
| `operator_voice_contradicts_programme_intent` | programme `content.narrative_beat`, `contradiction_score` | Non-firing. Missing contradiction score means disagreement is not grounded. | Production snapshot reads recent STT but does not yet compute a contradiction score, so this predicate is currently inert. |

## Runtime Boundary

`AbortEvaluator` owns the abort/veto finite-state machine. `ProgrammeManager` owns lifecycle transitions. The current implementation wires them this way:

- `evaluate(active, snapshot)` opens at most one pending abort for the active programme.
- `commit_abort(active.programme_id)` commits only a pending abort that still belongs to the active programme.
- `handle_veto_impingement()` consumes `programme.abort.veto` during the five-second veto window.
- `clear_pending()` removes stale pending abort state when an operator, planned, or time-cap transition changes programme identity.

This means a pending abort is not a free-floating failure flag. It is a programme-scoped supervisory decision.

## Operational Implications

- A non-firing predicate can be a healthy state, insufficient evidence, missing data, stale data, or an unwired source. Callers must not collapse those into one meaning.
- Missing-data diagnostics should feed monitoring and later prep/runtime priors, but they should not author content or layout.
- Consent-expiry and contradiction-score predicates are registered but under-instrumented. They should remain visible as incomplete supervisory paths rather than being silently removed.
- Future loop cards for abort supervision should include sensor freshness, sample cadence, stale thresholds, pending/committed/vetoed counts, and per-predicate missing-field counts.

## Follow-Ups

1. Add sensor-freshness fields to the abort snapshot and expose per-field missing/stale diagnostics.
2. Populate `consent_contracts` from the consent registry or mark the predicate disabled with an explicit receipt until that source exists.
3. Add a grounded contradiction-score source before relying on `operator_voice_contradicts_programme_intent`.
4. Emit metrics for pending, committed, vetoed, stale-cleared, and missing-data abort decisions.
5. Add a loop card for programme abort supervision once the diagnostic fields exist.
