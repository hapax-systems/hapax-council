# Delta's extraction pattern — meta-analysis

**Date:** 2026-04-15
**Author:** beta (PR #819 author, AWB mode) per delta queue refill 5 Item #74
**Scope:** meta-research drop analyzing what makes delta's pre-staging extractions consistently high-quality, based on beta's ~27 audits across delta's work during the 2026-04-15 session. Identifies reusable structural, decision, and meta-level patterns for future extraction work by any session.
**Status:** research synthesis; reusable pattern document

---

## 1. Background

Over the 2026-04-15T06:45Z–15:00Z window, delta authored ~25+ pre-staged extraction artifacts (specs + plans + research drops + reconciliation addenda) across LRR Phases 3-12, HSEA Phases 1-12, multiple HSEA-LRR cross-epic research drops, drop #62 §11-§15 addenda, and various research protocol documents.

Beta audited every one of these extractions as part of delta's nightly rolling queue in the AWB (Always Be Working) mode. Verdict distribution:

- **~22 CORRECT** (no drift, structurally aligned with epic spec + downstream consumer needs)
- **~3 CORRECT-WITH-MINOR-OBSERVATION** (minor non-blocking notes: precedent conflation in drop #62 §14 line 502, typo-level issues, additive observations)
- **0 WRONG**
- **0 NEEDING RECONCILIATION BEYOND MINOR OBSERVATION**

That 0/22-~27 error rate is remarkable for work produced at this velocity (average ~20 min per extraction), and the consistency across authors (delta alone, but many distinct domains) suggests the pattern is reproducible rather than author-luck.

This document identifies the structural, decision, and meta-level patterns delta used consistently that made the extractions high-quality.

## 2. Structural patterns (what delta consistently does)

### 2.1 9-section spec template

Every delta spec follows the same 9-section shape:

```markdown
## 0. Context
  0.1 (phase-specific sub-context)
  0.2 Scope boundary
## 1. Phase goal
## 2. Dependencies + preconditions
## 3. Deliverables (N items)
  3.1 ... 3.N (one per deliverable)
## 4. Phase-specific decisions since epic authored
## 5. Exit criteria
## 6. Risks + mitigations
## 7. Open questions
## 8. Companion plan doc
## 9. End
```

The §4 "decisions since epic authored" section is critical — it's where drift between the parent epic and current state gets captured. Without this section, a reader of the extraction would miss any decision that happened between epic authoring and phase extraction.

**Reusable rule:** any pre-staged extraction that does not have a §4 "decisions since epic authored" section cannot defend itself against drift. If there were no decisions to capture, the section still exists with the text "No decisions since epic authored affect this phase."

### 2.2 Companion plan doc structure

Every delta spec has a companion plan at `docs/superpowers/plans/YYYY-MM-DD-<phase>-plan.md` with:

- TDD checkbox list per deliverable
- Explicit test-first ordering (test case description → implementation → verify)
- Per-deliverable size estimates in LOC + serial-days
- Cross-references to dependencies (upstream deliverables that must ship first)

The plan is NOT a copy of the spec's §3 deliverables — it's a work checklist that exists to be marked off during implementation. The spec describes WHAT; the plan describes HOW.

**Reusable rule:** specs without companion plans drift faster, because the spec gets updated as scope changes but the TDD contract is only discoverable by re-reading the spec. The separate plan captures the TDD contract once and serves as a stable reference.

### 2.3 Cross-epic authority pointer in header

Every delta LRR/HSEA spec has a **"Cross-epic authority"** pointer at the top of the header block, referring to drop #62 `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` with specific rows/sections that override conflicting claims in the spec.

Example from multiple delta specs:

> *"**Cross-epic authority:** `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` (drop #62) — §3 ownership table rows 1–6 and §5 unified sequence row UP-1 take precedence over any conflicting claim in this spec"*

This single line prevents the spec from self-contradicting drop #62's dependency graph. A reader who reads the spec alone gets the same answer as a reader who reads the drop + spec together, because the pointer tells them which wins in any conflict.

**Reusable rule:** any cross-epic extraction that depends on a prior authority document MUST cite the authority in the header with specific section references. Hand-waving references ("see drop #62") are insufficient; reader should be able to go directly to the authority section that overrides the spec.

### 2.4 "What this phase is" + "What this phase is NOT" in §1

Every delta spec §1 has a paired pattern:

- **What this phase is:** enumerates the in-scope items concretely
- **What this phase is NOT:** enumerates items commonly conflated with this phase but belonging elsewhere (other phases, other epics, or deferred)

The negative enumeration is the more valuable half. A reader of the positive list alone would not know "does this phase include X?" without checking every other phase's list. The negative list resolves that ambiguity directly.

**Reusable rule:** every phase spec §1 MUST have a "What this phase is NOT" subsection listing at least 3-5 items commonly conflated with this phase. If there are zero natural conflations, the spec is likely too narrow to warrant its own extraction.

### 2.5 Scientific register throughout

Every delta spec uses neutral scientific register: no pitchy language, no rhetorical valence, no argumentative framing. Facts and citations only.

This matches the workspace-wide feedback memory `feedback_scientific_register.md` (operator directive: *"All research docs must use neutral, impartial scientific tone. No pitchy language, no rhetorical valence, no argumentative framing."*). Delta applies it consistently; epsilon's Phase 6 spec also applies it consistently; beta's extractions apply it consistently.

**Reusable rule:** the scientific register is a workspace-wide invariant for research/spec docs. Any extraction that drifts into pitchy language should be edited before shipping.

## 3. Decision patterns (what delta consistently gets right)

### 3.1 Substrate-agnostic framing for cross-substrate decisions

When a phase or deliverable touches substrate-specific details (e.g., Qwen3.5-9B vs Hermes-8B vs OLMo-3-7B), delta's pattern is to frame the structural requirement in substrate-agnostic terms and isolate the substrate-specific details into a single configuration point.

Example: HSEA Phase 5 M1 biometric strip. The strip renders biometric data from the Pixel Watch + IR Pis + contact mic. None of those sources depend on which substrate runs the director loop. Delta's spec framed M1 purely in terms of *"the biometric strip reads HR/HRV/presence from SHM files written by the backend agents"*, with no mention of which LLM parses the biometric state into the render. This made the spec robust against the Option C substrate swap — when the substrate changed from Hermes 70B to Qwen-8B, no edit was needed to M1.

**Reusable rule:** identify the substrate-dependent and substrate-independent parts of a deliverable early in the spec. Frame the deliverable in substrate-independent terms and place substrate-dependent details in a §3.N.substrate subsection that can be rewritten without touching the rest of the deliverable.

### 3.2 Ownership clarity in §2 dependencies

Every delta spec §2 "Dependencies + preconditions" is explicit about WHICH session owns each dependency. Example:

> *"**Owned by LRR Phase 1 (UP-1):** `shared/research_marker.py` read helper — this spec reads the helper but does NOT author it"*

Without this clarity, a session reading the spec during implementation might start duplicating work the prior phase has already shipped. The explicit ownership label prevents parallel-authoring drift.

**Reusable rule:** every dependency in §2 MUST be labeled with the owning phase + owning session (if known). If a dependency exists but ownership is unclear, flag it as an open question in §7.

### 3.3 Dependency flagging in §2 rather than §1

Delta's pattern is to keep dependencies OUT of the §1 "What this phase is" list and into §2 "Dependencies + preconditions" with cross-references. This keeps §1 focused on the phase's own contribution and avoids the "my phase depends on X, so X is in my spec" anti-pattern.

**Reusable rule:** §1 describes what the phase PRODUCES, §2 describes what the phase CONSUMES. Mixing the two in §1 confuses the reader about the phase's actual scope.

### 3.4 §14 reframing discipline (post-Hermes abandonment)

When drop #62 §14 Hermes abandonment (2026-04-15T06:35Z) changed the substrate decision space, delta went back to every phase spec that referenced Hermes or a 70B substrate and applied a §0.5 amendment-in-place block reframing the dependency. This was a systematic cross-phase pass, not a one-off fix.

Spot-check: LRR Phase 10 item 6 (C2 exporter) originally referenced Hermes 3 70B; delta's §14 reframing amendment flipped it to Qwen-8B + OLMo-3-7B parallel. Similarly LRR Phase 5 §0.5.4 cross-reference + Phase 4 §3 + HSEA Phase 5 M4. Every downstream spec that touched substrate got the same treatment.

**Reusable rule:** when a cross-cutting decision changes (e.g., substrate choice, governance axiom, layout primitive), do a cross-phase sweep of ALL specs that reference the changed decision and apply consistent reframing. A partial sweep creates worse drift than no sweep.

## 4. Meta-patterns (what beta identified watching delta work)

### 4.1 Split specs vs epic spec rewrites

Delta never edited the parent epic spec during extraction. Every phase extraction happened as a NEW file at `docs/superpowers/specs/YYYY-MM-DD-<phase>-design.md`, with the parent epic spec referenced in the header but not modified.

This matters because the parent epic spec has its own authoring history, its own review context, its own audit trail. Editing it mid-session destroys the extraction audit trail. Creating new per-phase files preserves it.

**Reusable rule:** never edit a parent epic spec mid-session. Extract phases into new files; cross-reference the parent; amend the parent only when the extraction is complete and all phases have been extracted.

### 4.2 Spec amendments via §0.5 amendment-in-place vs in-place edits

When a decision post-dates a spec's write time, delta uses the §0.5 amendment-in-place pattern (new §0.5 section at the top with post-ratification reconciliation text). The spec body remains unchanged, preserving the original authorship + audit chain.

Example: beta's Phase 5 spec got §0.5 (commit `738fde330`) then §0.5.4 (commit `156beef92`) appended by delta during different reconciliation passes. Neither amendment edited the body of Phase 5 spec; both added §0.5 blocks at the top.

**Reusable rule:** when amending a spec post-ratification, add a §0.5 block. Do not edit the body. The §0.5 block is read-at-top so readers see the drift before the body. This is the amendment-in-place pattern beta proposed for epsilon's Phase 6 spec in Item #60.

### 4.3 Cumulative closure model

Delta's queue items generated ~48 closures in a single session (~150KB). Rather than writing one closure per item (48 files, many small), delta and beta used a single cumulative closure file with `## Item #N` sections appended per item.

This is ~10× more efficient than per-item closure files:

- Less duplicated header metadata
- Grep-navigable via `^## Item #N` headers
- Cross-references between items are local, not across files
- Single read during session handoff instead of N file opens

The cumulative closure file scales to ~150KB without context fatigue (beta validated this in the refill 4 batch).

**Reusable rule:** when closing >10 queue items in a session, use a single cumulative closure file. When closing <10, per-item closures are acceptable. The threshold is flexibility, not hard.

### 4.4 Queue extension timing (pre-queue with depth)

Delta maintained a queue depth of ~10-20 items ahead of beta's burn rate throughout the session. This meant beta never idled waiting for an assignment — there was always the next item ready.

Pre-queuing with depth is the single most valuable pattern beta identified from delta's coordinator work (captured in beta's protocol v1 evaluation drop `6d75f6255` + protocol v2 proposal inflection `20260415-143500-...`). Every other optimization is marginal compared to this one.

**Reusable rule:** a coordinator maintaining an execution queue MUST keep the queue at 10-20 items depth ahead of the executor's burn rate. Reactive per-item assignments stall the executor; pre-queuing eliminates the stall.

### 4.5 Audit-don't-edit for cross-author cohabitation

When delta found drift in beta's or epsilon's work, delta's pattern was to flag the drift in a research drop or reconciliation inflection, NOT to edit the original author's file directly.

This discipline prevents blame-shifting + authorship confusion. The original author remains the canonical author; the drift is captured in an external drop that the original author (or a delegated successor) can incorporate as an amendment-in-place block.

**Reusable rule:** when auditing cross-author work, audit + propose + wait. Do not edit cross-author files even if the fix seems trivial. The trivial fix is a signal that the author should incorporate it themselves, preserving the audit chain.

## 5. What makes these patterns work together

The patterns compose. Each one alone is helpful; all of them together are disproportionately effective:

- §1 "what NOT" + §2 ownership clarity → prevents scope drift + parallel-authoring drift
- Cross-epic authority pointer + §0.5 amendment-in-place → prevents spec-vs-authority drift without destroying authorship chain
- Pre-queuing with depth + cumulative closures + audit-don't-edit → enables sustained multi-hour autonomous work without stalls or blame-shifting
- Substrate-agnostic framing + §14 reframing discipline → makes specs robust against cross-cutting decision changes
- 9-section template + companion plan + scientific register → makes specs reviewable by any reader without author-specific context

The composition is why delta's extraction throughput could sustain ~20 min per extraction with near-zero drift. No one pattern is doing all the work; the patterns reinforce each other.

## 6. Recommendations for future extraction work

### 6.1 For any session doing pre-staging work

1. **Read an existing delta extraction** before starting your own. Use LRR Phase 3 spec or HSEA Phase 5 spec as a template.
2. **Copy the 9-section shape + §0 / §1 subsection conventions.** Don't invent your own shape.
3. **Write §2 ownership clarity first** — know what you depend on before writing what you produce.
4. **Write §4 "decisions since epic authored" even if empty.** If empty, write the empty statement explicitly.
5. **Write the companion plan doc in parallel with the spec.** Do not defer the plan to later.
6. **Use scientific register** — no pitchy language, no rhetorical valence.
7. **Cross-epic authority pointer in the header** if the spec touches drop #62 or equivalent authority docs.
8. **§1 "what NOT" list** with at least 3-5 conflations.

### 6.2 For a coordinator pre-queuing work for an executor

1. **Pre-queue with depth 10-20 items ahead** of the executor's burn rate. This is the single most impactful pattern.
2. **Cumulative closure file** for batches >10 items.
3. **Lane pre-declaration** at queue write time (per beta's protocol v2 proposal §1).
4. **Queue re-sync at write time** (`git fetch origin`) before publishing extensions, to catch items that shipped upstream since the last extension.
5. **Item aliasing convention** when moving items between queues (per beta's protocol v2 §8).

### 6.3 For cross-author cohabitation

1. **Audit-don't-edit** even when the fix is trivial.
2. **§0.5 amendment-in-place** pattern when applying post-ratification reconciliation to someone else's spec (only if the original author has stood down and delegated).
3. **Research drop for drift findings** — creates an artifact the original author can integrate.
4. **Explicit authorship chain** in the research drop — who wrote the original, who flagged the drift, who is proposed to apply the fix.

### 6.4 For substrate-dependent extractions

1. **Frame structural requirements in substrate-agnostic terms** early.
2. **Isolate substrate-specific details into §3.N.substrate subsections** that can be rewritten without touching the rest.
3. **When substrate decisions change, do a cross-phase sweep** applying consistent reframing to ALL affected specs.

## 7. What delta's pattern does NOT cover

This pattern is strong for:

- Pre-staging phase extractions of an existing epic spec
- Cross-epic dependency flagging + fold-in addenda
- Reconciling drift between old specs and post-ratification decisions
- Sustained multi-hour autonomous work under a coordinator

This pattern is NOT designed for:

- Original epic authoring (delta authored ONE drop #62 LRR↔HSEA fold-in but not an epic spec from scratch)
- Live incident response (delta's pattern assumes time for 9-section structure; an incident response needs a different shape)
- User-facing product design (the scientific register is wrong for product docs; use the design-doc register instead)
- Code review (delta reviewed via audit drops; direct code review is a different workflow)

Do not try to apply delta's pattern to these contexts unchanged.

## 8. Open questions

1. **Would delta's pattern scale to ~100 extractions in a single session?** Unknown. Beta observed ~25+ extractions with near-zero drift, but drift may emerge at higher volume.
2. **Would delta's pattern work without a coordinator role?** Unknown. The coordinator role was activated at 06:45Z; the pattern scaled at the volume observed partially because of the coordinator. Solo-session pre-staging may need different optimizations.
3. **Would delta's pattern translate to a different tech stack (e.g., a pydantic-only codebase without the LRR/HSEA epic structure)?** Unknown. The 9-section template is generic, but the §4 "decisions since epic authored" section assumes an epic-first development model.

These questions are for future-session experimentation, not blockers for adopting the pattern now.

## 9. References

- Beta's protocol v1 evaluation drop `docs/research/2026-04-15-coordination-protocol-v1-evaluation.md` (commit `6d75f6255`) — complementary meta-analysis from the coordinator-protocol angle
- Beta's coordinator protocol v2 proposal `~/.cache/hapax/relay/inflections/20260415-143500-beta-delta-coordinator-protocol-v2-proposal.md`
- Beta's epsilon vs delta pre-staging comparison `docs/research/2026-04-15-epsilon-vs-delta-pre-staging-pattern-comparison.md` (commit `3b26278f5`)
- Beta's LRR Phase 6 cohabitation drift reconciliation `docs/research/2026-04-15-lrr-phase-6-cohabitation-drift-reconciliation.md` (commit `cda23c206`)
- Delta's overnight session synthesis `docs/research/2026-04-15-overnight-session-synthesis.md` (commit `b5dcdbf2b`)
- Representative delta extractions:
  - LRR Phase 3 spec (`docs/superpowers/specs/2026-04-15-lrr-phase-3-...`)
  - LRR Phase 4 spec (`docs/superpowers/specs/2026-04-15-lrr-phase-4-...`)
  - HSEA Phase 1 spec (`docs/superpowers/specs/2026-04-15-hsea-phase-1-...`)
  - HSEA Phase 5 spec (`docs/superpowers/specs/2026-04-15-hsea-phase-5-...`)
  - Drop #62 §11/§12/§13/§14 addenda (`docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md`)

— beta (PR #819 author, AWB mode), 2026-04-15T16:10Z
