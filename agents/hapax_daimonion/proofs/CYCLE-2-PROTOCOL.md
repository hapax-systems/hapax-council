# SCED Cycle 2 Protocol

**Date**: 2026-05-16
**Source**: Council IV Investment 2 + CCTV scoring
**Status**: Design (pre-registration pending)

## Corrections from Cycle 1

Cycle 1 BF=3.66 (corrected ~2.0-2.5 after autocorrelation). Does not clear BF>=10 for a claim this large. Observed effect +0.029 vs predicted +0.150 — study was underpowered.

## Statistical Model

**Primary analysis**: Kruschke BEST (Bayesian Estimation Supersedes the t-Test)
- HDI+ROPE as decision rule
- BF retained as secondary readout only
- BF threshold: >=10 for persuasive support in either direction
- BF 3-10 is anecdotal — not cited as support

**Autocorrelation**: AR(1) residual modeling mandatory
- Do not report BF without autocorrelation correction
- Cycle 1's BF=3.66 corrects to ~2.0-2.5 — this must not recur

**Effect size**: Recalibrated to observed +0.029 range
- Pre-registered +0.150 was mechanistically naive
- Power analysis based on +0.029 determines required N

## Primary Dependent Variable

**repair_cycle_resolution_rate_2turn**: fraction of REPAIR_1 DUs that reach GROUNDED within 2 turns.

This is trust-relevant (did understanding get repaired?) rather than task-accurate (did the answer score well?). It is grounding-native and directly tied to the DU state machine.

Requires Repair 1 (acceptance off-by-one) to be deployed before data collection — otherwise the DU transitions are corrupted.

## Design

ABAB or multiple-baseline (not simple reversal).

Justification: ordinary reversal is suspect for interventions that create persistent common ground. Once a grounding ledger has accumulated state, removing it doesn't return the system to baseline — it removes a substrate while the operator retains the understanding built on it.

## Pre-Registration Template

1. **Hypothesis**: Structured grounding context (thread + acceptance + directive + effort) increases repair_cycle_resolution_rate_2turn compared to baseline.
2. **Primary DV**: repair_cycle_resolution_rate_2turn
3. **Secondary DVs**: GQI, monologic score, acceptance distribution
4. **Effect size**: Expected +0.029 (calibrated from Cycle 1 observed)
5. **N**: [compute from power analysis at +0.029 effect]
6. **BF threshold**: >=10
7. **Autocorrelation**: AR(1) residuals
8. **Design**: ABAB with minimum 20 sessions per phase
9. **Exclusions**: Sessions < 5 turns, sessions with consent/guest overrides
10. **Analysis plan**: Kruschke BEST with HDI+ROPE

## Sentinel Retirement

Sentinel fact (2-digit number retrieval) is retired from the grounding package narrative per Council IV. Tests prompt-integrity retrieval, not grounding. Retained only as narrow prompt-integrity diagnostic.
