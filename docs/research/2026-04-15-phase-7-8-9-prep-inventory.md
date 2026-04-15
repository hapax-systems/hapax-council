# LRR Phase 7/8/9 pre-substrate prep inventory

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #131)
**Scope:** For LRR Phases 7 (persona/posture/role), 8 (objectives), and 9 (closed-loop feedback/narration/chat): list substrate-dependent items, substrate-independent items, and specific suggested prep deliverables with size estimates. Goal: amortize the Phase 5 wait window (post-§14, blocked on alt-substrate selection) into prep progress on 3 downstream phases.
**Register:** scientific, neutral
**Per:** alpha's gap proposal F (inflection `20260415-173500`, §1.F)

## 1. Headline

**Alpha + beta can advance ~60% of Phase 7 + ~50% of Phase 8 + ~40% of Phase 9 prep work without waiting for alt-substrate ratification.** Specifically:

- **Phase 7:** persona/posture/role spec authoring is largely substrate-independent — the spec is a YAML file at `axioms/persona/hapax-livestream.yaml` that describes the role stance, engagement commitments, and scientific register. Only the "make the persona survive the substrate's system-prompt compliance behavior" requirement is substrate-dependent.
- **Phase 8:** content programming via research objectives is mostly substrate-independent — the objective schema, attention-bid channel spec, and governance budget ledger are all substrate-agnostic. Only objective-driven LLM call wiring is substrate-specific.
- **Phase 9:** closed-loop feedback + narration involves `/dev/shm` SHM publishers that are substrate-independent (editor state, git state, CI state). Only the narration consumer + live commit narration is substrate-dependent.

## 2. Phase 7 — Persona / Posture / Role Spec Authoring

### 2.1 Goal (per LRR epic spec)

Author the persona / posture / role spec. Make the persona survive Hermes 3's "aggressively system-prompt compliant" substrate. Wire VOLATILE-band system-prompt injection.

### 2.2 Substrate-dependent items (WAIT)

| Item | Why substrate-dependent |
|---|---|
| **P7.dep1** — "make persona survive Hermes 3's system-prompt compliance" | Hermes 3 specifically named; post-§14 the substrate is undefined, so the concrete compliance-behavior target is unknown. Needs alt-substrate selection first. |
| **P7.dep2** — VOLATILE-band injection format validation against substrate | Substrate-specific system-prompt format (e.g., ChatML vs Alpaca vs plain); needs the real substrate to test. |
| **P7.dep3** — Persona grounding evaluation against `claim-shaikh-sft-vs-dpo` | The claim depends on substrate pair (originally Qwen vs Hermes); post-§14 the pair is undefined. |

### 2.3 Substrate-independent items (PREP NOW)

| Item | Substrate-independent reason |
|---|---|
| **P7.indep1** — Author `axioms/persona/hapax-livestream.yaml` schema | YAML schema + role stance + engagement commitments are entirely conceptual; no substrate-specific details |
| **P7.indep2** — Draft the `role`, `posture`, `personality`, `engagement_commitments` sections | All four sections derive from DF-1 theoretical grounding (Clark & Brennan, I-2 role resolution, P-4/P-6) — pure concept |
| **P7.indep3** — Author the register spec (`scientific_neutral_with_sudden_concreteness`) | Register is a stylistic constraint, independent of substrate |
| **P7.indep4** — Draft the GDO § 3.1 ethical engagement commitments table (thermometer_not_scoreboard, measure_structure_not_quality, fixed_transparent_relationship) | Pulled directly from existing GDO doc; zero substrate dependency |
| **P7.indep5** — Author `docs/superpowers/specs/2026-04-XX-lrr-phase-7-persona-spec-design.md` (spec doc itself) | Spec doc is prose, not substrate-specific |

### 2.4 Suggested prep deliverables

#### P7.prep-A — Persona YAML draft + spec doc

**Estimate:** ~300 LOC (150 YAML + 150 markdown spec). ~1 session.

**What ships:**
- `axioms/persona/hapax-livestream.yaml` with draft role/posture/personality/engagement_commitments
- `docs/superpowers/specs/2026-04-XX-lrr-phase-7-persona-spec-design.md` (spec doc for future execution session)

**Branch-only** commit; does not merge to main until Phase 7 open (then unblock + merge).

**Substrate-dep items to append at Phase 7 open:** P7.dep1 + P7.dep2 added as a § 0.5 amendment block once alt-substrate is known.

#### P7.prep-B — Engagement commitments cross-reference audit

**Estimate:** ~100 LOC research doc. ~30 min.

**What ships:**
- `docs/research/2026-04-XX-phase-7-engagement-commitments-crossref.md` mapping each engagement commitment to its existing source (GDO §3.1, token pole design principles, P-4/P-6)

**Branch-only** commit.

**Purpose:** ensures the persona spec does not drift from source documents. Phase 7 authoring session can reference directly.

### 2.5 Phase 7 substrate-dep vs indep split

| | Substrate-dep | Substrate-indep |
|---|---|---|
| Count | 3 items | 5 items |
| Estimated effort | ~40% | ~60% |

