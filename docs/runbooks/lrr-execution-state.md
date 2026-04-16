# LRR Execution State Runbook

**Scope:** operator-facing single-page status for the Livestream Research Ready (LRR) epic.
**Authoritative surface:** `origin/main` and local infrastructure state as of **2026-04-16** (13:15 CDT).
**Regeneration:** rewrite whenever a phase closes or substrate state changes. Last rewrite: beta (LRR single-session takeover continuation), 2026-04-16.

---

## Headline

Stream-ready milestone is **within reach**. Governance foundations shipped today: stream-mode axis, consent-gated Qdrant, presence-T0 gate, stimmung auto-private. Joint constitutional PR awaits operator review at [hapax-constitution#46](https://github.com/ryanklee/hapax-constitution/pull/46). Phase 10 per-condition slicing helpers live; call-site wiring remains. At the governance-complete inflection the hardware migration fires.

---

## Per-phase status table

| # | Phase | Status | Last meaningful change | Blockers | Next execution step |
|---|---|---|---|---|---|
| **0** | Verification & Stabilization | ✅ CLOSED | 2026-04-14 (PR #794) | — | — |
| **1** | Research Registry Foundation | ✅ CLOSED | 2026-04-15 (PRs #840-#844) | — | — |
| **2** | Archive + Replay as Research Instrument | ✅ CLOSED | 2026-04-15 (PRs #849-#864) | — | operator audio-archive activation (#58 runbook ready) |
| **3** | Hardware Migration Validation | ✅ CLOSED (substrate prep) | 2026-04-15 (PR #848) + OLMo deploy 2026-04-16 | — | — |
| **4** | Phase A Completion + OSF Pre-Registration | 🟡 IN-PROGRESS (stream-accumulation-gated) | 2026-04-16 OSF filed @ https://osf.io/5c2kr/overview (PR #945) | Livestream uptime + PyMC MCMC BEST upgrade before Phase B analysis | Accumulate Phase A data on-stream |
| **5** | Substrate Scenario 1+2 Deployment | ✅ CLOSED | 2026-04-16 (PRs #932-#936) | — | — |
| **6** | Governance Finalization + Stream-Mode Axis | 🟡 **MOSTLY SHIPPED** | 2026-04-16 (PRs #947 §2, #948 §3, #949 §5+§6) | hapax-constitution#46 joint PR operator review | §4 redaction + §7 revocation drill + §11 ConsentRegistry.load_all validation |
| **7** | Persona Spec Authoring (DF-1) | 🟡 SPEC ON MAIN; kickoff-state drafted | 2026-04-16 (PR #939) | Phase 6 joint PR merged first | Begin persona schema + YAML authoring |
| **8** | Content Programming via Research Objectives | 🟡 Item 1+2 SHIPPED | 2026-04-16 (PRs #940, #946) | operator seed objectives (on-stream authoring ok) | Items 3-12 (~1,900 LOC remaining) |
| **9** | Closed-Loop Feedback + Narration + Chat | 🟡 Hooks plumbing SHIPPED | 2026-04-16 (PR #943) | substrate consumer wiring | Wire publish_vad_state in daimonion pipeline + DuckController instantiation |
| **10** | Observability, Drills, Polish | 🟡 Helpers SHIPPED | 2026-04-16 (PRs #937 Grafana fixes, #944 condition_metrics, #939 FINDING-S retire) | call-site wiring | Wire record_llm_call_start/finish at LiteLLM consumer sites |
| 11 | (none) | — | — | — | See `2026-04-16-lrr-phase-11-definition.md` — no Phase 11; LRR = phases 0-10 |

---

## Governance-complete (stream-ready) milestone tracker

Milestone fires when all 6 gates below are green. At that point the hardware migration is triggered.

| Gate | State | Shipped as |
|---|---|---|
| Substrate ratified | ✅ | Phase 5 / PRs #932-#936 |
| OSF pre-reg filed | ✅ | PR #945 (URL https://osf.io/5c2kr/overview) |
| Stream-mode axis CLI + API + state | ✅ | PR #947 |
| ConsentGatedQdrant wired at factory | ✅ | PR #948 (FINDING-R closed) |
| Presence-T0 + stimmung auto-private | ✅ | PR #949 |
| Joint `hapax-constitution` PR merged | 🟡 | [constitution#46](https://github.com/ryanklee/hapax-constitution/pull/46) awaits operator |
| Phase 10 per-condition slicing at call sites | 🟡 | helpers shipped (PR #944); call-site wire-in pending |

**5 of 7 green.** Remaining: constitution#46 merge (operator) + one call-site wiring PR (mine). Migration trigger fires when both land.

---

## Substrate scenario 1+2 state (Phase 5)

| Track | Infrastructure | Exit test | Follow-ups |
|---|---|---|---|
| Scenario 1 — Qwen3.5-9B + RIFTS | Qwen3.5-9B live on TabbyAPI `:5000`, `local-fast`/`coding`/`reasoning` routes | RIFTS harness + baseline run complete (PR #934) | Scale labeling, comparison vs OLMo baselines |
| Scenario 2 — OLMo-3-7B parallel | TabbyAPI-olmo live on `:5001` (GPU 1 pinned), `local-research-instruct` route (PR #932 + #933) | `curl` smoke test returns `ROUTE_OK` | Three-variant (SFT/DPO/RLVR) swap — deferred; cycle 2 full run — awaits operator |

## Observability posture (current)

| Signal | State |
|---|---|
| LiteLLM → Langfuse callback | ✅ wired (success + failure) |
| MinIO `events/` retention | 3d lifecycle |
| `LANGFUSE_SAMPLE_RATE` | 0.1 |
| `/data` inode usage | 37% (21.7M cap) |
| ClickHouse `max_concurrent_queries_for_user` | 16 |
| GPU thermal alert | ✅ fixed (PR #937) |
| Qdrant p99 latency alert | ✅ fixed (PR #937) |
| Langfuse observations/hour | 46K+ post-fix |
| Per-condition LLM metrics | helpers shipped (PR #944); call-site wire-in pending |
| Stream mode state file | live at `~/.cache/hapax/stream-mode` |
| Consent gate on Qdrant upserts | active (PR #948) |
| Stream auto-private daemon | systemd unit shipped (not yet enabled) |

---

## Shipped PR chain (this session, latest 12)

| PR | Title |
|---|---|
| #949 | §5+§6 stream-transition gate + auto-private daemon |
| #948 | §3 FINDING-R closure (`get_qdrant()` gated) |
| #947 | §2 stream-mode axis |
| #946 | Phase 8 item 2 hapax-objectives CLI |
| #945 | Phase 4 OSF registration stamp |
| #944 | Phase 10 §3.1 per-condition Prometheus slicing helpers |
| #943 | Phase 9 hooks 3+4 plumbing (YouTube quota + VAD ducking) |
| #942 | Phase 4 OSF pre-reg audit + harden |
| #941 | livestream-IS-research-instrument correction |
| #940 | Phase 8 item 1 Objective schema |
| #939 | FINDING-S retire + Phase 9 prep + Phase 7 kickoff state |
| #938 | Phase 5 closure + Phase 6/10 cherry-picks |

---

## Operator-gated decisions

| Item | Surface | Status |
|---|---|---|
| Phase 4 OSF pre-reg filing | https://osf.io/5c2kr/overview | ✅ FILED 2026-04-16 |
| Phase 6 joint `hapax-constitution` PR | [#46](https://github.com/ryanklee/hapax-constitution/pull/46) | awaiting operator review + `registry.yaml` patch |
| FINDING-S SDLC pipeline retire | Decision shipped in PR #939 | default-ship 2026-04-22 |
| Scenario 2 three-variant comparison | model swap + test | any time; after governance complete |
| Hardware migration trigger | Operator executes when milestone fires | waiting on #46 + call-site wiring PR |

---

## Constitutive framing — livestream IS the research instrument

All LRR research and development happens via livestream. There are no separate "operator voice sessions," "recording sessions," or offline data collection windows distinct from stream operation. Phase A baseline accumulates from chat-monitor transcripts, daimonion event logs, compositor token ledger, and stimmung time series captured during normal stream operation.

---

## What to read next

- **Phase 6 opener:** `docs/superpowers/specs/2026-04-15-lrr-phase-6-governance-finalization-design.md` (§0.5 reconciliation block present)
- **Phase 7 opener:** `docs/superpowers/handoff/2026-04-16-lrr-phase-7-kickoff-state.md` + the plan
- **Phase 8 opener:** plan on main; items 3-12 remaining
- **Phase 9 opener:** hook inventory at `docs/research/2026-04-15-daimonion-code-narration-prep.md`
- **Phase 10 opener:** plan on main; Grafana dashboards + stability matrix pending
- **Migration runbook:** not yet written (fires at governance-complete trigger — see memory `project_rig_migration.md`)
- **Epic closure criteria:** `docs/research/2026-04-16-lrr-phase-11-definition.md`

---

— rewritten by beta (LRR single-session takeover continuation), 2026-04-16 13:15 CDT
