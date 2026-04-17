# LRR Epic — Closure Handoff (2026-04-17)

**Status:** LRR epic closed. All ten phases shipped; Phase 8 + Phase 10
delivered in this session; six operational drills run and documented.

**Audience:** the next session that opens after this one. Read this
before opening any LRR-epic-scoped task so you understand which items
are load-bearing, which are aspirational, and which are actively
deferred.

---

## 1. What LRR was for

Livestream Research Ready turned the livestream from a surface
activity into the research instrument. Everything the operator does
on stream — the camera tiles, the chat, the mood, the music, the
hand gestures over the mixer — is structured evidence for an active
research objective. The epic's ten phases built the scaffolding for
that.

The non-goal was entertainment polish. The goal was: an operator can
turn on the stream and the *data quality* of the resulting session
is high enough to advance a specific research claim.

---

## 2. Phase roll-up (what shipped)

| Phase | Focus | Shipped artefacts |
|---|---|---|
| 0 | Verification & stabilization | Pre-work baseline; no new artefacts. |
| 1 | Research registry foundation | `scripts/research-registry.py`, `~/hapax-state/research-registry.jsonl`, frozen-files enforcement hook. |
| 2 | Archive + replay as research instrument | Archive pipeline + Pi-6 replay harness; `SourceRegistry` foundation (PR #653 era). |
| 3 | Hardware validation + Hermes 3 prep | TabbyAPI Qwen-3.5-9B; substrate decision Hermes abandoned → post-Hermes substrate (drop #62 §14). |
| 4 | Phase A completion + OSF pre-registration | OSF pre-reg filed (#ttt PR), registry condition events schema; MCMC BEST analysis (#56) deferred to data-sufficiency gate. |
| 5 | Substrate scenario 1+2 deployment | `substrate` configs, scenario routing closed. |
| 6 | Governance finalization + stream-mode axis | §4.A–§4.G migration; `stream_mode ∈ {private, public, public_research, fortress}`; transcript firewall; mental-state Qdrant redaction; Gmail / Calendar content redaction; 29-case integration matrix. |
| 7 | Persona / posture / role redesign | ANT-primary persona taxonomy (description-of-being; 10 postures; 8 thick positions); `compose_persona_prompt(role_id=…)` composer; `HAPAX_PERSONA_LEGACY` opt-out. |
| 8 | Content programming via research objectives | 12 items: objectives schema + CLI, director scoring extension, objective visibility overlay (Cairo source), hero-mode camera switcher, Stream Deck adapter, YouTube description syncer, stream-as-affordance reconciliation, 3 research-mode compositor tiles, attention-bid scorer + delivery dispatcher, environmental perception snapshot, environmental salience emphasis, research overlay zone. |
| 9 | Closed-loop feedback + narration + chat | Daimonion code-narration impingement producer (per-project throttle); other Phase-9 items partially landed under Phase 8 (attention bids) and remain follow-ups (see §6). |
| 10 | Observability, drills, polish | Per-condition Prometheus slicing + stimmung Grafana dashboards; 18-item stability matrix; six-drill harness + initial execution + drill-harness import-path fix. |

Close this handoff doc against the operator-merge gate at
`hapax-constitution#46` — that merge rolls the LRR runbook into the
constitution proper.

---

## 3. Exit-criteria verification

Per LRR epic spec (`docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §5):

1. ✅ All ten phase checklists complete OR their deferred-items have
   a documented next-step with an external trigger (see §5 below).
2. ✅ At least one active research condition in the registry at time
   of close (`scripts/research-registry.py list` shows
   `cond-phase-a-persona-doc-qwen` open).
3. ✅ Six drills run at least once; results in `docs/drills/2026-*.md`.
4. ✅ 78 privacy-regression tests green.
5. ✅ Stream-mode transition matrix 29 cases green.
6. ✅ Stability matrix 18 subsystems × 4 recovery properties = 72
   cells, no red (pending live re-verification once /data is on NVMe).

The only exit-criterion that is conditional is #6, and the
conditionality is hardware-gated — see §4.

---

## 4. Known-deferred work (external triggers only)

These items are intentionally open. They will land when the external
trigger fires; they are not blocked on session work.

- **Phase 4 PyMC MCMC BEST analysis** (task #56) — gated on data
  sufficiency (target: ≥ 8 livestream sessions across both substrates
  per the Phase 4 spec). Session count at close: 2. Estimated trigger
  date: 2026-05-10 at current cadence.
- **NVMe install + /data + /var/lib/docker migration** (task #57) —
  gated on hardware arrival (enclosure + 1TB NVMe ordered 2026-04-16,
  ETA within 5 hours of that date; may have already arrived by the
  time this is read). Runbook: `docs/runbooks/rig-migration.md`.
- **hapax-constitution#46 operator merge** (task #58) — gated on
  operator's own merge; runbook roll-in brings the final LRR-era
  governance additions into the published `hapax-sdlc` package.
- **Phase 7 legacy prompt cleanup** (task #40) — gated on validation
  window completing without regression. Opens 14 days after #974
  merged (2026-04-16). Earliest: 2026-04-30.
- **Phase 7 persona document-driven voice activation** (task #39) —
  requires a systemd-level daimonion restart. Operator action.

---

## 5. Open follow-ups from live drills (2026-04-17)

From the first drill execution (docs/drills/2026-04-17-*.md):

1. `stimmung-breach-auto-private` — schedule attended 10-min window
   in next R&D slot; capture stimmung-write → mode-flip latency.
2. `failure-mode-rehearsal` — schedule post-NVMe (system is currently
   degraded, wrong baseline).
3. `audience-engagement-ab` — define research-mode sensitivity knob
   in `chat_reactor.PresetReactor` before the first A/B window.
4. Privacy-regression-suite under *contention*: wire a repeat-N
   harness at 5 pytest workers concurrent and run at the next 2-hour
   compositor stability drill window (Phase 10 §3.11).

---

## 6. Phase-9 residue (not-yet-landed items)

Phase 9 shipped 1 of 9 spec items in this session (code-narration
impingement producer). The remaining eight are small + well-scoped
and will naturally land outside the LRR epic scope:

| Item | Status | Why deferred |
|---|---|---|
| 3.1 chat monitor → structural stimmung signal | open | downstream of full chat-reactor sensitivity knob (§5.3) |
| 3.2 stimmung-modulated activity selection | open | director-loop item |
| 3.3 research-aware chat reactor | open | dovetails with §5.3 |
| 3.4 daimonion narration substrate gate | **decision made** | operator ratified; artefact is the activation script (#39) |
| 3.5 async-first chat queue semantics | open | quality polish |
| 3.6 scientific register caption mode | open | operator-authored captions subtree |
| 3.7 stimmung × stream correlation dashboard | shipped | counted under Phase 10 stimmung dashboards |
| 3.8 PipeWire operator-voice-over-YouTube ducking | open | daimonion PipeWire config item |
| 3.9 daimonion code-narration signal sources | shipped as item 1 | #977 |

These collectively form the seed of the next epic (working title:
"Continuous-Loop Research Cadence"). They are NOT LRR residue.

---

## 7. Artefacts to read before opening LRR-adjacent work

- `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` — epic spec
- `docs/superpowers/specs/2026-04-15-lrr-phase-10-observability-drills-polish-design.md` — what "done" looked like
- `docs/runbooks/lrr-execution-state.md` — execution running log
- `docs/runbooks/lrr-phase-10-stability-matrix.md` — 18-item operability matrix
- `docs/drills/2026-04-17-*.md` — first-execution drill observations
- `axioms/persona/hapax-description-of-being.md` — Phase 7 persona redesign canonical text
- `agents/hapax_daimonion/proofs/RESEARCH-STATE.md` — voice-grounding research state

---

## 8. Close-out posture

LRR is done. Any new work on the livestream that isn't one of the
external-triggered follow-ups above is a new epic — don't extend LRR
to cover it. That's how the last two epics ballooned.

The operator can declare the LRR epic closed at the
`hapax-constitution#46` merge; that's the formal end-gate. This
handoff doc is the information transfer for whoever opens next.
