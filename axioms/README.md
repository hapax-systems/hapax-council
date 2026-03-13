# axioms/ — Constitutional Governance

This directory contains the formal governance infrastructure that constrains every agent, every code path, and every operational workflow in hapax-council. The system borrows from constitutional law, common law precedent, and statutory interpretation — not as metaphors but as executable mechanisms with runtime enforcement.

## Why Governance as Architecture

Most software systems encode policy as configuration: feature flags, role-based access control, rate limits. These mechanisms are designed to be changed — a product manager flips a toggle, a deploy rolls out new permissions. The assumption is that the humans operating the system share context about what the system should and shouldn't do, and that they'll update the policy when circumstances change.

hapax-council has a different constraint profile. It is a single-operator system where LLM agents perform unsupervised work — processing meeting transcripts, updating context about people, generating notifications, controlling cameras and microphones. The agents are capable of constructing code paths that violate the operator's values in ways that would be difficult to detect after the fact. A sync agent could persist behavioral patterns about a household member. A management agent could generate coaching language about a direct report. A perception backend could accumulate biometric data without consent.

The axiom system addresses this by making certain constraints structurally unrelaxable. They are not configuration that can be updated through a normal code review. They are constitutional principles with formal enforcement at commit time, at runtime, and in the precedent record. Violating a T0 implication is not a bug to be triaged — it is a structural failure that tools prevent before it reaches review.

## The Five Axioms

The axioms are defined in `registry.yaml`. Each has a weight (0–100) that determines priority when axioms conflict, a type (hardcoded or softcoded), and a scope (constitutional or domain).

| ID | Weight | Type | Scope | Constraint |
|----|--------|------|-------|------------|
| `single_user` | 100 | hardcoded | constitutional | One operator. No authentication, no roles, no multi-user abstractions. Absolute. |
| `executive_function` | 95 | hardcoded | constitutional | Zero-config agents. Errors include next actions. Routine work automated. State visible without investigation. |
| `corporate_boundary` | 90 | softcoded | domain: infrastructure | Work data stays in employer systems. Home infrastructure is personal + management-practice only. |
| `interpersonal_transparency` | 88 | hardcoded | constitutional | No persistent state about non-operator persons without an active, revocable consent contract. |
| `management_governance` | 85 | softcoded | domain: management | LLMs prepare context; humans deliver feedback. No generated coaching language about individuals. |

**Hardcoded** axioms are system invariants that cannot be specialized per domain. **Softcoded** axioms can be refined for specific domains while preserving the core constraint. **Constitutional** scope means the axiom applies system-wide; **domain** scope means it applies within a specific subsystem (management, infrastructure) and can be overridden by constitutional axioms of higher weight.

### The Weight System

Weights are not priorities for a scheduler. They resolve conflicts when two axioms produce opposing guidance. If `corporate_boundary` (90) says "route all inference through LiteLLM on the home network" but `executive_function` (95) says "the agent must work with zero configuration," then executive_function prevails — the agent must degrade gracefully when LiteLLM is unreachable, not fail with a configuration error.

The `single_user` axiom at weight 100 is absolute. No other axiom, no operational pressure, no convenience argument overrides it. Code that introduces identity models, role enumerations, authentication middleware, or multi-tenant data partitions is structurally blocked.

## Implication Derivation

Each axiom generates concrete, testable implications through an interpretive process that uses four canons borrowed from legal reasoning:

**Textualist**: What does the axiom text literally say? `single_user` says "one operator" — this means no identity management classes, no access control functions, no multi-account UI.

**Purposivist**: What goal does the axiom serve? `executive_function` exists to accommodate ADHD and autism as genuine cognitive constraints. An error message that says "check logs for details" violates the purpose even if it doesn't violate the literal text, because it requires sustained attention and task-switching that the axiom exists to eliminate.

**Absurdity doctrine**: Reject interpretations that produce absurd results. `single_user` doesn't mean the system can't have a login screen to protect the local interface from physical access — that would be absurd. It means the login doesn't create an identity or imply that other operators could exist.

**Omitted-case canon**: What does silence mean? `management_governance` says "LLMs prepare context; humans deliver feedback." It does not say "LLMs may generate suggested feedback language for humans to edit." The silence is intentional — the canon says don't add what the axiom chose not to include.

