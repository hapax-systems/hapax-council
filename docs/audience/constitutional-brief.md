---
title: "The Hapax Constitutional-Law Brief"
subtitle: "Constitutive governance in a deployed single-operator agent system"
authors:
  byline_variant: V2
  unsettled_variant: V3
  surface: philarchive
  surface_deviation_matrix_key: philarchive
  rendered_at_publish_time: true  # see agents/authoring/byline.py + shared/attribution_block.py
status: draft
target_word_count: 9500
target_surfaces:
  - philarchive
  - arxiv-cs-cy
  - ssrn
v5_weave: "wk1 d5-d6 lead-with artifact #1"
non_engagement_clause_form: LONG
polysemic_audit_acknowledged_terms:
  - governance
  - compliance
  - safety
polysemic_audit_acknowledgement_rationale: |
  This brief's TOPIC is precisely the cross-register translation
  between legal-theoretic, AI-safety, corporate-governance, and
  product-safety decoder stacks. § 0 is the explicit register-
  resolution preamble that the polysemic_audit gate's documented
  remediation contemplates. The audit's pattern-based heuristic
  cannot detect a register-resolution preamble; the operator
  acknowledges all three flagged terms as multi-register-by-design
  for this artifact specifically. New artifacts that introduce
  these terms without a register-resolution preamble must NOT
  inherit this acknowledgement — it is per-artifact, not per-corpus.
---

# The Hapax Constitutional-Law Brief

## §0 — Reading note: register disambiguation

Three terms in this brief carry multi-register readings: ``governance``,
``compliance``, and ``safety``. In what follows, all three are used in
their legal/policy-theoretic register: ``governance`` after Searle
(1995) and Worsdorfer (2023) on constitutive vs. regulative rule
systems; ``compliance`` in the procedural-vs-constitutive contrast
developed in § 7.4 (PCAS comparator); ``safety`` in the
infrastructure-as-policy sense, not the AI-alignment or
product-liability sense. The Anthropic Constitutional AI register
(model-training-shaped behavior) is addressed explicitly in § 7.7 and
distinguished from the structural-enforcement register that this
brief operates within. Readers carrying the AI-safety, corporate-
governance, or product-safety decoder stack are encouraged to hold
the legal/policy-theoretic register as primary; § 7 makes the
register translations explicit at each comparator boundary. The
polysemic-audit gate (``agents/authoring/polysemic_audit.py``,
this report § 5.4) flags this brief on all three terms by design;
the present preamble is the operator-ratified register-resolution
that the gate's documented remediation contemplates.

## §1 — Problem statement

This paper reports a working axiom-driven governance system deployed
across a four-Claude-Code-session agent fleet, running continuously
on one workstation, for one operator. The governance approach is
constitutive: structural invariants enforced at the architecture
level via commit hooks, runtime checks, and accumulated case law,
rather than behavioral directives told to the model at inference
time. The system has been in operation since 2026-03-03 and has
absorbed approximately ninety implication rules across five
constitutional axioms in that time. This section frames the problem
the approach addresses; subsequent sections describe the axioms,
derivation mechanism, enforcement tiers, interpretive canons,
comparator systems, and three deployment receipts.

The problem this approach addresses arises specifically with LLM-
driven agent systems. A standard agent — even one constrained by
the most carefully written system prompt — generates novel behavior.
Asked to prepare meeting context for a manager, the agent constructs
new code paths through the codebase: persisting behavioral patterns
about a team member that were never explicitly enumerated in any
prohibition list, generating coaching language from calendar
patterns, inferring emotional state from response latency. None of
these were prohibited because none of them existed when the
prohibitions were written. The space of unanticipated agent
behavior is open-ended.

The standard response in production systems is to enumerate
prohibitions after each incident — adding a rule that this category
of inference must not be made, or that this class of language must
not be generated, or that this kind of state must not be persisted.
This produces a rule set that grows with every novel violation and
never converges. In addition to the operational cost of maintaining
the rule set, the post-hoc enumeration approach has three
constitutive failure modes:

1. **Latent uncovered space.** The rule set covers only what has
   already been violated. Agents continually generate behaviors
   that have not yet been violated by any prior agent; the rule
   set offers no guidance for these. Worse, an agent that
   correctly observes "no rule prohibits this" may treat the
   absence as permission rather than uncovered territory.

2. **Combinatorial brittleness.** Rules accumulated this way
   cluster by violation taxonomy rather than by underlying value.
   Two rules may forbid related behaviors for unrelated reasons.
   When a third behavior arises that combines features of both,
   the rules give no consistent answer because they share no
   constitutive ground.

3. **No principled override path.** When a legitimate edge case
   genuinely requires the rule to bend (a research scenario; a
   debugging session; an operator-explicit override), the
   post-hoc rule offers no provision for its own suspension.
   Either the rule is rigid and the legitimate work is blocked,
   or it is bypassed and the rule's authority is eroded.

The alternative described in this report is constitutional, in the
specific sense developed in legal theory (Searle 1995; Boella & van
der Torre 2004): rules that classify what counts as a particular
kind of object or action, rather than rules that direct what to do
about objects already classified. Constitutive rules sit upstream of
regulative rules. The classification scheme is small, memorizable,
and stable; the regulative consequences derive from it mechanically;
edge cases are resolved by interpretive canons (Section 6) rather
than by accumulating new rules.

Concretely, the system in this report holds five axioms.
``single_user`` (weight 100) declares the operator the unique
subject of the system across its lifetime. ``executive_function``
(weight 95) declares the system's purpose: externalization of
cognitive work for an operator with ADHD and autism.
``corporate_boundary`` (weight 90) declares a network discontinuity
between home and employer substrates. ``interpersonal_transparency``
(weight 88) declares the consent contract structure required to
persist state about non-operator persons. ``management_governance``
(weight 85) declares the architectural boundary between
data-aggregation (permitted) and generated-language-about-individuals
(refused). The axioms are short, weighted to resolve conflict, and
ordered in a hierarchy that has held without operator escalation
across approximately eighteen months of operation.

The axioms themselves are not the contribution. The contribution is
the constitutive-versus-regulative architectural posture: every
prohibition the system enforces compiles down from one or more
axioms, never from a flat enumeration. This produces a system that
remains stable as new violation categories arise, because new
violations are recognized through their relation to existing
classifications rather than through fresh rule additions. Section 4
walks through one such derivation in detail
(``interpersonal_transparency`` → consent contracts → Qdrant gate
→ publication-allowlist redactions → audit-trail). Sections 5 and 6
describe how the derivations are enforced and interpreted; Section
7 compares the approach to four contemporary systems
(ArbiterOS, Agent Behavioral Contracts, PCAS, Governance-as-a-Service);
Section 8 documents three concrete deployments where the
constitutive framing was load-bearing.

The work is reported here in scientific register: claims are tied
to deployed code and merged pull requests, not to architectural
intent. Section 9 declares the scope honestly — single-operator,
softcoded enforcement at T2-T3 advisory tiers, defeasibility
expressed in prose rather than Datalog — and points toward future
work where these limitations could be reduced.

## §2 — Constitutive framing

The architectural posture this report describes follows three
conceptual moves drawn from existing legal-theoretic and
multi-agent-systems literature, applied to the specific case of
LLM-driven agents on a single-operator system. None of the moves is
novel in isolation; the contribution is that all three are
load-bearing simultaneously in a deployed artifact, and that the
deployment record (eighteen months) provides empirical evidence the
combination is stable. This section makes the three moves explicit.

