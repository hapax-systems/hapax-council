# Bayesian Validation R&D Schedule

**Created:** 2026-03-29
**Authority:** Bayesian Validity Analysis of Hapax Research Tent-Pole Models (session 2026-03-29)
**Working mode:** R&D (switch to RESEARCH only for voice data collection sessions)
**Cadence:** 12 hr/day, 7 days/week
**Start:** 2026-03-30 (Day 1)

## Constraints

### Experiment Freeze (Active)

Cycle 2 Phase A baseline collection active since 2026-03-21. These paths are FROZEN:

| Zone | Files | Constraint |
|------|-------|------------|
| Inner (absolute) | grounding_ledger.py, grounding_evaluator.py, stats.py, experiment_runner.py, eval_grounding.py, proofs/ | No changes without deviation record |
| Middle (behavioral) | conversation_pipeline.py, persona.py, conversational_policy.py | No changes without deviation record |
| Config | experiment-phase.json, experiment-freeze-manifest.txt | Self-protecting |

**Implication:** Measure 7.1 (log missing salience signals) touches `conversation_pipeline.py` (frozen). Requires DEVIATION-025 before execution. The change is observability-only — adds Langfuse score calls, does not alter model input/output. Impact: none on experiment validity.

### Phase A Completion

- Min 10 sessions, max 20. Stability criterion: last 3 session means within 20% of phase mean.
- Sessions happen during evening voice use (~5-10 per evening).
- Phase A has been active 8 days. At ~5 sessions/evening with irregular use, estimate 10-session minimum reached by ~Day 3-5.
- Phase B transition requires: stability criterion met + BEST implementation in stats.py + OSF pre-registration filed.

### Non-Frozen Work

All measures on non-frozen code can proceed freely in R&D mode:
- Stimmung (shared/stimmung.py, agents/visual_layer_aggregator.py)
- DMN (agents/dmn/)
- Salience router internals (agents/hapax_daimonion/salience/) — but NOT conversation_pipeline.py integration
- Visual/Reverie (hapax-logos/, crates/hapax-visual/)
- Temporal bands (agents/temporal_*.py) — test harnesses only
- Infrastructure (systemd, docker, monitoring)

---

## Schedule

### SPRINT 0: Instrumentation + Quick Analysis (Days 1-2)

**Goal:** Deploy all telemetry that requires no code changes to frozen paths + analyze existing data.

#### Day 1 (2026-03-30, Sun) — 12 hr

| Block | Hours | Measure | Detail | Frozen? |
|-------|-------|---------|--------|---------|
| 0800-0830 | 0.5 | — | Read this schedule + verify working mode R&D + verify Phase A session count in Langfuse | No |
| 0830-0930 | 1.0 | **7.1 prep** | Draft DEVIATION-025 for conversation_pipeline.py observability addition. Justification: adds 3 `hapax_score()` calls for novelty, concern_overlap, dialog_feature_score. No model input/output change. Impact: none. | Deviation |
| 0930-1000 | 0.5 | **7.1 execute** | Add 3 lines after line 1161 of conversation_pipeline.py. Run existing tests to verify no behavioral change. Commit with deviation reference. | FROZEN (w/ deviation) |
| 1000-1200 | 2.0 | **4.1** | Parse `/dev/shm/hapax-dmn/impingements.jsonl`. Write analysis script: count by type, detect contradictions (same metric improving→degrading <60s), report distribution. Save results to `docs/research/dmn-impingement-analysis.md`. | No |
| 1200-1300 | 1.0 | **4.5** | Profile Ollama latency: measure median/p95/p99 inference time for sensory (5s) and evaluative (30s) prompts. Measure VRAM under load. Record in DMN analysis doc. | No |
| 1300-1400 | 1.0 | — | Break + voice session (Phase A data collection) | — |
| 1400-1600 | 2.0 | **6.3** | Add threshold-cross telemetry to `StimmungCollector.snapshot()` in `shared/stimmung.py`. Per-dimension transition events with old/new value, stance contribution, trend. Push to Langfuse via existing trace infrastructure. Tests. | No |
| 1600-1800 | 2.0 | **6.2** | Add modulation factor telemetry. Log modulation_factor, computed word_limit, and actual_response_length per turn. This touches the voice daemon response path — check if frozen. If `conversation_pipeline.py` is the only integration point, bundle into DEVIATION-025. Otherwise instrument in non-frozen wrapper. | Check freeze |
| 1800-2000 | 2.0 | **6.5** | Add per-source health tracking to `visual_layer_aggregator.py`: SourceHealth dataclass, success/fail tracking per data source, alert on consecutive failures. | No |

