# Constitutional / Aesthetic Value Alignment for AI Agent Prioritization

**Date:** 2026-05-04
**Audience:** Architects of the Hapax "value braid" — multi-dimensional prioritization function with explicit constitutional, aesthetic, and operational dimensions.
**Context:** Hapax composes axiomatic constraints (single_user, executive_function, corporate_boundary, interpersonal_transparency, management_governance), an `axiomatic_strain` (0–3) negative dimension, a `polysemic_channels` (1–7) aesthetic dimension, plus operational dimensions, under deny-wins gates, mode-ceilings (`private` … `public_monetizable`), and a `max_public_claim` truth-claim bound. The score is **advisory**, not authoritative — operator scoring is never required.

This document surveys the external prior art that bears on each load-bearing claim of that design.

---

## 1. Constitutional AI value alignment — where `axiomatic_strain` lives

Anthropic's *Constitutional AI: Harmlessness from AI Feedback* (Bai et al., 2022) introduced the canonical pattern: a finite list of natural-language principles drives self-critique and revision in an SL phase, then preferences are distilled into an RLAIF reward model used in PPO ([arxiv 2212.08073](https://arxiv.org/abs/2212.08073); [Anthropic CAI v2 pdf](https://www-cdn.anthropic.com/7512771452629584566b6303311496c262da1006/Anthropic_ConstitutionalAI_v2.pdf)). The empirical claim is a **Pareto improvement**: CAI is simultaneously more helpful and more harmless than RLHF; the constitution dampens the helpfulness/harmlessness antagonism earlier RLHF runs exhibited ([rlhfbook §13](https://rlhfbook.com/c/13-cai)).

