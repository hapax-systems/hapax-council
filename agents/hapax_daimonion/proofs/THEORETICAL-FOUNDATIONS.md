# Theoretical Foundations: Conversational Continuity Research

**Date:** 2026-03-20
**Status:** Comprehensive literature review + synthesis
**Scope:** Everything that bears on our design, methodology, predictions, and counter-positions

---

## I. The Full Grounding Theory Landscape

### Clark's Contribution Model (Complete)

Clark & Brennan (1991) is our cited foundation, but the full model spans a decade of work:

- **Clark & Wilkes-Gibbs (1986)**: Referring is collaborative. Expressions are iteratively refined through proposal-repair-acceptance cycles. Effect: ~86% efficiency gain over 6 trials on fixed referents. *Our transfer: 10-20% at best (open-domain voice, no fixed referents).*
- **Clark & Schaefer (1989)**: Every contribution has two phases — presentation and acceptance. A contribution is the *joint product* of both parties. **A presentation is not complete until acceptance confirms it.**
- **Clark & Brennan (1991)**: The grounding criterion: mutual belief of understanding "sufficient for current purposes." Five levels of evidence, weakest to strongest: continued attention → relevant next turn → acknowledgment → demonstration → verbatim display.
- **Clark (1996) *Using Language***: Full synthesis. Adds **installments** (breaking contributions into checkable pieces), **repairs** (integral, not afterthoughts), **collaborative referring**, **least collaborative effort** (minimize total joint work).

### Eight Medium Constraints

Clark & Brennan identify 8 properties that determine available grounding techniques:
copresence, visibility, audibility, contemporality, simultaneity, sequentiality, reviewability, revisability.

**Voice has**: audibility, contemporality, simultaneity, sequentiality.
**Voice lacks**: copresence, visibility (partially — we have cameras but system doesn't use them for grounding), reviewability (no transcript visible to operator), revisability (spoken words can't be edited).

**Implication**: Our medium is grounding-constrained. The thread compensates for lack of reviewability by making the discourse record available to the system (but NOT to the operator — asymmetric reviewability).

### Traum's Computational Grounding Model

David Traum (1994, PhD, Rochester) formalized Clark into 7 **grounding acts**:

| Act | Definition | Our System |
|-----|-----------|------------|
| Initiate | Begin new discourse unit | Every assistant turn |
| Continue | Add to open DU by same speaker | Multi-sentence responses |
| Acknowledge | Signal understanding | **NOT IMPLEMENTED** — system never asks "does that make sense?" |
| Repair | Correct misunderstanding | **NOT IMPLEMENTED** — bridge phrases prevent rather than repair |
| Request-Repair | Signal lack of understanding | **NOT IMPLEMENTED** — system never says "what do you mean?" |
| Request-Acknowledge | Prompt confirmation | **NOT IMPLEMENTED** — system never says "right?" |
| Cancel | Abandon discourse unit | **NOT IMPLEMENTED** |

**Assessment**: We implement 2 of 7 grounding acts (initiate, continue). We *classify* the operator's acceptance (ACCEPT/CLARIFY/REJECT/IGNORE in `grounding_evaluator.py`), which maps to detecting the operator's acknowledge/request-repair acts. But the system performs none of the 5 responsive acts (acknowledge, repair, request-repair, request-acknowledge, cancel).

Traum's **grounding automaton** tracks each Discourse Unit through states: ungrounded → acknowledged → grounded. Our thread has no per-DU state tracking.

**Key papers**: Traum (1994) PhD thesis; Traum (1999) AAAI Fall Symposium; Roque & Traum (2008) on graded grounding; Paek & Horvitz (2000) on probabilistic grounding as Bayesian inference.

### Brennan's Conceptual Pacts

Brennan & Clark (1996): Interlocutors form **conceptual pacts** — temporary agreements on how to conceptualize referents. Pacts are *partner-specific* (different names for same thing with different partners). Breaking a pact (using different terminology) incurs processing cost.

**Our gap**: The thread stores `user_clause → resp_clause` pairs but doesn't preserve the operator's chosen terminology. If the operator says "that beat" and the system rephrases as "the musical composition," no pact forms.

