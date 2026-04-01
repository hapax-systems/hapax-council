# CPAL Phase 4: Grounding Control + Daemon Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the grounding ledger into the CPAL control law as the control variable, unify impingements as conversational events, and create the CPAL async runner that can replace CognitiveLoop.

**Architecture:** Three new modules: grounding bridge (adapts existing ledger to CPAL), impingement adapter (routes impingements through CPAL gain/error), and CPAL runner (async loop replacing CognitiveLoop). No existing daemon code is deleted in this phase — the runner is a parallel path that can be enabled via config.

**Depends on:** Phase 1-3 (merged)

---

### File Structure

| File | Responsibility |
|---|---|
| `agents/hapax_daimonion/cpal/grounding_bridge.py` | Adapts GroundingLedger to CPAL control law inputs |
| `agents/hapax_daimonion/cpal/impingement_adapter.py` | Routes impingements through CPAL gain and error modulation |
| `agents/hapax_daimonion/cpal/runner.py` | Async run loop using CPAL evaluator — replaces CognitiveLoop |
| `tests/hapax_daimonion/test_grounding_bridge.py` | Grounding state to error signal mapping |
| `tests/hapax_daimonion/test_impingement_adapter.py` | Impingement to gain/error modulation |
| `tests/hapax_daimonion/test_cpal_runner.py` | Runner tick lifecycle |

---

### Task 1: Grounding Bridge

Adapts the existing `GroundingLedger` (which tracks DU states and computes GQI) to provide the inputs the CPAL control law needs: `ungrounded_du_count`, `repair_rate`, `gqi`, and grounding outcomes for hysteresis.

### Task 2: Impingement Adapter

Routes DMN impingements, stimmung shifts, and system alerts through the CPAL control loop. Instead of separate speech recruitment, impingements adjust the reference signal (what mutual understanding should include) and modulate loop gain. Priority is determined by error magnitude, not routing tables.

### Task 3: CPAL Runner

The async run loop that replaces CognitiveLoop. Ticks at ~150ms, drives the perception stream from audio frames, runs the evaluator, dispatches composed actions through the production stream. Manages the full lifecycle: audio input -> perception -> formulation -> evaluator -> tier composer -> production.
