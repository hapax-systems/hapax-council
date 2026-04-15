# LRR Phase 9 — Closed-Loop Feedback + Narration + Chat Integration — Design Spec

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction; LRR execution remains alpha/beta workstream)
**Status:** DRAFT pre-staging — awaiting LRR UP-9 (persona) + UP-8 Phase 8 close before Phase 9 open
**Epic reference:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §5 Phase 9
**Plan reference:** `docs/superpowers/plans/2026-04-15-lrr-phase-9-closed-loop-feedback-plan.md`
**Branch target:** `feat/lrr-phase-9-closed-loop-feedback`
**Cross-epic authority:** drop #62 §5 row UP-11 (LRR Phase 8 + Phase 9 + HSEA Phase 3 co-ship) + §14 (Hermes abandonment supersedes item 4 framing)
**Unified phase mapping:** **UP-11 Content programming + objectives + closed loop** — Phase 9 portion (~1,800 LOC)

> **2026-04-15T07:35Z note:** item 4 "Daimonion narration of active code work" originally framed as "Under Hermes 3: ...narration style; Under Qwen: unusable". This Hermes framing is SUPERSEDED per drop #62 §14. Phase 9 opener must validate whichever post-Hermes substrate the operator ratifies can produce the expressive narration quality item 4 requires. Per beta's research §9, Qwen3.5-9B may be capable if thinking mode + first-call latency fixes hold; OLMo 3-7B is an untested alternative. Decision gate at phase open.

---

## 1. Phase goal

Wire the closed loop: **chat structure → audience engagement signal → operator stimmung → Hapax's activity selection → output that feeds back into chat**. Enable daimonion narration of active code work (editor + git + CI state → stream narration). Convert the chat reactor from keyword-matching to research-aware. Ship PipeWire operator-voice-over-YouTube ducking (GDO handoff §6.5 request). Ship the SHM signal publishers (editor/git/CI state) that the code narrator consumes.

**Phase 9 closes the closed loop.** After Phase 9, Hapax's content programming is reactive to chat + operator + objectives simultaneously.

**What this phase is:** 9 items — chat signals → stimmung, stimmung-modulated scoring, research-aware chat reactor, daimonion code-narration sub-mode, async-first chat queue, scientific-register captions, stimmung × stream correlation dashboard, operator-voice sidechain ducking, SHM signal publishers.

**What this phase is NOT:** does not ship objectives (LRR Phase 8), does not ship persona (LRR Phase 7), does not ship Phase 10 observability/drills/polish, does not ship HSEA Phase 3 C-cluster narrators (co-ships in UP-11 but distinct ownership).

**Theoretical grounding:** Narration unblock (substrate enables code-narration quality) + research-aware chat reactor (substrate enables LLM-evaluating chat against research context). The closed loop IS the substrate of "never-ending research based on livestream interactions."

---

## 2. Dependencies + preconditions

