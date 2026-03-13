# axioms/ — Constitutional Governance for Agentic Systems

## The Problem with Governing Agents

Traditional software systems govern behavior through access control: enumerate who can do what, check permissions at runtime, log violations. This works when the space of possible actions is known in advance. A web application has endpoints; each endpoint has a permission; the middleware checks it.

LLM agents break this model. An agent tasked with "prepare context for a 1:1 meeting" might, in the course of doing useful work, construct a code path that persists behavioral patterns about a team member, generates suggested coaching language, or infers someone's emotional state from calendar patterns. None of these actions were anticipated in an access control list. The agent didn't circumvent a rule — it found a path through territory where no rules existed.

The conventional response is to add rules after each incident: "don't do that specific thing." This creates an expanding list of prohibitions that grows with every novel violation, never converges, and gives false confidence that the remaining unprohibited space is safe. It is a fundamentally reactive posture applied to a system that can generate novel behavior faster than you can prohibit it.

This directory contains an alternative approach. Instead of enumerating what agents may not do, the system establishes structural invariants — constitutional axioms — that constrain what the codebase itself can express. An agent cannot persist behavioral patterns about a household member because the code required to do so cannot be written: commit hooks block it before it reaches review, runtime checks reject it at the ingestion boundary, and the precedent store records the reasoning for future reference. The constraint is not in the agent's prompt. It is in the architecture.

## The Five Axioms

Five axioms govern the system. Each is a statement of principle — short enough to memorize, precise enough to generate concrete rules, and weighted to resolve conflicts when principles collide.

| ID | Weight | Constraint |
|----|--------|------------|
| `single_user` | 100 | One operator. No authentication, no roles, no multi-user abstractions. Absolute. |
| `executive_function` | 95 | Zero-config agents. Errors include next actions. Routine work automated. State visible without investigation. |
| `corporate_boundary` | 90 | Work data stays in employer systems. Home infrastructure is personal + management-practice only. |
| `interpersonal_transparency` | 88 | No persistent state about non-operator persons without an active, revocable consent contract. |
| `management_governance` | 85 | LLMs prepare context; humans deliver feedback. No generated coaching language about individuals. |

The weights are not priorities for a task scheduler. They resolve conflicts. When `corporate_boundary` (90) says "route inference through the home proxy" and `executive_function` (95) says "agents must work with zero configuration," the higher-weighted axiom prevails: the agent must degrade gracefully when the proxy is unreachable, not fail with a configuration error demanding manual setup. The operator doesn't choose which axiom wins. The weights encode that choice permanently.

`single_user` at weight 100 is absolute. No other axiom, no operational convenience, no future feature can override it. This means the system will never contain identity models, permission hierarchies, role-based routing, or multi-tenant data separation — not because those features haven't been built yet, but because the architecture structurally prevents them from being built.

### The Executive Function Axiom

The `executive_function` axiom (weight 95) deserves particular attention because it encodes a specific disability accommodation — ADHD and autism — as a governance constraint, not a quality-of-life enhancement.

Task initiation, sustained attention, and routine maintenance are genuine cognitive bottlenecks for the operator. An error message that says "check the logs for details" is not merely unhelpful; it requires exactly the kind of attention switching and sustained investigation that the axiom exists to eliminate. The T0 implication is concrete: every error must include a specific next action. Not "something went wrong" but "Qdrant is unreachable — run `docker compose up -d qdrant` and retry." Every recurring task must have a systemd timer — you cannot ship an agent and leave it as "the operator can run it manually." Every agent must work with zero configuration beyond environment variables.

This extends to the system's own meta-processes. Four implications govern multi-round agent deliberations (adversarial debates over axiom tensions). When two agents argue across multiple rounds about whether a proposed change violates an axiom, the system checks whether the deliberation is genuine: Did either agent change its position when presented with contrary evidence? Can you trace why each agent shifted? Is one agent systematically capitulating to the other? These are adapted from hoop tests in process-tracing methodology — the political science technique for determining whether a causal mechanism is actually operating or merely correlating. If a deliberation fails all three hoop tests, it is flagged as performative: the agents went through motions without reasoning.

### The Consent Framework

The `interpersonal_transparency` axiom (weight 88) creates the system's hardest constraint after single-user. It exists because the system operates in a household with other people. Cameras detect faces, microphones pick up voices, arrival patterns are observable. Without explicit governance, this data accumulates into persistent models of other people's behavior.

Most systems handle this with anonymization ("we don't store names") or opt-out ("you can request deletion"). This axiom takes a different position: no persistent state about any specific non-operator person may exist without an active consent contract — a bilateral agreement that enumerates exactly which data categories are permitted, grants the subject inspection access to everything the system holds about them, and is revocable by either party at any time with full data purge on revocation.

