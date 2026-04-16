# LRR Execution State Runbook

**Scope:** operator-facing single-page status for the Livestream Research Ready (LRR) epic.
**Authoritative surface:** `origin/main` and local infrastructure state as of **2026-04-16** (16:00 CDT).
**Regeneration:** rewrite whenever a phase closes or substrate state changes. Last rewrite: beta (LRR single-session takeover, continuous run), 2026-04-16.

---

## Headline

Pre-migration state: governance-complete milestone is 6 of 7 gates green (constitution#46 is operator-gated). Substantial Phase 8/9/10 progress shipped beyond the migration milestone per operator's "keep moving, not ready to migrate yet." Remaining pre-migration work is largely additive — Phase 6 §4 redaction, §7 revocation drill, Phase 8 items 4-12, Phase 9 hook 1 (code-narration), Phase 10 dashboards/drills.

---

## Per-phase status table

| # | Phase | Status | Last change | Remaining pre-migration | Blockers |
|---|---|---|---|---|---|
| **0** | Verification & Stabilization | ✅ CLOSED | 2026-04-14 | — | — |
| **1** | Research Registry Foundation | ✅ CLOSED | 2026-04-15 | — | — |
| **2** | Archive + Replay | ✅ CLOSED | 2026-04-15 | operator audio-archive activation (#58 runbook) | — |
| **3** | Hardware Validation + Substrate Prep | ✅ CLOSED | 2026-04-16 | — | — |
| **4** | Phase A Completion + OSF | 🟢 OPERATOR-DONE; data accumulating | 2026-04-16 (OSF #5c2kr filed) | PyMC MCMC BEST upgrade before Phase B analysis | Stream uptime (autonomous) |
| **5** | Substrate Scenario 1+2 | ✅ CLOSED | 2026-04-16 | — | — |
| **6** | Governance Finalization | 🟡 MOSTLY SHIPPED | 2026-04-16 (§2 #947, §3 #948, §5+§6 #949, §10+§11 #953) | §4 redaction, §7 revocation drill, §12 broadcast-safe typography | hapax-constitution#46 operator merge |
| **7** | Persona Spec | 🟡 SPEC ON MAIN; kickoff-state drafted | 2026-04-16 (#939) | Pydantic persona schema, YAML authoring, stream-mode axis consumer | constitution#46 merge |
| **8** | Content Programming | 🟡 Items 1+2+3 SHIPPED | 2026-04-16 (#940, #946, #954) | Items 4-12 (~1,500 LOC remaining) | — |
| **9** | Closed-Loop Feedback | 🟡 Hooks 3+4 SHIPPED | 2026-04-16 (#943 plumbing, #952 VAD producer) | Hook 1 (code-narration), hook 3 YouTube description wire-in | — |
| **10** | Observability / Drills / Polish | 🟡 Slicing helpers SHIPPED | 2026-04-16 (#944 helpers, #951 llm_call_span, FINDING-S retire) | Stimmung dashboards (Grafana JSON), 18-item stability matrix, 6 drills, per-agent call-site migration | — |
| 11 | (none) | — | — | — | No Phase 11; LRR = phases 0-10 |

---

## Governance-complete (stream-ready) milestone tracker

| Gate | State | Shipped as |
|---|---|---|
| Substrate ratified | ✅ | Phase 5 / #932-#936 |
| OSF pre-reg filed | ✅ | #945 (https://osf.io/5c2kr/overview) |
| Stream-mode axis CLI + API + state | ✅ | #947 |
| ConsentGatedQdrant wired at factory | ✅ | #948 (FINDING-R closed) |
| Presence-T0 + stimmung auto-private | ✅ | #949 |
| Phase 10 per-condition slicing at call sites | ✅ | helpers #944; canonical span #951 |
| Joint `hapax-constitution` PR merged | 🟡 | [constitution#46](https://github.com/ryanklee/hapax-constitution/pull/46) awaits operator |

**6 of 7 green.** constitution#46 + `registry.yaml` patch from operator completes it. Operator has said "not ready to migrate yet" so keep moving on additional pre-migration work.

---

## Shipped today (this session, in chronological order)

| PR | Title |
|---|---|
| #932 | OLMo-3 parallel TabbyAPI :5001 |
| #933 | LiteLLM local-research-instruct route |
| #934 | RIFTS harness + Qwen baseline + GPT-4 labeler |
| #935 | cross-epic tagging audit |
| #936 | RIFTS↔Langfuse gap + MinIO inode recovery |
| #937 | bulk audits batch 1 + Grafana alert fixes |
| #938 | Phase 5 closure + Phase 6/10 cherry-picks |
| #939 | FINDING-S retire + Phase 9 prep + Phase 7 kickoff state |
| #940 | Phase 8 item 1 — Objective schema |
| #941 | livestream-IS-research-instrument correction |
| #942 | Phase 4 OSF pre-reg audit + harden |
| #943 | Phase 9 hooks 3+4 plumbing (YouTube quota + VAD ducking) |
| #944 | Phase 10 per-condition Prometheus slicing helpers |
| #945 | Phase 4 OSF URL stamp |
| #946 | Phase 8 item 2 — hapax-objectives CLI |
| #947 | Phase 6 §2 — stream-mode axis |
| #948 | Phase 6 §3 — FINDING-R / ConsentGatedQdrant wire-in |
| #949 | Phase 6 §5+§6 — transition gate + auto-private daemon |
| #950 | runbook refresh (post Phase 6 wave) |
| #951 | Phase 10 §3.1 — llm_call_span helper |
| #952 | Phase 9 hook 4 — VadStatePublisher in pipecat chain |
| #953 | Phase 6 §10 fortress retire + §11 fail-loud consent load |
| #954 | Phase 8 item 3 — director reads active objectives |
| #46 (constitution) | Joint governance amendment (awaits operator) |

(OSF pre-reg https://osf.io/5c2kr/overview filed by operator 2026-04-16)

---

## Observability posture (current)

| Signal | State |
|---|---|
| LiteLLM → Langfuse callback | ✅ wired (success + failure) |
| MinIO `events/` retention | 3d lifecycle |
| `LANGFUSE_SAMPLE_RATE` | 0.1 |
| `/data` inode usage | 37% (21.7M cap) |
| ClickHouse `max_concurrent_queries_for_user` | 16 |
| GPU thermal alert | ✅ fixed (#937) |
| Qdrant p99 latency alert | ✅ fixed (#937) |
| Langfuse observations/hour | 46K+ |
| Per-condition LLM metrics | helpers shipped; call-site migration mechanical |
| Stream mode state file | live at `~/.cache/hapax/stream-mode` |
| Consent gate on Qdrant upserts | active (#948 + existing 411-LOC gate) |
| VadStatePublisher in daimonion | active after next restart (#952 merged) |
| Stream auto-private daemon | systemd unit shipped; activate with `systemctl --user enable --now hapax-stream-auto-private.timer` |

---

## Operator-gated decisions

| Item | Surface | Status |
|---|---|---|
| Phase 4 OSF pre-reg | https://osf.io/5c2kr/overview | ✅ FILED 2026-04-16 |
| Phase 6 joint `hapax-constitution` PR | [#46](https://github.com/ryanklee/hapax-constitution/pull/46) | awaits operator review + `registry.yaml` patch |
| Hardware migration trigger | BIOS / mobo / CPU / RAM swap; GPUs + storage + peripherals stay | **deferred** — operator not yet ready; keep moving |
| FINDING-S SDLC pipeline retire | Decision in PR #939 | default-ship 2026-04-22 |
| Scenario 2 three-variant comparison | model swap + test | any time after migration window |

---

## Constitutive framing — livestream IS the research instrument

All LRR research and development happens via livestream. There are no separate "operator voice sessions," "recording sessions," or offline data collection. Phase A baseline accumulates from chat-monitor transcripts, daimonion event logs, compositor token ledger, stimmung time series captured during normal stream operation.

---

## Migration scope (when triggered)

Per operator 2026-04-16 clarification, migration only swaps CPU, RAM, mobo. Everything else stays: same GPUs (3090 + 5060 Ti), same storage (`/data`, `/store` physically unchanged), same OS (CachyOS), same NVIDIA driver, same USB peripherals, same network + Pi fleet, same repos + secrets. Downtime ≈ physical swap + BIOS + reboot. No data-volume migration needed.

---

## What to read next (pre-migration work surface)

- **Phase 6 §4 redaction**: `docs/superpowers/specs/2026-04-15-lrr-phase-6-governance-finalization-design.md` §3.4 (stream-mode-aware API response redaction; touches most `logos/api/routes/*`)
- **Phase 6 §7 revocation drill**: spec §3.7 (mid-stream revocation < 5s; needs inotify-based ConsentRegistry watcher)
- **Phase 8 item 4**: objective visibility overlay (Cairo source on compositor)
- **Phase 8 items 5-12**: hero-mode, Stream Deck, YouTube description wire-in, attention bids, environmental perception, overlay content formalization
- **Phase 9 hook 1**: daimonion code-narration (impingement consumer for source='code_narration')
- **Phase 10**: stimmung dashboards (Grafana JSON), 18-item stability matrix, 6 operational drills
- **Migration runbook**: not yet written; will be at migration trigger time per memory `project_rig_migration.md`

---

— rewritten by beta (LRR single-session takeover, continuous run), 2026-04-16 16:00 CDT