**Day 1 deliverables:**
- [ ] DEVIATION-025 filed and committed
- [ ] Salience signals (novelty, concern_overlap, dialog_feature_score) logging to Langfuse
- [ ] DMN impingement analysis complete (contradiction rate, type distribution)
- [ ] Ollama latency profile recorded
- [ ] Stimmung threshold-cross telemetry active
- [ ] Modulation factor telemetry active (or deviation-scoped if frozen)
- [ ] Source health tracking active

#### Day 2 (2026-03-31, Mon) — 12 hr

| Block | Hours | Measure | Detail | Frozen? |
|-------|-------|---------|--------|---------|
| 0800-1000 | 2.0 | **7.2 prep** | Query Langfuse for existing activation_score traces. Determine N (how many turns have activation_score + context_anchor_success in same trace). If N ≥ 50: proceed to analysis. If N < 50: estimate sessions needed to reach 50. | No |
| 1000-1200 | 2.0 | **7.2 execute** | If N ≥ 50: Run correlation analysis. Compute Pearson r for (activation, response_tokens) and (activation, context_anchor_success). Bayesian correlation with prior Normal(0.3, 0.15), ROPE [-0.1, 0.1]. Record results. If N < 50: document data gap, set collection target, move to next task. | No (analysis) |
| 1200-1300 | 1.0 | — | Break + voice session (Phase A) | — |
| 1300-1500 | 2.0 | **8.1** | Signal availability audit for Bayesian Tool Selection. Grep codebase for all 16 proposed signals. For each: exists/missing/derivable. Document in `docs/research/bayesian-tools-signal-audit.md`. | No |
| 1500-1700 | 2.0 | **3.2** | Protention accuracy validation. Write `tests/test_protention_validation.py`: for each ProtentionSnapshot prediction, check if transition occurred within expected_in_s. Track precision/recall/lead-time-error. Need recent protention data — check if ProtentionEngine logs predictions. | No |
| 1700-1900 | 2.0 | **3.3** | Surprise flagging impact. Write test harness: send primal_impression to Claude with and without surprise markup. Compare whether model mentions surprised fields. 20 perception snapshots, paired design. | No |
| 1900-2000 | 1.0 | Sprint 0 review | Compile results. Update this schedule with findings. Record any blockers. | — |

