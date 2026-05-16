# Pre-Registration: Conversational Grounding via Structured Context Anchoring (Cycle 2)

**Pre-registration date:** 2026-04-16
**Registration location:** https://osf.io/5c2kr/overview + Git commit `ceb84310e5e7cc46758e647f2df3ac5f2850533e`
**Substrate condition locked for this pre-registration:** Condition A — Qwen3.5-9B (EXL3 5.0bpw) served by TabbyAPI on `:5000`, routed as the `local-fast`/`coding`/`reasoning` LiteLLM routes. The parallel OLMo-3-7B substrate (Condition A') deployed 2026-04-16 on `:5001` is **out of scope** for this pre-registration; an equivalent Cycle 2 analysis under Condition A' will be filed as a separate pre-registration if and when it is undertaken.

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

**Livestream context for phase transitions:** Data collection occurs entirely during 24/7 livestream operation (see §3.2). Phase transitions happen mid-stream: a phase boundary is marked by the operator toggling the feature-flag set defined in §2.3 via the operator-facing flag CLI, which causes an atomic persistence of the new flag state before the next utterance is processed. In-flight discourse units (DU state PENDING at the moment of transition) are allowed to resolve under their originating phase's flags and are tagged with their originating phase; no mid-DU flag changes occur. The stream itself does not stop at phase boundaries.

### 2.3 Phase Definitions

| Phase | Label | Condition | Treatment Flags |
|-------|-------|-----------|----------------|
| A | Baseline | No grounding treatment | stable_frame=false, grounding_directive=false, effort_modulation=false, cross_session=false |
| B | Intervention | Full treatment package | stable_frame=true, grounding_directive=true, effort_modulation=true, cross_session=true |
| A' | Reversal | No grounding | Same as Phase A |

All phases share: `experiment_mode=true`, `phenomenal_stimmung_only=true`, `salience_context=false`, `screen_context=false`.

`sentinel` is not a treatment flag. If enabled during a probe window, it is
analyzed only as prompt-integrity instrumentation and not as evidence that the
grounding package worked.

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
Home office, 24/7 research livestream (the constitutive LRR-epic principle: the stream IS the research instrument; there are no offline / non-stream-context sessions). CachyOS (Arch-based), RTX 5060 Ti (compositor + imagination) + RTX 3090 (TabbyAPI local inference), Hyprland (Wayland). Blue Yeti microphone (operator voice), PreSonus Studio 24c audio interface (Cortado MKIII contact mic + monitor outputs). Studio compositor at `/dev/video42` → OBS V4L2 + native GStreamer RTMP → MediaMTX local relay on `:1935` → YouTube public endpoint.

**LLM infrastructure (locked for Condition A pre-registration):**
- LiteLLM gateway on `:4000` routes the voice conversational backbone to local inference (`local-fast` → Qwen3.5-9B via TabbyAPI `:5000`). Cloud routes (`balanced` → Claude Opus, `fast` → Gemini Flash) are used only for auxiliary reasoning surfaces (orientation, briefing, governance) and do NOT serve the conversational turn under study.
- STT: faster-whisper distil-large-v3 (GPU).
- TTS: Kokoro 82M (CPU).
- Langfuse callback wired on LiteLLM for per-turn trace capture (enabled 2026-04-16; see LRR Phase 5 closure).
- Nomic embedder: `nomic-embed-text-v2-moe` via Ollama CPU route (GPU-isolated from TabbyAPI per workspace CLAUDE.md § Shared Infrastructure).

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

### 5.0 Operational definition of "session"

Because data collection occurs during continuous livestream operation (§3.2), "session" is defined operationally as follows:

A **session** is a contiguous livestream segment bounded on both sides by either (a) a feature-flag transition event, (b) a stream-stop event (including unintended stream interruption > 30s), or (c) an explicit operator-emitted session boundary marker (a CLI command writing a timestamped session-boundary event to the research registry). Every utterance within a session shares a single set of feature-flag values (§2.3). Sessions are non-overlapping and together tile the full livestream uptime during the study period.

Session IDs are assigned deterministically from the session boundary markers in the append-only research registry. No session exists outside the livestream.

### 5.1 Inclusion
- Minimum 5 conversational turns
- Feature flags in correct state for current phase throughout the session
- All per-turn scores present in Langfuse

### 5.2 Exclusion
- System crash or VRAM failure mid-session (the session is truncated at the failure timestamp; if the pre-failure portion meets the 5-turn minimum it may be included, otherwise excluded)
- Operator-emitted `experiment-pause` marker active during the session (operator is explicitly debugging the system itself, not conducting natural-use interaction)
- Feature flag state incorrect for current phase (should not occur if §2.2 mid-stream-transition protocol is followed; any such session is excluded)

**Not exclusion criteria (explicit):** operator coding on-stream, operator reading audience chat, operator reacting to ambient studio/music activity, operator engaged with other non-Hapax software — all of these are natural livestream operation and are IN SCOPE as conversational ground-truth per the livestream-as-research-instrument principle.

### 5.3 Turn-Level
All turns with valid `turn_pair_coherence` score included. Turns where embedding failed (score=None) excluded from primary analysis but counted for session turn threshold.

### 5.4 Missing Data
Sessions with >30% missing turn-level coherence scores excluded. No imputation.

---

## 6. Sample Size

### 6.1 Sessions Per Phase
Minimum 10, maximum 20 per phase.

### 6.2 Justification
Sessions accumulate during livestream uptime (§3.2, §5.0); the rate of session accumulation depends on flag-transition cadence and stream duration rather than on scheduled offline windows. 10 sessions minimum provides adequate precision for BEST estimation (Cycle 1 pilot: 17 baseline sessions yielded stable session means under a prior non-stream session model that is no longer operational; session-level variance is expected to be comparable or lower in stream-continuous data). 20 sessions maximum prevents indefinite collection.

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

**Code and implementation commitment:** `agents/hapax_daimonion/stats.py` currently ships a **scipy-analytical BEST approximation** (method label `scipy-analytical-approx-2026-04-14`). Before Phase B analysis begins, the analysis code will be upgraded to **PyMC MCMC BEST** (method label `pymc-mcmc-2026-04-XX`) per the priors and model specified in §7.2–§7.3. The analytical-approximation code remains in the repository as a secondary sensitivity check; primary results will be reported from the MCMC implementation. The MCMC upgrade must land on main before the first Phase B session is included in any analysis. This commitment is frozen by §9 deviation-protocol rules once pre-reg is filed.

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
| 1 | §3.2, §4.1 | Local conversational backbone is Qwen3.5-9B EXL3 5.0bpw on TabbyAPI :5000 (Condition A). OLMo-3 is the only enumerated alternative (Condition A'), invalidating-deviation if swapped. | Substrate swapped to **Command-R 35B EXL3 5.0bpw** on TabbyAPI :5000 (dual-GPU `[16, 10]` split, Q4 cache, max_seq_len 16384) on or before 2026-04-25. Neither Qwen3.5-9B nor OLMo-3 is in the runtime per current council CLAUDE.md. | Operator architectural decision (recorded in council CLAUDE.md update history); Command-R offers stronger grounding/RAG-shape vs Qwen at acceptable VRAM cost. The §9 substrate-swap clause names a hypothetical Qwen→OLMo-3 swap as invalidating; this swap (Qwen→Command-R) is the same shape and equally invalidating per the clause's intent. | **INVALIDATING.** Per §9 substrate-swap clause, this triggers requirement for a new pre-registration. The replacement filing is `agents/hapax_daimonion/proofs/UBCC-PREREGISTRATION.md` (Universal Bayesian Claim-Confidence research program, supersedes osf.io/5c2kr). No further data is to be analyzed under the present pre-registration; any data carried forward is reported as Cycle-2 historical comparator only. |

**Code freeze:** Analysis code is versioned at the git commit SHA recorded on line 4 above; this SHA is set when the pre-registration PR merges and matches the commit that lands this file on main. Post-registration code changes to any path listed in `research/protocols/frozen-paths.yaml` are deviations and require a row in the table above. Experiment freeze enforcement (pre-commit hook + CI gate) prevents accidental changes to frozen paths during data collection.

**Substrate swap during collection:** if operator elects to switch the conversational backbone from Qwen3.5-9B (Condition A) to OLMo-3 (Condition A') during the Cycle 2 collection window, this constitutes a deviation that invalidates the current pre-registration and requires a new pre-registration under Condition A'. The deployed OLMo-3 backend at `:5001` (LiteLLM `local-research-instruct` route) is idle from the pre-reg's perspective until such a new filing occurs.

**STATUS (2026-04-25):** This pre-registration is **superseded** by `UBCC-PREREGISTRATION.md` per Deviation #1. The substrate locked in §3.2/§4.1 has been swapped to Command-R 35B, an alternative not enumerated in §9, which the §9 clause's intent ("any substrate swap during collection invalidates") covers. The replacement registration carries OSF cross-link `Supersedes: osf.io/5c2kr` per OSF Registries amendment mechanics.

See `lab-journal/posts/2026-03-21-deviation-disclosure/` for Cycle 1→2 deviation disclosure (Willroth & Atherton 2024 format).

---

## 10. Transparency

- Raw session data: `proofs/claim-1-stable-frame/data/cycle-2/` (in-repo; stream-originated per §3.2, §5.0)
- Langfuse trace archive: live via the LiteLLM `langfuse` callback (enabled 2026-04-16); metadata persists indefinitely in ClickHouse (no TTL) with a 3-day MinIO blob retention per the LRR Phase 5 observability remediation. A durable consumer-side trace reader (`agents/_langfuse_local.py`) writes per-day JSONL snapshots so trace-level metadata remains readable after blob expiry.
- Analysis code: `agents/hapax_daimonion/stats.py` (pinned at the pre-reg commit SHA; upgraded to PyMC MCMC per §7.6 before Phase B analysis)
- Research documents: `agents/hapax_daimonion/proofs/`
- Livestream archive (where relevant, subject to consent posture): public YouTube channel feed; per-segment sidecar metadata under `/data/archive/`
- Lab journal: not yet published (placeholder removed from this pre-reg; will be added via deviation record if enabled later)
- OSF registration: https://osf.io/5c2kr/overview (filed 2026-04-16)
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