**Alpha recommendation:** file P7.prep-A + P7.prep-B as queue items now.

## 3. Phase 8 — Hapax Content Programming via Research Objectives

### 3.1 Goal (per LRR epic spec)

Programmatic content via research objectives (I-3 resolution). Attention-bid channel as a shared mechanism. Governance budget ledger consumption.

### 3.2 Substrate-dependent items (WAIT)

| Item | Why substrate-dependent |
|---|---|
| **P8.dep1** — Objective-driven LLM call wiring | Needs substrate's tool-call / function-calling API to be confirmed |
| **P8.dep2** — Spawn budget ledger integration with live LLM calls | Depends on substrate cost model (per-token rates for budget accounting) |
| **P8.dep3** — `attention_bid` mechanism consumer integration | Downstream consumer of LRR Phase 8 → HSEA Phase 5 M1 biometric reuse; needs substrate to validate the bid channel format |

### 3.3 Substrate-independent items (PREP NOW)

| Item | Substrate-independent reason |
|---|---|
| **P8.indep1** — Author research objective schema (YAML/Pydantic) | Schema is conceptual data structure, not substrate-specific |
| **P8.indep2** — Draft the attention-bid channel spec (`/dev/shm/hapax-attention/bids.jsonl` format) | File format is independent of LLM substrate |
| **P8.indep3** — Draft the HSEA Phase 0 0.2 spawn budget ledger interface contract | Budget ledger is the HSEA Phase 0 deliverable; interface spec is substrate-independent |
| **P8.indep4** — Author `docs/superpowers/specs/2026-04-XX-lrr-phase-8-objectives-design.md` (spec doc) | Prose spec |
| **P8.indep5** — Draft the objective types taxonomy (e.g., `research-question`, `measurement-capture`, `axis-exploration`) | Conceptual taxonomy |

### 3.4 Suggested prep deliverables

#### P8.prep-A — Research objective schema + attention-bid format

**Estimate:** ~250 LOC (100 LOC Python Pydantic + 100 LOC markdown spec + 50 LOC example YAML objectives). ~1 session.

**What ships:**
- `shared/research_objective.py` with `ResearchObjective` Pydantic model
- `docs/superpowers/specs/2026-04-XX-lrr-phase-8-objectives-design.md`
- Example objective YAML at `axioms/objectives/example-phase-a-baseline.yaml`

**Branch-only** commit.

#### P8.prep-B — attention-bid channel spec

**Estimate:** ~120 LOC markdown. ~45 min.

**What ships:**
- `docs/superpowers/specs/2026-04-XX-attention-bid-channel-design.md` documenting the `/dev/shm/hapax-attention/bids.jsonl` format, consumer interface, and governance budget integration

**Branch-only** commit.

**Purpose:** enables parallel HSEA Phase 5 M1 work to start prototyping the biometric reuse path without waiting for LRR Phase 8 execution.

### 3.5 Phase 8 substrate-dep vs indep split

| | Substrate-dep | Substrate-indep |
|---|---|---|
| Count | 3 items | 5 items |
| Estimated effort | ~50% | ~50% |

## 4. Phase 9 — Closed-Loop Feedback + Narration + Chat Integration

### 4.1 Goal (per LRR epic spec)

Closed-loop feedback from narration consumers (daimonion) + chat reactor + live code narration via `/dev/shm` SHM publishers.

### 4.2 Substrate-dependent items (WAIT)

| Item | Why substrate-dependent |
|---|---|
| **P9.dep1** — Live code narration (daimonion speaking recent commits) | Uses substrate LLM to generate narration text; substrate-specific voice/quality tradeoff |
| **P9.dep2** — Narration consumer error handling (FSM recovery narration from HSEA Phase 7 D-cluster) | Consumer format depends on substrate's streaming output format |
| **P9.dep3** — Chat reactor → LLM-mediated response | Substrate latency + cost model affects reactor design |
| **P9.dep4** — CI-watch triager (HSEA Phase 11 G15 extension) | Depends on substrate's ability to read + narrate CI output |

### 4.3 Substrate-independent items (PREP NOW)

| Item | Substrate-independent reason |
|---|---|
| **P9.indep1** — `/dev/shm/hapax-editor-state.json` publisher | SHM publisher is a simple file writer; no LLM involvement |
| **P9.indep2** — `/dev/shm/hapax-git-state.json` publisher | Ditto — git log/status extraction is substrate-independent |
| **P9.indep3** — `/dev/shm/hapax-ci-state.json` publisher | CI API polling → SHM write; substrate-independent |
| **P9.indep4** — Author SHM publisher interface contract (shared with HSEA Phase 7/11 consumers) | Contract is format spec; substrate-independent |
| **P9.indep5** — Draft closed-loop feedback policy doc | Policy is operational, not substrate-specific |

### 4.4 Suggested prep deliverables

#### P9.prep-A — SHM publisher stubs (all 3)

**Estimate:** ~300 LOC Python (3 publishers × ~100 LOC) + ~100 LOC tests. ~1-2 sessions.

