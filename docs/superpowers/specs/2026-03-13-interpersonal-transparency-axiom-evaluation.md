# Interpersonal Transparency — Axiom Evaluation

**Date:** 2026-03-13
**Status:** Evaluation / Pre-ratification
**Depends on:** Spatial awareness research (2026-03-13), axiom registry

---

## 1. Candidate Axiom

### Proposed Text (draft)

> The system must not maintain persistent state about any non-operator person without an active consent contract. A consent contract requires explicit opt-in, grants the subject inspection access to all data the system holds about them, and is revocable by either party at any time — upon revocation, the system purges all subject-specific state.

### Proposed Properties

| Property | Value | Rationale |
|----------|-------|-----------|
| id | `interpersonal_transparency` | |
| weight | 88 | Above management_governance (85), below corporate_boundary (90). See §4. |
| type | hardcoded | Cannot be softcoded — the constraint protects people who have no access to the system config. |
| scope | constitutional | Applies to all system behavior, not a single domain. See §3. |
| domain | null | Constitutional scope has no domain. |

---

## 2. Durability Evaluation

Applying durability criteria from constitutional design literature, FIPPs, Ostrom's commons principles, and reciprocal transparency frameworks.

### 2.1 Abstract Over Mechanism ✓

The axiom says *what must hold* (consent required, inspection available, revocation purges) without specifying *how* (no mention of MQTT, GPS, APIs, or specific sensor types). It would survive:
- Adding new sensor types (cameras, microphones, biometrics)
- Changing transport layers (MQTT → HTTP → whatever comes next)
- Expanding the person set (wife today, guests tomorrow, collaborators later)
- Technology evolution (phones → wearables → ambient sensing)

The Fair Information Practice Principles have survived 50+ years using this same pattern. GDPR's principle-based approach has outlasted HIPAA's prescriptive approach.

### 2.2 Specific Enough to Violate ✓

Clear violation examples:
- **T0 violation:** System stores wife's GPS coordinates without a consent contract → blocked
- **T0 violation:** System models a guest's presence pattern (arrival/departure history) without consent → blocked
- **T1 violation:** System maintains subject data but provides no inspection mechanism → review
- **T1 violation:** Revocation doesn't purge all subject-specific state → review

This is the "adaptability paradox" sweet spot: specific enough to have teeth, abstract enough to apply across contexts.

### 2.3 Self-Enforcing ✓

The operator is both the governed and the governor (per `single_user` axiom). The consent contract is enforceable because:
- The operator creates and manages contracts
- The system can structurally enforce "no contract → no data flow" at the PerceptionBackend level
- SDLC hooks can scan for non-operator person modeling without contract references