Brennan & Hanna (2009): Partner-specific adaptation is rapid, automatic, and supported by memory associations. Even our single-operator system should build operator-specific vocabulary over time. We don't.

### Counter-Positions to Clark

**Pickering & Garrod (2004) — Interactive Alignment**: Coordination arises via automatic priming, not explicit negotiation. Alignment operates at phonological, lexical, syntactic, and semantic levels simultaneously. **Percolation**: alignment at one level causes alignment at others.

*Does this undermine our thread approach?* Partially. If alignment is priming-based, an explicit thread is solving the wrong problem. **However**: LLMs have no persistent priming mechanism between turns. The thread is a *proxy* for what priming would do in human dialogue. Pickering & Garrod (2009 revision) acknowledge both mechanisms operate: priming handles routine alignment, explicit grounding handles novel references and repairs.

**Healey et al. (2018) — Running Repairs**: Repairs occur approximately **once every 25 words** in natural conversation — far more frequent than assumed. Both positive evidence (acknowledgments) and negative evidence (clarification requests) are critical. **Our system produces neither.**

**Mills (2014)**: Coordination produces **complementary** (divergent, specialized) turns, not convergent ones. Repetition (priming) is a special case. *Implication: our word-overlap metric is theoretically wrong even for measuring Clark-style grounding.*

**Koschmann & LeBaron (2003)**: Attempted to apply Clark's model to surgical team interactions. Conclusion: "common ground represents a confusing metaphor rather than a useful explanatory mechanism" for real-world multiparty embodied interaction.

### Grounding in Human-Computer Interaction

**Brennan (1998)**: Distinguishes computers as medium vs partner. When computers are partners, many HCI errors are grounding failures. People entrain to system vocabulary (lexical entrainment) — but the system typically doesn't entrain to theirs (asymmetric).

**Brennan & Hulteen (1995)**: Framework for context-appropriate feedback at each system state (heard → processing → understood → executing → complete). *Directly relevant to our tool-call continuity problem.*

**Critical point**: Our system's architecture is **fundamentally unidirectional**. We inject context into the system prompt, then generate. The operator has no visibility into what context was injected, no way to inspect or correct the system's "understanding." This violates Clark's bilateral requirement.

### Grounding in LLM Systems (2024-2026)

**Shaikh et al. (2025, ACL) — Rifts benchmark**: LLMs are **3× less likely to initiate clarification** and **16× less likely to provide follow-up requests** than humans. All frontier models averaged **23.23% accuracy** (worse than random at 33%). *This empirically validates our problem statement.*

**Mohapatra et al. (2024, LREC-COLING)**: First systematic annotation using Traum's grounding acts. LLMs generate language with *less* conversational grounding than humans — assuming common ground exists rather than establishing it.

**Mohapatra et al. (2024, EMNLP)**: Direct correlation between pre-training data size and grounding abilities.

**Jokinen (2024, NeusymBridge workshop)**: LLMs need grounding at two levels — factual (avoiding hallucination) and conversational (constructing shared understanding).

**ESSLLI 2024 Workshop**: "Conversational Grounding in the Age of Large Language Models" — organized by Cassell, Traum, and Mohapatra. **The problem is recognized as open and unsolved.**

**No commercial system implements Clark & Brennan grounding.** Not ChatGPT, Gemini, Alexa+, or Apple Intelligence. We are genuinely novel — and genuinely alone.

### Symbol Grounding ≠ Conversational Grounding

Harnad (1990) — symbols acquiring intrinsic meaning via sensory grounding.
Clark (1991) — interlocutors establishing mutual understanding via dialogue.

These are entirely different constructs sharing a word. Our work is about conversational grounding. We make no claims about symbol grounding. **This distinction must be explicit in all documentation.**

---

## II. Counter-Positions and Strongest Arguments Against Us

### The Steelman Against Our Approach

> "You've built an elaborate theoretical framework citing Clark & Brennan to justify what is, mechanically, a system prompt with a growing conversation summary appended to it. Every competing system also appends conversation history to the context — you just call yours a 'thread' and claim it preserves 'grounding.' Your measurement apparatus is impressive but measures surface correlates, not the theoretical constructs you invoke. Meanwhile, Mem0 actually publishes benchmark numbers. MemGPT actually manages memory actively. GAM actually solves context rot. You have a position paper and an N-of-1 experimental design with no results yet."

