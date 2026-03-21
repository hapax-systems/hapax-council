# Pre-Registration: Conversational Context Anchoring (Cycle 2)

**Pre-registration date:** [TO BE FILLED — before Cycle 2 baseline begins]
**Registration location:** [OSF URL] + Git commit [SHA]
**Registered by:** the operator

---

## 1. Study Information

### 1.1 Title
Does conversation thread injection improve semantic grounding in
voice AI interaction? A single-case Bayesian estimation study.

### 1.2 Research Question
Does injecting a turn-by-turn conversation thread into the LLM
system prompt improve embedding-based semantic coherence between
operator utterances and system responses?

### 1.3 Background and Rationale
Cycle 1 pilot (N=37 sessions) found a small but consistent effect
(+0.029 on word overlap metric, BF=3.66) that did not reach the
pre-registered effect size (+0.150). However, qualitative analysis
revealed grounding behaviors (sustained high-anchor sequences,
contradiction catching, co-developed ideas) that word overlap cannot
capture. Cycle 2 replaces word overlap with embedding-based semantic
coherence as the primary metric.

The effect size target is calibrated from Cycle 1 pilot baseline SD.

### 1.4 Hypotheses
**H1:** Phase B sessions (stable_frame=true) will show higher
mean `turn_pair_coherence` than Phase A sessions (stable_frame=false).

**H0:** The intervention produces no practically meaningful change
in `turn_pair_coherence`.

---

## 2. Design

### 2.1 Study Type
Single-case experimental design (SCED), open-label.

### 2.2 Design Structure
A-B-A (baseline → intervention → reversal).

### 2.3 Phase Definitions
| Phase | Label | Condition | Feature Flag |
|-------|-------|-----------|-------------|
| A | Baseline | No thread | stable_frame=false |
| B | Intervention | Thread injected | stable_frame=true |
| A' | Reversal | No thread | stable_frame=false |

### 2.4 Phase Change Decision Rules
Minimum 10 sessions per phase. Transition when minimum reached AND
last 3 session means are within 20% of phase mean (stability criterion).
Maximum 20 sessions per phase.

### 2.5 Blinding Status
**Blinding:** Unblinded (open-label). The operator designed the
experiment, knows the hypothesis, and is the sole participant.

**Bias mitigation measures:**
- All scoring is automated (embedding similarity, Langfuse traces)
- Pre-specified analysis pipeline (committed before data collection)
- Feature flag controls intervention (no behavioral adaptation possible
  for the thread injection itself)
- Behavioral covariates (user_word_count, assistant_word_count) tracked
  to detect operator behavioral drift between phases
- A-B-A reversal provides 2 demonstrations of effect removal
- All raw data published in lab journal
- Deviations documented per Section 9

---

## 3. Participant and Setting

### 3.1 Participant Description
Single operator, adult male, daily voice AI user, ADHD diagnosis.
System architect and hip hop producer.

### 3.2 Setting
Home office, CachyOS (Arch-based), RTX 3090, Hyprland desktop,
Blue Yeti microphone. LiteLLM gateway routing to Claude Opus 4.6.
Kokoro TTS. Faster-whisper STT.

### 3.3 Generalizability Statement
This is a single-case study. Results apply to this specific
operator-system dyad and cannot be generalized to other users
without replication.

---

## 4. Variables

### 4.1 Independent Variable
Conversation thread injection into the LLM system prompt.
When `stable_frame=true`, per-turn summaries accumulate in
`_conversation_thread` (max 15 entries) and are injected as
"## Conversation So Far" in the STABLE band of the system prompt.
Implementation: `conversation_pipeline.py:388-390`.

### 4.2 Primary Dependent Variable
**Name:** `turn_pair_coherence`
**Definition:** Cosine similarity between nomic-embed-text-v2-moe
(768-dim) embeddings of the user utterance and assistant response.
**Scale:** Continuous, 0.0-1.0
**Collection:** Automated per-turn via `grounding_evaluator.py:score_turn_pair_coherence()`
**Pushed to:** Langfuse per utterance trace

### 4.3 Secondary Dependent Variables
- `coherence_trajectory_slope` — Kendall Tau of turn_pair_coherence × turn index within session
- `acceptance_type` — ACCEPT(1.0)/CLARIFY(0.7)/IGNORE(0.3)/REJECT(0.0)
- `frustration_score` — 8-signal mechanical detector
- `context_anchor_success` — word overlap (retained for Cycle 1 comparison)

