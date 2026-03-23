# Pre-Registration: Conversational Grounding via Structured Context Anchoring (Cycle 2)

**Pre-registration date:** [TO BE FILLED — before Phase B data collection begins]
**Registration location:** [OSF URL] + Git commit [SHA]

---

## 1. Study Information

### 1.1 Title
Does a structured conversational grounding package — comprising thread-based context anchoring, discourse unit state tracking, and effort modulation — produce measurably different conversational behavior in a voice AI system?

### 1.2 Research Question
Does injecting a multi-component grounding package into the LLM context window improve embedding-based semantic coherence between operator utterances and system responses, relative to a stripped baseline with no grounding machinery?

### 1.3 Background and Rationale

**Theoretical basis:** Clark & Brennan (1991) define conversational grounding as the collaborative process of establishing mutual understanding. Traum (1994) formalized this into 7 computational grounding acts (initiate, continue, acknowledge, repair, request-repair, request-acknowledge, cancel). No commercial conversational AI system implements Clark-compliant grounding (Shaikh et al., ACL 2025: frontier LLMs score 23.23% on grounding tasks, worse than random). RLHF training actively suppresses grounding acts (Shaikh et al., NAACL 2024).

**Mechanistic basis:** Structured context creates genuinely different computational dynamics in LLMs — not organizational convenience but computational architecture. The prompt functions as a program that configures the transformer's forward pass (Von Oswald et al. 2023; theoretical framework 2026). Position determines representation (primacy tail, attention sinks). Context components are literal feature activators (Anthropic SAE 2024). Acceptance signals function as reward for implicit in-context reinforcement learning (2024). See `CONTEXT-AS-COMPUTATION.md` for full evidence stack.

**Cycle 1 pilot:** 37 sessions (17 baseline + 20 intervention). BF=3.66 (inconclusive) on word overlap metric. Qualitative grounding effects observed (sustained high-anchor sequences, contradiction catching, co-developed ideas) but invisible to word overlap. Cycle 2 replaces word overlap with embedding-based coherence and adds the full grounding package (ledger, effort modulation, concern-aware repair) based on exhaustive refinement research (28 agents, 80+ citations). See `CYCLE-1-PILOT-REPORT.md`.

**Counter-position:** The industry converges on profile-gated retrieval (ChatGPT Memory, Gemini, Mem0). We argue this architecture produces 5 documented failure modes and does not achieve grounding in Clark's sense. See `POSITION.md`.

### 1.4 Hypotheses

**H1:** Phase B sessions (full grounding package active) will show higher mean `turn_pair_coherence` than Phase A sessions (grounding package inactive).

**H0:** The grounding package produces no practically meaningful change in `turn_pair_coherence`.

**Predicted effect size:** d=0.3-0.6, calibrated from grounding research literature (Clark & Wilkes-Gibbs 1986 transfer, dialogue intervention meta-analysis d=0.44-0.53).

**Power:** At d=0.5 with 20 sessions/phase, ~40-50% probability of decisive BF (>10). Pre-commit to extending if inconclusive.

---

## 2. Design

### 2.1 Study Type
Single-case experimental design (SCED), open-label, N=1.

### 2.2 Design Structure
A-B-A (baseline → intervention → reversal).

**Carryover concern:** Barlow, Nock & Hersen (2009) note reversal designs are inappropriate when interventions entail learning. Grounding creates persistent knowledge structures. If A' does not return to baseline, this will be interpreted as "residual of learning" rather than evidence against the intervention. A-B-A-B extension may be adopted if A' is ambiguous.

### 2.3 Phase Definitions

| Phase | Label | Condition | Treatment Flags |
|-------|-------|-----------|----------------|
| A | Baseline | No grounding | stable_frame=false, grounding_directive=false, effort_modulation=false, cross_session=false, sentinel=false |
| B | Intervention | Full package | stable_frame=true, grounding_directive=true, effort_modulation=true, cross_session=true, sentinel=true |
| A' | Reversal | No grounding | Same as Phase A |

All phases share: `experiment_mode=true`, `phenomenal_stimmung_only=true`, `salience_context=false`, `screen_context=false`.

