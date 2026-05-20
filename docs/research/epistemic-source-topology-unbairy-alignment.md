# EQI Source Topology Schema Alignment with Unb-AIRy

**Date:** 2026-05-20
**Authority:** REQ-20260512-epistemic-quality-infrastructure

## 1. Concept Mapping

| EQI Concept | Unb-AIRy Concept | Relationship | Notes |
|-------------|-----------------|--------------|-------|
| `CitationEdge` (proposed) | `Assertion.supersedes` / `superseded_by` | Subset — citation edges generalize the supersession chain | EQI citation edges carry direction + type (supports/contradicts/extends); Unb-AIRy only has supersession |
| `TopologyMetrics` (proposed) | No direct equivalent | New — Unb-AIRy lacks graph-level metrics | Unb-AIRy tracks per-assertion confidence, not graph structure |
| Source provenance | `ProvenanceRecord` | Equivalent — both track extraction source and method | EQI should reuse `ProvenanceRecord`, not create a parallel type |
| Citation target | `Assertion.source_uri` | Related — source_uri identifies where an assertion was extracted from | EQI citation targets point to what an assertion *cites*, not where it *came from* |
| Confidence score | `Assertion.confidence` + `Assertion.score` | Equivalent — EQI quality scores should feed into Unb-AIRy confidence | EQI's 4-axis scores (claim_evidence_alignment, etc.) are more granular than Unb-AIRy's scalar |

## 2. Storage Decision

**Decision: Do NOT add new PostgreSQL tables or Qdrant collections for EQI topology.**

Rationale:
- Unb-AIRy already uses Qdrant `assertions` collection for assertion storage
- Citation edges should be stored as structured payload fields on existing assertions, not as separate graph tables
- Graph metrics are computed at query time from the edge payload, not stored as materialized views

Implementation path:
```yaml
# Add to Assertion payload in Qdrant assertions collection:
citation_edges:
  - target_assertion_id: "asr-xxx"
    edge_type: "supports"  # supports | contradicts | extends | cites
    evidence_strength: 0.8  # 0-1
    
topology_metrics_cache:
  in_degree: 3
  out_degree: 1
  hub_score: 0.4
  authority_score: 0.7
  computed_at: "2026-05-20T00:00:00Z"
```

## 3. Graph Metric Definitions

| Metric | Definition | Deny-Wins Handling |
|--------|-----------|-------------------|
| `in_degree` | Count of citation edges pointing TO this assertion | Missing citations count as 0 (no credit for uncited) |
| `out_degree` | Count of citation edges FROM this assertion | Missing citations count as 0 |
| `hub_score` | HITS algorithm hub value — assertions that cite many authoritative sources | Missing citations yield hub_score = 0 (deny-wins: no citation = no hub credit) |
| `authority_score` | HITS algorithm authority value — assertions cited by many hubs | Missing citations yield authority_score = 0 |
| `citation_chain_depth` | Longest directed path from this assertion to a root source | Broken chains terminate at the break point, not at an estimated depth |
| `contradicted_by_count` | Count of edges with type=contradicts pointing to this assertion | Missing contradictions count as 0 (absence of contradiction is NOT evidence of truth) |

**Deny-wins principle:** Every metric defaults to the least-favorable value when citations are missing. An assertion with no citation edges has zero hub, zero authority, zero chain depth. Missing data never inflates confidence.

## 4. Topology Does Not Equal Truth

**Explicit invariant:** Graph topology metrics (hub_score, authority_score, citation_chain_depth) measure *structural position* in the citation graph, NOT epistemic truth. A well-cited false claim has high authority_score. A true claim with no citations has zero authority_score.

Topology metrics inform reviewer attention allocation (which claims to examine first), not automated truth judgments. The EQI calibration pipeline uses topology as one input alongside human labels, not as a replacement.

## 5. Integration Points

| Surface | EQI Reads From | Unb-AIRy Reads From | Shared |
|---------|---------------|---------------------|--------|
| Assertion storage | Qdrant `assertions` | Qdrant `assertions` | Yes — same collection |
| Provenance | `ProvenanceRecord` | `ProvenanceRecord` | Yes — same model |
| Confidence | EQI 4-axis scores | `Assertion.confidence` | EQI scores feed Unb-AIRy confidence via calibrated mapping |
| Citation graph | Payload `citation_edges` | `supersedes`/`superseded_by` | Partially — EQI edges are richer than supersession |
| Graph metrics | Computed from edges | N/A | EQI-only, not shared |
