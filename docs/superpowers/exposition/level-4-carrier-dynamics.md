# Level 4: Carrier Dynamics — The Original Contribution

Audit note, 2026-05-12: this exposition is an older positioning document. Use
`docs/research/2026-05-12-carrier-dynamics-formalization-track.md` as the
current scoped support artifact. Claims below about proven bounds,
near-optimality, and LDPC equivalence should be read as research hypotheses
until the prototype defines a code/channel/noise model or reports simulation
results.

## Why This Is the Paper That Matters Most

Everything in Levels 2-3 applies existing formalisms (DLM, LIO, NorMAS, defeasible logic) to a new domain. That's valuable — novel application of known theory. But carrier dynamics is a **new mechanism** addressing a **named problem** with **formal backing** from information theory. This is the part that's independently publishable and potentially influential.

---

## The Problem, Stated Precisely

In any system organized by domains (departments, services, agents, microservices), there exists a class of errors that are:

1. **Cross-domain**: The error spans two or more domains
2. **Invisible within each domain**: Each domain's local knowledge is internally consistent
3. **Detectable only at domain boundaries**: Only when facts from different domains are compared does the contradiction become visible
4. **Persistent by default**: Without a mechanism to carry facts across boundaries, the contradiction persists indefinitely

This is not a theoretical concern. The theory document catalogs cases where this failure mode killed people. The Nagappan et al. finding is the quantitative anchor: organizational structure predicted software defects better than any code metric. Your org chart determines your blind spots.

The key reframing: Conway's law is usually understood as a structural constraint ("communication structure determines system structure"). The deeper reading is **epistemic**: communication structure determines what the system can *know*. The 85% defect prediction from org metrics works because org structure determines which failure modes are *epistemically accessible* to the development team. A defect that spans two teams' domains is invisible to each team individually — it exists in the structural hole between them.

---

## Factor Graphs: Why This Isn't Just an Analogy

Kschischang, Frey, and Loeliger (2001) proved that belief propagation, error-correcting codes, the Viterbi algorithm, turbo decoding, and the Kalman filter are all instances of a **single message-passing algorithm** on factor graphs.

A factor graph has two kinds of nodes:
- **Variable nodes**: Hold local state (a belief, a signal value, a domain fact)
- **Check nodes**: Points where multiple variables meet and consistency is checked

Messages pass between them: variables send their current state to checks, checks send consistency signals back.

The mapping to multi-agent systems is structural, not metaphorical:
- **Variable nodes** = agents with local domain knowledge
- **Check nodes** = cross-domain contact points where facts from multiple domains meet
- **Variable → check messages** = agents sharing local facts at contact
- **Check → variable messages** = contradiction/consistency signals propagated back
- **Sparse connectivity** = each agent participates in few cross-domain contacts

This matters because factor graph theory provides **proven bounds** on error correction capability. You don't have to guess whether bounded cross-domain contact is "good enough" — the theory tells you exactly how much contact is needed.

---

## LDPC Codes: Why Small Capacity Works

LDPC (Low-Density Parity-Check) codes were invented by Gallager in 1962, forgotten, and rediscovered in the 1990s when MacKay and Neal showed they achieve near-Shannon-limit performance. They are the error correction behind 5G, Wi-Fi, and satellite communication.

The "low density" part is the key insight: each parity check involves only 6-20 bits out of potentially thousands. The check matrix is **sparse**. Yet this sparse checking achieves nearly the theoretical maximum error correction.

Translation: each agent needs to carry facts from only a handful of other domains (the "low density" checks), yet the system achieves near-optimal cross-domain error detection. The practical heuristic from the submodularity analysis: 3-5 foreign-domain facts per agent hits the plateau of diminishing returns.

The submodularity proof (from arXiv:2511.16708) formalizes the diminishing returns:
- Agent 1 alone catches 32.8% of bugs
- Adding agent 2: +14.9 percentage points
- Adding agent 3: +13.5 percentage points
- Adding agent 4: +11.2 percentage points
- Four agents total: 76.1%

