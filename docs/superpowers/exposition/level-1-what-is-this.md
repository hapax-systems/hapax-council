# Level 1: What Is This, and Why Does It Exist?

## The System

You built a system where AI agents run on your home workstation. They monitor your calendar, process ambient audio from microphones, track your health data, prepare management briefings, and generally act as externalized cognitive infrastructure — compensating for ADHD executive function challenges.

These agents share your physical space. A microphone doesn't just hear you — it hears your partner, your housemates, anyone who walks through your living room. A camera doesn't just see your desk — it sees whoever's in the frame.

This creates a problem that sounds philosophical but is actually engineering: **what is your system allowed to know about other people, and how do you make that enforceable?**

The answer you arrived at is: treat this as a constitutional governance problem. Write down your values as enforceable rules. Build the enforcement into the system's architecture, not into the goodwill of individual agents.

That's what hapax-council is. The "council" is the governance layer. The question is whether the governance is *sound* — whether the guarantees actually hold through every step of processing, not just at the front door.

---

## The Soundness Problem (Why This Got Formal)

Here's the moment this stopped being a nice-to-have.

Your system checks consent when data enters — in `speaker_id.py`, when it first identifies a voice. If Alice hasn't consented, her voice data is dropped. Good.

But then what happens? The data that *did* pass the check flows through a pipeline: `Stamped[T]` → `Behavior[T]` → `FusedContext` → `VetoChain` → `PipelineGovernor` → profiler → sync agents → Qdrant storage. At every one of those steps, the consent information **disappears**. The pipeline doesn't know which data came from which consent contract. It can't.

This is exactly like a type system that only checks types at function inputs but lets anything happen inside the function body. You'd never accept that in a programming language. The guarantees are meaningless if they only hold at the boundary.

So the question became: can consent travel *with* the data, through every transformation, fusion, and storage operation? Can it be checked at every step?

This is where the formal stuff enters. Not because formalism is inherently valuable, but because the guarantees you need are *algebraic* — they need to compose correctly, which means you need to prove composition properties, which means you need math.

---

## Labels and Lattices — The Type System for Consent

The core insight came from a field called **information flow control** (IFC). IFC was invented to solve a different problem — military classified data shouldn't leak to unclassified systems — but the structure is identical.

### What's a label?

A label is a tag attached to data that says "who owns this and who can see it." In your system, a `ConsentLabel` looks like this:

```python
ConsentLabel(policies=frozenset({
    ("alice", frozenset({"operator"})),
    ("bob", frozenset({"operator"})),
}))
```

This says: "This data is governed by two policies. Alice permits the operator to see her portion. Bob permits the operator to see his portion." Both must hold.

A piece of data with no policies — `ConsentLabel(frozenset())` — is public. Anyone can see it. This is called **bottom**, the least restrictive label.

### What's a lattice?

A lattice is a mathematical structure where any two elements have a well-defined "combination" (called a **join**) and a well-defined ordering. Think of it like this:

- **Ordering** (`can_flow_to`): Data labeled with fewer policies can flow to a context labeled with more policies. Public data can flow anywhere. Data requiring both Alice's and Bob's consent can only flow to places that have both permissions. Less restricted flows to more restricted. Never the reverse.

- **Join** (combining labels): When you merge data from two sources — say, Alice's audio and Bob's calendar — the result carries *both* labels. The join is set union: you get all the policies from both sides. This is the most restrictive combination. Formally: `a.join(b) = ConsentLabel(a.policies | b.policies)`.

Why this matters: the join is how fusion works. When `with_latest_from` merges multiple data streams into a `FusedContext`, the output consent label is the join of all input labels. You can't accidentally drop consent requirements during fusion.

### What makes it a lattice specifically?

Three properties, all proven with hypothesis testing in the codebase:

1. **Commutative**: `a.join(b) == b.join(a)` — order doesn't matter
2. **Associative**: `(a.join(b)).join(c) == a.join(b.join(c))` — grouping doesn't matter
3. **Idempotent**: `a.join(a) == a` — combining with yourself changes nothing

Plus: bottom is the identity element (`a.join(bottom) == a`), and the flow relation is reflexive, antisymmetric, and transitive (a partial order).

These aren't nice-to-haves. If any of them broke, consent could leak. The hypothesis tests generate thousands of random label combinations and verify these properties hold. They're algebraic proofs, not spot-checks.

### Where this comes from: DLM and LIO

**DLM** (Decentralized Label Model, Myers & Liskov, 2000) invented the owner-set-of-readers label format. It was designed for confidentiality in distributed systems — "who owns this secret and who can read it." Your system repurposes it for consent — "who is the subject of this data and who has permission to process it." Same algebra, different domain. This repurposing appears to be novel.

