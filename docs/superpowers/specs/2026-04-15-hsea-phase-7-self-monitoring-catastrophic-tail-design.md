# HSEA Phase 7 — Self-Monitoring + Catastrophic Tail (Cluster D) — Design Spec

**Date:** 2026-04-15
**Author:** beta (pre-staging extraction per delta's nightly queue Item #16 / #47; matches delta's HSEA Phase 0/1/2/3/4/5/6/8/9/10/11/12 extraction pattern)
**Status:** DRAFT pre-staging — awaiting operator sign-off + HSEA UP-10 (Phase 2) + HSEA UP-2 (Phase 0) close before Phase 7 open
**Epic reference:** `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` §5 Phase 7 (lines 515–529)
**Thesis reference:** drop #58 §3 Cluster D (self-monitoring + catastrophic tail mitigation)
**Plan reference:** `docs/superpowers/plans/2026-04-15-hsea-phase-7-self-monitoring-catastrophic-tail-plan.md`
**Branch target:** `feat/hsea-phase-7-self-monitoring-catastrophic-tail`
**Cross-epic authority:** drop #62 §5 UP-12 cluster basket (Phase 7 is one of the parallel UP-12 phases)

---

## 1. Phase goal

Ship the **anomaly narration + self-healing + catastrophic tail mitigation** layer. When something is going wrong on the stream — stimmung anomaly, FSM stuck state, recurring bug pattern, alert storm, watchdog trip, DMCA risk, consent face redaction pending, hardware event — hapax narrates it on-stream or operator-privately, proposes fixes via the governance queue, and documents the incident post-hoc.

