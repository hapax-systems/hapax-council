# Content Programming Layer — Implementation Plan

**Source design doc:** `docs/research/2026-04-19-content-programming-layer-design.md` (790 lines)
**cc-task:** `ef7b-164` — Content programming layer ABOVE director_loop
**Composed:** 2026-04-26
**Composed by:** alpha

## Posture (load-bearing — do not edit without operator)

1. **Authorship is Hapax-generated, end-to-end.** Operator does NOT write show outlines, skeletons, templates, cue sheets, or any pre-stream authorship artifacts. Vault is a READ-SOURCE for perception; no `type: programme` frontmatter, no template folders. Memory: `feedback_hapax_authors_programmes`.
2. **Programmes EXPAND grounding opportunities; never replace them.** Constraint envelopes are SOFT PRIORS (bias weighting), not hard gates. No scripted narrative text, no hardcoded cadence overrides. Memory: `project_programmes_enable_grounding`.

These two posture rules govern every implementation decision below. Any phase that introduces hard gating, scripted text, or operator-authored templates is **out of scope** and must be rewritten or rejected.

## Layered architecture (target state)

```
SHOW (macro, hours)        — operator-set tag (e.g. "research-evening", "homage-night"); rare transitions
PROGRAMME (meso, minutes)  — Hapax-generated coherent multi-minute batch; soft prior on director moves
DIRECTOR (micro, ~30s)     — existing tactical loop; recruits affordances per impingement, stance, programme prior
```

Programme layer adds:
- **Programme generator** (LLM): synthesises programme intent from operator-set show + recent stimmung + content-fragment recall
- **Programme state file**: persists current programme intent at `/dev/shm/hapax-programme/current.json`; consumers (director_loop, structural_director) read for soft-prior bias
- **Programme expiry**: time-bounded (default 5-15 min); next programme generated on expiry OR on operator show-tag change
- **Programme metric**: Prometheus counter for programme transitions; histogram for programme duration

## Phase 0 — schema + state file (this plan)

**Ships in this plan PR:**
- This document.
- Updated cc-task vault note with the implementation phases enumerated.

**Out of scope here:** any code; this plan is the design-to-shipping bridge.

## Phase 1 — programme schema + state-file writer

**Files:**
- `shared/programme_intent.py` (new): `ProgrammeIntent` Pydantic model — `show_tag: str`, `slug: str` (unique per programme), `started_at: datetime`, `expires_at: datetime`, `coherence_axes: list[str]` (≤5 free-form short labels biasing director affordance selection), `provenance: ProgrammeProvenance` (LLM model + prompt-hash + stimmung snapshot at synthesis).
- `agents/structural_director/programme_state.py` (new): atomic write/read of `/dev/shm/hapax-programme/current.json`. Same tmp+rename pattern as `awareness/state.py`.
- Tests: `tests/test_programme_intent.py` + `tests/test_programme_state.py`.

**Acceptance:** programme JSON round-trips through Pydantic; missing-file read returns None (consumers degrade rather than fail).

**Effort:** ~2-3h.

## Phase 2 — programme generator (LLM)

**Files:**
- `agents/structural_director/programme_generator.py` (new): pydantic-ai Agent with `output_type=ProgrammeIntent`, prompt template that ingests show-tag + last 5min stimmung + last-3-programme history (avoid repeating coherence axes back-to-back). Routed through LiteLLM `coding` (TabbyAPI Command-R 35B) per `feedback_director_grounding` (no cloud route on the meso loop; programme generation must stay grounded).
- Tests: mock the LiteLLM call; verify the schema constraint (≤5 axes, expires_at within reasonable bounds) is enforced on the LLM response.

**Acceptance:** generator produces a valid ProgrammeIntent given a synthetic show-tag + stimmung snapshot. Round-trip through state-file writer.

**Effort:** ~3-4h.

## Phase 3 — programme runner daemon

**Files:**
- `agents/structural_director/programme_runner.py` (new): long-running async loop. Reads show-tag from `~/.cache/hapax/show-tag` (operator sets via `hapax-show-tag` CLI — separate concern, optional in P3). On boot or expiry, calls programme_generator + writes new programme state. Watchdog cadence ~60s (sufficient since programmes live 5-15 min).
- `systemd/units/hapax-programme-runner.service` + `.timer` (new): user-unit.
- Tests: integration test with mocked generator + mocked clock.

