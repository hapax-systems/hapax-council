# LRR Execution State Runbook

**Scope:** operator-facing single-page status for the Livestream Research Ready (LRR) epic.
**Authoritative surface:** `origin/main` and local infrastructure state as of **2026-04-16**.
**Regeneration:** this doc should be rewritten whenever a phase closes or substrate state changes. Last rewrite: beta (LRR single-session takeover), 2026-04-16.

---

## Headline

Substrate decision is **resolved**. Scenarios 1 (Qwen baseline) + 2 (OLMo-3 parallel backend) are shipped. The second half of the epic (Phases 6-10) is now unblocked; critical-path items are Phase 6 joint constitutional PR and Phase 8/9 engineering work.

---

## Per-phase status table

| # | Phase | Status | Last meaningful change | Blockers | Next execution step |
|---|---|---|---|---|---|
| **0** | Verification & Stabilization | ✅ CLOSED | 2026-04-14 (PR #794) | — | — |
| **1** | Research Registry Foundation | ✅ CLOSED | 2026-04-15 (PRs #840-#844) | — | — |
| **2** | Archive + Replay as Research Instrument | ✅ CLOSED | 2026-04-15 (PRs #849-#864) | — | operator audio-archive activation (#58 runbook ready) |
| **3** | Hardware Migration Validation | ✅ CLOSED (substrate prep) | 2026-04-15 (PR #848) + OLMo deploy 2026-04-16 | — | — |
| **4** | Phase A Completion + OSF Pre-Registration | 🟡 IN-PROGRESS (stream-accumulation-gated) | 2026-04-15 (PRs #845-#852) | Livestream uptime to cross Phase A capture thresholds (OSF filed) | Accumulate Phase A data on-stream; verify `stats.py` BEST on accumulated stream data |
| **5** | Substrate Scenario 1+2 Deployment | ✅ CLOSED | 2026-04-16 (PRs #932-#936) | — | — |
| **6** | Governance Finalization + Stream-Mode Axis | 🟡 SPEC ON MAIN (cherry-picked today) | 2026-04-16 (spec + plan + §0.5 patch applied) | None (substrate ratified) | Begin execution per plan |
| **7** | Persona Spec Authoring (DF-1) | 🟡 SPEC ON MAIN | 2026-04-15 (spec + plan pre-existing) | None (substrate ratified, was pending) | Begin execution — persona spec authoring |
| **8** | Content Programming via Research Objectives | 🟡 SPEC ON MAIN | 2026-04-15 (spec + plan) | Phase 7 for persona grounding (parallel-able) | Author objectives data structure |
| **9** | Closed-Loop Feedback + Narration + Chat | 🟡 SPEC ON MAIN | 2026-04-14 + 2026-04-15 | Phase 8 for content primitives (parallel-able) | chat-monitor + code-narration |
| **10** | Observability, Drills, Polish | 🟡 SPEC ON MAIN (cherry-picked today) | 2026-04-16 | Phase 9 for closed-loop signal | Per-condition Prometheus slicing |
| 11 | (none) | — | — | — | See `2026-04-16-lrr-phase-11-definition.md` — no Phase 11; LRR = phases 0-10 |

---

## Substrate scenario 1+2 state (Phase 5)

| Track | Infrastructure | Exit test | Follow-ups |
|---|---|---|---|
| Scenario 1 — Qwen3.5-9B + RIFTS | Qwen3.5-9B live on TabbyAPI `:5000`, `local-fast`/`coding`/`reasoning` routes | RIFTS harness + baseline run complete (PR #934) | Scale labeling, comparison vs OLMo baselines |
| Scenario 2 — OLMo-3-7B parallel | TabbyAPI-olmo live on `:5001` (GPU 1 pinned), `local-research-instruct` route (PR #932 + #933) | `curl` smoke test returns `ROUTE_OK` | Three-variant (SFT/DPO/RLVR) swap — deferred (queue #212.3); cycle 2 full run — awaits operator |

## Observability posture (post-2026-04-16 recovery)

| Signal | State |
|---|---|
| LiteLLM → Langfuse callback | ✅ wired (success + failure) |
| MinIO `events/` retention | 3d lifecycle (was 14d; tightened during inode crisis) |
| `LANGFUSE_SAMPLE_RATE` | 0.1 (was 0.3) |
| `/data` inode usage | 37% (21.7M cap) |
| ClickHouse `max_concurrent_queries_for_user` | 16 (was 8 — raised during recovery spike) |
| GPU thermal alert | ✅ fixed (was silently broken; orphan metric rename today) |
| Qdrant p99 latency alert | ✅ fixed (was silently broken; orphan metric rename today) |
| Langfuse observations/hour | 46K+ post-fix |
| Failed jobs (legacy backlog) | ingestion-queue=100K, otel=61K — terminal from inode-exhaustion era |

---

## Queue cross-reference (items currently advancing which phase)

| Queue item | Advancing | Status |
|---|---|---|
| #210 / #227 / #241 / #243 | Phase 5 scenario 1 | shipped PR #934 |
| #211 | Phase 5 scenario 2 (TabbyAPI) | shipped PR #932 |
| #212 | Phase 5 scenario 2 (LiteLLM route) | shipped PR #933 |
| #242 | Phase 5 / Phase 10 observability | shipped PR #936 |
| #181 | Meta — cross-epic docs | shipped PR #935 |
| #184, #301-#320 | Meta — bulk audits | shipped PR #937 (batch 1) |
| #147 | This runbook | this doc |
| #145 | Phase 11 clarification | shipped `2026-04-16-lrr-phase-11-definition.md` |
| #225, #226, #228, #239, #240 | Phase 9 + beta ops | pending |

---

## Operator-gated decisions

| Item | Surface | Default-ship date |
|---|---|---|
| Phase 4 OSF pre-reg filing | ✅ FILED 2026-04-16 at https://osf.io/5c2kr/overview | closed |
| Phase 6 joint `hapax-constitution` PR authoring window | constitutional authoring session | awaiting open |
| FINDING-S SDLC pipeline decision | `docs/research/2026-04-13/round5-unblock-and-gaps/phase-6-sdlc-pipeline-audit.md` | 2026-04-22 |
| Scenario 2 three-variant comparison (SFT/DPO/RLVR) | model swap + test | any time; `claim-shaikh` cycle 2 |

---

## Recent PR activity (merged, last 10 LRR-related)

| PR | Title | Closes |
|---|---|---|
| #937 | bulk audits batch 1 + apply scripts/shebang + Grafana alert fixes | #184, #301-#320 partial |
| #936 | RIFTS↔Langfuse comparison gap + MinIO inode wall | #242 |
| #935 | cross-epic tagging audit | #181 |
| #934 | RIFTS harness + Qwen baseline + GPT-4 labeler + --split | #210, #227, #241, #243 |
| #933 | wire OLMo into LiteLLM as local-research-instruct | #212 |
| #932 | OLMo-3-7B-Instruct parallel TabbyAPI on :5001 | #211 |
| #908 | LRR epic spec § Phase 5 cross-ref amendment | #154 |
| #907 | Drop #62 fold-in § Queue cross-reference audit | #152 |
| #906 | Cross-epic dependency graph + Mermaid visual | #149 |
| #905 | Prometheus alert-rule cross-ref audit | #148 (GPU thermal finding applied in #937) |

---

## Constitutive framing — livestream IS the research instrument

All LRR research and development happens via livestream. There are no separate "operator voice sessions," "recording sessions," or offline data collection windows distinct from stream operation. Phase A baseline (Phase 4) accumulates from chat-monitor transcripts, daimonion event logs, compositor token ledger, and stimmung time series captured during normal stream operation — not from separate studio sessions. This is the constitutive LRR commitment from the 2026-04-13 end-state statement.

---

## What to read next

- **Phase 6 opener:** `docs/superpowers/specs/2026-04-15-lrr-phase-6-governance-finalization-design.md` (has §0.5 reconciliation block as of 2026-04-16)
- **Phase 7 opener:** `docs/superpowers/plans/2026-04-15-lrr-phase-7-persona-spec-plan.md`
- **Phase 8 opener:** `docs/superpowers/plans/2026-04-15-lrr-phase-8-content-programming-via-objectives-plan.md`
- **Phase 9 opener:** `docs/superpowers/plans/2026-04-15-lrr-phase-9-closed-loop-feedback-plan.md`
- **Phase 10 opener:** `docs/superpowers/plans/2026-04-15-lrr-phase-10-observability-drills-polish-plan.md`
- **Epic closure criteria:** see `docs/research/2026-04-16-lrr-phase-11-definition.md`

---

— rewritten by beta (LRR single-session takeover), 2026-04-16