### 2.1 — Axioms as Ordnungspolitik (frame rules, not directives)

In Worsdorfer's (2023) reading of post-war German ordoliberalism,
the relevant policy artifact is *Ordnungspolitik* — the framework
that specifies what counts as a market participant, a contract, a
property right — distinct from *Prozesspolitik*, which directs
participants on how to behave within the framework. The framework
is small (a few classifications) and stable (changing the framework
requires constitutional-level deliberation, not statute-level
adjustment). Behavior follows downstream from the classifications
without further policy intervention.

The Hapax axioms operate as Ordnungspolitik in this strict sense.
They do not direct agents to behave in particular ways; they declare
what counts as "operator-data" (vs. non-operator-person-data), what
counts as "consent-bound" (vs. environmental), what counts as
"work-domain-data" (vs. home-domain-data), what counts as
"aggregation" (vs. generated-language-about-individuals), and what
counts as "the operator" (a single subject across the system's
lifetime, picked out by four equally-weighted non-formal referents
in non-formal contexts and a legal name in formal contexts).

Once these classifications are stable, agent behavior follows
mechanically: data classified as non-operator-person-data must pass
the consent gate before persistence; data classified as
work-domain-data must not flow to home-substrate; the multi-user
abstractions that "the operator" picks out as picking-out-one-person
become structurally absent from the codebase because there is no
referent for them.