The distinction between observation and modeling matters. Voice activity detection can detect that someone is speaking without identifying who. A camera can detect motion without recognizing a face. These transient observations don't require consent because they don't produce persistent state about a specific person. But the moment the system extracts a voice embedding for speaker identification, or infers a habitual arrival pattern, or derives "this person tends to be home between 6 and 9pm" — that is persistent state about an identifiable person, and it requires a contract.

The `ConsentRegistry` enforces this at the ingestion boundary — before embeddings are extracted, before state is persisted, before any downstream processing. The gate is early and hard. The `contracts/` directory is currently empty: no consent contracts have been established. The system is designed to support them but has not yet been exercised with a real household member willing to give structured consent.

## How Axioms Become Rules

An axiom like "one operator, no multi-user abstractions" is a principle. To enforce it, you need concrete rules: what specific code patterns violate it? What constitutes "multi-user"? What about a password-protected local interface — is that "authentication"?

The system derives concrete implications from axioms through an interpretive process that borrows four canons from statutory and constitutional interpretation in law. These are not metaphorical borrowings. They are the actual reasoning techniques that courts use to derive specific obligations from general principles, adapted to generate machine-checkable rules from short axiom texts.

**Textualist reading** asks: what does the axiom literally say? `single_user` says "one operator." This means the codebase cannot contain classes that model distinct identities, functions that route by credentials, or interfaces that display account-switching UI. The literal text prohibits the structural scaffolding of multiplicity.

**Purposivist reading** asks: what goal does the axiom serve? `executive_function` exists to accommodate specific cognitive constraints. An agent that requires three command-line flags to run correctly doesn't violate the literal text ("zero-config" could be read as "no config files"), but it violates the purpose: the operator shouldn't have to remember invocation details. The purposivist reading catches violations that the text doesn't anticipate.

**Absurdity doctrine** rejects interpretations that produce nonsensical results. `single_user` doesn't prohibit a login screen on the local web interface — that would be absurd, since physical security is a reasonable concern for a server in a shared household. What it prohibits is a login screen that creates a user identity or implies that other accounts could exist. The absurdity doctrine is the mechanism that prevents axiomatic governance from becoming oppressive: if a strict reading of the axiom leads somewhere unreasonable, the reading is wrong.

**Omitted-case canon** asks: what does the axiom's silence mean? `management_governance` says "LLMs prepare context; humans deliver feedback." It does not say "LLMs may draft suggested feedback language for humans to review and edit." The silence is intentional. The canon says: do not add what the axiom chose not to include. If the axiom had wanted to permit drafted language, it would have said so. Its silence on the matter is a prohibition.

This process currently yields 90 concrete implications across the five axioms, each tagged with the canon that produced it, the tier of enforcement, and whether it's a negative constraint ("don't do X") or a positive requirement ("actively provide Y"). Implications are generated via LLM with majority-vote consistency checking across multiple runs, then reviewed and committed by the operator. They do not change at runtime.

## Enforcement

### Tiers

Not all implications warrant the same response. The system uses four enforcement tiers:

**T0 — Blocked.** Code that violates a T0 implication cannot be written. Claude Code hooks scan every file edit, every commit, and every push against 20 regex patterns that detect the structural scaffolding of prohibited categories. The hook fires before the edit is applied, not after. A T0 violation is not a failed code review — it is a prevented action.

**T1 — Flagged.** Requires human review before merging. The SDLC pipeline's axiom gate (a separate LLM judge) identifies T1 implications and flags them for operator attention. The code can be written; it cannot be merged without review.

**T2 — Advisory.** Automated warnings in agent output. Non-blocking, but logged and visible.

**T3 — Lint.** Style and documentation guidance. No automated enforcement.

### Structural Prevention at Commit Time

Two shell scripts in `hooks/scripts/` implement the T0 boundary. `axiom-scan.sh` intercepts every file write and edit, scanning the proposed content against T0 patterns. `axiom-commit-scan.sh` intercepts every `git commit` and `git push`, scanning staged changes or branch diffs. Both scripts source a shared pattern definition (`axiom-patterns.sh`) that maintains 20 regex patterns covering the structural categories that axioms prohibit: identity management scaffolding, multi-account abstractions, content-sharing features, and management safety violations like generated coaching language.

The patterns are tuned to catch class and function definitions, not incidental prose. They skip axiom enforcement files themselves to avoid false positives on the patterns that define the patterns.

### Runtime Compliance

The enforcement module (`shared/axiom_enforcement.py`) provides two compliance-checking paths for different contexts:

The **hot path** (`check_fast`) runs in sub-millisecond time with no I/O. It pre-compiles T0 implications into keyword co-occurrence rules at startup. When a governance decision needs axiom compliance at perception cadence — inside a VetoChain evaluating at 2.5-second intervals — the hot path checks whether the situation description co-activates keywords from any T0 implication. This is fast enough for the voice daemon's real-time pipeline.

