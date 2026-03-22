# Self-Improving Deliberative Processes: Research Synthesis

**Date:** 2026-03-12
**Purpose:** Research foundations for post-run evaluation and adjustment in LLM agent deliberation on constitutional tensions.

---

## 1. Reflexive Governance / Reflexive Law

### What they evaluate

Reflexive law (Teubner) does not evaluate substantive outcomes directly. Instead it evaluates **whether a system's internal procedures produce adequate self-observation and self-regulation regarding its external effects**. The unit of analysis is the coupling between autonomous subsystems — not the content of their decisions, but whether their decision-making structures are capable of registering and responding to perturbations from other systems.

Julia Black extends this into "really responsive regulation," where the regulator evaluates five dimensions: the firm/system's own operating framework, the regulatory regime's logic, institutional context, interactions between regulatory tools, and changes in each over time. The focus shifts from "did the right outcome occur" to "is the regulatory conversation iterating productively."

Oren Perez introduces the problem of **higher-order reflexivity** — the regulator must not only be reflexive about the regulated system but reflexive about its own reflexivity. He identifies a deep tension: reflexive regulation claims epistemic modesty (we can't know the right outcome in advance) while simultaneously requiring sophisticated epistemic capacity to design and evaluate its own procedures.

### What criteria they use

- **Structural coupling adequacy**: Are the system's internal procedures producing communications that other subsystems can register? (Teubner)
- **Procedural rationality**: Not whether the outcome is correct, but whether the process that produced it was structured to surface relevant considerations (Teubner)
- **Responsiveness**: Is the regulatory conversation actually iterating, or has it collapsed into ritual compliance? (Black)
- **Second-order reflexivity**: Can the system evaluate whether its evaluation criteria are themselves adequate? (Perez)

### How evaluation translates to adjustment

Teubner's model works by **restructuring internal discourse procedures** rather than commanding different outcomes. The feedback loop is: observe external effects -> evaluate whether internal procedures adequately registered those effects -> modify procedures (not outcomes). This is explicitly procedural, not substantive.

Black's responsive regulation adds graduated escalation: start with persuasion/dialogue, escalate to more interventionist tools only when lighter approaches demonstrably fail. Evaluation of failure at one level triggers movement up the enforcement pyramid.

### Constraints on self-modification

- **Autopoietic closure**: A system can only modify itself using its own internal logic. External commands that don't translate into the system's internal language will be ignored or distorted. This is a feature, not a bug — it prevents destabilizing external interference.
- **Procedural, not substantive**: Self-modification is constrained to procedures. The system cannot directly rewrite its values/axioms through reflexive adjustment — it can only restructure how those values are processed.
- **Perez's paradox**: The more reflexive a system becomes about its own procedures, the more epistemic capacity it needs, creating potential infinite regress. Some procedural elements must remain fixed as anchors.

### Relevance to LLM deliberation

The key insight is the **separation of outcome evaluation from procedural adjustment**. A constitutional deliberation system should not adjust its axioms based on outcome evaluation — it should adjust how axioms are surfaced, weighted, and traded off. Perez's paradox is directly relevant: the meta-evaluation layer needs fixed criteria it does not itself modify, or you get infinite regress.

---

## 2. Deliberative Systems Theory — The Systemic Turn

### What they evaluate

Mansbridge, Parkinson, and Dryzek (2012) shifted evaluation from individual deliberative forums to **the deliberative system as a whole**. The system includes formal institutions, informal talk, media, activism, and everyday political conversation. No single site needs to be perfectly deliberative; the system as a whole must perform certain functions.

The Discourse Quality Index (DQI), developed by Steenbergen et al. (2003), operationalizes measurement at the forum level with indicators grounded in Habermasian discourse ethics.

### What criteria they use

**System-level functions (Mansbridge et al.):**
- **Epistemic function**: Do the system's outputs reflect adequate consideration of relevant facts, logic, and reasons?
- **Ethical function**: Does the system promote mutual respect among participants?
- **Democratic function**: Is the process inclusive and egalitarian?

**Forum-level indicators (DQI):**
- **Participation equality**: Measured via interruptions that prevent expression
- **Level of justification**: Syntactic structure of argument — are claims supported by complete justifications accessible to rational critique?
- **Content of justification**: Are arguments oriented toward the common good vs. narrow self-interest?
- **Respect**: Toward groups, toward counterarguments, toward demands
- **Constructive politics**: Mediating proposals, consensus-seeking behavior

**The critical distinction**: A single deliberation can score poorly on DQI indicators while the system-level functions remain healthy (e.g., a heated parliamentary debate that surfaces tensions later resolved elsewhere). Conversely, a polite forum can score well on DQI while the system fails epistemically (groupthink).

### How evaluation translates to adjustment

The systemic approach identifies **functional gaps**: the system is evaluated against its three functions, and deficiencies point to specific structural remedies. If the epistemic function is failing, the adjustment targets information flow. If the democratic function is failing, the adjustment targets inclusion mechanisms.

This is diagnostic rather than prescriptive — the framework identifies what is broken but does not mandate a specific fix.

### Constraints on self-modification

- **Division of labor**: Not every component of the deliberative system needs to perform every function. Some components can be partisan, some can be technocratic, as long as the system as a whole covers all functions. This constrains over-optimization of individual components.
- **Systemic coupling**: Adjusting one component can degrade another. The framework requires evaluating system-wide effects of local adjustments.
- **Temporal dimension**: A single deliberation is not a full evaluation cycle. The system must be evaluated over time, across multiple deliberative episodes.

### Relevance to LLM deliberation

Map directly: each deliberation run is a forum; the series of runs is the system. Evaluate individual runs on DQI-like indicators (justification quality, consideration breadth, respect for all axioms). Evaluate the system over time on the three functions. This two-level structure prevents over-fitting adjustments to a single bad run.

---

## 3. Process Tracing in Deliberation Research

### What they evaluate

Process tracing asks: **did the deliberative process actually cause the outcome, or was the outcome predetermined?** This is the core question for detecting pseudo-deliberations where the conclusion was reached before or independent of the deliberative process.

### What criteria they use

Four diagnostic tests (Beach & Pedersen, adapted from Van Evera):

1. **Straw-in-the-wind**: Evidence consistent with the causal claim but not conclusive. Passing provides some support; failing does not eliminate.
2. **Hoop test**: Establishes necessary criteria. If a causal explanation cannot pass this test, it is eliminated. (E.g., if no participant changed their position during deliberation, the claim that deliberation caused the outcome fails the hoop test.)
3. **Smoking gun**: Sufficient but not necessary. Strong evidence that the mechanism operated. (E.g., direct evidence that a specific argument introduced during deliberation was the pivotal reason for the outcome.)
4. **Doubly decisive**: Both necessary and sufficient. Extremely rare in practice.

Applied to deliberation specifically:
- **Temporal sequencing**: Did opinion change occur after exposure to deliberative arguments, not before?
- **Mechanism identification**: Can you trace the specific argumentative pathway from input to outcome?
- **Counterfactual**: Would the outcome have been different without the deliberative process? Comparison groups help isolate deliberation's effect from mere information exposure.

### How evaluation translates to adjustment

Process tracing is diagnostic — it identifies whether deliberation is actually doing work. If a system repeatedly fails hoop tests (participants never change positions), the adjustment is structural: change the framing, participant selection, information inputs, or argument format.

Research shows key mechanism: participants soften strongly held views and encounter different perspectives during genuine deliberation. If this softening is absent, the process is likely performative.

### Constraints on self-modification

- Process tracing is post-hoc and case-specific. It cannot generate universal rules, only case-level diagnoses.
- Multiple independent variables are manipulated simultaneously in deliberation (information, discussion format, group composition), making clean attribution difficult.
- The method requires preserving rich process data, not just outcomes.

### Relevance to LLM deliberation

This is the **pseudo-deliberation detector**. For each run, apply hoop tests:
- Did any agent's position shift during deliberation? (If not: likely pseudo-deliberation.)
- Can you trace a specific argument from one agent to a change in another's reasoning? (Smoking gun for genuine deliberation.)
- Compare the outcome to what a simple axiom-priority ranking would have produced without deliberation. If identical, deliberation added nothing.

The LLM system has a massive advantage here: full process traces are automatically available. Every intermediate state is logged. Human deliberation researchers would kill for this.

---

## 4. Adaptive Management / Double-Loop Learning

### What they evaluate

Argyris and Schon distinguish:
- **Single-loop learning**: Detect error, adjust action strategy, keep goals/values/norms unchanged. "The thermostat model."
- **Double-loop learning**: Detect error, question and potentially modify the governing variables (values, norms, goals, assumptions) that produced the action strategy.
- **Deutero-learning** (Bateson, extended by Argyris): Learning how to learn — improving the learning process itself.

In adaptive management (natural resource context), this maps to:
- **Technical learning phase**: Iterative cycle of action, monitoring, evaluation, adjustment within a fixed problem frame.
- **Institutional learning phase**: Periodically interrupting the technical cycle to reconsider objectives, alternatives, stakeholder engagement, and the deliberative frame itself.

### What criteria they use

The key diagnostic: **Is the system repeatedly encountering the same class of error?** If yes, single-loop learning is insufficient — the governing variables need examination.

Argyris identifies "Model I" behavior (unilateral control, self-protection, win/lose framing) as the default that prevents double-loop learning. "Model II" (valid information, free choice, internal commitment) enables it.

For adaptive management:
- Are management objectives still aligned with stakeholder values?
- Are the predictive models still adequate?
- Are the monitoring protocols capturing what matters?
- Has the problem itself changed?

### How evaluation translates to adjustment

**Single-loop**: Outcome deviates from expectation -> adjust parameters (e.g., change the weighting of an input, modify a threshold, alter the sequence of deliberative steps).

**Double-loop**: Outcome repeatedly deviates despite parameter adjustment -> question the governing variables:
- Are we deliberating about the right question?
- Are the axioms we're balancing the right axioms?
- Is the framing of the tension correct?
- Are the agents representing the right perspectives?

**The deliberative phase / institutional learning phase** structure from adaptive management provides the clearest template: run multiple technical cycles, then periodically pause for a meta-cycle that examines the frame.

### Constraints on self-modification

- **Double-loop learning is threatening**: Argyris emphasizes that questioning governing variables triggers defensive routines. In an LLM system, the analog is that changing the constitutional axioms undermines the stability that makes deliberation meaningful.
- **Not all errors warrant double-loop response**: The system needs criteria for when to escalate from parameter adjustment to frame questioning. Over-eager double-looping destabilizes; under-eager single-looping ossifies.
- **Deutero-learning requires stability at the meta-level**: The process for evaluating whether to do single or double loop learning must itself be relatively stable, or you get infinite regress (same as Perez's paradox).

### Relevance to LLM deliberation

This provides the **escalation logic**:
1. After each run: single-loop evaluation. Did the deliberation produce a well-reasoned resolution? If not, adjust parameters (prompt structure, argument ordering, evidence weighting).
2. After N runs or persistent failure patterns: double-loop evaluation. Are the axioms correctly specified? Is the tension framed correctly? Are the agent roles appropriate?
3. The meta-evaluation criteria (when to escalate) should be constitutionally fixed — not subject to the same adjustment process.

---

## 5. Algorithmic Fairness Auditing

### What they evaluate

Post-hoc evaluation of automated decision systems for systematic bias, using the system's own outputs as evidence.

### What criteria they use

**Statistical parity metrics:**
- **Disparate Impact Ratio**: Rate of favorable outcomes for protected group / rate for reference group. Below 0.8 typically flags concern.
- **Equal Opportunity**: Equal true positive rates across groups.
- **Equalized Odds**: Equal true positive AND false positive rates.
- **Calibration**: Among those assigned a given risk score, actual outcomes should be similar across groups.

**Causal / counterfactual metrics:**
- **Counterfactual fairness**: Would the decision have been the same if the protected attribute were different, all else equal?
- **Peer-induced fairness**: Compare outcomes for individuals who are similar on all relevant dimensions except protected class.

**Key impossibility result** (Chouldechova 2017, Kleinberg et al. 2016): You cannot simultaneously satisfy calibration, equal false positive rates, and equal false negative rates when base rates differ across groups. This means **the choice of fairness criteria is itself a normative decision**, not a technical one.

### How evaluation translates to adjustment

1. Compute fairness metrics on system outputs.
2. If metrics reveal disparities beyond thresholds, diagnose source: training data, feature selection, model architecture, or threshold setting.
3. Apply targeted interventions: re-weighting, constraint optimization, post-processing calibration.
4. Re-evaluate.

The feedback loop is: **output audit -> disparity diagnosis -> targeted adjustment -> re-audit**.

### Constraints on self-modification

- **Impossibility results constrain optimization**: You cannot optimize all fairness criteria simultaneously. The system must have fixed normative commitments about which criteria take priority.
- **Infinite regress in AI-auditing-AI**: If the auditing system is itself algorithmic, who audits the auditor? At some point, human judgment must anchor the process.
- **Transparency requirement**: Self-modification must be auditable. Black-box self-adjustment undermines the purpose of the audit.
- **Domain sensitivity**: Fairness criteria that are appropriate in one context may be inappropriate in another. The system cannot learn universal fairness rules.

### Relevance to LLM deliberation

Transferable patterns:
- **Axiom-parity testing**: Analog of disparate impact. Over a series of runs, does any axiom systematically lose in tension resolution? If one axiom is always subordinated, the process may have structural bias.
- **Counterfactual analysis**: Re-run the deliberation with the axiom ordering/framing changed. If the outcome always follows presentation order, the process is not genuinely deliberative.
- **Calibration across tension types**: Are similar tensions being resolved consistently? Inconsistency may indicate sensitivity to irrelevant features.
- **The impossibility result transfers**: You cannot simultaneously optimize for all constitutional values. The system needs fixed meta-norms about which trade-offs are acceptable, and these meta-norms are not derivable from the audit process itself.

---

## 6. Quality Assurance in Structured Analytic Techniques

### What they evaluate

Intelligence community evaluation of whether structured techniques (ACH, red teaming, devil's advocacy, scenario planning) actually improve analysis quality versus adding process overhead.

### What criteria they use

- **Accuracy**: Did the technique produce more accurate predictions/assessments than unstructured analysis?
- **Bias reduction**: Did it reduce specific cognitive biases (confirmation bias, anchoring, availability)?
- **Calibration**: Are analysts appropriately confident — not overconfident or underconfident?
- **Value-added over base rate**: Did the technique outperform simple reference class forecasting or historical base rates?

### Key empirical findings

**Mixed results** (Chang, Berdini, Mandel & Tetlock 2018):
- Devil's advocacy outperformed consensus methods in ~70% of cases.
- ACH reduced confirmation bias only in non-analysts (people without intelligence backgrounds). For experienced analysts, it had null or even negative effects.
- SATs apply a "one-size-fits-all-biases" approach, but bias susceptibility varies by situation, evidentiary quality, and analyst experience.
- Some techniques create **new distortions** while mitigating old ones (e.g., ACH's matrix format can artificially flatten evidence quality differences).

**Dhami, Mandel, Mellers & Tetlock (2015)**: Decision science methods (calibration training, reference class forecasting, structured comparison) outperform traditional intelligence SATs. The IC should import methods with stronger empirical grounding rather than relying on techniques adopted primarily for institutional/political reasons (post-9/11 reform pressure).

**The fundamental evaluation challenge**: Techniques adopted for political reasons (demonstrating that analysis was "rigorous") resist evaluation because their purpose is partly performative. Evaluating whether they "work" requires distinguishing analytic value from institutional legitimacy value.

### How evaluation translates to adjustment

The IC model is largely **centralized and periodic**: techniques are reviewed, sometimes restructured, through institutional processes (e.g., establishment of the Office of Analytic Integrity). But:
- Feedback from evaluation to practice is slow and often blocked by institutional inertia.
- Techniques with political backing persist even when empirical evidence is weak.
- The evaluation itself is politically sensitive (challenging mandated techniques is career-risky).

Tetlock's recommendation: shift from technique-centric to **outcome-centric** evaluation. Track forecasting accuracy over time, use proper scoring rules, and let techniques compete on results.

### Constraints on self-modification

- **Institutional lock-in**: Once a technique is mandated (by legislation, executive order, or organizational policy), removing it requires overcoming significant political barriers even if evaluation shows it is ineffective.
- **Performative function**: If a technique's primary value is legitimacy rather than accuracy, effectiveness evaluation is orthogonal to its actual purpose.
- **Evaluation burden**: Rigorous evaluation of analytic techniques requires controlled experiments, which are expensive and politically difficult in intelligence contexts.

### Relevance to LLM deliberation

Critical warnings:
- **Process overhead detection**: Not every deliberative step adds value. The system should track whether each procedural element (e.g., mandatory devil's advocacy, explicit axiom-ranking) actually changes outcomes vs. merely adding cost.
- **Technique-specific evaluation**: Don't evaluate "deliberation" as a monolith. Evaluate each component: Does the tension-identification step surface genuine tensions? Does the counter-argument step produce arguments that influence the resolution? Does the synthesis step integrate inputs or just pick a winner?
- **Avoid the IC's mistake**: Don't adopt process steps for legitimacy reasons and then fail to evaluate them. The LLM system has the advantage of cheap evaluation — use it.
- **Context sensitivity**: A technique that works for one class of constitutional tension may fail for another. Track effectiveness by tension type, not globally.

---

## Cross-Cutting Synthesis: Design Implications

### The three-level evaluation architecture

Every framework reviewed converges on a similar structure:

| Level | What is evaluated | Adjustment scope | Stability requirement |
|-------|------------------|------------------|-----------------------|
| **Run-level** (single-loop) | Individual deliberation quality — DQI indicators, process tracing hoop tests, axiom-parity metrics | Parameters: prompt structure, argument ordering, evidence weighting, deliberation duration | Governing variables fixed |
| **Series-level** (double-loop) | Patterns across runs — persistent axiom subordination, recurring pseudo-deliberation, systematic inconsistency | Governing variables: tension framing, agent roles, axiom specifications, deliberative structure | Meta-evaluation criteria fixed |
| **Constitutional-level** (deutero/meta) | Whether the evaluation and adjustment process itself is working | Evaluation criteria, escalation thresholds, the scope of what is adjustable | Fixed by design; changed only by explicit constitutional amendment, not by the process itself |

### Five principles for self-improving deliberation

1. **Separate outcome evaluation from procedural adjustment** (Teubner, Black). Never adjust axioms based on whether you liked the outcome. Adjust procedures based on whether the process exhibited deliberative quality.

2. **Evaluate the system, not just the forum** (Mansbridge et al.). A single bad run is not evidence of system failure. Track the three functions (epistemic, ethical, democratic) across runs over time.

3. **Detect pseudo-deliberation actively** (process tracing). Apply hoop tests every run: Did positions shift? Can you trace argument influence? Does the outcome differ from a naive priority ranking? If all fail, the deliberation is performative.

4. **Escalate adjustment scope deliberately** (Argyris & Schon). Single-loop first, double-loop only when single-loop repeatedly fails on the same class of problem. Never adjust governing variables and parameters simultaneously.

5. **Fix the meta-level** (Perez's paradox, impossibility results, deutero-learning). The criteria for evaluating evaluation must not be subject to the same adjustment process. Some things must be constitutionally anchored: which axioms exist, what counts as a well-formed tension, when double-loop escalation is warranted. These change only through explicit amendment, not through the self-improvement loop.

### The LLM advantage

Unlike human deliberative systems, an LLM constitutional deliberation system can:
- **Preserve complete process traces** automatically (process tracing becomes trivial)
- **Run counterfactuals cheaply** (re-run with altered conditions to test causal claims)
- **Compute parity metrics over axioms** across runs (algorithmic fairness auditing at scale)
- **Evaluate every procedural element** for value-added (no political cost to removing ineffective steps)
- **Iterate rapidly** (what takes human institutions decades takes the system hours)

The constraint is the same as in every framework reviewed: **the meta-level cannot improve itself without fixed anchors, or the system becomes unmoored**. The constitution — the axioms, the definition of a well-formed tension, the criteria for genuine deliberation — must be the thing the system serves, not the thing it optimizes.

---

## Sources

### Reflexive Governance / Reflexive Law
- [Teubner — Substantive and Reflexive Elements in Modern Law (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=896509)
- [Reflexive Law as Legal Paradigm for Sustainable Development (Buffalo)](https://digitalcommons.law.buffalo.edu/cgi/viewcontent.cgi?article=1135&context=belj)
- [Black — Critical Reflections on Regulation (LSE)](https://eprints.lse.ac.uk/35985/1/Disspaper4-1.pdf)
- [Black & Baldwin — Really Responsive Risk-Based Regulation (LSE)](https://eprints.lse.ac.uk/27632/1/__lse.ac.uk_storage_LIBRARY_Secondary_libfile_shared_repository_Content_Black,%20J_Really%20responsive%20risk-based%20regulation_Black_Really%20responsive%20risk-based%20regulation_2014.pdf)
- [Perez — Courage, Regulatory Responsibility, and Higher-Order Reflexivity (Wiley)](https://onlinelibrary.wiley.com/doi/abs/10.1111/rego.12038)
- [Perez — Responsive Regulation and Second-Order Reflexivity (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1970707)

### Deliberative Systems Theory
- [Mansbridge & Parkinson — Deliberative Systems (Cambridge)](https://www.cambridge.org/core/books/deliberative-systems/E4CB073306429F1A5B849FB31211B332)
- [Mansbridge et al. — A Systemic Approach to Deliberative Democracy (Cambridge excerpt)](https://assets.cambridge.org/97811070/25394/excerpt/9781107025394_excerpt.pdf)
- [Steenbergen et al. — Measuring Political Deliberation: A Discourse Quality Index (Springer)](https://link.springer.com/article/10.1057/palgrave.cep.6110002)
- [DQI chapter in Research Methods in Deliberative Democracy (Oxford)](https://academic.oup.com/book/44646/chapter/378695331)
- [Fourth Generation of Deliberative Democracy — editorial (Taylor & Francis)](https://www.tandfonline.com/doi/full/10.1080/19460171.2016.1175956)

### Process Tracing in Deliberation
- [Process Tracing chapter in Research Methods in Deliberative Democracy (Oxford)](https://academic.oup.com/book/44646/chapter/378696459)
- [Collier — Understanding Process Tracing (Berkeley)](https://polisci.berkeley.edu/sites/default/files/people/u3827/Understanding%20Process%20Tracing.pdf)
- [How Deliberation Affects Policy Opinions (Cambridge APSR)](https://www.cambridge.org/core/journals/american-political-science-review/article/abs/how-deliberation-affects-policy-opinions/60BBEAE885EB4EF99D81913375176743)
- [Change for the Better? — Mechanisms of Deliberative Opinion Change (OSU)](https://polisci.osu.edu/sites/polisci.osu.edu/files/_change%20for%20the%20better_%20linking%20the%20mechanisms%20of%20deliberative%20opinion%20change%20to%20normative%20theory_.pdf)
- [O'Malley, Farrell, Suiter — Does Talking Matter? (SAGE)](https://journals.sagepub.com/doi/abs/10.1177/0192512118824459)

### Double-Loop Learning / Adaptive Management
- [Double-Loop Learning in Adaptive Management (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC6244979/)
- [Argyris — Double Loop Learning in Organizations (HBR, 1977)](https://www.avannistelrooij.nl/wp/wp-content/uploads/2017/11/Argyris-1977-Double-Loop-Learning-in-Organisations-HBR.pdf)
- [Chris Argyris: Theories of Action, Double-Loop Learning (infed.org)](https://infed.org/dir/welcome/chris-argyris-theories-of-action-double-loop-learning-and-organizational-learning/)
- [Auqui-Caceres — Revitalizing Double-Loop Learning: Systematic Review (Wiley)](https://onlinelibrary.wiley.com/doi/10.1111/emre.12615)

### Algorithmic Fairness Auditing
- [Peer-induced Fairness: Causal Approach to Algorithmic Fairness Auditing (arXiv)](https://arxiv.org/html/2408.02558v4)
- [Causality for Fairness: Unified Framework for AI Auditing (arXiv)](https://arxiv.org/html/2207.04053)
- [PreCoF: Counterfactual Explanations for Fairness (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10047477/)
- [Towards Algorithm Auditing (Royal Society)](https://royalsocietypublishing.org/rsos/article/11/5/230859/92764/Towards-algorithm-auditing-managing-legal-ethical)
- [Ethics-Based Auditing for AI (arXiv)](https://arxiv.org/pdf/2407.06232)
- [AI Auditing AI: Towards Digital Accountability (GMU CHAIS)](https://chais.gmu.edu/ai-auditing-ai-towards-digital-accountability/)

### Structured Analytic Techniques
- [CIA Tradecraft Primer: Structured Analytic Techniques (CIA)](https://www.cia.gov/resources/csi/static/Tradecraft-Primer-apr09.pdf)
- [Chang, Berdini, Mandel & Tetlock — Restructuring SATs in Intelligence (Taylor & Francis)](https://www.tandfonline.com/doi/abs/10.1080/02684527.2017.1400230)
- [Dhami, Mandel, Mellers & Tetlock — Improving Intelligence Analysis with Decision Science (SAGE)](https://journals.sagepub.com/doi/full/10.1177/1745691615598511)
- [Belton & Dhami — Cognitive Biases and Debiasing in Intelligence Analysis (Strathclyde)](https://strathprints.strath.ac.uk/76840/1/Belton_Dhami_RHBR_2020_Cognitive_biases_and_debiasing_in_intelligence_analysis.pdf)
- [CIA — Instituting Devil's Advocacy in IC Analysis (CIA)](https://www.cia.gov/resources/csi/static/610d592f509c5ad03f5a999827dd9bdb/Article-Instituting-Devils-Advocacy-in-IC-Analysis-after-October-1973-War.pdf)
- [Correcting Judgment Correctives in National Security Intelligence (Frontiers)](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2018.02640/full)