### Strongest Arguments FOR Profile-Retrieval

1. **Scalability**: Profile scales to 1,000 sessions (fixed-size fact store). Thread hits context window limits.
2. **Efficiency**: Mem0 achieves 91% lower latency, 90% token savings vs full-context.
3. **Task diversity**: Profile facts are reusable across arbitrary contexts. Thread is bound to the pipeline.
4. **Composability**: Profile facts shared across agents/modalities. Thread is single-pipeline.
5. **Cold start**: Profile gives informative priors immediately. Thread starts from nothing.
6. **Published benchmarks**: Mem0: 26% accuracy improvement over OpenAI memory. GAM: >90% on RULER. **We have zero benchmark numbers.**

### Relevance Theory Counter-Prediction

Sperber & Wilson's Relevance Theory: communication succeeds when utterances have high **cognitive effect** relative to **processing effort**. Profile retrieval *reduces processing effort* by pre-extracting relevant facts. Thread *increases processing effort* by forcing the model to do its own relevance filtering. **Under RT, profile retrieval may be superior.**

### Conversation Analysis Critique

A CA perspective (Schegloff) would say: "You measure grounding outcomes without implementing the interactional machinery that produces grounding. Grounding is not a score — it's an organizational achievement produced through specific sequential practices (adjacency pairs, repair organization, turn-taking). You have none of these."

### Scaling Limits

- **Context rot** (Chroma 2025): Every model degrades at every length increment. Growing thread = growing degradation.
- **Lost in the Middle** (Liu et al. 2024): 30%+ accuracy drop for mid-context content.
- **Multi-turn degradation** (Laban et al. 2025): 39% average performance drop. Errors compound; models don't recover.
- **LOCOMO** (ACL 2024): GPT-4 at F1=32.1 vs human ceiling 87.9 for 32-session conversational memory.

### Most Dangerous Competitor

**GAM (Nov 2025)** — JIT context compilation. Addresses context rot while constructing optimized context on demand. >90% on RULER where conventional approaches fail. If GAM preserves sequential conversational structure (not just fact retrieval accuracy), it undermines our argument that thread preservation is necessary.

### Our Honest Response

Our claim is narrower than it appears. We are NOT claiming:
- That thread-based anchoring is universally superior to profile retrieval
- That our system achieves Clark-compliant grounding
- That our approach scales to millions of users

We ARE claiming:
- For a single-operator voice system with sustained relational interaction, context anchoring produces qualitatively different (not necessarily "better" on benchmarks) conversational behavior than profile retrieval
- This difference is measurable via semantic coherence, acceptance patterns, and frustration trajectories
- The difference matters for the operator's subjective experience of continuity

The honest version: "We believe that keeping conversation history in context and measuring conversational quality in real-time will produce better subjective experience for a single operator than extracting facts into a database. That's a defensible engineering bet."

---

## III. SCED Methodology: Threats and Mitigations

### Critical Design Flaw: A-B-A May Be Inappropriate

The literature is explicit: **reversal designs are not warranted when the intervention entails learning.** Grounding creates persistent knowledge structures — once you establish common ground, removing the mechanism doesn't erase the knowledge. The operator learns how the system communicates; expectations shaped by B phase persist into A'.

**Barlow, Nock & Hersen (2009)** conditions where reversal is inappropriate:
- Behavior change is irreversible (comes into contact with maintaining contingencies)
- Intervention creates new skills/knowledge that cannot be "unlearned"

**Mitigation options**:
1. A-B-A-B (stronger evidence, ends on treatment, 3 phase-change demonstrations)
2. Multiple baseline across behaviors (different metrics staggered)
3. Acknowledge carryover explicitly; analyze A' as "residual of learning"
4. Pre-specify what "reversal" means operationally — full return to baseline or partial degradation

### Beta-Binomial Is Wrong for Continuous Data

Our pre-registered analysis uses beta-binomial with binarization. This is a **model misspecification error**:
- Beta-binomial is for count/proportion data bounded [0,1]
- Our metrics (turn_pair_coherence, context_anchor_success) are continuous
- Binarization at an arbitrary threshold loses information