**What ships:**
- `agents/editor_state_publisher.py` → `/dev/shm/hapax-editor-state.json`
- `agents/git_state_publisher.py` → `/dev/shm/hapax-git-state.json`
- `agents/ci_state_publisher.py` → `/dev/shm/hapax-ci-state.json`
- 3 systemd user units + timers
- Tests for each publisher

**Branch-only** commit.

**Purpose:** unblocks downstream consumers (HSEA Phase 7 D-cluster, HSEA Phase 11 G15) to prototype against real SHM state.

#### P9.prep-B — SHM publisher contract spec

**Estimate:** ~80 LOC markdown. ~30 min.

**What ships:**
- `docs/superpowers/specs/2026-04-XX-lrr-phase-9-shm-publishers-design.md` documenting the 3 SHM file formats + update cadence + consumer guarantees

**Branch-only** commit.

### 4.5 Phase 9 substrate-dep vs indep split

| | Substrate-dep | Substrate-indep |
|---|---|---|
| Count | 4 items | 5 items |
| Estimated effort | ~60% | ~40% |

Phase 9 has the highest substrate-dependency ratio of the three phases. Still, ~40% of prep work is shippable now.

## 5. Unified prep plan

### 5.1 Session allocation (alpha + beta)

| Session | Prep items | Total sessions |
|---|---|---|
| alpha-1 | P7.prep-A (persona YAML + spec) | 1 |
| alpha-2 | P8.prep-A (objective schema + attention-bid) | 1 |
| alpha-3 | P9.prep-A (SHM publishers) | 1-2 |
| beta-1 | P7.prep-B (engagement commitments audit) | 0.5 |
| beta-2 | P8.prep-B (attention-bid spec) | 0.5 |
| beta-3 | P9.prep-B (SHM publisher contract) | 0.5 |

**Total:** ~5-6 sessions across alpha + beta. Parallelizable by phase (alpha on P7/P8/P9, beta on same phases but different artifacts).

### 5.2 Execution order

Phase 7 prep can ship first (most substrate-independent items at 60%). Phase 8 second (50%). Phase 9 last (40%).

### 5.3 What this prep does NOT do

- **Does not execute any of the phases.** Prep is spec/schema/stub authoring only. Phase execution happens post-alt-substrate-ratification.
- **Does not modify the LRR epic spec.** Prep outputs live in `docs/superpowers/specs/` as new sibling specs + `axioms/` as new data; the epic spec remains unchanged.
- **Does not unblock Phase 5.** The substrate gate is still the critical-path blocker. Prep work runs in parallel to substrate selection.

## 6. Follow-up queue items (proposed)

```yaml
id: "143"  # or next
title: "P7.prep-A — Persona YAML + spec doc draft"
description: |
  Per queue #131 Phase 7 prep inventory. Draft the persona YAML +
  Phase 7 spec doc. Substrate-dep items (P7.dep1-3) deferred to
  Phase 7 open. ~300 LOC, 1 session.
priority: normal

id: "144"  # or next
title: "P8.prep-A — Research objective schema + attention-bid"
description: |
  Per queue #131 Phase 8 prep inventory. Draft research objective
  schema + attention-bid channel format. ~250 LOC, 1 session.
priority: normal

id: "145"  # or next
title: "P9.prep-A — SHM publisher stubs (3 files)"
description: |
  Per queue #131 Phase 9 prep inventory. Ship the 3 SHM publisher
  daemons (editor/git/ci state). Unblocks HSEA Phase 7/11 consumer
  prototyping. ~300 LOC, 1-2 sessions.
priority: normal

id: "146"
title: "P7.prep-B — Engagement commitments cross-reference audit"
priority: low
size_estimate: "~100 LOC, ~30 min"

id: "147"
title: "P8.prep-B — attention-bid channel spec"
priority: low
size_estimate: "~120 LOC, ~45 min"

id: "148"
title: "P9.prep-B — SHM publisher contract spec"
priority: low
size_estimate: "~80 LOC, ~30 min"
```

Delta can pick up any or all of these during next refill.

## 7. Cross-references

- LRR epic spec: `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §§ Phase 7, 8, 9
- Drop #62 §14: Hermes abandonment (creates the substrate wait window)
- Drop #62 §2: fold-in matrix (rows 15 = daimonion narration, 16 = attention bid)
- Queue item #122: cross-epic dependency graph (identifies Phase 7/8/9 as downstream of substrate gate)
- Alpha's gap proposal F: inflection `20260415-173500` §1.F
- Workspace CLAUDE.md § "Key Services" — `hapax-daimonion` is the narration consumer

## 8. Closing

Phase 7 + 8 + 9 have substantial substrate-independent prep work (60% + 50% + 40% respectively). Alpha recommends filing P7.prep-A, P8.prep-A, P9.prep-A, P7.prep-B, P8.prep-B, P9.prep-B as follow-up queue items. Total ~5-6 session effort; parallelizable; amortizes the Phase 5 substrate gate wait window.

Branch-only commit per queue item #131 acceptance criteria.

— alpha, 2026-04-15T19:27Z
