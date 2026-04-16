---
title: OSF pre-registration audit — Cycle 2 grounding package
date: 2026-04-16
queue_item: phase-4-osf-prereg
epic: lrr
phase: 4
status: audit
---

# Cycle 2 pre-registration audit — findings + applied edits

Audit of `agents/hapax_daimonion/proofs/CYCLE-2-PREREGISTRATION.md` prior to OSF submission. Operator directed "make it perfect then I'll file." Findings below were all applied inline via the companion PR.

## Findings applied (8)

| # | Section | Finding | Disposition |
|---|---|---|---|
| F1 | Header / §3.2 | Pre-reg framed setting as "Home office" without livestream specification. Contradicts the constitutive LRR principle (2026-04-16 operator directive: livestream IS the research instrument). | **Edited.** §3.2 now specifies 24/7 livestream context, compositor → MediaMTX → YouTube path, and LiteLLM infrastructure state locked for Condition A. |
| F2 | Header / §3.2 | Substrate ambiguity: §3.2 named Claude Opus 4.6 as the LLM, which is actually auxiliary (reasoning/orientation), not the conversational backbone. The substrate under study is Qwen3.5-9B via TabbyAPI `:5000`. Post-2026-04-16 there are TWO viable local substrates (Qwen = Condition A, OLMo-3 = Condition A' via `:5001`). | **Edited.** Header now explicitly locks this pre-reg to Condition A (Qwen3.5-9B). §3.2 clarifies cloud routes are auxiliary only. §9 adds "substrate swap during collection" as deviation-protocol rule that invalidates the pre-reg. |
| F3 | §2.2 | No discussion of how phase transitions work under continuous livestream operation. | **Edited.** §2.2 adds "Livestream context for phase transitions" paragraph describing atomic flag persistence, in-flight DU handling, and stream-continuity semantics at phase boundaries. |
| F4 | §5 | "Session" was undefined in livestream-native terms; exclusion criteria ambiguous for on-stream coding/ambient activity. | **Edited.** New §5.0 "Operational definition of session" defines sessions as contiguous livestream segments bounded by flag-transitions, stream-stops, or explicit operator markers. §5.2 explicitly NOT-EXCLUDES on-stream coding, chat-reading, and ambient activity. |
| F5 | §6.2 | "Operator has ~5-10 sessions per evening" justification reflects a pre-livestream session model. | **Edited.** Reworded to stream-uptime-based session accumulation. |
| F6 | §7.6 | "Code: stats.py (to be updated with BEST implementation before Phase B analysis)" was vague. Current implementation is scipy-analytical-approx; §7.3 priors imply MCMC. | **Edited.** §7.6 now contains an explicit **implementation commitment**: upgrade to PyMC MCMC BEST before first Phase B session is included in any analysis; analytical approximation remains as secondary sensitivity. |
| F7 | Header line 3 | "[TO BE FILLED]" pre-registration date placeholder. | **Edited.** Set to 2026-04-16 (draft); actual registration date to be re-stamped at OSF submission. |
| F8 | §10 | "Lab journal: [GitHub Pages URL — to be enabled]" and related placeholders were stale. | **Edited.** Lab journal placeholder removed (will be added via deviation record if enabled). Added Langfuse trace archive + livestream archive as data-source surfaces. Added reference to durable trace reader `agents/_langfuse_local.py` so trace-level metadata persists past MinIO blob retention. |

## Findings NOT applied (left to operator decision)

| # | Section | Finding | Operator decision needed |
|---|---|---|---|
| N1 | Line 4 | Git commit SHA placeholder is intentional — it will be set when the pre-reg PR merges. This is standard pre-reg practice and was correctly left as a placeholder. | None. |
| N2 | §10 | OSF registration URL is intentionally left as placeholder — filled at the moment of filing. | Fill it in on osf.io at filing time. |
| N3 | §1.1 Title | Title references "voice AI system" without saying "livestream voice AI." The title is the pre-reg's public identifier; changing it is a minor but non-zero risk. | Operator decision: keep as-is (substrate-agnostic and platform-independent title reads better on OSF), or amend to be livestream-specific. My recommendation: **keep as-is** — the pre-reg's ABSTRACT on OSF can mention livestream setting; the title is more durable. |
| N4 | §3.3 Generalizability | Single-case N=1 caveat is strong. Some OSF reviewers may push back on single-case designs. The existing mitigation (Barlow/Nock/Hersen, Shadish autocorrelation) is standard SCED practice. | No action; accept SCED framing. |

## Infrastructure prerequisites (verified 2026-04-16)

Pre-reg assumes these are live; verified during audit:

- ✅ `agents/hapax_daimonion/grounding_evaluator.py:255` exports `score_turn_pair_coherence()` via `nomic-embed-text-v2-moe` (Ollama CPU)
- ✅ All 5 feature flags (`stable_frame`, `grounding_directive`, `effort_modulation`, `cross_session`, `sentinel`) are wired in `conversation_pipeline.py` + `conversational_policy.py`
- ✅ `nomic-embed-text-v2-moe:latest` is loaded in Ollama (957 MB, 5 weeks old)
- ✅ LiteLLM `langfuse` success_callback + failure_callback wired as of 2026-04-16 (LRR Phase 5 closure)
- ⚠️ `stats.py` ships analytical BEST approximation only; PyMC MCMC upgrade is a §7.6 commitment before Phase B analysis

## Path to OSF submission after operator review

1. Operator reviews edits in the companion PR.
2. Operator merges PR. Merge commit SHA is recorded on pre-reg line 4 before OSF upload.
3. Operator creates OSF project per `research/protocols/osf-project-creation.md`.
4. Operator uploads CYCLE-2-PREREGISTRATION.md to OSF project's "Analysis Plan" component.
5. Operator files the registration (this creates an immutable OSF-versioned copy).
6. Operator updates pre-reg line 4 `Registration location` with OSF URL. This update itself is committed as a post-pre-reg metadata update and is not a §9 deviation.
7. Data collection can begin (or continue, if stream is already live).

— beta, 2026-04-16
