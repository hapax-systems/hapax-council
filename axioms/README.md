# axioms/ — Constitutional Governance for Agentic Systems

Constitutional governance for LLM-driven agent systems. Axioms are structural invariants enforced at the architecture level via commit hooks, runtime checks, and accumulated case law. The approach applies ordoliberalism (Worsdorfer 2023): axioms as frame rules (Ordnungspolitik) that constrain what the system can express, rather than directives that tell agents what to do.

## Formal grounding

| Concept | Source | Application here |
|---------|--------|-----------------|
| Constitutive vs. regulative rules | Searle 1995, Boella & van der Torre 2004 | Constitutive rules classify data ("email from domain X counts as work data"); regulative rules constrain behavior ("work data must not persist on home infrastructure") |
| Defeasible logic | Governatori & Rotolo | General constitutive rules can be defeated by specific conditions (e.g., environmental data is personal if it enables re-identification) |
| NorMAS enforcement tiers | Criado et al. | T0 = regimentation (structurally impossible), T1 = enforcement (blocked with review), T2 = monitoring (advisory), T3 = suggestion (lint) |
| Interpretive canons | Statutory/constitutional law | Textualist, purposivist, absurdity doctrine, omitted-case canons applied to derive specific obligations from general principles |
| Vertical stare decisis | Common law | Precedent authority hierarchy: operator (1.0) > agent (0.7) > derived (0.5) |
| AMELI governor pattern | Esteva et al. 2004 | GovernorWrapper validates inputs/outputs at agent boundaries |

See [`shared/README.md`](../shared/README.md) for the theory-to-code map and algebraic proofs.

## Governance Approach

LLM agents can generate novel behavior that was not anticipated in an access control list. An agent tasked with preparing meeting context may construct code paths that persist behavioral patterns about a team member, generate coaching language, or infer emotional state from calendar patterns — none of which were enumerated as prohibited actions.

Enumerating prohibitions after each incident produces an expanding rule set that grows with every novel violation and never converges. This directory implements an alternative: structural invariants (constitutional axioms) that constrain what the codebase itself can express. An agent cannot persist behavioral patterns about a household member because the code required to do so is blocked by commit hooks before it reaches review, rejected by runtime checks at the ingestion boundary, and recorded in the precedent store for future reference. The constraint is architectural, not prompt-level.

## The Five Axioms

Five axioms govern the system. Each is a statement of principle — short enough to memorize, precise enough to generate concrete rules, and weighted to resolve conflicts when principles collide.

| ID | Weight | Constraint |
|----|--------|------------|
| `single_user` | 100 | One operator. No authentication, no roles, no multi-user abstractions. Absolute. |
| `executive_function` | 95 | Zero-config agents. Errors include next actions. Routine work automated. State visible without investigation. |
| `corporate_boundary` | 90 | Work data stays in employer systems. Home infrastructure is personal + management-practice only. |
| `interpersonal_transparency` | 88 | No persistent state about non-operator persons without an active, revocable consent contract. |
| `management_governance` | 85 | LLMs prepare context; humans deliver feedback. No generated coaching language about individuals. |

The weights resolve conflicts between axioms. When `corporate_boundary` (90) says "route inference through the home proxy" and `executive_function` (95) says "agents must work with zero configuration," the higher-weighted axiom prevails: the agent must degrade gracefully when the proxy is unreachable, not fail with a configuration error demanding manual setup. The weights encode conflict resolution permanently.

`single_user` at weight 100 is absolute. No other axiom or operational convenience can override it. The system does not contain identity models, permission hierarchies, role-based routing, or multi-tenant data separation. The architecture structurally prevents them from being built.

### The Executive Function Axiom

The `executive_function` axiom (weight 95) encodes ADHD and autism accommodation as a governance constraint. Task initiation, sustained attention, and routine maintenance are cognitive bottlenecks for the operator.

The T0 implication: every error must include a specific next action ("Qdrant is unreachable — run `docker compose up -d qdrant` and retry"), not a generic failure message. Every recurring task must have a systemd timer. Every agent must work with zero configuration beyond environment variables.

This extends to the system's meta-processes. Four implications govern multi-round agent deliberations (adversarial debates over axiom tensions). When two agents argue across multiple rounds about whether a proposed change violates an axiom, the system checks deliberation quality: Did either agent change its position when presented with contrary evidence? Can the reasoning behind each shift be traced? Is one agent systematically capitulating to the other? These checks are adapted from hoop tests in process-tracing methodology (political science technique for determining whether a causal mechanism is operating or merely correlating). If a deliberation fails all three hoop tests, it is flagged as performative.

### The Consent Framework

The `interpersonal_transparency` axiom (weight 88) governs persistent state about non-operator persons. The system operates in a household with other people. Cameras detect faces, microphones pick up voices, arrival patterns are observable. Without explicit governance, this data accumulates into persistent models of other people's behavior.