**Day 2 deliverables:**
- [ ] Claim 5 correlation result (or documented data gap with collection plan)
- [ ] Signal audit for Bayesian Tools (16 signals: exists/missing/derivable)
- [ ] Protention accuracy baseline (precision/recall at 120s horizon)
- [ ] Surprise flagging impact result (helps/doesn't help model reasoning)
- [ ] Sprint 0 retrospective recorded

**Sprint 0 gate:** If 4.1 shows >15% contradiction rate in DMN impingements, STOP and rescope DMN measures. If 7.2 shows r < 0.1, STOP and rescope salience measures. These are go/no-go gates.

---

### SPRINT 1: Core Validation Experiments (Days 3-7)

**Goal:** Execute the high-value experiments that move posteriors most.

#### Day 3 (2026-04-01, Tue) — 12 hr

| Block | Hours | Measure | Detail |
|-------|-------|---------|--------|
| 0800-1200 | 4.0 | **4.2** | Crisis detection benchmark. (1) Verify hapax-dmn.service running. (2) Seed fortress with marginal resources: pop=5, drink=8 (below 5×2=10 threshold). (3) Monitor impingement stream — time from resource deficit → ABSOLUTE_THRESHOLD impingement → fortress deliberation → governor action. (4) Disable DMN pulse, repeat measurement. (5) Compare latencies. Record in `docs/research/dmn-crisis-benchmark.md`. |
| 1200-1300 | 1.0 | — | Break + voice session |
| 1300-1700 | 4.0 | **3.1 prep** | ~~Temporal band A/B test harness.~~ **DONE (Day 2, PR #480).** Harness at `tests/research/test_temporal_contrast.py`. 50 synthetic snapshots, 4-task battery, LLM-as-judge scoring, automated effect size computation. Additionally: multi-scale temporal integration shipped (minute/session/day in XML), surprise-weighted impression ordering (RoPE exploit), ProtentionEngine training wired. |
| 1700-2000 | 3.0 | **3.1 run** | Execute A/B test. Run `uv run pytest tests/research/test_temporal_contrast.py -m llm -v`. 20 pairs × 4 tasks × 2 conditions = 160 LLM calls. Gate: temporal_awareness effect ≥ 0.5 points. Analysis: `uv run python tests/research/analysis.py`. |

**Day 3 deliverables:**
- [ ] DMN crisis detection benchmark complete (latency with/without DMN)
- [ ] Temporal band A/B test result (effect size + CI) — harness ready, just run

#### Day 4 (2026-04-02, Wed) — 12 hr

| Block | Hours | Measure | Detail |
|-------|-------|---------|--------|
| 0800-1200 | 4.0 | **6.1 prep** | Stimmung perturbation study setup. (1) Build stimmung override mechanism: write `nominal` to `/dev/shm/hapax-stimmung/state.json` every 5s, overriding collector. (2) Instrument all 10 consumers to log their stimmung-derived parameters (response length, model tier, visual warmth, haptic events, scheduler density, engine phase). (3) Design A-B-A protocol: 2hr normal → 2hr overridden → 2hr normal. (4) Build comparison dashboard (Langfuse query or local script). |
| 1200-1300 | 1.0 | — | Break |
| 1300-1900 | 6.0 | **6.1 run** | Execute A-B-A perturbation. Phase A (1300-1500): system normal, log all parameters. Phase B (1500-1700): override stimmung to nominal, log all parameters. Phase A' (1700-1900): remove override, log all parameters. During each phase: note subjective experience, use voice for at least 2 sessions. |
| 1900-2000 | 1.0 | **6.1 analysis** | Compare instrumented parameters across phases. Key questions: (1) Did response lengths change? (2) Did model tier change? (3) Did visual warmth change? (4) Did you notice? Record in `docs/research/stimmung-perturbation-results.md`. |

**Day 4 deliverables:**
- [ ] Stimmung perturbation study complete (parameter comparison + subjective report)

#### Day 5 (2026-04-03, Thu) — 12 hr

| Block | Hours | Measure | Detail |
|-------|-------|---------|--------|
| 0800-1200 | 4.0 | **4.3** | Voice integration wire-up. (1) Modify voice daemon to read `/dev/shm/hapax-dmn/buffer.txt` and include in phenomenal context (Layer 2, after stimmung). (2) Modify voice daemon to write TPN_ACTIVE flag when processing utterance. (3) Verify DMN anti-correlation: tick rate should double during voice. (4) Tests. NOTE: If voice daemon path is frozen, this requires DEVIATION-026. Check freeze manifest — voice daemon main loop (`agents/hapax_daimonion/`) has `conversation_pipeline.py` frozen but the daemon entry point and phenomenal context renderer may not be. |
| 1200-1300 | 1.0 | — | Break + voice session |
| 1300-1700 | 4.0 | **7.3** | Salience component ablation. (1) Configure salience router with 3 weight profiles: concern_only, dialog_only, novelty_only. (2) Collect 20 turns per profile (if data from 7.2 sufficient, use Langfuse replay; otherwise collect live). (3) Compute context_anchor_success per profile. (4) Compare: which component predicts grounding best? |
| 1700-2000 | 3.0 | **6.4** | Operator perception ground truth mechanism. Add lightweight prompt in voice daemon: when operator says "system feels [X]" or similar health-perception utterance, log perceived state alongside computed stimmung. Use keyword detection (already in utterance_features.py pattern). Start collecting ground truth passively. |

**Day 5 deliverables:**
- [ ] Voice daemon consuming DMN buffer (or deviation filed + scheduled)
- [ ] TPN_ACTIVE signaling wired
- [ ] Salience component ablation results
- [ ] Operator perception ground truth mechanism active

#### Day 6 (2026-04-04, Fri) — 12 hr

| Block | Hours | Measure | Detail |
|-------|-------|---------|--------|
| 0800-1200 | 4.0 | **10.1** | Amendment 1: Materialization from substrate. Modify content_layer.wgsl: gate content visibility by `noise(uv) > threshold` where threshold decreases over 500ms (uniform driven by Rust). Content crystallizes FROM the noise field rather than screen-blending on top. Test in dev mode. |
| 1200-1300 | 1.0 | — | Break |
| 1300-1900 | 6.0 | **10.2** | Amendment 3: Material quality. Create 5 material shader variants: water (flowing edges, horizontal dissolution, transparent overlap), fire (expanding outward, bright edges, center opacity), earth (slow crystallization, hard edges, sediment), air (rapid scatter, soft edges, opacity pulse), void (inverse — content is absence in noise). Wire material selection from ImaginationFragment.material field. |
| 1900-2000 | 1.0 | — | Test all 5 materials rendering. Screenshot each for comparison doc. |

**Day 6 deliverables:**
- [ ] Amendment 1 (materialization) implemented and rendering
- [ ] Amendment 3 (5 materials) implemented and rendering
- [ ] Visual comparison document with screenshots

#### Day 7 (2026-04-05, Sat) — 12 hr

| Block | Hours | Measure | Detail |
|-------|-------|---------|--------|
| 0800-1000 | 2.0 | **10.4** | Amendment 6: Soft escalation. Replace hard threshold proactive speech trigger with `P(speak) = sigmoid(k × (salience - midpoint))`. Wire in imagination loop. |
| 1000-1400 | 4.0 | **10.3** | Phenomenological interview. Run 30-min session with Amendments 1+3 active. After session, complete 7-question protocol: (1) How did text appear? (2) Emerged or placed? (3) Where from? (4) Water vs fire feel? (5) Distinguish without labels? (6) Space after fade? (7) Any content feel resistant/inevitable? Score for Bachelardian vs control vocabulary. |
| 1400-1500 | 1.0 | — | Break |
| 1500-1700 | 2.0 | **10.5** | Comparative rendering. Session A: amendments on. Session B: amendments off (vanilla blend). Blind self-report on "immersive / material / remembered / surprising" dimensions. |
| 1700-1900 | 2.0 | Sprint 1 review | Compile all results. Update posterior estimates. Identify any failed gates. Adjust Sprint 2 scope. |
| 1900-2000 | 1.0 | — | Update RESEARCH-STATE.md + this schedule with findings |

**Day 7 deliverables:**
- [ ] Amendment 6 (soft escalation) implemented
- [ ] Phenomenological interview complete (Bachelard vocabulary score)
- [ ] Comparative rendering result
- [ ] All Sprint 1 results compiled
- [ ] Updated posterior estimates for all 6 models

**Sprint 1 gate:** Review all posteriors. If any model dropped below its original posterior (negative result), document why and remove further investment in that model from Sprint 2.

---

### SPRINT 2: Integration + Longitudinal Setup (Days 8-12)

**Goal:** Wire cross-system integrations, begin longitudinal data collection, prepare for Phase B.

#### Day 8 (2026-04-06, Sun) — 12 hr

| Block | Hours | Measure | Detail |
|-------|-------|---------|--------|
| 0800-1200 | 4.0 | **Phase A check** | Query Langfuse: how many Phase A sessions collected? If ≥ 10 and stability criterion met: prepare for Phase B transition. If < 10: continue collection, adjust timeline. |
| — | — | **stats.py BEST** | If Phase A nearly complete: implement BEST (Kruschke 2013) in stats.py. Student-t likelihood, separate variance, priors calibrated from Phase A data. This is a FROZEN file — requires DEVIATION-026. Justification: pre-registered analysis method change (already documented in pre-registration as "must fix before Phase B"). |
| 1200-1300 | 1.0 | — | Break |
| 1300-1700 | 4.0 | **8.2** | Minimal mode selector prototype. Keyword/heuristic implementation (MIDI→Studio, calendar→Scheduling, docker→System, default→Research). Mode restricts which tools are offered. Non-Bayesian — tests the principle only. Wire into voice daemon if non-frozen path exists, otherwise standalone evaluation harness. |
| 1700-2000 | 3.0 | **8.3** | Tool fitness baseline from Langfuse. Query: which tools invoked, on which turns, with what context_anchor_success. Compute per-tool relevance = P(anchor_success > median | tool_invoked). Identify tools that consistently help vs. hurt. |

#### Day 9 (2026-04-07, Mon) — 12 hr

| Block | Hours | Measure | Detail |
|-------|-------|---------|--------|
| 0800-1200 | 4.0 | **M-1: Integration depth** | Controlled mesh integration experiment (SCM §4.2). (1) Baseline: collect 30 min of `/api/stimmung` snapshots (includes E_mesh, sheaf residuals, eigenform state, topology) at 1-min intervals. (2) Disable stimmung collector (`systemctl --user stop hapax-stimmung-sync.timer`). Hold for 20 min. (3) Record which components change behavior: check DMN pulse rate (should lose modulation), imagination cadence (should lose stance adjustment), voice response length (should lose word_limit modulation), visual surface intensity (should lose gain scheduling). (4) Count non-adjacent affected components: if ≥ 3 components beyond stimmung's direct consumers change, integration depth ≥ 1. (5) Restore stimmung. Record recovery time. Save to `docs/research/mesh-integration-depth.md`. **This simultaneously validates SCM §4.2 and provides data for G-mesh criterion 1.** |
| 1200-1300 | 1.0 | — | Break |
| 1300-1500 | 2.0 | **3.4** | Decay function comparison. Run retention summarization with exponential, power law, and stepped decay. Generate temporal context for 20 perception windows per strategy. Human-rate coherence (which narrative best captures what actually happened?). |
| 1500-1700 | 2.0 | **4.4** | U-Curve primacy validation. Parse 20 fortress deliberation outputs. Count references to DMN buffer summary (position 0) vs. individual mid-buffer observations. Compute ratio. Target: summary referenced >3× more. |
| 1700-1900 | 2.0 | **7.4** | Static tier comparison. From Langfuse: identify turns where salience would have routed to LOCAL or FAST. Compare context_anchor_success on those turns vs. CAPABLE turns. Tests whether "Always CAPABLE" is empirically justified. |
| 1900-2000 | 1.0 | **Consolidation** | Compile all measure results into unified posterior update table. Write `docs/research/bayesian-validation-results.md` with: measure, expected result, actual result, posterior shift, implications. |

#### Days 10-12 (2026-04-08 to 2026-04-10) — 36 hr total

| Day | Focus | Detail |
|-----|-------|--------|
| 10 | **Phase B preparation** | File OSF pre-registration (if not done). Finalize stats.py BEST implementation. Verify all experiment flags. Calibrate Phase B priors from Phase A data. Run prior predictive check. Switch experiment-phase.json to "intervention" when ready. |
| 11 | **Phase B session 1-5** | Begin Phase B data collection. Monitor all newly instrumented telemetry (salience signals, stimmung transitions, DMN buffer integration). Verify data flowing to Langfuse. First sequential checkpoint at session 5. |
| 12 | **Sprint 2 review + buffer** | Review all Phase B early data. Fix any instrumentation issues. Update schedule for Sprint 3. Begin Phase B sessions 6-10. |

---

### SPRINT 3: Phase B Data Collection + Ongoing Measurement (Days 13-21)

**Goal:** Collect Phase B data while longitudinal measures accumulate.

| Day | Focus | Detail |
|-----|-------|--------|
| 13-14 | Phase B sessions 6-10 | Sequential checkpoint at session 10: compute interim posterior, HDI width, %ROPE. If BF > 10: early decisive result. If inconclusive: continue to 20. |
| 15-16 | Phase B sessions 11-15 | If Phase B running: continue. If decisive: begin Phase A' reversal. Meanwhile: collect stimmung modulation correlation data (6.2), operator perception ground truth (6.4), salience signal correlations (7.2 longitudinal). |
| 17-18 | Phase B sessions 16-20 OR Phase A' | Complete Phase B or begin reversal. Analyze Reverie longitudinal data (has operator's experience deepened since Day 6-7 amendments?). |
| 19-20 | Analysis | Full Cycle 2 analysis: BEST model, posterior for mu_diff, 95% HDI, %ROPE, BCTau. Update Claim 1 posterior. Run secondary analyses (trajectory slope, acceptance prediction, behavioral covariates, RLHF monitoring). |
| 21 | **Final review** | Compile comprehensive posterior update for all 10 models. Write final validation results document. Update RESEARCH-STATE.md. Plan Cycle 3 scope (if needed). |

---

## Decision Gates

| Gate | Day | Condition | If PASS | If FAIL |
|------|-----|-----------|---------|---------|
| G1: DMN hallucination | 1 | Contradiction rate < 15% | Continue DMN measures | Stop DMN investment; rescope to "fix hallucination containment first" |
| G2: Salience correlation | 2 | r ≥ 0.1 (weak positive) | Continue to ablation (7.3) | Rescope salience: remove Bayesian tools (8.x) from schedule, investigate why activation doesn't predict outcomes |
| G3: Temporal band value | 3 | Effect > 0.5 points on 5-point scale | Continue phenomenological measures | Downgrade phenomenological mapping; accept ML-mechanistic explanation without philosophical vocabulary |
| G4: Stimmung perception | 4 | Operator notices perturbation | Continue stimmung investment | Amplify stimmung effects (increase modulation range) or accept as infrastructure-only (no phenomenological claim) |
| G5: Material imagination | 7 | Bachelardian vocabulary > control in interview | Continue Reverie investment | Accept visual surface as "good generative art" without phenomenological framing |
| **G-mesh: Integrated mesh** | **7** | **See criteria below** | **Treat portfolio as coupled system; apply correlated gains** | **Treat models as independent; discount portfolio by coupling fragility factor 0.85** |
| G6: Phase A stability | 8 | ≥ 10 sessions + stability criterion | Transition to Phase B | Continue Phase A collection; delay Sprint 2 integration work |
| G7: Phase B decisive | 14 | BF > 10 at session 10 | Early Phase A' reversal | Continue to session 20 |

### G-mesh Criteria (Sprint 1 Review, Day 7)

The SCM formalization claims the 14 S1 components form a genuinely integrated mesh, not independent agents sharing a filesystem. This gate tests that claim using three operational criteria. All three must pass.

**Criterion 1: Cascade propagation.** During the stimmung perturbation study (6.1, Day 4), measure whether forcing stimmung to nominal changes behavior in at least 3 non-adjacent components (integration depth ≥ 1 per §4.2). Components to instrument: DMN pulse rate, imagination cadence, visual surface intensity, voice response length. If perturbation in stimmung changes only its direct consumers (depth 0), the mesh is merely aggregated.

**Criterion 2: Sheaf consistency under load.** During normal operation on Days 3-7, collect `restriction_residual_rms` from `/api/stimmung` at 5-minute intervals. Pass condition: median residual < 0.15 (restriction maps are approximately consistent). If median ≥ 0.15, the mesh's distributed state is incoherent — components are reading the same traces but computing inconsistent results.

**Criterion 3: Topological robustness.** From `topology_health.py`, verify β₀ = 1 (single connected component) and stability > 0.25 (removing the worst single node doesn't fragment the cycle structure by >75%). If β₀ > 1, the mesh has disconnected subgraphs. If stability < 0.25, a single node failure destroys most feedback loops.

**If G-mesh fails:** The portfolio probability must be computed as independent products with a 0.85 coupling fragility discount (models that the SCM claims are integrated but aren't get their SCM-adjusted gains reduced by 15%). The remaining schedule measures are still valid but their interpretation shifts from "validating a system" to "validating components."

**If G-mesh passes:** The portfolio benefits from correlated gains — improvements to stimmung, DMN, or salience propagate through the mesh and raise neighboring models' posteriors. The ~0.92 SCM-adjusted portfolio estimate holds.

---

## Posterior Tracking Table

Update this table as results come in. Initial values from Bayesian Validity Analysis (2026-03-29).

### SCM-Adjusted Priors (2026-04-01)

The SCM formalization (PRs #507-#524, spec: `docs/research/stigmergic-cognitive-mesh.md`) delivered structural changes that move several priors before scheduled measures execute. These adjustments reflect implemented, operational code — not aspirational design. The schedule's 10 models are not independent; the SCM reveals they are components of a single formal system with defined coupling through `/dev/shm` stigmergic traces. This has implications: correlated gains (SCM work raised multiple models simultaneously) and correlated risk (if stigmergic coordination proves empirically weak, several models fall together). Gate G-mesh (below) tests for this.

| Model | Pre-Schedule | SCM-Adjusted | Evidence |
|-------|-------------|-------------|----------|
| 1. Clark & Brennan Grounding | 0.88 | 0.88 | No SCM impact; awaits Phase B |
| 2. Context as Computation | 0.97 | 0.97 | No change |
| 3. Phenomenological Mapping | 0.58 | 0.63 | Temporal A/B harness shipped (PR #480), multi-scale integration (minute/session/day), surprise-weighted ordering, ProtentionEngine wired |
| 4. DMN Continuous Substrate | 0.53 | 0.70 | Extracted to 3 daemons (pulse/imagination/resolver), all publish ControlSignals, stimmung modulation (4:2:1.5:1× by stance), G1 passed (0% contradiction in 716 impingements), impingement cascade architecture operational |
| 5. Constitutional Governance | 0.93 | 0.95 | Production consent enforcement in 5 subsystems (calendar, gmail, pipeline, RAG, video), IFC label infra operational, fail-closed + staleness detection, 14 egress gates |
| 6. Stimmung | 0.64 | 0.73 | Gain scheduling operational (DMN pulse, imagination cadence), positioned as system prior with 11+ readers, hysteresis (3-reading recovery), sheaf health monitors stimmung↔DMN consistency |
| 7. Salience/Biased Competition | 0.61 | 0.65 | Signal audit complete (11/16 exist, 4 derivable, 1 naming only), salience_integration = 59.6% of all impingements (dominant type) |
| 8. Bayesian Tool Selection | 0.54 | 0.58 | Signal audit confirms no fundamental gaps, all 16 signals available or trivially derivable |
| 9. Temporal Structure | 0.94 | 0.94 | No change |
| 10. Reverie (Bachelard) | 0.33 | 0.58 | All 6 amendments implemented and operational (materialization, temporal feedback, 5 materials, DMN evaluative tick, per-slot immensity, soft escalation); smoke test renders exist; awaits phenomenological validation |
| **Portfolio** | **0.89** | **~0.92** | 6 remediation models avg 0.54→0.66; discount for correlated risk under SCM coupling |

### Live Tracking

| Model | SCM-Adjusted | After Sprint 0 | After Sprint 1 | After Sprint 2 | After Sprint 3 |
|-------|-------------|----------------|----------------|----------------|----------------|
| 1. Clark & Brennan Grounding | 0.88 | — | — | — | _Phase B result_ |
| 2. Context as Computation | 0.97 | — | — | — | — |
| 3. Phenomenological Mapping | 0.63 | _3.2, 3.3_ | _3.1_ | _3.4_ | — |
| 4. DMN Continuous Substrate | 0.70 | _4.1 ✓ (G1 pass), 4.5_ | _4.2, 4.3_ | _4.4_ | — |
| 5. Constitutional Governance | 0.95 | — | — | — | — |
| 6. Stimmung | 0.73 | _6.2, 6.3, 6.5_ | _6.1, 6.4_ | — | _longitudinal_ |
| 7. Salience/Biased Competition | 0.65 | _7.1, 7.2_ | _7.3_ | _7.4_ | — |
| 8. Bayesian Tool Selection | 0.58 | _8.1 ✓_ | — | _8.2, 8.3_ | — |
| 9. Temporal Structure | 0.94 | — | — | — | — |
| 10. Reverie (Bachelard) | 0.58 | — | _10.1-10.5_ | — | _longitudinal_ |
| **Portfolio** | **~0.92** | — | — | — | — |

---

## File Inventory

All output documents created by this schedule:

| Document | Created | Purpose |
|----------|---------|---------|
| `docs/research/bayesian-validation-schedule.md` | Day 0 | This file |
| `docs/research/dmn-impingement-analysis.md` | Day 1 | 4.1 results |
| `docs/research/bayesian-tools-signal-audit.md` | Day 2 | 8.1 results |
| `docs/research/dmn-crisis-benchmark.md` | Day 3 | 4.2 results |
| `docs/research/stimmung-perturbation-results.md` | Day 4 | 6.1 results |
| `docs/research/reverie-amendment-comparison.md` | Day 6-7 | 10.1-10.5 results |
| `docs/research/bayesian-validation-results.md` | Day 9 | Unified posterior updates |
| `docs/research/mesh-integration-depth.md` | Day 9 | M-1 results (SCM §4.2 integration depth) |
| `research/protocols/deviations/DEVIATION-025.md` | Day 1 | Salience observability in frozen file |
| `research/protocols/deviations/DEVIATION-026.md` | Day 8 | stats.py BEST implementation |

---

## Quick Reference: Measure → Code Location

| Measure | Primary File(s) | Frozen? |
|---------|-----------------|---------|
| 7.1 Log salience signals | agents/hapax_daimonion/conversation_pipeline.py:1161 | YES — deviation required |
| 4.1 Contradiction scan | /dev/shm/hapax-dmn/impingements.jsonl (read-only analysis) | No |
| 7.2 Claim 5 correlation | agents/hapax_daimonion/experiment_runner.py (read-only query) | YES — but read-only |
| 4.5 Ollama profiling | agents/dmn/ (measurement only) | No |
| 6.3 Threshold-cross | shared/stimmung.py | No |
| 6.2 Modulation telemetry | agents/hapax_daimonion/conversation_pipeline.py | YES — bundle with DEVIATION-025 |
| 6.5 Source health | agents/visual_layer_aggregator.py | No |
| 4.2 Crisis benchmark | agents/dmn/, fortress game state | No |
| 3.1 Temporal A/B | tests/research/ (new harness) | No |
| 6.1 Perturbation | shared/stimmung.py, /dev/shm override | No |
| 4.3 Voice integration | agents/hapax_daimonion/ daemon entry, phenomenal context | Check — may need deviation |
| 7.3 Ablation | agents/hapax_daimonion/salience/ (weight config) | No (salience internals not frozen) |
| 6.4 Perception ground truth | agents/hapax_daimonion/ utterance processing | Check freeze scope |
| 10.1-10.2 Amendments | hapax-logos/crates/hapax-visual/ (Rust/WGSL) | No |
| 10.3 Interview | Operator protocol (no code) | No |
| 8.2 Mode selector | New file (agents/hapax_daimonion/mode_selector.py) | No |
| 3.2 Protention | tests/ (new validation harness) | No |
| 3.3 Surprise | tests/ (new evaluation harness) | No |
| 3.4 Decay function | agents/temporal_bands.py config | No |
| 4.4 U-Curve primacy | Analysis of deliberation outputs | No |
| 7.4 Static tier | Langfuse query (analysis only) | No |
| 8.1 Signal audit | Codebase grep (analysis only) | No |
| 8.3 Tool baseline | Langfuse query (analysis only) | No |
| M-1 Integration depth | systemctl stop/start, /api/stimmung snapshots, DMN/imagination/voice/visual observation | No |