The **cold path** (`check_full`) is for decisions that aren't time-critical. It loads the full axiom and implication set from YAML, runs the hot path first, then searches the Qdrant precedent store for semantically similar situations. An agent deciding whether a proposed data flow violates the consent framework calls `check_full` and gets back a comprehensive result with violation details, relevant axiom IDs, and the most similar precedent decisions.

## The Precedent Store

Ninety implications cannot anticipate every situation. The system will encounter novel cases — a data flow that doesn't clearly fall into any implication's scope, a perception backend that processes biometric data in a way the implications didn't envision. The question is: how do you handle ambiguity consistently over time?

The answer is case law. When a governance decision encounters a novel situation, the decision is recorded as a **precedent**: what was being decided, what the decision was (compliant, violation, or edge case), and critically, the reasoning and distinguishing facts that drove the decision. Future encounters with similar situations consult the precedent store first, before escalating.

This is the mechanism that common law legal systems use to handle the gap between general principles and specific cases. A statute says "no vehicles in the park." Is a bicycle a vehicle? A wheelchair? An ambulance? The statute's authors didn't enumerate every case. Instead, the first time a court encounters "bicycle in the park," it decides and records the reasoning. The next time a similar case arises, the prior decision — the precedent — provides guidance. Over time, a body of case law accumulates that handles the edge cases the original statute couldn't anticipate.

The same pattern applies here. The axiom says "no persistent state about non-operator persons without consent." A perception backend detects a voice but doesn't identify the speaker. Is that "persistent state about a person"? The first time this situation arises, a decision is made and recorded with the distinguishing facts: "transient observation, no identity resolution, no state persisted." Future similar situations find this precedent via semantic search and follow it.

### Authority and Weight

Not all precedent-setters are equal. The system implements what legal theory calls **vertical stare decisis** — the principle that decisions from higher authorities bind lower ones.

Precedents carry an authority field:
- **Operator** (weight 1.0) — The operator has explicitly reviewed and decided. This is the highest authority.
- **Agent** (weight 0.7) — An agent made a governance call during execution. The decision stands until the operator reviews it, but it can be overridden.
- **Derived** (weight 0.5) — Generated by the derivation pipeline or test infrastructure. Lowest authority.

When an agent records a precedent, it enters the store with `authority="agent"`. It is provisional — good enough to guide future agent decisions, but pending operator ratification. If the operator later reviews the precedent and disagrees, the operator's decision supersedes it, creating a new precedent with higher authority. The old precedent is marked superseded but retained for audit.

This solves a practical problem in agentic governance: the system needs to make consistent decisions even when the operator hasn't reviewed every edge case. Agent-authority precedents provide that consistency while preserving the operator's ability to override. The 31 seed precedents in `precedents/seed/` establish the initial body of case law with operator authority, covering architecture decisions, management boundaries, and executive function patterns.

### Semantic Search

Precedents are stored in Qdrant (768-dimension embeddings via nomic-embed-text-v2-moe). When a new situation arises, `PrecedentStore.search()` embeds the situation text and finds the most semantically similar precedents, filtered by axiom and excluding superseded entries. This means the system finds relevant precedents even when the exact wording differs — "voice embedding extracted for visitor" matches "biometric data processed for non-operator person" because the semantic meaning overlaps, even though the words don't.

### Supremacy

When implications from different axioms conflict, the constitutional hierarchy resolves the tension. `validate_supremacy()` checks for structural overlaps between domain axiom implications (scoped to a subsystem) and constitutional axiom implications (system-wide). Constitutional axioms always prevail. A domain axiom cannot override a constitutional principle, just as a state law cannot override a constitutional right. Tensions are flagged for operator review as `SupremacyTension` records.

## Compatibility and Sufficiency

Each implication operates in one of two modes, and the distinction matters for how enforcement works.

**Compatibility** implications are negative constraints: things the system must not do. "The codebase must not contain identity management scaffolding." Enforcement is scanning — the forbidden thing is present and detectable. Pattern matching, code scanning, and commit hooks handle this well.

**Sufficiency** implications are positive requirements: capabilities the system must actively provide. "Every error must include a specific next action." "All recurring tasks must have systemd timers." "The system must have proactive alerting for critical state changes." You cannot detect a sufficiency violation by scanning for something — the violation is an *absence*.

Sufficiency is verified through behavioral probes (`shared/sufficiency_probes.py`) — deterministic functions that inspect actual infrastructure state. A probe checks whether agent error handlers contain remediation strings. Another counts running systemd timers and compares them to the expected agent set. Another reads deliberation transcripts and verifies the hoop tests passed. These are not unit tests; they are runtime verification that the axiom's requirements are actively met.

The distinction between "the system doesn't do X" and "the system actively does Y" is where most governance frameworks stop. Proving that you don't violate a rule is easier than proving that you fulfill a requirement. The sufficiency probes are the mechanism that bridges that gap.

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