**LIO** (Labeled Information-flow Operating System, Stefan et al., 2011) invented the "floating label" pattern. As a computation observes data from higher-consent sources, its own label floats upward — it becomes more restricted. Once you've seen data requiring Alice's consent, you can't write to a place that doesn't have Alice's consent. This prevents laundering. Your `Behavior[T]` implements this: its `consent_label` only ever joins upward, never resets.

---

## Labeled[T] — The Functor That Carries Consent

`Labeled[T]` is a wrapper. It takes any value of type `T` and pairs it with a consent label and provenance:

```python
@dataclass(frozen=True)
class Labeled[T]:
    value: T
    label: ConsentLabel
    provenance: frozenset[str]  # which contracts justify this data
```

It's a **functor**, which is a fancy way of saying: you can transform the value inside without touching the label. `labeled.map(f)` applies `f` to the value and returns a new `Labeled` with the same label and provenance. This is proven:

- `x.map(id) == x` — mapping the identity function does nothing
- `x.map(f).map(g) == x.map(lambda v: g(f(v)))` — mapping two functions separately is the same as mapping their composition

Why does the functor property matter? Because it means transformations can't silently strip consent. If you have a `Labeled[AudioChunk]` and you transform it into a `Labeled[Transcript]`, the consent label rides along unchanged. The only way to change the label is through explicit `relabel()` (which checks flow direction) or through `join_with()` (which combines labels from multiple sources).

### Provenance: the "why" trail

The `provenance` field answers: "which consent contracts were needed to produce this data?" It's a set of contract IDs. This is a simplified form of **why-provenance** from database theory (Green, Karvounarakis, Tannen, 2007).

This matters for revocation. If Alice revokes her consent contract `c1`, you need to find and purge every piece of data whose provenance includes `c1`. Without provenance, you'd have to scan everything and guess. With provenance, it's a targeted operation: `if "c1" in data.provenance: purge()`.

The theory calls this **PosBool(X)** — positive boolean formulas over contract identifiers. At your current scale (~5 contracts), this degenerates to simple set membership. The implementation reflects this honestly: `frozenset[str]` rather than a full formula evaluator.

---

## Principals — Who Can Do What

A **principal** is anything that participates in a data processing chain. You are a principal. Your agents are principals. The distinction:

- **Sovereign principals** (humans) can originate and revoke consent contracts. This is the **constitutive speech act** — saying "I consent" *is* the act of consenting. Software can't perform this act because it doesn't have the standing.

- **Bound principals** (software) operate under delegated authority that they cannot amplify. If you delegate scope `{audio, presence}` to an agent, that agent can delegate `{audio}` to a sub-agent, but never `{audio, presence, biometrics}`. Authority only narrows downstream.

This non-amplification invariant is proven by hypothesis testing: for any delegation chain, the child's authority is always a subset of the parent's grant. It maps to four independent formalizations:

| Framework | Same property, different name |
|-----------|-------------------------------|
| VetoChain | Deny-wins monotonicity: constraints only narrow |
| Miller (object-capability) | Attenuation: wrappers only restrict, never amplify |
| DLM | Relabeling: data only moves to equally or more restrictive labels |
| GDPR Article 28 | Sub-processor obligations must be at least as restrictive |

Ten different research traditions — security, philosophy, law, capability theory, speech act theory — all converge on the same answer about what distinguishes humans from software in governance: consent authority. The `Principal` type encodes this.

---

## The Governance Stack — Axioms, Implications, Enforcement

Your system has five axioms, weighted by priority:

| Axiom | Weight | What it means |
|-------|--------|---------------|
| `single_user` | 100 | One operator. No multi-user anything. |
| `executive_function` | 95 | System compensates for ADHD/autism. Never adds cognitive load. |
| `corporate_boundary` | 90 | Work data stays in employer systems. |
| `interpersonal_transparency` | 88 | No persistent state about non-operator persons without consent. |
| `management_governance` | 85 | LLMs prepare, humans deliver. No generated feedback about individuals. |

These aren't guidelines. They're enforced at four points:

1. **Commit time**: Git hooks scan diffs for T0 violations
2. **Push time**: Gate scripts block high-impact actions
3. **PR time**: An independent LLM (different model from the author) evaluates compliance
4. **Runtime**: Pattern checkers scan LLM output; consent registry checks at ingestion

Each axiom generates **implications** at four severity tiers:

| Tier | What happens | Equivalent |
|------|-------------|-----------|
| T0 block | Architecturally prevented. No autonomy. | A locked door |
| T1 review | Detected, human reviews. | A speed camera |
| T2 warn | Advisory notification. | A traffic survey |
| T3 lint | Informational. | A "suggested speed" sign |

The SDLC pipeline implements **separation of powers**: the operator writes axioms (legislative), Opus implements code (executive), Sonnet reviews and Haiku judges compliance (judicial). Different models serve different roles specifically to prevent self-exoneration.
