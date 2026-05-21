---
title: "CHI 2027 evidence pipeline requirements"
date: 2026-05-21
author: epsilon
status: draft
cc_task: 202605181733-hapax-perspective-phase0-research-chi2027-pipeline
authority_case: CASE-202605181733-HAPAX-P
parent_plan: docs/superpowers/plans/2026-05-17-hapax-perspective-implementation.md
---

# CHI 2027 Evidence Pipeline Requirements

## 1. Submission timeline

| Milestone | Date | Notes |
|-----------|------|-------|
| Track A/B dependencies complete | ~Jun 13, 2026 | Eigenform, governance, voice |
| Data collection window opens | Jun 13, 2026 | 8 weeks minimum |
| Data collection window closes | Aug 8, 2026 | |
| CHI 2027 submission deadline | Sep 10, 2026 | Paper C venue (stretch) |
| Engineering effort budget | ~10 days | Annotation + export + grafting + tests |

Source: `docs/superpowers/plans/publication-strategy.md:238`,
`docs/research/2026-05-21-chi-evidence-pipeline-investigation.md`

## 2. Required evidence artifacts

| Artifact | Source | Transformation | Destination | Status |
|----------|--------|---------------|-------------|--------|
| Eigenform state log | `shared/eigenform_logger.py` → `/dev/shm/hapax-eigenform/` | Time-series extraction + episode segmentation | `scripts/chi-data-export.py` output | Source exists, transform unbuilt |
| Grounding ledger entries | `agents/hapax_daimonion/grounding_ledger.py` → Qdrant `grounding-acts` | Filter by episode window + citation extraction | `scripts/chi-data-export.py` output | Source exists (13.7KB), transform unbuilt |
| Episode annotations | Operator (manual) via `scripts/chi-episode-annotate.py` | Coding tool → structured YAML | CHI paper figures + appendix | Tool unbuilt |
| Grafting condition evaluations | `shared/grafting_conditions.py` | Condition check over eigenform + grounding data | Evidence envelope per episode | Module unbuilt |
| Publication-quality figures | Eigenform + grounding + annotation data | `scripts/chi-data-export.py` → matplotlib/seaborn | Paper submission PDF | Script unbuilt |
| Langfuse trace retention | LLM calls via Langfuse → MinIO blob store | 14-day lifecycle (events/), full retention for traces | CHI reproducibility appendix | Config exists, retention policy active |

## 3. Planned but unbuilt modules

| File | Purpose | Dependencies |
|------|---------|-------------|
| `scripts/chi-episode-annotate.py` | Interactive episode coding tool | Eigenform logger data, grounding ledger |
| `scripts/chi-data-export.py` | Publication-quality figure/data export | All other evidence sources |
| `shared/grafting_conditions.py` | Formal grafting condition definitions | Eigenform logger, stimmung dimensions |
| `tests/shared/test_grafting_conditions.py` | Tests for grafting conditions | `shared/grafting_conditions.py` |

## 4. Data traceability requirements

Each CHI evidence artifact must trace back to Hapax perspective outputs through:

1. **Temporal binding**: Every evidence row carries an ISO-8601 timestamp linkable
   to eigenform state log entries and grounding ledger entries within the same
   episode window.
2. **Episode identity**: Episodes are operator-annotated windows (start/end
   timestamp + coding labels) that group eigenform states and grounding acts
   into coherent analytical units.
3. **Grafting provenance**: Each grafting condition evaluation references the
   specific eigenform state vector and grounding acts that triggered it,
   producing an auditable chain from raw data → condition → evidence claim.
4. **Langfuse trace IDs**: LLM-mediated grounding acts carry Langfuse trace IDs
   that link to the full prompt/completion/tool-use chain for reproducibility.

## 5. Dependency ordering

Per the implementation plan (Track C, Task 10):

```
Track A (eigenform/sensing) ──┐
Track B (governance/voice) ───┤
Track C (CCTV fix, langfuse) ─┴──→ Task 10: CHI evidence infrastructure
```

Task 10 is correctly last because it consumes outputs from all other tracks.
The pipeline is unstarted planned work in its correct dependency position,
not a broken or rescued pipeline.

## 6. Pre-existing research

| Document | Key contribution |
|----------|-----------------|
| `docs/superpowers/plans/2026-05-17-hapax-perspective-implementation.md` | Track C task map, file map, dependency ordering |
| `docs/research/2026-05-21-chi-evidence-pipeline-investigation.md` | Root cause investigation confirming planned-not-broken status |
| `docs/superpowers/plans/publication-strategy.md` | CHI 2027 venue entry, deadline, paper scope |
| `docs/research/grounding-problem-map.md` | Grounding act taxonomy feeding the ledger |
