# Delta Queue Flow & Throughput Organization — 2026-04-20

**Author:** alpha (peer of delta in the trio-delivery protocol)
**Audience:** delta + operator
**Register:** Organizational planning, scientific
**Workstream split source:** [`docs/research/2026-04-19-delta-alpha-coordination-protocol.md`](2026-04-19-delta-alpha-coordination-protocol.md) §2.2 — delta owns daimonion / voice / MIDI / audio-topology / research; alpha owns compositor / HARDM / wards / detectors.
**Triage source:** [`docs/superpowers/research-to-plan-triage-2026-04-20.md`](../superpowers/research-to-plan-triage-2026-04-20.md) — delta's own enumeration of all 46 2026-04-20 research drops against the plan queue (commit `7b57af434`).
**Live state:** [`/home/hapax/.cache/hapax/relay/delta.yaml`](file:///home/hapax/.cache/hapax/relay/delta.yaml) refreshed 2026-04-20T04:10:00Z.

---

## §1. TL;DR

Delta has been on a sustained ~6h sprint from `828ca55d4` (2026-04-20 00:11Z) through `55491704a` (2026-04-20 04:01Z) with **35 commits**, **~21,500 LOC added** across **78 file-touches**, spanning seven feature-families in rapid interleave. The work is shipping; the question is whether the next four hours benefit from continuing the same rapid context-switch cadence or from consolidating one or two families.

**Three highest-leverage next items for delta** (sequenced for unblock-others-first → ship-most-completed-family → cheapest-operator-unblock):

1. **Mode D × voice-tier mutex Phase 3** (task #198) — the only thing that closes a started-but-incomplete family AND closes a coordination gate with alpha. Voice-tier Phases 1–4 are shipped; Mode D mutex Phases 1–2 are shipped; the cross-zone Phase 3 (`director_loop` counters + `acquire_engine` wiring) is the seam between two of delta's already-shipped surfaces. Highest leverage because it converts shipped infrastructure into shipped behavior.
2. **De-monetization safety Phase 2** (capability-catalog risk annotation, CI-blocking field-presence assertion) — go-live Gate 1 support per [`delta-to-alpha-pr1109-merged-queue-20260420.md`](file:///home/hapax/.cache/hapax/relay/delta-to-alpha-pr1109-merged-queue-20260420.md) §G1. Phase 1 shipped (`0886d37ab`); Phase 2 is a one-pass survey that materially advances a go-live blocker without touching any contended file.
3. **Audio-topology Phase 5 (Ryzen-codec pin-glitch watchdog)** — completes the audio-topology family at a natural cap (Phase 6 already shipped as `71ac1accf`, a leapfrog) and turns a recurring operator-hardware annoyance into a deterministic auto-fix. Cheap (~150 LOC, single file), no coordination required.

**4-hour block shape**: Hour 1 = Mode D × voice-tier mutex Phase 3 + counter wiring (seam-closing). Hour 2 = de-monetization Phase 2 catalog audit (governance unblock). Hour 3 = audio-topology Phase 5 pin-glitch watchdog (close family). Hour 4 = elective: either content-programme Phase 2 (ProgrammePlanStore persistence) if alpha has open compositor ground, OR audio-chain L6 multitrack Grafana dashboard if operator confirms AUX 1 routing, OR head-down on Evil Pet `.evl` Phase 1 reverse if operator sends a factory file.

---

## §2. Delta's trajectory today (cluster map + completion state)

### §2.1 Commit-by-cluster (2026-04-20 00:11Z → 04:01Z, 35 commits)

Clusters extracted from `git log --since '2026-04-20 00:00:00'` filtered through delta-zone ownership per [`coordination-protocol §2.2`](2026-04-19-delta-alpha-coordination-protocol.md). LOC is `git log --numstat` aggregated.

| Family | Commits | LOC added | Completion state |
|---|---|---|---|
| **HOMAGE wards × Nebulous Scrim research bundle** | 1 (`828ca55d4`) | 5,145 | Shipped — handoff-doc set, alpha's zone for impl |
| **Vinyl-broadcast 6-doc research bundle** | 1 (`0f7106ac2` includes 6 docs + audio split) | 3,376 | Shipped (research) |
| **Audio-chain retargets (24c retirement, L6 routing)** | 8 (`f1b5cacd4`, `54a10217f`, `6a4867c17`, `7f5ba5eee`, `d0ea67a6f`, `e4a33b47b`, `9fbf77e3a`, `0f7106ac2` partial) | ~1,500 | Topology stable; 5 retargets pending operator AUX 1 confirm per [`delta.yaml audio_config_retargets_queued`](file:///home/hapax/.cache/hapax/relay/delta.yaml) |
| **Voice-tier 7-tier transformation spectrum** | 4 (`071e960ca` P1, `c7eeb17be` P2, `2385cf929` P3a, `99f851cfb` P4) | 2,289 | Phases 1–4 shipped; Phase 3b (`director_loop` impingement, **alpha-zone**) and Phase 5 pending |
| **Director / livestream-halt investigation + watchdog** | 4 (`e1355071d`, `e2175469a`, `e7af06b79`, `9b85da3e6`, `89ac17193`) | 2,367 | Phase 1 watchdog shipped; cold-start fix shipped; Phase 2+ unqueued |
| **Audio-topology declarative CLI** | 6 (`bb04ac104` P1, `5760634af` P2, `3a7ec2670` P3, `55491704a` P4, `71ac1accf` P6) | 2,177 | Phases 1–4 + 6 shipped (Phase 5 watchdog NOT shipped — still queued per [plan §Phase 5](../superpowers/plans/2026-04-20-unified-audio-architecture-plan.md)) |
| **Evil Pet mutex + base-scene auto-boot** | 3 (`b27758c79` P1, `e1da54fae` P2, `c8475becf` systemd) | 1,206 | Phases 1–2 shipped; Phase 3 (`acquire_engine` in `director_loop`, **alpha-zone**) pending per [`mode-d-voice-tier-mutex.md`](2026-04-20-mode-d-voice-tier-mutex.md) |
| **Dead-bridge audit** | 1 (`3d70dddba`) | 978 | Inventory shipped; remediation plan missing — alpha notes this in [research-triage §2 #12](../superpowers/research-to-plan-triage-2026-04-20.md) |
| **Audio-normalization research** | 1 (`df6629f43`) | 318 | Shipped (research); blocked on LADSPA syntax research per triage §1 #8 |
| **Research-to-plan triage + 3 stub plans** | 1 (`7b57af434`) | 416 | Shipped — ramp for next session |
| **Tactical fixes (CI test, face-obscure, CBIP border)** | 3 (`9545829f4`, `f1e8ef483`, `89ac17193`) | 46 | Shipped |
| **Compositor preset-recruitment consumer** | 1 (`74644208e`) | 125 | Shipped — closes director→chain mutation loop |
| **Torso S-4 base-scene writer** | 1 (`1b21fbc52`) | 113 | Shipped — Track 1 voice processing |
| **Degraded-mode HARDM publisher bridge** | 1 (`a07d600bc`) | 20 | Shipped — Gate 3 effectiveness fix |

### §2.2 Throughput signal

- **35 commits / ~6 hours = ~5.8 commits/hour, sustained.**
- **~21,500 LOC inserted; ~140 LOC deleted.** High-write, low-rewrite session — characteristic of greenfield primitive-shipping rather than refactor cycles.
- **Docs-to-code split:** roughly 13,000 LOC of research/docs (`828ca55d4`, `0f7106ac2` partial, `e7af06b79`, `e1355071d`, `3d70dddba`, `df6629f43`, `7b57af434`) vs ~8,500 LOC of code. ~60/40 docs/code by LOC. By commit count it inverts: ~10 docs commits, 25 code commits.
- **Cross-cutting commits:** `0f7106ac2` is the largest single commit (3,376 LOC, 8 files) bundling research drops with audio-config retargets — outlier; the typical commit is one feature-family in 100–700 LOC across 1–3 files.
- **No revert commits in the window.** No commits prefixed `revert`. Single forward push.

### §2.3 What this implies for the next block

Delta is in a productive sprint mode. The risk is not throughput; it is **family-completion**. Several families are at "Phase N shipped, Phase N+1 not shipped" with no PR open and no immediate dependency forcing the next phase. That state is fragile — the cost to resume rises as context decays. The next block should preferentially close started families (audio-topology, voice-tier, Evil Pet mutex) before opening new ones (Evil Pet `.evl` reverse, content-programme P2).

---

## §3. Dependency graph between queued items

Edges read "X must ship before Y." Sources: delta.yaml stated next, the 3 stub plans (`unified-audio-architecture-plan.md`, `dual-fx-routing-plan.md`, `evil-pet-preset-pack-plan.md`), and the demonetization-safety plan §3.1 DAG.

```
PR #1109 (MERGED, 04:05Z) ──── unblocks alpha; no further dependency on delta side

Voice-tier Phase 1 (071e960ca, shipped)
  └─> Phase 2 (c7eeb17be, shipped)
        └─> Phase 3a (2385cf929, shipped)  ── role/stance resolver
              └─> Phase 4 (99f851cfb, shipped) ── monetization + capability registration
                    └─> [Phase 3b: director_loop impingement] ── ALPHA ZONE; cross-zone seam
                          └─> [Phase 5: end-to-end smoketest] ── delta-owned ship gate
                          └─> [Phase 5/6 remaining: documented in voice-transformation-tier-spectrum.md §6+]

Evil Pet mutex Phase 1 (b27758c79, shipped) ── single-owner arbitration + SHM state
  └─> Phase 2 (e1da54fae, shipped) ── engine-gated activation wrappers
        └─> [Phase 3: acquire_engine in director_loop + Prometheus counters] ── ALPHA ZONE; cross-zone seam
              └─> Mode D × voice-tier 5/6 mutex correctness end-to-end
                    └─> Voice-tier Phase 5 (granular-wash) becomes safe to add

Mode D shipped (22dcfc695 + 26cfc6387, 2026-04-19 23:20Z+) ── Gate 2 satisfied (research shipped, capability live)
  └─> Vinyl Mode D capability gates monetization opt-in (via demonet Phase 5)

Audio-topology CLI Phase 1 (bb04ac104, shipped)
  └─> Phase 2 (5760634af, shipped)
        └─> Phase 3 (3a7ec2670, shipped)
              └─> Phase 4 pw-dump (55491704a, shipped)
                    └─> Phase 6 canonical descriptor (71ac1accf, shipped — leapfrogged Phase 5)
              └─> [Phase 5: Ryzen-codec pin-glitch watchdog] ── DELTA ZONE; small, no coordination
                    └─> CI gate (Phase 6 §last bullet) becomes meaningful

De-monetization Phase 1 (0886d37ab, shipped, 2026-04-19 23:36Z) ── primitive + field
  └─> Phase 2: catalog audit + risk classification ── DELTA ZONE; CI-blocking
        └─> Phase 3: Ring 2 pre-render classifier ── DELTA ZONE; large
              └─> Phase 4: classifier-degraded fail-closed ── DELTA ZONE; mid
              └─> Phase 6: egress audit JSONL ── parallel-safe with 4
                    └─> Phase 7: music provenance ── DELTA ZONE
                          └─> Phase 8: music policy ── OPERATOR-GATED on §11 Q1
        └─> Phase 5: Programme.monetization_opt_ins ── BLOCKED on content-programme P1 (already shipped f6cc0b42b)
              └─> Phase 11: quiet-frame programme ── BLOCKED on Phase 3

Content programmes Phase 1 (f6cc0b42b, shipped) ── Programme primitive
  └─> Phase 2: ProgrammePlanStore persistence ── DELTA ZONE per delta.yaml delta_next
        └─> Phase 3+: Programme transitions, choreographer recruitment

Evil Pet `.evl` preset pack Phase 1 ── BLOCKED on operator providing factory `.evl` file for hexdump
  └─> Phase 2: build_preset.py
        └─> Phase 3: SD-card deployment (operator action)
              └─> Phase 4: preset-recall MIDI glue
                    └─> Phase 5: firmware decision gate (operator-gated)

Dual-FX routing Phase 1 ── DELTA ZONE; needs S-4 USB enumeration
  └─> Phase 2: routing-map yaml
        └─> Phase 3: select_voice_path hook
              └─> Phase 4: PipeWire route switcher
                    └─> Phase 5: voice-tier integration
                          └─> Phase 6: S-4 firmware (operator-gated)

Audio-chain L6 multitrack validation ── BLOCKED on operator AUX 1 confirm + Rode Wireless Pro on ch 1
  └─> 5 retargets per delta.yaml audio_config_retargets_queued
        └─> Grafana dashboard for L6 ch routing

Dead-bridge mental_state_redaction.py wiring ── CROSS-ZONE; both delta and alpha touch
```

### §3.1 What the graph reveals

- **Two cross-zone seams** dominate the critical path: voice-tier Phase 3b and Mode D mutex Phase 3 both terminate in `agents/studio_compositor/director_loop.py` (alpha's file). These are the only edges where a delta dependency leaves delta's zone. Both can be unblocked by delta writing the shared-side glue (impingement schema, SHM read pattern) and handing alpha a one-PR pickup.
- **Two operator-gated chains** are completely blocked: Evil Pet `.evl` reverse (needs factory file) and Audio-chain L6 retargets (needs AUX 1 routing confirm). Neither benefits from delta time until operator signals.
- **Demonetization Phase 5 unblocked early**: the plan §3.1 marks Phase 5 as "stub until task #164 P1." Task #164 P1 = `f6cc0b42b` shipped already. Delta can ship Phase 5 non-stub on the same wave as Phase 2.
- **Single longest delta-only chain**: demonetization Phase 1 → Phase 2 → Phase 3 → Phase 4 (~12–18 dispatch hours per the plan §3.2 critical path).

### §3.2 Parallelizable fringe (no coordination required)

- Audio-topology Phase 5 (pin-glitch watchdog)
- Demonetization Phase 2 (capability catalog audit)
- Demonetization Phase 5 (Programme opt-ins, now non-stub)
- Demonetization Phase 6 (egress audit JSONL writer + rotation)
- Content-programme Phase 2 (ProgrammePlanStore persistence)
- Audio-chain mixquality skeleton (`docs/research/2026-04-20-mixquality-skeleton-design.md`)
- Vinyl-broadcast signal-chain software wiring (research #36 in triage)

These five+ items can ship independently with no peer dependency.

---

## §4. Bottleneck + flow analysis

### §4.1 Critical path

The longest delta-owned chain is **demonetization Phase 1 → Phase 2 → Phase 3 → Phase 4** at ~12–18 dispatch hours per [`demonetization-safety-plan.md §3.2`](../superpowers/plans/2026-04-20-demonetization-safety-plan.md). Phases 1 (`0886d37ab`) and the field declaration are already shipped; Phase 2 is the next gate; Phase 3 is the heavy LLM-classifier integration.

The next-longest is voice-tier Phase 5+6+7 — but the spec for these in [`voice-transformation-tier-spectrum.md`](2026-04-20-voice-transformation-tier-spectrum.md) treats Phase 4 (shipped) as the meaningful capability gate; remaining phases are tuning passes against operator regression.

Audio-topology is one Phase 5 from complete and Phase 6 already leapfrogged. Effectively 80% complete; sub-2-hour wrap.

### §4.2 Where delta will idle-wait

- **Audio-chain L6 retargets** wait on operator AUX 1 confirm + physical Rode Wireless Pro receiver placement. No delta time can advance these until operator signals.
- **Evil Pet `.evl` Phase 1** waits on operator providing a factory `.evl` file to hexdump.
- **De-monetization Phase 8** waits on operator answering §11 Q1 (mute-and-transcript vs ≤30s clip windower).
- **Content-programme Phase 11 (quiet-frame)** waits on Phase 3 of demonet shipping.
- **Voice-tier Phase 3b** and **Mode D mutex Phase 3** wait on alpha's bandwidth — but the wait is bidirectional: alpha cannot start without delta's impingement schema. Solving this with a one-shot delta-side glue PR converts wait to an unblock.

### §4.3 Re-loop risk

- **Voice-tier 7-phase plan** is the highest re-loop risk: each tier (T0–T6) modulates 9 dimensions across two FX engines. A Phase 5 add could regress Phases 1–4 audibly. Mitigation: audible regression test — each phase ends with a 3-utterance smoketest at every lower tier — already in the spec.
- **Audio-topology** has zero re-loop risk; declarative descriptors make the round-trip self-checking via `verify`.
- **Evil Pet mutex** Phase 3 carries the highest cross-zone re-loop risk: a wrong write order in `director_loop` could drop CC writes from both Mode D and voice-tier simultaneously. Tests at the SHM-flag boundary would catch this; per `mode-d-voice-tier-mutex.md §2`, the SHM state is single source of truth.

### §4.4 Effort estimate per item (delta-owned)

| Item | Size | Notes |
|---|---|---|
| Audio-topology Phase 5 (pin-glitch watchdog) | S (~150 LOC + tests) | Self-contained; existing `pactl` / `pw-cli` deps |
| Demonet Phase 2 (catalog audit) | M (400-700 LOC, mostly annotations + governance doc) | One-pass survey; no logic |
| Demonet Phase 5 (opt-ins, non-stub) | S (150-250 LOC) | Programme primitive already exists |
| Demonet Phase 6 (egress audit JSONL) | M (300-450 LOC + tests + systemd timer) | Independent of Phase 3 |
| Demonet Phase 3 (Ring 2 classifier) | M-L (400-600 LOC) | TabbyAPI integration, 500-sample benchmark required |
| Demonet Phase 4 (fail-closed) | M (250-350 LOC) | After Phase 3 |
| Content-programme Phase 2 (PlanStore persistence) | M (200-350 LOC) | Per [`programme-layer-plan.md`](../superpowers/plans/2026-04-20-programme-layer-plan.md) Phase 2 |
| Voice-tier Phase 3b glue (delta-side) | S (50-100 LOC) | Impingement schema for `director_loop` |
| Mode D mutex Phase 3 glue (delta-side) | S (50-100 LOC) | SHM state read pattern + Prometheus counter |
| Evil Pet `.evl` Phase 1 (when unblocked) | M (200-300 LOC) | Pure parser |
| Dual-FX Phase 1 (S-4 USB sink descriptor) | S (50-100 LOC) | One conf file + one verify test |
| Audio-chain mixquality skeleton | M (250-400 LOC) | LUFS measurement + Prometheus emit |

---

## §5. Context-switching cost assessment

### §5.1 Today's switching pattern

Delta interleaved seven feature-families in 35 commits over ~6 hours. The interleave pattern (chronological):

```
HOMAGE-research → face-obscure-fix → v4l2sink-research+watchdog → audio-norm-research →
audio-chain-fix×4 → degraded-mode-fix → vinyl-research+audio-split → S-4-base-scene →
audio-livestream-revert → preset-recruitment-consumer → voice-tier-P1 → CBIP-border →
dead-bridge-audit → audio-fix×3 → director-watchdog → voice-tier-P2 → voice-tier-P3a →
voice-tier-P4 → Evil-Pet-mutex-P1 → audio-gain-fix → Evil-Pet-mutex-P2 →
director-watchdog-cold-start → Evil-Pet-base-scene-systemd → research-triage →
audio-topology-P1→P2→P3→P4→P6
```

Switches between families: ~22 (counting consecutive same-family as no switch). Run-length per family: median 1, max 5 (audio-topology streak at end of session).

### §5.2 Helping or hurting?

The pattern that emerged tonight (interleave-heavy early, run-streak late) is consistent with a **discovery-then-execution** rhythm: early in the session the operator surfaced new audio-chain problems → research-and-patch loops; mid-session voice-tier became the dominant ship surface; late session converged on audio-topology as a coherent CLI epic.

**The audio-topology streak (5 commits in ~10 minutes, 4:01Z back to ~3:51Z)** is the most efficient stretch in the whole session. Same file mental model, same Pydantic schema, same CLI surface. This argues that delta benefits most from sustained single-family streaks once the family's design is settled.

**The audio-chain interleave (8 commits scattered across 3 hours)** is the most expensive in context-switching cost. Each fix required re-reading the L6 routing topology and the Studio 24c retirement state. These commits were operator-driven and unavoidable in real-time, but if the operator were not actively patching, the optimal pattern is to batch them.

### §5.3 Re-sequencing recommendation

For the next 4 hours: **bias to streaks of 3+ commits per family**, with explicit "I'm done with X for now" relay updates between streaks. Specifically:

- Streak 1: close audio-topology (Phase 5 + Phase 6 CI gate) — 2 commits, ~30 min, single mental model.
- Streak 2: demonet Phase 2 (one big annotation pass) + Phase 5 (small Programme opt-in field) — 2 commits, ~90 min, governance mental model.
- Streak 3: cross-zone seam closure — voice-tier 3b glue + Mode D mutex Phase 3 glue together — 2 commits, ~45 min, director-loop mental model. Hand off to alpha at end with one relay drop.

That's 6 commits in 165 minutes, with three context switches (audio-topology → governance → director seam) instead of the random interleave.

---

## §6. Operator-gated items (pre-scope opportunities)

Five items wait on operator signal. For each, name what delta can pre-scope so delta hits "ready to ship" the moment the operator unblocks.

| Item | Operator action needed | Pre-scope work delta can do now (≤30 min each) |
|---|---|---|
| **Audio-chain L6 retargets** (5 configs) | Confirm AUX 1 routing path; receive Rode Wireless Pro on ch 1 | Write the 5 patches as a single PR draft on a branch; add `pw-dump` regression test for expected node graph. Land on operator confirm. |
| **Evil Pet `.evl` Phase 1** | Provide factory `.evl` file from SD card | Write `parse_evl()` + `serialize_evl()` against a stubbed binary spec; finalize against real bytes when received. |
| **De-monet Phase 8 music policy** | Answer §11 Q1 (mute+transcript vs ≤30s windower) | Write both Path A and Path B as branches; CI both; merge whichever operator picks. |
| **Dual-FX Phase 6 (S-4 firmware)** | Flash S-4 OS 2.1.4 | Phase 1–5 (config + routing-map + path-selection + switcher + voice-tier integration) ship without firmware; Phase 6 only enables Track-5 separation. |
| **Programme monetization_opt_ins authoring** | Operator authors first programme with non-empty opt-ins | Write the Pydantic model + validation rules now; expose via CLI; populate when operator decides which programmes need opt-ins. |

**Net opportunity**: all five operator-gated items have ≥80% of their work pre-scopable. None blocks delta's hands during the next 4 hours.

---

## §7. Alpha coordination gates (cross-zone items)

Three items cross the delta/alpha workstream split per [`coordination-protocol.md §2.2`](2026-04-19-delta-alpha-coordination-protocol.md). Each touches `agents/studio_compositor/` (alpha primary) from a delta-owned design surface.

### §7.1 Voice-tier Phase 3b — `director_loop` impingement

**Status:** Phase 3a `2385cf929` shipped delta-side (role/stance resolver + programme band override). Phase 3b ports the resolver's outputs into `director_loop.py` so the director can emit voice-tier transitions as impingements. Per [`research-triage §1 #2`](../superpowers/research-to-plan-triage-2026-04-20.md), this is "pending alpha zone."

**Recommendation**: delta ships a one-PR shared-side glue:
- Add `VoiceTierImpingement(BaseModel)` to `shared/impingements.py` (5 fields: tier, programme_band, voice_path, monetization_risk, since)
- Add `vocal_chain.emit_voice_tier_impingement()` returning the typed impingement
- Add a regression test asserting the impingement schema

This delivers alpha a one-line consumer task: read the impingement, dispatch to the loop. Branch: `delta/voice-tier-3b-glue`. Hand off via [`relay`](file:///home/hapax/.cache/hapax/relay/) with the alpha PR slug and acceptance criteria.

### §7.2 Mode D × voice-tier mutex Phase 3 — `acquire_engine` in `director_loop`

**Status:** Phases 1 (`b27758c79`) and 2 (`e1da54fae`) shipped delta-side (single-owner arbitration + engine-gated activation wrappers). Phase 3 wires `acquire_engine()` calls into `director_loop` so the director can request the granular engine before issuing CCs. Per [`mode-d-voice-tier-mutex.md §2`](2026-04-20-mode-d-voice-tier-mutex.md), the SHM state is single source of truth; the director needs to read-then-write through that.

**Recommendation**: same pattern as §7.1. Delta ships a one-PR shared-side glue:
- Add `EnginePool.acquire_engine(consumer)` and `release_engine(consumer)` context manager (probably already in shared from Phase 2 — verify)
- Add Prometheus counters `hapax_evil_pet_engine_acquires_total{consumer}` and `hapax_evil_pet_engine_contention_total`
- Add a regression test asserting two simultaneous acquires raise EngineContention

Hand off to alpha with a `director_loop` task description, named branch, expected counters.

### §7.3 Dead-bridge `mental_state_redaction.py` wiring

**Status:** Per [`dead-bridge-modules-audit.md`](2026-04-20-dead-bridge-modules-audit.md) (commit `3d70dddba`), `shared/governance/mental_state_redaction.py` has zero production callers. Module exists; nothing touches it. Either wire it or delete it.

**Recommendation:** Defer this until after the demonet Phase 2 catalog audit; that audit will reveal which capabilities should be calling the redaction module. Coupling the wiring to the catalog pass keeps both decisions grounded in the same governance review.

### §7.4 Hot-file overlap risk

**`agents/studio_compositor/director_loop.py`** is the highest-risk file: both voice-tier 3b and Mode D mutex Phase 3 want to land changes there. If alpha opens both PRs in parallel they will conflict. Sequencing: ship voice-tier 3b first (smaller, lower-risk); rebase Mode D mutex Phase 3 on top.

**`shared/impingements.py`** is also touched by both delta cross-zone PRs. Mitigate by bundling both new impingement classes into a single delta-side PR (one PR, two new types) rather than two PRs each adding one type.

---

## §8. Ship-rhythm patterns

### §8.1 Tonight's cadence

- **First hour (00:11Z–01:11Z):** 6 commits, ~7,800 LOC, mostly research drops + audio-chain hotfixes. High file-touch, low single-feature focus.
- **Second hour (01:11Z–02:11Z):** 5 commits, ~3,800 LOC, audio-fix continuation + S-4 base-scene + audio-split bundle.
- **Third hour (02:11Z–03:11Z):** 7 commits, ~2,000 LOC, voice-tier P1 + dead-bridge audit + audio fixes + degraded-mode bridge + preset-recruitment consumer.
- **Fourth hour (03:11Z–04:11Z):** 17 commits, ~7,900 LOC, voice-tier P2-P4 + Evil Pet mutex P1-P2 + audio-topology P1-P4-P6 + triage + systemd unit. **Acceleration phase — half the session's commits.**

### §8.2 Where to break

The session pattern shows accelerating throughput as the night progresses, which suggests delta does not need a "consolidate" break in the next hour. The natural break point is one of:

1. **End of audio-topology family** (after Phase 5 watchdog + CI gate). Clean cap.
2. **End of demonet Phase 2** (catalog audit ships, capability surface is annotated). Major governance milestone.
3. **End of Mode D × voice-tier mutex Phase 3 cross-zone glue** (delta has done its half; ball is in alpha's court).

Recommend break point #3 — it converts a coordination gate into a clean handoff and ends the cross-zone work for the day.

### §8.3 Pending CI failures on recent commits

`gh pr list` shows no open PRs from delta — all 35 commits today were direct-to-branch via the trio-delivery direct-push pattern documented in [`coordination-protocol §4`](2026-04-19-delta-alpha-coordination-protocol.md). CI runs on push but does not gate at PR-open. Per [`alpha-to-delta-queue-ack-20260420.yaml`](file:///home/hapax/.cache/hapax/relay/alpha-to-delta-queue-ack-20260420.yaml), PR #1109 (the audit-closeout that delta's flush was waiting on) merged at ~04:05Z, so the rebase friction window is closed.

Recommend running `gh run list --limit 5` once before each new commit cluster to spot any silent CI red.

---

## §9. Proposed re-ordered queue (priority-sequenced)

Sequencing rules applied in order: (a) close cross-zone seams first (alpha unblocks); (b) close started families before opening new ones; (c) operator-unblock items get pre-scoped now; (d) bundle by feature-family to reduce context switching; (e) defer research-only work until the next cold period.

### Tier 1 — ship in the next 4 hours

| # | Item | Size | Why now | Dependencies |
|---|---|---|---|---|
| 1 | **Mode D × voice-tier mutex Phase 3 delta-side glue** | S (~150 LOC) | Closes the highest-risk cross-zone seam; converts coordination wait into alpha unblock | None |
| 2 | **Voice-tier Phase 3b delta-side glue (impingement schema)** | S (~100 LOC) | Same seam family; cheap to bundle with #1 in same `shared/impingements.py` PR | None |
| 3 | **De-monetization Phase 2 (capability catalog audit + risk classification)** | M (400–700 LOC) | Go-live Gate 1 support; CI-blocking; pure annotations | Phase 1 shipped |
| 4 | **Audio-topology Phase 5 (Ryzen-codec pin-glitch watchdog)** | S (~150 LOC) | Closes audio-topology family; converts recurring operator annoyance to deterministic auto-fix | Phases 1–4 shipped |
| 5 | **De-monetization Phase 5 (Programme opt-ins, non-stub)** | S (150–250 LOC) | Programme primitive shipped (`f6cc0b42b`); plan said "stub until shipped" — now non-stub possible | Phases 1, 2; programme P1 |

### Tier 2 — ship in the following 4 hours (or earlier if Tier 1 finishes fast)

| # | Item | Size | Why this slot |
|---|---|---|---|
| 6 | **De-monetization Phase 6 (egress audit JSONL writer + rotation)** | M (300–450 LOC + systemd timer) | Parallel-safe with Phase 3; higher operator visibility than Phase 3 |
| 7 | **De-monetization Phase 3 (Ring 2 pre-render classifier)** | M-L (400–600 LOC) | Critical-path heavy lift; better with rested context |
| 8 | **Content-programme Phase 2 (ProgrammePlanStore persistence)** | M (200–350 LOC) | Unblocks Phase 11 quiet-frame; flagged in delta.yaml `delta_next` |
| 9 | **De-monetization Phase 4 (classifier-degraded fail-closed)** | M (250–350 LOC) | Strict serial-after Phase 3 |
| 10 | **Audio-chain mixquality skeleton → concrete impl** | M (250–400 LOC) | Reference: [`mixquality-skeleton-design.md`](2026-04-20-mixquality-skeleton-design.md); flagged in [`pr1109-merged-queue-20260420.md`](file:///home/hapax/.cache/hapax/relay/delta-to-alpha-pr1109-merged-queue-20260420.md) §P3 |

### Tier 3 — operator-gated (pre-scope, ship on signal)

| # | Item | Size | Operator gate |
|---|---|---|---|
| 11 | Audio-chain L6 multitrack retargets (5 configs) | M | AUX 1 routing confirm + Rode Wireless Pro |
| 12 | Evil Pet `.evl` preset pack Phase 1 (parser) | M | Factory `.evl` file delivered |
| 13 | De-monet Phase 8 music policy (Path A or B) | S-M | §11 Q1 answer |
| 14 | Dual-FX routing Phase 1–5 | M (split across phases) | None for Phases 1–5; Phase 6 needs S-4 firmware |
| 15 | De-monet Phase 11 quiet-frame programme | M | Phase 3 shipped + content-programme Phase 1 (already shipped) |

### Tier 4 — defer to the next cold period (research / low-leverage)

| # | Item | Why defer |
|---|---|---|
| 16 | Vinyl-broadcast signal-chain software wiring (research #36) | Operator-owned signal chain dominant; software side is ~1 conf file |
| 17 | Dead-bridge `mental_state_redaction.py` wiring | Couple to Phase 2 catalog audit; not standalone |
| 18 | Audio-normalization LADSPA syntax research (triage §1 #8) | Blocked on LADSPA reference docs; not on critical path |
| 19 | Audio-topology cross-device extension (Wear OS ↔ phone ↔ council) | Deferred per plan §Deferred |

---

## §10. Specific flow recommendations

### §10.1 Pre-load for the next block

- **`agents/studio_compositor/director_loop.py`** — read top-to-bottom once before starting Tier 1 items #1 and #2. The cross-zone glue lands cleanest if delta knows alpha's existing impingement-consumption pattern.
- **`shared/compositional_affordances.py`** — read the entire capability list once before Tier 1 item #3 (catalog audit). The annotation pass is faster with a single read of the file.
- **`pw-dump | jq`** snapshot of current PipeWire graph — capture once for Tier 1 item #4 (pin-glitch watchdog regression test). Saves ~10 minutes of repeated `pw-dump` invocations during test authoring.

### §10.2 Defer to alpha with clean handoff

Per [`coordination-protocol §3`](2026-04-19-delta-alpha-coordination-protocol.md), every cross-zone deferral writes a relay drop. The two cross-zone glues (Tier 1 #1, #2) ship as one delta-side PR + one relay drop naming alpha's pickup task. Format:

```yaml
from: delta
to: alpha
subject: "Cross-zone glue ready: voice-tier 3b + Mode D mutex Phase 3"
ready_for_alpha:
  voice_tier_3b:
    branch_landed: <SHA>
    consumer_task: "wire VoiceTierImpingement consumer into director_loop main tick"
    expected_loc: ~30 LOC
    test: tests/studio_compositor/test_voice_tier_consumer.py
  mode_d_mutex_p3:
    branch_landed: <SHA>
    consumer_task: "wire EnginePool.acquire_engine() guard into director's CC emit path"
    expected_loc: ~40 LOC
    counters: hapax_evil_pet_engine_acquires_total, hapax_evil_pet_engine_contention_total
```

### §10.3 What to stop doing

- **Stop dispatching new research drops** until the existing 46-doc pile is reduced. Per [`research-triage §1`](../superpowers/research-to-plan-triage-2026-04-20.md), 4 delta-zone docs are still unqueued or partially queued. Triage shipped 3 stub plans; the remaining unqueued items (`audio-normalization-ducking-strategy`, parts of vinyl-broadcast topology) need attention more than new research does. **Bias 100% to ship-from-existing for the next 4 hours.**
- **Stop bundling research with code commits** like `0f7106ac2` (3,376 LOC, mixed). The bundle obscures the actual code change and makes revert harder. Separate commits per concern.
- **Stop interleaving audio-chain hotfixes with feature work** unless operator is actively patching. Today's audio-chain interleave was driven by real-time operator hardware moves; in the next 4 hours, the audio-chain is stable (Mode D capability live, voice-tier P1-4 live), so the interleave should drop to zero.

---

## §11. A concrete 4-hour block shape

### Hour 1 (T+0 → T+60 min): Cross-zone seam closure

**Goal**: ship one PR closing both voice-tier 3b and Mode D mutex Phase 3 delta-side glue. Hand off to alpha.

- T+00 to T+10: read `agents/studio_compositor/director_loop.py` end-to-end; read `shared/impingements.py` for current schema patterns
- T+10 to T+25: write `VoiceTierImpingement` + `EngineAcquireImpingement` (or whatever the natural shape is) + tests
- T+25 to T+40: wire `vocal_chain.emit_voice_tier_impingement()` and `EnginePool.acquire_engine()` context manager + Prometheus counters
- T+40 to T+50: regression test asserting two simultaneous acquires raise contention
- T+50 to T+60: commit, push, write relay drop to alpha with consumer-task description

**Acceptance**: one commit landed; relay drop in `~/.cache/hapax/relay/delta-to-alpha-cross-zone-handoff-20260420.md`.

### Hour 2 (T+60 → T+120 min): De-monetization Phase 2 (catalog audit)

**Goal**: every `CapabilityRecord` in `shared/compositional_affordances.py` and every JSON under `affordances/` carries explicit `monetization_risk` + `risk_reason`. Plus the governance doc.

- T+60 to T+75: read `shared/compositional_affordances.py` end-to-end; enumerate capabilities
- T+75 to T+105: annotate each capability with risk classification per the demonet plan §1.1 rubric (most are `none` or `low`; identify the `medium` and `high` cases)
- T+105 to T+115: write `docs/governance/monetization-risk-classification.md` with rubric + per-capability rationale
- T+115 to T+120: add CI-blocking `test_capability_catalog_complete`; commit; push

**Acceptance**: one commit landed; CI-blocking test green; governance doc cross-linked from `docs/governance/README.md`.

### Hour 3 (T+120 → T+180 min): Audio-topology Phase 5 (pin-glitch watchdog)

**Goal**: `hapax-audio-topology verify` detects Ryzen-codec pin-glitch state and `auto-fix` re-cycles the card profile. Closes the audio-topology family.

- T+120 to T+135: read `shared/audio_topology/` end-to-end; understand the Phase 4 `pw_dump_to_descriptor` parser
- T+135 to T+155: write failing test asserting `verify` returns `PIN_GLITCH` diagnostic on the simulated stuck-monitor-port state
- T+155 to T+170: implement detection (monitor port RMS via `pactl`); implement `auto-fix` subcommand running the documented `pactl set-card-profile` cycle
- T+170 to T+180: commit; verify against live workstation if possible; push

**Acceptance**: one commit landed; audio-topology family closed at Phase 5+6 (Phase 6 already shipped); `hapax-audio-topology verify` exits 0 against current live graph.

### Hour 4 (T+180 → T+240 min): Elective

Three elective options based on what surfaced in hours 1–3:

- **Option A — De-monet Phase 5 (Programme opt-ins, non-stub).** Ship if the catalog audit (hour 2) revealed `medium`-risk capabilities that need programme opt-in. ~150 LOC, 30 min.
- **Option B — Audio-chain mixquality skeleton → concrete impl.** Ship if operator confirms AUX 1 routing during the block (unblocks the multitrack source matrix). ~300 LOC, 60 min.
- **Option C — Content-programme Phase 2 (ProgrammePlanStore persistence).** Ship if Tier 1 items came in fast and there's appetite for opening a new family. ~250 LOC, 45 min.

Default if no signal: Option A (lowest risk, stays in the demonet family for context coherence with hour 2).

### Sanity break at T+240

Write a relay update to `delta.yaml` reflecting:
- 4 commits landed
- Cross-zone seam closed
- Catalog audit shipped (Gate 1 advanced)
- Audio-topology family complete
- One of Options A/B/C shipped or noted as queued

If energy remains, continue with Tier 2 items #6 (egress audit) or #7 (Ring 2 classifier). Otherwise hand off to next session via [`docs/superpowers/handoff/2026-04-20-delta-handoff.md`](../superpowers/handoff/) with the Tier 1 queue advanced.

---

## §12. Sources

1. [`/home/hapax/.cache/hapax/relay/delta.yaml`](file:///home/hapax/.cache/hapax/relay/delta.yaml) — delta's own state, refreshed 2026-04-20T04:10:00Z
2. [`/home/hapax/.cache/hapax/relay/delta-to-alpha-pr1109-merged-queue-20260420.md`](file:///home/hapax/.cache/hapax/relay/delta-to-alpha-pr1109-merged-queue-20260420.md) — go-live gates locked, alpha queue
3. [`/home/hapax/.cache/hapax/relay/delta-to-alpha-research-triage-20260420.md`](file:///home/hapax/.cache/hapax/relay/delta-to-alpha-research-triage-20260420.md) — alpha-zone gap flag
4. [`/home/hapax/.cache/hapax/relay/alpha-to-delta-queue-ack-20260420.yaml`](file:///home/hapax/.cache/hapax/relay/alpha-to-delta-queue-ack-20260420.yaml) — workstream split ack
5. [`docs/superpowers/research-to-plan-triage-2026-04-20.md`](../superpowers/research-to-plan-triage-2026-04-20.md) — delta's 46-doc triage (commit `7b57af434`)
6. [`docs/research/2026-04-19-delta-alpha-coordination-protocol.md`](2026-04-19-delta-alpha-coordination-protocol.md) — workstream-family ownership table §2.2
7. [`docs/superpowers/plans/2026-04-20-unified-audio-architecture-plan.md`](../superpowers/plans/2026-04-20-unified-audio-architecture-plan.md) — audio-topology phases 1–6
8. [`docs/superpowers/plans/2026-04-20-evil-pet-preset-pack-plan.md`](../superpowers/plans/2026-04-20-evil-pet-preset-pack-plan.md) — `.evl` preset pack phases
9. [`docs/superpowers/plans/2026-04-20-dual-fx-routing-plan.md`](../superpowers/plans/2026-04-20-dual-fx-routing-plan.md) — S-4 USB-direct routing phases
10. [`docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md`](../superpowers/plans/2026-04-20-demonetization-safety-plan.md) — 11-phase demonet plan, DAG §3.1
11. [`docs/superpowers/plans/2026-04-20-programme-layer-plan.md`](../superpowers/plans/2026-04-20-programme-layer-plan.md) — content-programme 12-phase plan
12. [`docs/research/2026-04-20-voice-transformation-tier-spectrum.md`](2026-04-20-voice-transformation-tier-spectrum.md) — 7-tier voice spectrum spec
13. [`docs/research/2026-04-20-mode-d-voice-tier-mutex.md`](2026-04-20-mode-d-voice-tier-mutex.md) — mutex correctness invariant
14. [`docs/research/2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md`](2026-04-20-vinyl-broadcast-mode-d-granular-instrument.md) — Mode D scene definition
15. [`docs/research/2026-04-20-unified-audio-architecture-design.md`](2026-04-20-unified-audio-architecture-design.md) — unified audio research drop
16. [`docs/research/2026-04-20-dual-fx-routing-design.md`](2026-04-20-dual-fx-routing-design.md) — dual-FX research drop
17. [`docs/research/2026-04-20-evil-pet-factory-presets-midi.md`](2026-04-20-evil-pet-factory-presets-midi.md) — `.evl` factory-preset trap
18. [`docs/research/2026-04-20-dead-bridge-modules-audit.md`](2026-04-20-dead-bridge-modules-audit.md) — 11 confirmed + 6 suspected dead bridges (commit `3d70dddba`)
19. [`docs/research/2026-04-20-audio-normalization-ducking-strategy.md`](2026-04-20-audio-normalization-ducking-strategy.md) — full source matrix (commit `df6629f43`)
20. [`docs/research/2026-04-20-mixquality-skeleton-design.md`](2026-04-20-mixquality-skeleton-design.md) — LUFS measurement skeleton
21. [`docs/research/2026-04-20-livestream-halt-investigation.md`](2026-04-20-livestream-halt-investigation.md) — director cold-start root cause
22. [`docs/research/2026-04-20-v4l2sink-stall-prevention.md`](2026-04-20-v4l2sink-stall-prevention.md) — Phase 1 watchdog (commit `df6629f43` adjacent)
23. Git commit `7b57af434` — `docs: research-to-plan triage + 3 delta stub plans` (416 LOC)
24. Git commit `071e960ca` — `feat(voice-tier): 7-tier transformation spectrum + operator CLI (Phase 1)` (666 LOC)
25. Git commit `c7eeb17be` — `feat(voice-tier): VocalChainCapability.apply_tier() — Phase 2` (877 LOC)
26. Git commit `2385cf929` — `feat(voice-tier): role/stance resolver + programme band override (Phase 3a)` (412 LOC)
27. Git commit `99f851cfb` — `feat(voice-tier): monetization + capability registration + intelligibility budget (Phase 4)` (334 LOC)
28. Git commit `b27758c79` — `feat(evil-pet): single-owner arbitration + SHM state (mutex Phase 1)` (707 LOC)
29. Git commit `e1da54fae` — `feat(evil-pet): engine-gated activation wrappers (mutex Phase 2)` (454 LOC)
30. Git commit `c8475becf` — `feat(systemd): Evil Pet base-scene auto-boot as oneshot before daimonion` (45 LOC)
31. Git commit `bb04ac104` → `5760634af` → `3a7ec2670` → `55491704a` → `71ac1accf` — audio-topology Phases 1, 2, 3, 4, 6 (2,177 LOC total)
32. Git commit `f6cc0b42b` — `feat: Programme primitive (task #164 Phase 1)` — pre-tonight, referenced as enabler for demonet Phase 5
33. Git commit `0886d37ab` — `feat: MonetizationRiskGate primitive (task #165 Phase 1)` — pre-tonight, demonet Phase 1
34. Git commit `22dcfc695` — `feat(daimonion): Vinyl Mode D granular-wash capability (go-live gate 2)` — pre-tonight
35. Git commit `26cfc6387` — `feat(daimonion): Vinyl Mode D invocation — daimonion wiring + operator CLI` — pre-tonight, gate 2 satisfied
36. Git commit `89ac17193` — `fix(director-watchdog): seed _last_real_intent_monotonic at import to prevent cold-start crash loop` — director-watchdog hardening
37. Git commit `9b85da3e6` — `feat(compositor): director liveness watchdog Phase 1` — director-watchdog initial
38. `git log --since '2026-04-20 00:00:00' --numstat` (full file-touch + LOC accounting for §2 trajectory)
39. `gh pr list --state open --author '@me'` — confirms zero open delta PRs at audit time (direct-push pattern)
40. CLAUDE.md (`/home/hapax/projects/hapax-council/CLAUDE.md`) — workstream split context for `agents/hapax_daimonion/`, `shared/`, `agents/studio_compositor/director_loop.py`, `shared/impingement_consumer.py`

---

*End of organizational planning pass.*