**What this phase is:** 10 Cluster D deliverables (D2–D13, with gaps at D1/D5/D7 per drop #58 numbering) that turn anomalies + tail events into observable signals + operator-facing fixes + post-hoc documentation.

**What this phase is NOT:** does not ship the watchdog infrastructure (already exists at the systemd + Prometheus layer), does not ship the FSM itself (already exists in the compositor 24/7 resilience epic + daimonion CPAL), does not auto-heal without operator approval for code changes. Phase 7 is the **narration + proposal + documentation** layer on top of existing monitoring primitives.

---

## 2. Dependencies + preconditions

**Cross-epic (from drop #62):**

1. **HSEA UP-2 (Phase 0 foundation primitives) closed.** D4 recurring-pattern fix proposals consume the governance queue + spawn budget + `promote-patch.sh`. D8 postmortem auto-drafting uses `ComposeDropActivity`.
2. **HSEA UP-10 (Phase 2 core director activities) closed.** D2 + D3 + D6 + D9 narration paths all extend Phase 2 activities.
3. **LRR UP-1 (Phase 1 research registry) closed.** D8 postmortems reference `condition_id` for per-condition incident filtering.
4. **LRR UP-13 observability partially present** — Phase 7 relies on Prometheus alerts, systemd timer state, watchdog metrics. LRR Phase 10's 18-item stability matrix is the ideal partner but not strictly required; Phase 7 can consume whatever observability is live.
5. **HSEA Phase 4 Cluster I (rescoped) partial** — D4 recurring-pattern fix proposals compose the `promote-patch.sh` pipeline shipped in Phase 4. If Phase 4 has not opened, D4 ships with a stubbed patch path that writes to governance queue only (no actual git apply).
6. **Substrate-agnostic** — no §14 reframing required.

**Infrastructure:**

1. Prometheus alert state via `shared/prom_query.py` (HSEA Phase 0 0.1)
2. Systemd user unit state (already queryable via `systemctl --user show`)
3. Compositor FSM state (already published to `/dev/shm/hapax-compositor/fsm-state.json` per camera 24/7 resilience epic)
4. Daimonion CPAL state (already published to `/dev/shm/hapax-dmn/cpal-state.json`)
5. `agents/hapax_daimonion/activities/compose_drop.py::ComposeDropActivity` (HSEA Phase 2 3.6)
6. IR perception stream for D12 face redaction trigger (contact mic + Pi NoIR)
7. Consent contract registry (`axioms/contracts/`) for D12 consent check

---

## 3. Deliverables (10 Cluster D items)

### 3.1 D2 — Threshold-crossed anomaly narration

- When any Prometheus metric crosses a pre-defined anomaly threshold (separate from the LRR Phase 10 18-item matrix — these are subtler anomalies like "stimmung tension increased 40% in 10 min"), daimonion narrates the anomaly on-stream at salience 0.55
- Narration includes: which metric, what the threshold was, current value, why it matters
- **Target files:** `agents/hapax_daimonion/d_cluster/d2_anomaly_narrator.py` (~250 LOC), anomaly threshold config at `config/d-cluster-anomaly-thresholds.yaml` (~40 lines), tests (~120 LOC)
- **Size:** ~410 LOC

### 3.2 D3 — FSM step-by-step recovery narration

- The camera 24/7 resilience FSM has 5 states: HEALTHY → DEGRADED → RECOVERING → FAILED → DISABLED. D3 narrates each state transition on-stream with context ("cam-desk entered RECOVERING because USB altsetting failed; waiting for kernel re-enumerate")
- Similar narration for daimonion CPAL FSM states
- Consumes `/dev/shm/hapax-compositor/fsm-state.json` + `/dev/shm/hapax-dmn/cpal-state.json`; watches for mtime changes
- **Target files:** `agents/hapax_daimonion/d_cluster/d3_fsm_recovery_narrator.py` (~280 LOC), tests (~130 LOC)
- **Size:** ~410 LOC

### 3.3 D4 — Recurring-pattern detection → fix proposal

- Monitors `~/hapax-state/alerts.jsonl` + `~/hapax-state/anomalies.jsonl` for recurring patterns (e.g., "cam-operator failed 3 times in 24h", "tabbyapi OOM occurred twice this week")
- On detection, composes a fix proposal as a `promote-patch.sh`-gated draft in the governance queue with: pattern description, root cause hypothesis, proposed code change, test plan, rollback plan
- **Extends HSEA Phase 4 `code_drafter` infrastructure** per drop #62 §10 Q3 ratification — D4 uses the same `promote-patch.sh` pipeline Phase 4 I6/I7 use
- **Safety:** drafter NEVER auto-applies; operator approval via inbox frontmatter flip always required
- **Target files:** `agents/hapax_daimonion/d_cluster/d4_pattern_fix_proposer.py` (~300 LOC), tests (~150 LOC)
- **Size:** ~450 LOC

### 3.4 D6 — Alert triage on stream

- When multiple Prometheus alerts fire in a burst window (e.g., >3 alerts in 60 sec), daimonion narrates a triage summary: "three alerts are firing — compositor frame drops + mixer_master disconnect + HLS archive dormant — investigating compositor first because frame drops is upstream"
- Uses ordered heuristic: compositor > audio > chat > archival > cosmetic
- **Target files:** `agents/hapax_daimonion/d_cluster/d6_alert_triage.py` (~220 LOC), triage heuristic config, tests (~100 LOC)
- **Size:** ~340 LOC

### 3.5 D8 — Postmortem auto-drafting

- Triggered at incident close (FSM returned to HEALTHY OR alert cleared OR operator declared "resolved"): composes a postmortem drop covering: timeline, root cause hypothesis, fix applied (or workaround), prevention proposal
- Uses HSEA Phase 2 `ComposeDropActivity` with findings_reader wrapped around `~/hapax-state/incidents/<id>/`
- Draft goes through governance queue + operator review per standard promote-drop flow
- **Target files:** `agents/hapax_daimonion/d_cluster/d8_postmortem_drafter.py` (~280 LOC), tests (~140 LOC)
- **Size:** ~420 LOC

### 3.6 D9 — Pre-flight checklist narration

- Before each research-mode session start (stream-mode transition `off → public_research`), daimonion narrates a 30-second pre-flight checklist: compositor healthy, tabbyapi serving, Qdrant reachable, frozen-files unchanged, current condition_id, last session's notes
- Blocks stream start if any critical check fails (operator override via stream deck button)
- **Target files:** `agents/hapax_daimonion/d_cluster/d9_preflight_checklist.py` (~250 LOC), tests (~120 LOC)
- **Size:** ~370 LOC

### 3.7 D10 — Watchdog self-expansion proposal

- Detects when a service fails in a pattern that the current watchdog doesn't cover (e.g., a new failure mode of tabbyapi that existing restart-on-failure doesn't handle); composes a governance queue proposal for expanding the watchdog
- Conservative: only proposes, never auto-modifies systemd units; operator approval via `promote-patch.sh` pipeline
- **Target files:** `agents/hapax_daimonion/d_cluster/d10_watchdog_expander.py` (~220 LOC), tests (~100 LOC)
- **Size:** ~320 LOC

### 3.8 D11 — DMCA/Content ID pre-check

- Before music starts playing (contact mic BPM transition idle→active + album-identifier hit), check the album metadata against a pre-seeded DMCA risk list (`config/dmca-risk-list.yaml`, operator-maintained); if risk is high, daimonion narrates operator-privately ("this album has DMCA history — consider skipping or cutting audio")
- On DMCA-high: optionally emit a compositor-level audio duck signal
- **Target files:** `agents/hapax_daimonion/d_cluster/d11_dmca_precheck.py` (~200 LOC), risk list config (operator-seeded), tests (~100 LOC)
- **Size:** ~300 LOC

### 3.9 D12 — Consent face redaction narration

- IR perception fleet detects face in frame (not operator's face per operator_face signal); D12 checks consent contract registry for that location/context; if no active consent, daimonion narrates operator-privately ("someone's face is visible and no consent contract exists for this location — enabling redaction")
- Triggers compositor-level face blur via existing face-detection + blur path (if that exists; if not, D12 proposes shipping it as part of this deliverable)
- **Target files:** `agents/hapax_daimonion/d_cluster/d12_consent_redaction_narrator.py` (~250 LOC), tests (~140 LOC)
- **Size:** ~390 LOC

### 3.10 D13 — Mobo swap scheduled event

- Operator-scheduled hardware events (mobo swap, PSU replacement, drive swap) are first-class citizens: operator writes an event to `config/scheduled-hardware-events.yaml` with `date + type + expected_duration + impact`; D13 narrates the event on-stream in advance + coordinates the shutdown sequence (compositor stop, service drain, etc.) + narrates return-to-service after the event
- **Target files:** `agents/hapax_daimonion/d_cluster/d13_hardware_event_narrator.py` (~280 LOC), event schema config, tests (~130 LOC)
- **Size:** ~430 LOC

---

## 4. Phase-specific decisions since epic authored

1. **D4 extends HSEA Phase 4 Cluster I via `promote-patch.sh`** — per drop #62 §10 Q3, D4 is NOT a new code-drafter; it composes the Phase 4 infrastructure that ships with I6 + I7 as the two code-drafting paths. If Phase 4 hasn't opened, D4 ships with a stub that writes to governance queue only.
2. **D10 watchdog self-expansion is proposal-only** — drafter NEVER modifies systemd units directly. Same pattern as D4: governance queue + operator approval + `promote-patch.sh` pipeline. This is constitutionally load-bearing because systemd unit changes are operator-authority territory.
3. **D9 pre-flight checklist has a critical-fail gate** — blocks research-mode stream start if any critical check fails, unless operator overrides via stream deck button. This is a research integrity safety.
4. **D11 DMCA pre-check uses operator-maintained risk list** — not an LLM judgment; hapax defers to operator-curated data for a domain (music DMCA) where operator expertise vastly exceeds hapax's.
5. **D12 consent face redaction is interpersonal_transparency axiom enforcement at the compositor layer** — narration is operator-private; blur is compositor-level. Narration + blur together compose the full consent response.
6. **Substrate-agnostic** — no §14 reframing required.

---

## 5. Exit criteria

Phase 7 closes when ALL of the following are verified:

1. D2 fires on at least one threshold crossing + narration renders on stream
2. D3 fires on at least one FSM transition + narration captures context
3. D4 detects at least one recurring pattern + proposes a fix that reaches operator inbox
4. D6 triages at least one alert burst + triage narration renders
5. D8 drafts at least one postmortem + drop ships through governance queue
6. D9 pre-flight checklist runs on at least one stream start + blocks or passes correctly
7. D10 proposes at least one watchdog expansion + operator reviews
8. D11 DMCA pre-check runs on at least one album change + narration delivered operator-privately
9. D12 face redaction narration fires on at least one non-operator face detection + blur activates
10. D13 scheduled hardware event narrated at least once (e.g., the pending mobo swap 2026-04-16 is a natural test)
11. Phase 7 handoff doc written

---

## 6. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| D2 anomaly narration is noisy; operator ignores narrations | MEDIUM | Anomaly loop never closes | Thresholds operator-tunable; frequency cap (max 1 narration per metric per 5 min) |
| D4 recurring-pattern detection false-positives; bad fix proposals | MEDIUM | Operator review fatigue | Pattern must recur 3+ times before proposal; operator can blacklist patterns |
| D9 critical-fail gate blocks stream start incorrectly | LOW | Lost streaming time | Operator override via stream deck; checklist thresholds tunable |
| D10 watchdog expansion proposes dangerous systemd changes | LOW | Service breakage on approval | Proposal-only; operator reviews the unit diff before approving; test in dry-run first |
| D11 DMCA risk list is incomplete; music plays without warning | HIGH | Stream strike risk | Operator-maintained list with explicit "unverified" default; fallback to human judgment |
| D12 consent face redaction fires on operator's own face due to IR misclassification | MEDIUM | Operator annoyance | Operator_face signal from IR fleet distinguishes operator from others; fallback to manual override |

---

## 7. Open questions

1. D2 anomaly thresholds — what's the initial seed set? Operator-defined, or learned from historical data?
2. D4 recurrence threshold — 3 times in what window? 24 h? 7 days?
3. D9 critical-fail checklist — which checks are critical vs warning?
4. D11 DMCA risk list — operator authors initial list, or seeded from known risky artists?
5. D12 face redaction — does compositor-level face blur already exist, or does D12 ship the blur path? (Needs verification at phase open time.)
6. D13 scheduled event coordination — how does operator write the schedule file? Stream Deck? CLI? Calendar integration?

---

## 8. Companion plan doc

TDD checkbox task breakdown at `docs/superpowers/plans/2026-04-15-hsea-phase-7-self-monitoring-catastrophic-tail-plan.md`.

**Execution order inside Phase 7:**

1. **D2 anomaly narration** — foundational; other D items consume the narration pattern
2. **D3 FSM recovery narration** — independent; ships in parallel with D2
3. **D9 pre-flight checklist** — independent; ships early
4. **D6 alert triage** — consumes D2 pattern; ships after D2
5. **D8 postmortem auto-drafting** — depends on D2 + D3 incident records; ships mid-phase
6. **D11 DMCA pre-check** — independent; ships anytime
7. **D12 consent face redaction** — independent; ships anytime
8. **D13 hardware event narration** — independent; ships anytime
9. **D4 recurring-pattern fix proposal** — depends on D2 + D8; ships late
10. **D10 watchdog self-expansion** — depends on D4 infrastructure; ships last

---

## 9. End

Standalone per-phase design spec for HSEA Phase 7 Self-Monitoring + Catastrophic Tail. Extracts drop #58 §3 Cluster D content + HSEA epic §5 Phase 7 into the delta 9-section pattern. Pre-staging only; does not open Phase 7.

— beta (PR #819 author) per delta's nightly queue Item #16 / #47, 2026-04-15