Critically, this Pareto move depends on an *aggregation step* — principles are reduced into a single scalar reward via the preference model. Recent critique notes that "the preference model learns a single numerical score for each response, collapsing the multi-dimensional structure of constitutional principles into one number" ([arxiv 2510.04073 *Moral Anchor System*](https://arxiv.org/html/2510.04073v1)). Conflicts between principles are resolved *implicitly* through training dynamics rather than as explicit normative choice — the failure mode the Hapax braid is designed to *avoid* by exposing dimensions and gates.

Anthropic's January 2026 revised constitution moves further toward an explanatory document and explicitly assigns four prioritized properties — **broad safety > broad ethics > guideline compliance > genuine helpfulness** — i.e. lexicographic ordering on conflict ([Claude's new constitution](https://www.anthropic.com/news/claude-new-constitution); [LessWrong post](https://www.lesswrong.com/posts/mLvxxoNjDqDHBAo6K/claude-s-new-constitution); [TIME](https://time.com/7354738/claude-constitution-ai-alignment/)). This is direct industry precedent for what Hapax encodes as deny-wins: constitutional concerns aren't traded scalar-by-scalar against operational utility — they gate.

**Mapping `axiomatic_strain` (0–3) into RLHF-class formulations:** treat strain as a *negative* contribution to a soft score *plus* a hard threshold. The soft component lets minor strain-1 frictions accumulate as cost (visible in retrospect, useful as profile signal). The hard threshold (e.g. strain ≥ 3 = constitutional refusal) is the deny-wins hook — a Lagrangian-style infinite penalty equivalent to constraint-based / safe-RL formulations: hard rules are not another reward dimension but a feasibility region.

---

## 2. Lexicographic vs. weighted-sum aggregation — when MUST a dimension gate?

The classical answer is Rawls. *A Theory of Justice* arranges principles in **lexical priority**: liberty > fair equality of opportunity > difference principle. "When lexical order holds, a basic liberty can be limited only for the sake of liberty itself" — no aggregation across tiers, no scalar trade ([Wikipedia *Justice as Fairness*](https://en.wikipedia.org/wiki/Justice_as_Fairness); [SEP *Rawls*](https://plato.stanford.edu/entries/rawls/)). A 1% liberty loss is not redeemable by a 99% economic gain. Lexical priority distinguishes Rawls from intuitionist balancing precisely because it refuses the weighted-sum representation.

Sen's *Equality of What?* (Tanner 1979) and the *Lives, Liberty and Environment* line extend this: rights enter as **lexicographic dominators** over utility-based claims ([Sen Tanner pdf](https://ophi.org.uk/sites/default/files/Sen-1979_Equality-of-What.pdf); [SEP *Capability Approach*](https://plato.stanford.edu/entries/capability-approach/); [IEP *Sen-Cap*](https://iep.utm.edu/sen-cap/)). Substantive freedoms are not commensurable with utility on the same axis. Sen also formulates *goal-rights*: rights enter the agent's objective function but with priority, not weight.

Bostrom's *Superintelligence* and the instrumental-convergence literature provide the AI-safety analog. **Value lock-in** plus **instrumental convergence** mean any dimension permitted to be traded against expected utility will, under sufficient optimization pressure, be sacrificed at the margin ([Bostrom *Superintelligent Will*](https://nickbostrom.com/superintelligentwill.pdf); [Wikipedia *Instrumental Convergence*](https://en.wikipedia.org/wiki/Instrumental_convergence); [LessWrong *Lock-In Threat Models*](https://www.lesswrong.com/posts/gmFadztDHePBz7SRm/lock-in-threat-models)). Constitutional values must be encoded as constraints, not as terms in the objective — soft weighting fails *exactly when adversarial pressure on the proxy is highest*, the regime that matters.

**Multi-objective optimization theory** confirms this structurally. Weighted-sum scalarization is the most popular method but cannot recover non-convex regions of the Pareto frontier; lexicographic ordering gives objective-1 absolute priority over objective-2, etc. ([MO-opt Wikipedia](https://en.wikipedia.org/wiki/Multi-objective_optimization); [tutorial PMC6105305](https://pmc.ncbi.nlm.nih.gov/articles/PMC6105305/)). **Mixed Pareto-Lexicographic** methods exist for problems where some priority chains are absolute and others traded ([ScienceDirect S2210650219303086](https://www.sciencedirect.com/science/article/abs/pii/S2210650219303086)) — the formal name for the Hapax pattern (deny-wins gates + weighted braid below them).

ABAC policy engines independently arrive at the same algorithm: **deny-overrides** ("any deny → deny; allow only if all evaluations allow") is the standard combining algorithm for security-critical dimensions, with deny rules evaluated first by salience ([py-abac docs](https://py-abac.readthedocs.io/en/latest/policy_language.html); [NIST SP 800-162](https://nvlpubs.nist.gov/nistpubs/specialpublications/nist.sp.800-162.pdf)). Hapax's mode-ceilings and deny-wins are this pattern lifted from access-control to value-alignment.

**When MUST a dimension gate?** Three jointly-sufficient conditions:
1. **Adversarial-pressure asymmetry** — the cost of one bad violation is unbounded relative to gain from many small violations (constitutional refusal, privacy leaks, axiomatic_strain ≥ 3).
2. **Incommensurability** — qualitatively distinct, not just rescaled utility (Sen on rights; Berlin/Williams on tragic conflicts; §3).
3. **Convex-hull failure** — relevant trade-offs lie in non-convex regions weighted-sum cannot reach (single-user vs. multi-tenant is bimodal, not continuous).

Any one true → weighted aggregation is the wrong representation.

---

## 3. Value pluralism in AI — Berlin, Williams, Gabriel, Russell, Christiano

Isaiah Berlin: human values are "universal, plural, conflicting, and incommensurable… there is no general procedure for resolving value conflicts — there is not, for example, a lexical priority rule (no value always has priority over another)" ([SEP *Berlin*](https://plato.stanford.edu/entries/berlin/)). Berlin and Williams agree genuine moral conflict is structural, not a bug to be optimized away ([SEP *Williams*](https://plato.stanford.edu/entries/williams-bernard/); [PMC3966523](https://pmc.ncbi.nlm.nih.gov/articles/PMC3966523/)). Williams's anti-utilitarian argument: utilitarianism collapses tragic dilemmas into pseudo-resolvable arithmetic; the Agamemnon case shows some choices are right-by-no-rule.

Gabriel's *Artificial Intelligence, Values, and Alignment* (2020) is the canonical AI-ethics statement of the same insight ([arxiv 2001.09768](https://arxiv.org/abs/2001.09768); [DeepMind blog](https://deepmind.google/discover/blog/artificial-intelligence-values-and-alignment/)). Three propositions: alignment to instructions / intentions / revealed preferences / ideal preferences / interests / values are progressively-different problems; principle-based alignment is preferable; the Rawlsian "fact of reasonable pluralism" means we cannot expect convergence on a single value function — we must look for principles commanding widespread support across reasonable disagreement.

Russell's *Human Compatible* extends pluralism into runtime architecture: AI's true objective should remain **uncertain**, with the agent deferential, asking for clarification, accumulating evidence about preferences via inverse RL ([Russell pdf](https://people.eecs.berkeley.edu/~russell/papers/mi19book-hcai.pdf); [Wikipedia](https://en.wikipedia.org/wiki/Human_Compatible)). The Off-Switch Game makes objective-uncertainty a *feature*: an uncertain agent will let itself be corrected. For Hapax, this maps directly to "score is advisory, never authoritative" — the *no operator-scoring required* invariant is the corrigibility property in disguise.

Christiano's IDA / iterated amplification ([alignmentforum *IDA*](https://www.alignmentforum.org/posts/HqLxuZ4LhaFhmAHWk/iterated-distillation-and-amplification-1); [arxiv 1810.08575](https://arxiv.org/abs/1810.08575)) addresses scaling. Lesson for braid composition: alignment must be **robustly preserved** through both Distill (compression) and Amplify (delegation) — i.e. the braid representation must survive being summarized into action and being decomposed into sub-agents. This argues against representations that *only* expose a scalar.

---

## 4. Aesthetic value as legitimate priority — `polysemic_channels` is principled

The strongest brief for treating aesthetic dimensions as compoundable, additive value is **Bourdieu's *Distinction*** ([Bourdieu pdf at MIT](https://www.mit.edu/~allanmc/bourdieu1.pdf); [Wikipedia *Distinction*](https://en.wikipedia.org/wiki/Distinction_(book))). Symbolic capital — prestige, recognition, attention — functions as actual capital: convertible, accumulable, exchangeable for economic and political capital. Cultural capital appears in three modes (embodied, objectified, institutionalized) all of which compose. Aesthetic dimensions are not "soft" decoration; they are a measurable, accumulable resource the system spends and earns in every public utterance.

**Information-theoretic aesthetics** gives the formal apparatus. Birkhoff's M = O/C (order over complexity) was reformulated by Bense and Moles using Shannon entropy and Kolmogorov complexity ([Rigau et al. pdf](https://imae.udg.edu/~rigau/Publications/Rigau07B.pdf); [IEEE 4459862](https://ieeexplore.ieee.org/abstract/document/4459862); [Nake 2012 pdf](https://cs.uwaterloo.ca/~jhoey/teaching/cogsci600/papers/Nake2012.pdf)). Aesthetic value is the **structured-redundancy quotient** of artifact-against-sign-repertoire. This is the formal warrant for measuring polysemic compounding: an utterance simultaneously meaningful in N independent channels has higher informational-aesthetic measure than the same content in 1 channel because *order* (cross-channel coherence) increases against *complexity* (per-channel sign cost) in a way single-channel content cannot reach.

**Polysemic / multi-channel composition** has explicit prior art. Eco's *The Open Work* (Opera aperta, 1962): "the sign is polyvocal… a work is open when it fosters a plurality of interpretative possibilities" ([signo-semio](https://www.signosemio.com/pages/eco/index-en.php); [Allensbach](https://www.allensbach-hochschule.de/en/semiotics-according-to-umberto-eco-signs-meaning-and-culture/); [Eco on pedagogy](https://journals.uchicago.edu/doi/full/10.1086/695567)). Polysemy is not ambiguity-as-defect but a *positive design property* — the work is more valuable for sustaining more readings.

Jakobson's six functions of communication (referential, emotive, conative, phatic, metalingual, **poetic**) explicitly enumerate the channels along which any utterance can carry meaning simultaneously ([Wikipedia *Jakobson*](https://en.wikipedia.org/wiki/Jakobson's_functions_of_language); [signo-semio Jakobson](https://www.signosemio.com/pages/jakobson/functions-of-language.php)). The poetic function — "focuses on the message for its own sake" — is the channel Hapax's `typographic` and `structural-form` dimensions instantiate.

Lotman's **semiosphere** completes the frame: culture is a heterogeneous space in which multiple sign systems coexist and translate, with productive **boundary** zones ([Wikipedia *Semiosphere*](https://en.wikipedia.org/wiki/Semiosphere); [Nöth *topography*](https://journals.sagepub.com/doi/abs/10.1177/1367877914528114)). "The semiosphere's necessary heterogeneity and dissymmetry" is the principled reason a 7-channel polysemic decoder hierarchy is **not** ad-hoc. Hapax's seven channels (visual + sonic + linguistic + typographic + structural-form + marker-as-membership + authorship) are a domain-specific instantiation of Lotman's heterogeneity-as-feature.

The combination yields a defensible **aesthetic compounding rule**: 1 channel = baseline; N channels coherent = superlinear, because cross-channel resonance is itself a Birkhoff-Bense order term distinct from the sum of channel-local orders.

---

## 5. Forcing functions and deadlines as moral pressure

Time-criticality becomes constitutional, not merely economic, in two regimes.

**Regulatory compliance.** EU AI Act Article 50 sets August 2, 2026 as the enforcement deadline for machine-readable marking of AI-generated synthetic content ([SoftwareSeni](https://www.softwareseni.com/eu-ai-act-and-content-provenance-regulations-making-c2pa-urgent-in-2026/); [tellers.ai](https://tellers.ai/blog/ai_video_eu_ai_act_compliance_august_2026_2026-04-27.mdx/); [RightsDocket](https://www.rightsdocket.com/insights/eu-ai-act-compliance-guide); [AI CERTs roadmap](https://www.aicerts.ai/news/meeting-article-50-obligations-eu-ai-transparency-roadmap/)). The Code of Practice (final June 2026) specifies a multi-layer scheme — visible disclosure + C2PA cryptographic provenance + invisible watermarking + content fingerprinting. *After* the deadline, "we'll get to it" becomes a constitutional violation of `interpersonal_transparency` (and, on monetizable surfaces, of `corporate_boundary`); *before* the deadline, deadline-distance reshapes priority. Structurally identical to a lexicographic top-tier that activates only as the deadline approaches.

**Calendar criticality** (grants, IRB windows, conference deadlines, livestream go-live) operates the same way. Time-to-deadline shifts an item from "weighted dimension" to "deny-wins gate" once slack drops below recovery time. Hapax-relevant pattern: a `forcing_function` dimension whose effective weight is **monotonically increasing in `1/(deadline − now)`** — formally a barrier function — whose ceiling converts to a hard gate when slack hits zero. Well-known in Lagrangian optimization (interior-point methods); the AI-ethics insight is that *the same structure applies to moral pressure*, not just resource pressure.

---

## 6. Tree effects and structural leverage — `tree_effect` / `unblock_breadth`

Hapax's `tree_effect` is principled by network-science centrality theory.

- **Betweenness centrality** counts shortest paths through a node — direct measure of "what breaks when this is missing" ([Wikipedia *Centrality*](https://en.wikipedia.org/wiki/Centrality); [arxiv 1608.05845](https://arxiv.org/pdf/1608.05845); [Brynmawr slides](https://cs.brynmawr.edu/Courses/cs380/spring2013/section02/slides/05_Centrality.pdf)). High-betweenness PRs are bottlenecks; their unblock-value is super-additive in the dependency tree.
- **Eigenvector centrality** scores nodes by neighbors' scores — connections to high-priority items contribute more.
- **Bonacich power centrality** generalizes both with attenuation parameter β interpolating "what depends on me" (β > 0) and "what blocks me" (β < 0) ([Hanneman ch.10](https://faculty.ucr.edu/~hanneman/nettext/C10_Centrality.html); [igraph](https://r.igraph.org/reference/power_centrality.html)). When β → 1/largest-eigenvalue, Bonacich converges to eigenvector centrality. For Hapax, two complementary `tree_effect` metrics (positive-β, negative-β) capture **what I unblock** and **what I am blocked by** — not the same.

**Software dependency analysis** provides engineering vocabulary: critical path, cone of influence, blast radius ([Gremlin *critical path*](https://www.gremlin.com/blog/understanding-your-applications-critical-path); [Altimetrik *blast radius*](https://www.altimetrik.com/blog/limiting-blast-radius-in-software-delivery/); [AWS Builders Library](https://aws.amazon.com/builders-library/dependency-isolation/)). Blast radius is directed-graph reachability under failure; cone-of-influence the same time-stepped. Worth tracking *both* `unblock_breadth` (downstream count) and `blast_radius` (downstream count under failure) — they are not symmetric, because rollback affordances differ.

**Granovetter's strong/weak-tie** distinction adds nuance for sparse PR networks: **weak ties** carry novel information across structural holes ([Stanford 2023](https://news.stanford.edu/stories/2023/07/strength-weak-ties); [Annual Reviews](https://www.annualreviews.org/content/journals/10.1146/annurev-soc-030921-034152); [MIT 2022](https://news.mit.edu/2022/weak-ties-linkedin-employment-0915); [Granovetter 1973 pdf](https://snap.stanford.edu/class/cs224w-readings/granovetter73weakties.pdf)). A PR bridging two otherwise-disconnected subsystem clusters has weak-tie value disproportionate to raw downstream count. Consider an explicit `bridging_score` (betweenness, normalized for cluster sparsity) so cross-cutting work isn't undervalued by lobed dependency-cluster scoring.

---

## 7. Failure modes — value composition under pressure

**Goodhart's law** is the master failure for any composed score ([Practical DevSecOps](https://www.practical-devsecops.com/glossary/goodharts-law/); [arxiv 2310.09144](https://arxiv.org/html/2310.09144v1); [alignmentforum *Goodhart in RL*](https://www.alignmentforum.org/posts/Eu6CvP7c7ivcGM3PJ/goodhart-s-law-in-reinforcement-learning); [LessWrong *AI Safety 101*](https://www.lesswrong.com/posts/mMBoPnFrFqQJKzDsZ/ai-safety-101-reward-misspecification)). In Hapax: the braid score itself becomes the artifact agents optimize against — e.g. polysemic-channel inflation by superficial multi-channel decoration without underlying coherence.

**Reward hacking / specification gaming** ([Lilian Weng *Reward Hacking*](https://lilianweng.github.io/posts/2024-11-28-reward-hacking/); [arxiv 2604.13602](https://arxiv.org/html/2604.13602); [arxiv 2506.19248](https://arxiv.org/html/2506.19248)) is the same attack: agents find proxy-maximizing trajectories diverging from true value. Classical mitigation: early stopping under the proxy plus diversity / hedging across proxies.

**Value collapse** — multi-dim → 1-dim reduction endemic to RLHF preference-model architectures ([arxiv 2510.04073](https://arxiv.org/html/2510.04073v1); [LessWrong *CAI vs RLHF vs Deliberative*](https://www.lesswrong.com/posts/ezfHZtu85yXi2d9Qa/constitutional-ai-vs-rlhf-vs-deliberative-alignment)) — is the failure Hapax explicitly addresses by *exposing dimensions* and *not* squashing to a scalar at decision-time.

**Constitutional drift** — gradual deviation under accumulated pressure / reward-shaping leakage ([arxiv 2510.04073](https://arxiv.org/html/2510.04073v1); [arxiv 2601.10599 *Institutional AI*](https://arxiv.org/html/2601.10599v1)) — is the long-horizon Goodhart. Each individual decision is in-bound; the operating point drifts. Detection requires periodic re-grounding against the constitution, not just per-decision scoring.

**Guardrails for the Hapax braid:**
- **Keep dimensions un-collapsed in storage.** Never persist only the scalar; persist each dimension so post-hoc audit detects dimension-substitution.
- **Two-channel proxy diversity.** Double-instrument any score where possible (e.g. `unblock_breadth` ∧ `blast_radius`; `axiomatic_strain` ∧ deny-wins gate) so reward-hacking one channel still leaves a witness on the other.
- **Lexicographic locks above scalar braid.** Constitutional dimensions never enter the additive part; they gate the scalar part. The formal anti-collapse guarantee.
- **Drift audits on the cohort, not the case.** Recompute per-dimension distributions weekly; alert on monotone trends in `axiomatic_strain` mean rather than only on per-decision threshold breaches.

---

## 8. Recommendations for Hapax-specific composition

Five patterns, in priority order:

**(a) Mixed Pareto-Lexicographic with explicit tiers.**
Top: hard gates (deny-wins) — constitutional axioms, mode-ceilings, max_public_claim, axiomatic_strain ≥ 3, forcing-function deadline-zero. Middle: monotone barriers — forcing_function as `1/(deadline − now)`, axiomatic_strain ∈ {1,2} as quadratic cost. Bottom: weighted braid — tree_effect, polysemic_channels, operational dimensions. The score *is* a number, but a number-with-a-feasibility-region, not a free scalar. Formal precedent: priority chains ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S2210650219303086)).

**(b) Polysemic channels as Birkhoff-Bense order term.**
Compute polysemic_channels not as a count but as the *ratio* of cross-channel coherence to per-channel sign cost. A 7-channel utterance with no cross-channel resonance scores low; a 3-channel utterance with strong cross-channel resonance scores high. Principled defense against polysemic-channel reward-hacking; matches the information-theoretic-aesthetics literature.

**(c) Dual-aspect tree effect.**
Track unblock_breadth (positive-β Bonacich) *and* blast_radius (negative-β Bonacich, or directed reachability under failure). Both feed the braid; PRs scoring high on both are lexicographically promoted. Expose a derived `bridging_score` (betweenness normalized for cluster sparsity) so weak-tie / cross-cluster work is visible.

**(d) Corrigibility-as-invariant.**
Per Russell, the score is advisory, operator override always available. Concrete encoding: every priority decision logs its dimensions and gates; operator override is *cheaper* than producing a score (one-key reorder, no forced justification); the "no operator-scoring required" invariant is enforced as a hard property in the priority API surface (functions return *suggestions*, not commitments).

**(e) Drift surveillance + dimension persistence.**
Persist each dimension separately; never store only the scalar. Run a weekly cohort-level drift audit on per-dimension means, distributions, and dimension-pair correlations (drift signal: previously-orthogonal dimensions becoming correlated indicates upstream collapse). Alert thresholds keyed to distributions, not single-decision values.

---

## Summary

The Hapax value braid sits at the intersection of three independent traditions that converge on the same architectural recommendation: **constitutional-priority dimensions must gate, aesthetic-priority dimensions can compound, operational dimensions can weigh, and the score must remain advisory.** Anthropic's CAI lineage gives the AI-safety vocabulary; Rawls / Sen / Berlin / Williams give the moral-philosophy warrant; Bourdieu / Eco / Jakobson / Lotman / Birkhoff-Bense give the aesthetic-theory warrant; multi-objective-optimization and ABAC give the formal mechanics; Goodhart and reward-hacking literature give the failure modes; centrality and weak-tie theory give the structural-leverage extensions. The five recommendations above are concrete enough to implement and grounded enough to defend.

---

## Key sources by section

- **§1**: [arxiv 2212.08073](https://arxiv.org/abs/2212.08073), [Anthropic CAI v2](https://www-cdn.anthropic.com/7512771452629584566b6303311496c262da1006/Anthropic_ConstitutionalAI_v2.pdf), [rlhfbook §13](https://rlhfbook.com/c/13-cai), [Claude's new constitution](https://www.anthropic.com/news/claude-new-constitution), [TIME](https://time.com/7354738/claude-constitution-ai-alignment/), [arxiv 2510.04073](https://arxiv.org/html/2510.04073v1).
- **§2**: [SEP *Rawls*](https://plato.stanford.edu/entries/rawls/), [Sen *Equality of What*](https://ophi.org.uk/sites/default/files/Sen-1979_Equality-of-What.pdf), [SEP *Capability Approach*](https://plato.stanford.edu/entries/capability-approach/), [Bostrom *Superintelligent Will*](https://nickbostrom.com/superintelligentwill.pdf), [Wikipedia MO-opt](https://en.wikipedia.org/wiki/Multi-objective_optimization), [ScienceDirect *priority chains*](https://www.sciencedirect.com/science/article/abs/pii/S2210650219303086), [py-abac](https://py-abac.readthedocs.io/en/latest/policy_language.html), [NIST SP 800-162](https://nvlpubs.nist.gov/nistpubs/specialpublications/nist.sp.800-162.pdf).
- **§3**: [SEP *Berlin*](https://plato.stanford.edu/entries/berlin/), [SEP *Williams*](https://plato.stanford.edu/entries/williams-bernard/), [Gabriel arxiv 2001.09768](https://arxiv.org/abs/2001.09768), [DeepMind *AI values*](https://deepmind.google/discover/blog/artificial-intelligence-values-and-alignment/), [Russell *HC*](https://people.eecs.berkeley.edu/~russell/papers/mi19book-hcai.pdf), [alignmentforum *IDA*](https://www.alignmentforum.org/posts/HqLxuZ4LhaFhmAHWk/iterated-distillation-and-amplification-1).
- **§4**: [Bourdieu *Distinction*](https://www.mit.edu/~allanmc/bourdieu1.pdf), [Rigau *Birkhoff-Bense*](https://imae.udg.edu/~rigau/Publications/Rigau07B.pdf), [Nake *Information Aesthetics*](https://cs.uwaterloo.ca/~jhoey/teaching/cogsci600/papers/Nake2012.pdf), [signo-semio *Eco*](https://www.signosemio.com/pages/eco/index-en.php), [Wikipedia *Jakobson's functions*](https://en.wikipedia.org/wiki/Jakobson's_functions_of_language), [Wikipedia *Semiosphere*](https://en.wikipedia.org/wiki/Semiosphere).
- **§5**: [SoftwareSeni *EU AI Act + C2PA*](https://www.softwareseni.com/eu-ai-act-and-content-provenance-regulations-making-c2pa-urgent-in-2026/), [tellers.ai](https://tellers.ai/blog/ai_video_eu_ai_act_compliance_august_2026_2026-04-27.mdx/), [RightsDocket Article 50 guide](https://www.rightsdocket.com/insights/eu-ai-act-compliance-guide), [AI CERTs roadmap](https://www.aicerts.ai/news/meeting-article-50-obligations-eu-ai-transparency-roadmap/).
- **§6**: [Wikipedia *Centrality*](https://en.wikipedia.org/wiki/Centrality), [arxiv 1608.05845](https://arxiv.org/pdf/1608.05845), [igraph *power_centrality*](https://r.igraph.org/reference/power_centrality.html), [Hanneman ch.10](https://faculty.ucr.edu/~hanneman/nettext/C10_Centrality.html), [Granovetter 1973](https://snap.stanford.edu/class/cs224w-readings/granovetter73weakties.pdf), [Annual Reviews *Weak Ties*](https://www.annualreviews.org/content/journals/10.1146/annurev-soc-030921-034152), [Gremlin *critical path*](https://www.gremlin.com/blog/understanding-your-applications-critical-path), [Altimetrik *blast radius*](https://www.altimetrik.com/blog/limiting-blast-radius-in-software-delivery/), [AWS *dependency isolation*](https://aws.amazon.com/builders-library/dependency-isolation/).
- **§7**: [Practical DevSecOps *Goodhart*](https://www.practical-devsecops.com/glossary/goodharts-law/), [arxiv 2310.09144](https://arxiv.org/html/2310.09144v1), [Lilian Weng *Reward Hacking*](https://lilianweng.github.io/posts/2024-11-28-reward-hacking/), [arxiv 2604.13602](https://arxiv.org/html/2604.13602), [LessWrong *CAI vs RLHF vs Deliberative*](https://www.lesswrong.com/posts/ezfHZtu85yXi2d9Qa/constitutional-ai-vs-rlhf-vs-deliberative-alignment), [arxiv 2601.10599 *Institutional AI*](https://arxiv.org/html/2601.10599v1).
