# Sprint 0 Review

**Date:** 2026-03-31 (Day 2)
**Goal:** Deploy all telemetry that requires no code changes to frozen paths + analyze existing data.

## Gate Results

| Gate | Measure | Threshold | Result | Status |
|------|---------|-----------|--------|--------|
| G3 | 4.1 Impingement contradictions | <= 15% | 0.0% | **PASS** |
| G4 | 7.2 Activation-salience correlation | r < 0.1 rescope | N=0 (no data) | **DEFERRED** |

G3 clears decisively. G4 cannot be evaluated — blocked on 7.1 (DEVIATION-025 needed to instrument `conversation_pipeline.py`).

## Measure Results

### Completed

| Measure | Result | Doc |
|---------|--------|-----|
| 4.1 DMN impingement analysis | 0% contradictions, 716 impingements. Sensor starvation noise (57% burst rate). Strength dynamic range narrow (0.2-0.9, stdev 0.147). | `dmn-impingement-analysis.md` |
| 7.2 Activation score correlation | N=0. No activation_score entries in Langfuse. Blocked on 7.1 DEVIATION-025. | `activation-score-correlation.md` |
| 8.1 Signal availability audit | 11/16 exist, 4 derivable, 1 naming mismatch. No fundamental gaps. | `bayesian-tools-signal-audit.md` |
| 3.2 Protention accuracy | Data gap: activity classifier outputs idle for all 8K entries. Markov/flow models empty. Circadian has 395K obs. Test harness written (12 pass). | `protention-validation-results.md` |
| 3.3 Surprise flagging impact | Test harness written (3 validation tests pass). LLM evaluation ready to run (`-m llm`). | `tests/research/test_surprise_impact.py` |

### Not started (Day 1 items deferred)

| Measure | Blocker | Impact |
|---------|---------|--------|
| 7.1 Salience signal logging | DEVIATION-025 not filed (frozen code) | Blocks 7.2 data collection |
| 4.5 Ollama latency profile | Time — deprioritized for Reverie work | Low risk — can run anytime |
| 6.3 Stimmung threshold telemetry | Time | Non-frozen, can execute in Sprint 1 |
| 6.2 Modulation factor telemetry | May need DEVIATION-025 | Check if frozen path needed |
| 6.5 Per-source health tracking | Time | Non-frozen |

## Key Findings

1. **DMN impingement stream is coherent** — zero contradictions. Safe to build on.
2. **Bayesian tool signals are mostly available** — integration work is mechanical (4 explicit reads + 2 naming fixes).
3. **Protention engine has a data starvation problem** — activity classifier never produces non-idle labels. This blocks validation of the Markov and flow timing models. Root cause investigation needed.
4. **Activation score telemetry doesn't exist yet** — DEVIATION-025 is the critical path item for Sprint 1 salience validation.
5. **Surprise flagging harness is ready** — 40 LLM calls, paired design, can run during any voice session.

## Blockers for Sprint 1

1. **DEVIATION-025** — must be filed to unblock 7.1 and 7.2. Three `hapax_score()` calls to `conversation_pipeline.py`. Observability-only change, no model input/output impact.
2. **Activity classifier** — `production_activity` is always `idle`. Need to verify the `llm_activity` fallback in VLA line 384 and/or check why Hyprland activity detection isn't producing labels.

## Recommendations

1. File DEVIATION-025 immediately — it's the single highest-leverage action.
2. Investigate activity classifier starvation before Sprint 1 Day 3.
3. Run 3.3 surprise flagging test during next voice session.
4. Remaining Day 1 measures (4.5, 6.3, 6.5) can slot into Sprint 1 prep.