### 4.4 Behavioral Covariates
- `user_word_count` — words per operator utterance
- `assistant_word_count` — words per system response
- `total_latency_ms` — end-to-end turn time
- `activation_score` — salience router activation

---

## 5. Session Inclusion/Exclusion Criteria

### 5.1 Inclusion
- Minimum 5 conversational turns
- Feature flag in correct state for current phase
- All per-turn scores present in Langfuse

### 5.2 Exclusion
- System crash or VRAM failure mid-session
- Operator explicitly debugging/testing (not natural conversation)
- Feature flag state incorrect for current phase

### 5.3 Turn-Level
All turns with valid `turn_pair_coherence` score included.
Turns where embedding failed (score=None) excluded from primary
analysis but counted for session turn threshold.

### 5.4 Missing Data
Sessions with >30% missing turn-level coherence scores excluded.
No imputation.

---

## 6. Sample Size

### 6.1 Sessions Per Phase
Minimum 10, maximum 20 per phase.

### 6.2 Justification
Resource constraint: operator has ~5-10 sessions per evening.
10 sessions minimum provides adequate precision for BEST estimation
(pilot showed 17 baseline sessions yielded stable session means).
20 sessions maximum prevents indefinite collection.

### 6.3 Sequential Monitoring
Compute posterior after every 5 sessions. Report HDI width and
%ROPE at each checkpoint. No optional stopping — minimum 10
sessions regardless of posterior.

---

## 7. Analysis Plan

### 7.1 Framework
Bayesian Estimation Supersedes the t-Test (BEST; Kruschke 2013).

### 7.2 Model
Student-t likelihood on session-level mean `turn_pair_coherence`.
Two groups: baseline sessions, intervention sessions.
Separate variance estimates per group.

### 7.3 Priors
- Group means: Normal(mu=baseline_pilot_mean, sigma=0.3)
- Group SDs: HalfCauchy(beta=baseline_pilot_sd)
- Normality: Exponential(1/29) + 1

Prior predictive check: verify draws produce plausible coherence values.

### 7.4 ROPE
[-0.05, 0.05] on the raw difference in session means.

Justification: a 5-percentage-point shift in semantic coherence is
the smallest change that would justify the engineering cost of
maintaining the conversation thread mechanism. Below this threshold,
the thread adds complexity without meaningful grounding improvement.

### 7.5 Decision Rules
- **Effect confirmed:** 95% HDI of mu_diff falls entirely outside ROPE
- **Practical equivalence:** 95% HDI falls entirely inside ROPE
- **Inconclusive:** HDI overlaps ROPE boundary

Report BCTau as supplementary effect size.

### 7.6 Analysis Pipeline
1. Load session JSONs from `proofs/claim-1-stable-frame/data/`
2. Apply inclusion/exclusion criteria (Section 5)
3. Compute session-level mean `turn_pair_coherence`
4. Fit BEST model (PyMC)
5. Extract posterior for `mu_diff`
6. Compute 95% HDI, %ROPE, BCTau
7. Apply decision rules (Section 7.5)
8. Sensitivity: re-run with Normal(0, 1) prior and HalfNormal(1) SD prior

Code: `agents/hapax_voice/stats.py` (committed at pre-registration)

### 7.7 Exploratory
- Trajectory slope comparison (does coherence improve faster in Phase B?)
- Turn-pair acceptance coherence (does high coherence predict ACCEPT?)
- Behavioral covariate comparison (does operator behavior differ by phase?)
- G-Eval LLM-as-judge grounding scores (offline, post-collection)

---

## 8. Effect Size

### 8.1 Target
[TO BE FILLED from Cycle 2 baseline: 0.3-0.5 × baseline SD]

### 8.2 Justification
Calibrated from Cycle 1 pilot baseline data. A medium effect (0.3-0.5 SD)
represents a meaningful shift in semantic coherence that is detectable
with 10+ sessions per phase.

---

## 9. Deviation Protocol

Any deviation after data collection begins documented in:

| # | Section | Original | Deviation | Justification | Impact |
|---|---------|----------|-----------|---------------|--------|

Analysis code versioned at commit [TO BE FILLED]. Post-registration
code changes are deviations.

---

## 10. Transparency

- Raw session data: published in `proofs/claim-*/data/`
- Analysis code: `agents/hapax_voice/stats.py`
- Lab journal: [GitHub Pages URL]
- OSF registration: [URL]
- License: CC-BY-4.0 (text), CC0 (data)
