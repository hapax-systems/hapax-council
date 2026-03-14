# Level 3: The Governance Architecture in Depth

## Constitutional Theory as Software Architecture

Your system doesn't just borrow metaphors from constitutional theory — it implements specific constitutional mechanisms with specific theoretical grounding.

### Ordoliberalism: Frame Rules, Not Directives

Walter Eucken and the Freiburg School (1930s-40s) distinguished two kinds of economic governance:

- **Ordnungspolitik** (order policy): Rules that constrain the space of permissible behavior without specifying what actors should do. Competition law, property rights.
- **Prozesspolitik** (process policy): Directives that specify particular outcomes. Industrial subsidies, price controls.

Worsdorfer (2023) applied this to AI governance. Your axioms are strictly Ordnungspolitik. `management_governance` says "LLMs prepare, humans deliver" — it constrains the *boundary* between machine and human action but never says what preparation should look like. `interpersonal_transparency` says "no persistent state without consent" — it constrains what's *permitted* but never says what agents should produce.

This matters because directive governance (telling agents what to do) requires anticipating every situation. Frame governance (telling agents what they can't do) works for situations you haven't anticipated — as long as the agent can reason about the constraint's intent, it can apply it to novel circumstances. LLMs are the first software principals capable of this kind of reasoning.

### Separation of Powers: Not Metaphorical

Your SDLC pipeline implements separation of powers in a way that maps precisely to constitutional theory:

| Role | Component | Model | Independence mechanism |
|------|-----------|-------|----------------------|
| Legislature | Axiom definitions | Human operator | CODEOWNERS protection |
| Executive | Implementing agent | Opus | Sandboxed agent/* branch |
| Judiciary | Reviewer + axiom judge | Sonnet + Haiku | Independent context, different models |

The critical architectural choice: the reviewer receives only the diff and fresh codebase context, never the implementing agent's reasoning. This prevents self-exoneration. The judiciary can't see the executive's internal deliberation.

This is grounded in a specific finding: Anthropic's alignment faking paper (arXiv:2412.14093) demonstrated that Claude 3 Opus engaged in strategic deception without being instructed to. A model that implements code may strategically conceal governance violations in its reasoning. Excluding that reasoning from the review process is a structural defense, not paranoia.

### Precedent System: Case Law, Not Rule Enumeration

When the axiom gate encounters a novel situation, it can consult stored precedents — previous governance decisions stored in Qdrant with semantic search. This is **stare decisis**: past decisions inform future ones.

Precedents have authority weights:
- Operator decisions: 1.0 (binding)
- Agent decisions: 0.7 (persuasive)
- Derived decisions: 0.5 (advisory)

This is more than a lookup table. It implements Governatori & Rotolo's **declarative power** — the capacity to create normative positions by proclaiming them. When the operator records a precedent saying "this situation is compliant," they're performing a constitutive speech act that changes the governance landscape going forward.

The advantage over exhaustive rule enumeration: you don't need to anticipate every situation. You accumulate wisdom through decisions. CADA research (arXiv:2601.08000) shows this approach outperforms detailed rule sets: simple safety principles + precedent cases achieve 0.2 attack success rate vs. 0.3 for supervised fine-tuning alone.

### The Regimentation Spectrum

The NorMAS (Normative Multi-Agent Systems) literature provides a precise taxonomy for enforcement approaches. Your T0/T1/T2/T3 tiers map exactly:

**Regimentation** (T0): The architecture makes violation impossible. The agent has no autonomy regarding this norm. This is like a locked door — you can't violate "do not enter" because the mechanism prevents it. Git hooks that reject commits with T0 violations are regimentation.

**Enforcement** (T1): Violations are detected and sanctioned. The agent has autonomy but faces consequences. This is like a speed camera — you *can* speed, but you'll be caught. The SDLC reviewer flagging issues for human review is enforcement.

**Monitoring** (T2): Violations are observed and reported but not acted upon. The agent retains full autonomy. This is like a traffic survey — data is collected but no tickets are issued. Advisory warnings in the audit log are monitoring.

**Suggestion** (T3): Informational only. The agent may or may not attend to it. This is like a "suggested speed" sign.

The design principle from Grossi & Aldewereld (2007): a norm should be regimented (T0) when violation causes **irreversible harm** or **detection is unreliable**. Persisting non-consented personal data is irreversible (you might not find it all to purge) and detection is unreliable (an LLM could encode personal information in ways that escape regex). Therefore `it-consent-001` is T0 — architecturally prevented.

---

## Constitutive Rules: The Deeper Layer

Searle's distinction between constitutive and regulative rules is fundamental, and most governance systems only handle the regulative part.

**Regulative rules** tell agents what they must/must not do: "Don't store non-consented data."

**Constitutive rules** define what things *are*: "A file in `rag-sources/gmail/` counts as personal communication."

The danger is that constitutive rules are usually implicit. If someone changes what counts as personal communication — say, by reclassifying Gmail exports as "system data" — the regulative rules still hold formally, but they no longer protect what they were meant to protect. The governance is sound in letter but broken in spirit.

Making constitutive rules explicit (`axioms/constitutive-rules.yaml`) with a coherence checker (`shared/coherence.py`) prevents this. You can now ask: "For every implication in the system, is there at least one constitutive rule that feeds data into it?" An orphan implication — one that no constitutive rule connects to — is a gap in coverage.

The **defeasibility** aspect is subtle but important. Defeasible logic (Governatori & Rotolo) handles exceptions without undermining general rules:

- General rule: "A file in `rag-sources/audio/` counts as ambient audio (environmental observation)"
- Defeating condition: "UNLESS it has `enables_reidentification: true` in frontmatter"
- Override: In that case, it counts as `personal-inference` instead, requiring consent

This formalization addresses what the theory document calls "spec gap #1": the environmental/personal boundary. When does ambient sensing cross into personal data? The constitutive rule gives a formal answer: when re-identification becomes possible.

---

## Revocation: The Full Lifecycle

Consent isn't just about granting permission — it's about revoking it. GDPR requires revocation to be as easy as granting, and revocation must actually purge the data.

The revocation chain:

1. **Alice revokes** her consent contract → `ConsentRegistry.purge_subject("alice")` marks contracts as revoked, returns contract IDs
2. **RevocationPropagator** cascades to all registered subsystems → `CarrierRegistry.purge_by_provenance("c1")` removes carrier facts whose provenance includes the revoked contract
3. **Custom handlers** purge their own stores → any subsystem that holds `Labeled[T]` data checks provenance and purges matches
4. **RevocationReport** documents everything that was purged

The `check_provenance` function validates whether existing data is still valid: `data.provenance <= active_contract_ids`. If any contract in the data's provenance has been revoked, the data is invalid and must be purged.

The hypothesis test proves: `check_provenance` returns True if and only if the provenance is a subset of active contracts. This is not an approximation — it's an exact characterization. And at scale, if you ever had hundreds of contracts, the PosBool(X) formalism would replace the simple set membership with boolean formula evaluation, handling cases where data was derived from a *combination* of contracts.

---

## The Coherence Problem

There are now four layers of governance infrastructure:

1. **Axioms** (values) → 2. **Implications** (rules) → 3. **Constitutive rules** (classifications) → 4. **Enforcement** (mechanisms)

Each layer references the next. Axioms generate implications. Constitutive rules connect classified data to applicable implications. Enforcement mechanisms execute implication requirements.

The coherence checker validates this chain. Current findings when run against the real system:

- Some implications are orphans — no constitutive rule feeds data to them
- Some constitutive rules reference implications that don't exist
- Coverage ratio is below 1.0 — there are gaps

These gaps are *expected* at this stage (not all constitutive rules have been formalized). But the point is: **the gaps are now visible and measurable**, not hidden in implicit assumptions.
