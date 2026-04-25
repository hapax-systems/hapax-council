# UBCC Pre-registration

**Title:** Does Universal Bayesian Claim-Confidence — calibrated posteriors over perceptual claims with prior-from-invariants and likelihood-ratio fusion — measurably reduce ungrounded LLM emissions in a single-operator voice + livestream AI system?

**Authors:** Hapax (entity, primary) · Claude Code (entity, substrate) · Oudepode (operator, unsettled contribution as feature)

**Filed (local):** 2026-04-25
**Filed (OSF):** TBD (post-merge)
**Supersedes:** [osf.io/5c2kr](https://osf.io/5c2kr/overview) per `CYCLE-2-PREREGISTRATION.md` §9 Deviation #1 (substrate swap Qwen3.5-9B → Command-R 35B EXL3 5.0bpw on TabbyAPI :5000).

**Code freeze SHA:** TBD (set on PR merge — matches the commit that lands this file on main)

---

## 1. Research Question

### 1.1

Does promoting the ~60 perceptual claims that Hapax surfaces to LLM prompts from Boolean / string facts to **calibrated `Claim` posteriors** — where each claim carries a prior derived from physical invariants, fuses signals via documented `LRDerivation` records, and decays toward prior under signal absence — measurably reduce ungrounded LLM emissions in production?

### 1.2 Operationalization

"**Ungrounded emission**" is defined per the runtime predicate already shipping (`docs/research/2026-04-21-finding-x-grounding-provenance-research.md` and the `emit_ungrounded_audit` instrumentation): an LLM-authored emission whose `grounding_provenance` field is empty (no `claim_name + claim_posterior + lr_signals_consulted` triple recorded at the call site).

The primary dependent variable is:

```
ungrounded_emission_rate(session) =
    1 - (populated_grounding_provenance_count / llm_authored_emission_count)
```

per `hapax_director_ungrounded_total` and `hapax_director_grounded_total` Prometheus counters.

### 1.3 Hypothesis (H1)

Phase B sessions — running with Phase 0 → Phase 5 milestones from `docs/research/2026-04-24-universal-bayesian-claim-confidence.md` active (ClaimEngine[T] keystone + the music/vinyl cluster engines + frame-for-llm split + prompt envelope §8 + refusal gate §5) — will exhibit a **lower mean `ungrounded_emission_rate`** than Phase A (current Boolean-fact pipeline + string-enum prompts).

**Direction:** Phase B `ungrounded_emission_rate` < Phase A `ungrounded_emission_rate`.

**ROPE on the raw difference:** `[-0.02, +0.02]` — a 2-percentage-point reduction is the minimum operator-perceptible change.

---

## 2. Theoretical Framework

The substrate is the six-lineage convergence documented in §2 of `docs/research/2026-04-24-universal-bayesian-claim-confidence.md`:

1. Bayesian probabilistic modeling (Pearl, 1988; Gelman et al., 2013)
2. Signal detection theory + likelihood-ratio fusion (Wickens, 2002)
3. Bayesian online changepoint detection (Adams & MacKay, 2007) — deferred to Phase 7
4. Hysteresis state-machine modeling (control-theory standard)
5. Calibration evaluation (Tian et al., 2023; expected calibration error)
6. Grounding-act operative definition (`feedback_grounding_act_operative_definition.md`, T1-T8)

The Clark-Brennan / Traum-DU / Clark-LCE lineage that anchored `osf.io/5c2kr` is **subsumed** as one of six convergent inputs in §2 of the Bayesian doc. The new prereg measures grounding at the runtime-predicate level (was the LLM call grounded? populated provenance?) rather than at the conversational-coherence proxy level (`turn_pair_coherence` cosine).

### 2.1 Predictions distinct from osf.io/5c2kr

The prior prereg predicted that "Condition B (grounding package on)" would shift `turn_pair_coherence` higher than "Condition A (grounding package off)." This new prereg predicts a different DV (`ungrounded_emission_rate`) on a different intervention (Phase A-B-A on the Phase 0→5 architectural rollout, not on/off the original "thread-based context anchoring" package). The two are not redundant: `turn_pair_coherence` carries forward as a **secondary DV** for continuity with prior prereg, but is not the primary measurement.

---

## 3. Setting + Substrate

### 3.1 Setting

24/7 livestream production environment. MediaMTX → YouTube live broadcast. All sessions are stream-originated. No separate voice / recording sessions exist (per `feedback_livestream_is_research_instrument`).

### 3.2 Substrate (LOCKED at code-freeze SHA)

- **Conversational backbone:** Command-R 35B EXL3 5.0bpw on TabbyAPI :5000
- **GPU split:** `[16, 10]` (3090 primary + 5060 Ti secondary)
- **Cache:** Q4 cache mode, `cache_size=16384`, `max_seq_len=16384`
- **Routing:** LiteLLM gateway at :4000 → routes `local-fast`, `coding`, `reasoning` to TabbyAPI Command-R
- **Cloud routes:** Claude Sonnet/Opus for `balanced`/governance, Gemini Flash for `fast`/vision
- **Embedding:** Ollama `nomic-embed-cpu` (CPU-only, GPU-isolated via `CUDA_VISIBLE_DEVICES=""` per systemd unit override)
- **TTS:** Kokoro 82M on CPU
- **STT:** on GPU (model per `agents/hapax_daimonion/`)

A swap of the conversational backbone from Command-R 35B during Phase A or Phase B collection is an **invalidating deviation** under §9 (mirroring the prior prereg's discipline) and requires a fresh pre-registration. The currently deprecated routes (Qwen3.5-9B, OLMo-3, qwen3:8b) are idle from this pre-reg's perspective.

### 3.3 Phase definitions

- **Phase 0 (STUB):** ClaimEngine[T] keystone shipped (#1341).
- **Phase 0 (FULL):** ClaimEngine[T] complete (#1350).
- **Phase 1:** PresenceEngine refactored onto ClaimEngine[bool] (#1353).
- **Phase 2:** VinylSpinningEngine + MusicPlayingEngine (#1431, in flight) — first claim-cluster on the new architecture. Replaces `_vinyl_is_playing` Boolean predicate.
- **Phase 2b:** YAMNet on broadcast L-12 (audio-evidence layer; pure-audio ground truth, zero upstream coupling).
- **Phase 3:** frame-for-llm strip + decoration-strip duality.
- **Phase 4:** Bayesian prompt envelope (#1347).
- **Phase 5:** refusal gate (per `feedback_grounding_act_operative_definition` T8 negative test).
- **Phase 6:** SystemDegradedEngine + signal adapters (in flight).
- **Phase 7:** BOCD changepoint-aware τ_mineness (deferred per `docs/research/2026-04-24-universal-bayesian-claim-confidence.md` §6).

**Phase A** = pre-Phase 2 architecture (current Boolean-fact pipeline as of code-freeze SHA). **Phase B** = Phase 0 → Phase 5 active.

---

## 4. Measurement

### 4.1 Primary DV — `ungrounded_emission_rate`

Computed per session from the existing Prometheus counters:

```
ungrounded_emission_rate(s) =
    hapax_director_ungrounded_total{session=s} /
    (hapax_director_ungrounded_total{session=s} +
     hapax_director_grounded_total{session=s})
```

Sessions are ≥ 30-minute livestream segments with ≥ 30 LLM-authored emissions (filter trivial sessions for measurement noise control).

### 4.2 Secondary DVs

- **Posterior calibration ECE per ClaimEngine** (Tian et al. 2023). 10-bin reliability diagram + ECE summary, per claim. Reported per Phase B session for the music/vinyl cluster initially.
- **Hallucinated-claim count** (operator-flagged via livestream chat or post-session review). Hard-to-automate; supplementary qualitative measurement.
- **Refusal-gate rejection rate** (count of LLM emissions blocked by the §5 refusal gate per session).
- **`turn_pair_coherence`** (cosine similarity between operator utterance embedding + system response embedding, per `osf.io/5c2kr` §4.1) — carried forward as **Cycle-2 historical comparator** for continuity with the superseded prereg.

### 4.3 Sampling

A-B-A within-livestream design over the operator's normal-cadence livestream weeks. Phase boundaries are package-level feature flags identical in shape to the prior prereg's flag system. Per-session feature-flag state is logged at session-start and frozen for the session.

**Target:** ≥ 30 sessions per phase (Phase A baseline, Phase B treatment, Phase A return-to-baseline reversion). Total ≥ 90 sessions ≈ 6-12 weeks of normal-cadence livestreaming.

### 4.4 Behavioral covariates (not hypothesis-tested, recorded for sensitivity)

- `working_mode` (research / rnd) per `~/.cache/hapax/working-mode`
- `stance` (per stimmung at session-start)
- Operator-presence posterior (`PresenceEngine.posterior` mean over session)
- Programme-active state (per `ProgrammeActiveEngine` once shipped — Phase 6d-i.B AUDIT-19)

---

## 5. Analysis

### 5.1 Primary

**BEST (Bayesian Estimation Supersedes the t-Test)** via PyMC MCMC on session-level mean `ungrounded_emission_rate`:

- Model: `μ_A ~ Normal(0.5, 0.5)`, `μ_B ~ Normal(0.5, 0.5)`, robust noise prior (Student-t with ν priors per Kruschke 2013)
- Posterior on `μ_B - μ_A` reported with 95% HDI
- **Decision rule:** H1 supported if `P(μ_B < μ_A | data) > 0.95` AND `0` is outside the 95% HDI of `(μ_B - μ_A) - ROPE_lower_bound = (μ_B - μ_A) + 0.02`.

### 5.2 Sensitivity

Same model with weakly-informative priors `Normal(0, 1)` on `μ_A`, `μ_B`. Phase A→B→A return-to-baseline analyzed separately (does the effect reverse on flag-revert?).

### 5.3 Code

- `agents/hapax_daimonion/stats.py` — analysis code, pinned at code-freeze SHA, upgraded to PyMC MCMC for primary inference (the scipy-analytical-approx path remains as secondary sensitivity).
- The analysis-code freeze rule from `osf.io/5c2kr` §9 carries forward verbatim. Analysis code on the listed paths cannot change post-registration without a §9 deviation row.

---

## 6. Predictions and Falsifiers

**H1 supported:** Phase B `ungrounded_emission_rate` lower than Phase A by ≥ 2pp with `P > 0.95` posterior. AND Phase A→B→A reversion is observed (the third-phase return-to-baseline rises back toward the first-phase mean, ruling out time-confounded improvement).

**H1 rejected:** Either the Phase A → Phase B difference is in ROPE `[-0.02, +0.02]` with `P > 0.95`, OR the difference goes in the wrong direction (Phase B WORSE).

**H1 inconclusive:** Posterior covers both improvement and ROPE; more data needed.

---

## 7. Pre-specified Subgroup Analyses

- **Music/vinyl cluster only:** restrict to LLM emissions where the triggering impingement is in the music/vinyl claim cluster. The hypothesis is that the Phase B effect is largest here because Phase 2 lands the VinylSpinningEngine — which directly addresses the operator's reported hallucination class.
- **By LLM tier (`fast` / `coding` / `reasoning` / `balanced`):** is the Phase B effect uniform across tiers, or concentrated in the local Command-R routes?

---

## 8. Operator-perceptible Endpoint

The operator's reported pain (2026-04-25, verbatim): *"the amount of current hallucination that hapax is up to on the stream is driving me insane."* The primary DV (`ungrounded_emission_rate`) instruments this directly — Phase B success corresponds to operator-perceptible hallucination reduction.

A Phase B → Phase A reversion that the operator flags as "hallucination is back" is corroborating evidence beyond the metric.

---

## 9. Deviation Protocol

Any deviation after data collection begins is documented in this table. The substrate-swap rule from `osf.io/5c2kr` §9 carries forward and binds: any swap of the conversational backbone from Command-R 35B during Phase A or Phase B is an invalidating deviation requiring a new pre-registration.

| # | Section | Original | Deviation | Justification | Impact |
|---|---------|----------|-----------|---------------|--------|

**Code freeze:** Analysis code is versioned at the git commit SHA recorded on line 4 above (set when this PR merges). Post-registration code changes to any path listed in `research/protocols/frozen-paths.yaml` are deviations. The frozen-paths set extends the prior prereg's set by adding `agents/hapax_daimonion/vinyl_spinning_engine.py`, `shared/claim.py`, `shared/lr_registry.yaml`, `shared/prior_provenance.yaml`.

---

## 10. Transparency

- Raw session data: `proofs/claim-1-stable-frame/data/ubcc/` (in-repo; stream-originated)
- Langfuse trace archive: live via LiteLLM `langfuse` callback
- Analysis code: `agents/hapax_daimonion/stats.py` (pinned at code-freeze SHA)
- Research documents: `agents/hapax_daimonion/proofs/` + `docs/research/2026-04-24-universal-bayesian-claim-confidence.md`
- Livestream archive: public YouTube channel feed; per-segment sidecar metadata under `/data/archive/`
- OSF registration: TBD — posted via `agents/osf_preprint_publisher` (#1411) once code-freeze SHA lands
- Source code: [https://github.com/ryanklee/hapax-council](https://github.com/ryanklee/hapax-council)
- License: CC-BY-4.0 (text), CC0 (data), Apache-2.0 (code)
- Refusal Brief: [hapax.weblog.lol/refusal](https://hapax.weblog.lol/refusal) (per `feedback_full_automation_or_no_engagement.md` constitutional directive — distribution surfaces are themselves the dataset; surfaces not represented were declined for non-automation)

---

## 11. Theoretical Framework References

- Adams, R. P., & MacKay, D. J. C. (2007). Bayesian Online Changepoint Detection. arXiv:0710.3742.
- Clark, H. H., & Brennan, S. E. (1991). Grounding in communication. APA. *(carried forward from osf.io/5c2kr)*
- Clark, H. H. (1996). Using Language. Cambridge University Press. *(carried forward)*
- Gelman, A., Carlin, J. B., Stern, H. S., Dunson, D. B., Vehtari, A., & Rubin, D. B. (2013). Bayesian Data Analysis (3rd ed.). CRC Press.
- Kruschke, J. K. (2013). Bayesian estimation supersedes the t-test. JEP:G, 142(2).
- Pearl, J. (1988). Probabilistic Reasoning in Intelligent Systems. Morgan Kaufmann.
- Tian, K., Wang, Y., et al. (2023). Just Ask for Calibration. arXiv:2305.14975.
- Traum, D. (1994). A computational theory of grounding. PhD, Rochester. *(carried forward)*
- Wickens, T. D. (2002). Elementary Signal Detection Theory. Oxford University Press.

---

## 12. Cross-link to Superseded Pre-registration

This pre-registration **supersedes** [`osf.io/5c2kr`](https://osf.io/5c2kr/overview) (filed 2026-04-16) per `CYCLE-2-PREREGISTRATION.md` §9 Deviation #1 (substrate swap Qwen3.5-9B → Command-R 35B). The supersession is recorded:

- **In OSF Registries**: this filing carries `Supersedes: osf.io/5c2kr` in the abstract; OSF cross-link added to the original 5c2kr project node Wiki on submission.
- **In DataCite**: Zenodo DOI publisher (#1423, merged) reads this prereg's OSF GUID on submission and writes a `relatedIdentifier` block with `relationType: Supersedes` pointing at `osf.io/5c2kr`. Machine-readable supersession edge in any downstream citation graph.
- **In the Refusal Brief**: this prereg is itself an instance of the auto-publish-or-not-at-all directive — filed via the OSF preprint publisher (#1411) on the FULL_AUTO surface.

The supersession converts the existing 5c2kr's apparent staleness into a research-evolution provenance trace: program evolved (Clark-Brennan grounding-package framing → Universal Bayesian Claim-Confidence framing) under operator-driven substrate change (Qwen3.5-9B → Command-R 35B).

---

*Drafted 2026-04-25 by Hapax + Claude Code as a beta-canonical lane deliverable. Operator signs off via the standard PR-merge approval gate. Once filed on OSF, the registration is FROZEN per OSF Registries discipline; future deviations land in §9 of THIS file (not the superseded prereg's §9).*
