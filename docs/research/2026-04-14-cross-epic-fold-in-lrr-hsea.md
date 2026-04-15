# Drop #62 — Cross-epic fold-in: LRR ↔ HSEA unified roadmap

**Date:** 2026-04-14
**Author:** delta (research support role, synthesizing cross-epic fold-in research agent)
**Status:** Draft synthesis. Operator decisions required at §4 (substrate swap), §6 (state file), §10 (open questions).
**Source documents:**
- LRR spec: `/home/hapax/projects/hapax-council/docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` (1371 lines, 11 phases, alpha-authored)
- LRR plan: `/home/hapax/projects/hapax-council/docs/superpowers/plans/2026-04-14-livestream-research-ready-epic-plan.md`
- HSEA spec: `/home/hapax/projects/hapax-council/docs/superpowers/specs/2026-04-14-hsea-epic-design.md` (794 lines, 13 phases, delta-authored)
- HSEA plan: `/home/hapax/projects/hapax-council/docs/superpowers/plans/2026-04-14-hsea-epic-plan.md`
- Drop #57 (tactics), drop #58 (HSEA thesis), drop #59 (HSEA audit)

---

## 1. Executive summary

LRR and HSEA were authored independently the same day (2026-04-14) by two roles (alpha and delta). They are not duplicates — they have distinct purposes — but they collide on roughly a quarter of their scope. LRR is a **research-validity sequencing epic**: it ships the registry, archive, governance, persona, objectives, closed-loop, and observability that Legomena Live needs to remain a defensible research instrument. HSEA is a **content-execution layering epic**: it makes Hapax visibly draft research, code, governance, and revenue artifacts that then route through an operator-controlled approval queue, with the drafting itself becoming the stream content.

Five top findings:

1. **No fundamental conflict — one structural conflict.** The only hard incompatibility is LRR Phase 5 (Hermes 3 70B substrate swap) versus HSEA Phase 4 cluster I4 (Hermes 3 8B parallel-config pivot). Drop #56 already showed the 70B path is unreachable under the operator's own `interpersonal_transparency` consent-latency axiom; HSEA Phase 4 I4 is the reified fix. **Recommendation:** restructure LRR Phase 5 into Phase 5a (8B parallel, owned and shipped by HSEA Phase 4 I4) and Phase 5b (70B, deferred behind a hardware/quant gate, future epic).

2. **Five primitive families overlap and need single-owner declarations.** Frozen-files probe, research-marker SHM, condition_id tagging, research-registry CLI, and stats.py BEST port are touched by both epics. Each needs one owner, one consumer. **All five should be owned by LRR Phase 1**; HSEA reads them. HSEA Phase 0 should drop its `check-frozen-files.py --probe` extension as new work and instead **block on LRR Phase 1 frozen-files shipping** then add a thin probe wrapper.

3. **The "drafting visibility" axiom precedent (HSEA `sp-hsea-mg-001`) and LRR's `it-irreversible-broadcast` implication are the same governance work, split across two epics.** Both must land in `hapax-constitution` together, in one PR, with overlapping operator review. **Owner:** LRR Phase 6, with HSEA Phase 0 drafting the precedent text and contributing it as a sub-deliverable to LRR's Phase 6 PR.

4. **State files should be siblings under a shared index, not merged.** The two epics will run with overlapping active phases (HSEA Phases 5–9 parallelize while LRR is still in Phases 4–10). One unified file forces a single-writer constraint that destroys the parallelism. Sibling files (`lrr-state.yaml`, `hsea-state.yaml`) under a shared index file (`research-stream-state.yaml`) with cross-references is the correct design.

5. **Drop #57's 38 tactics are 60% LRR-owned, 30% HSEA-owned, 10% operator-only.** HSEA's Phase 4 cluster I attempts to cover several drop #57 tactics (T1.3, T1.7, T2.2, T2.6, T2.8, T4.8, T4.11) by drafting code patches. **All seven of those drafters generate code that is also LRR phase work.** The fold-in routes them: LRR phases own the *implementation*; HSEA Phase 4 I-drafters become *content surfaces that watch and narrate* the LRR work, not separate implementations. This eliminates duplicate substrate.

**Bottom-line recommendation:** Both epics ship. LRR is the substrate (research integrity, governance, content infrastructure). HSEA is the visibility/content layer that makes LRR's work into the stream itself. The fold-in is a **dependency reordering** — not a merger. The merged sequence has 14 unified phases (UP-0 through UP-13). Critical execution rule: every unified phase has one source-of-truth epic and one secondary-consumer epic; nothing has two owners.

---

## 2. Phase-by-phase overlap matrix

Rows = LRR phases (0–10). Columns = HSEA phases (0–12). Cells classify the relationship.

Key: `DUP` = duplicate scope; `PART` = partial/shared infrastructure; `DEP` = dependency (LRR → HSEA or HSEA → LRR); `COMP` = complement; `CONF` = conflict; `—` = no relationship.

