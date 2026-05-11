# ytb-SS2 — Substantive speech research + calibration

**Status:** research-scoping (not implementation spec)
**Author:** alpha (2026-04-24)
**Predecessors:** ytb-SS1 (#1286, autonomous narrative director Phase 1)
**Measurement infra:** ytb-QM1 (#1292, chronicle quality exporter), ytb-QM2 (#1293, impingement bus sampler)
**vault note:** `~/Documents/Personal/20-projects/hapax-cc-tasks/active/ytb-SS2-substantive-speech-research.md`

## §1. Why this is research, not a feature

SS1 shipped the *capability* for Hapax to emit narrative every 2-3 minutes during operator-absent stretches via the existing CPAL impingement path. That capability now exists. SS2 is the calibration thread that decides **what makes that narrative substantive** rather than filler.

The acceptance criterion is operator judgment: "holds attention at my standards." There is no benchmark to optimize against — quality is a moving target, irreducibly subjective, and only knowable in retrospect after operator listens. SS2 therefore unfolds as iteration cycles, not as a single shipped feature. Each cycle:

1. Ships one candidate change (typically a prompt-template tweak in `compose.py`, a new state-reader, or a gating-rule refinement).
2. Runs that change on a livestream slot for 24-48h.
3. Surfaces a sample of emissions for operator listen + judgment.
4. Synthesises the verdict into the next cycle's hypothesis.

This protects against the common failure mode of shipping a "speech improvement" that scores well on a proxy metric but reads worse to the operator. Each cycle must close the loop with operator judgment before the next cycle's design freezes.

## §2. Iteration protocol

### §2.1. Per-cycle steps

Each cycle follows this six-step pattern:

1. **Hypothesis.** What aspect of substantiveness is being tested. Stated as a falsifiable claim.
2. **Diff.** Smallest possible change that exercises the hypothesis. Prefer prompt-template changes + state-reader additions over architectural changes.
3. **Baseline capture.** 24h of pre-change QM1/QM2 metrics + a chronicle-sourced sample of pre-change autonomous narrative emissions.
4. **Ship + run.** Branch, PR, merge, deploy to the daimonion. Run on stream for 24-48h.
5. **Operator judgment.** Operator listens to a random-sampled batch of emissions, scores each on the §3 rubric, records verdict in the cycle log.
6. **Synthesis.** Decide: keep change (move to next hypothesis), revert (failed), or iterate within hypothesis (refine). Update vault note + this spec's cycle log.

### §2.2. Concurrency

Cycles can overlap **only if hypotheses are independent** — e.g. a prompt-template cycle (hypothesis A) and a gating-rule cycle (hypothesis B) can run simultaneously on different stream slots if both would not confound each other's measurement. When in doubt, run serially.

### §2.3. Decision gates

After each cycle's judgment step:

- **≥ 4/5 average on §3 rubric across a 20-emission sample (over the 48h observation window):** ship verdict = **hold**. The change merges; next cycle picks a different hypothesis.
- **3/5 to < 4/5:** ship verdict = **iterate**. Same hypothesis, refined diff. Maximum 3 iterations per hypothesis before declaring it inconclusive and moving on.
- **< 3/5:** ship verdict = **revert**. Diff is reverted. Next cycle either picks a new hypothesis or revisits this one with substantially different framing.

## §3. Operator judgment rubric

Each emission is scored on five binary axes (0/1 each):

| Axis | Question | Why it matters |
|------|----------|----------------|
| **Substantive** | Did the emission carry information / observation / reflection — not just texture? | The "filler" failure mode |
| **Grounded** | Could the operator point to a specific source (vault note, chronicle event, programme directive, recent music) the emission references? | Per `feedback_grounding_exhaustive`: every move is grounding or outsourced-by-grounding |
| **Coherent with stimmung** | Did the emission tone match `exploration_deficit` / `operator_stress` / `physiological_coherence` at emit time? | Stance-mismatched speech reads as either oblivious or panicked |
| **Programme-respecting** | Did the emission stay in the active programme's register (no "ritual" emissions during "wind_down", etc.)? | Programmes are affordance-expanders, not gates — but the register expectation is real |
| **Listenable** | Would the operator listen again, or skip? | The bottom-line subjective judgment |

Scoring procedure: operator (or delegated audit run) opens a random sample of N=20 emissions from the cycle's chronicle window, scores each, computes mean. Sample selection: uniform random over the 48h cycle window, NOT cherry-picked.

### §3.1. QM5 operator-quality feedback handoff

`ytb-QM5-operator-quality-feedback-interface` supplies the private input path
for the subjective side of this rubric. Producers append JSONL to:

- `~/hapax-state/operator-quality-feedback/ratings.jsonl`

The sink event is `operator_quality_rating` with `schema_version: 1`,
`occurred_at`, `rating` (1-5), `rating_axis`, `source_surface`, optional
`programme_id` / `condition_id` / `run_id` / `emission_ref`, and
`evidence_refs[]`. The two operator surfaces are:

- CLI/dry-run: `scripts/log-operator-quality-rating.py 4 --axis overall`
- Stream Deck: `operator.quality.rate` bindings in `config/streamdeck.yaml`

SS2 cycle scoring should join ratings to sampled emissions via `emission_ref`
when present. Ratings without an `emission_ref` are cycle/session-level
operator verdicts and should be aggregated by `programme_id`, `condition_id`,
or observation window. SS3 may consume only these cycle-level summaries until
SS2 has converged; the raw QM5 JSONL remains a private research signal and must
not become a public attribution, chat, or viewer-facing feedback surface.

### §3.2. Cycle report harness

`scripts/ss2-cycle-report.py` is the private cycle-packet generator for this
protocol. Given a cycle id and an observation window, it:

- reads `self_authored_narrative` / `narrative.emitted` chronicle rows;
- samples emissions uniformly with a deterministic seed;
- emits stable `emission_ref` handles such as `chronicle:<event_id>`;
- joins direct QM5 ratings by `emission_ref`;
- joins cycle-level QM5 ratings by observation window plus optional
  `programme_id`, `condition_id`, or `run_id`;
- computes the five-axis rubric mean and hold/iterate/revert/insufficient
  verdict;
- computes conservative autonomous-narrative grounding coverage over the
  whole window, treating missing `grounding_provenance` as ungrounded.

The output is private-by-default Markdown or JSON. It is an operator scoring
packet, not a public claim, and it cannot authorize publication, monetization,
or research-validity assertions.

## §4. Cycle 1 — first hypothesis (proposed)

### §4.1. Hypothesis

**SS1 emissions currently compose narrative from `chronicle + stimmung + director-intent + programme.narrative_beat`.** This gives Hapax thematic anchors but no factual grounding. Per `feedback_grounding_exhaustive`, every move must be grounding or outsourced-by-grounding.

**Claim:** SS1 emissions whose `compose.py` LLM call also receives the operator's recent vault notes (last 3-5 daily notes + active goals) will score higher on operator judgment than current emissions, primarily on the **Grounded** and **Substantive** axes.

### §4.2. Diff scope

- `agents/hapax_daimonion/autonomous_narrative/state_readers.py` — add a `read_recent_vault_context()` reader that pulls the last 3-5 daily notes + active `type: goal` notes from `~/Documents/Personal/`. Cap input bytes (keep prompt under ~4k tokens). Use file-mtime ordering — no LLM call in the reader.
- `agents/hapax_daimonion/autonomous_narrative/compose.py` — add the vault-context block to the prompt template. Frame it as "operator's current focus" not "what to talk about" — preserve the gating layer's authority.
- Tests: extend `tests/hapax_daimonion/autonomous_narrative/test_state_readers.py` with vault-reader fixtures + missing-vault graceful degradation.
- Bytes: ~80 LOC additions, no architectural change.

### §4.3. Baseline capture

24h of QM1/QM2 metrics before the diff lands. Specifically:
- `hapax_content_grounding_coverage_5m` — current SS1 emissions don't set `grounding_provenance`, so this should be near 0 or NaN for autonomous-narrative chronicle events.
- `hapax_content_intent_family_cardinality_1h` — establishes the current diversity floor.
- `hapax_impingement_novelty_score` — establishes the current novelty trajectory.

Plus: chronicle-sourced sample of 20 autonomous narrative emissions with their full payloads.

### §4.4. Expected signal

If the hypothesis is right:
- **Grounded** axis score should jump (operator can now trace each emission to a specific vault source).
- **Substantive** axis score should improve (vault context pushes the LLM toward observation-density rather than texture).
- **Coherent with stimmung** + **Programme-respecting** axes should be flat (this diff doesn't touch those code paths).
- **Listenable** axis: directional improvement expected, but the most subjective — final tiebreaker.

If wrong: Grounded improves but Substantive doesn't (vault context is being recited, not used as scaffolding for thought) — would lead to cycle 2 hypothesis around prompt-template framing rather than input availability.

## §5. Cycle 2+ candidate hypotheses (sketches)

Future cycles will pick from these depending on cycle 1 outcomes:

- **H2: Stimmung-coupled register.** Add stimmung-stance-conditional prompt fragments (different prosody guidance for `degraded` vs `flow` vs `seeking`). Tests the Coherent-with-stimmung axis.
- **H3: Programme-author voice transfer.** When programme.narrative_beat carries authored language, preserve it in emission rather than paraphrasing. Tests Programme-respecting + Substantive.
- **H4: Recent-music grounding.** Read the last N tracks from the studio compositor's playback log; reference them when stimmung suggests musical attentiveness. Tests Grounded.
- **H5: Cross-emission self-citation.** Within a programme slot, allow emission N to reference emission N-1 ("earlier I noticed…"). Note: this is the natural bridge to SS3.
- **H6: Operator-presence-conditional density.** When QM2 novelty_score is low (stuck), emit denser; when high (flowing), emit sparser. Tests an emergent gating layer.

These are sketches, not commitments. Cycle 1's judgment shapes which is most useful next.

## §6. Risks + mitigations

### §6.1. Operator judgment fatigue

Listening to 20 emissions per cycle adds up. Mitigation: surface samples in a fixed daily-cadence batch (e.g. once-per-cycle audit) rather than asking for live operator listening. The chronicle already retains 12h, so the audit can sample after-the-fact.

### §6.2. Sample selection bias

Random selection over the 48h window — not cherry-picked. The exporter could surface a CSV of {ts, emission_text, qm1_grounded_at_emit, qm2_novelty_at_emit, programme_slot} for each cycle to make sampling reproducible.

### §6.3. Cycle confounding by other shipped changes

If alpha or peer sessions ship other daimonion-affecting PRs during a cycle window, attribution gets murky. Mitigation: declare a cycle's start/end timestamps in the cycle log; tag all daimonion-touching PRs in the window so the audit can filter.

### §6.4. Drift in operator's standard

Operator's "holds attention" standard may drift over weeks. Mitigation: re-baseline the rubric every 3 cycles by re-scoring an old sample to check inter-rater consistency.

## §7. Out of scope

- **Multi-session long-arc narrative continuity.** That's ytb-SS3 — depends on SS2 having converged on per-emission substantiveness first.
- **Programme-author intent.** Programmes themselves are operator-authored or Hapax-authored; SS2 changes only how emissions DRAW from programmes, not who composes them.
- **Voice prosody calibration.** Kokoro TTS engine is a separate concern. SS2 measures the *content* substantiveness; prosody fixes go into a different track.
- **Cross-stream personalization.** Single-operator axiom; no per-viewer state.

## §8. Termination criteria

SS2 is **done** when:

1. At least 3 cycles have completed and been logged.
2. Final cycle scores ≥ 4/5 average on the §3 rubric over a 20-emission sample.
3. `hapax_content_grounding_coverage_5m` is sustained ≥ 0.7 during the final cycle's observation window.
4. `hapax_impingement_novelty_score` is sustained > pre-SS2 baseline during the final cycle's observation window.
5. Cycle log retained in vault + this spec; operator can retrace what was tried, what worked, what didn't.

If after 5 cycles the rubric average remains < 4/5, SS2 escalates to a redesign discussion: the hypothesis space is exhausted, and the next move is architectural rather than calibration.

## §9. Cycle log

(Filled in as cycles complete. Each entry: cycle number, hypothesis short name, diff PR, observation window, mean rubric score, verdict.)

| Cycle | Hypothesis | PR | Window (UTC) | Score | Verdict |
|-------|------------|----|----|-------|---------|
| 1 | Vault-context grounding | #1295 | Pending report via `scripts/ss2-cycle-report.py` | Pending operator/QM5 ratings | Pending |

## §10. Inputs from prior work

- **SS1 (#1286)** — autonomous narrative director Phase 1. Established the impingement-emitter architecture, the gating layer, and the `compose.py` LLM call. SS2 modifies `compose.py` and `state_readers.py`; it does NOT touch the gating or emit layers.
- **QM1 (#1292)** — chronicle quality exporter. Provides the per-emission grounding-coverage signal SS2 cycles measure against.
- **QM2 (#1293)** — impingement bus sampler. Provides the novelty-score trajectory SS2 cycles measure against.
- **Memory: `feedback_grounding_exhaustive`** — "every move is grounding or outsourced-by-grounding." This is the architectural axiom cycle 1 takes literally.
- **Memory: `feedback_director_grounding`** — Director stays on the grounded model under speed pressure. SS2 emissions follow the same constraint: no model downgrade for latency.
- **Memory: `feedback_no_expert_system_rules`** — "behavior emerges from impingement→recruitment→role→persona; hardcoded cadence/threshold gates are bugs." SS2 must preserve emergent dynamics; rubric-driven changes go into the prompt + grounding sources, not into hardcoded thresholds.
- **v5 plan synthesis** — `~/.cache/hapax/relay/context/2026-04-24-v5-plan-synthesis.md` §2.1 places SS2 in the alpha lane as P0 self-sufficiency research.
