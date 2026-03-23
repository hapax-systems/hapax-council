# Voice Grounding Research State

**Last updated:** 2026-03-22 (session 10 — pre-testing readiness + context-as-computation research)
**Update convention:** After any session with research decisions or implementation progress, update this file before ending.

## Position (one paragraph)

This project implements Clark & Brennan's (1991) conversational grounding theory in a production voice AI. Current voice AI systems use profile-gated retrieval (ChatGPT Memory, Gemini, Mem0); none implement Clark's contribution-acceptance cycle. Shaikh et al. (ACL 2025) report frontier LLMs score 23.23% on grounding tasks. Shaikh et al. (NAACL 2024) identify RLHF as a factor suppressing grounding acts.

## Current Phase

- **Cycle 1:** COMPLETE (pilot, 37 sessions, BF=3.66 inconclusive, word overlap metric replaced)
- **Cycle 2:** READY FOR BASELINE DATA COLLECTION
  - All research complete (28 agents across 4 rounds, 80+ citations)
  - Implementation: **Batches 1-4 COMMITTED** + **wiring gaps closed** (PR #236, 85 tests)
  - **GQI-stimmung coupling** implemented (10th dimension, weight 0.3, cross-process via shm)
  - **Pre-registration updated** with 3+1 package, new DVs, effect size calibration
  - **Repository optimization** complete (session 3)
  - **Environment audited** (session 4): 10 audit agents, resource hogs killed, worktrees cleaned, configs corrected
  - **CI/CD + PII hardened** (session 5): Full CI pipelines on all 6 repos, SDLC pipeline consistency audit, 5 audit passes removing operator PII from tracked files + git history, speaker labels refactored ("ryan"→"operator"), gitleaks custom rules deployed, cockpit-mcp renamed to hapax-mcp
  - **cockpit→logos rename** (session 6): `cockpit/` directory → `logos/` across council (PR #263) and officium (PR #46). All Python imports, pyproject.toml scripts/extras, Docker configs, CI workflows, systemd units, cache paths updated. hapax-mcp env var `COCKPIT_BASE_URL` → `LOGOS_BASE_URL` (with fallback). ~345 files changed, 5788 tests pass
  - **RESEARCH/R&D mode isolation** (session 7): Mechanical enforcement separating experiment work from development. Pre-commit hook + CI workflow freeze experiment paths during active phases. Working mode switch (`hapax-working-mode research|rnd`) with pre-flight checklist, relay protocol integration, Langfuse environment tagging, waybar/fish visual indicators. Deviation workflow for frozen-path changes. See `experiment-freeze-manifest.txt`
  - **Experiment config** set to Phase A baseline (continuity-v2)
  - **SESSION-PROTOCOL** updated with selective flags (replaces monolithic volatile_lockdown)
  - Remaining: ORCID, OSF project, pre-registration filing, Zenodo, GitHub Pages
- **Cycle 3:** NOT STARTED (contingent on Cycle 2 results; may require fine-tuned model if RLHF anti-pattern binds)

## What Was Built (Batches 1-4)

### Batch 1 — Foundation
- `_EXPERIMENT_PROMPT` in persona.py (~200 tokens, no tools)
- `_EXPERIMENT_STYLE` in conversational_policy.py (~30 tokens, dignity floor + minimal style)
- `ThreadEntry` dataclass: verbatim operator text (preserves conceptual pacts), acceptance signal, grounding state, repair flag, seeded flag
- `_extract_substance()`: no more `split(",")[0].split(".")[0][:60]` — preserves full text, max 100 chars
- `_render_thread()`: tiered compression (recent=full+quotes, middle=referring expression, oldest=keyword)
- Thread cap: 10 entries (down from 15, Lost in the Middle research)
- Phenomenal context: stimmung-only gating for experiment
- Salience: prompt block stripped, router still computes mechanically
- Env context: presence only in experiment mode

### Batch 2 — Grounding Loop
- `grounding_ledger.py` (NEW, ~315 lines):
  - DU state machine: PENDING → GROUNDED/REPAIR-1/REPAIR-2/ABANDONED/CONTESTED/UNGROUNDED
  - Concern-aware repair thresholds (Clark's "sufficient for current purposes"): high concern + low GQI → require ACCEPT (0.9), low concern + high GQI → IGNORE is fine (0.3)
  - GQI computation: 50% EWMA acceptance + 25% trend + 15% consecutive negatives + 10% engagement
  - 2D effort calibration: activation × (1 - gqi_discount) → EFFICIENT/BASELINE/ELABORATIVE with hysteresis
  - Strategy directives injected into VOLATILE band per turn
- Pipeline wired: acceptance feeds ledger with concern_overlap, DU registered per response, directive + effort level injected

### Batch 3 — Memory Integration
- `_load_seed_entries()`: returns list[ThreadEntry] from Qdrant, prioritizes unresolved DUs
- Thread seeding: 2-3 prior session entries with `[PRIOR]` markers
- Age-out: seeded entries compress at 6 current entries, drop at 11
- Persist: unresolved DUs and grounding_state stored in Qdrant payload
- Experiment flags loaded before prompt construction (was after — bug)

### Batch 4 — Observability
- `_score_monologic()`: detects RLHF anti-pattern (monologic=1.0 vs dialogic=0.0)
- `score_directive_compliance()`: did model follow the grounding directive?
- Selective lockdown: grounding directive/effort NOT locked even with volatile_lockdown
- Salience router computes in both phases (activation/concern available mechanically)

## Critical Decisions (with reasoning)

1. **3+1 package**: 3 treatment (thread + drop + memory) + 1 diagnostic (sentinel). WHY: sentinel tests retrieval not grounding; including it as treatment threatens construct validity (Ward-Horner & Sturmey 2010).

2. **Refine BEFORE test**: gestalt effects require properly composed components. WHY: "testing an incomplete system for emergence is playing 2 of 4 notes."

3. **BEST over beta-binomial**: continuous data requires t-distributed likelihood. WHY: beta-binomial wrong for continuous metrics; autocorrelation inflates BF (Shadish et al. 2013 mean r=0.20).

4. **turn_pair_coherence** replaces context_anchor_success. WHY: word overlap penalizes abstraction/paraphrasing; qualitative grounding effects invisible to prior metric.

5. **Always CAPABLE**: intelligence is last thing shed. Salience router becomes effort calibrator, not model selector.

6. **Acceptance must actuate**: classified but not fed back = 1/3 of Clark's cycle. Closing the loop is the bridge from anchoring to grounding.

7. **Conceptual pacts**: preserve operator's verbatim terminology in thread. WHY: Metzing & Brennan 2003 — pact violations maximally costly with single known partner.

8. **Bands = grounding substrate**: STABLE band = discourse record, VOLATILE band = turn-specific directives, stimmung = GQI signal, salience = effort calibrator, concern graph = "sufficient for current purposes."

9. **Every token justified**: system prompt stripped to ~800-1000 tokens for experiment. No tool descriptions, no profile digest, no environmental modulation.

10. **GQI as stimmung dimension**: 10th dimension, unidirectional (no circular dependency). GQI reads conversation signals only, feeds stimmung, stimmung renders in Layer 1.

## Session 10 (2026-03-22): Pre-Testing Readiness + Context-as-Computation

- **Full environment audit** (10 agents): operations, methodology, research basis, data pipeline, development state, system stability, resource contention, lifecycle management, relay protocol, experiment freeze enforcement. All green except resource hogs (killed) and working mode (set to RESEARCH).
- **Context-as-Computation research** (4 agents): Established mechanistic justification for multi-band architecture. Prompt is a program (Von Oswald 2023, mesa-optimization). Position determines representation (primacy tail proven 2026). Entrainment heads elevate context-seen tokens (ACL 2025 Outstanding Paper). Acceptance signals function as reward for in-context RL. Function vectors compose additively. RLHF correction angle: we restore training-suppressed grounding capability at runtime.
- **Decision: black box first, white box if warranted.** Cycle 2 measures behavioral outputs. Internal model investigation (attention patterns, SAE features, representation similarity) deferred to Cycle 3+ and only if Cycle 2 shows positive effect.
- **New research document**: `proofs/CONTEXT-AS-COMPUTATION.md` + lab journal entry. DEVIATION-003 filed.
- **Methodology gaps identified**: stats.py still implements beta-binomial (not BEST); must fix before Phase B analysis. OSF pre-registration not yet filed. Cycle 1/2 data not segregated.

## Open Questions

- A-B-A vs A-B-A-B design (Barlow: reversal inappropriate for learning interventions)
- Effect size target from Cycle 2 baseline data
- RLHF anti-pattern: prompted Opus sufficient or fine-tuning needed? (Cycle 3 decision)
- White-box investigation: local model parallel experiment for mechanistic interpretability (Cycle 3+)
- stats.py needs BEST implementation before Phase B analysis
- 13 L8-L9 test failures (wake word debounce) — pre-existing, not from grounding changes
- Verify Shaikh et al. ACL 2025 citation accuracy (23.23% figure, venue)

## Operator Action Items (from session 3 research)

1. Get ORCID → update CITATION.cff files
2. Create OSF project → link GitHub repos
3. File pre-registration on OSF (comprehensive template + SCED addendum)
4. Connect Zenodo to GitHub → enable for council + constitution
5. Enable GitHub Pages for lab journal
6. Verify Shaikh et al. citation accuracy

## Key Documents (read to reconstruct full context)

| Document | Tokens | Content |
|----------|--------|---------|
| `THEORETICAL-FOUNDATIONS.md` | ~8K | Literature review: Clark, Traum, Brennan, SCED methodology, LLM architectures |
| `REFINEMENT-RESEARCH.md` | ~5K | 8 research streams → refined model design |
| `PACKAGE-ASSESSMENT.md` | ~4K | Component analysis, 2x2 matrix, SCED methodology |
| `POSITION.md` | ~3K | Positioning vs profile retrieval, 5 failure modes |
| `WHY-NO-ONE-IMPLEMENTED-CLARK.md` | ~3K | 35-year gap analysis: obstacles, misconceptions |
| `CYCLE-2-PREREGISTRATION.md` | ~3K | Experiment design: ABA, BEST, HDI+ROPE, session protocol |
| `CYCLE-1-PILOT-REPORT.md` | ~2K | Methods, results, 6 deviations, limitations |
| `BASELINE-ANALYSIS.md` | ~2K | 17 sessions, 8 patterns |
| `REFINEMENT-DECISION.md` | ~1K | Decision to refine before testing |
| `SYSTEM-CLEANUP-DECISION.md` | ~1K | Strip to research essentials directive |
| `REPO-OPTIMIZATION-RESEARCH.md` | ~12K | Repository optimization research (140+ sources, 6 streams) |
| Plan: `shimmering-growing-lollipop.md` | ~3K | Implementation batches 1-4 |

## Research Infrastructure (added session 3)

| Artifact | Location | Purpose |
|----------|----------|---------|
| Research compendium | `research/` | TIER/Psych-DS directory structure |
| Theory traceability | `research/THEORY-MAP.md` | Theory → code → test matrix |
| Experiment phase | `experiment-phase.json` | CI phase-gating state |
| CITATION.cff | repo root | Academic citation metadata |
| Handoff doc | `~/gdrive-drop/research-infrastructure-handoff.docx` | Operator action items |
| Freeze manifest | `experiment-freeze-manifest.txt` | Frozen paths during active experiment |
| Deviation records | `research/protocols/deviations/` | Changes to frozen paths with justification |
| Working mode | `~/.cache/hapax/working-mode` | RESEARCH or RND operator state |
| Mode switch | `scripts/hapax-working-mode` | Pre-flight checklist + relay + ntfy + waybar |
| Freeze hook | `scripts/experiment-freeze-check` | Pre-commit enforcement of frozen paths |
| CI freeze gate | `.github/workflows/experiment-freeze.yml` | PR-level freeze enforcement |

## Session 5–7 Infrastructure Changes (2026-03-21)

All infrastructure-only. No changes to experiment code, grounding theory, or research design.

- **Session 5 (CI/CD + PII)**: CI pipelines on all 6 repos. Pinned GitHub Actions. PII removal (5 passes): operator name from docs/code/tests, /home/hapax/ paths, speaker labels "ryan"→"operator", family references, coordinates. Custom .gitleaks.toml. PII guard hook. cockpit-mcp → hapax-mcp rename.
- **Session 6 (cockpit→logos)**: `cockpit/` → `logos/` directory rename across council + officium. All imports, configs, Docker, systemd, CI updated. hapax-mcp env var fallback. ntfy topic stays "cockpit" (external).
- **Session 7 (mode isolation)**: Five-layer RESEARCH/R&D isolation: (1) code freeze via manifest + pre-commit + CI gate, (2) data isolation via Langfuse environment tagging, (3) working mode file + Python module, (4) relay protocol integration, (5) waybar + fish prompt visual indicators. Deviation workflow for frozen-path changes. Pre-flight checklist enforces zero stale branches before mode switch.
- **Session 8 (systemd overhaul)**: Reverted /home/operator PII scrub (incomplete, fragile symlink dependency). Normalized 168 path references across 41 files. Imported 51 untracked systemd units + 8 drop-in override directories (coverage 47%→97%). Reconciled 4 drifted units: llm-stack (--profile full), logos-api (merged 3 versions, retired drop-in), rag-ingest (Type=simple daemon), audio-recorder (pw-record pipeline). Fixed health-watchdog bug (exit code 2 discarded reports). Cleaned broken symlinks, debris, stale branches. officium-api.service now tracked in hapax-officium repo. PR #264 merged, all CI green.
- **Session 9 (drift + cockpit rename)**: Tuned drift detector to split headline count: real drift vs doc hygiene (coverage-gap, missing-section, etc). Drops reported items from 181→~20. Completed cockpit→logos rename across all 3 repos (~80 files): `COCKPIT_API_URL`→`LOGOS_API_URL`, `COCKPIT_WEB_DIR`→`LOGOS_WEB_DIR` in shared/config.py + all importers, docstrings, Tauri commands, vscode extension, specs, cache paths. Fixed Qdrant collection count (4→8), vscode port (8095→8051/8050), boundary doc sync (constitution←officium). Fixed AgentSummary to handle flat array API response (was showing "0 agents"). Fixed studio-compositor crash (PyGObject missing after Python 3.14 upgrade — `uv pip install PyGObject`). PR #265 merged, all CI green.

## Operator Research Preferences

- Strip system to research essentials only
- Independent research agents per major concern
- Substrate independence: phenomena are implementation-agnostic
- Composable perspectives: decomposable, independently tappable
- Always CAPABLE model tier; willing to wait if justified
- Continuous cognitive loop, not request-response state machine
- No stale branches; PR completed work immediately
- Scientific register in all documentation; no rhetorical valence
