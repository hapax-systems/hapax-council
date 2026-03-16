# Consent-Gated Retrieval: IFC Patterns for Query-Time Consent Filtering

**Date**: 2026-03-15
**Status**: Research complete, patterns extracted
**Context**: ConsentGatedWriter handles persistence. This research addresses the harder problem: filtering at retrieval/query time, real-time perception gating, and graceful degradation.

---

## 1. Retrieval-Time Consent Filtering

### The Problem

Data stored before consent infrastructure existed (pre-existing Qdrant collections, markdown files with person mentions) now needs consent-aware filtering at query time. The ConsentGatedWriter gates persistence but says nothing about reads.

### Pattern A: Query-by-Label (from IFDB / Myers-Liskov DLM)

IFDB (MIT, Schultz/Liskov) extends PostgreSQL with decentralized information flow control at the row level. The key insight: **every row carries a security label, and queries automatically filter rows whose labels don't flow to the querier's clearance**.

**How it maps to hapax-council:**
- Each Qdrant point and each markdown file already carries (or should carry) a `ConsentLabel` via the `Labeled[T]` wrapper
- At query time, the retrieval layer computes a **consent filter** from the active `ConsentRegistry`
- Points whose `person_ids` metadata includes non-consented persons are excluded from results *before* they reach the LLM

**Implementation pattern:**
```
query_filter = build_consent_filter(registry.active_contracts)
# Qdrant payload filter: exclude points where person_ids ∩ non_consented ≠ ∅
results = qdrant.search(vector, filter=query_filter)
```

This is **early binding** (pre-retrieval filtering) — the LLM never sees non-consented data. Preferred over late binding (post-generation redaction) because it prevents information leakage through LLM reasoning.

### Pattern B: Two-Phase Retrieval (from Secure RAG literature)

AWS and recent academic work (SAG framework, August 2025) describe a two-phase approach:

1. **Semantic search** returns candidate results with metadata
2. **Policy filter** removes results that violate access control before passing to LLM

The policy filter is where consent checking happens. This is essentially IFDB's query-by-label adapted for vector databases where you can't do row-level SQL predicates but *can* filter on payload metadata.

### Pattern C: Retroactive Labeling for Legacy Data

For data that predates consent labels:
- **Batch scan**: Run a person-mention detector (NER or regex) over existing collections, tag points with `person_ids` metadata
- **Quarantine-on-ambiguity**: If a point *might* mention a non-operator person but detection is uncertain, label it `consent_required: true` — it gets filtered until explicitly cleared
- Oracle Label Security and PostgreSQL `SECURITY LABEL` both support retroactive label application without modifying the underlying data

### Concrete Recommendation

Add a `ConsentGatedReader` that mirrors `ConsentGatedWriter`:
- Wraps Qdrant search and markdown file reads
- Accepts the query + current `ConsentRegistry`
- Filters results by checking `person_ids` metadata against active contracts
- Logs filtered-out results to audit (count only, not content) for transparency
- Returns only consent-clean results to the caller

---

## 2. Graceful Degradation Patterns

### The Binary Trap

Most access control is binary: allow or deny. This destroys utility. The research shows four non-binary degradation levels, ordered by information preservation:

### Level 1: Full Access (consent active)
"You have a meeting with Sarah at 3pm to discuss the Q2 budget."

### Level 2: Abstraction (no name consent, but event consent exists)
"You have a meeting with 1 person at 3pm to discuss the Q2 budget."

Person identity is replaced with a count. The meeting, time, and topic survive. This is the **generalization** pattern from anonymization literature — reduce precision on the sensitive dimension while preserving analytical value on other dimensions.

### Level 3: Existence Acknowledgment (no consent at all for this person)
"You have a meeting at 3pm. Some details are withheld pending consent."

The operator knows *something* exists. They can seek consent proactively. This avoids the information-loss problem of total suppression.