**Correct approach**: Kruschke's BEST (Bayesian Estimation Supersedes the t-Test):
- t-distributed likelihood (robust to outliers)
- Complete posterior for effect size, means, SDs
- 95% HDI + ROPE decision rule
- Published: *J. Experimental Psychology: General* 142(2), 573-603

### Autocorrelation

Turns within sessions are serially dependent. Shadish et al. (2013): meta-analytic mean autocorrelation in SCED = 0.20 (bias-adjusted).

**Impact on our analysis**:
- Effective sample size drops by factor (1+r)/(1-r). At r=0.3, our 115 baseline turns → effective N≈62
- BF is inflated. Cycle 1's BF=3.66 may be ~2.0-2.5 corrected
- Natesan Batley & Hedges (2021): choose slope modeling over autocorrelation modeling when both can't be estimated (small N)

**Mitigation**: Use BEST on session means (aggregation removes within-session autocorrelation). For definitive analysis, hierarchical model with AR(1) residuals.

### N=1 Validity Threats

| Threat | Severity | Mitigation |
|--------|----------|-----------|
| History (concurrent events) | **High** | Behavioral covariates (word count, time of day). Cannot fully control. |
| Maturation (operator learning) | **High** | A' reversal tests this. If A' ≈ B, maturation confounds. |
| Testing/Reactivity | **Medium** | Open-label by necessity. Lockdown mode freezes non-experiment variables. |
| Instrumentation drift | **Medium** | Embedding model is fixed. Word overlap → embedding is a one-time change documented as deviation. |
| External validity | **Zero** | N=1, no replication path for this specific operator-system pair. Generalization through conceptual replication only. |

**What WWC standards require** (Kratochwill et al. 2010/2021):
- ≥5 data points per phase: **Yes** (10-20 sessions)
- ≥3 demonstrations of effect: **A-B-A gives 2; A-B-A-B gives 3**
- Systematic IV manipulation: **Yes** (feature flags)
- Established inter-rater reliability: **Questionable** (LLM-based measurement)

### Power Analysis

At expected effect size d=0.3-0.6, with 20 sessions per phase:

| BF Outcome | Probability | Implication |
|------------|------------|-------------|
| BF > 10 (decisive H1) | 40-50% | Effect detected |
| 3 < BF < 10 (moderate) | 25-35% | Most likely outcome |
| BF < 3 (inconclusive) | 15-25% | Need more sessions |
| BF < 1/10 (decisive H0) | 5-10% | Intervention doesn't work |

**We are underpowered for medium effects.** This is honest. Pre-commit to extending if inconclusive.

### Effect Size Measures

| Measure | Appropriate? | Notes |
|---------|-------------|-------|
| NAP (Parker & Vannest 2009) | Moderate | Outlier-resistant but assumes independence |
| Tau-U (Parker et al. 2011) | **No** | Values inflated, unacceptable Type I error (Tarlow 2017) |
| BCTau (Tarlow 2017) | **Yes** | Theil-Sen trend correction, bounded [-1,1] |
| Hedges-Pustejovsky-Shadish d | For meta-analysis | Requires ≥3 cases |
| BEST (Kruschke) | **Yes** | Correct for continuous data, Bayesian |

---

## IV. Emergence and Gestalt: Formal Framework

### Wimsatt's Aggregativity Conditions (The Operational Test)

A property is *merely aggregative* (non-emergent) if ALL four hold:

1. **InterSubstitution (IS)**: Invariant under part rearrangement
2. **Size Scaling (QS)**: Scales qualitatively similarly under part addition
3. **Decomposition-Recomposition (DR)**: Invariant under disassembly/reassembly
4. **Linearity (CI)**: No cooperative or inhibitory interactions

**Any failure = some form of emergence.**

For our system:
- **IS**: Reorder thread, memory, directive, and effort signals in the prompt. Does output change? Almost certainly yes → IS fails → emergence.
- **QS**: Add a 5th component. Does quality scale linearly? Unknown.
- **DR**: Split package, measure parts, recombine. Does recombined = original? Requires ablation data.
- **CI**: Measure each alone, then together. Sum ≠ combination? Requires ablation data.

**We can test IS immediately. DR and CI require the dismantling phase (Cycle 3+).**

### Kohler's Correction