However, this raises a genuine weakness: **the subject has no enforcement power within the system**. They cannot file a complaint or trigger an audit. This is mitigated by:
- The contract grants inspection access (the subject can *see* what's stored)
- Either party can revoke (the subject can withdraw consent)
- The axiom is hardcoded (the operator cannot waive it, even for convenience)

### 2.4 Survives the Brin/Mann Critique ⚠️ (partial)

Reciprocal transparency frameworks (sousveillance, Transparent Society) assume roughly symmetric power. The operator-subject relationship here is asymmetric: the operator controls the system, the subject does not. Pure reciprocity would require the subject to have a comparable system — which is unrealistic.

**Mitigation:** The axiom doesn't claim symmetry. It claims a *minimum floor*: the subject can inspect what the system holds about them. This is closer to GDPR's "right of access" (Article 15) than to Brin's full reciprocal transparency. That's appropriate — we're not building mutual surveillance, we're constraining a single-user system that models other people.

### 2.5 Accommodates Edge Cases ✓

**Environmental vs. personal sensing:** The axiom explicitly covers *persistent state about a specific person*, not transient environmental perception. VAD detecting a voice in the room = environmental. "Wife arrived home at 18:30" = personal modeling. This line is clear and enforceable.

**Visitors and transient persons:** A guest walks through the studio and appears on a webcam feed. If the system doesn't persist anything about them specifically, no contract is needed. If it starts tracking "Ryan's friend visits Tuesdays," that's personal modeling and requires a contract.

**Derived/inferred state:** "Wife is probably on her way because she usually leaves work at 17:00" — this is inferred state about a non-operator person. The axiom covers it: persistent inference counts as persistent state.

---

## 3. Scope Decision: Constitutional vs. Domain

### Arguments for Constitutional
- The constraint protects people who have no voice in the system's governance
- It applies everywhere the system could model a person (voice, perception, management, spatial)
- It cannot be domain-restricted without leaving gaps (what domain is "wife's location" in?)
- The existing constitutional axioms constrain *what the system can be*, and this belongs in that category

### Arguments for Domain
- Only relevant when the system has sensors that can track non-operator persons
- Could be scoped to a "perception" or "spatial" domain

### Decision: Constitutional

The domain argument is weak because the boundary of "which domain touches other people" is impossible to draw cleanly. Management already touches other people (team members). Voice perception touches other people (voices in the room). Spatial awareness touches other people (wife's location). A domain scope would need to be listed in every domain, which is equivalent to constitutional scope with extra bookkeeping.

---

## 4. Weight Decision

### Existing Weights
| Axiom | Weight | Scope |
|-------|--------|-------|
| single_user | 100 | constitutional |
| executive_function | 95 | constitutional |
| corporate_boundary | 90 | domain |
| management_governance | 85 | domain |

### Analysis

`interpersonal_transparency` should be:
- **Below corporate_boundary (90):** Corporate boundary protects an employer — a legal entity with contractual power over the operator. Interpersonal transparency protects household members — closer, more trust, less formal power.
- **Above management_governance (85):** Management governance constrains how the system handles work relationships. Interpersonal transparency constrains something more fundamental: whether the system is permitted to model a person at all.

**Proposed weight: 88.**

### Conflict Analysis

Does this axiom conflict with any existing axiom?

**`su-privacy-001`** (T0, single_user implication): "Privacy controls, data anonymization, and consent mechanisms are unnecessary since the user is also the developer."

This implication applies to the operator's own data. The new axiom applies to *non-operator persons*. There is no direct conflict — `su-privacy-001` does not say "consent mechanisms for third parties are unnecessary." However, the *spirit* of `su-privacy-001` (no consent overhead) is in tension with the *spirit* of `interpersonal_transparency` (consent required for third-party data).

**Resolution:** `su-privacy-001` should be amended to explicitly scope itself: "Privacy controls and consent mechanisms *for the operator's own data* are unnecessary." This makes the non-conflict explicit.

**`single_user`** (weight 100): "All decisions must be made respecting and leveraging [the single-user fact]."

No conflict. The new axiom doesn't introduce multi-user features. It constrains how the single-user system handles data about people who are *not* users. The system remains single-user; it just has rules about modeling non-users.

---

## 5. Contract Concept Evaluation

### What Is a Contract in This System?

A contract is **a new runtime concept** — an artifact the axiom requires before certain data flows are permitted. The hierarchy:

```
Axiom (constitutional constraint — what contracts can exist)
  └── Contract (bilateral agreement — what data flows are permitted)
       └── Data flow (runtime behavior — actual sensor data)
```

This mirrors the legal hierarchy of norms: constitution → statute → contract. Each level constrains the one below.

### Contract Properties

| Property | Type | Purpose |
|----------|------|---------|
| id | str | Unique identifier |
| parties | tuple[str, str] | Operator + subject (by name) |
| scope | list[str] | What data categories are permitted (e.g., "coarse_location", "presence", "biometrics") |
| direction | str | "one_way" (system observes subject) or "bidirectional" (subject gets reciprocal access) |
| visibility_mechanism | str | How the subject inspects data (e.g., "web_dashboard", "shared_document", "on_request") |
| created_at | datetime | When consent was granted |
| revoked_at | datetime | None if active |
| revocation_purge_confirmed | bool | Whether purge has been executed |

### Contract Durability

Is the *concept* of a contract durable? Yes — it maps to:
- GDPR's lawful basis for processing (consent is one of six)
- HIPAA's authorization forms
- OAuth's consent screens (scope + revocation)
- Ostrom's collective-choice arrangements (affected parties participate in rule-making)

The abstraction has survived across legal and software systems for decades.

### Contract Storage

Contracts should live in `axioms/contracts/` alongside `axioms/implications/` and `axioms/registry.yaml`. They are governance artifacts, not runtime data. Format: YAML with the same schema discipline as implications.

### Contract Enforcement

The system enforces contracts at two levels:
1. **Design time:** SDLC hooks scan for non-operator person modeling without contract references (like existing axiom scanning)
2. **Runtime:** PerceptionBackends that ingest third-party data must check for an active contract before updating Behaviors. The MQTTBackend (or any backend receiving phone/location data) would call a `contract_check(person_id, data_category)` function before proceeding.

---

## 6. Assumptions Checked

| Assumption | Valid? | Notes |
|------------|--------|-------|
| single_user axiom doesn't address third parties | ✓ | Confirmed by reading registry.yaml — exclusively about the operator |
| su-privacy-001 applies only to operator data | ⚠️ | Text says "the user is also the developer" — doesn't explicitly exclude third parties. Needs amendment. |
| Contracts are a new concept | ✓ | No existing contract/consent mechanism in the codebase |
| Wife would consent to coarse location sharing | Unverified | Requires actual conversation — the system must not assume consent |
| MQTT is the right transport for distributed sensors | Likely ✓ | But not relevant to the axiom — the axiom is transport-agnostic |
| The axiom survives adding new person types (guests, collaborators) | ✓ | The contract mechanism scales to any number of subjects |
| Environmental sensing doesn't require consent | ✓ | As long as no persistent state about a specific person is derived |

---

## 7. Recommendation

**Ratify `interpersonal_transparency` as a constitutional axiom at weight 88, hardcoded.**

Immediate actions:
1. Add to `axioms/registry.yaml`
2. Derive implications (T0: no persistent third-party state without contract; T1: inspection mechanism required; T1: revocation purges; T2: contract audit trail)
3. Amend `su-privacy-001` to explicitly scope to operator data
4. Create `axioms/contracts/` directory with schema
5. Implement `shared/consent.py` — `contract_check()`, `load_contracts()`, `purge_subject()`

Deferred actions (blocked on contract with wife):
6. Create first contract (operator + wife, scope: coarse_location)
7. Deploy sensor infrastructure per spatial awareness plan

---

## 8. Draft Registry Entry

```yaml
- id: interpersonal_transparency
  text: >
    The system must not maintain persistent state about any non-operator
    person without an active consent contract. A consent contract requires
    explicit opt-in by the subject, grants the subject inspection access
    to all data the system holds about them, and is revocable by either
    party at any time. Upon revocation, the system purges all
    subject-specific persistent state.
  weight: 88
  type: hardcoded
  created: "2026-03-13"
  status: active
  supersedes: null
  scope: constitutional
  domain:
```