### Level 4: Total Suppression (required for certain data categories)
Result omitted entirely. Only appropriate when even acknowledging the existence of the data would violate consent (e.g., someone's presence at a sensitive location).

### Key Design Principle: Degradation Should Be Per-Field, Not Per-Record

From the data anonymization patterns literature (EuroPLoP 2024): the four anonymization design patterns — Generalization, Hierarchical Generalization, Suppress Outliers, Relocate Outliers — all operate on *fields within a record*, not entire records. This means:

- A calendar event can show time + topic but abstract the attendee
- A voice transcript can show "someone said [topic]" without identifying who
- A profile fact can show the behavioral category without the person reference

This maps cleanly to your existing `ConsentLabel` + `Labeled[T]` system. The label determines *which fields* get degraded, not whether the whole record is visible.

### Implementation Pattern: Degradation Functions

```python
def degrade_for_consent(record: dict, person_ids: set[str], registry: ConsentRegistry) -> dict:
    """Apply per-field degradation based on consent status."""
    non_consented = {p for p in person_ids if not registry.contract_check(p, "identity")}
    if not non_consented:
        return record  # Level 1: full access

    result = dict(record)
    if registry.contract_check(next(iter(non_consented)), "presence"):
        # Level 2: abstract identity, preserve event
        result["participants"] = f"{len(person_ids)} people"
        result.pop("participant_names", None)
    else:
        # Level 3: existence only
        result["participants"] = "[withheld pending consent]"
        result.pop("participant_names", None)
        result.pop("topic", None)  # topic might identify the person
    return result
```

### Prior Art: Apple Intelligence's Degradation Model

Apple Intelligence (2025-2026) implements a three-tier degradation:
1. **On-device**: Full access to all personal data, processed locally
2. **Private Cloud Compute**: Reduced data sent to Apple silicon servers, ephemeral, never stored
3. **Third-party models**: Only user-approved data forwarded, with explicit per-request consent

The key insight: **the degradation is invisible to the user**. When a task requires cloud processing, Apple doesn't show "[CLOUD REQUIRED]" — it just processes locally with reduced capability. The user experiences slightly less capable results, not a brick wall.

---

## 3. Real-Time Consent Gating for Perception

### The Detection-Before-Consent Paradox

To know you need consent for a person, you must first detect them. But detection itself is processing. This is a genuine philosophical tension, but it has practical resolutions.

### Resolution: The Detection/Identification Split

The academic literature (PMC 11256005, USENIX 2023) draws a clear line:

- **Detection**: "A person is present" — low-risk, no identity processing, no consent required
- **Identification**: "That person is Sarah" — requires consent
- **Characterization**: "That person seems upset" — requires consent (inference about a specific person)

This maps to a three-stage pipeline:

```
Camera/Mic Input
    │
    ▼
Stage 1: DETECT (consent-free)
    "N persons present, M known, K unknown"
    │
    ├─ For known persons with consent → Stage 2
    ├─ For known persons without consent → BLUR/MUTE + log
    └─ For unknown persons → ABSTRACT + prompt for consent
          │
          ▼
Stage 2: IDENTIFY (consent-gated)
    "Person X is speaking" — only if contract_check(X, "presence") passes
    │
    ▼
Stage 3: CHARACTERIZE (consent-gated, category-specific)
    "Person X said Y" — only if contract_check(X, "voice_content") passes
```

### The Bystander Problem (from Smart Home Literature)

ACM TOCHI (2025, Bystander Privacy in Smart Homes systematic review) identifies the core challenge: **bystanders in smart homes cannot meaningfully consent because they often don't know devices are collecting data**.

Their proposed solutions:
- **Least-privilege sensing**: Collect only what's needed (e.g., detect presence via IR, not camera)
- **Ambient notification**: Physical indicators (LEDs, sounds) that data collection is active
- **Bystander opt-out**: A mechanism for non-primary users to signal "don't process me"

For hapax-council, the practical mapping:
- The studio compositor already has camera feeds. When a non-consented person is detected (face not in enrollment DB, or enrolled but no contract), the system should:
  1. Continue detecting their *presence* (count of persons) — this is consent-free
  2. Blur their face/voice in any persisted data — already handled by ConsentGatedWriter
  3. **Not reason about them** in any LLM call — this is the new requirement
  4. Prompt the operator to facilitate consent if appropriate

### What "Not Reason About" Means Technically

The LLM context window is the enforcement boundary. If non-consented person data enters the prompt, the LLM *will* reason about it — you can't prevent that. Therefore:

**The filter must be pre-prompt, not post-generation.**

This means the `ConsentGatedReader` pattern from Section 1 applies to perception data too. The perception pipeline should:
1. Detect and identify (on-device, ephemeral)
2. Filter based on consent status
3. Pass only consent-clean data to LLM agents

Ephemeral on-device processing for detection/identification is analogous to Apple's on-device model — the data never leaves the local processing boundary, is never persisted, and is used only to make the consent decision.

---

## 4. Redaction vs Suppression vs Abstraction vs Annotation

### Pattern Comparison

| Pattern | Example | Utility | Privacy | UX | When to Use |
|---------|---------|---------|---------|-----|-------------|
| **Redaction** | "Meeting with [REDACTED] at 3pm" | Medium | High | Poor — breaks reading flow, feels hostile | Legal/compliance contexts; audit logs |
| **Suppression** | *(result omitted)* | Low | Highest | Poor — user doesn't know what they're missing | When even existence leaks information |
| **Abstraction** | "Meeting with 1 person at 3pm" | High | High | Good — reads naturally, preserves context | **Default for most cases** |
| **Annotation** | "Meeting with Sarah* at 3pm" *(consent pending)* | Highest | Low | Good — transparent, but shows non-consented data | Only when data was collected *with* prior consent that has since lapsed |

### Recommendation: Abstraction as Default, with Layered Escalation

1. **Default**: Abstraction. Replace person-specific fields with aggregate or categorical substitutes.
   - Names → count ("3 people")
   - Quotes → topic summary ("discussed budget")
   - Face → blur or silhouette
   - Voice → "someone spoke about [topic]"

2. **On request**: Annotation. If the operator explicitly asks "who was in that meeting?", show annotated results that make consent status visible: "Sarah (consent: active), [1 person without consent]". This respects the operator's need to know while making the consent gap transparent.

3. **For audit/legal**: Redaction. The audit log shows that data existed and was filtered, with enough metadata for the operator to reconstruct what happened without exposing the non-consented data.

4. **Never by default**: Suppression. Total suppression should only apply to data categories where existence itself is sensitive (none of the current hapax-council use cases require this).

### The Google Federated Learning Insight

Google's federated learning with differential privacy (deployed in Gboard) provides a useful analogy: **user-level DP ensures the model's output distribution doesn't change even if all of one user's data is removed**. The consent-aware retrieval system should aspire to a similar property: the operator's experience should degrade gracefully, not catastrophically, when one person's consent is missing.

In practice: if 5 people attended a meeting and 1 lacks consent, the operator should get 80% of the value, not 0%.

---

## 5. Prior Art Summary

### GDPR Right to Be Forgotten (RTBF)

The EDPB Guidelines 5/2019 on RTBF for search engines established:
- **Delisting ≠ deletion**: Search results are suppressed for name-based queries, but the underlying data may persist. This is exactly the abstraction pattern — the data exists, but retrieval is filtered.
- **Balancing test**: RTBF is not absolute. There's a balancing test between the data subject's rights and the public interest. For hapax-council, the analogous balance is between the non-consented person's privacy and the operator's executive function needs.
- **Implementation**: Google's RTBF implementation uses metadata flags on search index entries. When a RTBF request is granted, the entry is flagged and filtered from results when the query matches the person's name. The data itself is not deleted from the index.

**Mapping to hapax-council**: This is the `ConsentGatedReader` pattern. Qdrant points get `consent_status` metadata. The reader filters at query time based on metadata, not by deleting vectors.

### Apple On-Device Processing

Apple Intelligence's architecture (2025-2026):
- 3B parameter model runs on-device for most tasks — personal data never leaves the device
- Private Cloud Compute for complex tasks — data is ephemeral, processed on Apple silicon servers, never stored
- Third-party model access requires explicit per-request user approval

**Mapping to hapax-council**: The perception pipeline (camera, mic) should process detection/identification on-device (the Pi or local GPU). Only consent-cleared data flows to LLM agents via LiteLLM. Non-consented person data is processed ephemerally for detection purposes only, then discarded.

### IFDB / Decentralized Label Model

Myers-Liskov DLM (Cornell/MIT):
- Security labels are pairs of (owner, reader-set)
- Labels form a lattice; data can only flow to labels that are at least as restrictive
- IFDB implements this for PostgreSQL with row-level label filtering

**Mapping to hapax-council**: `ConsentLabel` already implements a lattice. The missing piece is query-time enforcement — currently labels are checked at write time only. Adding read-time filtering completes the DIFC property.

### Anonymization Design Patterns (EuroPLoP 2024)

Four patterns: Generalization, Hierarchical Generalization, Suppress Outliers, Relocate Outliers. All operate per-field. The key insight for hapax-council: degradation granularity should be *per-field within a record*, not per-record.

### Bystander Privacy in Smart Homes (ACM TOCHI 2025)

Systematic review establishing that bystander consent in ambient sensing environments requires:
- Awareness mechanisms (the bystander must know collection is happening)
- Opt-out mechanisms (the bystander must be able to refuse)
- Least-privilege sensing (collect minimum needed)
- Collective consent models (not just individual)

---

## 6. Concrete Next Steps for hapax-council

### Immediate (wire into existing infrastructure)

1. **ConsentGatedReader**: New class in `shared/governance/consent_gate.py` that wraps Qdrant search and markdown reads with consent filtering. Mirrors ConsentGatedWriter's API.

2. **Retroactive labeling**: Batch job to scan existing Qdrant collections (`profile-facts`, `documents`) and tag points with `person_ids` metadata based on NER/regex person detection.

3. **Degradation functions**: Utility module that takes a record + consent status and returns the appropriate degradation level (abstraction by default).

### Medium-term (perception pipeline)

4. **Three-stage perception gate**: Detection (consent-free) → Identification (consent-gated) → Characterization (consent-gated, per-category). Wire into studio compositor.

5. **Ephemeral processing boundary**: Ensure detection/identification happens in a scope that is never persisted and never forwarded to LLM context.

### Design decisions needed

6. **Should the operator be told *why* results are degraded?** Recommendation: yes, with a count. "3 results filtered due to pending consent." This preserves the operator's ability to seek consent without exposing the filtered data.

7. **What about voice transcripts that mention non-consented persons by name?** The transcript itself is operator speech (consented). The *mention* of another person creates a derived-data problem. Recommendation: abstract at retrieval time — "you mentioned [a person] in the context of [topic]" — rather than suppressing the entire transcript.

---

## Sources

- [IFDB: Decentralized Information Flow Control for Databases](http://pmg.csail.mit.edu/papers/ifdb.pdf) — Schultz/Liskov, MIT
- [Protecting Privacy using the Decentralized Label Model](https://www.cs.cornell.edu/andru/papers/iflow-tosem.pdf) — Myers/Liskov, Cornell
- [Secure Multifaceted-RAG: Hybrid Knowledge Retrieval with Security Filtering](https://www.mdpi.com/2078-2489/16/9/804)
- [Provably Secure Retrieval-Augmented Generation (SAG)](https://arxiv.org/html/2508.01084)
- [Secure RAG: Preventing Data Leakage with Provenance and Policy Enforcement](https://computerfraudsecurity.com/index.php/journal/article/view/976)
- [Rethinking Privacy in ML Pipelines from an IFC Perspective](https://arxiv.org/html/2311.15792)
- [Information Flow Control for Comparative Privacy Analyses](https://dl.acm.org/doi/10.1007/s10207-024-00886-0)
- [Bystander Privacy in Smart Homes: A Systematic Review](https://dl.acm.org/doi/10.1145/3731755) — ACM TOCHI 2025
- [Privacy Perceptions and Designs of Bystanders in Smart Homes](https://dl.acm.org/doi/10.1145/3359161)
- [Data Autonomy and Privacy: The Case for a Privacy Smart Home Meta-Assistant](https://link.springer.com/article/10.1007/s00146-025-02182-4)
- [Tangible Privacy: User-Centric Sensor Designs for Bystander Privacy](https://dl.acm.org/doi/10.1145/3415187)
- [Beyond Surveillance: Privacy, Ethics, and Regulations in Face Recognition](https://pmc.ncbi.nlm.nih.gov/articles/PMC11256005/)
- [Patterns of Data Anonymization](https://dl.acm.org/doi/10.1145/3698322.3698337) — EuroPLoP 2024
- [Anonymization: The Imperfect Science](https://www.science.org/doi/10.1126/sciadv.adn7053) — Science Advances
- [Federated Learning with Formal Differential Privacy Guarantees](https://research.google/blog/federated-learning-with-formal-differential-privacy-guarantees/) — Google Research
- [Federated Learning's Consent Crisis](https://secureprivacy.ai/blog/consent-orchestration-federated-learning)
- [EDPB Guidelines 5/2019: Right to be Forgotten for Search Engines](https://www.edpb.europa.eu/sites/default/files/files/file1/edpb_guidelines_201905_rtbfsearchengines_afterpublicconsultation_en.pdf)
- [Apple Intelligence and Privacy](https://support.apple.com/guide/iphone/apple-intelligence-and-privacy-iphe3f499e0e/ios)
- [Apple's Privacy-First AI Strategy: On-Device LLMs by 2026](https://www.webpronews.com/apples-privacy-first-ai-strategy-on-device-llms-by-2026/)
- [Securing AI Agents with Information-Flow Control](https://arxiv.org/pdf/2505.23643) — Costa/Kopf, 2025
- [Empowering Users to Control Privacy in Context-Aware Systems](https://www.researchgate.net/publication/228949408)
- [Protect Sensitive Data in RAG with Amazon Bedrock](https://aws.amazon.com/blogs/machine-learning/protect-sensitive-data-in-rag-applications-with-amazon-bedrock/)
- [Oracle Label Security](https://www.oracle.com/a/tech/docs/dbsec/ols/label-security-datasheet.pdf)
- [PostgreSQL SECURITY LABEL](https://www.postgresql.org/docs/current/sql-security-label.html)
