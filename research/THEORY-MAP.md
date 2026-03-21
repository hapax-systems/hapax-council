# Theory-to-Code Traceability Matrix

Maps theoretical claims from Clark & Brennan (1991), Traum (1994), and Brennan & Clark (1996) to their implementations in hapax-council.

## Core Constructs

| Theoretical Construct | Source | Code Module | Key Function/Class | Tests |
|----------------------|--------|-------------|-------------------|-------|
| Discourse Unit (DU) state machine | Traum 1994 | `grounding_ledger.py` | `DiscourseUnit`, `DUState` | `test_grounding_ledger.py` |
| Grounding criterion ("sufficient for current purposes") | Clark & Brennan 1991 | `grounding_ledger.py` | `_repair_threshold()` | `test_grounding_ledger.py` |
| Acceptance signals (ACCEPT/CLARIFY/IGNORE/REJECT) | Clark & Brennan 1991 | `grounding_evaluator.py` | `classify_acceptance()` | `test_grounding_ledger.py` |
| Contribution-acceptance cycle | Clark & Brennan 1991 | `grounding_ledger.py` | `update_from_acceptance()` | `test_grounding_ledger.py` |
| Repair sequences (rephrase → elaborate → abandon) | Clark & Brennan 1991 | `grounding_ledger.py` | `update_from_acceptance()` state transitions | `test_grounding_ledger.py` |
| Effort calibration (least collaborative effort) | Clark & Brennan 1991 | `grounding_ledger.py` | `effort_calibration()`, `EffortDecision` | `test_grounding_ledger.py` |
| Conceptual pacts (lexical entrainment) | Brennan & Clark 1996, Metzing & Brennan 2003 | `conversation_pipeline.py` | `ThreadEntry`, `_extract_substance()` | `test_thread_entry.py` |
| Common ground accumulation | Clark & Brennan 1991 | `conversation_pipeline.py` | `_render_thread()`, tiered compression | `test_conversational_continuity.py` |
| Grounding Quality Index (GQI) | Novel (composite metric) | `grounding_ledger.py` | `compute_gqi()` | `test_grounding_ledger.py` |
| Strategy directives (advance/rephrase/elaborate/move_on) | Traum 1994 | `grounding_ledger.py` | `grounding_directive()`, `_STRATEGY_DIRECTIVES` | `test_grounding_ledger.py` |

## Measurement Constructs

| Metric | Theoretical Basis | Code Module | Function | Tests |
|--------|------------------|-------------|----------|-------|
| Turn-pair coherence | Replaces word overlap (penalizes abstraction) | `grounding_evaluator.py` | `score_turn_pair_coherence()` | `test_conversational_continuity.py` |
| Context anchor success | Common ground maintenance | `grounding_evaluator.py` | `score_context_anchor()` | `test_conversational_continuity.py` |
| Reference accuracy | Grounding evidence fidelity | `grounding_evaluator.py` | `score_reference_accuracy()` | `test_conversational_continuity.py` |
| Monologic score | RLHF anti-pattern (Shaikh et al. 2024 NAACL) | `grounding_evaluator.py` | `_score_monologic()` | `test_rlhf_monitoring.py` |
| Directive compliance | Strategy execution fidelity | `grounding_evaluator.py` | `score_directive_compliance()` | `test_rlhf_monitoring.py` |

## System Architecture Mappings

| Clark & Brennan Concept | Hapax Implementation | Location |
|------------------------|---------------------|----------|
| Discourse record | STABLE band (conversation thread) | `conversation_pipeline.py` |
| Current purpose | Concern graph (salience router) | `conversation_pipeline.py` |
| Medium constraints | Stimmung (phenomenal context) | `conversational_policy.py` |
| Grounding techniques | VOLATILE band (strategy directives) | `grounding_ledger.py` |
| Costs of grounding | 2D effort calibration (activation x GQI) | `grounding_ledger.py` |
| Shared perceptual context | Environmental context (presence, cameras) | `env_context.py` |

## Critical Decisions

Numbered decisions from [RESEARCH-STATE.md](../agents/hapax_voice/proofs/RESEARCH-STATE.md#critical-decisions-with-reasoning):

| # | Decision | Theoretical Justification |
|---|----------|--------------------------|
| 1 | 3+1 package (3 treatment + 1 diagnostic sentinel) | Ward-Horner & Sturmey 2010: sentinel tests retrieval not grounding |
| 2 | Refine before test | Gestalt: incomplete system can't show emergence |
| 3 | BEST over beta-binomial | Continuous data needs t-distributed likelihood; Shadish et al. 2013 autocorrelation |
| 4 | turn_pair_coherence replaces context_anchor_success | Word overlap penalizes abstraction/paraphrasing |
| 5 | Always CAPABLE model | Intelligence is last thing shed under pressure |
| 6 | Acceptance must actuate (close the loop) | 1/3 of Clark's cycle without actuation |
| 7 | Preserve verbatim operator text | Metzing & Brennan 2003: pact violations maximally costly with known partner |
| 8 | Bands = grounding substrate | STABLE=record, VOLATILE=directives, stimmung=GQI, concern=sufficiency |
| 9 | Every token justified (~800-1000 token prompt) | Experiment isolation |
| 10 | GQI as stimmung dimension | Unidirectional: GQI reads signals, feeds stimmung, no circular dependency |

## References

All code paths are relative to `agents/hapax_voice/`:
- `grounding_ledger.py` — DU state machine, GQI, effort calibration
- `grounding_evaluator.py` — Acceptance classification, scoring, RLHF monitoring
- `conversation_pipeline.py` — ThreadEntry, thread rendering, pipeline integration
- `conversational_policy.py` — Dignity floor, operator style, experiment style
- `persona.py` — System prompts (standard, guest, experiment)
- `env_context.py` — Environmental/perceptual context

All test paths are relative to `tests/hapax_voice/`:
- `test_grounding_ledger.py` — Ledger unit tests
- `test_thread_entry.py` — ThreadEntry and substance extraction
- `test_conversational_continuity.py` — End-to-end continuity
- `test_rlhf_monitoring.py` — Monologic scoring, directive compliance
- `test_memory_integration.py` — Qdrant seed/persist integration