No persistent state about any specific non-operator person may exist without an active consent contract — a bilateral agreement that enumerates exactly which data categories are permitted, grants the subject inspection access to everything the system holds about them, and is revocable by either party at any time with full data purge on revocation.

The distinction between observation and modeling applies. Voice activity detection can detect that someone is speaking without identifying who. A camera can detect motion without recognizing a face. These transient observations do not require consent because they do not produce persistent state about a specific person. When the system extracts a voice embedding for speaker identification, infers a habitual arrival pattern, or derives "this person tends to be home between 6 and 9pm," that is persistent state about an identifiable person, and it requires a contract.

The `ConsentRegistry` enforces this at the ingestion boundary — before embeddings are extracted, before state is persisted, before any downstream processing. The `contracts/` directory is currently empty: no consent contracts have been established.

## How Axioms Become Rules

An axiom like "one operator, no multi-user abstractions" is a principle. Enforcement requires concrete rules: what specific code patterns violate it, what constitutes "multi-user," and whether a password-protected local interface counts as "authentication."

The system derives concrete implications from axioms through an interpretive process using four canons from statutory and constitutional interpretation.

**Textualist reading**: what does the axiom literally say? `single_user` says "one operator." The codebase cannot contain classes that model distinct identities, functions that route by credentials, or interfaces that display account-switching UI. The literal text prohibits the structural scaffolding of multiplicity.

**Purposivist reading**: what goal does the axiom serve? `executive_function` exists to accommodate specific cognitive constraints. An agent that requires three command-line flags to run correctly may not violate the literal text ("zero-config" could be read as "no config files"), but it violates the purpose: the operator should not have to remember invocation details. The purposivist reading catches violations that the text does not anticipate.

**Absurdity doctrine**: interpretations that produce nonsensical results are rejected. `single_user` does not prohibit a login screen on the local web interface — physical security is a reasonable concern for a server in a shared household. It prohibits a login screen that creates a user identity or implies that other accounts could exist.

**Omitted-case canon**: what does the axiom's silence mean? `management_governance` says "LLMs prepare context; humans deliver feedback." It does not say "LLMs may draft suggested feedback language for humans to review and edit." The silence is intentional: do not add what the axiom chose not to include.

This process currently yields 90 concrete implications across the five axioms, each tagged with the canon that produced it, the tier of enforcement, and whether it is a negative constraint ("don't do X") or a positive requirement ("actively provide Y"). Implications are generated via LLM with majority-vote consistency checking across multiple runs, then reviewed and committed by the operator. They do not change at runtime.

## Enforcement

### Tiers

The system uses four enforcement tiers:

**T0 — Blocked.** Code that violates a T0 implication cannot be written. Claude Code hooks scan every file edit, every commit, and every push against 20 regex patterns that detect the structural scaffolding of prohibited categories. The hook fires before the edit is applied, not after.

**T1 — Flagged.** Requires human review before merging. The SDLC pipeline's axiom gate (a separate LLM judge) identifies T1 implications and flags them for operator attention. The code can be written; it cannot be merged without review.

**T2 — Advisory.** Automated warnings in agent output. Non-blocking, but logged and visible.

**T3 — Lint.** Style and documentation guidance. No automated enforcement.

### Structural Prevention at Commit Time

Two shell scripts in `hooks/scripts/` implement the T0 boundary. `axiom-scan.sh` intercepts every file write and edit, scanning the proposed content against T0 patterns. `axiom-commit-scan.sh` intercepts every `git commit` and `git push`, scanning staged changes or branch diffs. Both scripts source a shared pattern definition (`axiom-patterns.sh`) that maintains 20 regex patterns covering the structural categories that axioms prohibit: identity management scaffolding, multi-account abstractions, content-sharing features, and management safety violations like generated coaching language.

The patterns are tuned to catch class and function definitions, not incidental prose. They skip axiom enforcement files themselves to avoid false positives on the patterns that define the patterns.

### Runtime Compliance

The enforcement module (`shared/axiom_enforcement.py`) provides two compliance-checking paths for different contexts:

The **hot path** (`check_fast`) runs in sub-millisecond time with no I/O. It pre-compiles T0 implications into keyword co-occurrence rules at startup. When a governance decision needs axiom compliance at perception cadence — inside a VetoChain evaluating at 2.5-second intervals — the hot path checks whether the situation description co-activates keywords from any T0 implication.

The **cold path** (`check_full`) is for decisions that are not time-critical. It loads the full axiom and implication set from YAML, runs the hot path first, then searches the Qdrant precedent store for semantically similar situations. An agent deciding whether a proposed data flow violates the consent framework calls `check_full` and gets back a comprehensive result with violation details, relevant axiom IDs, and the most similar precedent decisions.

## The Precedent Store

Ninety implications cannot anticipate every situation. Novel cases arise — a data flow outside any implication's scope, a perception backend that processes biometric data in a way the implications did not envision.