Each implication has an ID (e.g., `su-auth-001`), a tier (T0–T3), an enforcement mode, and the canon that produced it. The ~81 implications across the five axioms are stored in `implications/` as YAML files.

## Enforcement Tiers

| Tier | Action | Mechanism |
|------|--------|-----------|
| **T0** | Blocked | Claude Code hooks scan every file write, edit, commit, and push against 20 regex patterns. A PR that introduces prohibited scaffolding never reaches review. |
| **T1** | Flagged | Requires human review before merging. The SDLC axiom gate (Haiku) flags T1 implications for operator attention. |
| **T2** | Advisory | Automated warnings in agent output. Non-blocking but logged. |
| **T3** | Lint | Documentation and style-level guidance. No automated enforcement. |

### Commit-Time Enforcement

Two shell scripts in `hooks/scripts/` implement structural prevention:

**`axiom-scan.sh`** runs on every Edit or Write tool call. It extracts the content being written, strips comments, and scans against T0 violation patterns. A match produces an error with the matched line, the violated implication, and a recovery suggestion. The file write is blocked.

**`axiom-commit-scan.sh`** runs on every `git commit` or `git push`. It scans staged changes (for commits) or branch diffs (for pushes) against the same patterns. A T0 match blocks the commit.

Both scripts source `axiom-patterns.sh`, which defines 20 regex patterns covering prohibited structural categories: identity/access-control scaffolding, multi-account and multi-tenant abstractions, content-sharing and collaboration features, and management safety boundaries (generated feedback or coaching language about individuals). The patterns are calibrated to catch class and function definitions that introduce these categories, not incidental mentions in documentation.

The patterns skip axiom enforcement files themselves (to avoid false positives on the patterns that define the patterns) and common build artifacts.

### Runtime Enforcement

`shared/axiom_enforcement.py` provides two compliance-checking paths:

**Hot path** (`check_fast`) — sub-millisecond, no I/O. Pre-compiled `ComplianceRule` objects extract keywords from T0 implications and match them against a situation description using co-occurrence (2+ keywords from the same implication). Suitable for VetoChain predicates in the perception pipeline where governance decisions happen at audio-processing cadence.

**Cold path** (`check_full`) — full I/O. Loads axioms and implications from YAML, searches the Qdrant precedent store for semantically similar situations, and returns a comprehensive `ComplianceResult` with violation details, axiom IDs, and precedent matches. Used by agents making governance decisions that aren't time-critical.

## The Precedent System

When an axiom implication encounters a novel situation — one that the implication text doesn't clearly resolve — the decision is recorded as a **precedent**. This is the common law mechanism: consistency over time without requiring that every edge case be specified in advance.

### Structure

Each precedent (`axiom_precedents.py`) records:
- **Situation**: What was being decided
- **Decision**: `compliant`, `violation`, or `edge_case`
- **Reasoning**: Why this decision was made
- **Distinguishing facts**: The key facts that drove the decision (for future matching)
- **Authority**: `operator` (weight 1.0), `agent` (weight 0.7), or `derived` (weight 0.5)

The authority hierarchy implements **vertical stare decisis**: an operator decision outweighs an agent decision on the same situation, and an agent decision outweighs a derived one. When an agent records a precedent, it has `authority="agent"` — it stands until the operator reviews and either ratifies or overrides it.

### Storage and Retrieval

Precedents are stored in the `axiom-precedents` Qdrant collection (768-dimension embeddings via nomic-embed-text-v2-moe). When a new situation arises, `PrecedentStore.search(axiom_id, situation)` embeds the situation text and finds the most semantically similar precedents, filtered by axiom and excluding superseded entries. This means the system can find relevant precedents even when the exact wording differs.

~23 seed precedents in `precedents/seed/` establish the initial case law across architecture decisions, management boundaries, and executive function patterns.

### Supremacy Analysis

`validate_supremacy()` in `axiom_registry.py` checks for structural conflicts between domain and constitutional axioms. When a domain axiom's T0 implication overlaps with a constitutional axiom's T0 implication, the tension is flagged as a `SupremacyTension` for operator review. Constitutional axioms always prevail — a domain axiom cannot override a constitutional right.

## Implication Modes

Each implication operates in one of two modes:

**Compatibility** (negative constraint) — "What must NOT happen." The system checks that no code path violates the constraint. Example: `su-auth-001` — "All authentication, authorization, and identity management code must be removed or disabled." Enforcement: pattern matching, code scanning.

**Sufficiency** (positive constraint) — "What MUST be present." The system checks that a required capability exists. Example: `ex-alert-001` — "The system must have proactive alerting for all critical state changes." Enforcement: sufficiency probes that verify the capability is wired and functional.

The distinction matters because compatibility violations are detectable by scanning (the forbidden thing is present), while sufficiency violations require probing (the required thing is absent). The enforcement infrastructure handles both through `AuditFinding` objects with `FindingKind.VIOLATION` and `FindingKind.SUFFICIENCY`.

## Agent Integration

Two pydantic-ai tools in `shared/axiom_tools.py` expose the governance system to LLM agents:

**`check_axiom_compliance(situation, axiom_id, domain)`** — Runs the cold path compliance check and returns violations or compliant status. Agents call this when making decisions that might touch axiom boundaries.

**`record_axiom_decision(axiom_id, situation, decision, reasoning, tier, distinguishing_facts)`** — Records a new precedent with `authority="agent"`. Called by agents after making a governance-relevant decision, creating the case law record for future reference.

Both tools log usage to `AXIOM_AUDIT_DIR/tool-usage.jsonl` for observability.

## The Consent Framework

The `interpersonal_transparency` axiom (weight 88, constitutional) creates the hardest constraint in the system after single-user: no persistent state about non-operator persons without an active, revocable consent contract.

The `contracts/` directory (currently empty — no contracts have been established yet) is where bilateral consent agreements will be stored. Each contract must enumerate:
- The specific data categories permitted (presence, biometrics, coarse location, etc.)
- An explicit opt-in mechanism (not implied from behavior)
- Subject inspection access (the person can see what the system holds about them)
- Revocation by either party with full data purge
- Audit trail (timestamp, parties, scope, revocation status)

The `ConsentRegistry` (`shared/consent.py`) gates data flows at the ingestion boundary. In the voice daemon, `SpeakerIdentifier.identify_audio()` checks `ConsentRegistry.contract_check(person_id, "biometric")` before processing embeddings for non-operator persons. Without a contract, identification returns `uncertain` and enrollment raises `ValueError`. The gate is at the perception boundary — before embeddings are extracted, before state is persisted, before any downstream processing occurs.

## Directory Structure

```
axioms/
├── registry.yaml                    5 axiom definitions (SchemaVer 1-0-0)
├── implications/
│   ├── single-user.yaml            23 implications (su-*)
│   ├── executive-function.yaml     35+ implications (ex-*)
│   ├── corporate-boundary.yaml     7 implications (cb-*)
│   ├── interpersonal-transparency.yaml  9 implications (it-*)
│   └── management-governance.yaml  7 implications (mg-*)
├── precedents/
│   └── seed/
│       ├── single-user-seeds.yaml       4 seed precedents
│       ├── executive-function-seeds.yaml 3 seed precedents
│       ├── management-seeds.yaml        4 seed precedents
│       ├── architecture-seeds.yaml      12 seed precedents
│       └── sufficiency-seeds.yaml
├── contracts/                       Consent contracts (empty — none established)
│   └── .gitkeep
└── schemas/
    ├── axiom.schema.json            Axiom definition schema
    ├── implication.schema.json      Implication schema (tier, canon, mode)
    └── precedent.schema.json        Precedent schema (authority, stare decisis)
```

Enforcement modules in `shared/`:
```
shared/
├── axiom_registry.py       Load axioms, implications, validate supremacy
├── axiom_enforcement.py    Hot path (check_fast) + cold path (check_full)
├── axiom_precedents.py     Qdrant-backed precedent store
├── axiom_audit.py          Unified AuditFinding types
├── axiom_patterns.py       Pattern-based T0 violation scanning
├── axiom_tools.py          Pydantic AI agent tools (check + record)
├── axiom_derivation.py     LLM-based implication generator
└── axiom_patterns.txt      20 regex patterns for structural violations
```

Hook scripts in `hooks/scripts/`:
```
hooks/scripts/
├── axiom-scan.sh           Edit/Write tool protection
├── axiom-commit-scan.sh    Git commit/push protection
└── axiom-patterns.sh       Shared T0 pattern definitions
```