"The whole is *different* from the sum of its parts." Not greater — **different**. The question is not whether the treatment components produce "more grounding" than one, but whether they produce a *qualitatively different kind* of grounding.

### Formal Tools for Testing

| Tool | What It Tests | Feasibility |
|------|-------------|-------------|
| Wimsatt IS | Does component order matter? | Test now |
| Shapley values | Fair attribution across all 2^4=16 subsets | Feasible in Cycle 3 |
| Partial Information Decomposition | Synergistic information between components | Requires sufficient data |
| Bliss Independence | Pharmacological null model for no interaction | Adaptable if we define "dose" |
| Chou-Talalay CI | Synergy index (CI<1 = synergy) | Adaptable |
| Percolation threshold | Is there a critical component count? | Plot quality vs N_components |

### Threshold vs Linear

If grounding quality shows a sharp inflection between 2-3 or 3-4 components, this suggests a **percolation-like threshold** — a phase transition from fragmentary to comprehensive grounding. If the curve is linear, effects are additive and there is no gestalt.

**Catastrophe theory** (cusp model): grounding quality might exhibit a discontinuous jump. The transition point could depend on both component count AND coherence/integration quality. Hysteresis would mean the threshold differs depending on whether you're adding or removing components.

### Falsifying the Gestalt Hypothesis

The gestalt is DISPROVEN if:
1. Ablation shows perfect additivity (each component contributes exactly 1/4)
2. Wimsatt's all 4 conditions hold
3. PID shows zero synergistic information
4. Bliss independence holds for all pairs
5. Shapley interaction indices are all zero
6. Component reordering has no effect

---

## V. Predictions and Decision Tree

### Expected Effect Sizes

From grounding research literature:
- Clark & Wilkes-Gibbs (1986): d > 2.5 for fixed-referent convergence
- Transfer to open-domain voice: **10-20% of benchmark effect**
- Dialogue-based intervention meta-analysis: d = 0.44-0.53
- **Our prediction: d = 0.3-0.6, or +0.06 to +0.12 on turn_pair_coherence**

Cycle 1 pilot found +0.029 on word overlap (known-poor metric). Embedding coherence should capture more of the true effect.

### The Complete Decision Tree

```
CYCLE 2 (full treatment package, ABA):

A→B transition:
├── BF > 10 for H1 → EFFECT DETECTED
│   └── B→A' reversal:
│       ├── Score drops → CAUSAL (thread causes anchoring)
│       ├── Score unchanged → CONFOUNDED
│       │   ├── Check behavioral covariates for drift
│       │   └── Interpret as operator learning, not thread effect
│       └── Score drops partially → PARTIAL CAUSAL + LEARNING
│           └── Report both interpretations
│
├── 3 < BF < 10 → MODERATE EVIDENCE
│   └── Extend to 20+ sessions OR add B' phase (ABAB)
│
├── BF < 3 → INCONCLUSIVE
│   └── Effect may be real but undetectable at this N
│   └── Options: more sessions, revised metric, or accept null
│
└── BF < 1/10 → NO EFFECT
    └── Redesign intervention
    └── Consider: was the metric wrong? Was implementation correct?

SUPPLEMENTARY ANALYSES:
├── Quantile comparison (90th percentile B vs A)
│   ├── Peak experiences enabled → RAISES CEILING
│   ├── Mean shifts but peaks unchanged → RAISES FLOOR
│   └── Distribution shape changes → QUALITATIVE SHIFT
│
├── Trajectory analysis (within-session slopes)
│   ├── B slopes positive, A slopes negative → ACCUMULATION WORKS
│   └── Both flat → No within-session improvement
│
└── Behavioral covariates
    ├── user_word_count drift → Operator changed behavior
    ├── assistant_word_count drift → System changed behavior
    └── No drift → Cleaner causal inference

CYCLE 3 (dismantling, if Cycle 2 shows effect):
├── Full package > thread alone → INTERACTIONS PRESENT
├── Full package = thread alone → THREAD SUFFICIENT
├── Thread alone = baseline → THREAD NOT ACTIVE INGREDIENT
└── All components equal → ADDITIVITY (no gestalt)
```

### What Would Disprove Our Model

