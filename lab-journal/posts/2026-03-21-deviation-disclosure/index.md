---
title: "Deviation Disclosure: Cycle 1 → Cycle 2"
date: 2026-03-21
categories: [deviation, methodology]
description: "Formal deviation disclosure table per Willroth & Atherton (2024). 6 deviations: metric change, analysis method, package framing, ROPE, code freeze, thread cap."
---

## Preregistration Deviation Disclosure

Following [Willroth & Atherton (2024)](https://journals.sagepub.com/doi/10.1177/25152459231213802) format for transparent reporting of methodology changes between Cycle 1 (pilot) and Cycle 2 (corrected).

| # | Original Plan | Change | Type | Reason | Timing | Impact |
|---|--------------|--------|------|--------|--------|--------|
| 1 | Word overlap metric (`context_anchor_success`) | Embedding coherence (`turn_pair_coherence`) | Metric change | Word overlap penalizes abstraction and paraphrasing — qualitative grounding effects invisible to metric | Post-Cycle 1 analysis | Higher sensitivity to true grounding effects; baseline must be re-collected |
| 2 | Beta-binomial Bayes Factor | Kruschke's BEST on session means | Analysis change | Beta-binomial wrong for continuous data; turn-level independence violated by autocorrelation (Shadish et al. 2013, mean r=0.20) | Literature review | Correct model specification; wider but honest posteriors |
| 3 | 4-component package (thread + drop + memory + sentinel) | 3+1 framework (3 treatment + 1 diagnostic) | Framing change | Sentinel tests retrieval not grounding (Ward-Horner & Sturmey 2010 construct validity); including it as treatment inflates package | Package assessment | Cleaner construct validity; sentinel becomes dependent measure |
| 4 | ROPE [-0.05, 0.05] on binarized proportion | HDI+ROPE on continuous session means | Decision rule change | Original ROPE applied to binarized data but pre-registered on continuous scale; mismatch between analysis and pre-registration | Methodology review | Correct statistical decision framework |
| 5 | No code freeze protocol | TRUE code freeze with `volatile_lockdown` flag | Protocol change | Cycle 1 had word limit change (25→35) mid-baseline, creating confound | Protocol review | Eliminates code-change confounds during data collection |
| 6 | Thread cap 15 entries | Thread cap 10 entries (variable length) | Parameter change | "Lost in the Middle" research (Liu et al. 2024); entries 4-12 in attention dead zone at 15 | Compression/scale research | Higher signal-to-noise in thread; reduces context rot |

## Unregistered Steps

Decisions the original registration was ambiguous or silent about:

1. **A-B-A vs A-B-A-B design**: Original pre-registration specified A-B-A. Literature review (Barlow et al. 2009) identified that reversal designs are inappropriate for learning-based interventions. Decision pending — may switch to A-B-A-B or multiple baseline.

2. **Behavioral covariates**: Not in original plan. Added `user_word_count` and `assistant_word_count` as covariates to detect operator behavior change between phases.

3. **Quantile analysis**: Not in original plan. Will compare 90th percentile coherence between phases alongside mean comparison, based on observation that meaningful improvement may be in peak experiences rather than mean shift.

4. **Autocorrelation correction**: Not in original plan. Will use session means to aggregate within-session turns, removing the most severe autocorrelation. For definitive analysis, may fit hierarchical model with AR(1) residuals.
