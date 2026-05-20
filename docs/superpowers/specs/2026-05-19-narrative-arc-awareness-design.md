# Narrative Arc Awareness — Design Spec

**Goal:** Hapax perceives its own livestream narrative arc as a continuous density signal and plans programmes that respond to macro context (what's been established, audience knowledge state, stream lifecycle) without expert rules.

**Architecture:** Four layers extending existing IDF, affordance pipeline, and programme manager. Each layer produces perception signals; no layer prescribes action.

**Constraint:** `no_expert_system_rules` axiom. Every ordering/selection pressure must emerge from information-theoretic signals, not hardcoded thresholds or sequencing rules.

---

## Layer 1: Stream Biography

A grounding-native self-model populated exclusively by Command-R queries against chronicle and transcript history.

### 1.1 Data Model

- `StreamBiography`: evidence store with `established_concepts`, `introductions`, `narrative_events`, `total_segments_completed`, `total_stream_hours`
- `GroundedConcept`: concept string + evidence_refs (chronicle event IDs) + grounding_confidence + timestamps
- `GroundedIntroduction`: who/what introduced + citing evidence + timestamp

### 1.2 Population

- On show start and after each segment completion, Command-R queries the chronicle: "What concepts has this stream established? Cite specific events."
- Evidence-of-absence is first-class: a null query result for "operator introduction" IS the evidence that no introduction has occurred.
- The biography is append-only from grounded queries. Never written from configuration.

### 1.3 Storage

- `/dev/shm/hapax-compositor/stream-biography.json` for real-time access
- Persisted to `~/hapax-state/stream-biography.jsonl` across sessions

## Layer 2: Narrative Density Source

A new source registered in the existing `InformationDensityField`.

### 2.1 Signals

| Signal | Computation | What it measures |
|--------|------------|------------------|
| `anchor_mi` | MI between rolling transcript embedding and concept anchor embeddings | How much foundational content has been covered |
| `chronicle_entropy` | Shannon entropy over chronicle event-type distribution in current show window | Variety of content produced (low = inchoate) |
| `bocpd_novelty` | BOCPD change-point probability on narrative embedding stream | Phase transition detection |
| `viewer_relevance` | Viewer count normalized to [0,1] with log scaling | Audience presence as relevance weight |

### 2.2 Concept Anchors

Computed once at show start from operator profile (identity dimension), Hapax self-description, current vault goals, active sprint measures. 5-10 embeddings via `nomic-embed-cpu`. Each anchor represents a foundational concept the stream should eventually ground. Near-zero MI against transcript = never grounded.

### 2.3 Integration

Registered as source `"narrative"` in the density field alongside existing perception/stimmung/voice zones. The existing density field composition handles weighting — no special-case logic.

## Layer 3: Audience Perception

### 3.1 Perception Source

New daemon `agents/audience_perception.py` polling YouTube Data API on 2s cadence. Writes to `/dev/shm/hapax-perception/audience.json`. Signals: `viewer_count`, `chat_rate_per_min`, `avg_watch_time_s`, `subscriber_delta`. Zero viewers is a high-confidence signal, not missing data.

### 3.2 Concept Mastery (BKT)

Per-concept Bayesian Knowledge Tracing: `P(audience_knows[X] | evidence)` where evidence = prior segments that explained X (raises posterior), viewer retention during those segments (low retention deflates), chat mentions (confirms reception). Feeds density field as mutual information, not consumed by rules.

### 3.3 ZPD Signal

Concepts where `P(mastery) in [0.3, 0.7]` generate strongest affordance pressure — in the audience's zone of proximal development.

## Layer 4: Programme Affordance Recruitment

### 4.1 Programme Roles as Affordances

Register each role in Qdrant collection `affordances` under family `programme.segment.*`. Each gets Thompson sampling posteriors Beta(2,1), updated by narrative quality outcomes.

### 4.2 Prospective Narrative Quality Scoring

Before committing a segment, evaluate each candidate role through the 7-axis narrative quality rubric hypothetically. An iceberg on enactivism when enactivism was never defined scores low on `information_gap_integrity` and `escalation_architecture`, losing to alternatives that close gaps — not by rule, by score.

### 4.3 Stigmergic Ordering

Completed segments leave density traces: reduce Bayesian surprise on covered topics, increase pressure on adjacent concepts, update BKT posteriors. Ant colony pheromone — trail encodes history and remaining distance.

## Dependency Chain

```
Layer 1 (Stream Biography)    <- no dependencies, ships first
Layer 2 (Narrative Density)   <- depends on Layer 1 for anchor grounding
Layer 3 (Audience Perception) <- independent, parallels Layer 1-2
Layer 4 (Programme Recruitment) <- depends on Layers 1-3
```

## Files to Create/Modify

| File | Action | Layer |
|------|--------|-------|
| `shared/stream_biography.py` | Create | 1 |
| `agents/stream_biography_daemon.py` | Create | 1 |
| `shared/information_density.py` | Modify — add narrative source | 2 |
| `agents/information_density_daemon.py` | Modify — register narrative source | 2 |
| `agents/audience_perception.py` | Create | 3 |
| `shared/concept_mastery.py` | Create — BKT model | 3 |
| `shared/programme.py` | Modify — add affordance registration | 4 |
| `agents/programme_manager/manager.py` | Modify — prospective scoring | 4 |
| `agents/hapax_daimonion/programme_loop.py` | Modify — feed biography to planner | 4 |

## Research Sources

- Schulz et al. 2024 "Narrative Information Theory" (arXiv 2411.12907)
- Adams & MacKay 2007 (BOCPD)
- Bayesian Knowledge Tracing (Corbett & Anderson 1995)
- Deep Knowledge Tracing (Piech et al. 2015)
- Grey Area ZPD model (EDM 2017)
- Guinaudeau & Strube entity-level entropy (arXiv 1507.08234)
- BOCPD text segmentation (arXiv 2601.18788)