| Evidence | Interpretation |
|----------|---------------|
| Phase B mean ≤ Phase A (BF > 10 for H0) | Thread doesn't help |
| No reversal in A' | Carryover/learning, not thread |
| Behavioral covariate drift > effect | Operator, not system, changed |
| Reference accuracy drops below 0.90 in B | Thread introduces confabulation |
| Negative trajectory in B (grounding worsens) | Thread actively harms grounding |
| Embedding coherence as insensitive as word overlap | Metric is wrong, not intervention |

---

## VI. Field Position

### What Exists (Our Competition)

| System | Architecture | Grounding? | Benchmark |
|--------|-------------|-----------|-----------|
| ChatGPT Memory | Fact extraction → prompt injection | No (profile retrieval) | None published; 83% memory failure in Feb 2025 wipe |
| Gemini | Rule-gated context from Google services | No (profile retrieval) | None; prompt injection vulnerabilities |
| Mem0 | Dedicated memory modules + optional graph | No | 26% over OpenAI; 91% lower latency |
| MemGPT/Letta | OS-inspired self-editing memory | No (closer to active management) | Multi-document QA improvements |
| GAM | Dual-agent JIT context compilation | No | >90% RULER |
| Generative Agents | Memory stream + reflection + planning | No (reflection is closest) | Qualitative (Smallville simulation) |
| A-Mem | Zettelkasten-inspired knowledge network | No | Superior across 6 foundation models |
| **Hapax** | Thread-based context anchoring + grounding measurement | **Attempting** | N-of-1 SCED (pending) |

**We are the only system attempting Clark-compliant grounding.** We are also the only system honestly measuring where we fall short.

### What No One Has

1. Real-time grounding measurement during conversation (our evaluator)
2. Acceptance classification feeding back into context
3. Frustration detection as primary research metric
4. Theoretical framework explicitly mapping design to Clark/Traum
5. Pre-registered hypothesis testing of grounding mechanisms
6. Open lab journal with transparent methodology evolution

### Our Genuine Contribution

Even if our intervention shows null results, we contribute:
- **Traum mapping**: First system to map implementation to computational grounding acts
- **Measurement apparatus**: Grounding evaluator, acceptance classifier, frustration detector
- **Counter-positioning**: Documented failure modes of profile-retrieval (Gemini leak, ChatGPT wipe)
- **Methodology**: Bayesian SCED applied to conversational AI (novel combination)
- **Transparency**: Open lab journal with deviation disclosure

---

## VII. Publication Integration

### Lab Journal Structure

Categories: `data`, `theory`, `methodology`, `decision`, `deviation`, `preregistration`

### Weekly Cadence

| Day | Activity | Entry Type |
|-----|----------|-----------|
| Monday | Data review, run analysis | Data entry |
| Wednesday | Conceptual/theoretical work | Theory memo |
| Friday | Week synthesis, decisions | Decision record |

### Initial Backfill (publish before Cycle 2)

1. **Position paper** (theory) — counter-positioning against profile-retrieval
2. **Theoretical foundations** (theory) — this document
3. **Package assessment** (theory) — 3+1 component analysis
4. **Baseline analysis** (data) — 17 sessions, 8 patterns
5. **Cycle 1 pilot** (data) — honest methodology critique
6. **Cycle 2 pre-registration** (preregistration) — frozen at commit SHA
7. **Deviation disclosure** (deviation) — Cycle 1→2 changes per Willroth & Atherton (2024) table

### Deviation Disclosure Table (Cycle 1 → Cycle 2)

| # | Original Plan | Change | Type | Reason | Timing | Impact |
|---|--------------|--------|------|--------|--------|--------|
| 1 | Word overlap metric | Embedding coherence (turn_pair_coherence) | Metric change | Word overlap penalizes abstraction, paraphrasing — qualitative effects invisible | Post-Cycle 1 analysis | Higher sensitivity to true grounding effects |
| 2 | Beta-binomial BF | Kruschke's BEST on session means | Analysis change | Beta-binomial wrong for continuous data; autocorrelation invalidates turn-level independence | Literature review | Correct model specification; wider posteriors |
| 3 | 4-component package | 3+1 (3 treatment + 1 diagnostic) | Framing change | Sentinel tests retrieval not grounding; including it as treatment threatens construct validity | Package assessment | Cleaner construct validity |
| 4 | ROPE [-0.05, 0.05] on continuous | HDI+ROPE on session means | Decision rule change | Original ROPE applied to binarized proportion; mismatched with continuous metric | Methodology review | Correct statistical decision framework |
| 5 | No code freeze | TRUE code freeze with lockdown mode | Protocol change | Cycle 1 had word limit change mid-baseline (confound) | Protocol review | Eliminates code-change confounds |
| 6 | Thread cap 15 | Thread cap 10 (variable length) | Parameter change | Lost in the Middle research; entries 4-12 in attention dead zone at 15 | Compression research | Higher signal-to-noise in thread |

