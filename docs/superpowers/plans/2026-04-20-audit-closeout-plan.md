# Audit Closeout — Multi-Phase Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: this is the operator-
> directed closeout of the 2026-04-20 pre-live audit. Execute phases
> in parallel where dependencies permit; do ALL findings.

**Operator mandate (2026-04-20 14:45)**: "Not going live yet. We have
time. Postpone going live until I am satisfied. Things are not in a
good state right now." — this changes the quality bar. We're not
racing a go-live deadline. Every fix should land PROPERLY, with tests,
with thought, with root-cause addressing rather than bandaid patching.
The TTS leak re-occurred despite a shipped gate because the gate was
a bandaid; the grounding_provenance invariant is constitutionally
broken; observability has silent blind spots. Fix the systems, not the
symptoms.

**Goal**: ship every remediation the cascade+alpha audit slices produced,
across content-safety, observability, audio, tests, and post-live
hardening. 104 audits → 2 fails + 19 warns + 14 indeterminates.
All get addressed — **at depth, not at speed**.

**Architecture**: 7 phases, roughly-parallel after Phase 0. Each phase
lands a bundle of fixes that share a risk profile and deploy cadence.

---

## Phase 0 — Ground truth (resolve indeterminates)

**Goal**: flip as many `indeterminate` to `pass`/`fail`/`warn` as possible
so Phase 1+ operates on definite ground.

- [x] 11.2 pool_reuse_ratio re-audit after 30 min steady-state
- [x] 4.7 PipeWire graph baseline snapshot (write+commit)
- [x] 3.5 per-ward FSM-state gauge → recheck
- [x] 8.5 stream-mode-intent dispatch test
- [x] 16.1 NTP + 16.3 journal disk usage confirm
- [x] 10.6 firewall posture operator note

## Phase 1 — Stream-quality + audio routing

**Goal**: the fixes that materially improve what the operator + audience
hear next livestream. Operator-action-only items flagged.

- [x] 4.4 Install `voice-over-ytube-duck.conf` (OPERATOR-ACTION; cascade ships the file in repo, documents the install step)
- [x] 4.2 contact_mic → hapax-livestream leak-path check
- [x] 4.6 notification loopback target trace
- [x] 1.7 shared/notify.py → route through speech_safety
- [x] 15.1 default.json runtime-drift policy decision

## Phase 2 — Observability invariant (Pattern 1 meta-fix)

**Goal**: every invariant-emitter has both a happy-path counter and a
violation-counter. The 2026-04-20 14:08 TTS leak + alpha 12.1 share
this archetype; fix the whole class.

- [x] 12.1 grounding_provenance: director-loop emits UNGROUNDED warning + counter when provenance empty
- [x] 12.3 affordance pipeline recruitment counter
- [x] 12.4 compositional_consumer_dispatch counter
- [x] 12.5 affordance-activation persistence discovery + gauge
- [x] 5.2 face-obscure fail-closed gauge on detector crash
- [x] 7.1 observability-invariant docstring convention (ships as pattern-doc)

## Phase 3 — Test + invariant hardening

- [x] 3.2 test_layout_invariants.py (pytest)
- [x] 3.3 hardcoded-hex migration inventory (19 literals → plan subset for immediate migration vs catalog for post-live)
- [x] 2.5 cursor-file atomic-write test
- [x] 2.4 JSONL append-only static assertion

## Phase 4 — Post-deploy sanity cycle (Pattern 3 fix)

**Goal**: a systemd hook that re-runs alpha's 37-audit slice whenever
hapax-daimonion / studio-compositor / hapax-imagination restart.
Prevents the 2026-04-19 02:29 → 11:47 regression class.

- [x] `scripts/post-deploy-audit.sh` — runs cascade + alpha smoke
- [x] OnUnit= hook on the 3 critical services
- [x] Weekly `hapax-audit.timer` — full 104-row sweep, diffs vs baseline

## Phase 5 — Dispatched research (post-live)

**Goal**: the items that need real design work, not code.

- [x] Task #165: prompt-level slur prohibition — research agent to design the policy + test matrix
- [x] 1.9 trademark / copyrighted-lyric detector — research agent
- [x] 1.11 political flashpoint detector — research agent
- [x] 13.5 aggregated multi-modal risk classifier — research agent

## Phase 6 — Known follow-ups (tasks #182, #183, #166)

- [x] Task #183: yt-audio-state write-on-tick (10 min)
- [x] Task #182: pi-edge council URL stability via mDNS / Tailscale
- [x] Task #166: preset + chain variety (research drop)
- [x] Pi heartbeat coverage: install heartbeat.timer on pi4/pi5/hapax-ai (operator-SSH or separate rsync bundle)

## Phase 7 — Update open tasks + ship PR

- [x] Mark tasks #165, #166, #173, #178, #182, #183 with final status
- [x] Final summary doc
- [x] Push all commits; leave a clean branch state for operator

---

## Risk + dependency matrix

| Phase | Risk | Parallelisable | Operator action needed |
|---|---|---|---|
| 0 | minimal | yes | no |
| 1 | low | yes | yes (4.4, maybe 4.8) |
| 2 | medium (touches running services) | partial | no |
| 3 | minimal | yes | no |
| 4 | low | partial | no |
| 5 | zero (research only) | fully parallel | no |
| 6 | low | yes | yes (9.2 Pi SSH) |
| 7 | zero | serial (last) | no |

**Execution order**: 0 first, then 1+2+3+5+6 in parallel, then 4, then 7.

---

## What success looks like

- Zero `fail` in a re-run of both audit slices
- ≤ 5 `warn` remaining (down from 19; all remaining warns are
  operator-action-only or known-post-live research)
- ≤ 3 `indeterminate` (down from 14; survivors are physical
  operator-only checks)
- Post-deploy sanity cycle armed and validated by forcing a
  compositor restart
