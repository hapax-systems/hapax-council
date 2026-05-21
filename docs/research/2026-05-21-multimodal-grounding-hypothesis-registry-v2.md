---
type: research-artifact
task_id: 20260509-multimodal-grounding-phase2c-hypothesis-registry
title: "Multimodal Grounding Hypothesis Registry v2 (Phase 2)"
authority_case: CASE-20260509-MULTIMODAL-
created_at: 2026-05-21
supersedes: 2026-05-20-multimodal-grounding-hypothesis-registry.md
---

# Multimodal Grounding Hypothesis Registry v2

Phase 2 revision of the hypothesis registry. Extends H1–H9 from Phase 1c with
two new hypotheses (H10, H11) derived from the grounding inventory audit.
Experiment designs refined with specific Phase 2 task mappings. Classifications
unchanged pending empirical results from Phase 2a/2b/2c.

Machine-readable source: `2026-05-21-multimodal-grounding-hypothesis-registry-v2.yaml`

## Summary Table

| ID | Name | Classification | Phase 2 Role | Tested By |
|----|------|---------------|--------------|-----------|
| H1 | Cross-modal coordination necessity | contested | deferred | Phase 4 |
| H2 | Perceptual grounding reduces hallucination | untested | indirect | Phase 2b (partial) |
| H3 | Temporal freshness is primary constraint | supported | contextual | Phase 2c (indirect) |
| H4 | Self-perception enables aesthetic self-correction | untested | none | Phase 3 |
| H5 | Audio grounding bypasses text mediation | untested | **primary** | Phase 2b |
| H6 | Perceptual assertions need different tracking | supported | indirect | Phase 2c (indirect) |
| H7 | Embodiment strengthens CHI contribution | supported | none | Independent |
| H8 | Publication evidence can include perception | untested | none | Independent |
| H9 | Multimodal grounding needed for livestream quality | untested | indirect | Phase 4 |
| H10 | Specialized grounders outperform unified VLM | untested | **primary** | Phase 2a/2b |
| H11 | Text reduction destroys relevant signal | untested | **primary** | Phase 2c |

## Phase 2 Focus

Three hypotheses are primary targets for Phase 2 empirical evaluation:

1. **H5** (audio grounding utility) — tested by Phase 2b via three sub-tests:
   pyannote speaker detection, CLAP scene classification, Essentia music analysis
2. **H10** (specialized vs unified) — partially tested by Phase 2a/2b: if CPU-only
   tools suffice, the question of VRAM-consuming alternatives is deprioritized
3. **H11** (text reduction destroys signal) — tested by Phase 2c via direct
   comparison of text-mediated vs. structured-JSON paths on same audio events

## Changes from v1

- **Added H10:** Specialized audio grounders vs unified VLM (from REQ H5).
  Phase 1c omitted this because the REQ framing was abstract; Phase 1a inventory
  audit made it concrete by showing _clap.py already exists on CPU.
- **Added H11:** Text reduction destroys grounding-relevant signal. Phase 1a
  inventory audit identified three PRIMARY BOTTLENECK sites; this hypothesis
  directly tests whether the bottleneck matters for hapax's use cases.
- **Added phase2_experiment_map:** Explicit mapping between Phase 2 tasks and
  hypotheses, enabling the Gate 2 synthesis to update classifications
  mechanically from empirical results.
- **Added req_numbering_reconciliation:** Traces REQ H1–H7 to registry H-numbers,
  resolving the numbering divergence between the parent request and Phase 1c.
- **Refined experiment designs:** Each hypothesis now has phase assignment and
  explicit dependency list, clarifying execution order.
- **Restored from deletion:** v1 was accidentally removed in PR #3580; this v2
  supersedes and extends it.

## REQ Numbering Reconciliation

| REQ | Registry | Resolution |
|-----|----------|------------|
| REQ-H1 | H1 | Direct match |
| REQ-H2 | — | Subsumed into H1 experiment condition B |
| REQ-H3 | — | Subsumed into H1 experiment condition C |
| REQ-H4 | — | Deferred to Phase 5 per REQ |
| REQ-H5 | H10 | New hypothesis, specialized vs unified |
| REQ-H6 | — | AffordancePipeline tested implicitly via H1 |
| REQ-H7 | H5 | Audio grounding bypasses text |

## Gate 2 Update Protocol

When Phase 2a/2b/2c complete, the Gate 2 synthesis task
(`20260509-multimodal-grounding-phase2-gate-findings-synthesis`) will:

1. Read the `phase2_experiment_map` from the YAML
2. For each `tests_hypotheses` entry, update classification based on results
3. For each `contributes_evidence_to` entry, add evidence to supporting/contradicting
4. Produce a go/no-go recommendation for Phase 3 based on updated classifications
