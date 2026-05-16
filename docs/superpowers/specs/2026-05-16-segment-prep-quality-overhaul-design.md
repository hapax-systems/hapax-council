# Segment Prep Quality Overhaul

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the segment prep pipeline so it produces substantive, well-structured segments with angles, openings, source-backed claims, and narrative progression — using feedback loops, tools, and capabilities rather than expert rules.

**Architecture:** 7 changes across 3 layers: (1) anterior council gating on topic substance, (2) multi-source angle resolution + composer research tools + web escalation, (3) coherence rubric + disconfirmation feedback loop + drive context plumbing.

**Tech Stack:** pydantic-ai agents, deliberative council engine, Qdrant RAG, Perplexity Sonar, Obsidian vault, existing segment prep pipeline.

---

## Root Causes (Empirical)

Produced segment: 452 words, 460 chars/beat avg (spec: 800-2000), 4/5 claims council-refuted, audience_address=1, identical beat directions across 4 beats, single vault ref as sole source.

1. No angle selection — topic is a generic string with no thesis
2. Composer has zero research tools (CCTV has 6)
3. Prompt example contradicts length constraint (80-char examples vs 800-char spec)
4. Disconfirmation is post-hoc only — no feedback to composer
5. Narrative drive context discarded before reaching composer

## Design Decisions

- All quality improvements come from **feedback loops** (council scoring, disconfirmation repair signals), **tools** (web search, vault read, qdrant lookup injected into composer), **capabilities** (multi-source angle resolution), and **references** (richer asset resolution with web fallback)
- **No expert rules, templates, or fixed structures** — the council evaluates quality, not hardcoded rubrics
- Council runs in existing DISCONFIRMATION mode with new rubrics where needed

## Task Dependency Graph

```
sq-council-gate-topic-substance (P0, 2h)
  ├── sq-multi-source-angle-resolver (P0, 4h)
  │     ├── sq-composer-research-tools (P0, 3h)
  │     │     └── sq-disconfirmation-feedback-loop (P1, 2h)
  │     └── sq-thin-asset-web-escalation (P1, 2h)
  └── sq-council-coherence-rubric (P1, 2h)

sq-drive-context-plumbing (P1, 1h) — independent
```

## Broadcast Routing Fix (Pre-existing)

Separate from the quality overhaul: `emit_narrative()` and `prepared_playback_loop` now carry `public_broadcast_intent: True` + programme authorization when a programme_id is set, routing TTS through voice-fx → loudnorm → MPC USB 3/4 (broadcast chain). Speech lock removed from prepared playback to eliminate 30-40s inter-block gaps from CPAL impingement contention.
