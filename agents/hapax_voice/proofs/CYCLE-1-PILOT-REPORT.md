# Cycle 1 Pilot Report: Conversational Continuity

**Status**: Exploratory pilot. Not confirmatory. Informs Cycle 2 design.
**Date**: 2026-03-19 to 2026-03-20
**Operator**: (single operator)
**System**: Hapax Council voice daemon (Claude Opus 4.6 via LiteLLM)

---

## 1. What We Did

Tested whether injecting a turn-by-turn conversation thread into the
LLM system prompt improves conversational grounding, measured by
`context_anchor_success` (word overlap between response and thread).

**Design**: SCED A-B with planned A' reversal.
- Phase A (baseline): 17 sessions, all components OFF
- Phase B (intervention): 20 sessions, stable_frame=true
- Phase A' (reversal): planned but not yet collected

**Pre-registration**: Claims pre-registered in `proofs/claim-*/hypothesis.md`
on 2026-03-19 before Phase B collection began. However, the pre-registration
was incomplete (4 of ~20 recommended fields) and contained a ROPE mismatch
between the documented specification and the implemented analysis.

## 2. Results

### Quantitative (on pre-registered metric)

| Metric | Baseline (A) | Intervention (B) | Difference |
|--------|-------------|------------------|-----------|
| Mean context_anchor_success | 0.320 | 0.350 | +0.029 |
| Turns | 111 | 228 | — |
| Sessions (5+ turns) | — | 19 | — |
| Sessions above threshold | — | 7/19 (37%) | — |
| Bayes Factor | — | 3.66 | moderate |
| ROPE (posterior outside) | — | 78.5% | — |

**Decision**: Inconclusive. BF 3.66 is moderate evidence — above anecdotal
(>3) but not decisive (<10). The pre-registered effect size (+0.150) was
not reached. The measured effect (+0.029) is small but consistent.

### Qualitative (not pre-registered, observational)

Phase B produced grounding behaviors never observed in baseline:

1. **Sustained high-anchor sequences**: Sessions 2-4 had 0.7-0.8 anchoring
   across 4+ consecutive turns during substantive discussions. Baseline
   never sustained above 0.5 for more than 1 turn.

2. **Contradiction catching**: Session 11 — operator caught Hapax in a
   contradiction between "track all contexts" and "noise makes it hard
   to think." Thread enabled cross-turn accountability (anchor 0.8).

3. **Confabulation detection**: Sessions 7, 12 — operator used thread
   context to challenge fabricated visual/perceptual claims across
   multiple turns.

4. **Co-developed research**: Session 4 (18 turns) — operator and Hapax
   co-developed the Bayesian mode/tool selection concept through
   sustained grounded conversation.

5. **Self-reflective grounding**: Baseline session 5 — system articulated
   its own context overload problem ("trying to think clearly in a room
   full of alarms"). This occurred WITHOUT the thread, suggesting the
   architecture itself enables emergent grounding.

## 3. Deviations from Pre-Registration

| # | Deviation | When Decided | Impact |
|---|-----------|-------------|--------|
| 1 | ROPE mismatch: pre-registered [-0.05, 0.05] on continuous metric, implemented [0.45, 0.55] on binarized proportion | During implementation (before data collection) | BF computed on wrong scale. Results not directly comparable to pre-registration. |
| 2 | Word cutoff changed 25→35 mid-baseline (sessions 1-8 vs 12-20) | During baseline collection | Creates two sub-baselines with different response length constraints. Potential confound. |
| 3 | Tool hallucination guard expanded during baseline | During baseline collection | Mechanical fix, unlikely to affect primary metric. |
| 4 | Wake word fuzzy matching expanded during baseline | During baseline collection | Affects session initiation, not session content. |
| 5 | Presence-consent override added during baseline | During baseline collection | Affects whether sessions start, not session content. |
| 6 | Missing sessions 009-011 | Pre-baseline engineering sessions excluded a priori | Reduces baseline from 20 to 17 sessions. Not post-hoc exclusion. |

## 4. Limitations

### Metric Limitations
- `context_anchor_success` measures word overlap, not semantic grounding.
  It penalizes abstraction, synthesis, and paraphrasing — all indicators
  of GOOD grounding. The qualitative effects (contradiction catching,
  sustained deep discussion) are invisible to this metric.

### Design Limitations
- **No true code freeze**: Multiple mechanical fixes during baseline
  (most critically, word cutoff 25→35). This violates the principle that
  the only change between phases should be the intervention.
- **Operator awareness**: Open-label design. The operator designed the
  experiment, knows the hypothesis, and may unconsciously change behavior
  between phases. Mitigated by automated scoring but not eliminated.
- **Incomplete pre-registration**: Only 4 of ~20 recommended fields
  specified. No inclusion/exclusion criteria, no prior justification,
  no ROPE justification, no deviation protocol.

### Statistical Limitations
- Beta-binomial analysis with binarization discards within-session
  variance and continuous metric information.
- No autocorrelation modeling for within-session turns.
- Effect size target (+0.150) was a guess with no empirical justification.

## 5. What We Learned

### For Metric Design
- Word overlap is the wrong primary metric for grounding quality
- Embedding-based semantic coherence captures what word overlap misses
- Trajectory slope (does grounding improve within session?) is more
  discriminating than level (what's the average grounding score?)
- Turn-pair coherence (conditional probabilities linking consecutive turns)
  captures the sequential nature of grounding that per-turn averages lose

### For Methodology
- Code must be TRULY frozen before baseline session 1
- Pre-registration needs ~20 fields, not 4
- ROPE must be on the same scale as the analysis
- Effect size targets should be calibrated from pilot data, not guessed
- Session inclusion criteria (minimum turns) must be pre-specified
- Behavioral covariates needed to check for operator drift between phases

### For Analysis
- Kruschke's BEST on session means is better than Beta-binomial binarization
- HDI+ROPE decision rule is more interpretable than BF threshold
- Hierarchical model (turns nested in sessions) is the gold standard
  but BEST on session means is sufficient and simpler

### For the Research Question
- The conversation thread IS doing something — but what it does
  (enabling accountability, supporting sustained discussion, providing
  cross-turn reference) isn't captured by word overlap
- The architecture itself (workspace state as continuous environment)
  enables emergent grounding even without the thread (session 5)
- Tool calls are a separate research direction (Claim 6) that should
  not be conflated with conversational grounding claims

## 6. Decision

Redesign as Cycle 2 with corrected pre-registration:
- New primary metric: embedding-based `turn_pair_coherence`
- New analysis: Kruschke's BEST with HDI+ROPE
- New effect size: calibrated from Cycle 1 pilot baseline SD
- Complete pre-registration template (~20 fields)
- Register on OSF before Cycle 2 baseline
- TRUE code freeze
- Phase A' reversal MANDATORY (primary defense against operator awareness)

Cycle 1 data retained as pilot/background. Not discarded, not retrofitted.

## 7. Data Location

- Baseline: `proofs/claim-1-stable-frame/data/baseline-session-*.json` (17 files)
- Phase B: `proofs/claim-1-stable-frame/data/phase-b-session-*.json` (20 files)
- Phase A': not yet collected
- All session data duplicated in claim-2 and claim-4 directories

---

*This report documents the pilot study honestly. The findings inform
Cycle 2 design but do not constitute confirmatory evidence for any claim.*