| LRR ↓ / HSEA → | H0 Foundation | H1 Visibility | H2 Activities | H3 Research orch | H4 Code drafting | H5 Biometric triad | H6 Content quality | H7 Self-monitor | H8 Platform value | H9 Revenue | H10 Reflexive | H11 Spawner | H12 Long-tail |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **L0 Verification** | PART (chat-monitor, Kokoro baseline, FINDING-Q) | — | — | — | — | — | — | DEP→ (anomaly narration consumes L0 alerts) | — | — | — | — | — |
| **L1 Research registry** | **PART** (frozen-files, condition_id, stats.py) | DEP→ (HUD reads condition_id) | DEP→ (activities read marker) | **DEP→** (C5/C6 wait on L1) | **DEP→** (I1 PyMC drafter watches L1) | DEP→ (M4 reads condition_id) | — | — | — | — | — | — | — |
| **L2 Archive instrument** | — | DEP→ (research state broadcaster reads archive) | — | DEP→ (C10 reads archive segments) | — | DEP→ (M4 reads 18-month archive) | DEP→ (clip-miner consumes archive) | DEP→ (postmortem reads segments) | DEP→ (chronicle reads archive) | — | DEP→ (F8/F9 read archive) | — | — |
| **L3 Hardware validation** | — | — | — | — | **CONF→ I4** (8B pivot vs 70B path) | — | — | DEP→ (D13 mobo swap watcher) | — | — | — | — | — |
| **L4 Phase A completion** | — | — | — | **DEP→** (C2 spectator event) | DEP→ (drafters wait on Phase A lock) | — | — | — | — | — | — | — | — |
| **L5 Hermes 3 swap (70B)** | — | — | — | DEP→ (C7 OSF amendment, C8 spectator) | **CONF** — supplanted by HSEA I4 (8B pivot); see §4 | — | — | — | — | — | — | — | — |
| **L6 Governance finalization** | **PART** (axiom precedent + irreversible-broadcast = same PR vehicle) | DEP→ (governance overlay reads queue) | — | — | DEP→ (drafter pre-emit consent scan) | DEP→ (M1 consent gate) | — | DEP→ (D12 face redaction narration) | DEP→ (E10 governance audit ticker) | DEP→ (H8 axiom-revenue gate) | — | DEP→ (G8 constitutional decision proxy) | — |
| **L7 Persona spec** | — | DEP→ (persona feeds glass-box prompt overlay) | DEP→ (activities adopt persona register) | — | — | — | DEP→ (B5 self-A/B compares against persona) | — | — | — | DEP→ (F11 stimmung self-narration) | — | — |
| **L8 Content programming via objectives** | — | DEP→ (orchestration strip = G3 = same surface) | **PART** (objectives ↔ activities) | DEP→ (objective-advancement scoring) | — | — | DEP→ (clipability drives objective scoring) | — | DEP→ (E1 RESEARCH.md surfaces objectives) | — | — | — | — |
| **L9 Closed-loop feedback** | — | — | DEP→ (chat → activities) | — | — | DEP→ (M2 voice-Qdrant retrieval) | DEP→ (B8 music-aware self-observation) | — | DEP→ (E3 stimmung-annotated git ticker) | — | — | — | — |
| **L10 Observability + drills + polish** | DEP→ (HSEA HUD reads same Prom series) | **PART** (HUD = D1 from drop #58) | — | — | — | DEP→ (M1 HRV strip = same Prom plumbing) | — | **PART** (anomaly narration = D2-D6 = same alerts) | — | — | — | — | DEP→ (H12 long-tail observability) |

**Read of the matrix:**
- **One conflict cell (L3↔H4 / L5↔H4):** the 70B-vs-8B substrate question. Resolved in §4.
- **Five PART cells:** L0↔H0, L1↔H0, L1↔H1, L6↔H0, L8↔H1, L10↔H1, L10↔H7. Each maps to a shared concept that must be single-owned (§3).
- **No duplicate cells.** Where work could collide, it is actually shared infrastructure, not duplicated implementation.
- **Heavy DEP traffic from LRR → HSEA.** HSEA is structurally a layer on top of LRR. This validates the fold-in: LRR ships the substrate; HSEA reads it.

---

## 3. Shared concept ownership table

For every primitive that both epics touch, a single owner-epic is declared. The other epic READs the primitive at the documented interface.

| # | Concept | Owner epic / phase | Consumer epic / phase | Resolution rule |
|---|---|---|---|---|
| 1 | `scripts/check-frozen-files.sh` (or `.py`) | **LRR Phase 1** (item 4: pre-commit hook) | HSEA Phase 0 (consumes; adds `--probe` mode as a thin extension PR within Phase 0 if and only if LRR Phase 1 has merged) | One tool, two callers. HSEA Phase 0 must NOT drop a parallel `check-frozen-files.py`. If LRR Phase 1 hasn't merged when HSEA Phase 0 opens, HSEA Phase 0 sequencing slips. |
| 2 | `~/hapax-state/research-registry/cond-*/condition.yaml` | **LRR Phase 1** (item 1) | HSEA Phase 1 (research state broadcaster), HSEA Phase 3 (C5/C6/C11), HSEA Phase 4 I1 (drafter waits), HSEA Phase 5 M4 | Append-only by definition. HSEA writes nothing under this path. |
| 3 | `/dev/shm/hapax-compositor/research-marker.json` | **LRR Phase 1** (item 3) | HSEA Phase 1 (1.2 research state broadcaster reads it), HSEA Phase 2 (`reflect`/`critique` activities tag with current condition_id) | LRR's `scripts/research-registry.py` is the only writer. HSEA reads via standard atomic-read pattern. |
| 4 | `scripts/research-registry.py` | **LRR Phase 1** (item 8) | HSEA Phase 3 C-cluster orchestration uses subcommands as-is; HSEA does not extend the CLI. New subcommands needed by HSEA must be PR'd into LRR Phase 1's source file, not forked. |
| 5 | `condition_id` tagging on Qdrant + JSONL + Langfuse | **LRR Phase 1** (item 2: per-segment metadata; item 5: Langfuse extension) | HSEA Phase 3 (C-cluster reads), HSEA Phase 5 M4 (drift detector reads), HSEA Phase 10 F-cluster (reflexive layers cite condition_id) | Same. Backfill is LRR's responsibility (Phase 1 item 9). |
| 6 | `stats.py` PyMC 5 BEST port (drop #57 T1.3) | **LRR Phase 1** (item 7: BEST verification) | HSEA Phase 4 I1 drafter | **Resolution:** HSEA Phase 4 I1 drafter does NOT write the PyMC 5 port from scratch. Instead, I1 becomes a *narration drafter* that watches LRR Phase 1's port commits, drafts a research drop summarizing the change for stream content, and routes the drop through governance queue. This converts I1 from "Hapax writes the canonical research code" to "Hapax narrates the canonical research code being written." See §4 for the same pattern applied to other I-drafters. |
| 7 | Hermes 3 substrate swap | **See §4 — substrate is split into 5a (HSEA-owned 8B) and 5b (LRR-owned 70B, deferred)** | — | Single most consequential ownership decision. |
| 8 | `chat-monitor.service` fix (LRR Phase 0 item 1) | **LRR Phase 0** | HSEA Phase 9 (closed-loop feedback consumes chat signal); HSEA Phase 7 D6 (alert triage reads chat-monitor reconnect metric) | Bug fix. Owner is whichever epic ships first, but LRR Phase 0 is structurally first. |
| 9 | `axioms/persona/hapax-livestream.yaml` | **LRR Phase 7** | HSEA Phase 1 (1.3 glass-box prompt renders it), HSEA Phase 2 activities adopt the register, HSEA Phase 10 F-cluster cites it | Persona is research-validity-load-bearing; LRR owns. HSEA renders it on stream. |
| 10 | `hapax-stream-mode` CLI + axis | **LRR Phase 6** (item 2) | HSEA Phase 6 (B-cluster checks mode for clipability publication), HSEA Phase 9 (H6 revenue overlay default-hidden in `public`) | LRR owns the axis. HSEA reads. |
| 11 | `it-irreversible-broadcast` implication + `sp-hsea-mg-001` precedent | **LRR Phase 6** (item 1) bundled with HSEA Phase 0 0.5 deliverable | Both epics consume | These are the same governance work split across two specs. Single PR vehicle to `hapax-constitution`. HSEA Phase 0 drafts the precedent YAML; LRR Phase 6 ships both as one PR. |
| 12 | `ConsentGatedWriter` for Qdrant (FINDING-R) | **LRR Phase 6** (item 3) | HSEA Phase 5 M2 (retrieval-augmented memory), HSEA Phase 11 G6 (voice-session parallel scoring) | LRR ships the gate. HSEA's later phases call it. |
| 13 | Per-condition Prometheus slicing | **LRR Phase 10** (item 1) | HSEA Phase 1 (1.1 HUD overlay) reads the same series; HSEA Phase 5 M1 (HRV strip) plumbed into the same scrape; HSEA Phase 7 D2 anomaly narration reads | Cardinality budget owned by LRR. HSEA queries via `shared/prom_query.py` (HSEA Phase 0 0.1 deliverable, no overlap). |
| 14 | Stream content surfaces (Cairo overlays, Sierpinski slots, content zones) | **HSEA owns the new surfaces; LRR Phase 8 owns objective-overlay + research-mode tiles** | LRR Phase 8 surfaces (objective overlay, Logos studio view tile, terminal capture tile, PR/CI status overlay) become HSEA-pluggable surfaces. HSEA Phase 1 uses LRR Phase 8's `OutputRouter`/`SourceRegistry` registration pattern. | LRR ships the registration mechanism (Phase 2 item 10 + Phase 8); HSEA writes new sources against it. |
| 15 | Daimonion code-narration / closed loop | **LRR Phase 9** (items 4, 9) — `/dev/shm/hapax-editor-state.json`, `git-state.json`, `ci-state.json` SHM publishers | HSEA Phase 7 D-cluster (FSM recovery narration consumes; alert triage reads); HSEA Phase 11 G15 CI-watch triager extends | LRR ships the publishers. HSEA's anomaly/recovery narration reads them. |
| 16 | `attention bid` mechanism | **LRR Phase 8** (item 10) | HSEA Phase 5 M1 (biometric proactive intervention reuses the attention-bid channel for HRV nudges) | One channel, multiple producers. LRR builds it. |
| 17 | Spawn budget ledger + governance queue | **HSEA Phase 0** (deliverables 0.2, 0.3) | LRR Phase 5 (Hermes swap rate-limited via `check_can_spawn`); LRR Phase 8 objective-driven LLM calls routed through ledger; LRR Phase 9 closed-loop reactor calls budgeted | HSEA owns. LRR consumes. This is the inverse of most other rows. |
| 18 | `promote-*.sh` scripts + `~/Documents/Personal/00-inbox/` flow | **HSEA Phase 0** (deliverable 0.4) | LRR Phase 4 (OSF pre-reg artifact routes through inbox); LRR Phase 6 (constitutional amendments use `promote-axiom-precedent.sh`); LRR Phase 8 (objective edits via inbox) | HSEA owns. LRR consumes. |
| 19 | Glass-box prompt rendering (HSEA 1.3) | **HSEA Phase 1** | LRR Phase 7 persona spec consumed *by* the glass-box renderer for visibility | HSEA owns surface; LRR owns content. |
| 20 | Research-mode tile inventory (Logos studio view, terminal capture, PR/CI status) | **LRR Phase 8** (item 9) | HSEA Phase 1 1.4/1.5/1.6 are different surfaces (HUD, research state broadcaster, governance queue overlay) — no overlap with LRR Phase 8 item 9 if naming kept distinct | Distinct surfaces; document separately to prevent re-implementation drift. |

**Anti-pattern to prevent:** any HSEA file that begins `# Owner: delta` and reimplements something LRR Phase 1 already declares as owned. Sessions picking up HSEA Phase 0 must read this table before writing any code.

---

## 4. 70B vs 8B substrate swap resolution

### The conflict

LRR Phase 5 (lines 531–629 of LRR spec) executes Hermes 3 70B EXL3 3.0bpw via dual-GPU layer split, drops `max_seq_len` to 4096, evicts `hapax-dmn` to GPU 0, and treats this as the canonical Condition A → A' transition. The exit criteria include consent-revocation latency drill (≤500ms over pre-migration envelope) and speech-continuity drill (zero dropped frames during long generation).

HSEA Phase 4 cluster I, sub-drafters I4a/I4b/I4c (drop #58 thesis, drop #59 audit), splits the **8B parallel-pivot** from drop #57 T2.6 into three independent code drafters:
- I4a `t2_6a_tabby_config` — second-instance TabbyAPI config
- I4b `t2_6b_litellm_routes` — additive `local-fast-hermes` / `coding-hermes` / `reasoning-hermes` routes
- I4c `t2_6c_pipeline_dispatch` — `conversation_pipeline.py` dispatch on `active_model_family` field

Drop #56 v3 already established that **the 70B path is unreachable under the operator's `interpersonal_transparency` consent-latency axiom**: 70B layer-split inference on Blackwell+Ampere cannot meet the <2s consent-revocation round-trip the constitutional axiom requires. Drop #57 T2.6 reified this as "8B parallel, not swap." HSEA Phase 4 I4 codifies the implementation. LRR Phase 5 was authored before delta absorbed drop #56 v3 into the LRR scope and still nominally targets 70B-as-swap.

### The three options

(a) **Replace LRR Phase 5 with the 8B pivot, defer 70B to a future epic.** Clean, but loses LRR Phase 5's exit criteria (which are the right exit criteria for *any* substrate change, not just 70B).

(b) **Keep LRR Phase 5 as written; HSEA Phase 4 I4 ships it with explicit axiom-precedent update.** Worst option — HSEA Phase 4 is not the right place to ship a substrate swap; it's a drafter, not a deployer. Also fails to acknowledge that the consent-latency axiom already says 70B is wrong.

(c) **Fork LRR Phase 5 into 5a (8B parallel) and 5b (70B, gated on hardware/quant changes).** Recommended.

### Recommendation: option (c) with HSEA Phase 4 I4 demoted to narration-only

- **Unified Phase 5a (was LRR Phase 5):** Hermes 3 8B parallel pivot. Owner: **LRR**, not HSEA. This is research-validity-load-bearing work; LRR is the authoritative epic. The 8B pivot is the *implementation* of T2.6 / drop #56 v3 inside the LRR sequence. LRR Phase 5a inherits all of LRR Phase 5's exit criteria (consent-revocation drill, speech-continuity drill, CAPABLE-tier preservation) but executes them against the 8B parallel config.
- **Unified Phase 5b (deferred):** Hermes 3 70B path. Gated on either (i) different hardware (PCIe Gen 5 dual-Blackwell, single-card 80GB Blackwell, or similar) or (ii) sub-2s 70B inference demonstrated empirically. Until then, 5b is a backlog item, not an LRR phase.
- **HSEA Phase 4 cluster I4:** rescoped from "Hapax drafts the 8B pivot code" to "Hapax narrates LRR Phase 5a's 8B pivot landing, drafts a research drop summarizing the substrate change, and routes the drop through the governance queue." The three sub-drafters become a single composite spectator narrator. Saves ~600 LOC of duplicate code.
- **Axiom precedent action:** LRR Phase 6 governance pass formalizes the rule: "any future 70B substrate decision must pre-register a consent-revocation drill and pass it before being authorized." Goes into the same `it-irreversible-broadcast` PR vehicle.
- **OSF pre-registration:** the OSF amendment (drop #57 T2.7, current LRR Phase 4 item 4) explicitly names the 8B arm as the C2 condition; the original 70B language is replaced or annotated.
- **DEVIATION-037:** still filed, but its content is the 8B pivot rationale + reference to drop #56 v3 + reference to the consent-latency axiom, not the 70B procedure.

**Why option (c):** it preserves LRR's research integrity machinery, surfaces drop #56 v3 as a binding axiom decision rather than buried research, eliminates the duplicate substrate code in HSEA Phase 4 I4, and leaves a clear path back to 70B if the hardware envelope changes. It also makes the LRR/HSEA boundary cleaner: LRR ships substrate, HSEA narrates it.

---

## 5. Unified phase sequence

The merged sequence has **14 unified phases (UP-0 through UP-13)**. Each phase declares its source phase(s), owner epic, shared state surfaces, and dependencies.

| Unified phase | Source phases | Owner epic | Shared state read/written | Dependencies | Sessions / LOC est. |
|---|---|---|---|---|---|
| **UP-0 Verification & primitives bootstrap** | LRR Phase 0 + HSEA Phase 0 deliverables 0.6 + 0.1 | LRR Phase 0 first; HSEA 0.6 (state file) and 0.1 (`prom_query.py`) ride along | Creates `lrr-state.yaml`, `hsea-state.yaml`, `research-stream-state.yaml` index | — | 2 sessions, ~700 LOC |
| **UP-1 Research registry foundation** | LRR Phase 1 (all 10 items) + HSEA Phase 0 deliverable 0.5 (axiom precedent draft, deferred submission to UP-7) | LRR Phase 1 | Owns `~/hapax-state/research-registry/`, frozen-files hook, condition_id, stats.py BEST | UP-0 | 2-3 sessions, ~1400 LOC |
| **UP-2 Foundation primitives (HSEA core)** | HSEA Phase 0 deliverables 0.2 (governance queue), 0.3 (spawn budget), 0.4 (promote scripts) | HSEA Phase 0 | Owns `governance-queue.jsonl`, `spawn-budget.jsonl`, `promote-*.sh`, `00-inbox/` schema | UP-0, UP-1 (frozen-files probe depends on UP-1) | 2 sessions, ~2100 LOC |
| **UP-3 Archive instrument** | LRR Phase 2 (all 10 items including layout-declared `video_out`) | LRR Phase 2 | Writes `~/hapax-state/stream-archive/`, segment sidecars, `OutputRouter` registration, archive-search CLI | UP-1 | 2-3 sessions, ~1500 LOC |
| **UP-4 Visibility surfaces** | HSEA Phase 1 (all 5 surfaces) | HSEA Phase 1 | Reads UP-1 condition data, UP-3 archive metadata, UP-2 governance queue, UP-0 prom_query | UP-1, UP-2, UP-3 | 2-3 sessions, ~1200 LOC |
| **UP-5 Hardware validation + Hermes 8B prep** | LRR Phase 3 (rescoped: gpu_split for 8B parallel, no eviction of `hapax-dmn` needed) | LRR Phase 3 | Updates systemd unit GPU pins, downloads Hermes 3 8B EXL3 5.0bpw quant, drafts TabbyAPI config | UP-1 | 1-2 sessions, ~300 LOC + systemd config |
| **UP-6 Phase A completion + OSF pre-reg** | LRR Phase 4 (all items, with OSF amendment naming 8B as C2 arm per drop #56 v3) | LRR Phase 4 | Locks Condition A data; writes OSF URL into condition.yaml | UP-1 (registry), UP-5 (hardware ready) | Time-gated: 1–2 weeks operator |
| **UP-7 Hermes 3 8B parallel substrate (resolved §4)** | **LRR Phase 5a** (was LRR Phase 5; 8B path); HSEA Phase 4 I4 demoted to narration-only | LRR Phase 5a | Opens `cond-phase-a-prime-hermes-8b-002` in registry; files DEVIATION-037; runs consent-revocation + speech-continuity drills | UP-5, UP-6 | 2 sessions |
| **UP-7' (deferred backlog)** | LRR Phase 5b (70B path) | Future epic | — | Hardware envelope change | — |
| **UP-8 Governance finalization** | LRR Phase 6 (all 11 items) + HSEA Phase 0 0.5 axiom precedent (`sp-hsea-mg-001`) bundled into one `hapax-constitution` PR | LRR Phase 6 | Ships `hapax-stream-mode` CLI, `it-irreversible-broadcast` + `sp-hsea-mg-001` + `mg-drafting-visibility-001` + `su-privacy-001` clarification + `corporate_boundary` clarification, `ConsentGatedWriter`, presence-detect closed loop, fortress retirement | UP-7 | 2-3 sessions |
| **UP-9 Persona spec** | LRR Phase 7 (all 7 items) | LRR Phase 7 | Writes `axioms/persona/hapax-livestream.yaml`; persona becomes part of frozen-files manifest; HSEA glass-box renders it | UP-7, UP-8 | 1-2 sessions, multi-iteration |
| **UP-10 Core director activities** | HSEA Phase 2 (`draft`, `reflect`, `critique`, `patch`, `compose_drop`, `synthesize`, `exemplar_review`); ReflectiveMomentScorer with 7-day calibration | HSEA Phase 2 | Extends `ACTIVITY_CAPABILITIES`; reads UP-9 persona; respects UP-2 budget | UP-2, UP-9 | 3 sessions, ~2500 LOC |
| **UP-11 Content programming + objectives + closed loop** | LRR Phase 8 + LRR Phase 9 + HSEA Phase 3 (research orchestration) | LRR Phases 8 + 9 own infra; HSEA Phase 3 owns C-cluster narration on top | Writes `~/Documents/Personal/30-areas/hapax-objectives/`; ships `objective-overlay`, hero mode, Stream Deck, YouTube description auto-update, attention bids; ships `chat-signals.json`, daimonion code-narration, async chat queue, scientific captions, voice-over-YouTube ducking, SHM editor/git/ci publishers | UP-3, UP-10 | 5–7 sessions, ~4000 LOC |
| **UP-12 HSEA execution clusters (parallelizable)** | HSEA Phase 4 (rescoped per §4: I1–I3, I5–I7 only; I4 is narration-only and folded into UP-7), Phase 5 (M-series biometric/studio/archival), Phase 6 (B clip mining), Phase 7 (D self-monitor), Phase 8 (E platform value), Phase 9 (H revenue) | HSEA owns each cluster | Each cluster reads UP-1 registry, UP-2 governance queue, UP-2 spawn budget, UP-11 objectives | UP-10 + UP-11 | Parallelizable across alpha + beta worktrees; ~10–15 sessions total, ~13000 LOC |
| **UP-13 Observability + reflexive + spawner + handoff** | LRR Phase 10 + HSEA Phase 10 (reflexive F-cluster) + HSEA Phase 11 (G spawner) + HSEA Phase 12 (long-tail handoff) | LRR Phase 10 owns observability; HSEA owns reflexive + spawner + handoff | Per-condition Prom slicing; stimmung dashboards; 18-item stability matrix; 6 drills + 2-hour stability; FINDING-S decision; T3 prompt caching; cross-repo scrape fixes; F2-F14 reflexive layers (F10 ships first per drop #59); G1-G16 spawn-based touch points; epic close handoff | UP-11, UP-12 | 6–8 sessions, ~6000 LOC |

**Total:** 14 unified phases, 30–45 sessions across 6–10 weeks, ~33,000 LOC. Most parallelism lives in UP-12 (which is intentionally a basket of independent clusters that beta and alpha can split).

**Critical execution note:** UP-7 is the only phase that has a hard predecessor chain. Everything else can be reordered locally if a session has reason to pick a different next phase. The unified state file (§6) supports that.

---

## 6. State file integration design

### Recommendation: sibling files under a shared index

```
~/.cache/hapax/relay/
├── research-stream-state.yaml      # NEW: shared index, single source of truth for which epics are live
├── lrr-state.yaml                  # owned by LRR sessions, cross-referenced from index
├── hsea-state.yaml                 # owned by HSEA sessions, cross-referenced from index
└── alpha.yaml | beta.yaml          # session-level state, unchanged
```

**Why not a single unified file:** LRR and HSEA can have simultaneously active phases (HSEA Phases 5–9 parallelize while LRR is still in Phase 4 collection or Phase 10 observability). A single file imposes a single-writer constraint that destroys the parallelism. Worse, sessions would have to merge concurrent edits, which the relay protocol does not support.

**Why not entirely separate files (current HSEA plan assumption):** sessions picking up either epic must read both files to know whether their work is blocked by cross-epic dependencies. The shared index encodes those dependencies machine-readably.

### `research-stream-state.yaml` schema

```yaml
schema_version: 1
authored_at: 2026-04-14T00:00:00Z

epics:
  lrr:
    state_file: ~/.cache/hapax/relay/lrr-state.yaml
    spec_doc: docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md
    plan_doc: docs/superpowers/plans/2026-04-14-livestream-research-ready-epic-plan.md
    status: active             # active | paused | retired
    current_phase_ref: lrr.current_phase    # path into lrr-state.yaml
  hsea:
    state_file: ~/.cache/hapax/relay/hsea-state.yaml
    spec_doc: docs/superpowers/specs/2026-04-14-hsea-epic-design.md
    plan_doc: docs/superpowers/plans/2026-04-14-hsea-epic-plan.md
    status: active
    current_phase_ref: hsea.current_phase

unified_sequence:
  # Mirrors §5 of drop #62. Sessions read this to understand cross-epic ordering.
  - id: UP-0
    name: Verification & primitives bootstrap
    sources: [lrr.phase_0, hsea.phase_0_deliverables_0_6_0_1]
    owner: lrr
    status: open                # open | in_progress | closed
  - id: UP-1
    name: Research registry foundation
    sources: [lrr.phase_1, hsea.phase_0_deliverable_0_5_draft]
    owner: lrr
    status: pending
    blocks: [UP-2, UP-4, UP-7, UP-12.hsea_phase_4]
  # ... through UP-13

cross_epic_dependencies:
  - producer: lrr.phase_1.frozen_files_hook
    consumer: hsea.phase_0.frozen_files_probe_extension
    interface: scripts/check-frozen-files.{sh,py}
    status: pending
  - producer: lrr.phase_1.condition_id_tagging
    consumer: hsea.phase_3.research_state_broadcaster
    interface: /dev/shm/hapax-compositor/research-marker.json
    status: pending
  - producer: hsea.phase_0.governance_queue
    consumer: lrr.phase_5.deviation_037_routing
    interface: ~/hapax-state/governance-queue.jsonl
    status: pending
  - producer: hsea.phase_0.spawn_budget
    consumer: lrr.phase_8.objective_llm_calls
    interface: shared/budget_ledger.check_can_spawn
    status: pending
  - producer: lrr.phase_6.it_irreversible_broadcast
    consumer: hsea.phase_4.code_drafter_consent_scan
    interface: hapax-constitution axiom registry
    status: pending
  - producer: lrr.phase_7.persona_yaml
    consumer: hsea.phase_1.glass_box_prompt
    interface: axioms/persona/hapax-livestream.yaml
    status: pending

substrate_decision:
  resolved: true
  resolution_doc: docs/research/2026-04-14-cross-epic-fold-in.md  # this drop
  active_substrate_path: hermes_3_8b_parallel
  deferred_paths:
    - hermes_3_70b_layer_split   # gated on hardware envelope change
  authoritative_phase: UP-7

last_modified: 2026-04-14T00:00:00Z
```

**Concurrency rules:**
1. Index file is read-only for execution sessions; only the cross-epic coordinator (alpha during fold-in, then operator) edits it.
2. Each `<epic>-state.yaml` is single-writer (the session that holds `current_phase_owner`), append-friendly via atomic tmp+rename.
3. `session-context.sh` reads all three files and surfaces a unified status line: `LRR: phase 4 (alpha) | HSEA: phase 5 (beta) | UP: 6,12 active`.
4. When either epic closes a phase, the closing session updates both that epic's state file AND the shared index `unified_sequence[N].status`.

**Backwards compatibility:** existing LRR plan and HSEA plan documents reference single state files. They continue to work — the index is a *new layer above*, not a replacement. Sessions that don't know about the index file are no worse off than they are today.

---

## 7. Resource conflict resolutions

| Resource | Conflict | Resolution |
|---|---|---|
| **Operator attention (review queue)** | HSEA budget projects 5–15 inbox items/day at steady state, peaking 20–30 during Phase 4 code-drafting weeks. LRR Phase 4 OSF pre-reg + Phase 5 substrate swap + Phase 6 governance amendments + Phase 7 persona iteration cycles add another ~10 items/week. Combined steady-state peak: ~40 items/day. | **Sequenced, not parallel.** UP-6 (Phase A collection, time-gated by operator voice sessions) is the natural "operator attention low" window for HSEA Phase 0 + UP-2 + UP-4 ramp. Defer UP-12's Cluster I drafters until UP-9 + UP-10 are stable so the operator isn't reviewing persona iterations and code patches in the same week. **Hard cap: 10 inbox items/day during UP-6 voice-collection window**, enforced via spawn-budget per-touch-point caps in HSEA Phase 0 0.3. |
| **Worktree slots (max 4 per hook policy)** | alpha + beta + delta + 1 spontaneous. LRR plan assumes serial single-worktree; HSEA plan assumes alpha + beta parallel on Phases 5–9. | **Allocation:** alpha = active LRR phase. beta = active HSEA UP-12 cluster (one at a time). delta = research-only, no code-writing per global CLAUDE.md subagent git safety. spontaneous = reserved for cross-cutting bug fixes, never for HSEA or LRR phases. |
| **Branch names** | `feat/lrr-phase-N-*` and `feat/hsea-phase-N-*` are already disambiguated. Risk: HSEA Phase 4 cluster I creates ~7 sub-branches; LRR Phase 8 has multiple sub-deliverables. | Add convention: every sub-branch must include the unified phase ID: `feat/up-7-lrr-phase-5a-hermes-8b`, `feat/up-12-hsea-i5-guardrail`. Sessions self-discover the ID from `research-stream-state.yaml::unified_sequence`. |
| **LLM budget ($5/day)** | HSEA Phase 0 0.3 ledger enforces global cap. But LRR Phases 5–10 also make LLM calls (Hermes 3 swap eval, persona testing, closed-loop reactor, weekly correlation report). LRR currently does NOT route through the ledger. | **Resolution:** during UP-2 (HSEA Phase 0 0.3 deliverable), retrofit LRR's LLM call sites to route through `check_can_spawn(touch_point="lrr-<phase>-<purpose>")`. This is one helper import line per call site; ~6–10 sites total. Spawn budget then reflects total epic spend, not just HSEA. **Per-epic sub-caps:** allocate $2/day to LRR (research, persona, closed loop), $3/day to HSEA (drafting). Operator-adjustable. |
| **Compositor deployment slots / Cairo sources** | LRR Phase 8 ships objective overlay, Logos studio view tile, terminal capture tile, PR/CI status overlay. HSEA Phase 1 ships HUD, research state broadcaster, glass-box prompt, orchestration strip, governance queue overlay. Total: 9 new Cairo sources. | LRR Phase 2 item 10 already mandates layout-declared `video_out` migration. Make Cairo source registration go through the new `SourceRegistry` from day one. Each new source is a JSON entry in `config/compositor-layouts/default.json`. **No conflict** as long as zone allocation is documented; add a "zones registry" file at `config/compositor-zones.yaml` that lists every zone and its source. UP-3 ships the registry; UP-4 and UP-11 add their entries. |
| **Director loop activity space** | HSEA Phase 2 expands `ACTIVITY_CAPABILITIES` from 6 → 13. LRR Phase 8 adds objective-advancement scoring on top of the existing 6 activities. LRR Phase 9 adds stimmung-modulated activity selection. | **Order:** UP-10 (HSEA Phase 2 activity expansion) lands before UP-11 (LRR Phase 8 objective scoring + LRR Phase 9 closed loop). LRR Phase 8 / 9 must be aware of the 13-activity taxonomy when computing `objective_advancement_score(a)`. The scoring formulas in LRR Phase 8 item 3 must include the new activities. |
| **Frozen-files manifest churn** | Every condition's frozen-files manifest grows when LRR Phase 7 adds the persona file. HSEA Phase 4 cluster I drafters must respect the active manifest, including the persona file. | **Hard rule:** any HSEA drafter that touches a file in the current condition's frozen-files manifest is required to draft a DEVIATION-NNN inline as part of the patch bundle, and the operator approves DEVIATION + patch as one inbox item, not two. Enforced by `promote-patch.sh`. |

---

## 8. Drop #57 ownership map

Drop #57 has 38 ranked tactics across 5 tiers. For each critical-path tactic, ownership is now declared. The convention:
- **LRR-OWNED:** the tactic is implementation work that LRR phases ship. HSEA may narrate but does not duplicate.
- **HSEA-OWNED:** the tactic is content-execution work that HSEA phases ship.
- **OPERATIONAL:** the tactic is operator-only or external (revenue, distribution, hardware).
- **SHARED:** the tactic spans both — both phases must coordinate.

| Tactic | Description | Owner | Notes |
|---|---|---|---|
| **T1.1** | Deploy FDL-1 fix | OPERATIONAL | Pre-epic; mobo swap recovery; not in scope of either epic. |
| **T1.2** | Phase 4 PR landing (beta worktree bootstrap) | LRR-OWNED → **UP-1** | This IS LRR Phase 1 + Phase 4 execution. HSEA references it but does not ship code. |
| **T1.3** | PyMC 5 BEST port | LRR-OWNED → **UP-1** (item 7) | LRR Phase 1 owns the port. HSEA Phase 4 I1 drafter is rescoped to narration only (drafts a research drop summarizing the port; the port itself is LRR work). |
| **T1.4** | output-freshness Prometheus gauge | LRR-OWNED → **UP-13** (Phase 10 observability) | Could ship earlier as Phase 0 polish. **Not** an HSEA touch point. |
| **T1.5** | fd_count + RSS Prometheus gauges | LRR-OWNED → **UP-13** | Same. |
| **T1.6** | Wire `YOUTUBE_VIDEO_ID` at stream start | LRR-OWNED → **UP-0** (LRR Phase 0 item 1 implicit fix; chat-monitor fix depends on it) | Cheap fix; ride along with chat-monitor repair. |
| **T1.7** | Stimmung-gated director activity prior | LRR-OWNED → **UP-11** (LRR Phase 9 closed loop) | HSEA Phase 4 I2 drafter is rescoped to narration only. The activity prior IS LRR Phase 9 item 2. |
| **T1.8** | AI content disclosure baked into broadcast | LRR-OWNED → **UP-8** (LRR Phase 6 governance) | Stream-start AI disclosure is a governance overlay; LRR Phase 6 ships it. |
| **T2.1** | Attribution integrity daily audit timer | LRR-OWNED → **UP-1** (closely related to Phase 1 backfill verification) or **UP-13** | Move into UP-1 because it is the integrity check that protects Condition A. |
| **T2.2** | Burst-with-gaps director cadence | LRR-OWNED → **UP-11** (LRR Phase 9 + Phase 10 PERCEPTION_INTERVAL tuning) | HSEA Phase 4 I3 drafter is rescoped to narration only. |
| **T2.3** | Director persona + exemplars + anti-patterns | LRR-OWNED → **UP-9** (LRR Phase 7 persona spec authoring) | Persona is LRR's domain. The exemplars + antipatterns YAML files are HSEA Phase 0 deliverables (`shared/exemplars.yaml`, `shared/antipatterns.yaml`); they are *populated* by LRR Phase 7. |
| **T2.4** | Visible research condition diegetic overlay | SHARED → **UP-4** (HSEA Phase 1 1.2 research state broadcaster) | HSEA owns the surface; LRR owns the underlying condition data. |
| **T2.5** | Clipability score per reaction + Obsidian export | HSEA-OWNED → **UP-12** (HSEA Phase 6 B-cluster) | New work, no LRR overlap. |
| **T2.6** | 8B pivot as parallel TabbyAPI config | **LRR-OWNED → UP-7 (was LRR Phase 5; resolved §4)** | Critical: rescoped from "swap" to "parallel pivot" per drop #56 v3. HSEA Phase 4 I4 demoted to narration. |
| **T2.7** | OSF pre-registration amendment | LRR-OWNED → **UP-6** (LRR Phase 4 item 4) | Operator action; LRR Phase 4 sequences it. |
| **T2.8** | LLM output guardrail layer | LRR-OWNED → **UP-9** (persona) or **UP-13** (Phase 10 polish) | Should land alongside the persona spec because both shape utterance behavior. HSEA Phase 4 I5 drafter is rescoped to narration only — actual guardrail code is LRR work because it touches `conversation_pipeline.py`, which is FROZEN under the current condition. The DEVIATION must be filed by the LRR session that opens the new condition. |
| **T3.1** | Zero-touch clip-mining pipeline | HSEA-OWNED → **UP-12** (HSEA Phase 6) | New work. |
| **T3.2** | Cross-platform auto-publish | HSEA-OWNED → **UP-12** (HSEA Phase 6) + **OPERATIONAL** (Publer setup) | HSEA owns the daemon; operator handles platform credentials. |
| **T3.3** | Reflexivity overlay | HSEA-OWNED → **UP-4** (HSEA Phase 1 1.3 glass-box prompt) | HSEA owns. |
| **T3.4** | HN research drop + live status page | HSEA-OWNED + OPERATIONAL → **UP-12** (HSEA Phase 6 / E-cluster) | HSEA Phase 8 E-cluster ships the live status page; operator writes the post. |
| **T3.5** | Sequenced community launches | OPERATIONAL | — |
| **T3.6** | Stimmung × activity preset routing | LRR-OWNED → **UP-11** (LRR Phase 9 closed loop) | LRR Phase 9 ships it. |
| **T3.7** | Scheduled scarce operator cameos | OPERATIONAL | — |
| **T3.8** | `reflect` director activity | HSEA-OWNED → **UP-10** (HSEA Phase 2 activity expansion) | New activity; HSEA Phase 2 owns. |
| **T3.9** | Session protocol batching | LRR-OWNED → **UP-6** (LRR Phase 4) | Phase A operator-collection cadence. |
| **T3.10** | GitHub Sponsors / Ko-fi / Nostr | OPERATIONAL + HSEA-OWNED → **UP-12** (HSEA Phase 9 H1 sponsor copy drafter) | HSEA drafts the copy; operator deploys. |
| **T3.11** | NLnet NGI0 grant | OPERATIONAL + HSEA-OWNED → **UP-12** (HSEA Phase 9 H2) | HSEA drafts the grant; operator submits. |
| **T4.1** | Weekly drops digest + lab notebook | HSEA-OWNED → **UP-12** (HSEA Phase 8 E-cluster) | New work. |
| **T4.2** | Reframe drops with run framing | OPERATIONAL (writing convention) | No code. |
| **T4.3** | Pre-announced substrate swap event | SHARED → **UP-7** (substrate swap) + HSEA Phase 3 C8 (spectator narration) | LRR ships the swap; HSEA narrates. |
| **T4.4** | RESEARCH.md top-level | HSEA-OWNED → **UP-12** (HSEA Phase 8 E1) | New work. |
| **T4.5** | Cognitive prosthetic surfaces | HSEA-OWNED → **UP-12** (HSEA Phase 5 M-series + Phase 8 E-cluster) | M1, M2, M5 cover this. |
| **T4.6** | Three-cell confound design | LRR-OWNED → **UP-6** (Phase 4 OSF amendment names the aux cell) | LRR Phase 4 item 4 must be extended to include the aux cell rationale. |
| **T4.7** | Music-aware commentary | LRR-OWNED → **UP-11** (LRR Phase 9) or HSEA-OWNED → **UP-12** (Phase 5 M3 studio creative-state) | Slight overlap. **Resolution:** HSEA Phase 5 M3 owns the studio creative-state daemon; LRR Phase 9 wires the music-aware reactor signal into stimmung. |
| **T4.8** | YouTube backup ingest URL | HSEA-OWNED → **UP-12** (HSEA Phase 4 I6 drafter) | But the actual `rtmp_output.py` is in `agents/studio_compositor/` and may be frozen. **Resolution:** I6 drafter is allowed if `rtmp_output.py` is not in the active condition's frozen-files manifest (verify in UP-1). If frozen, defer to a DEVIATION cycle. |
| **T4.9** | External watchdog classes | LRR-OWNED → **UP-13** (Phase 10 observability + drills) | New systemd units; LRR Phase 10 owns. |
| **T4.10** | Governance framework spin-off | OPERATIONAL + HSEA-OWNED → **UP-12** (HSEA Phase 8 E4 spin-off doc drafter) | HSEA drafts; operator publishes. |
| **T4.11** | Time-of-day rituals | HSEA-OWNED → **UP-12** (HSEA Phase 4 I7 drafter; the only I-drafter that survives §4 unchanged) | I7 actually writes new ritualized state code; not a duplicate of LRR. |
| **T4.12** | Consent-first face redaction | LRR-OWNED → **UP-8** (LRR Phase 6 governance) | Existing governance closed loop in LRR Phase 6. |

**Tally:**
- LRR-owned: 22 tactics
- HSEA-owned: 11 tactics
- Operational: 5 tactics

**Critical insight:** of HSEA Phase 4 cluster I's 7 sub-drafters (I1–I7), **only I7 (T4.11 ritualized states) survives §4 unchanged**. I1, I2, I3, I4, I5 all become narration-only spectator drafters because the underlying code work is LRR-owned. I6 (T4.8 YouTube tee) is conditional on whether `rtmp_output.py` is frozen. **HSEA Phase 4 should be rescoped from "Hapax drafts critical-path code" to "Hapax narrates LRR's critical-path code landings + drafts T4.11 + T4.8."** Rough LOC delta: ~−2400 from HSEA Phase 4.

---

## 9. Recommended HSEA spec edits

### Edits to `docs/superpowers/specs/2026-04-14-hsea-epic-design.md`

**Section 0 (Headline):** add a paragraph after the "End-state" sentence:

> **Cross-epic relationship.** HSEA does not own the research substrate, the persona spec, the governance amendments, the closed-loop wiring, the per-condition observability, or the substrate swap. Those are all LRR scope. HSEA's role is to (a) ship the shared content-execution primitives (governance queue, spawn budget, promote scripts), (b) ship the visibility surfaces that make LRR's work into stream content, and (c) ship the new work that LRR does not touch (clip mining, revenue preparation, M-series biometric/studio/archival, reflexive content). Drop #62 (cross-epic fold-in) is the authoritative dependency map.

**Section 1 (Prior art):** the row "LRR epic — Parallel, dependency-coupled" needs a stronger tie. Replace the existing description with:

> HSEA is structurally a content-execution layer above LRR. LRR ships the substrate (registry, archive, governance, persona, observability, closed loop). HSEA reads all of LRR's outputs and renders them as visible drafting work routed through an operator-controlled approval queue. The two epics share five primitive families (frozen-files, condition_id, research-marker, research-registry CLI, persona); LRR owns all five and HSEA reads them. See drop #62 §3 for the canonical ownership table.

**Section 2 (Pre-epic verification findings) → Missing primitives subsection:** add a note above the list:

> Several of these primitives are now LRR-owned per drop #62: `scripts/check-frozen-files.py` (LRR Phase 1 item 4) and the persona file (LRR Phase 7) are NOT HSEA Phase 0 deliverables. HSEA Phase 0 still owns: governance queue, spawn budget, promote scripts, axiom precedent draft, and epic state file. The frozen-files probe extension lands as a thin wrapper after LRR Phase 1 merges.

**Section 4 (Phase summary), Phase 4 row:** rewrite the goal:

> ~~Per-task drafters for T1.3 PyMC 5 BEST, T1.7 stimmung prior, T2.2 burst cadence, T2.6 8B pivot (3 sub-drafters), T2.8 guardrail, T4.8 YouTube tee, T4.11 ritualized states~~
>
> **Replacement:** Per-task drafters for the subset of drop #57 tactics that LRR does not own. After fold-in: I6 (T4.8 YouTube tee, if `rtmp_output.py` is not frozen) and I7 (T4.11 ritualized states). All other I-drafters become narration spectator agents that watch LRR phases and draft research drops summarizing the LRR work as it lands; the original code generation for I1, I2, I3, I4, I5 is owned by LRR phases 1, 9, 9, 5a, and 7 respectively.

**Section 5, Phase 4 spec:** rewrite 4.3 list (Per-task drafter subclasses) to reflect the rescoping. Drop I1 / I2 / I3 / I4a-c / I5 from the per-task drafter list; add a new subsection 4.3' "Spectator narrator drafters" that handles them as stream-content-only.

**Section 5, Phase 5 spec (M-series):** no edits needed; the M-series is genuinely additive and does not collide with LRR.

**Section 5, Phase 9 (Revenue):** no edits; entirely HSEA-owned.

**Section 6 (Constitutional axiom precedent):** add a note:

> **PR vehicle:** This precedent ships in the same `hapax-constitution` PR as LRR Phase 6's `it-irreversible-broadcast` implication, `su-privacy-001` clarification, and `corporate_boundary` clarification. HSEA Phase 0 deliverable 0.5 drafts the YAML; LRR Phase 6 (UP-8) opens the PR. Operator review is one cycle covering all three pieces, not two.

**Section 8 (Execution invariants):** add an invariant:

> - **Cross-epic dependency check.** Any HSEA phase that depends on an LRR phase output (per drop #62 §3 ownership table) MUST verify the LRR phase has reached `closed` status in `lrr-state.yaml` before opening. The `research-stream-state.yaml` index file is the canonical lookup.

### Edits to `docs/superpowers/plans/2026-04-14-hsea-epic-plan.md`

**Section 1 (Execution model):** add to the invariants list:

> - **Read `research-stream-state.yaml` before reading `hsea-state.yaml`.** The index file declares cross-epic dependencies that block phase opens.

**Section 3 (Phase dependency graph):** the diagram needs LRR cross-edges. Replace with:

```
                 LRR UP-0 (verification + state files) ─┐
                          │                              │
                          v                              │
                    LRR UP-1 (registry) ──────► HSEA UP-2 (foundation primitives)
                          │                              │
              ┌───────────┼──────────┐                   │
              v           v          v                   v
        LRR UP-3     LRR UP-5    LRR UP-6           HSEA UP-4 (visibility)
        (archive)    (HW prep)   (Phase A)               │
              │           │          │                   │
              └───────────┴──────────┴────► LRR UP-7 (8B substrate, resolved §4)
                                                     │
                                                     v
                                              LRR UP-8 (governance) [+HSEA precedent]
                                                     │
                                                     v
                                              LRR UP-9 (persona)
                                                     │
                                                     v
                                            HSEA UP-10 (activities) ──► UP-11 (objectives + closed loop)
                                                                              │
                                                                              v
                                              ┌───────────────────────────────┴─────────────────────────────┐
                                              │              UP-12 (parallelizable cluster basket)            │
                                              │  HSEA Phase 4 (rescoped)  HSEA Phase 5 (M)  HSEA Phase 6 (B) │
                                              │  HSEA Phase 7 (D)         HSEA Phase 8 (E)  HSEA Phase 9 (H) │
                                              └───────────────────────────────┬─────────────────────────────┘
                                                                              v
                                              UP-13 (LRR Phase 10 + HSEA Phase 10/11/12 + handoff)
```

**Section 4 (Per-phase execution briefs), Phase 4 brief:** change the duration from 5 sessions to 2–3 sessions, change the deliverable list per the spec rescoping, and add: "Phase 4 cannot open until LRR UP-7 has merged."

**Section 8 (Cross-epic coordination):** rewrite. The current text is too vague. Replace with a reference to drop #62 §3 ownership table and §6 state file design.

**Section 11 (Resource budget):** revise LOC estimate from ~29,000 to ~25,000–27,000 (subtracting the rescoped Phase 4 LOC). Revise daily inbox load estimate to reflect the dependency: 5–15 items/day at steady state, with hard cap 10/day during UP-6 voice-collection windows.

---

## 10. Open questions for operator review

1. **Substrate swap path:** confirm the recommendation in §4 (option c — fork into 5a 8B and deferred 5b 70B). The alternative is to keep LRR Phase 5 as written and treat HSEA Phase 4 I4 as either redundant or as an axiom-precedent-update PR. The recommendation here is the cleanest, but it requires accepting that the 70B path is deferred, possibly indefinitely, until hardware changes.

2. **Ownership of T2.8 LLM output guardrail layer:** the guardrail must touch `conversation_pipeline.py`, which is currently FROZEN under `cond-phase-a-baseline-qwen-001`. This means any guardrail change requires a DEVIATION and a new condition. Two options: (a) ship the guardrail under UP-7 (the substrate-swap-induced new condition naturally allows it), bundling it with the 8B pivot DEVIATION. (b) Open a separate condition for the guardrail alone before UP-7. Option (a) is cheaper; option (b) is cleaner research-validity-wise. Operator decision.

3. **HSEA Phase 4 rescoping:** confirm that HSEA Phase 4 should be rescoped from "code drafting" to "narration drafting" for I1–I5 (with I6 conditional and I7 unchanged). This drops ~2400 LOC of HSEA implementation. The alternative is to keep HSEA Phase 4 as code-drafting but route the patches into a separate condition that doesn't touch frozen files — which is unworkable because all the target files are frozen.

4. **State file design:** confirm sibling files under shared index (§6 recommendation) versus a single unified `research-stream-state.yaml`. The sibling design is favored here for parallelism, but if the operator prefers one source of truth, the shared index can be promoted to the only file with both epics' phase tables embedded.

5. **`hapax-constitution` PR strategy:** confirm that LRR Phase 6 and HSEA Phase 0 0.5 should ship as one constitutional PR (~5 amendments and 1 new precedent in one operator review cycle). Alternative: two PRs in close succession. One PR is faster but harder to review. Operator pref.

6. **Cluster H (revenue) timing:** HSEA Phase 9 Cluster H ships sponsor copy, NLnet drafter, consulting gate, etc. Drop #57 tier 3 says these should ship in days 15–21. The unified phase sequence puts them in UP-12, which lands in week 4–6. Two reasons: (a) they depend on UP-2 governance queue; (b) operator review bandwidth. Confirm acceptable, or accelerate by shipping Cluster H first within UP-12.

7. **Worktree allocation:** confirm that delta is research-only / no-code-writing per global CLAUDE.md. Both HSEA spec and HSEA plan are delta-authored; if delta cannot ship code, HSEA execution falls to alpha + beta. This compresses the parallel UP-12 cluster basket from 3 worktrees to 2.

8. **Index file maintenance:** who edits `research-stream-state.yaml::unified_sequence` over time? Recommendation: alpha during fold-in commit, then operator-only edits. Any session that wants to add an entry files a request via the governance queue. Confirm.

9. **Drop #62 itself:** does this drop become a docs/research/ artifact (`docs/research/2026-04-14-cross-epic-fold-in.md`), or does it land as a docs/superpowers/specs/ supplement (`docs/superpowers/specs/2026-04-14-lrr-hsea-fold-in-design.md`)? Recommendation: research drop, with a one-line reference from each of LRR spec §1 and HSEA spec §1.

10. **Phase ordering deviation tolerance:** the unified sequence is a recommended order, not a strict ordering. Within the constraint that UP-7 has hard predecessors, sessions should be allowed to pick a different "next phase" if they have local reason. Confirm this looseness is acceptable or whether the operator prefers strict serial execution.

---

## Closing

The fold-in is mostly mechanical once the substrate-swap question is resolved. The two epics were authored against largely complementary scopes and only collide in five primitive families and one substrate decision. The five primitives have a clear single-owner declaration (LRR owns all of them); the substrate decision is option (c) per §4 (8B parallel as UP-7, 70B deferred).

The downstream cleanup is concentrated in HSEA Phase 4 — that is the one HSEA phase that materially shrinks under the fold-in. Everything else in HSEA is genuinely additive. LRR is unchanged in scope; only its Phase 5 internal structure splits.

The merged sequence is realistic for a single operator: 14 unified phases, 30–45 sessions, 6–10 weeks, with UP-12's cluster basket providing the parallelism needed for alpha + beta to work simultaneously without colliding. The shared state index makes that parallelism legible to every session that picks up either epic.

**Files referenced (repo-relative paths):**
- `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` (LRR spec, 1371 lines)
- `docs/superpowers/plans/2026-04-14-livestream-research-ready-epic-plan.md` (LRR plan, 321 lines)
- `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` (HSEA spec, 794 lines)
- `docs/superpowers/plans/2026-04-14-hsea-epic-plan.md` (HSEA plan, 375 lines)
- `docs/research/2026-04-14-tactics-and-strategies-to-increase-success-probabilities.md` (drop #57, 737 lines)
- `docs/research/2026-04-14-hapax-self-executes-tactics-as-content.md` (drop #58, 480 lines)
- `docs/research/2026-04-14-drop-58-audit-critical-evaluation.md` (drop #59, 444 lines)

---

## 11. Addendum 2026-04-15 — operator ratification of §10 Q1 (Option C)

**Written:** 2026-04-15T05:25Z by delta, after beta's inflection `20260415-051500-beta-delta-alpha-epsilon-operator-ratified-option-c.md` reported the operator's one-word `ratified` response at 05:10Z.

### 11.1 What was ratified

**§10 question 1** ("Substrate swap path") is **closed in favor of option (c)** per §4: LRR Phase 5 forks into

- **5a (now UP-7a)** — Hermes 3 Llama 3.1 **8B** EXL3 5.0bpw parallel primary. Active. Small-footprint swap, runs alongside Qwen 3.5-9B on existing 5060 Ti topology.
- **5b (now UP-7b)** — Hermes 3 Llama 3.1 **70B** layer-split. Deferred backlog artifact. Gated on a future hardware envelope change (second GPU, shared VRAM pool, or equivalent). Beta's 3.5bpw quant chain remains useful as the backlog weight; it is not wasted.

The 8B parallel pivot is explicitly acknowledged by the operator as the LRR Phase 5 substrate path going forward. The 70B swap is no longer the live path and no longer blocks Phase 5 opening.

The ratification **does not** implicitly answer any of the other nine §10 questions (Q2–Q10 remain operator-pending — see §11.4).

### 11.2 Cross-links

**PR #826 — the ratification vehicle**, authored by alpha on the `docs/drop-62-option-c-ratification` branch:

- `docs/research/2026-04-15-drop-62-option-c-ratification.md` — authoritative ratification decision record with rationale, downstream implications, embedded draft LiteLLM routes, draft tabbyAPI config, and the 9-step operator activation sequence.
- `systemd/units/tabbyapi-hermes8b.service` — draft unit for a second TabbyAPI instance on `:5001` serving Hermes 3 8B alongside the Qwen 3.5-9B instance on `:5000`. Not started until operator activation.
- `systemd/units/tabbyapi-hermes8b.service.d/gpu-pin.conf` — drop-in with two candidate GPU allocation blocks, both commented out, awaiting operator decision on placement.

**PR #819 — the LRR Phase 5 pre-staging branch**, authored by the `beta-phase-4-bootstrap` session (operating under `epsilon.yaml` per the relay cohabitation protocol — this is *not* the `beta.yaml` autonomous watcher):

- Commit `738fde330` — initial reconciliation (Phase 5 spec §0.5 + DEVIATION-037 amendment headers added in conditional "RECONCILED WITH DROP #62 OPTION C" form).
- Commit `156beef92` — status flip (Phase 5 spec status line + §0.5 heading + DEVIATION-037 status line all flipped from "reconciled, pending ratification" to "ratified 2026-04-15"). Five-line surgical edit; body content unchanged.

**Inflection trail (paths relative to the relay inbox):**

- `20260415-044500-delta-hsea-epic-cross-epic-fold-in-shipped.md` — delta's drop-#62 shipping inflection to alpha/beta/epsilon (this drop is the artifact it announced).
- `20260415-050000-beta-delta-drop-62-reconciliation-ack.md` — beta's reconciliation ack (commit `738fde330`, triggered the operator's review that ended in `ratified`).
- `20260415-050500-delta-alpha-identity-correction-ack.md` — delta's identity correction and scope handoff to alpha (confirmed alpha owns the ratification PR, delta pivoted to HSEA Phase 0 extraction).
- `20260415-051500-beta-delta-alpha-epsilon-operator-ratified-option-c.md` — beta's ratification announcement (the inflection that asked delta to write this addendum).

**Authoritative docs flipped to RATIFIED (both on PR #819 branch, not yet merged):**

- `docs/superpowers/specs/2026-04-14-lrr-phase-5-hermes-3-substrate-swap-design.md` — status line + §0.5 "Amendment 2026-04-15" heading.
- `research/protocols/deviations/DEVIATION-037.md` — status line flipped.

### 11.3 Downstream implications

The ratification has four structural downstream effects on already-authored documents:

**(a) HSEA epic spec §4, Phase 4, Cluster I4 ("8B parallel pivot as narrated R&D content") becomes structurally sound.** The Cluster I demotion to narration-only (drop #62 §9 HSEA spec edits, committed as part of drop #62) was conditional on option (c) being the substrate path. With Q1 ratified, I1–I5 narration is now the correct scope and no further HSEA spec edits are required for this axis. The spec already reflects it — this addendum is the audit trail, not an edit trigger.

**(b) HSEA epic plan §8 "Cross-epic coordination" — the dependency pointer from HSEA Phase 4 to "LRR UP-7 merged" remains correct but now resolves to "LRR UP-7a (8B) merged", not "UP-7 (70B)".** The dependency wording in the plan is already option-c-neutral ("LRR UP-7 has merged"), so no edit is needed. Noting for future reference.

**(c) Two distinct constitutional artifacts are concretized by Q1 ratification.** Per beta's Item #41 precedent-coherence audit (2026-04-15T~12:00Z), this paragraph originally conflated two structurally-independent concerns. Disambiguated:

1. **`sp-hsea-mg-001` axiom precedent (HSEA Phase 0 deliverable 0.5) — drafting-as-content.** This is the substrate-*agnostic* precedent that codifies "LLM-drafted content under management_governance constraints" as a constitutional pattern. It was already drafted into the HSEA Phase 0 extraction spec (`docs/superpowers/specs/2026-04-15-hsea-phase-0-foundation-primitives-design.md` deliverable 0.5, written 2026-04-15T05:00Z). Q1 Option C does not add or modify this precedent; the precedent stands regardless of which substrate ships. Noting for the constitutional PR authoring session to confirm.

2. **70B reactivation guard rule (LRR Phase 6 amendment) — substrate-specific.** Per beta's inflection §"Epsilon (informational)": the rule *"any future 70B substrate decision must pre-register a consent-revocation drill and pass it before being authorized"* was hypothetical under drop #62's conditional language. With Option C ratified, this becomes a concrete LRR Phase 6 constitutional amendment, NOT an expansion of `sp-hsea-mg-001`. The rule lives in the LRR governance-finalization phase because it is about substrate authorization (LRR concern), not about drafting-as-content (HSEA concern). Epsilon's Phase 6 pre-staging on `beta-phase-4-bootstrap` should incorporate this rule explicitly.

**(d) Phase 5a hardware provisioning window opens immediately.** Per beta's inflection §"Alpha (informational)": the Hermes 3 8B EXL3 5.0bpw quant must be staged on disk before Phase 5a (UP-7a) opens. This is a weight download, not a compute job, and can happen in parallel with the Phase 4 quant chain still running on the 70B path. No action required from delta or this drop; flagged for whichever session opens the provisioning slot.

### 11.4 Status of the other nine §10 questions

| §10 # | Question | Status | Blocks |
|---|---|---|---|
| 1 | Substrate swap path | **CLOSED — option (c) ratified 2026-04-15T05:10Z** | — |
| 2 | T2.8 LLM output guardrail layer — DEVIATION vs bundling under UP-7 | PENDING | T2.8 execution (LRR-owned) |
| 3 | HSEA Phase 4 I1–I5 rescoping to narration (−2400 LOC) | PENDING | HSEA Phase 4 execution |
| 4 | State file design — sibling files under shared index vs unified | PENDING | UP-0 (HSEA Phase 0) opening for state file work |
| 5 | `hapax-constitution` PR strategy — one joint PR vs two sequential | PENDING | Epsilon's Phase 6 plan PR 5 structure; HSEA Phase 0 0.5 ship form |
| 6 | Cluster H (revenue) timing — days 15–21 vs UP-12 (week 4–6) | PENDING | No execution block; long-term priority |
| 7 | Worktree allocation — delta research-only confirmation | PENDING | UP-12 parallelism (3 worktrees vs 2) |
| 8 | `research-stream-state.yaml::unified_sequence` maintenance ownership | PENDING | State file governance |
| 9 | Drop #62 artifact location — research drop vs specs supplement | PENDING | Doc organization only (this drop currently lives in `docs/research/`) |
| 10 | Phase ordering deviation tolerance — strict vs loose within dependency envelope | PENDING | Session autonomy scope |

**Priority order for operator batching** (per beta's 05:15Z inflection, not drop #62's numeric order):

1. **Q5** — constitutional PR strategy. Blocks epsilon's Phase 6 plan PR 5 structure *and* shapes HSEA Phase 0 0.5 ship form.
2. **Q3** — HSEA Phase 4 rescoping confirmation. Saves ~2400 LOC; blocks HSEA Phase 4 execution (whichever session opens it).
3. **Q2** — T2.8 guardrail DEVIATION cycle. Blocks T2.8 execution (LRR-owned per drop #62 §3).
4. **Q4** — state file design. Blocks UP-0 opening (HSEA Phase 0 state file work).
5. **Q6, Q7, Q8, Q9, Q10** — lower-priority coordination questions; no execution blocks, only long-term architecture alignment.

None of Q2–Q10 are urgent in the "decide today or something breaks" sense, but the more the operator resolves in a single batch, the more sessions can align without sequential round-trips.

### 11.5 Delta's action trail from this addendum forward

- **This addendum (§11):** written and committed with the HSEA Phase 0 spec + plan pre-staging docs in a single delta research commit.
- **HSEA Phase 0 per-phase spec + plan extraction:** already written as delta's complementary pre-staging action (per the 05:05Z identity correction inflection scope handoff). Spec at `docs/superpowers/specs/2026-04-15-hsea-phase-0-foundation-primitives-design.md`, plan at `docs/superpowers/plans/2026-04-15-hsea-phase-0-foundation-primitives-plan.md` (being written alongside this addendum).
- **Inflection:** delta will write a brief closure inflection to beta + alpha summarizing the §11 addendum + Phase 0 pre-staging completion after commit.
- **No further drop #62 edits** unless the operator answers additional §10 questions. Each subsequent ratification gets its own addendum section (§12, §13, ...) rather than in-place edits to the body of the drop.

— delta, 2026-04-15T05:25Z

---

## 12. Addendum 2026-04-15 — operator batch ratification of §10 Q2–Q10

**Written:** 2026-04-15T05:45Z by delta, after alpha's inflection `20260415-053500-alpha-beta-epsilon-delta-operator-batch-accepted-all-recommendations.md` reported the operator's keyword "I accept all your recommendations" at 05:35Z.

### 12.1 What was ratified

At 2026-04-15T05:35Z, in response to alpha's comprehensive drop #62 §10 decision pack (posted inline in the terminal session earlier), the operator responded with:

> "I accept all your recommendations"

That keyword ratifies **every remaining item** in drop #62 §10, closing Q2 through Q10 in a single operator turn. Combined with §11's Q1 ratification at 05:10Z, all 10 drop #62 §10 open questions are now resolved.

Additionally, the same operator keyword ratified 6 autonomous-queue items from alpha's parallel recommendation pack (DR-3, DR-7, F1 HLS-disable, F3 gop-size, F6 YUY2→NV12, Qwen config bump). These are non-drop-#62 items and are out of scope for this drop; alpha will ship them directly. They are noted here only for traceability.

### 12.2 Resolutions per question

| Q | Topic | Resolution | Phase 0 impact |
|---|---|---|---|
| 2 | T2.8 LLM output guardrail DEVIATION cycle | **option (a)** — bundle T2.8 into UP-7a DEVIATION; one DEVIATION covers both the substrate swap and the guardrail; one new condition opens for both | None. T2.8 is LRR-owned and executes at UP-7a time. |
| 3 | HSEA Phase 4 full rescoping | **option (a)** — I1/I2/I3/I5 become narration-only; I4 already resolved by Q1; I6 stays conditional; I7 unchanged. Net: HSEA Phase 4 shrinks from 7 code drafters to 2. ~−2,400 LOC. | None to deliverable scope. Note added to HSEA Phase 0 spec §4 decision 6 that `promote-patch.sh` expects only I6/I7 invocations during Phase 4 execution. |
| 4 | State file design | **option (a)** — sibling files under shared index. `~/.cache/hapax/relay/` has `research-stream-state.yaml` + `lrr-state.yaml` + `hsea-state.yaml` (plus session-level `alpha.yaml` / `beta.yaml`, unchanged). | HSEA Phase 0 deliverable 0.6 already assumed this; matches spec. |
| 5 | `hapax-constitution` PR strategy | **option (a)** — one joint PR for LRR Phase 6's 4 constitutional items + HSEA Phase 0 0.5's `sp-hsea-mg-001` precedent. Drafting owned by HSEA Phase 0 (draft YAML); PR vehicle owned by LRR Phase 6 (opens the PR). One operator review cycle. | HSEA Phase 0 deliverable 0.5 already assumed this; matches spec. |
| 6 | Cluster H (revenue) timing | **option (a)** — accept UP-12 timing (week 4–6). No acceleration. | None. |
| 7 | Worktree allocation for parallel UP-12 | **option (a)** — 2-parallel (alpha + beta each own one UP-12 cluster at a time). No spontaneous-worktree promotion into UP-12 work. Identity consolidation at PR #819 merge time (real beta slot naturally inherits). | None. |
| 8 | `research-stream-state.yaml` maintenance authority | **option (a)** — alpha writes the initial file during UP-0 fold-in commit; operator-only edits thereafter. Sessions file governance-queue requests for cross-epic dependency changes. | **Applied to HSEA Phase 0 deliverable 0.6:** spec and plan updated to VERIFY shared index existence and APPEND the HSEA entry, not CREATE the shared index. If the shared index is absent when HSEA Phase 0 opens, the phase MUST block on UP-0 fold-in landing. |
| 9 | Drop #62 artifact location | **option (a)** — keep at `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md`. Add one-line references from LRR spec §1 and HSEA spec §1. HSEA-side reference is already in the drop #62 commit; LRR-side reference gets added at PR #819 rebase time by the PR #819 author. | None. |
| 10 | Phase ordering deviation tolerance | **option (b)** — operator-discretion. Sessions can skip to a later unified phase if hard predecessors are met, for local reason. UP-7 remains the only phase with hard predecessors. | None. |

### 12.3 Cross-links

**Alpha's inflection announcing the batch ratification:**

- `20260415-053500-alpha-beta-epsilon-delta-operator-batch-accepted-all-recommendations.md` — full text of alpha's fan-out to beta/epsilon/delta, containing the 9 Q2–Q10 resolutions + the 6 autonomous-queue resolutions + alpha's ship queue order.

**Beta's PR #826 convergence ack (parallel context, not ratification trigger):**

- `20260415-053000-beta-alpha-pr-826-convergence-ack.md` — written at 05:30Z, 5 minutes before the batch ratification. Describes the complementary materialization of PR #819 (in-place spec + DEVIATION amendment) vs PR #826 (decision record + systemd scaffolding). Useful context for understanding why both PRs are needed and how they compose.

**Alpha's ship queue (from inflection §"Alpha's ship queue"):**

1. ✅ PR #826 merged at 2026-04-15T05:35Z (squash, admin)
2. 🔄 DR-3 (B1) `temporal_buffers` retirement on `chore/drop-47-dr-3-temporal-buffers-retirement`
3. DR-7 (B2) PresetInput retirement (~200 LOC, 4 files)
4. Environment verification (compositor state, v4l2loopback NV12 support)
5. F1 + F3 + F6 cam-stability bundle
6. **Q3 HSEA Phase 4 rescoping** — alpha ships dedicated PR updating HSEA spec + plan to reflect the full rescoping
7. **Decision-capture follow-up** — alpha extends the ratification record at `docs/research/2026-04-15-drop-62-option-c-ratification.md` with all 9 Q2–Q10 decisions + the 6 autonomous-queue resolutions, durable on main

Delta's HSEA Phase 0 extraction work (this drop's addenda + `docs/superpowers/specs/2026-04-15-hsea-phase-0-foundation-primitives-design.md` + `docs/superpowers/plans/2026-04-15-hsea-phase-0-foundation-primitives-plan.md`) is delta's pre-staging path that compose with alpha's decision-capture follow-up: alpha captures the decision rationale in the ratification record, delta captures the deliverable shape in the per-phase spec + plan. No conflict; complementary framings of the same Phase 0 scope.

### 12.4 Downstream edits applied in this commit

Alongside writing this addendum, delta made surgical edits to the pre-staging HSEA Phase 0 spec + plan to reflect Q4/Q5/Q8 ownership clarifications:

- `docs/superpowers/specs/2026-04-15-hsea-phase-0-foundation-primitives-design.md`:
  - §3.6 deliverable 0.6 "Shared index ownership" paragraph added citing Q8 ratification; HSEA Phase 0 verifies-and-appends rather than creates.
  - §3.6 target files list split into "HSEA Phase 0 creates" (hsea-state.yaml) vs "verified-and-appended-to only" (research-stream-state.yaml).
  - §4 "Phase-specific decisions" extended from 5 to 7 items, incorporating Q2, Q3, Q4, Q5, Q8 resolutions and explicitly noting that HSEA Phase 0 has no remaining open questions from drop #62 §10.
  - §7 "Open questions" rewritten from a list of 4 pending questions to a status table showing all 10 questions ratified. Phase 0 has no remaining drop #62 §10 dependencies.

- `docs/superpowers/plans/2026-04-15-hsea-phase-0-foundation-primitives-plan.md`:
  - §0 Preconditions: Q1 and Q2–Q10 ratification checkboxes marked `[x]`; Q3/Q4/Q5/Q8 resolutions enumerated inline with their Phase 0 impact.
  - §0 Preconditions: added "research-stream-state.yaml exists" as an unchecked precondition (Phase 0 blocks on UP-0 fold-in landing).
  - §1.2 task renamed from "Create research-stream-state.yaml shared index" to "Verify research-stream-state.yaml shared index + append HSEA Phase 0 entry"; task body rewritten to verify-and-append rather than create.

### 12.5 Phase 0 readiness implication

With all 10 drop #62 §10 questions resolved, the pre-staging HSEA Phase 0 spec + plan have zero remaining operator-pending dependencies from the drop #62 side. The **remaining** Phase 0 preconditions are:

1. LRR UP-0 (LRR Phase 0 verification) closed
2. LRR UP-1 (LRR research registry) closed
3. FDL-1 deployed to a running compositor
4. `research-stream-state.yaml` created by alpha at UP-0 fold-in commit time (per Q8 resolution)
5. A session claims HSEA Phase 0 via `hsea-state.yaml::phase_statuses[0].status: open`

Precondition 4 is the new precondition that this ratification introduced; it replaces the "create the shared index" task that HSEA Phase 0 originally owned. The timing is: alpha's decision-capture follow-up commit on main may include `research-stream-state.yaml` creation, OR alpha may defer shared-index creation until UP-0 (LRR Phase 0) actually closes. Delta cannot determine which from the alpha inflection alone; both are acceptable timings.

### 12.6 Delta's action trail from this addendum forward

- **This addendum (§12)** written + committed alongside the HSEA Phase 0 spec/plan surgical edits in a single delta research commit.
- **No further drop #62 edits planned.** All 10 §10 questions are closed; the drop is now structurally complete. If future ratifications occur (e.g. downstream execution-time decisions), they get their own sections (§13, §14, ...).
- **HSEA Phase 0 spec + plan** are now ratification-consistent pre-staging docs and can be picked up by whichever session opens Phase 0 (expected to be alpha or beta after UP-0 and UP-1 close, per Q7 worktree allocation).
- **Inflection** will be written to alpha + beta summarizing the addendum + Phase 0 edits after commit.

— delta, 2026-04-15T05:45Z

---

## 13. Addendum 2026-04-15 — operator reframes 5b from "deferred backlog" to structurally unreachable

**Written:** 2026-04-15T06:30Z by delta, after beta's inflection `20260415-062500-beta-alpha-delta-epsilon-70b-quant-killed-5b-unreachable.md` reported the operator's 06:20Z direction "1 hardware env unlikely to change within the year" and beta's subsequent kill of the 3.5bpw quant process at layer 57/80.

### 13.1 What the operator said + what beta did

At 2026-04-15T06:20Z, in response to beta's three-reason quant-completion status report, the operator replied:

> "1 hardware env unlikely to change within the year"

The "1" prefix references beta's reason 1: *"completion preserves the weight as a backlog artifact if hardware envelope ever changes (PCIe Gen 5 dual-Blackwell, single-card 80GB Blackwell, etc.)."* The operator's message directly falsifies the premise: the hardware envelope (RTX 3090 + RTX 5060 Ti, PCIe Gen 4 dual-GPU) is not changing within the year, so the 70B weight has no plausible activation path in the foreseeable future.

Beta's actions in response (all non-destructive):

1. Killed the 3.5bpw quant process (PID 106727) via SIGTERM at layer 57/80. Process terminated cleanly. GPU 1 (RTX 3090) VRAM freed from ~18GB used to 18359 MiB free. Chain-watcher retired.
2. Updated task #63 subject and status to `completed` (quant chain terminated per operator direction).
3. Left the partial 3.5bpw work dir + the bf16 reference weight + the completed 3.0bpw weight on disk — all operator-disposition items per beta's 06:25Z inflection disk table (~221 GB total recoverable, not urgent).
4. Did NOT restart TabbyAPI (operator controls restart timing given the mobo-swap context).
5. Did NOT edit Phase 5 spec §0.5 or DEVIATION-037 (both are correct on 5a, the live path; the 5b reframing is a nuance best captured here).

### 13.2 Reframing: 5b from "deferred backlog" to "structurally unreachable"

The §4 recommendation (option c: fork LRR Phase 5 into 5a 8B parallel + 5b 70B layer-split deferred) was authored 2026-04-14 with the hedge that 5b was *gated on* future hardware-envelope changes or sub-2s 70B inference demonstrations. That hedge is now collapsed:

- **Gate (i) — different hardware** (PCIe Gen 5 dual-Blackwell, single-card 80GB Blackwell, or similar): operator explicitly says this is not going to happen within the year.
- **Gate (ii) — sub-2s 70B inference on current envelope**: drop #56 v3's `interpersonal_transparency` consent-latency axiom analysis established that 70B layer-split on the current hardware cannot meet the <2s consent-latency bound no matter the quant level. This gate was already unreachable; the operator's direction doesn't move it but confirms that no hardware path opens it either.

**Net: 5b is no longer "deferred backlog, may reactivate if hardware envelope changes" — it is "dormant-indefinitely, reactivation requires both a hardware envelope change AND a fresh consent-latency validation."** The 5b reference procedure bodies in Phase 5 spec §0.5 and DEVIATION-037 remain intact as audit-trail documentation of what was assumed when drop #62 §4 was authored, but they describe a path that has no plausible activation trajectory.

### 13.3 Corrections to §11 and §12 framing

§11.1 contained the sentence: *"Beta's 3.5bpw quant chain remains useful as the backlog weight; it is not wasted."* At delta's 05:25Z write time, this was accurate given the hardware gate was plausible. As of 06:20Z operator direction, the premise of "useful as backlog weight" is falsified and the 3.5bpw chain has been killed. Delta does NOT edit §11.1 in place per the "each ratification gets its own addendum" convention (established in §11.5); §11.1 is historically accurate to its write time, and this §13 addendum provides the updated read.

§12.3 item (b) described the HSEA epic plan §8 "Cross-epic coordination" dependency on "LRR UP-7 merged" resolving to "LRR UP-7a (8B) merged, not UP-7 (70B)". That resolution is unchanged: UP-7a (8B parallel) is still the live path. The 06:20Z operator direction does not affect UP-7a in any way.

### 13.4 Implications for downstream artifacts

**(a) 70B reactivation guard constitutional rule (LRR Phase 6 amendment, NOT HSEA Phase 0 0.5).**

**Clarification per beta's item #41 audit finding (2026-04-15T10:15Z) — 2026-04-15T16:15Z inline edit by delta (timestamp corrected 2026-04-15T16:58Z per delta's refill 7 item #96; delta's clock was ~1h ahead during the overnight session, real UTC was ~16:xxZ throughout the addenda writes):** the earlier draft of this subsection conflated two separate precedents. They are:

1. **`sp-hsea-mg-001` (HSEA Phase 0 deliverable 0.5)** — the drafting-as-content precedent. *"Drafting constitutes preparation (not delivery) IFF operator retains discrete revocable non-visual delivery authority."* **Substrate-agnostic by construction.** §14 does not affect this precedent; its content, scope, and ship vehicle (joint `hapax-constitution` PR via LRR Phase 6 per §10 Q5 ratification) are all unchanged by the Hermes abandonment.

2. **The 70B reactivation guard rule** — a **LRR Phase 6 constitutional amendment**, NOT part of `sp-hsea-mg-001`. The rule: *"any future 70B substrate decision must pre-register a consent-revocation drill and pass it before being authorized."* **Substrate-specific by construction** (it is about 70B substrate authorization, which is an LRR concern about research substrate swaps, not an HSEA concern about drafting-as-content).

The two precedents ship together in the same joint `hapax-constitution` PR (per Q5 joint PR ratification), but they are distinct constitutional artifacts. Conflating them would misattribute substrate-specific content to a substrate-agnostic precedent.

**§14 impact on the 70B reactivation guard (LRR Phase 6 rule only):** with 5b structurally unreachable, this rule shifts from a **continuous active guard** (protecting against a plausible near-term 70B reactivation) to a **forward-guard clause for a currently-dormant path**. The rule content does not change; only its scope-of-applicability narrows from "watch for hardware envelope changes" to "if the hardware envelope ever changes beyond the year horizon, gate 70B reactivation on a consent-revocation drill." This is an LRR Phase 6 scope note, not an HSEA Phase 0 0.5 content change.

**§14 impact on `sp-hsea-mg-001` (HSEA Phase 0 0.5 precedent):** **NONE.** The drafting-as-content precedent is substrate-agnostic. §14 does not modify, narrow, or expand `sp-hsea-mg-001`. The HSEA Phase 0 spec's §3.5 axiom precedent deliverable is unchanged by the Hermes abandonment.

Per beta's 06:25Z inflection §"Epsilon" paragraph, the LRR Phase 6 scope-note work is optional for epsilon (not a content change). Per beta's 07:50Z HSEA Phase 0 audit item #3 finding and beta's item #41 cross-phase audit, the two precedents must stay clearly distinguished to prevent re-implementation drift or misattribution during the joint constitutional PR review cycle.

**(b) Phase 5 spec §0.5 + DEVIATION-037 amendment headers.** Beta's PR #819 amendments retain the 5b (70B) reference procedure bodies verbatim as audit trail. This is the correct data structure: the reference procedure is dormant but preserved for future re-examination if the hardware envelope ever changes. Beta is explicitly NOT editing these artifacts in response to the 06:20Z direction, on the grounds that:
1. 5a (the live path) is unchanged.
2. The 5b body is audit-trail; deleting it would erase "what was assumed 2026-04-14."
3. PR #819 is a Phase 4 bootstrap PR; 5b reframing is scope creep past the Phase 4 purpose.

Delta concurs with beta's reasoning. The amendment headers are correct as-authored; the nuance belongs in this drop #62 §13 addendum rather than in the spec or DEVIATION.

**(c) Alpha's `beta.yaml::quant_state` block.** Alpha owns the yaml update per the cohabitation protocol. Beta's 06:25Z inflection §"Alpha" section surfaces the needed edits: `3_5bpw` row flipped to killed status, `chain_watcher_pid` nulled, optional `5b_disposition: "unreachable_structurally"` row added. Delta does not touch beta.yaml.

**(d) Disk disposition (~221 GB recoverable).** Beta's 06:25Z inflection flags three operator-disposition items: `~/hapax-state/quant-staging/work-3.5bpw/` (54 GB partial quant, safe to delete), `~/hapax-state/quant-staging/Hermes-3-Llama-3.1-70B-bf16/` (~140 GB reference weight, operator's call), `~/projects/tabbyAPI/models/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw/` (27 GB completed but dormant, operator's call). Not urgent. Flagged here for audit-trail completeness; operator decides disposition.

### 13.5 Cross-links

- Beta's inflection `20260415-062500-beta-alpha-delta-epsilon-70b-quant-killed-5b-unreachable.md` — full text of the kill report + disk disposition table + implications per peer.
- Operator keyword "1 hardware env unlikely to change within the year" at 2026-04-15T06:20Z (terminal, not relay-captured).
- Task #63 updated by beta at 06:25Z: "Chain 3.5bpw quant — KILLED at layer 57/80 per operator 'hardware env unlikely to change within the year' direction (5b deferred backlog unreachable)".

### 13.6 Delta's action trail from this addendum forward

- **This addendum (§13)** written + committed alongside the LRR Phase 1 per-phase spec + plan pre-staging docs (delta's current extraction task) and the HSEA Phase 2 extraction (alpha's 06:20Z delegated request). Single commit.
- **No further drop #62 edits planned** from delta unless another operator signal lands that shifts the UP-7a/UP-7b framing. If the operator's disposition decisions on the ~221 GB disk artifacts arrive, those are operator-space actions and do not require a §14.
- **No code, no PRs, no worktree.** Same delta constraints as all prior addenda.
- **No ack requested** — this is a closure addendum, not a recipient-action inflection.

— delta, 2026-04-15T06:30Z

---

## 14. Addendum 2026-04-15 — operator abandoned Hermes; substrate question reopened

**Written:** 2026-04-15T07:15Z by delta, after beta's inflection `20260415-070000-beta-delta-awb-activation-plus-two-audits-closure.md` reported the operator's 2026-04-15T06:35Z signal and beta's subsequent substrate re-evaluation research shipped as commit `bb2fb27ca` on `beta-phase-4-bootstrap` (`docs/research/2026-04-15-substrate-reeval-post-hermes.md`, 722 lines).

### 14.1 What the operator said

At 2026-04-15T06:35Z, in response to beta's quant-killed + 5b-reframing state, the operator issued a direct terminal message:

> "We've abandoned hermes. Devote extensive research into if Qwen3.5-9B-exl3-5.00bpw is actually the best production substrate for our very unique use cases."

The message carries two parallel directives:

1. **Hermes abandoned as the substrate.** Not just 70B (which §13 already captured as structurally unreachable) — the 8B Hermes 3 Llama path is also rejected as the substrate. Drop #62 §4 option c's 5a arm ("Hermes 3 Llama 3.1 8B EXL3 5.0bpw parallel primary") is no longer the operator's preferred path. The "parallel primary" framing collapses.

2. **Substrate re-evaluation mandate.** The operator explicitly commissioned research into whether Qwen3.5-9B is the right production substrate. This opens the full substrate landscape for re-evaluation — not just 8B alternatives but any model + post-training combination that fits the hardware envelope and the interpersonal_transparency consent-latency axiom.

Beta accepted the research mandate and shipped 722 lines of substrate re-evaluation across 30+ candidate models, 4 post-training buckets, and ~5 deployable shortlist entries. The research drop is authoritative for the post-Hermes substrate landscape.

### 14.2 Implications for prior addenda

This §14 addendum does NOT invalidate the prior §11/§12/§13 ratification records. Those remain historically accurate to their write times (05:25Z, 05:45Z, 06:30Z) and describe operator decisions that were in force at those times. The §10 Q1 "Option C ratified 2026-04-15T05:10Z" statement in §11.1 is historically true — the operator DID ratify Option C at that time. §14 documents that the operator subsequently withdrew support for the 5a Hermes path ~85 minutes later.

**§11 Q1 status:** was CLOSED (ratified Option C); now REOPENED in practice. Delta does NOT edit §11 in place; the "each ratification gets its own addendum" convention applies to reversals too. §14 documents the reversal without rewriting the audit trail.

**§12 status:** Q2–Q10 ratifications remain valid. None of them depend on the Hermes substrate being the active path:
- Q2 (T2.8 guardrail bundles into UP-7a DEVIATION): the UP-7a DEVIATION no longer has a clear content (substrate is TBD), but the bundling-into-DEVIATION framing is substrate-independent and still valid for whatever future substrate swap occurs.
- Q3 (HSEA Phase 4 Cluster I rescoping): narration-only rescoping is substrate-independent. Still valid.
- Q4 (sibling state files): file layout choice, substrate-independent. Still valid.
- Q5 (joint constitutional PR): axiom precedent shipping mechanism, substrate-independent. Still valid.
- Q6 (Cluster H timing): revenue deliverable timing, substrate-independent. Still valid.
- Q7 (2-parallel worktree): session allocation, substrate-independent. Still valid.
- Q8 (alpha-initial shared index): index ownership, substrate-independent. Still valid.
- Q9 (drop #62 artifact location): file location choice, substrate-independent. Still valid.
- Q10 (phase ordering tolerance): session autonomy scope, substrate-independent. Still valid.

**§13 status:** the 5b reframing ("structurally unreachable on foreseeable hardware envelope") remains valid. The 70B path was structurally unreachable under the current hardware regardless of whether 5a was Hermes or something else. §13 is unaffected.

### 14.3 Beta's substrate research findings (summary)

Beta's `docs/research/2026-04-15-substrate-reeval-post-hermes.md` (commit `bb2fb27ca` on `beta-phase-4-bootstrap`, 722 lines) delivers the following findings relevant to the substrate question. This §14 cross-references the research drop; full details live in the research drop itself, not here.

**Qwen3.5-9B audit (research §1):**
- Current substrate is Alibaba's 2026-03-02 release — multimodal vision-language model with Gated DeltaNet + full attention hybrid, trained with GRPO+GSPO+"million-agent-environment" scaled RL via distillation-from-RL-teacher
- Sits at the RL-heavy extreme of the post-training spectrum (relevant to Shaikh SFT-vs-DPO framing)
- **Two concrete production concerns:** (a) thinking mode default-on may tax LOCAL-tier voice calls with a latency surprise, (b) hybrid-attention JIT compile is "shaky" on first call per exllamav3 README — cold-start latency tax on the first request after startup

**Post-training literature update (research §4):**
- Shaikh SFT-vs-DPO framework confirmed in general form
- Qwen3/Qwen3.5 has NOT been evaluated on any grounding benchmark (RIFTS, QuestBench, SYCON Bench, MultiChallenge) in published work as of April 2026
- Any substrate argument against Qwen3.5-9B on grounding grounds is **predictive from training recipe, not empirical**
- New findings: Laban et al.'s 39% multi-turn degradation across models; Parrot's Qwen-family sycophancy warning at small sizes (Qwen 2.5-1.5B shows 94% follow-rate)

**Candidate landscape (research §5 + §6):**
- 30+ models enumerated across 4 post-training buckets (pure-SFT, SFT+DPO, SFT+RLHF, RL-heavy)
- Deployable shortlist (fits the hardware envelope + consent-latency axiom):
  - Qwen3.5-9B EXL3 5.0bpw (current)
  - Llama 3.1 8B Instruct
  - Qwen3-8B
  - OLMo 3-7B Instruct (SFT + DPO variants)
  - Mistral Small 3.1 24B Instruct

**Unique finding on OLMo 3-7B:** AI2 publishes separate hybrid SFT-only and DPO-only checkpoints as ready EXL3 quants (`turboderp/Olmo-Hybrid-Instruct-SFT-7B-exl3` + `UnstableLlama/Olmo-Hybrid-Instruct-DPO-7B-exl3`). **This is the ONLY candidate in the entire landscape where the Shaikh SFT-vs-DPO hypothesis can be tested within a single model family on identical base weights.** Uniquely valuable for the research program (`claim-shaikh-sft-vs-dpo`), though not necessarily for production.

**Research §9 recommendation (beta's synthesis):**
- **Primary:** keep Qwen3.5-9B as the production substrate, fix three concrete production concerns (disable thinking mode, add TabbyAPI cache warmup, upgrade exllamav3), run RIFTS benchmark for empirical grounding validation
- **Complementary (non-exclusive):** parallel-deploy OLMo 3-7B on a second TabbyAPI slot for the research program's SFT-vs-DPO claim test
- Both actions are HIGH-confidence per beta's research audit

**Research §10.2 Cycle 2 reframing:**
- `claim-shaikh-sft-vs-dpo` claim requires reframing with Hermes abandoned
- Beta recommends **Option Z: defer the claim test to Cycle 3** with cleaner substrate comparison (OLMo SFT vs OLMo DPO on identical base weights)
- Cycle 2 proceeds with grounding-package test only (not a substrate comparison)

**§14 does not ratify the research §9 or §10.2 recommendations.** Those are operator-gated decisions. §14 captures the research content as the current authoritative synthesis of the post-Hermes substrate landscape.

### 14.4 Downstream doc status

**Documents that reference Hermes 3 substrate as the active path (now partially stale):**

1. **Drop #62 §4 three-options analysis** (body of this drop) — describes 5a as "Hermes 3 Llama 3.1 8B EXL3 5.0bpw parallel primary". Historically accurate; operator support withdrawn. Not edited in place per audit-trail convention.

2. **Drop #62 §11.1** (this drop) — describes 5a as the live path. Historically accurate at 05:25Z write time. Not edited in place.

3. **`docs/superpowers/specs/2026-04-14-lrr-phase-5-hermes-3-substrate-swap-design.md`** (beta's PR #819) — the entire Phase 5 spec is about Hermes 3. Beta's amendment headers at §0.5 correctly describe the 8B pivot; the "RATIFIED 2026-04-15" status line is historically true but the Hermes substrate is no longer the chosen path. Beta may want to add a §0.6 reframing note at rebase time, but delta does not direct this edit.

4. **`research/protocols/deviations/DEVIATION-037.md`** (beta's PR #819) — filed against the Hermes 3 8B pivot. Same status as Phase 5 spec.

5. **`docs/research/2026-04-15-drop-62-option-c-ratification.md`** (alpha's PR #826 + PR #833) — alpha's ratification decision record + 5b reframing amendment. The ratification record is historically true; the draft systemd `tabbyapi-hermes8b.service` unit at `systemd/units/tabbyapi-hermes8b.service` is no longer a live trajectory. Alpha may want to add a follow-up amendment noting the Hermes abandonment, but delta does not direct this edit (alpha's ship queue decision).

6. **`docs/superpowers/specs/2026-04-15-lrr-phase-7-persona-spec-design.md`** (delta's `dac6b4974`) — references tuning the persona for "Hermes 3's aggressively system-prompt compliant substrate". The substrate-specific framing is now obsolete. Delta will NOT edit in place; the spec's §2 preconditions already say "UP-7 (substrate swap) closed" without naming Hermes, and §6 risks table mentions Hermes once in a "Pre-Hermes Qwen3.5-9B" risk row. A future Phase 7 opener will read §14 of this drop and know the Hermes framing is historical.

7. **HSEA Phase 4 I4 `t2_6_hermes_8b_pivot_narrator`** (alpha's PR #830) — narrates a substrate transition that now won't occur. Alpha's PR #830 rescoping is still structurally correct (I4 is narration-only), but the specific narration target (Hermes 3 pivot) is no longer a real event. Alpha may want to rescope I4 to "post-Hermes substrate selection narrator" or similar at execution time.

8. **All HSEA Phase 0/1/2/3 specs + plans** (delta's extractions) — none of them reference Hermes directly. They reference "UP-7a substrate swap" generically, which is substrate-agnostic. No edits required.

**Documents that do NOT need updates:**

- HSEA Phase 0 spec + plan (delta's `5b75ad1cd`)
- HSEA Phase 1 spec + plan (delta's `c55f4dad5`)
- HSEA Phase 2 spec + plan (delta's `31119ce6f` + `280d90cab`)
- HSEA Phase 3 spec + plan (delta's `3eabafacb`-adjacent)
- LRR Phase 1 spec + plan (delta's `8a2c42bcf`)
- LRR Phase 2 spec + plan (delta's `03790b07a`)

The substrate-agnostic framing of these docs (referencing "UP-7" or "UP-7a" without naming the substrate) means they remain valid regardless of which substrate the operator ultimately chooses.

### 14.5 Cross-links

- Beta's 07:00Z inflection `20260415-070000-beta-delta-awb-activation-plus-two-audits-closure.md` — source of this §14 addendum's content
- Beta's substrate research drop `docs/research/2026-04-15-substrate-reeval-post-hermes.md` at commit `bb2fb27ca` on `beta-phase-4-bootstrap` — authoritative post-Hermes substrate landscape
- Operator keyword at 2026-04-15T06:35Z: "We've abandoned hermes. Devote extensive research into if Qwen3.5-9B-exl3-5.00bpw is actually the best production substrate for our very unique use cases." (terminal, not relay-captured)
- Delta's assignment inflection `20260415-071000-delta-beta-assignment-thinking-mode-disable.md` — queues the first production-fix derivable from beta's research (thinking-mode disable)

### 14.6 What §14 does NOT do

- Does NOT ratify beta's research §9 recommendation (Qwen3.5-9B primary + OLMo parallel) — operator-gated
- Does NOT retire the `cond-phase-a-prime-hermes-8b-002` condition — that condition may never open at all, in which case it's a never-opened placeholder
- Does NOT invalidate the §10 ratifications (Q1 substrate path is re-open in practice but historically ratified; Q2–Q10 are substrate-independent and remain valid)
- Does NOT direct alpha or beta to edit any downstream docs in place — edits are session-owner decisions
- Does NOT re-open operator decisions; §14 is a status update, not a new ratification

### 14.7 Delta's action trail from this addendum forward

- This §14 addendum written + committed (non-blocking; does not gate any other work)
- Delta continues pre-staging extractions per operator's earlier "always be working" directive. Substrate-agnostic extractions proceed normally (HSEA Phase 4 rescoped, HSEA Phase 5 M-series, etc.)
- Delta's LRR Phase 7 persona spec (`dac6b4974`) remains in the pre-staging queue as-is; the Hermes-specific framing is a minor cosmetic staleness that the Phase 7 opener will notice and handle at execution time
- Delta does NOT rewrite LRR Phase 5 spec or DEVIATION-037 or PR #826 ratification record — those are beta's/alpha's ownership
- **If the operator ratifies a new substrate (e.g., "keep Qwen3.5-9B per beta's research §9 recommendation"), delta will write §15** documenting that ratification and the associated new 5a execution trajectory

— delta, 2026-04-15T07:15Z

— End of drop #62 fold-in analysis.