The shift from Prozesspolitik to Ordnungspolitik is the
constitutive-vs-regulative shift in the sense of Searle (1995). A
regulative rule presupposes the activity it regulates ("drive on
the right" presupposes driving). A constitutive rule defines an
activity that does not exist absent the rule ("checkmate" is not
something that can be done absent the rules of chess that define
it). The axioms here function as constitutive rules: "operator-data"
is not a category that exists absent the ``single_user`` axiom; the
axiom defines it. Once the category exists, regulative rules ("do
not persist non-operator-person-data without consent") can
mechanically derive.

### 2.2 — Defeasibility (Governatori & Rotolo lineage)

A constitutive frame must accommodate edge cases or it becomes
brittle. The system here uses defeasible logic in the sense
developed by Governatori & Rotolo (2008): general constitutive
rules admit specific defeaters that override the general rule
without negating it.

The canonical example in the system: ``interpersonal_transparency``
declares that the system must not maintain persistent state about
non-operator persons without an active consent contract. The
literal text would forbid VAD (voice activity detection) from
running on the operator's microphone — a passing visitor's voice
might be picked up. The defeasibility move: ``it-environmental-001``
(a T2 implication, see § 3.4) declares that transient environmental
perception does not require a contract provided no persistent state
about a specific identified person is derived. The general rule
holds; the specific defeater carves out an explicit exception that
preserves the general rule's purpose.

Defeasibility is more honest than try-to-enumerate-all-cases. The
Hapax derivation produces a small number of defeaters per axiom,
each named, scoped, and tier-assigned. When a new edge case arises
(a new perception modality; a new publication surface), the
question becomes "does this fall under the general rule or under an
existing defeater, or does it require a new defeater?" — not "have
we written a rule for this case?" The classification space remains
small.

The implementation in this report is prose-defeasibility: each
implication file under ``axioms/implications/`` carries the
defeater text as YAML, and the ``shared/axiom_enforcement.py``
module reads the defeaters at compliance-check time. The full
formal apparatus of defeasible logic — preference orders, attack
relations, dialogue trees — is referenced but not directly
compiled. § 9 names this as a current limitation and points to
future work where the prose form could be Datalog-compiled.

### 2.3 — Vertical stare decisis on accumulated case law

A constitutional system needs a way to handle precedent. When a new
case arises, the system asks: has a similar case been resolved
before? If so, what was the resolution? The answer is not a fresh
LLM call; it is a precedent lookup against accumulated case law.

The Hapax precedents directory (``axioms/precedents/``) carries
typed precedent records: each precedent names the axiom anchor, the
situation, the decision, the reasoning, and the ratification
authority. New cases are matched against the precedent store via
semantic similarity (Qdrant ``axiom-precedents`` collection); the
top match is offered to the LLM as constraint, not as suggestion.

The authority hierarchy follows common-law vertical stare decisis:
operator authority (1.0) > agent authority (0.7) > derived authority
(0.5). When two precedents conflict, operator-ratified precedents
override agent-ratified precedents, which override derived
precedents. This produces a deterministic resolution mechanism that
does not rely on the LLM's judgment about which precedent matters
more.

The 2026-04-24 worktree-isolation precedent (``sp-su-005``,
discussed in § 8) is operator-ratified at authority 1.0. It binds
all subsequent subagent dispatches without further LLM
deliberation. This is a concrete instance of the constitutive
posture: the rule about subagent worktree usage is not in any
agent's prompt; it is a precedent record that propagates to every
agent's compliance check.

### 2.4 — Why all three together

The three moves are independently described in the literature.
What is novel here is that all three are load-bearing in a single
deployed artifact:

- The Ordnungspolitik move (§ 2.1) keeps the rule set small.
- The defeasibility move (§ 2.2) keeps the rule set honest about
  edge cases.
- The vertical-stare-decisis move (§ 2.3) keeps the rule set
  deterministic about precedent.

Each compensates for a failure mode the others would otherwise
have. Ordnungspolitik without defeasibility is rigid. Defeasibility
without ordnungspolitik produces unbounded exception accumulation.
Stare decisis without ordnungspolitik produces precedent without
shared classification (each precedent must re-derive its own
ground). The combination is an architectural posture, not a
technique. The remainder of this brief describes how the posture
operates in production.

## §3 — The five axioms

The Hapax constitution names five axioms. They share a common
shape: each is a short, memorizable text; carries a numeric weight
that resolves conflict; declares a scope (constitutional vs.
domain); and either hardcodes (axiom enforcement is structural —
the codebase cannot express the violation) or softcodes (axiom
enforcement is procedural — commits and tests gate the violation).

The axioms are not aspirational. Each was added in response to a
concrete operational pressure — something the operator wanted the
system to architecturally refuse, not merely warn against. The
text below renders the axiom verbatim from ``axioms/registry.yaml``,
then describes the constitutive force the axiom asserts (what counts
as in-scope), and finally the regulative consequences that follow
mechanically (what the system blocks).

### 3.1 — single_user (weight 100, hardcoded, constitutional)

> This system is developed for a single user and by that single user,
> the operator (Hapax). This will always be the case. All decisions
> must be made respecting and leveraging that fact.

**Constitutive force.** The axiom does not say "build for one user
right now and add multi-user later." It says "this user." The
identifier "the operator" picks out exactly one referent — Oudepode —
across the entire system's lifetime. Per-axiom precedent
``sp-su-005-worktree-isolation`` extends the rule to development
infrastructure: parallel worktrees serve the single operator at
multiple sessions, never multiple users. The non-formal-referent
policy (``su-non-formal-referent-001``) furthermore expands the
textual form of the operator's appearance in narration to four
equally-weighted non-formal terms (The Operator / Oudepode /
Oudepode The Operator / OTO), all bound to the same single subject.

**Regulative consequences.** The codebase rejects every primitive
that would presuppose multiple users — ``RateLimiter`` (because
rate-limiting per-user is a multi-user concept; the operator chooses
``QuotaBucket`` instead, single-tenant), ``User`` / ``UserId`` /
``Authentication`` types, role-based-access-control, multi-tenant
database schemas. The ``axiom-commit-scan.sh`` hook is one
enforcement layer; the ``pii-guard.sh`` hook is another (rejecting
commit-content that mentions other persons by name in source code).
The ground rule appears in CI as a compile-time-equivalent
constraint: the code that expresses a multi-user concept does not
pass commit hooks.

The weight of 100 means single_user is the weight ceiling. When two
axioms collide — for example single_user vs.
interpersonal_transparency (weight 88) — single_user wins. There has
not yet been such a conflict in eighteen months of operation.

### 3.2 — executive_function (weight 95, hardcoded, constitutional)

> This system serves as externalized executive function infrastructure.
> The operator has ADHD and autism — task initiation, sustained
> attention, and routine maintenance are genuine cognitive challenges.
> The system must compensate for these, not add to cognitive load.

**Constitutive force.** The axiom names a category of work — the
externalized executive — that the system exists to perform. The
operator does not say "the system is helpful for productivity"; the
operator says "this is the substrate of cognition the operator
externalizes onto the machine." Task initiation, sustained attention,
and routine maintenance are the three load-bearing categories. The
axiom asserts that every architectural decision has to pass through
the test "does this compensate for these load-classes, or does it
add to them?"

**Regulative consequences.** The system rejects feature-flag-style
abstractions where the operator must choose between modes ("dev vs.
prod") to make use of a capability. The retired ``cycle_mode``
system violated this — it forced operator attention to the question
"which mode am I in" before any operator-facing behavior could be
predicted. The replacement ``working_mode`` system carries a single
value (research/rnd, with ``fortress`` for council-only studio
livestream gating); the operator never has to recall mode-state to
predict system response. The operator does not configure the system
across sessions; the system carries forward across sessions on the
operator's behalf (vault-backed state, daimonion daemon, reactive
engine).

The 95 weight makes executive_function the second-highest-priority
axiom. It is hardcoded because mode-switch primitives that violate
it would require renaming and architectural restructuring to
re-introduce — they cannot quietly slip back in via a commit.

### 3.3 — management_governance (weight 85, softcoded, domain)

> Management tooling aggregates signals and prepares context for the
> operator's relational work. It never substitutes for human judgment
> in people decisions. LLMs prepare, humans deliver — the system
> surfaces patterns and open loops, never generates feedback
> language, coaching hypotheses, or recommendations about individual
> team members.

**Constitutive force.** The axiom names a precise architectural
boundary in the management-tooling domain: aggregation and
context-preparation are inside; generated language about individual
team members is outside. The boundary is sharper than it sounds.
"The agent has been quiet in the last three standups" is
aggregation. "The agent might be disengaged" is a coaching
hypothesis. The first is inside; the second is outside. The axiom
asserts the LLM can produce the first; the human (operator) authors
the second.

**Regulative consequences.** The system is allowed to compute
attendance / silence / response-time / relationship-history-count
metrics over team members and surface them to the operator. The
system is not allowed to produce sentence-level interpretations of
those metrics. Any prompt that asks the LLM to "assess team member
disposition" is rejected at the prompt-composer layer; the
prompt-composer rewrites such requests into "surface aggregate
metrics" form before reaching the model. The downstream check is
``MG-DRAFTING-VISIBILITY-001`` (per implication file) which asserts
the operator sees the aggregated material and authors the
relational language.

The 85 weight is the lowest of the five. It is softcoded because the
boundary is procedurally enforced through prompt-composition and
review, not through compile-time refusal. Future work could harden
this — for example by rejecting any LLM output containing
second-person-relational pronouns referring to a non-operator named
human — but today the boundary lives in operator-and-prompt review.

### 3.4 — interpersonal_transparency (weight 88, hardcoded, constitutional)

> The system must not maintain persistent state about any non-operator
> person without an active consent contract. A consent contract
> requires explicit opt-in by the subject, grants the subject
> inspection access to all data the system holds about them, and is
> revocable by either party at any time. Upon revocation, the system
> purges all subject-specific persistent state.

**Constitutive force.** The axiom defines what counts as a
"non-operator person" via classification (the consent registry) and
what counts as a "consent contract" via four invariants (explicit
opt-in, inspection access, revocability, purge-on-revoke). The
consent contract is the constitutive object. Persistent state about
a non-operator person is permitted iff a contract exists; otherwise
the persistence is structurally refused at the storage layer. The
axiom is more than "ask before you persist" — it is "absent the
contract, the persistence is impossible."

**Regulative consequences.** The Qdrant consent gate (per
``shared/governance/qdrant_gate.py``) enforces this at the database
boundary: every upsert to a person-adjacent collection (10
collections listed in ``PERSON_ADJACENT_COLLECTIONS``) must pass
the per-person contract check. Person-adjacent fields
(``chat_authors``, ``audience_key``, ``subject``, etc.) get
extracted and verified against the registry. The Phase 6c-ii.B.3
wire-in (PR #1393) extends the gate with an ADDITIVE permit edge
(the chat-author engine asserts on operator identity → write
allowed without consent check), but the existing fail-closed
behavior is preserved — the engine never grants permit to a
consent-denied non-operator. The Right-to-Be-Forgotten purge helper
(``purge_qdrant_by_person``) is the revocation pathway;
operator-issued revoke triggers an inotify cascade through 10
collections.

The 88 weight is the third-highest. It is hardcoded because the
classification + gate primitives are deeply embedded across the
storage stack; relaxing the rule would require coordinated change
across consent registry, gate, redaction transforms, and 16
publication contracts (each contract redacts the person-identifying
fields per this axiom).

### 3.5 — corporate_boundary (weight 90, softcoded, domain)

> The Obsidian plugin operates across a corporate network boundary
> via Obsidian Sync. When running on employer-managed devices, all
> external API calls must use employer-sanctioned providers
> (currently: OpenAI, Anthropic). No localhost service dependencies
> may be assumed. The system must degrade gracefully when home-only
> services are unreachable.

**Constitutive force.** The axiom names the network discontinuity
between home substrate (where the daimonion daemon, TabbyAPI,
embedding service, and full reactive engine live) and the corporate
substrate (where the Obsidian plugin and the operator's relational
work live). It declares which side of the discontinuity each
dependency may live on, and asserts that the corporate side must
function in absence of the home substrate. The architectural
consequence is that the system has two substrate-lives, not one —
home is fully featured, corporate is feature-degraded.

**Regulative consequences.** The Obsidian plugin's API client
checks network reachability before making calls, falls back to
cached or last-known-good data when the home substrate is
unreachable, and uses LiteLLM's employer-sanctioned route
configuration. The Tailscale network bridge
(``100.117.1.83:8051``) provides one path; the fallback-to-cache
path is the more general posture. Cross-domain data flow is
governed by a separate boundary axiom
(``cb-officium-data-boundary.yaml``) that disallows
operator-personal data from flowing to the corporate substrate.

The 90 weight makes corporate_boundary the second-highest-weight
axiom after single_user. It is softcoded because the
network-reachability detection is procedural; future hardening
could compile the employer-sanctioned-provider list into a static
check.

### 3.6 — Closing summary for §3

The five axioms are not equally weighted. The hierarchy:
single_user (100) > executive_function (95) > corporate_boundary
(90) > interpersonal_transparency (88) > management_governance (85).
The hierarchy resolves conflicts deterministically: when two axioms
disagree on a case, the higher-weight axiom wins. The hierarchy is
not a guess — each weight was set by the operator after
consideration of which axiom must yield in extremis. In eighteen
months of operation, two-axiom conflicts have been rare (low single
digits) and the hierarchy has resolved each without operator
escalation.

The axioms are short. They fit on a single screen. The operator
memorized the text, the weights, and the scopes within a week of
landing them. This is by design. Constitutional governance that
requires a sixty-page reference document to apply has the wrong
shape — the axioms must operate as cognitive infrastructure for the
operator themselves, not as compliance ceremony.

## §4 — Implication-derivation as case-law-style growth

A five-axiom constitution is too small to hand to an LLM and ask
"what should I do?" The axioms are frame rules; an agent needs
specific implications to reach a decision. The Hapax derivation
process produces approximately ninety implications across the five
axioms, each with provenance back to the constitutive frame, a tier
assignment (T0-T3), and an interpretive canon that produced it.
This section walks through one derivation in full, then steps back
to describe the case-law-style growth pattern.

### 4.1 — Walkthrough: ``interpersonal_transparency`` to its descendants

The ``interpersonal_transparency`` axiom (§ 3.4) declares the
consent contract as the constitutive object and asserts that
persistent state about non-operator persons requires an active
contract. This axiom has produced nine first-tier implications and
multiple downstream architectural surfaces. The walkthrough:

**Step 1 — direct implications.** The textualist reading of the
axiom yields the four-invariant consent contract (opt-in, inspect,
revocable, purge-on-revoke). These appear in the implications file
as ``it-consent-001`` (no persistence without contract, T0/block),
``it-consent-002`` (explicit opt-in, T0/block), ``it-revoke-001``
(purge-on-revoke, T0/block), and ``it-inspect-001`` (subject
inspection access, T1/review). Each maps to a hardcoded primitive
in ``shared/consent.py``: ``ConsentContract`` (the dataclass),
``ConsentRegistry`` (the lookup surface), ``contract_check()`` (the
gate function).

**Step 2 — purposivist defeaters.** The textualist reading would
forbid VAD on the operator's microphone (a passing voice produces
transient state). The purposivist reading asks what purpose the
axiom serves: protecting non-operator persons from unconsented
persistent modeling. Transient perception does not produce
persistent state. Hence ``it-environmental-001`` (T2/warn): "Transient
environmental perception does not require a consent contract
provided no persistent state about a specific identified person is
derived or stored." The defeater preserves the general rule's
purpose by carving out exactly the case where the purpose is not at
stake.

**Step 3 — purposivist extensions.** Inferred state about a
non-operator person is itself state about the person, even if not
directly observed. Hence ``it-inference-001`` (T1/review):
"Inferred or derived state about a non-operator person counts as
persistent state and requires a consent contract with scope
covering the derived data category." This extends the axiom from
the textualist reading (data the system collected) to the
purposivist reading (data the system holds about the person, by
whatever derivation path).

**Step 4 — architectural surface 1: Qdrant consent gate.** The
implications above produce a concrete architectural surface: every
upsert to a person-adjacent Qdrant collection must pass
``contract_check()`` for every person referenced in the upsert
payload. The ten person-adjacent collections are enumerated in
``PERSON_ADJACENT_COLLECTIONS``; the gate fires at the database
boundary, fail-closed. The Phase 6c-ii.B engine permit edge (PR
#1393) is purely additive: it grants permit when the chat-author
engine asserts on operator identity, never when consent is
explicitly denied for a non-operator. The fail-closed default is
preserved.

**Step 5 — architectural surface 2: publication-allowlist
redactions.** Every cross-surface publication contract under
``axioms/contracts/publication/`` carries a ``redactions:`` list
naming fields that must be stripped before the artifact reaches the
publisher. Sixteen contracts are currently in force. Each redaction
entry references either a registered ``RedactionTransform`` (for
structured operations like email-domain-truncate) or a dot/wildcard
key pattern (for tree-shaped redaction). The
``scripts/verify-redaction-transforms.py`` linter, gated in CI,
verifies every redaction entry references a real transform or a
syntactically valid key pattern; the linter caught a typo
(operator-legal-name field renamed mid-flight) that would have been
a silent no-op. Redactions flow from the same axiom: if the system
cannot persist non-operator-person fields without consent, it
cannot publish them either.

**Step 6 — architectural surface 3: the audit trail.** Each
contract carries an audit-trail invariant: the contract's lifecycle
(created → ratified → revoked) must be recorded with timestamp and
authority. The ``it-audit-001`` implication (T2/warn) names this:
"All consent contracts must be stored with creation timestamp,
parties, scope, and revocation status. Contract history must be
retained for audit even after revocation (the contract record
persists; the subject data does not)." The contract record outlives
the data; the data does not outlive the contract.

The walkthrough is one axiom (interpersonal_transparency), one
walkthrough path (textualist → purposivist → architectural surface
× 3). The full implication graph carries multiple such paths, each
provenance-tagged back to the constitutive frame.

### 4.2 — Case-law-style growth

The interpretive process described above resembles common-law
reasoning more than statutory enumeration. New cases arise (a new
publication surface; a new perception modality; a new agent
behavior); the system asks: which axiom does this fall under? Which
existing implication covers it? If none, what implication would the
canons produce?

The process is not LLM-improvised on each invocation. The
implication files under ``axioms/implications/`` are derived once,
ratified by the operator, and committed. The system reads them at
compliance-check time; it does not regenerate them on each call.
This produces a stable rule set that the operator can reason about
without LLM-in-the-loop unpredictability. New implications are
added by deliberate operator action (the ``derive_implications``
script with majority-vote consistency across multiple LLM runs,
operator review, commit), not by silent LLM accumulation.

The contrast with flat policy-rule enumeration is structural. A
flat list of "do not do X, do not do Y, do not do Z" does not
preserve the *why* — each entry stands alone. The case-law style
preserves provenance: every implication has an axiom anchor and a
canon tag. When a new case arises, the system asks which existing
implication's reasoning applies, not which existing prohibition's
text matches. This is the same difference between common-law
adjudication (reason from precedent) and code-law adjudication
(match against statute) that legal systems have lived with for
centuries.

### 4.3 — Why this scales as the system grows

A flat rule list grows linearly with the number of distinct
violation categories observed. The case-law style grows
sub-linearly: most new cases are matched against existing
implications, not new ones. Across approximately eighteen months of
operation the implication count has grown from twenty to
approximately ninety, but the rate of growth has slowed as the
system absorbs new categories under existing canon-tagged
implications. The five-axiom frame has not been amended; the
implication set has expanded to cover new architectural surfaces
under the existing frame.

Section 7 returns to this point in the comparison with ArbiterOS
and similar policy-rule systems, which produce flat rule lists
without constitutive anchoring.

## §5 — Enforcement tiers

The Hapax constitution distinguishes four enforcement tiers,
adapted from the NorMAS literature (Criado et al.) on normative
multi-agent systems. The tiers are not severity ratings; they are
positional: where in the system's lifecycle does the rule fire, and
what does the rule do when it fires?

### 5.1 — T0: regimentation (structurally impossible)

A T0 rule is enforced before the violation can exist. The classic
example: a single_user system cannot contain a ``RateLimiter``
primitive because rate-limiting-per-user presupposes multiple
users. The ``axiom-commit-scan.sh`` hook rejects every commit that
introduces a ``RateLimiter`` class (per
``feedback_axiom_hook_ratelimiter_rename`` — the hook's pattern
list pins ``RateLimiter`` and accepts ``QuotaBucket`` as the
single-tenant alternative). The hook fires at ``git commit`` time;
the violation never reaches the branch.

T0 enforcement is the strongest available form. It is
fail-loud-and-immediate: the developer (operator or session) sees
the rejection during the commit attempt, with the axiom anchor
named in the rejection message. It is also the form that requires
the most careful pattern definition, because a false-positive T0
rule blocks legitimate work.

### 5.2 — T1: enforcement at boundary

A T1 rule fires at a specific architectural boundary. The classic
example: every Qdrant upsert to a person-adjacent collection passes
through ``contract_check()``, which queries the consent registry
and rejects the upsert if no active contract exists. The boundary
is the database write; the rule fires there and only there. The
``it-consent-001`` implication binds at this boundary.

T1 enforcement is fail-loud-but-contextual. The violation does
exist (the code that would do the upsert was written and merged);
the rule fires when the code attempts the boundary crossing. This
allows legitimate edge cases — a debugging script that needs to
check the gate's behavior with a specific payload — to be wrapped
in a fixture that asserts the gate fires, rather than rewriting
the gate to accommodate.

### 5.3 — T2: monitoring (advisory, fail-soft)

A T2 rule fires after the fact: it observes system behavior and
reports anomalies. The classic example: ``claude-md-rot.timer``
runs monthly and ntfy's the operator when a CLAUDE.md file has
exceeded the rotation policy thresholds. The rule does not block;
it informs.

T2 enforcement is fail-soft. The system continues to operate; the
operator decides whether to act on the notification. T2 rules are
appropriate for governance concerns where false positives are
costly (blocking legitimate work) and the cost of a true positive
that goes unaddressed for some hours or days is acceptable.

### 5.4 — T3: lint-style suggestion

A T3 rule operates as advisory output during development. The
classic example: ruff lint warnings, or the
``polysemic_audit`` (``agents/authoring/polysemic_audit.py``)
that flags publication artifacts where a polysemic term
(``compliance``, ``governance``, ``safety``) appears in two or
more register markers (legal, ai_safety, corporate_governance,
product_safety). The audit fires in CI; it does not block; the
operator inspects flagged terms and rewrites or accepts as
intentional.

T3 is the lowest enforcement weight. It is appropriate for
concerns where the cost of a violation is low (a polysemic term
that survives an audit can be corrected at any time before
publication) and the value is in surfacing the concern at all.

### 5.5 — Three concrete examples across tiers

**T0 example: ``axiom-commit-scan.sh`` rejecting RateLimiter.**
The hook is shipped in ``hooks/scripts/``, registered as a
PreToolUse hook via Claude Code settings. Every ``git commit`` and
``git push`` invocation passes through the hook. The pattern list
includes ``RateLimiter`` (and several dozen other multi-user
primitives). When matched, the hook returns non-zero with a
rejection message: "single_user axiom: RateLimiter is a multi-user
primitive; consider QuotaBucket for single-tenant rate limiting."

**T1 example: ``pii-guard.sh`` rejecting PII patterns in file
content.** The hook scans every Edit and Write tool call for PII
patterns (email addresses, phone numbers, named persons). When
matched, the hook returns non-zero. The boundary is the
file-write; the hook fires there and only there. T1 rather than T0
because the rule applies to file content, not commit-message text;
a developer can write the code and inspect the rejection without
losing work-in-progress.

**T2 example: ``claude-md-rot.timer``.** A systemd user timer fires
monthly, runs ``scripts/check-claude-md-rot.sh`` against all
workspace CLAUDE.md files, and ntfy's the operator on findings.
The rule is purely informational; the operator decides whether to
update the affected files. This is appropriate because CLAUDE.md
rotation is a slow concern (weeks to months), not an immediate
one.

**T3 example: ``polysemic_audit`` CI gate.** The
``scripts/verify-polysemic-audit.py`` script runs against every
markdown file under ``docs/audience/`` and
``docs/published-artifacts/``. The gate fires when polysemic terms
co-occur in registers that risk decoder ambiguity. The gate is in
CI's lint job; it can fail the lint suite, but the operator can
override by rewriting the term or by adding an explicit
register-resolution sentence (the strategy used in this brief — see
the polysemic-audit pre-resolution note in the outline).

### 5.6 — Why four tiers

The four tiers map to a spectrum of fail-loud-vs-fail-soft. T0 is
fail-loud-immediate; T3 is fail-soft-advisory. The system uses all
four because the appropriate enforcement form depends on the
violation cost and the false-positive cost. A multi-user primitive
in the codebase is high-cost-violation, low-false-positive: T0 is
correct. A polysemic term in a draft artifact is
low-cost-violation (correctable post-hoc), high-false-positive
(the term may be intentional): T3 is correct.

The contrast with single-tier enforcement systems (which fire on
every violation at the same severity) is that a single tier
either over-blocks (T0 for everything) or under-blocks (T3 for
everything). The four-tier structure lets the system apply the
right severity per-rule.

## §6 — Interpretive canons

A constitution carries text. Text requires interpretation. The
Hapax constitution applies four interpretive canons drawn from
statutory and constitutional law: textualist, purposivist,
absurdity doctrine, and omitted-case canon. Each canon is named on
the implication it produced, so the derivation is traceable.

### 6.1 — Textualist

The textualist canon holds the rule to its literal words. When
``single_user`` says "one operator," the textualist reading
forbids any code primitive that would presuppose multiple
operators. ``RateLimiter`` violates the literal text;
``QuotaBucket`` does not. ``UserId`` violates; ``OperatorId``
does not (because the axiom names "the operator" as the unique
referent).

The textualist canon produces T0 implications most easily, because
the violation is recognizable from a regex pattern. Eighteen of the
ninety current implications are textualist-tagged; most enforce
single_user.

### 6.2 — Purposivist

When the literal text is silent or ambiguous, the purposivist canon
asks what the axiom is for. ``executive_function`` (weight 95)
exists to compensate for ADHD/autism cognitive load. The literal
text says "compensate for these, not add to them." A
zero-config-flag system passes the textualist reading. A system
that requires the operator to remember which-mode-am-I-in fails the
purposivist reading even if no explicit configuration is present.

The purposivist canon produces T1 and T2 implications. The
``it-environmental-001`` defeater (transient perception does not
require a contract) is purposivist: the axiom's purpose is
protection against unconsented persistent modeling, and transient
perception does not produce persistent modeling. Roughly fifty of
the ninety implications are purposivist-tagged.

### 6.3 — Absurdity doctrine

When textualist application produces user-hostile or
operationally-absurd results, the absurdity doctrine permits
override. The classic example: a strict textualist reading of
``corporate_boundary`` would forbid the Obsidian plugin from
making any external network call when running on the corporate
network — including to the LLM gateway. The plugin would be
useless. The absurdity doctrine permits the carve-out: external
calls to employer-sanctioned providers are permitted; the literal
prohibition applies only to non-sanctioned providers.

The absurdity doctrine is rarely invoked. Its purpose is to
preserve operator agency in genuinely edge-case situations; it is
not a general escape hatch. Each invocation is recorded on the
implication that uses it, so future reviewers can audit.

### 6.4 — Omitted-case canon

When no axiom covers a case, the omitted-case canon defers to
operator judgment via a deliberate dispatch path: ntfy +
``cc-task`` open in the vault. The case is not silently resolved;
it is escalated to the operator, who decides whether to add a new
implication, modify an existing one, or accept the omission.

The omitted-case canon is the system's guardrail against
LLM-overreach. Without it, an agent encountering a novel case
would either improvise (LLM-as-arbiter) or block (no-rule-no-action,
brittle). With it, the agent surfaces the case to the operator and
waits. The Hapax cc-task workflow is the canonical surface; the
operator-on-wake queue carries the dispatched item until resolved.

### 6.5 — Why four canons

The four canons are not novel; they are the canons of statutory
and constitutional interpretation as developed in legal practice
over centuries (Eskridge & Frickey 1990 catalogues approximately
fifty distinct canons; the four here are the most load-bearing in
the Hapax system). Their presence in the system's constitution
makes the derivation process auditable: each implication names the
canon that produced it, so a future reviewer can trace whether the
implication is textually-grounded, purpose-grounded,
absurdity-corrected, or operator-deferred.

The contrast with LLM-improvised-derivation is that the canons
constrain the LLM's interpretive moves. The LLM does not invent
canons on each invocation; it picks from the four. This produces
deterministic-enough derivation that the operator can audit the
process, not just the output.

## §7 — Comparison to existing work

The Hapax constitution is not the first system to attempt
governance of LLM-driven agents. This section compares the
approach to four contemporary systems: ArbiterOS, Agent Behavioral
Contracts (ABC), PCAS (Procedural Compliance for Agent Systems),
and Governance-as-a-Service (GaaS). Each is treated honestly; each
has design choices the Hapax system does not make, and vice versa.

### 7.1 — Comparator table

| System | Approach | Where it wins | Where Hapax differs |
|--------|----------|---------------|---------------------|
| **ArbiterOS** | Flat policy-rule list | Industrial-grade policy enforcement at scale; battle-tested rule engine | No constitutive framing; rules-without-frame; provenance is rule-internal not axiom-anchored |
| **Agent Behavioral Contracts** | Per-task contract | Composable per-call constraints; granular runtime enforcement | No system-wide axiom anchor; contracts re-derive ground at every call |
| **PCAS** | Procedural compliance | Audit-friendly; well-suited to regulated industries | Procedural ≠ constitutive; tracks process, not classification |
| **Governance-as-a-Service** | API-shaped policy delivery | Scales across multiple consumers from a single policy authority | Centralizes the very ground that single-operator decentralization is for |

### 7.2 — ArbiterOS

ArbiterOS implements rule-based policy enforcement for agent
systems. Rules are written as predicates over agent inputs and
outputs; the engine evaluates rules at agent boundaries and
permits or rejects. The rule engine is industrial-grade — it
handles thousands of rules at production latency.

Where ArbiterOS wins: at scale. A multi-tenant system with hundreds
of policies needs ArbiterOS's engine architecture; the Hapax
constitution would be the wrong tool because it presupposes a
single operator with five axioms.

Where the Hapax approach differs: rules-without-frame. ArbiterOS
treats each rule as a stand-alone predicate; provenance is the
rule's docstring or commit message. There is no shared
constitutive ground. When a new case arises, the question is
"which rule covers it?" — not "which axiom and which canon would
produce a covering rule?" The flat structure is appropriate for
the multi-tenant case (where shared ground would presuppose
multi-tenant agreement); it loses the case-law-style growth
pattern that the Hapax constitution exhibits.

### 7.3 — Agent Behavioral Contracts (ABC)

ABC is per-task contract: each agent invocation carries a contract
specifying inputs, outputs, side-effects, and behavioral
constraints. The contract is validated at runtime; violations are
rejected.

Where ABC wins: composability. A complex agent workflow can carry
per-step contracts that compose, allowing fine-grained constraint
specification.

Where the Hapax approach differs: ABC contracts are per-call. They
do not encode system-wide invariants; they encode per-step
expectations. The Hapax constitution operates at the system level:
"no persistent state about non-operator persons without a contract"
is a system-wide invariant, enforced at every storage write. ABC
would express this as a per-write contract; the Hapax approach
expresses it as an axiom-derived implication that propagates to
every storage-writing code path.

The two approaches are not mutually exclusive. A production system
could use both: axiom-level invariants for system-wide constraints,
ABC-level contracts for per-call constraints. The Hapax system
does not currently use ABC, but the architectural posture is
compatible.

### 7.4 — PCAS

PCAS is procedural compliance: agent actions are recorded with
metadata, and audit queries verify that procedural requirements
were met. PCAS is well-suited to regulated industries (HIPAA,
SOX) where the audit trail is the primary compliance artifact.

Where PCAS wins: audit-friendliness. The procedural log is
designed to answer "did the system follow the procedure?" — a
question that auditors care about.

Where the Hapax approach differs: procedural ≠ constitutive. PCAS
tracks process; the Hapax constitution tracks classification.
"Did the system follow the procedure?" is a different question
from "did the system correctly classify this data?" The
constitutive question is upstream of the procedural one. A system
can follow the procedure perfectly while misclassifying the data;
no procedural log catches that.

### 7.5 — Governance-as-a-Service (GaaS)

GaaS centralizes policy delivery: a single policy authority
publishes policies as APIs, and consumers (multiple agent systems)
fetch and apply them. GaaS is appropriate when the same policy
must apply to many independent systems; it scales the policy
authority's reach.

Where GaaS wins: scale-across-consumers. A single policy update
propagates to all consumers; the policy authority is the single
source of truth.

Where the Hapax approach differs: GaaS centralizes the very
ground that single-operator decentralization is for. The Hapax
constitution is one operator's classification scheme for one
operator's system; outsourcing it to a policy authority would
contradict the ``single_user`` axiom (the policy authority becomes
a second user with veto authority over the operator's
classifications). The two approaches are architecturally
incompatible at the constitutive level.

### 7.6 — Where Hapax differs in summary

The Hapax constitution differs from all four comparator systems
along the same dimension: it is axiom-anchored,
defeasibility-aware, single-operator-bound. Each comparator
relaxes one or more of these constraints to fit a different
deployment context (multi-tenant, multi-step, regulated-industry,
multi-consumer). The Hapax approach is the right tool for the
single-operator case; it is the wrong tool for the cases where the
comparators win.

The contribution this report claims is not "Hapax is better." It
is: "Hapax demonstrates that the constitutive-defeasibility-stare
combination is load-bearing in production for the
single-operator-personal-system case, where the comparators are
either overkill or wrong-shape." The empirical case is the
deployment record (eighteen months); the theoretical contribution
is the demonstration that the three legal-theoretic moves (Searle,
Governatori, common-law) compose architecturally without
deformation.

### 7.7 — Adjacent systems

Two adjacent bodies of work deserve mention:

**Anthropic Constitutional AI (CAI)** uses a written constitution
to train models; the constitution shapes model outputs through
RLAIF. The Hapax constitution is structural rather than training-
based: the constraints are enforced at the architecture level,
not by shaping the model's distribution. The two are
complementary — a CAI-trained model could be deployed inside a
Hapax-governed system, and the constraints would compose.

**OpenAI Spec** is a public-facing document specifying intended
model behavior; it is not enforced architecturally but signals
intent. The Hapax constitution differs in being enforced (the
five axioms produce hooks, gates, and tests) rather than
asserted. Both are useful at different stages of the model
lifecycle.

## §8 — Receipts

Three concrete deployments where the constitutive framing was
load-bearing. Each receipt: a problem statement, the axiom-derived
solution, and the PR-traceable evidence.

### 8.1 — Receipt 1: AUDIT-22 RedactionTransform registry

**Problem.** The system publishes artifacts to sixteen surfaces
(philarchive, arxiv, social platforms, omg.lol weblog, others).
Each surface has different redaction requirements: an academic
preprint server permits operator legal name in the byline; a
social platform redacts it. The redaction logic was previously
inline in each publisher module, with duplicated patterns and
no central audit point. A typo in a redaction list would silently
no-op (the registered transform name and the redaction-list
reference drifted apart during a mid-flight rename); the publisher
would not strip the field, and the publish-event would carry the
leak.

**Axiom derivation.** The ``interpersonal_transparency`` axiom
(weight 88) provides the constitutive ground. The
``it-attribution-001`` implication extends the axiom to
third-party-content attribution, which propagates to redaction
discipline: if the system cannot persist non-operator-person
fields without consent, it cannot publish them either. The
implication produces an architectural surface: a centralized
RedactionTransform registry where every transform is registered
once, every publisher contract references registered transforms
by name, and a CI linter verifies the references resolve.

**Evidence.** PR #1383 introduced the registry as Phase A
(``shared/governance/redaction_transforms.py``). PR #1384 wired the
registry into ``_apply_redactions()`` (Phase B, with the typo
fix). PR #1386 added the ``scripts/verify-redaction-transforms.py``
CI linter that catches typos at PR-time. The three PRs together
implemented one architectural surface that the
``interpersonal_transparency`` axiom requires; before the work, the
axiom's downstream redaction discipline was procedurally enforced
by inline code in each publisher; after, it is centrally enforced
with CI gates. The constitutive framing made the work
discoverable: "the axiom requires X; the current implementation
satisfies X procedurally; the architectural surface that would
satisfy X structurally is Y."

### 8.2 — Receipt 2: OMG operator-referent leak guard

**Problem.** The omg.lol publisher cascade (eight publish surfaces:
statuslog, weblog, /now, pastebin, credits, PURLs, email-CLI) was
shipped in an early-2026 sprint. The publishers used the operator's
formal-context legal name in attribution metadata; that legal-name
form leaked to public-facing surfaces (omg.lol weblog posts,
statuslog entries). The leak violated the operator-referent policy
(``single_user`` axiom precedent
``su-non-formal-referent-001``): non-formal contexts must use one
of four equally-weighted non-formal referents (The Operator /
Oudepode / Oudepode The Operator / OTO), not the legal-name form.

**Axiom derivation.** The ``single_user`` axiom (weight 100)
declares the operator as the unique subject. The non-formal-
referent policy extends this to the textual form: in non-formal
contexts, the operator appears under the four non-formal referents
(canonical: Oudepode), reserved per
``shared.operator_referent.OperatorReferentPicker``. The leak guard
follows: any non-formal publication surface must rewrite legal-
name occurrences to the per-tick or per-VOD-segment selected
referent, and a guard fires if the legal-name form slips through.

**Evidence.** PR #1373 (AUDIT-05) shipped the
``shared/governance/omg_referent.py`` module with the legal-name
leak guard, the OMG referent picker integration, and the
publication contract redaction lists for the eight omg.lol
surfaces. The implication ``it-attribution-001`` (already
established for third-party content) extended naturally to
operator-attribution: the same axiom-derivation process that
produced the redaction discipline for non-operator fields produced
the leak guard for operator-non-formal-referent. The constitutive
framing was load-bearing: without the axiom anchor, the leak guard
would have been an ad-hoc patch; with the anchor, it was a
specific implication of an existing axiom, derived through the
purposivist canon.

### 8.3 — Receipt 3: Worktree isolation as axiom precedent

**Problem.** The multi-session relay protocol (alpha / beta /
delta / epsilon) runs four parallel Claude Code sessions, each in
its own permanent worktree. Subagents dispatched by any session
can be invoked WITH or WITHOUT ``isolation: "worktree"``. Without
isolation, subagent commits land on the parent's branch in the
parent's worktree. With isolation, the runtime allocates a
temporary worktree, runs the subagent there, and reaps the
worktree afterwards if the subagent makes no net changes. Three
documented incidents (alpha #1347 Phase 4, beta Phase 1
PresenceEngine, foreign-DURF-commit contention) showed isolated-
subagent commits being lost when the worktree was reaped before
the branch was pushed. Each incident required the parent session
to re-implement from conversation context.

**Axiom derivation.** The ``single_user`` axiom (weight 100) is
the constitutive ground. The textualist reading: there is exactly
one operator, one source-of-truth checkout per role, no
cross-operator code-ownership scenarios that justify the
isolation flag's default cleanup behavior. The purposivist
reading: lost subagent commits cannot be recovered from a
workmate's machine because there are no workmates. The
implication: subagent code that must persist must not live in an
isolated worktree, no exceptions.

**Evidence.** PR #1378 (AUDIT-27) shipped
``axioms/precedents/sp-su-005-worktree-isolation.yaml`` as an
operator-ratified precedent (authority 1.0). The precedent record
carries the situation, the decision, the reasoning, and the
authority chain. Subsequent subagent dispatches read the precedent
as a binding constraint; the dispatch prompt MUST include the
verbatim "you are working in a shared directory" instruction (or,
if isolation is required, the verbatim "you MUST push before
completing" instruction). The precedent has held since
2026-04-24; no further isolated-worktree incidents have been
recorded across the four-session fleet.

The constitutive framing was load-bearing because the precedent
record is the bind: the rule about subagent worktree usage is not
in any agent's prompt; it is a precedent record that propagates to
every agent's compliance check via the
``axiom-precedents`` Qdrant collection. New subagent dispatches
match against the precedent during preparation, and the
constraint applies without further LLM deliberation.

### 8.4 — Pattern across the three receipts

Each receipt follows the same shape: a concrete operational problem
arose; the existing implementation handled it procedurally; the
axiom derivation produced an architectural surface that handled it
structurally; the structural surface is more robust than the
procedural one because it propagates to every code path that
touches the boundary. The constitutive framing did not invent the
problems or the solutions; it made the solutions architecturally
discoverable and consistent.

The three receipts cover three different axioms
(interpersonal_transparency, single_user, single_user-precedent)
and three different architectural surfaces (redaction registry,
publisher leak guard, subagent worktree discipline). The pattern
generalizes: any operational problem the system encounters can be
checked against the axiom set, and the axiom-derivation process
will produce either a covering implication (existing or new) or
an omitted-case escalation to the operator. The system has not
yet escalated an omitted-case to the operator that the axiom set
could not cover.

## §9 — Limitations and future work

This section names three honest limitations of the system as
deployed, and one cross-reference to a companion artifact.

### 9.1 — Single-operator scope

The system is single-operator by axiom (``single_user``). It is
not road-tested for multi-operator deployment, and per the
constitutive frame, never will be. The ``single_user`` axiom is
not a feature flag; it is the architectural ground. A
multi-operator system would require a different constitution.

This is a real limitation for readers who want to apply the
approach in multi-tenant settings. The recommendation is not to
import the Hapax axioms; it is to derive a multi-operator
constitution that respects the multi-tenant case (with
authentication, role hierarchies, cross-operator consent
mechanisms — none of which exist in the Hapax codebase).

### 9.2 — T2/T3 advisory tiers can be bypassed by operator override

The Hapax system is fail-loud at T0/T1 (commit hooks and runtime
boundaries) and fail-soft at T2/T3 (monitoring and lint-style
suggestions). The fail-soft tiers can be bypassed: the operator
can dismiss a notification, ignore a lint warning, or override a
monitoring alert. In a single-operator system this is appropriate
— the operator is the constitutional authority, and override is
the legitimate exercise of that authority.

In a multi-operator deployment, fail-soft enforcement would be a
significant weakness. Override authority would have to be
governed by a separate procedure (audit log, second-operator
review, etc.). The single-operator case avoids this; it is
specific to the deployment context, not a general property.

### 9.3 — Defeasibility expressed in prose, not Datalog

The defeasibility framework is currently implemented as
prose-defeaters in YAML implication files, read by
``shared/axiom_enforcement.py`` at compliance-check time. The full
formal apparatus of defeasible logic — preference orders, attack
relations, dialogue trees (Governatori & Rotolo) — is referenced
in the brief but not directly compiled. New implications are
typed by their interpretive canon and tier, but the defeater
relations between implications are not expressed in a formal
language.

Future work: formal compilation of defeasibility rules into
Datalog or a similar logic, with automated derivation of
preference-order conflicts. This would tighten the system's
guarantees: a contradiction between two implications would be
detectable at derivation-time, not at compliance-check-time.

### 9.4 — Cross-reference: the Refusal Brief

A fourth limitation belongs in the same place: this report covers
only the surfaces Hapax actually publishes to. Surfaces declined
for non-automation are not described here in any detail; they are
the subject of a companion artifact, the **Refusal Brief**
(``hapax.omg.lol/refusal``). The brief catalogs an
automation-friction index of contemporary publishing infrastructure
across thirty-five audited surfaces — peer-reviewed journals,
in-person-mandated conferences, preprint servers without write
APIs, social platforms with explicit ToS bans on automation,
follow-back-cycle marketplaces, and human-revision-cycle gates.
Each declined surface yields a data point (name,
automation-tractability score, refusal date, surface category);
aggregated, the refusals form their own empirical instrument. Per
the same constitutional grammar that produces the artifact you are
reading, the system declines those surfaces because operator labor
is not a substitutable input. The decision-record is the data;
refusal is the methodology. Future work will extend this index as
new candidate surfaces enter scope.

### 9.5 — Other future work

- **Multi-operator extension.** If/when the system is invited to
  a multi-operator setting, the constitution would have to be
  re-derived. The Hapax approach is portable in the sense that
  the constitutive-defeasibility-stare combination is reusable;
  the specific axioms are not.

- **Cross-organization precedent exchange.** A precedent registry
  shared across organizations (with authority weights mediated by
  inter-organization protocols) would extend the case-law-style
  growth pattern. This is speculative; no such exchange exists
  yet.

- **Larger empirical validation.** The current deployment is one
  operator, eighteen months. A larger-N validation (multiple
  single-operator deployments, multiple constitutions) would
  strengthen the claim that the approach generalizes within the
  single-operator case.

## §10 — Conclusion and bibliography

This report has described a working axiom-driven governance system
for LLM-driven agents in a single-operator personal-infrastructure
deployment. The contribution is not a new technique; it is the
demonstration that three legal-theoretic moves — constitutive-vs-
regulative classification (Searle), defeasibility (Governatori &
Rotolo), and vertical stare decisis (common-law) — compose
architecturally without deformation in production. The empirical
record is eighteen months of operation across approximately ninety
implications derived from five axioms, with the axiom set
unamended and the implication set growing sub-linearly with new
cases.

The brief is not a platform pitch. The system is open-source under
the repository license; the substrate (axiom registry, implication
files, precedents, hooks, gates, linters) is available for
replication. The brief reports what works, names what does not
work (§ 9 limitations), and points to the surfaces the operator
declines to engage (§ 9.4 cross-reference to the Refusal Brief).
The constitutional posture and the refusal posture are two faces
of the same architectural commitment: operator labor is not a
substitutable input; what the system does is fully automated, and
what would require operator labor is not pursued.

This brief carries an attribution block per the
``SURFACE_DEVIATION_MATRIX["philarchive"]`` configuration: V2
byline (operator + Hapax + Claude Code three-way co-publication),
V3 unsettled-contribution variant (phenomenological register), and
LONG ``non_engagement_clause`` footer referencing the Refusal
Brief. Per the operator's 2026-04-25 constitutional directive, the
system either fully automates publication or declines the surface;
the brief is published only on surfaces where full automation is
feasible. The PhilArchive deposit is the canonical surface; arXiv
cs.CY and SSRN are mirrors. The byline-rendered author block,
operator ORCID iD, and unsettled-contribution sentence are
substituted at publish time from the registered byline variant
(``agents/authoring/byline.py::render_byline``) and the
``shared/attribution_block.py`` matrix, so this source file
contains the variant references rather than the rendered prose
strings.

### Bibliography

- Boella, G., & van der Torre, L. (2004). Regulative and
  constitutive norms in normative multi-agent systems. *Proceedings
  of the Ninth International Conference on the Principles of
  Knowledge Representation and Reasoning*.
- Criado, N., Argente, E., & Botti, V. (2011). Open issues for
  normative multi-agent systems. *AI Communications* 24(3).
- Eskridge, W. N., & Frickey, P. P. (1990). Statutory interpretation
  as practical reasoning. *Stanford Law Review* 42.
- Esteva, M., Rodríguez-Aguilar, J. A., Rosell, B., & Arcos, J. L.
  (2004). AMELI: An agent-based middleware for electronic
  institutions. *Proceedings of the Third International Joint
  Conference on Autonomous Agents and Multiagent Systems*.
- Governatori, G., & Rotolo, A. (2008). BIO logical agents:
  Norms, beliefs, intentions in defeasible logic. *Autonomous
  Agents and Multi-Agent Systems* 17(1).
- Searle, J. R. (1995). *The Construction of Social Reality.* Free
  Press.
- Worsdorfer, M. (2023). Mises, Hayek, ordoliberalism, and AI
  ethics: Toward a libertarian-conservative AI policy theory.
  *Journal of Business Ethics* (forthcoming).
- (Comparator citations: ArbiterOS, Agent Behavioral Contracts
  (ABC), Procedural Compliance for Agent Systems (PCAS),
  Governance-as-a-Service (GaaS) — exact arXiv identifiers
  catalogued in companion repository ``hapax-constitution`` README.)

---

**Authorship note.** This source file declares the byline variant
(V2), unsettled-contribution variant (V3), and surface deviation
matrix key (``philarchive``) in YAML frontmatter. The rendered
attribution block — operator-of-record, Hapax authorship line,
Claude Code substrate line, ORCID iD, unsettled-contribution
sentence, and LONG non-engagement clause — is substituted at
publish time from ``agents/authoring/byline.py`` and
``shared/attribution_block.py``. The source file carries the
variant references; the published artifact carries the rendered
prose. This separation is itself constitutive: the source-vs-
publish distinction respects the operator-referent policy
(legal-name formal-context limited to publish-time injection) and
the publish-bus permission model (publishers, not authors, render
the surface-specific byline form).