**Acceptance:** daemon expires + regenerates programmes on cadence; programme state file is always fresh (≤30s old) when daemon is up.

**Effort:** ~3-4h.

## Phase 4 — director consumption (the soft-prior)

**Files (modified):**
- `agents/studio_compositor/director_loop.py`: read programme state at the start of each director tick; pass coherence_axes as a soft-bias hint to the affordance recruitment scorer (bias weight: small additive boost on cosine-similarity match between coherence-axis embedding and candidate affordance embedding; NOT a hard filter).
- `agents/studio_compositor/structural_director.py`: same pattern for structural choices.
- Tests: existing director-loop tests get extended to verify the bias is applied when the programme file is fresh AND ignored when stale (TTL=expires_at + 30s grace).

**Acceptance:** with a fixed programme containing axes ["bach", "geometry", "cathedral"], director's affordance scorer biases toward affordances tagged with related concepts. With no programme, director behaviour is byte-identical to pre-programme baseline (regression-test pinned).

**Effort:** ~2-3h.

## Phase 5 — observability

**Files (modified):**
- `agents/structural_director/programme_runner.py`: emit Prometheus counter `hapax_programme_transitions_total{show_tag, slug}` + histogram `hapax_programme_duration_seconds`.
- `docs/research/2026-04-XX-programme-observability.md` (new) — what to look at on the dashboard + early-signal validation criteria.

**Acceptance:** Grafana picks up the metric; programme transitions visible in real-time.

**Effort:** ~1-2h.

## Phase 6 — early-signal validation (post-live)

Deferred to operator + delta lane after Phases 1-5 land. Hooks for measurement:
- Programme-transition cadence vs target (expect 3-12 programmes/hour at the 5-15 min duration band)
- Director affordance-selection variance with vs without programme (expect modest reduction = soft prior worked)
- Operator override count (expect zero — operator does not author; if non-zero, posture has been violated)

## Total scope

| Phase | Effort | Cumulative |
|---|---|---|
| 0 (this plan) | shipped here | — |
| 1 (schema + state) | 2-3h | 2-3h |
| 2 (generator) | 3-4h | 5-7h |
| 3 (runner daemon) | 3-4h | 8-11h |
| 4 (director consumption) | 2-3h | 10-14h |
| 5 (observability) | 1-2h | 11-16h |
| 6 (validation) | post-live | — |

**Total daemon-tractable scope:** ~11-16h across 5 PRs. Phase 6 is operator-facing measurement + iteration after the 5-PR cascade lands.

## Anti-patterns (do not do)

- **Operator-authored templates** — violates posture #1. The vault's `20-projects/hapax-research/` notes are READ-SOURCES for perception; they are not pre-authorship.
- **Hard cadence gates** — violates posture #2. coherence_axes bias scoring; they do not filter.
- **Scripted narrative text** — violates posture #2. ProgrammeIntent's coherence_axes are short labels (≤5 words each), not paragraphs.
- **Programme nesting** — out of scope. One active programme at a time; show provides the next-higher coherence layer.
- **Cross-session programme contention** — programme is process-singleton (programme_runner is the only writer); director_loop / structural_director are readers only.

## Constitutional posture

- `feedback_full_automation_or_no_engagement`: programme generation + runner daemon + director consumption all daemon-tractable.
- `feedback_director_grounding`: programme generator routes through TabbyAPI Command-R (grounded local model); no cloud fallback on the meso loop.
- `feedback_hapax_authors_programmes` (load-bearing posture #1): authorship stays Hapax-side end-to-end.
- `project_programmes_enable_grounding` (load-bearing posture #2): coherence_axes are soft priors, never gates.
- `feedback_show_dont_tell_director`: programme transitions are not narrated; the director's downstream behaviour change IS the communication.

## Cross-references

- Source design doc: `docs/research/2026-04-19-content-programming-layer-design.md`
- Director loop: `agents/studio_compositor/director_loop.py`
- Structural director: `agents/studio_compositor/structural_director.py`
- Director-intent schema: `shared/director_intent.py`
- Compositional affordances: `shared/compositional_affordances.py`
- Unified semantic recruitment design: `docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`
- Homage completion plan: `docs/superpowers/plans/2026-04-19-homage-completion-plan.md`

— alpha
