# Multimodal Grounding Hypothesis Registry

**Authority:** CASE-20260509-MULTIMODAL-
**Date:** 2026-05-20
**Machine-readable:** `2026-05-20-multimodal-grounding-hypothesis-registry.yaml`
**Gate artifact for:** Phase 1 operator review

## Summary

9 hypotheses from 3 research passes. 2 supported, 1 contested, 6 untested.

| ID | Name | Classification | Feasibility |
|----|------|---------------|-------------|
| H1 | Cross-modal coordination necessity | Contested | High |
| H2 | Perceptual grounding reduces hallucination | Untested | High |
| H3 | Temporal freshness is the primary constraint | Supported | Medium |
| H4 | Self-perception enables aesthetic self-correction | Untested | Medium |
| H5 | Audio grounding bypasses text mediation | Untested | High |
| H6 | Perceptual assertions need different tracking | Supported | Low |
| H7 | Embodiment strengthens CHI contribution | Supported | Medium |
| H8 | Perceptual artifacts as publication evidence | Untested | High |
| H9 | Multimodal grounding improves livestream quality | Untested | Low |

## H1: Cross-Modal Coordination Necessity (Contested)

The robotics counter-evidence (subsumption, parallel reactive paths) applies partially but Hapax differs: its perceptual channels feed truth claims, not motor actions. The coordination needed is epistemic (freshness gating), not behavioral (priority arbitration).

## H3: Temporal Freshness (Supported)

The clause verifier and temporal band architecture are purpose-built for freshness. The experiment categorizes 100 failures to confirm staleness dominates.

## H5: Audio Presence Bypass (Untested, High Feasibility)

STT voice activity signal already exists. Experiment compares latency: IR→text→LLM vs. STT activity. 3-day timeline.

## H7: Embodiment + CHI (Supported)

Two-abstract blind expert evaluation. Novelty differentiation + empirical grounding are the supporting arguments.

## Phase 2/3 Experiment Details

**H5 (Phase 2):** Wire `stt_voice_activity_detected` as presence indicator alongside IR path. Measure latency delta from speech onset to presence acknowledgment across 50 events. Implementation: add a `presence_source` field to the perception fusion output that records which channel triggered first. No new hardware required.

**H7 (Phase 3):** Write paired abstracts. Recruit 3 CHI/CSCW reviewers via academic network. Blind evaluation form: novelty (1-5), clarity (1-5), contribution strength (1-5), free-text. 2-week turnaround. Gate: if embodied framing scores higher on average, adopt it for the submission draft.