Each additional carrier provides decreasing marginal information gain. This is the mathematical reason why bounded capacity suffices — you hit the useful plateau quickly.

---

## Displacement: Why Frequency, Not Recency

When an agent's carrier slots are full and a new foreign fact arrives, which existing fact should it replace?

The naive answer is FIFO — replace the oldest. But this creates a pathology: high-turnover carrier slots that never persist long enough to reach a contradiction-detecting contact. A fact needs to be carried for a while to have a chance of being compared against relevant local knowledge elsewhere.

The design choice (DD-25): displacement by **frequency**. The new fact replaces the least-observed existing fact only if the new fact has been observed significantly more frequently (the displacement threshold).

Three independent literatures support this:

1. **Epidemiological superinfection**: A more transmissible strain (higher-frequency fact) displaces a less transmissible one, but there's a critical threshold below which coexistence is stable. The displacement threshold serves this role.

2. **Galam's contrarian model**: In opinion dynamics, a fraction of agents maintaining minority-position facts has a moderating (not polarizing) effect. Low-frequency facts that persist in the system prevent groupthink.

3. **LDPC degree distributions**: The optimal variable node degree distribution for LDPC codes is carefully designed — not uniform. Some bits participate in many checks, others in few. Similarly, some facts should be high-frequency carriers, others should persist as rare but valuable diversity.

---

## Anti-Homogenization: Why Domains Must Stay Different

A naive error-correction mechanism would cause all agents to converge on the same knowledge — homogenization. This destroys the value of domain specialization.

Three mechanisms prevent this:

1. **Friedkin-Johnsen stubbornness**: Each agent maintains a stubbornness parameter *s_i* > 0, representing partial attachment to its domain knowledge. No amount of carrier facts can overwhelm an agent's core domain expertise.

2. **Hegselmann-Krause bounded confidence**: Agents in different domains have incommensurable knowledge that limits cross-domain influence. A health monitor can carry a scheduling fact, but it can't *reinterpret* its health domain through a scheduling lens. Domain boundaries act as natural confidence thresholds.

3. **Facts, not interpretations**: Carriers propagate observations ("disk I/O peaks at 2am"), not conclusions ("the operator is a night owl"). This preserves Surowiecki's independence condition for collective intelligence: individual judgments must be made independently for the group to be wise.

---

## What Carrier Dynamics Adds to the Literature

The concept assembles five independently formalized properties:

| Property | Existing literature | Carrier dynamics extension |
|----------|-------------------|---------------------------|
| Probabilistic spreading | Gossip protocols (Demers et al., 1987) | Cross-domain, not intra-domain |
| Message passing for consistency | Factor graphs (Kschischang et al., 2001) | Incidental, not deliberate |
| Bounded capacity | Memory-bounded agents (PODC 2024) | Applied to cross-domain facts |
| Error detection via redundancy | LDPC codes (Gallager, 1962) | Agents as sparse parity checks |
| Anti-homogenization | Stubbornness (Friedkin-Johnsen) | Domain boundaries as confidence bounds |

Additional supporting traditions:

- **Boundary spanners** (Tushman, 1981): Human cross-domain fact carriers are disproportionately valuable in organizations. Carrier dynamics mechanizes this.
- **Structural holes** (Burt, 1992): Bridging disconnected groups provides information advantages. Carrier dynamics prevents persistent structural holes.
- **Epistemic injustice** (Fricker, 2007): Suppressing valid observations based on domain standing is structurally analogous to testimonial injustice. The harm falls on system users (collectively dumber system).
- **High-reliability organizations** (Weick & Sutcliffe): "Reluctance to simplify" and "deference to expertise" — carrier dynamics implements these as structure rather than culture.

The named contribution is the **epistemic characterization of Conway's law**: Conway's law determines what systems can *know*, not just what they can *build*. And carrier dynamics is the structural antidote.
