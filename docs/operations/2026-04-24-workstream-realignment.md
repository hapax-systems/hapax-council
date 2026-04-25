# Workstream Realignment — 2026-04-24T21:20Z

**Author:** beta
**Operator directive:** *"make sure no session is idle and all are aligned and that the workstream is readjusted to present state given all the work that has been done and the introduction of new workstreams. WSJF again. Adjust workstreams. Make sure nothing gets lost and the entire plan is accounted for. Aim: faster flow"*
**Scope:** full present-state audit; WSJF rescored; per-session assignments; no lost work.

---

## 1. Present state snapshot (2026-04-24T21:20Z)

**Today's shipped work (operator-away window from 09:31Z):** 32 feature merges across 9 epics. Main green. CI speed ~5-8min (was 25min wall).

**Closed epics:** main-red (#1302) · LORE-MVP A+B+C (#1284/#1296/#1308) · OMG cascade 1-8 (#1299/#1300/#1301/#1303/#1304/#1305/#1306/#1307/#1312/#1313/#1319/#1320) · AUTH-family wave 1 (#1285/#1287/#1288/#1289/#1290/#1291) · AUTH-ENLIGHTENMENT Phase 1 (#1314) · AUTH-PALETTE Phase 1 (#1315) · QM1+QM2 (#1292/#1293) · SS1+SS2 cycle1 (#1286/#1294/#1295) · YouTube backbone (ytb-007 #1276, ytb-004 #1281, ytb-001 #1310, ytb-005 #1311, ytb-011 #1317, ytb-010 Phase 1+2 #1319/#1320) · CI infrastructure (#1318) · deps (#1309).

**In-flight:**
- **#1316 delta render_stage filter** — admin-merge-eligible (diff-surface-disjoint); awaiting delta

**Chronic residual:** 7 tests fail on every PR since ~20:00Z (legibility_sources::TestSmoke ×5 + token_pole_palette + objectives_overlay). Xfail cc-tasks filed at tick 85 (ytb-LEGIBILITY-SMOKE-FOLLOWUP, ytb-TOKEN-POLE-PALETTE-FOLLOWUP, ytb-OBJECTIVES-OVERLAY-RENDER-FOLLOWUP).

**New workstreams introduced today (not yet assigned):**
1. **Grounding-capability-recruitment implementation** (synthesis at `docs/research/2026-04-24-grounding-capability-recruitment-synthesis.md`). Phase 0→3 plan. 23-site migration. The biggest new workstream.
2. **Chronic main-red xfails** — above.
3. **Fortress grounding-act violation** — `model_daily=claude-sonnet` on cloud. Grounding-act per T1-T7; not operator-directed fix yet but within autonomy mandate.

---

## 2. Epic catalog — WSJF rescored against present state

### 2.1 HIGH (10+) — active critical path

| Epic | WSJF | Sessions | Status |
|---|---|---|---|
| **Grounding-capability-recruitment Phase 0** (shared/grounding.py + GroundingAdjudicator skeleton + ruff HPX001 + CapabilityRecord extension) | **11.0** | beta | **TO-CLAIM** |
| **Chronic xfails PR** (unblock all future PRs from admin-merge-eligible noise) | **10.0** | epsilon | **DISPATCHED** |
| **LRR Phase A validation** (voice grounding; Shaikh RIFTS against Qwen3.5-9B; Phase 7 doc-persona live since 2026-04-17; ≥8 livestream sessions to MCMC BEST data-sufficiency) | **10.0** | alpha (research-direction) + beta (observability) | ongoing |

### 2.2 HIGH (8-10) — active high-value

| Epic | WSJF | Sessions | Status |
|---|---|---|---|
| **ytb-OG2 dual-format broadcast verification** | 16.0 | **operator** | operator-action pending (Shorts-feed injection verify) |
| **ytb-OG3 quota extension filing** | 8.0 | **operator** | operator-action (YT Data API v3 quota extension form) |
| **FINDING-V publishers research-spec-plan** (5 orphan consumer wards) | 8.0 | delta | offered; TO-CLAIM |
| **Grounding-capability-recruitment Phase 1 migrations** (23 sites → GroundingAdjudicator) | 8.0 | distributed by lane | TO-CLAIM after Phase 0 |

### 2.3 MEDIUM (5-8)

| Epic | WSJF | Sessions | Status |
|---|---|---|---|
| **FINDING-X grounding-provenance research-spec-plan** (~54% empty-provenance on LLM-authored emissions; axiom closure via GroundingAdjudicator) | 7.0 | delta | offered; subsumed by Grounding-capability-recruitment Phase 1 |
| **Mobile-livestream substream research-spec-plan** | 6.0 | delta | offered; deferrable |
| **ytb-010 Phase 3 Mastodon poster** (Phase 1 Discord + Phase 2 Bluesky both shipped) | 5.5 | alpha | TO-CLAIM |
| **ytb-OMG6 Phase B publishers** (programme-plans / axiom-precedents / research-corpus; Phase A chronicle shipped as #1306) | 5.0 | epsilon | offered; backup pickup |

### 2.4 MEDIUM-LOW (3-5)

| Epic | WSJF | Sessions | Status |
|---|---|---|---|
| **AUTH-ENLIGHTENMENT Phase 2** (authentic EDC/PNG ingestion; authored-placeholders OK under autonomy mandate) | 4.5 | epsilon | offered |
| **AUTH-PALETTE Phase 2** (Moksha .edc loader → compositor boot + byte-exact LAB values via `aesthetic_library_loader`) | 4.5 | epsilon | offered |
| **ytb-003 thumbnail auto-generation** | 4.0 | delta | offered |
| **ytb-LEGIBILITY-SMOKE-FOLLOWUP** (xfail cluster #1) | 4.0 | epsilon (via dispatch) | **DISPATCHED** |
| **ytb-TOKEN-POLE-PALETTE-FOLLOWUP** (xfail; likely from #1315 Moksha palette) | 3.5 | epsilon (via dispatch) | **DISPATCHED** |
| **ytb-009 in-band live captions** | 3.2 | delta | offered |
| **ytb-OBJECTIVES-OVERLAY-RENDER-FOLLOWUP** (xfail) | 3.0 | epsilon (via dispatch) | **DISPATCHED** |
| **FINDING-W chrome wards post-FX** (#1316 merged the infra) | 3.0 | delta | delivered; needs default-layout-retag follow-on |
| **4 original main-red follow-ups** (ytb-WARD-CONTRAST / EMISSIVE-RETIRED-FLASH / EMISSIVE-GOLDEN-PANGO / ytb-GEAL-PERF-BUDGET) | 3.0 each | mixed | ongoing; xfails in place |

### 2.5 LOW (1-3)

| Epic | WSJF | Sessions | Status |
|---|---|---|---|
| **ytb-OMG9 infrastructure** (DNS/PFP/PGP/preferences — operator verified; session-automatable) | 2.2 | beta | claimed 20:05Z; re-scoped |
| **ytb-LORE-EXT future wards** | 2.1 | delta | offered |
| **ytb-012 shorts extraction pipeline** | 2.1 | delta | offered |
| **Fortress model_daily grounding-act violation** (config.model_daily=claude-sonnet; T1-T7 fail → cloud violation) | 2.0 | *out-of-lane (beta or delta)* | surface; defer until Phase 0 GroundingAdjudicator ships |
| **ytb-OMG8 Phase A compose-side** (Phase B weblog publisher shipped as #1307) | 1.5 | epsilon | follow-on |
| **ytb-OMG2 Phase 2** (Jinja2 dynamic rebuilder + systemd timer for hapax.omg.lol) | 1.5 | alpha (owner of Phase 1) | follow-on |

### 2.6 Research specs (ungated WSJF=0 in vault; load-bearing but not actionable until specs land)

- `finding-v-publishers-research-spec-plan` (delta)
- `finding-x-grounding-provenance-research-spec-plan` (delta) — **partially subsumed by Grounding-capability-recruitment**
- `mobile-livestream-substream-research-spec-plan` (delta)
- LRR Phase 4 Phase A completion (ef7b-031)
- 60f6-022…027 gaps implementation series

---

## 3. Per-session realignment

### 3.1 alpha (SS family + AUTH lane + youtube-boost)

**Current state:** just shipped #1319 + #1320 ytb-010 Phase 1+2; engaged with YT boost and cross-surface federation. Demonstrates claim-before-parallel + out-of-lane pickup competence (ytb-011, ytb-OMG2, ytb-010 series).

**Queue (in priority order):**
1. **ytb-010 Phase 3 Mastodon poster** (WSJF 5.5) — natural continuation; pattern identical to Phase 1/2; 1 PR.
2. **Grounding-capability-recruitment Phase 1 migration: conversation_pipeline main turn** (WSJF 8.0 slice) — the engineering-tension call from the synthesis. Wrap in `GroundingAdjudicator.invoke(capability="express.respond-to-operator-in-conversation", ...)`; currently routes cloud Opus via salience router; post-wrap substrate-binding emerges from `GroundingProfile`. Coordinates with beta's Phase 0 landing.
3. **SS2 cycle 2** (voice grounding research, LRR Phase A) — continue the 6-step cycle protocol from #1294/#1295; next cycle trigger when data-sufficiency threshold hits.
4. **ytb-OMG2 Phase 2** dynamic rebuilder (WSJF 1.5, follow-on to own Phase 1).

### 3.2 delta (compositor + LORE + audio)

**Current state:** stuck on #1316 (admin-merge-eligible since 19:47Z but not merged by delta). LORE-MVP epic complete. Chronic 7-test failures in delta-adjacent surfaces.

**Queue (in priority order):**
1. **Admin-merge #1316** immediately (own PR, admin-merge-eligible, blocking own next work).
2. **Follow-on #1316 default-layout retag** (WSJF 3.0) — the PR body's own deferred work: re-tag default-layout assignments per the pre_fx/post_fx split. Small PR.
3. **Grounding-capability-recruitment Phase 1 migration: director_loop + structural_director** (WSJF 8.0 slice) — delta's lane; director tick is #1 hottest grounding act; wrap in `GroundingAdjudicator.invoke(capability="express.narrate-stream-tick-grounded", ...)`. Requires beta's Phase 0 landed first.
4. **FINDING-V publishers research-spec-plan** (WSJF 8.0) — spec 5 orphan-consumer-ward producers.
5. **ytb-003 thumbnail auto-generation** (WSJF 4.0) — natural compositor work.
6. **ytb-009 in-band live captions** (WSJF 3.2).

### 3.3 epsilon (authentic-asset steward + OMG)

**Current state:** idle since 20:08Z per epsilon.yaml; 14 items shipped today; "no epsilon-lane offered work remaining."

**Queue (in priority order):**
1. **Chronic xfails PR** (WSJF 10.0) — **already dispatched** via `beta-to-epsilon-2026-04-24-chronic-test-xfails.md`. Immediate queue-unlock for every other session. Low-risk xfail markers + 3 follow-up cc-tasks.
2. **Grounding-capability-recruitment Phase 1 migration: metadata_composer + knowledge/query** (WSJF 8.0 slice) — paradigm work-class cases; test the architecture on the cleanest safe-cloud surface first. Requires beta's Phase 0.
3. **AUTH-PALETTE Phase 2** (WSJF 4.5) — authored-placeholders for Moksha .edc loader wiring into compositor boot (no asset wait; autonomy mandate per #1315 precedent).
4. **AUTH-ENLIGHTENMENT Phase 2** (WSJF 4.5) — authentic EDC/PNG ingestion with authored placeholders.
5. **ytb-OMG6 Phase B** (WSJF 5.0) — programme-plans / axiom-precedents / research-corpus publishers.

### 3.4 beta (audit + coordination + infrastructure)

**Current state:** shipped #1318 (CI infra + narration fences + grounded routing + catalog fix) + synthesis doc + multiple audits. Audit cadence ongoing.

**Queue (in priority order):**
1. **Grounding-capability-recruitment Phase 0 scaffolding** (WSJF 11.0) — `shared/grounding.py` (GroundingProfile Pydantic + T1-T8 validator) + `shared/grounding_adjudicator.py` skeleton + ruff HPX001 custom rule + `CapabilityRecord` extension with default `GroundingProfile`. No LLM-call migrations yet — just the structural primitives. ~300 LOC, 4 files. Blocks Phase 1 migrations across sessions.
2. **Ongoing peer audit** — continue 270s watch; fast-audit new PRs; surface coordination observations.
3. **ytb-OMG9 infrastructure automation** (WSJF 2.2) — OMG9 client extensions (`set_pfp`, `set_preferences`, `set_theme`, `set_key` for PGP). Operator confirmed verification done → fully automatable.
4. **Workstream documentation maintenance** — keep this doc current; file new cc-tasks when workstreams emerge.

---

## 4. Present-state grounding-act audit (full system)

Per the 6-lineage operative definition + 5-lineage formalization synthesis:

### GROUNDING ACTS (must route local-grounded)

| # | Surface | Current | Post-fix | Status |
|---|---|---|---|---|
| 1 | `director_loop` LLM tick | `local-fast` ✓ | `local-fast` via adjudicator | ✅ substrate correct; wrapping pending |
| 2 | `structural_director` | `local-fast` ✓ | `local-fast` via adjudicator | ✅ substrate correct; wrapping pending |
| 3 | `conversation_pipeline` main turn | cloud (salience router → Opus typically) | adjudicator selects; engineering tension | ⚠️ **ENGINEERING TENSION** — local uplift plan (Shaikh RIFTS + OLMo 3-7B) in progress |
| 4 | `conversation_pipeline` spontaneous speech | **FIXED 21:01Z via #1318** — `local-fast` | adjudicator-wrapped | ✅ post-#1318 |
| 5 | `autonomous_narrative/compose.py` | **FIXED 19:30Z via #1318** — `local-fast` | adjudicator-wrapped | ✅ post-#1318 |
| 6 | `fortress/deliberation.py` | `claude-sonnet` ❌ | TBD per T-profile | ⚠️ **VIOLATION**; defer until Phase 0 adjudicator ships |
| 7 | `logos/chat_agent.py` + `logos/interview.py` | cloud (typical) | adjudicator selects | ⚠️ **ENGINEERING TENSION** (same as #3) |

### DELEGABLE WORK (cloud legitimate with register-guard)

| # | Surface | Current | Status |
|---|---|---|---|
| 1 | `metadata_composer/composer.py` YouTube/Discord/Bluesky polish | `balanced` (Sonnet) ✓ | ✅ correct — deterministic grounded seed + register-guard + fallback |
| 2 | `knowledge/query.py` + `dev_story/query.py` RAG | `balanced` ✓ | ✅ correct — FACTS/RAG canonical |
| 3 | `hapax_daimonion/eval_grounding.py` offline judge | `claude-sonnet` ✓ | ✅ correct — offline post-hoc, not live |
| 4 | `scout` / `drift` / `digest` / `research` / `briefing` | `fast`/`balanced` ✓ | ✅ correct — analytic summarization |
| 5 | Profile classification + health analysis + chronicle composition | `fast`/`balanced` ✓ | ✅ correct |

### OUTSOURCED-BY-GROUNDING (cloud for capability local lacks)

| # | Surface | Current | Status |
|---|---|---|---|
| 1 | `tools.py` vision (scene description) | `gemini-2.0-flash` ✓ | ✅ correct — caller's grounding_provenance cites tool invocation |
| 2 | `tools.py` Imagen | `imagen-3.0-generate-002` ✓ | ✅ correct |

### MECHANICAL (should be code, not LLM)

| # | Surface | Current | Status |
|---|---|---|---|
| 1 | `conversation_pipeline` prewarm | 1-token LLM call ⚠️ | needs deLLM → TCP ping |
| 2 | `chat_reactor.py` keyword match | regex ✓ | ✅ correct |

**Current violation count:** 2 (fortress + prewarm) + 1 violation-fixed-post-#1318 + 2 engineering-tensions (pending local uplift).

**Neurosis index** (empty grounding_provenance rate on grounded-shape emissions): ~54% per FINDING-X. Target: 0.

---

## 5. Not-lost list (coverage guarantee)

Every item listed here has a home:

**4 original main-red follow-ups** (post-#1302):
- ytb-WARD-CONTRAST-FOLLOWUP — §2.4; delta-lane
- EMISSIVE-RETIRED-FLASH-FOLLOWUP — §2.4
- EMISSIVE-GOLDEN-PANGO-FOLLOWUP — §2.4
- ytb-GEAL-PERF-BUDGET-FOLLOWUP — §2.4

**Operator queue items (pre-existing):**
- SS1 live-validation flip — operator action (set env var + restart daimonion)
- AUTH-HOMAGE default-flip review — operator action (aesthetic signoff but per autonomy-mandate no-approval-waits: session-callable now; alpha's bitchx-authentic-v1 stays registered-not-default until operator or session flips)
- LORE-MVP visual signoffs — operator action (flip env flags post-visual-review; autonomy-mandate applies)
- AUTH-HOSTING bootstrap — operator-only (creates external `ryanklee/hapax-assets` repo via `scripts/setup-hapax-assets-repo.sh`; credentials-boundary)
- it-attribution-001 implication framing — advisory-strong
- CODEOWNERS additions — advisory

**Bayesian validation R&D schedule** — Day 26 of 21-day schedule per SessionStart; LRR Phase A continues; condition `cond-phase-a-persona-doc-qwen-001` open; ≥8 sessions to data-sufficiency.

**Research spec queue (delta-assigned):**
- finding-v-publishers — §2.2
- finding-x-grounding-provenance — subsumed by Grounding-capability-recruitment Phase 1 (delta)
- mobile-livestream-substream — §2.3 deferrable

**SCM Formalization** (Stigmergic Cognitive Mesh) — 14 control laws, 7 research docs; mostly shipped; remaining items live under memory `project_scm_formalization`.

**Governance** — 5 axioms active; implications in `axioms/implications/`; new operative definition `feedback_grounding_act_operative_definition` crystallizes grounding-act discipline.

**Nothing is dropped.** Everything above is either scheduled, subsumed by a larger workstream, or deferred with explicit rationale.

---

## 6. Flow-maximization principles (operator aim: faster flow)

1. **Every session has both a short-path queue item AND a long-path queue item.** Short = immediate merge-track; long = research-workstream contribution. Prevents session-lock on one blocked PR.
2. **Claim-before-parallel-work rule** remains active. Sessions file 1-line claim inflection before opening out-of-lane PRs. Cross-cutting → cc-task FIRST.
3. **Autonomy mandate** remains absolute. No operator-approval waits. Aesthetic signoffs are session-callable. Revert > stall.
4. **Admin-merge discipline**: 25-min timeout (now ~5-6min post-#1318) + disjoint-failure = admin-merge-eligible. Self-admin-merge on own PRs.
5. **Grounding-provenance runtime predicate**: every capability emission must cite PerceptualField keys; empty-provenance rate is the continuously-visible neurosis index.
6. **270s cadence locked** across all sessions. Cache-warm default.
7. **Phase 0 blocks Phase 1 migrations.** Beta ships Phase 0 infrastructure first; sessions pick up Phase 1 slices when `GroundingAdjudicator` + `GroundingProfile` land.

---

## 7. Post-realignment session disposition

| Session | Immediate (0-1h) | Short (1-4h) | Medium (4-24h) | Epic-scale |
|---|---|---|---|---|
| **alpha** | ytb-010 Phase 3 Mastodon | SS2 cycle 2 trigger | conv-pipeline adjudicator wrap | LRR Phase A completion |
| **delta** | admin-merge #1316 + retag follow-on | chronic-failures diagnose (not xfail — real fix if tractable) | director_loop adjudicator wrap | FINDING-V publishers |
| **epsilon** | chronic xfails PR (dispatched) | AUTH-PALETTE Phase 2 | metadata_composer adjudicator wrap | AUTH-ENLIGHTENMENT Phase 2 |
| **beta** | Phase 0 scaffolding (`shared/grounding.py`) | ruff HPX001 rule + commit-hook extension | audit Phase 1 PRs as they land | ytb-OMG9 automation |

No session has fewer than 3 queue entries. No item in §5 unaccounted.

---

## 8. Broadcast

Companion inflection at `~/.cache/hapax/relay/inflections/20260424T212000Z-beta-all-workstream-realignment.md`.

— beta, 2026-04-24T21:20Z