### 2.4 Phase Change Decision Rules
Minimum 10 sessions per phase. Transition when minimum reached AND last 3 session means are within 20% of phase mean (stability criterion). Maximum 20 sessions per phase.

### 2.5 Blinding Status
**Unblinded** (open-label). The operator designed the experiment, knows the hypothesis, and is the sole participant.

**Bias mitigation:**
- All scoring is automated (embedding similarity, Langfuse traces)
- Pre-specified analysis pipeline committed before data collection
- Feature flags control intervention mechanically (no behavioral adaptation possible for the grounding machinery itself)
- Behavioral covariates tracked to detect operator drift between phases
- A-B-A reversal provides 2 demonstrations of effect
- All raw data published in lab journal
- Deviations documented per Section 9
- Experiment freeze enforcement: pre-commit hook + CI gate prevent changes to frozen paths during data collection

---

## 3. Participant and Setting

### 3.1 Participant
Single operator, sole user of the system. Daily voice AI user. ADHD diagnosis (relevant: pacing, dysfluency tolerance, and executive function support are part of the system's design rationale).

### 3.2 Setting
Home office. CachyOS (Arch-based), RTX 3090, Hyprland (Wayland). Blue Yeti microphone, PreSonus Studio 24c audio interface. LiteLLM gateway routing to Claude Opus 4.6. Kokoro TTS. Faster-whisper STT (distil-large-v3).

### 3.3 Generalizability
Single-case study. Results apply to this specific operator-system dyad only. Generalization requires conceptual replication on different systems and operators.

---

## 4. Variables

### 4.1 Independent Variable
Conversational grounding package (3+1 framework):

**Treatment components** (toggled together as a package per Kazdin 2011 treatment package strategy):

1. **Conversation thread** (`stable_frame`): `ThreadEntry` dataclass with verbatim operator text (preserving conceptual pacts per Brennan & Clark 1996), acceptance signal, grounding state. Max 10 entries with tiered compression (recent=full+quotes, middle=referring expression, oldest=keyword). Injected in STABLE band (primacy position).

2. **Grounding ledger** (`grounding_directive`): DU state machine implementing simplified Traum (1994) automaton. States: PENDING → GROUNDED/REPAIR-1/REPAIR-2/ABANDONED/CONTESTED/UNGROUNDED. Concern-aware repair thresholds (Clark's "sufficient for current purposes"): high concern + low GQI → require ACCEPT (threshold 0.9), low concern + high GQI → IGNORE acceptable (threshold 0.3). Strategy directive injected per turn in VOLATILE band (recency position).

3. **Effort modulation** (`effort_modulation`): 2D calibration mapping activation × GQI to 3 discrete effort levels (EFFICIENT 22-25 words / BASELINE 30-35 / ELABORATIVE 40-48). Hysteresis: escalation immediate, de-escalation damped. Implements Clark's Principle of Least Collaborative Effort.

4. **Cross-session memory** (`cross_session`): Seeds thread with 2-3 prior session entries at session start. Hybrid retrieval (2 recency + 1 semantic). Prioritizes unresolved DUs. Cosine threshold >0.4 — empty beats irrelevant.

**Diagnostic instrument** (not part of treatment IV):

5. **Sentinel fact** (`sentinel`): Random 2-digit number for prompt integrity verification. Dependent measure, not treatment component (Ward-Horner & Sturmey 2010 construct validity).

**System prompt:** Stripped to ~800-1000 tokens (`experiment_mode=true`). No tool descriptions, no profile digest, no environmental modulation. Dignity floor + minimal operator style only.

Implementation: `conversation_pipeline.py`, `grounding_ledger.py`, `persona.py`, `conversational_policy.py`.

### 4.2 Primary Dependent Variable
**Name:** `turn_pair_coherence`
**Definition:** Cosine similarity between nomic-embed-text-v2-moe (768-dim) embeddings of user utterance and assistant response.
**Scale:** Continuous, 0.0-1.0
**Collection:** Automated per-turn via `grounding_evaluator.py:score_turn_pair_coherence()`
**Pushed to:** Langfuse per utterance trace

### 4.3 Secondary Dependent Variables
- `coherence_trajectory_slope` — Kendall Tau of turn_pair_coherence × turn index within session
- `acceptance_type` — ACCEPT(1.0)/CLARIFY(0.7)/IGNORE(0.3)/REJECT(0.0)
- `frustration_score` — 8-signal mechanical detector
- `context_anchor_success` — word overlap (retained for Cycle 1 comparison)
- `response_monologic` — RLHF anti-pattern detector (1.0=monologic, 0.0=dialogic). Monitors whether RLHF training-time suppression of grounding acts manifests in model output.
- `directive_compliance` — did model follow the grounding directive? (1.0=compliant, 0.0=non-compliant). Phase B only.
- `gqi` — Grounding Quality Index. Composite: 50% EWMA acceptance + 25% trend + 15% consecutive negatives + 10% engagement. Feeds stimmung as 10th dimension (weight 0.3, cognitive category).
- `du_state` — last Discourse Unit grounding state per Traum automaton

### 4.4 Behavioral Covariates
- `user_word_count` — words per operator utterance
- `assistant_word_count` — words per system response
- `total_latency_ms` — end-to-end turn time
- `activation_score` — salience router activation (computed mechanically, not used for model selection; feeds effort calibrator)
- `concern_overlap` — salience router concern overlap (feeds grounding criterion modulation)
- `effort_level` — EFFICIENT/BASELINE/ELABORATIVE (from activation × GQI)

---

## 5. Session Inclusion/Exclusion Criteria

### 5.1 Inclusion
- Minimum 5 conversational turns
- Feature flags in correct state for current phase
- All per-turn scores present in Langfuse

### 5.2 Exclusion
- System crash or VRAM failure mid-session
- Operator explicitly debugging/testing (not natural conversation)
- Feature flag state incorrect for current phase

### 5.3 Turn-Level
All turns with valid `turn_pair_coherence` score included. Turns where embedding failed (score=None) excluded from primary analysis but counted for session turn threshold.

### 5.4 Missing Data
Sessions with >30% missing turn-level coherence scores excluded. No imputation.

---

## 6. Sample Size

### 6.1 Sessions Per Phase
Minimum 10, maximum 20 per phase.

### 6.2 Justification
Resource constraint: operator has ~5-10 sessions per evening. 10 sessions minimum provides adequate precision for BEST estimation (Cycle 1 pilot: 17 baseline sessions yielded stable session means). 20 sessions maximum prevents indefinite collection.

### 6.3 Sequential Monitoring
Compute posterior after every 5 sessions. Report HDI width and %ROPE at each checkpoint. No optional stopping — minimum 10 sessions regardless of posterior.

---

## 7. Analysis Plan

### 7.1 Framework
Bayesian Estimation Supersedes the t-Test (BEST; Kruschke 2013).

### 7.2 Model
Student-t likelihood on session-level mean `turn_pair_coherence`. Two groups: Phase A sessions, Phase B sessions. Separate variance estimates per group.

Session-level aggregation addresses within-session autocorrelation (Shadish et al. 2013: mean SCED autocorrelation r=0.20).

### 7.3 Priors
- Group means: Normal(mu=Phase_A_mean, sigma=0.3) — calibrated from Cycle 2 Phase A data
- Group SDs: HalfCauchy(beta=Phase_A_sd)
- Normality (df): Exponential(1/29) + 1

Prior predictive check: verify draws produce plausible coherence values (0.0-1.0 range).

### 7.4 ROPE
[-0.05, 0.05] on the raw difference in session means (mu_B - mu_A).

Justification: a 5-percentage-point shift in semantic coherence is the smallest change that would justify the engineering cost of maintaining the grounding package. Below this threshold, the package adds complexity without meaningful improvement.

### 7.5 Decision Rules
- **Effect confirmed:** 95% HDI of mu_diff falls entirely outside ROPE
- **Practical equivalence:** 95% HDI falls entirely inside ROPE
- **Inconclusive:** HDI overlaps ROPE boundary → extend to 20 sessions/phase or add B' phase

Report BCTau (Tarlow 2017) as supplementary effect size.

### 7.6 Analysis Pipeline
1. Load session data from `proofs/claim-1-stable-frame/data/cycle-2/`
2. Apply inclusion/exclusion criteria (Section 5)
3. Compute session-level mean `turn_pair_coherence`
4. Fit BEST model (PyMC, Student-t likelihood)
5. Extract posterior for `mu_diff`
6. Compute 95% HDI, %ROPE, BCTau
7. Apply decision rules (Section 7.5)
8. Sensitivity: re-run with Normal(0, 1) prior and HalfNormal(1) SD prior

Code: `agents/hapax_voice/stats.py` (to be updated with BEST implementation before Phase B analysis).

### 7.7 Exploratory (not pre-registered, lower evidential status)
- Trajectory slope comparison (does coherence improve faster in Phase B?)
- Turn-pair acceptance prediction (does high coherence predict ACCEPT?)
- Behavioral covariate comparison (does operator behavior differ by phase?)
- Quantile comparison (90th percentile coherence B vs A — peak experiences vs mean shift)
- G-Eval LLM-as-judge grounding depth scores (offline, post-collection)
- RLHF monitoring: directive_compliance and response_monologic trends across phases

---

## 8. Effect Size

### 8.1 Target
To be calibrated from Cycle 2 Phase A baseline: target = 0.3-0.5 × Phase A SD of session-level mean `turn_pair_coherence`.

### 8.2 Justification
Expected d=0.3-0.6 based on:
- Clark & Wilkes-Gibbs (1986): ~86% efficiency gain on fixed referents, transferred at 10-20% to open-domain voice → d=0.25-0.50
- Dialogue intervention meta-analysis: d=0.44-0.53
- Cycle 1 qualitative observations suggest real but small effect masked by wrong metric

Power: at d=0.5 with 20 sessions/phase, ~40-50% probability of decisive BF (Schönbrodt & Wagenmakers 2018). Pre-commit to extending if inconclusive.

---

## 9. Deviation Protocol

Any deviation after data collection begins documented in `research/protocols/deviations/`:

| # | Section | Original | Deviation | Justification | Impact |
|---|---------|----------|-----------|---------------|--------|

Analysis code versioned at code freeze commit (SHA to be recorded here after freeze). Post-registration code changes are deviations. Experiment freeze enforcement (pre-commit hook + CI gate) prevents accidental changes to frozen paths.

See `lab-journal/posts/2026-03-21-deviation-disclosure/` for Cycle 1→2 deviation disclosure (Willroth & Atherton 2024 format).

---

## 10. Transparency

- Raw session data: `proofs/claim-1-stable-frame/data/cycle-2/`
- Analysis code: `agents/hapax_voice/stats.py`
- Research documents: `agents/hapax_voice/proofs/`
- Lab journal: [GitHub Pages URL — to be enabled]
- OSF registration: [URL — to be filed]
- Source code: [https://github.com/ryanklee/hapax-council](https://github.com/ryanklee/hapax-council)
- License: CC-BY-4.0 (text), CC0 (data), Apache-2.0 (code)

---

## 11. Theoretical Framework References

- Clark & Brennan (1991). Grounding in communication. APA.
- Clark (1996). Using Language. Cambridge University Press.
- Traum (1994). A computational theory of grounding. PhD, Rochester.
- Brennan & Clark (1996). Conceptual pacts. JEPLMC 22.
- Kazdin (2011). Single-Case Research Designs. Oxford.
- Kruschke (2013). BEST. J Exp Psych: General 142(2).
- Ward-Horner & Sturmey (2010). Component analyses. JABA 43(4).
- Shaikh et al. (2025). Navigating rifts in human-LLM grounding. ACL 2025.
- Shaikh et al. (2024). Grounding gaps in LM generations. NAACL 2024.
- Tarlow (2017). Baseline Corrected Tau. Behavior Modification 41(4).
- Barlow, Nock & Hersen (2009). Single Case Experimental Designs. 3rd ed.
- Shadish et al. (2013). Bayesian autocorrelation estimates. Behavior Research Methods.
- Schönbrodt & Wagenmakers (2018). Bayes Factor Design Analysis.
