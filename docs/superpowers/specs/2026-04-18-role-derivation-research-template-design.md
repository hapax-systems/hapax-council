# Role Derivation Research Template — Design

**Status:** DRAFT
**Date:** 2026-04-18
**CVS:** #156
**Relates to:** #155 (anti-personification / active-directorial-decisions), #121 (HARDM dot-matrix)

## 1. Goal

Establish a research-first derivation methodology for every role in `axioms/roles/registry.yaml`. Role specifications must be grounded in a documented general-case function catalogue and an explicit Hapax-specific adjustment column, with per-cadence decision schedules and grep-targets. Declaration-only role authoring is retired.

> Operator, 2026-04-18 18:47: "ROLE specifications should be derived from research surfacing what the ROLE actually is in the general case (minute by minute, cadence by cadence functions) and what the ROLE then actually is for US given the very strange set of tools, constraints, and goals we have."

The directive is methodological. The fix is a template plus a CI gate plus retroactive backfill, not new runtime code.

## 2. Current gap

`axioms/roles/registry.yaml` lists eight roles across three layers (structural / institutional / relational). Audit (CVS #156 research note §2):

- **Two roles** (`partner-in-conversation`, `addressee-facing`) carry literature anchors (Clark/Brennan, Goffman overhearer) through to per-function mechanics.
- **Six roles** were authored top-down in the 2026-04-16 Phase 7 reframe; ANT / Goffman / Sloman / Biddle are cited at the framework level only.
- **No role** enumerates minute-by-minute / cadence-by-cadence functions.
- **No answers_for item** carries a per-cadence decision schedule, a Hapax-specific-adjustment note, or a grep target to running code.

This is what #155 ("effects should be active directorial decisions") surfaces for `livestream-host`. The director answers for `scene-composition` in the registry, but nothing enumerates the tempo at which directorial decisions should fire, nor which Hapax constraints modify the general-case broadcast-director function set.

## 3. Three-phase methodology

### Phase A — general case

For each role, produce `docs/research/YYYY-MM-DD-role-<id>-general-case.md`:

1. Practitioner literature survey (broadcast-directing handbooks, ADHD-coaching craft, stage-management manuals, Clark & Brennan, etc.).
2. Per-cadence function catalogue. Minimum tempo bands: multi-second / multi-minute / multi-tens-of-minutes / session.
3. For each function: what decision fires at that tempo, what information feeds it, what failure mode is named in the literature.
4. Scientific register (see `feedback_scientific_register`). Citations only; no rhetorical valence.

### Phase B — Hapax adjustment

Produce `docs/research/YYYY-MM-DD-role-<id>-hapax-adjustment.md` with a four-column table:

| function | general-case baseline | Hapax-adjusted | evidence |

The adjustment lens — the "very strange set of tools, constraints, goals":

- Livestream IS the research instrument (no back-stage separation; Goffman front/back dissolves)
- Affordance pipeline (no fixed action repertoire; every expression is recruited)
- Continuous DMN + CPAL (posture is emergent state, not actor choice; no session boundaries)
- 6-camera + Reverie + 9-dim GPU surface (scene-composition decomposes into shader-graph + cairo-overlay + camera-fusion)
- `corporate_boundary` axiom (employer-data-isolation obligation for `household-inhabitant`)
- OSF pre-registration (condition fidelity across every utterance, not just measurement windows)
- Single-operator axiom (no multi-user arbitration for EF-assistant)
- 5-axiom governance mesh (chat interactions route through consent gates)

Each row must name which constraint modifies the function, or explicitly mark `no-analog` / `new-function`.

### Phase C — operationalization

Registry YAML entries cite Phase A + B inline. Each `answers_for` item carries a `cadence`, `general_case_ref`, `hapax_adjustment_ref`, and `grep_target` (or `not-yet-implemented`). The prose in `axioms/persona/hapax-description-of-being.md` §4 is amended to reference the same docs.

## 4. Template artifact

`docs/superpowers/templates/role-derivation-template.md` — skeleton file that authors copy per role. Contains:

1. Frontmatter (role id, layer, date, researcher).
2. Phase A sections: literature review, per-cadence function table, named failure modes.
3. Phase B sections: four-column adjustment table, `is_not` scoping (explicit anti-personification boundary), new-function list.
4. Phase C sections: proposed registry YAML diff, grep targets, open-question list.
5. Worked-example pointer to the first backfilled role (`livestream-host`).

## 5. CI gate

`hooks/scripts/role-derivation-gate.sh` — blocking hook on any diff that touches `axioms/roles/registry.yaml`:

- Parses the diff; for every added or modified `answers_for` item, requires `cadence`, `general_case_ref`, `hapax_adjustment_ref`.
- Validates that referenced paths exist on disk and resolve to headings matching the item id.
- Blocks registry additions whose role id has no Phase A + Phase B research doc present.
- Emits a structured failure with the exact missing fields and the template path.

Wired into the pre-commit layer and into the PR-check workflow alongside `no-stale-branches.sh`. Matches the enforcement principle from `hapax-description-of-being.md` ("every structural claim must be grep-able"), lifted to the role registry.

## 6. Retroactive backfill order

The eight existing Phase-7 roles each receive Phase A + Phase B docs. Order:

1. **livestream-host** — urgency from #155 anti-personification; `scene-composition` and `show-rhythm` are the functions operator named under-specified.
2. **partner-in-conversation** — smallest lift; Clark/Brennan anchors already present; serves as worked example for the template's completeness.
3. **executive-function-assistant** — director-loop consumes EF-state for orientation; next-largest consumer.
4. **research-participant** — OSF condition-fidelity cadence needed before next pre-registered block.
5. **addressee-facing** — Clark overhearer anchors partial; completes the relational-layer pair.
6. **research-subject-and-instrument** — structural; defers until the two relational are closed.
7. **executive-function-substrate** — structural anchor; minimal per-cadence content expected.
8. **household-inhabitant** — `corporate_boundary` axiom already carries most of the weight.

Sequencing rationale: direct operator pressure (#155) first, smallest-lift / worked-example second, director-loop-consumption for the middle band, structural last.

## 7. Registry schema extension

```yaml
- id: livestream-host
  layer: institutional
  whom_to: audience-and-youtube-platform
  derivation:
    general_case_refs:
      - "Clark 1996 — Using Language"
      - "Goffman 1981 — Forms of Talk"
      - "TV live-production craft literature (TBD citations)"
    cadence_table: docs/research/2026-04-NN-role-livestream-host-general-case.md
    hapax_adjustment: docs/research/2026-04-NN-role-livestream-host-hapax-adjustment.md
    is_not:
      - "Not an identity; not a persona; not a continuously-resident self"
      - "Not responsible for off-air operator behaviour"
  answers_for:
    - id: scene-composition
      cadence: multi-second
      general_case_ref: docs/research/2026-04-NN-role-livestream-host-general-case.md#scene-composition
      hapax_adjustment_ref: docs/research/2026-04-NN-role-livestream-host-hapax-adjustment.md#scene-composition
      grep_target: agents/studio_compositor/director_loop.py
```

`is_not` is the explicit anti-personification scoping field (reinforces #155 — bounded per-cadence functions cannot slide into identity claims). `derivation.*` fields are required by the CI gate.

## 8. File-level plan

| Path | Action |
|---|---|
| `docs/superpowers/templates/role-derivation-template.md` | new (skeleton + instructions) |
| `docs/research/2026-04-NN-role-livestream-host-general-case.md` | new (worked example, Phase A) |
| `docs/research/2026-04-NN-role-livestream-host-hapax-adjustment.md` | new (worked example, Phase B) |
| `hooks/scripts/role-derivation-gate.sh` | new (blocking hook) |
| `.git/hooks/pre-commit` wiring + PR-check workflow | amended |
| `axioms/roles/registry.yaml` | schema extended; `livestream-host` entry migrated as worked example |
| `axioms/roles/schema.md` (or equivalent schema doc) | amended to document `derivation.*` and `answers_for[*].cadence` |
| `axioms/persona/hapax-description-of-being.md` §4 | prose amended to cite research docs |

Sequencing (per CVS #156 §8):

- **PR 1:** template + `livestream-host` Phase A + Phase B research docs. No registry schema change yet.
- **PR 2:** registry schema extension, `livestream-host` migrated, hook + CI gate armed (advisory first run).
- **PR 3..N:** backfill remaining seven roles in the §6 order; flip hook to blocking once two roles are landed.

## 9. Test strategy

- Unit tests for `role-derivation-gate.sh` parsing logic: YAML diff parsing, path existence checks, heading-resolution checks, structured failure output. Table-driven fixtures for each failure mode.
- CI smoke: dry-run the hook against the current registry; confirm zero false positives once the backfill completes.
- Worked-example review: operator walks the `livestream-host` Phase A + B before the hook becomes blocking.
- Regression guard: a contrived PR that adds an `answers_for` item without `cadence` / refs must fail the hook in CI.

## 10. Open questions

1. `research-subject-and-instrument` crosses the principal / sovereign-principal boundary parked in Phase 7 — does Phase B for this role re-open that boundary, or explicitly defer?
2. Should `cadence` be a free-form string or an enum (`multi-second` / `multi-minute` / `multi-tens-of-minutes` / `session`)? Enum is stricter; free-form tolerates roles whose literature names different bands.
3. Where do cross-role modulations (SuppressionField, multi-role-composition design) land in the template — a Phase C sub-section per role, or a separate cross-role-interactions doc?
4. `is_not` — author-supplied prose vs structured list of anti-claims? Structured list is grep-able; prose captures nuance.
5. Retroactive backfill cadence: one role per week, or batch three at a time? Affects #155 follow-up timing.

## 11. Relation

- **Reinforces #155** (anti-personification). Bounded per-cadence functions with grep targets and `is_not` scoping cannot slide into "who Hapax is" framing. The methodology operationalises the Phase 7 reframe's core guardrail.
- **Feeds #121** (HARDM dot-matrix). Role state on the dot-matrix requires per-cadence functions to render as discrete dots; without them, role state has nothing to display at the minute-by-minute resolution HARDM targets.
- **Blocks future role additions.** Once PR 2 lands, the registry is amendment-gated on the Phase A + B + C trio. No top-down role authoring from this point.
- **Applies `feedback_exhaust_research_before_solutioning`** to role definition specifically. Same principle, new surface.