**Cross-epic (from drop #62):**

1. **LRR UP-0 + UP-1 closed.**
2. **LRR UP-7 (substrate swap) closed** with operator-ratified post-Hermes substrate per §14. Phase 9 item 4 daimonion code-narration requires narration-quality LLM output; Phase 9 opener verifies the chosen substrate produces usable narration before committing to item 4.
3. **LRR UP-9 (Phase 7 persona) closed.** Scientific-register caption mode (item 6) references the persona register.
4. **LRR UP-11 Phase 8 closed.** Phase 9 item 2 modulates the Phase 8 objective scorer with a stimmung term; Phase 9 item 3 research-aware chat reactor queries Phase 8 objective state.
5. **HSEA UP-2/UP-4 closed.** Cairo caption source (item 6) uses HSEA Phase 1 zone registry pattern.
6. **LRR UP-3 (Phase 2 archive) closed.** PipeWire sidechain (item 8) interacts with the audio sink routing that Phase 2 item 10 layout-declared sinks migration enables.

**Intra-epic:** Phases 0-8 closed.

**Infrastructure:**

1. `chat_monitor` (Phase 0 fix) that writes recent messages to a readable location
2. `nomic-embed-cpu` (existing, running via Ollama GPU-isolated)
3. `shared/stimmung.py` or equivalent with the 11-dim state (Phase 9 adds 12th: `audience_engagement`)
4. `agents/studio_compositor/chat_reactor.py::PresetReactor` (existing)
5. `agents/hapax_daimonion/director_loop.py` (Phase 8 extended scorer)
6. `#778` audio ducking PR (existing, shipped)
7. PipeWire `filter-chain` (existing, used for voice FX and other routing)
8. `echo_cancel_source` (existing, operator Yeti mic)
9. Grafana dashboard infrastructure (existing)
10. `shared/config.py` `audience_engagement` dimension addition

---

## 3. Deliverables (9 items)

### 3.1 Chat monitor → structural signal → stimmung modulation (item 1)

- Chat monitor (Phase 0 fix) produces structural analysis: thread count, novelty rate, participant diversity, semantic coherence (via nomic-embed)
- Write as SHM at `/dev/shm/hapax-chat-signals.json`
- Stimmung reader consumes SHM + modulates new 12th dimension `audience_engagement`
- Thresholds: `audience_engagement > 0.7` → SEEKING tilt; `< 0.3` → quiet_presence tilt
- **Target files:** `agents/chat_monitor/structural_analyzer.py` (~200 LOC), `shared/stimmung.py` 12th-dim extension (~40 LOC), tests (~150 LOC)
- **Size:** ~390 LOC

### 3.2 Stimmung-modulated activity selection (item 2)

- Extend Phase 8 scorer (`director_loop._call_activity_llm`):
  - `score(a) = 0.7·momentary + 0.25·objective + 0.05·stimmung_term` (start conservative per §6 oscillation risk)
  - High `audience_engagement` + active chat threads → raise `chat` score
  - Low engagement → raise `study` or `silence`
  - Critical stimmung → auto-private (Phase 6 loop already active)
- **Target files:** `agents/hapax_daimonion/director_loop.py` (~50 LOC extension), `config/director_scoring.yaml` updated with stimmung_term weight, tests
- **Size:** ~120 LOC

### 3.3 Research-aware chat reactor (item 3)

- `chat_reactor.py::PresetReactor` subscribes to `/dev/shm/hapax-chat-signals.json`
- Per-message: embed via nomic-embed; cosine similarity to current objective title/notes > 0.6 → flag "research-relevant"
- Research-relevant messages trigger `study` activity biased toward the chat topic
- 30s cooldown preserved; no per-author state (consent-safe)
- **Target files:** `agents/studio_compositor/chat_reactor.py` (~120 LOC extension), tests (~100 LOC)
- **Size:** ~220 LOC

### 3.4 Daimonion narration of active code work (item 4) — **SUBSTRATE DECISION GATE**

**Superseded framing per drop #62 §14:** originally "Under Hermes 3: expressive narration style; Under Qwen: unusable; unblocks only after Phase 5". Phase 9 opener:

1. Tests the ratified post-Hermes substrate on narration prompts (3-5 fixture narration tasks)
2. Operator evaluates narration quality on a 1-5 scale
3. If quality ≥ 3/5: Phase 9 item 4 ships as-specced
4. If quality < 3/5: Phase 9 item 4 ships with a "disabled by default" flag and the code narrator returns generic study narration until substrate quality improves
5. Phase 9 close does NOT gate on narration quality reaching the target — ships infrastructure + enables it when substrate is ready

- Daimonion `study` activity gains a `code-narration` sub-mode
- Reads SHM signals from item 9 (editor/git/CI state)
- Narrates code edits, PR opens, test runs, error encounters
- **Target files:** `agents/hapax_daimonion/activities/study.py` extension (~150 LOC), `agents/hapax_daimonion/narrators/code_narrator.py` (~250 LOC), tests (~180 LOC)
- **Size:** ~580 LOC

### 3.5 Async-first chat queue semantics (item 5)

- Chat messages land in both real-time path (existing 30s cooldown preset matching) AND async queue
- Queue bounds: max 20 messages FIFO eviction
- Hapax reviews queue holistically during `chat` activity, not on receipt
- Protects `executive_function` axiom (asynchronous less interrupt-heavy)
- **Target files:** `agents/hapax_daimonion/chat_queue.py` (~150 LOC), tests (~100 LOC)
- **Size:** ~250 LOC

### 3.6 Scientific register caption mode (item 6)

- Auto-captions (STT output) rendered as Cairo overlay
- `public_research` stream-mode: scientific-register font + styling per persona spec
- `public` mode: normal styling
- **Target files:** `agents/studio_compositor/captions_source.py` (~200 LOC), tests (~120 LOC)
- **Size:** ~320 LOC

### 3.7 Stimmung × stream correlation dashboard (item 7)

- Prometheus time-series of stimmung dimensions + stream events (activity changes, chat engagement, audience size)
- Grafana panel: stimmung × time × stream event overlay
- Purpose: validate closed loop without creating negative feedback spiral
- **Target files:** `grafana/dashboards/stimmung-stream-correlation.json` (~300 lines Grafana JSON), Prometheus scrape config edit, tests via `promtool`
- **Size:** ~400 LOC (mostly Grafana JSON)

### 3.8 PipeWire operator-voice-over-YouTube ducking (item 8)

- NEW PipeWire filter-chain: `operator-voice-sidechain` reads operator VAD from `echo_cancel_source`, generates control signal
- YouTube audio sink (`youtube-audio-{0,1,2}`) routes through `sc-compressor` with sidechain input from operator VAD
- 6 dB attenuation when operator VAD active, 0 dB silent, 80ms attack + 200ms release
- Disable-able via Stream Deck button
- Verify no conflict with existing `#778` daimonion-TTS ducking
- **Target files:** `config/pipewire/operator-voice-sidechain.conf` (~80 lines), tests (manual A/B audio verification + gst pipeline check)
- **Size:** ~100 LOC config

### 3.9 Daimonion code-narration signal sources (item 9)

Signal publishers for item 4:

- `/dev/shm/hapax-editor-state.json` — VS Code plugin publishes current file, cursor line, last edit, unsaved buffer count. Likely lives in `hapax-council/vscode/` extension (existing). ~50 LOC extension edit.
- `/dev/shm/hapax-git-state.json` — `scripts/publish-git-state.sh` systemd timer (5s) publishes current branch, modified files, staged count, last 3 commit SHAs. ~40 LOC shell.
- `/dev/shm/hapax-ci-state.json` — `scripts/publish-ci-state.sh` polls `gh run list --branch <current>` every 30s. ~50 LOC shell.
- `ContextAssembler.snapshot()` reads all 3 signals; daimonion falls through to generic `study` narration if any signal stale > 30s
- **Target files:** VS Code extension edit + 2 shell scripts + 2 systemd units + tests
- **Size:** ~300 LOC total

---

## 4. Phase-specific decisions since epic authored

1. **Item 4 substrate decision gate per drop #62 §14.** Phase 9 opener tests post-Hermes substrate narration quality and ships item 4 with appropriate enablement flag.

2. **Damping weight conservative (0.05 stimmung_term).** Per §6 oscillation risk — start at 5% stimmung influence, tune up only after observing closed-loop behavior without feedback spirals.

3. **Item 8 sidechain compressor conflict with #778 ducking.** Phase 9 opener must manually A/B test both ducking paths firing simultaneously to verify no amplitude collision. Epic spec flags this explicitly.

4. **No drop #62 §10 open questions affect Phase 9 directly.** All 10 ratifications substrate-independent except Q1 (practically reopened per §14).

5. **LRR Phase 9 co-ships with LRR Phase 8 + HSEA Phase 3 in UP-11.** They can ship in any order relative to each other within UP-11 as long as the cross-dependencies are met (Phase 9 item 2 depends on Phase 8 scorer; Phase 9 items 3/4 depend on Phase 8 objectives).

---

## 5. Exit criteria

1. `/dev/shm/hapax-chat-signals.json` written by chat monitor, read by stimmung
2. 12th stimmung dimension `audience_engagement` tracking chat signal
3. Director loop activity scoring includes stimmung term (verify via LLM prompt log comparison in high vs low engagement state)
4. Research-aware chat reactor triggers on objective-similar message in `public_research` mode
5. Daimonion code-narration operational IF substrate passes quality gate; otherwise disabled flag enabled
6. Async chat queue bounded: flood 50 messages, FIFO evicts down to 20
7. Scientific register captions render in `public_research` mode
8. Grafana dashboard shows stimmung × stream correlation; operator closes-loop sanity check
9. PipeWire operator-voice-over-YouTube ducking: 6dB attenuation, 80ms attack, 200ms release, no conflict with #778
10. SHM publishers (editor/git/CI) active + `ContextAssembler.snapshot()` reads them
11. `lrr-state.yaml::phase_statuses[9].status == closed`
12. Phase 9 handoff doc written

---

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Closed-loop oscillation (high engagement → more chat → more engagement → feedback spiral) | Visible stream chaos | Start at 5% stimmung weight, 1-week observation before tuning up |
| Daimonion code-narration requires substrate quality not yet validated | Phase 9 item 4 ships disabled | Decision gate per §4 decision 1; infrastructure ships regardless |
| Research-aware chat reactor activates on tangential messages | False positives | 0.6 cosine threshold tunable; 30s cooldown; operator override |
| Item 8 sidechain compressor conflicts with #778 | Audio artifacts | Manual A/B test mandatory before close |
| Signal publishers flaky | Narration incoherent | 30s staleness fallthrough to generic `study` |
| `audience_engagement` dimension breaks existing stimmung consumers | Downstream agent errors | Backward-compatible: absence of field is treated as 0.5 (neutral) |

---

## 7. Open questions

Phase 9-specific (all substrate-independent except item 4):

1. **Stimmung term weight default.** 5% conservative start; operator tunes.
2. **Item 4 substrate decision gate threshold.** 1-5 Hapax-ness scale matching LRR Phase 7 eval; ≥3/5 enables item 4.
3. **Research-aware chat reactor cosine threshold.** 0.6 default; operator tunes.
4. **Async chat queue eviction policy.** FIFO default; alternative: relevance-ranked.

---

## 8. Companion plan

`docs/superpowers/plans/2026-04-15-lrr-phase-9-closed-loop-feedback-plan.md`.

Execution order: item 9 (signal publishers) → item 1 (chat signals) → item 2 (stimmung modulation) → item 5 (async queue) → item 3 (research-aware reactor) → item 6 (captions) → item 7 (dashboard) → item 8 (sidechain) → item 4 (code narration, with substrate gate).

---

## 9. End

Standalone per-phase design spec for LRR Phase 9 Closed-Loop Feedback. 9 items; ~1,800 LOC. Phase 9 closes the closed loop after Phase 8 lands objectives + scorer.

Pre-staging. Phase 9 opens when:
- LRR UP-0/UP-1/UP-3/UP-7/UP-9 closed
- LRR UP-8 (Phase 8) closed
- HSEA UP-2/UP-4/UP-10 closed
- Post-Hermes substrate ratified per drop #62 §14
- Session claims via `lrr-state.yaml::phase_statuses[9].status: open`

Eleventh complete extraction in delta's pre-staging queue this session.

— delta, 2026-04-15