When a governance decision encounters a novel situation, the decision is recorded as a **precedent**: what was being decided, the decision (compliant, violation, or edge case), and the reasoning and distinguishing facts that drove the decision. Future encounters with similar situations consult the precedent store first, before escalating.

This follows the common law pattern. An axiom says "no persistent state about non-operator persons without consent." A perception backend detects a voice but does not identify the speaker. The first time this situation arises, a decision is made and recorded with the distinguishing facts: "transient observation, no identity resolution, no state persisted." Future similar situations find this precedent via semantic search and follow it.

### Authority and Weight

The system implements **vertical stare decisis** — decisions from higher authorities bind lower ones.

Precedents carry an authority field:
- **Operator** (weight 1.0) — The operator has explicitly reviewed and decided. Highest authority.
- **Agent** (weight 0.7) — An agent made a governance call during execution. The decision stands until the operator reviews it, but it can be overridden.
- **Derived** (weight 0.5) — Generated by the derivation pipeline or test infrastructure. Lowest authority.

When an agent records a precedent, it enters the store with `authority="agent"`. It is provisional — sufficient to guide future agent decisions, but pending operator ratification. If the operator later reviews the precedent and disagrees, the operator's decision supersedes it, creating a new precedent with higher authority. The old precedent is marked superseded but retained for audit.

Agent-authority precedents provide decision consistency when the operator has not reviewed every edge case, while preserving the operator's ability to override. The 31 seed precedents in `precedents/seed/` establish the initial body of case law with operator authority, covering architecture decisions, management boundaries, and executive function patterns.

### Semantic Search

Precedents are stored in Qdrant (768-dimension embeddings via nomic-embed-text-v2-moe). When a new situation arises, `PrecedentStore.search()` embeds the situation text and finds the most semantically similar precedents, filtered by axiom and excluding superseded entries. The system finds relevant precedents even when the exact wording differs — "voice embedding extracted for visitor" matches "biometric data processed for non-operator person" because the semantic meaning overlaps.

### Supremacy

When implications from different axioms conflict, the constitutional hierarchy resolves the tension. `validate_supremacy()` checks for structural overlaps between domain axiom implications (scoped to a subsystem) and constitutional axiom implications (system-wide). Constitutional axioms always prevail. Tensions are flagged for operator review as `SupremacyTension` records.

## Compatibility and Sufficiency

Each implication operates in one of two modes.

**Compatibility** implications are negative constraints: things the system must not do. "The codebase must not contain identity management scaffolding." Enforcement is scanning — the forbidden thing is present and detectable. Pattern matching, code scanning, and commit hooks handle this.

**Sufficiency** implications are positive requirements: capabilities the system must actively provide. "Every error must include a specific next action." "All recurring tasks must have systemd timers." "The system must have proactive alerting for critical state changes." A sufficiency violation is an absence, not a presence.

Sufficiency is verified through behavioral probes (`shared/sufficiency_probes.py`) — deterministic functions that inspect actual infrastructure state. A probe checks whether agent error handlers contain remediation strings. Another counts running systemd timers and compares them to the expected agent set. Another reads deliberation transcripts and verifies the hoop tests passed. These are runtime verification that the axiom's requirements are actively met.

## Agent Tools

Two tools in `shared/axiom_tools.py` expose governance to LLM agents at runtime. `check_axiom_compliance()` runs the cold-path compliance check and returns violations or compliant status — agents call this when making decisions near axiom boundaries. `record_axiom_decision()` records a new precedent with agent authority — called after making a governance-relevant decision, adding to the case law for future reference. Both log to the audit trail.

## Directory Structure

```
axioms/
├── registry.yaml                    5 axiom definitions (SchemaVer 1-0-0)
├── implications/
│   ├── single-user.yaml            25 implications (su-*)
│   ├── executive-function.yaml     42 implications (ex-*)
│   ├── corporate-boundary.yaml     7 implications (cb-*)
│   ├── interpersonal-transparency.yaml  9 implications (it-*)
│   └── management-governance.yaml  7 implications (mg-*)
├── precedents/
│   └── seed/                       31 seed precedents (operator authority)
├── contracts/                       Consent contracts (empty — none established)
└── schemas/                         JSON schemas for axioms, implications, precedents
```

Enforcement in `shared/`: `axiom_registry.py` (loading), `axiom_enforcement.py` (hot/cold compliance), `axiom_precedents.py` (precedent store), `axiom_audit.py` (finding types), `axiom_patterns.py` (T0 scanning), `axiom_tools.py` (agent tools), `axiom_derivation.py` (implication generation), `sufficiency_probes.py` (positive requirement verification).

Hooks in `hooks/scripts/`: `axiom-scan.sh` (edit/write protection), `axiom-commit-scan.sh` (commit/push protection), `axiom-patterns.sh` (shared T0 patterns).
