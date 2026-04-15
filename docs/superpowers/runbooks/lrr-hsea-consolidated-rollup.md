# LRR + HSEA Consolidated Epic Rollup

**Epics:** Livestream Research Ready (LRR, 11 phases 0–10) + Hapax Studio Executive Agent (HSEA, 13 phases 0–12)
**Scope:** Both epics side-by-side in one document
**Status snapshot:** 2026-04-15
**Author:** alpha (queue #160)
**Depends on:** queue #147 LRR execution state runbook (shipped PR #926)
**Cross-references:** drop #62 cross-epic fold-in (docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md) + queue #122 cross-epic dependency graph

---

## §0. TL;DR

| Epic | Phases in motion/closed | Specs on main | Plans on main | Structural gaps |
|---|---|---|---|---|
| **LRR** (11 phases 0–10) | 8/11 (73%) | 9/11 | 9/11 | Phase 6 (no spec) |
| **HSEA** (13 phases 0–12) | all 13 have specs; varies execution | 13/13 | 11/13 | Plans missing for Phase 6, Phase 7 |

**Cumulative:** 24 phases across both epics, 22 with specs on main (92%), 20 with plans on main (83%). Phase 2 of LRR is the most-advanced phase (10 shipped PRs + regression test coverage). HSEA is at pre-staging for most phases — Phase 0 is the only HSEA phase with active execution work (first precedent shipped via PR #911).

**Substrate decision cascades into both epics:** scenario 1 (Qwen3.5-9B + RIFTS) + scenario 2 (OLMo 3-7B × {SFT, DPO, RLVR}) ratified in drop #62 §16; Option C parallel-backend pivot in §17 (beta #209 blocker). Queue #171 PR #919 found v0.0.28 is a viable Option A alternative pending beta verification. This decision gates LRR Phase 5 and HSEA Phase 5 (M-series triad).

---

## §1. Phase-status cross-grid

Combined view of both epics. Status + blocking dependencies.

### §1.1. LRR column (11 phases)

| # | Phase | Status | Spec | Plan | Next step |
|---|---|---|---|---|---|
| 0 | Finding Q + verification | closed | ✓ | ✓ | — |
| 1 | Research registry | closed (SHM marker gap flagged) | ✓ | ✓ | apply manual SHM one-liner + systemd hydration follow-up |
| 2 | Archive + replay as research instrument | **closed (10 PRs + G1/G2/G4 test gaps filled #925)** | ✓ | ✓ | — |
| 3 | Hardware validation (post-Hermes) | execution in progress | ✓ | ✓ | validation checklist against Qwen3.5-9B + scenario 2 |
| 4 | Phase A completion + OSF pre-reg | spec staged, time-gated | ✓ | ✓ | G3 resolution → ≥10 voice sessions → OSF filing |
| 5 | Substrate scenario 1+2 swap | spec staged | ✓ | ✓ | Option A/C decision (§3.1) → RIFTS + OLMo execution |
| 6 | (reserved) | **GAP** | ✗ | ✗ | authoring session |
| 7 | Persona spec authoring | spec staged | ✓ | ✓ | await Phase 4 closure |
| 8 | Content programming via objectives | spec staged | ✓ | ✓ | await Phase 5 closure |
| 9 | Closed-loop feedback | spec staged | ✓ | ✓ | await Phase 5 + 7 |
| 10 | Observability + stability matrix | **execution in progress** | runbook | — | §3.3 pins → §3.2 dashboards → §3.6 T3 caching |

Full details: `docs/superpowers/runbooks/lrr-execution-state.md` (queue #147 / PR #926).

### §1.2. HSEA column (13 phases)

| # | Phase | Status | Spec | Plan | Next step |
|---|---|---|---|---|---|
| 0 | Foundation primitives | **execution in progress** | ✓ | ✓ | precedent draft `sp-hsea-mg-001.yaml` shipped via PR #911 (queue #166); deliverable 0.5 pre-stage continues |
| 1 | Visibility surfaces | spec staged | ✓ | ✓ | await Phase 0 exit criteria |
| 2 | Core director activities | spec staged | ✓ | ✓ | await Phase 1 |
| 3 | Research program orchestration | spec staged (prereq audit #914 flagged) | ✓ | ✓ | prereq items from queue #162 audit |
| 4 | Code drafting cluster | spec staged (prereq audit #914 flagged) | ✓ | ✓ | Phase 2 + Phase 3 closure |
| 5 | M-series triad (substrate-dependent) | spec staged | ✓ | ✓ | substrate scenario 1+2 ratification closure from LRR Phase 5 |
| 6 | Content quality + clip mining | spec staged | ✓ | **✗ no plan** | authoring session |
| 7 | Self-monitoring + catastrophic tail | spec staged | ✓ | **✗ no plan** | authoring session |
| 8 | Platform value + curation | spec staged | ✓ | ✓ | Phase 6 closure |
| 9 | Revenue preparation | spec staged | ✓ | ✓ | Phase 8 closure |
| 10 | Reflexive stack | spec staged | ✓ | ✓ | Phase 9 closure |
| 11 | Multi-agent spawner | spec staged | ✓ | ✓ | Phase 10 closure |
| 12 | Long-tail handoff | spec staged | ✓ | ✓ | epic closure — final phase |

All HSEA specs were authored as a delta pre-staging batch on 2026-04-15. Execution is not yet underway except for Phase 0 (precedents directory bootstrap from PR #911).

### §1.3. Structural gaps (both epics)

| Epic | Phase | Gap | Impact |
|---|---|---|---|
| LRR | 6 | no spec, no plan | downstream phases 7/8/9 depend on it conceptually; authoring session needed |
| HSEA | 6 | plan missing (spec present) | Phase 8 downstream; authoring session |
| HSEA | 7 | plan missing (spec present) | Phase 8 downstream; authoring session |

All three gaps are **authoring-only** — they need a session to extract the plan from the already-shipped spec. No code or research blockers.

---

## §2. Cross-epic dependencies

Pulled from queue #122 cross-epic dependency graph (PR with Mermaid render at #906).

```
LRR Phase 0 ─────────────────┐
                             │
LRR Phase 1 ─────────────────┤
                             │
LRR Phase 2 ─────────────────┤
                             ├──► HSEA Phase 0 (foundation primitives)
LRR Phase 3 ─────────────────┤         │
                             │         ▼
                             │    HSEA Phase 1 (visibility)
                             │         │
                             │         ▼
                             │    HSEA Phase 2 (core director)
                             │         │
LRR Phase 4 (Phase A data) ──┘         ▼
                                  HSEA Phase 3 (research program)
                                        │
LRR Phase 5 ◄─── substrate ───────► HSEA Phase 5 (M-series)
      │                                 │
      ▼                                 ▼
LRR Phase 7 (persona)              HSEA Phase 4 (code drafting)
      │                                 │
      ▼                                 ▼
LRR Phase 8 (content programming)  HSEA Phase 6 (content quality)
      │                                 │
      ▼                                 ▼
LRR Phase 9 (closed-loop)          HSEA Phase 7 (self-monitoring)
                                        │
                                        ▼
                                   HSEA Phase 8 (platform value)
```

### §2.1. Hard dependencies

| From | To | Reason |
|---|---|---|
| LRR Phase 0 | HSEA Phase 0 | HSEA precedent framework reuses LRR Finding Q verification infrastructure |
| LRR Phase 2 (archive instrument) | HSEA Phase 3 (research program) | HSEA Phase 3 consumes the archive for program-level analysis |
| LRR Phase 5 (substrate) | HSEA Phase 5 (M-series triad) | M-series runs on the substrate that LRR Phase 5 selects + ships |
| HSEA Phase 0 (precedents) | HSEA Phase 1+ | Every subsequent HSEA phase references the precedent framework established in Phase 0 |

### §2.2. Soft dependencies (coordination, not blocking)

| From | To | Reason |
|---|---|---|
| LRR Phase 4 (Phase A data) | LRR Phase 7 (persona) | persona extraction uses collected baseline data |
| LRR Phase 7 (persona) | HSEA Phase 6 (content quality) | persona informs clip-mining criteria |
| LRR Phase 10 (stability matrix) | all phases | observability overlay for any phase running in production |

---

## §3. Substrate decision impact on both epics

**Canonical framing:** `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` §14–§18.

### §3.1. Current state

| Scenario | Model | Runtime (§16) | Runtime (§17 pivot) | Verification (#171) |
|---|---|---|---|---|
| 1 | Qwen3.5-9B EXL3 | TabbyAPI :5000 | unchanged | — |
| 2 | OLMo 3-7B × {SFT, DPO, RLVR} | TabbyAPI :5000 (Option A in-place) | TabbyAPI :5001 (Option C parallel) | v0.0.28 viable per PR #919; beta verification pending |

### §3.2. Impact on LRR

- **LRR Phase 5** executes the substrate swap. Scenario 1 is beta's RIFTS baseline (#210). Scenario 2 is OLMo parallel arms (#211 + #212).
- **LRR Phase 4** is substrate-independent on the Condition A side (Qwen3.5-9B stays regardless) per spec §1 (queue #177 alignment patch PR #920).
- **LRR Phase 9 closed-loop feedback** depends on stable substrate — runs after Phase 5 ships.

### §3.3. Impact on HSEA

- **HSEA Phase 5 M-series triad** directly depends on scenario 2 OLMo arms. The triad design assumes three parallel model heads (SFT/DPO/RLVR) can be reached concurrently from the director. Option A (in-place) simplifies routing; Option C (parallel :5001) requires the LiteLLM router to distinguish the two TabbyAPI backends.
- **HSEA Phase 3 research program orchestration** consumes the LRR Phase 2 archive regardless of substrate — not substrate-blocked.
- **HSEA Phase 4 code drafting cluster** runs on whatever cloud model the director recruits at draft time — not substrate-blocked.

### §3.4. Unblocker

The scenario 2 Option A/C decision is the single most impactful unblocker across both epics. Queue #171 PR #919 found v0.0.28 is a viable Option A candidate (OlmoHybrid support from v0.0.26, same `torch>=2.6.0` pin, no new xformers dep vs v0.0.23 baseline). A 15-minute beta verification would resolve this. If Option A confirms: retire Option C queue items (#211, #212), simplify HSEA Phase 5 routing. If Option A refutes: continue Option C, document in queue #919 as a future upstream upgrade candidate.

---

## §4. Operator-gated decisions across both epics

Combines the 3 LRR-side gates from queue #147 runbook + HSEA-side gates.

### §4.1. Scenario 2 Option A vs Option C (cross-epic, HIGH priority)

See §3.4 above. Unblocks LRR Phase 5 scoping + HSEA Phase 5 router design.

**Needs:** operator allocation of a beta session for verification.

### §4.2. FINDING-S default-ship deadline 2026-04-22 (LRR)

Phase 2 retention policy auto-ship date. Needs operator sign-off or defer decision before the 7-day deadline.

### §4.3. OSF pre-registration filing (LRR Phase 4)

One-way operator-physical action once ≥10 voice grounding sessions are captured.

### §4.4. LRR Phase 6 authoring (LRR)

Pure triage decision: author now (unblocks ordering) vs defer (mark as post-Phase 5 retrograde).

### §4.5. HSEA Phase 6 + Phase 7 plan authoring (HSEA)

Two authoring-only gaps: HSEA Phase 6 (content quality + clip mining) and Phase 7 (self-monitoring + catastrophic tail) have specs on main but no plans. Both plans are needed before execution can start on Phase 6/7. Out of scope for any current queue item — needs scheduling.

### §4.6. HSEA epic-exit criteria (HSEA)

HSEA has no formal exit criteria document yet. Phase 12 (long-tail handoff) is the nominal terminus but the epic-level "done" definition is not written. Operator-level decision: should epic exit criteria be authored upfront or left implicit?

---

## §5. Combined PR activity (last 20 PRs touching either epic)

| PR | Commit | Epic/Phase | Queue | Title |
|---|---|---|---|---|
| #927 | 75443234f | infra | #174 | docs(research): systemd user timers sweep audit (gemini) |
| #926 | d7e30ca9f | LRR | #147 | docs(runbooks): LRR execution state runbook |
| #925 | e93bba955 | LRR P2 | #146 | test(lrr-phase-2): fill top 3 regression gaps from #117 audit |
| #924 | 352b9554a | infra | #173 | docs(research): gemini ↔ claude hook drift check + sync |
| #923 | bcdbc8db5 | cross | #172 | docs(research): thematic index of superpower specs (gemini) |
| #922 | 999a1fa0d | infra | #175 | docs(research): Docker compose containers audit |
| #921 | 35e90b7eb | infra | #176 | docs(research): axiom-commit-scan.sh coverage verification |
| #920 | cabec58eb | LRR P4 | #177 | docs(lrr-phase-4): spec+plan alignment patch post-§16/§17 |
| #919 | 5eb799830 | substrate | #171 | docs(research): exllamav3 v0.0.24-v0.0.29 release matrix |
| #918 | a86dbd117 | LRR P10 | #170 | docs(research): LRR Phase 10 per-section status audit |
| #917 | e1efbdd9d | drop-62 | #169 | docs(drop-62): update ToC with §18 link |
| #916 | e465314c2 | cross | #165 | docs(research): beta branch cherry-pick gap check |
| #915 | 0918f6f2b | LRR P1 | #164 | docs(research): LRR Phase 1 Qdrant integration check |
| #914 | a195ee5d5 | HSEA P3/P4 | #162 | docs(research): HSEA Phase 3/4 execution prereq audit |
| #913 | b4cc0fc11 | cross | #161 | docs(research): cross-repo sync state check |
| #912 | db7d43527 | drop-62 | #156 | docs(drop-62): §18 draft — forward-looking post-scenario-1+2 ship |
| #911 | 4b5d6a2df | HSEA P0 | #166 | feat(axioms): ship 4 drop #62 §10 amendments |
| #910 | 4a22833d0 | LRR P3 | #157 | docs(lrr-phase-3): plan refresh matching #139 Hermes cleanup |
| #909 | a439a4a61 | LRR P10 | #153 | docs(research): LRR Phase 10 §3.3 CI pin integration check |
| #908 | 8d86afd58 | LRR epic | #154 | docs(lrr-epic): Phase 5 cross-reference amendment |

Notably absent in recent activity: direct HSEA-phase-2-through-12 execution PRs. HSEA is still pre-staging — specs + plans land but execution hasn't begun beyond Phase 0 precedents.

---

## §6. Read-next navigation

Minimum reading paths by task.

### §6.1. Cold start — new to both epics

1. `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` §0 ToC (5 min)
2. `docs/superpowers/runbooks/lrr-execution-state.md` (5 min; this rollup's LRR counterpart)
3. `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` (~15 min)
4. `docs/superpowers/specs/2026-04-15-hsea-phase-0-foundation-primitives-design.md` (~10 min; HSEA start)

### §6.2. Substrate decision only

1. Drop #62 §14 → §16 → §17 → §18 (~10 min)
2. PR #919 / `docs/research/2026-04-15-exllamav3-release-notes-matrix.md` (~5 min; the Option A/C decision context)

### §6.3. HSEA specifically

1. Delta's thematic index: `docs/research/2026-04-15-docs-superpowers-specs-thematic-index.md` (from PR #923)
2. HSEA Phase 0 spec: `docs/superpowers/specs/2026-04-15-hsea-phase-0-foundation-primitives-design.md`
3. HSEA Phase 3/4 prereq audit: PR #914 (queue #162)

### §6.4. LRR specifically

1. LRR execution state runbook: `docs/superpowers/runbooks/lrr-execution-state.md`
2. LRR Phase 10 stability matrix runbook: `docs/superpowers/runbooks/lrr-phase-10-stability-matrix.md`
3. Per-phase spec + plan under `docs/superpowers/specs/2026-04-15-lrr-phase-N-*.md`

### §6.5. Queue state

1. Active items: `~/.cache/hapax/relay/queue/*.yaml`
2. Archive: `~/.cache/hapax/relay/queue/done/2026-04-15/*.yaml` (97+ items closed this session block)
3. Session status: `~/.cache/hapax/relay/{alpha,beta}.yaml`

---

## §7. Refresh mechanics

Same as queue #147 runbook: this rollup is manually regenerated on meaningful state changes. Not time-driven. Triggers:

1. An epic's phase status changes (closed → in progress, etc.)
2. Substrate scenario pivots (already happened twice: §16 → §17; potentially §17 → Option A)
3. A cross-epic dependency is added or resolved
4. HSEA execution begins in earnest (beyond Phase 0)
5. Either epic's exit criteria are drafted

A scripted regenerator for **both** this rollup and the LRR runbook is a proposed follow-up: `scripts/render-epic-rollups.py` that consumes phase-catalog YAML + `git log` + queue state. Out of scope for queue #160.

---

## §8. Cross-references

- queue #147 PR #926 — LRR execution state runbook (dependency)
- queue #122 — cross-epic dependency graph (pulled for §2)
- queue #162 PR #914 — HSEA Phase 3/4 execution prereq audit (pulled for §1.2)
- queue #172 PR #923 — gemini's thematic index of all superpower specs (pulled for §6.3)
- `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` — drop #62 canonical
- LRR epic spec + plan: `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` + plan
- HSEA Phase 0–12 specs + plans (9 of 13 plans shipped)
- queue #160 — this item

---

## §9. Verdict

The combined LRR + HSEA state is **healthy at the authoring layer** and **selective at the execution layer**. 22 of 24 phase specs are on main (92%); 20 of 24 phase plans are on main (83%). LRR is actively executing Phase 2 (closed), Phase 3 (in progress), and Phase 10 (in progress). HSEA is actively executing Phase 0 only — every other HSEA phase is staged.

The epics converge structurally at the substrate layer (LRR Phase 5 ↔ HSEA Phase 5 M-series). A single decision (Option A vs C, queue #171 beta verification) determines both epics' near-term execution path. Every other blocker is either a phase-specific prerequisite (e.g., Phase 4 voice sessions) or an authoring gap (LRR Phase 6, HSEA Phase 6/7 plans).

No immediate cross-epic execution blockers beyond the three gated decisions in §4.1/§4.2/§4.3. Both epics are in a shippable state.

— alpha, queue #160