---

## VIII. Key Citations

### Core Theory
- Clark & Brennan (1991). Grounding in communication. APA.
- Clark & Schaefer (1989). Contributing to discourse. Cognitive Science 13, 259-294.
- Clark & Wilkes-Gibbs (1986). Referring as a collaborative process. Cognition 22, 1-39.
- Clark (1996). Using Language. Cambridge University Press.
- Traum (1994). A computational theory of grounding. PhD, Rochester.
- Traum (1999). Computational models of grounding. AAAI Fall Symposium.
- Brennan & Clark (1996). Conceptual pacts. JEPLMC 22, 1482-1493.
- Brennan & Hanna (2009). Partner-specific adaptation. Topics in Cog Sci 1, 274-291.
- Brennan (1998). The grounding problem in conversations with computers. Erlbaum.

### Counter-Positions
- Pickering & Garrod (2004). Toward a mechanistic psychology of dialogue. BBS 27, 169-190.
- Healey et al. (2018). Running repairs. Topics in Cog Sci 10, 367-388.
- Mills (2014). Complementarity, convergence, conventionalization. New Ideas in Psych 32.
- Koschmann & LeBaron (2003). Reconsidering common ground. ECSCW 2003.

### LLM Grounding (2024-2026)
- Shaikh et al. (2025). Navigating rifts in human-LLM grounding. ACL 2025.
- Mohapatra et al. (2024). Grounding acts annotation. LREC-COLING 2024.
- Mohapatra et al. (2024). LLM effectiveness in grounding. EMNLP 2024.
- Jokinen (2024). Need for grounding in LLM dialogue. NeusymBridge.
- Laban et al. (2025). LLMs get lost in multi-turn conversation. arXiv 2505.06120.

### Memory Architectures
- Mem0 (2025). arXiv 2504.19413.
- MemGPT/Letta (2023). arXiv 2310.08560.
- GAM (2025). arXiv 2511.18423.
- Park et al. (2023). Generative Agents. UIST/arXiv 2304.03442.
- A-Mem (2025). arXiv 2502.12110.
- Maharana et al. (2024). LOCOMO benchmark. ACL 2024.

### Context Engineering
- Anthropic (2025). Effective context engineering for AI agents.
- Chroma (2025). Context rot research.
- Liu et al. (2024). Lost in the middle. TACL/arXiv 2307.03172.

### SCED Methodology
- Kazdin (2011). Single-Case Research Designs. Oxford.
- Ward-Horner & Sturmey (2010). Component analyses. JABA 43(4).
- Riden et al. (2022). Nature and extent of component analyses. Behavior Modification.
- Kratochwill et al. (2010/2021). WWC SCD standards.
- Shadish et al. (2013). Bayesian autocorrelation estimates. Behavior Research Methods.
- Kruschke (2013). BEST. J Exp Psych: General 142(2).
- Tarlow (2017). Baseline Corrected Tau. Behavior Modification 41(4).
- Collins et al. (2005). MOST framework.
- Willroth & Atherton (2024). Preregistration deviation disclosure. Advances in Methods.
- Johnson & Cook (2019). Preregistration in SCD. Exceptional Children.

### Emergence/Gestalt
- Bedau (1997). Weak emergence.
- Chalmers (2006). Strong and weak emergence.
- Wimsatt (1997/2000). Emergence as non-aggregativity.
- Hoel. Causal emergence and effective information.
- Williams & Beer (2010). Partial Information Decomposition.
- Chou & Talalay. Combination index. Cancer Research 70(2).
