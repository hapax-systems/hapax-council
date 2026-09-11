---
date: 2026-04-19
author: alpha (Claude Opus 4.7, 1M context, cascade worktree, research subagent)
audience: operator + delta + future authorship-path implementer
register: scientific, neutral
status: design write-up — not a plan, not code
related:
  - agents/studio_compositor/director_loop.py
  - agents/studio_compositor/structural_director.py
  - shared/director_intent.py
  - shared/compositional_affordances.py
  - docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md
  - docs/superpowers/plans/2026-04-19-homage-completion-plan.md
  - 20-projects/hapax-research/2026-04-18-go-live-cascade.md (vault)
  - 20-projects/hapax-research/2026-04-19-homage-aesthetic-reckoning.md (vault)
operator-directive-load-bearing: |
  "director loop is not enough; hapax needs to program content in
  coherent batches in the way livestream content would actually be
  planned and then executed; director loop should be used for
  sub-programme moves."
---

# Content Programming Layer — Design Write-Up

## §1. Problem framing

The current director architecture has two LLM-driven tiers:

- **Narrative director** (`director_loop.py`, ~30 s cadence) — emits
  `DirectorIntent` with a stance, an activity label, a narrative
  utterance, one or more `CompositionalImpingement`s, and a
  `NarrativeStructuralIntent` (per-tick ward emphasis / dispatch /
  retire / placement-bias / rotation-mode override).
- **Structural director** (`structural_director.py`, ~90 s cadence) —
  emits `StructuralIntent` with a `scene_mode`, a
  `preset_family_hint`, a one-or-two-sentence `long_horizon_direction`,
  and a `homage_rotation_mode`.

Both tiers operate at the *tactical* scale: their outputs decide what
the surface does over the next tens-of-seconds-to-few-minutes window.
Both tiers improvise every tick against the full affordance catalog,
bounded only by the `IntentFamily` literal and the choreographer's
concurrency rules.

A real livestream — a DJ set, a broadcast hour, a theatre run, an
operator's evening on stream — is not an unbroken sequence of
tactical reactions. It is a *programmed* artifact with structure at
multiple scales. A viewer watching for ten minutes can name what
section they are watching ("opening run", "deep cut", "interlude
chat", "wind-down ambient set"). The section has identity, duration,
internal grammar, entry and exit rituals, and a clear job. Tactical
moves *within* a section are constrained by the section's identity.
A "burst" rotation in a deep-listening segment is a category error;
a "deliberate" rotation in a hothouse-pressure segment leaves the
viewer cold.

Hapax has the macro layer (the show is "tonight's livestream", as a
single artifact with a research condition_id and a working_mode) and
the micro layer (`DirectorIntent` per tick). It has no representation
of the **meso** layer: the bounded, named, time-extended *sections*
that organise the show into legible chunks. The director improvises
the entire show as one unbroken stream of tactical moves, and the
surface reads that way: as a sequence of reactions, not as a show
with sections.

### 1.1 Layer naming

For the rest of this document the four scales are named:

| Scale     | Cadence            | Existing primitive                                  | Owns                                                                               |
| --------- | ------------------ | --------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Show      | per livestream (1-4 h) | research condition + working mode (implicit)    | identity of the entire broadcast; the artifact research data attaches to           |
| Programme | 5-30 min               | **MISSING** — proposed `Programme` primitive    | bounded section with role, content directives, constraint envelope, success criteria |
| Sub-programme | 30 s - few min     | `StructuralIntent` (today)                      | mid-horizon shape inside a programme: scene_mode, preset_family, rotation_mode     |
| Tactical  | per-tick (~30 s)       | `DirectorIntent` + `NarrativeStructuralIntent`  | per-tick ward emphasis / impingement set / narrative utterance                     |

The operator's directive recasts the existing two-tier director into
the bottom two rows: the structural director becomes the
**sub-programme** layer, and the narrative director stays as the
**tactical** layer. The proposed `Programme` primitive sits above
both, and `Show` becomes a thin shell that selects and sequences
programmes.

### 1.2 The 2-hour example, end to end

A concrete go-live shape from the operator's domain (~2 h, vinyl +
studio-work + chat interlude):

```
T+00:00  SHOW START — show_id=lrr-2026-04-19, condition_id=cond-phase-a-homage-active-001
T+00:00  P#1 opening-listening  (18 min) role=listening, vinyl side-A,
                                  rotation_mode=steady, ward_cap=2, cadence=45s
T+00:18  P#2 studio-work-block  (35 min) role=showcase+work_block, mpc+sliding,
                                  rotation_mode=deliberate, ward_cap=4
T+00:53  P#3 chat-interlude     (22 min) role=interlude, YT+chat,
                                  rotation_mode=rapid, package=bitchx-chat-variant
T+01:15  P#4 hothouse-pressure  (28 min) role=hothouse, research+IR-heavy,
                                  rotation_mode=burst, cadence=20s
T+01:43  P#5 wind-down          (17 min) role=wind_down, calm-textural,
                                  rotation_mode=paused, cadence=120s, captions dim
T+02:00  SHOW END
```

Each programme has a job, a constraint envelope on the layers below,
and a success criterion (did the listening programme sit with the
music, or did director churn break the stillness?). The structural
director's `scene_mode` / `preset_family` choices become programme-
internal — bounded by role, not re-improvised. Same for the narrative
director's tactical choices.

### 1.3 What a Programme is NOT

- **Not an impingement** (impingements are short-lived narrative-
  bearing recruitment cues; a programme is a long-lived constraint
  envelope under which many impingements arise).
- **Not an intent** (`DirectorIntent` / `StructuralIntent` declare
  what the system wants this tick / this 90 s; a programme declares
  what the system is doing for 5-30 min, and what intents are
  admissible inside it).
- **Not a research condition** (a condition is a research-registry
  artifact for slicing data — the unit of statistical comparison; a
  programme is a livestream artifact for organising the surface —
  the unit of compositional pacing; they map but are not the same).
- **Not a research-marker** (a marker tags a moment; a programme is
  a span with internal grammar).
- **Not a scene_mode / preset_family** (those remain sub-programme
  primitives, bounded by the active programme).

---

## §2. Prior art and adjacent systems

### 2.1 Within this repository

In-repo primitives in the neighbourhood, none of which is the right
shape but each contributing pattern material:

- **Research conditions** (`~/hapax-state/research-registry/<id>/condition.yaml`):
  bounded spans with id + parent + opened/closed + frozen files +
  directives manifest. Cover hours-to-days, not 5-30 min. A
  programme can map 1:N or N:1 to a condition (§9).
- **Structural director** (`structural_director.py`): long-horizon
  (90 s) with explicit `scene_mode` and `preset_family_hint`. The
  closest existing shape but improvisational — no planned duration,
  no entry/exit ritual, no constraint envelope.
- **`ContentScheduler`** (`agents/content_scheduler.py`): weighted-
  softmax with `DisplayDensity` mode (AMBIENT / FOCUSED /
  RECEPTIVE / PRESENTING). The density mode is programme-shaped but
  selected per-tick from environment, not from a planned span.
  Natural to make programme-owned for the programme's duration.
- **`PerceptualField.homage`** (PR #1072): first-class perception of
  the active homage package. A `PerceptualField.programme` block
  would be the natural extension.
- **`objective-*` artifacts** (sprint-tracker, vault goal notes):
  wrong scale (days-to-weeks), but the frontmatter pattern
  (`type: goal`, `status`, `depends_on`) is reusable for
  `type: programme` vault notes (§4.2 path).

Closest existing shape: structural director + research condition,
fused. Neither alone is sufficient.

### 2.2 External prior art

**Broadcast rundowns.** Live TV and broadcast streaming production
converged on the *rundown* (run of show): a sequence of timed, typed
segments with duration, content, and per-department technical
cues[^1][^2]. The data model is `Show → [Segments] → [Cues per
Segment]`. This maps directly onto Hapax's
`Show → [Programmes] → [Tactical moves per programme]` proposal.

**DJ set planning** (rekordbox / DJ.Studio / Serato). Tracks tagged
across orthogonal axes — *vibe*, *components*, *function* (set
starter / ender / exclude / tempo shifter)[^3][^4] — drafted into a
sequence of *phases* (opening, build, peak, breakdown, closer)[^5].
The phase is the DJ equivalent of a programme: bounded span with
role, content shortlist, constraint envelope on per-track decisions.

**Theatre cue sheets.** A grid of cue numbers tied to script pages
or sight cues, grouped into acts/scenes; an act carries explicit run
time and thematic identity[^6][^7]. Hierarchy: `Show → Act → Scene
→ Cue` ≅ Hapax `Show → Programme → Sub-programme → Tactical`.

**Twitch schedule API.** A `Schedule` composed of `Segment`s, each
with title, duration, category_id, recurring flag[^8]. Per-stream
category change is itself a programme transition (viewer UI + VOD
chapter boundary).

Convergent finding: a programme-shaped primitive is a **bounded,
named, typed span with planned duration, content directives, and an
internal grammar that constrains the tactical layer below it**.

### 2.3 Cognitive / perception theory

The unified semantic recruitment architecture (`compositional_
affordances.py`, spec 2026-04-02) treats all expression as
recruitment over a context-conditioned space. `AffordancePipeline.
select()` already accepts context biasing — SEEKING stance halves
the threshold for dormant capabilities, reshaping which candidates
win without changing the catalog.

A programme is the same kind of object one level up: a **context
gate** on what gets scored. A listening programme excludes
`cam.hero.operator-brio.conversing` regardless of narrative; a
hothouse programme excludes `fx.family.calm-textural` regardless
of stimmung. The programme does not change the algorithm — it
restricts the search space. The architecture invariant holds: still
one recruitment mechanism, no bypass paths, just a per-programme
filter at the candidate-set stage.

---

## §3. The Programme primitive

A concrete Pydantic-style sketch (illustrative — not for shipping;
implementation is post-live work per §7). All fields are explicit so
the discussion in §4-§6 has names to refer to.

```python
class ProgrammeRole(StrEnum):
    LISTENING       = "listening"       # operator + viewer sit with music
    SHOWCASE        = "showcase"        # operator visibly works on craft
    RITUAL          = "ritual"          # opening / closing / signature beats
    INTERLUDE       = "interlude"       # chat / Q&A / between-thing pause
    WORK_BLOCK      = "work_block"      # focused operator labour (code, write)
    TUTORIAL        = "tutorial"        # operator teaches / explains
    WIND_DOWN       = "wind_down"       # de-escalation toward silence
    HOTHOUSE_PRESSURE = "hothouse_pressure"  # max impingement density
    AMBIENT         = "ambient"         # operator-absent or background
    EXPERIMENT      = "experiment"      # research-condition swap, A/B variant
    REPAIR          = "repair"          # post-failure recovery / debug-on-stream
    INVITATION      = "invitation"      # explicit call for viewer participation


class ProgrammeStatus(StrEnum):
    PENDING   = "pending"
    ACTIVE    = "active"
    COMPLETED = "completed"
    ABORTED   = "aborted"


class ProgrammeConstraintEnvelope(BaseModel):
    """What the active programme constrains in the layers below it.

    Every field is optional; an empty envelope means 'no constraint
    beyond the existing director-tier defaults'. Consumers (affordance
    pipeline, structural director, narrative director, choreographer,
    Reverie mixer, CPAL) read this on each tick and apply the limits.
    """

    forbidden_capabilities: set[str] = Field(default_factory=set)
    required_capabilities:  set[str] = Field(default_factory=set)
    preset_family_priors:   list[PresetFamilyHint] = Field(default_factory=list)
    homage_rotation_modes:  list[HomageRotationMode] = Field(default_factory=list)
    homage_package:         str | None = None
    ward_emphasis_cap:      int = 4              # narrative director cap
    narrative_cadence_s:    float | None = None  # override director cadence
    structural_cadence_s:   float | None = None
    surface_threshold:      float | None = None  # CPAL should_surface threshold
    reverie_saturation_target: float | None = None  # A6 substrate target
    display_density:        DisplayDensity | None = None
    consent_scope:          str | None = None    # which contract this programme runs under


class ProgrammeContent(BaseModel):
    """What the programme is about, concretely.

    Operator-curated path (§4.2) populates these explicitly; Hapax-
    authored path (§4.1) fills them from perception + profile.
    """

    music_track_ids:        list[str] = Field(default_factory=list)
    operator_task_ref:      str | None = None       # vault note path
    research_objective_ref: str | None = None       # condition_id or vault ref
    narrative_beat:         str | None = None       # 1-2 sentence prose intent
    invited_capabilities:   set[str] = Field(default_factory=set)


class ProgrammeRitual(BaseModel):
    """Entry / exit choreography that marks the programme boundary."""

    entry_signature_artefact: str | None = None     # quit-quip / motd-block id
    entry_ward_choreography:  list[str] = Field(default_factory=list)
    entry_substrate_palette_shift: str | None = None
    exit_signature_artefact:  str | None = None
    exit_ward_choreography:   list[str] = Field(default_factory=list)
    exit_substrate_palette_shift: str | None = None
    boundary_freeze_s:        float = 4.0           # director-loop freeze on transition


class ProgrammeSuccessCriteria(BaseModel):
    """How the programme knows it's done or should abort.

    Each criterion is a name + a target — concrete predicates are
    evaluated by a programme-monitor loop that runs alongside the
    structural director.
    """

    completion_predicates: list[str] = Field(default_factory=list)
    abort_predicates:      list[str] = Field(default_factory=list)
    min_duration_s:        float = 60.0
    max_duration_s:        float = 1800.0


class Programme(BaseModel):
    programme_id: str
    role:         ProgrammeRole
    status:       ProgrammeStatus = ProgrammeStatus.PENDING
    planned_duration_s: float
    actual_started_at:  float | None = None
    actual_ended_at:    float | None = None

    constraints: ProgrammeConstraintEnvelope = Field(
        default_factory=ProgrammeConstraintEnvelope
    )
    content:     ProgrammeContent     = Field(default_factory=ProgrammeContent)
    ritual:      ProgrammeRitual      = Field(default_factory=ProgrammeRitual)
    success:     ProgrammeSuccessCriteria = Field(
        default_factory=ProgrammeSuccessCriteria
    )

    parent_show_id:     str
    parent_condition_id: str | None = None  # research-registry mapping
    notes: str = ""

    @property
    def elapsed_s(self) -> float | None:
        if self.actual_started_at is None:
            return None
        end = self.actual_ended_at or time.time()
        return end - self.actual_started_at
```

### 3.1 Field commentary

- **`role`** is a closed enum because it gates the consumers below.
  Twelve roles cover the operator's livestream content; wider produces
  decision paralysis for the Hapax-authored path (§4.1).
- **`planned_duration_s` vs `actual_*`** follows the broadcast-rundown
  pattern: plan + observed result. Success criteria (§3) decide
  whether early/late ending is acceptable.
- **`constraints` envelope** is the load-bearing field. It is the only
  thing tying the programme abstraction to the running stack. Without
  it a programme is a label; with it, a context gate (§5).
- **`ritual`** makes transitions legible. The choreographer already
  has the vocabulary (BitchX `mode-change`, `topic-change`,
  `netsplit-burst`); ritual just declares which runs at the seam.
- **`success`** predicates are named strings (e.g.
  `"operator_left_room_for_10min"`, `"vinyl_side_a_finished"`),
  resolved by a programme-monitor loop — not Python callables, since
  the object must be JSON-serialisable.
- **`parent_condition_id`** connects to research data slicing (§8).
  A programme may sit inside a condition or *be* one.

### 3.2 What a Programme does NOT have

No callables / closures / live state beyond `actual_*` + `status` —
the object is plan + observed result, JSON-serialisable. No per-tick
state. No nested programmes; the hierarchy stops at one level (sub-
programmes are the existing structural-director primitive, not
recursive Programme objects).

---

## §4. How programmes get planned — Hapax-authored (only path)

**Authorship is Hapax-generated, end-to-end. No operator authorship at
any level — no outlines, no templates, no skeletons, no cue sheets.**
The operator's original directive ("hapax needs to program content in
coherent batches") is unambiguous: Hapax does the programming. See
memory `feedback_hapax_authors_programmes.md` for the load-bearing
correction that retired the earlier hybrid/operator-curated proposals.

### 4.1 Hapax-generated programme plans

At show-start and each programme boundary, Hapax's director LLM emits
a programme plan — 2-5 programmes with role, planned duration, content
directives, constraint envelope. Inputs:

- Perceptual field (operator presence, stance, biometrics, recent
  utterance, camera/IR signals)
- Operator profile (recent activity, fatigue, working mode)
- Vault state as **read-source** (goals with `type: goal`, sprint
  measures, daily note, active project frontmatter) — programme
  generation reads these; the operator does NOT pre-author anything
  at the programme scale
- Research condition history (what programme shapes produced what
  outcomes on prior streams — Thompson-sampling posteriors over
  programme-role × condition)
- Available content state (vinyl platter current track, SoundCloud
  queue depth, whiteboard content classification, YouTube reaction
  queue)

Output: list of `Programme` JSON, validated, persisted at
`~/hapax-state/programmes/<show_id>/plan.json`. The plan is
regenerated (not just appended) at programme boundaries so Hapax can
re-plan forward in response to the live context.

*Grounding anchor.* Per `project_programmes_enable_grounding` and
`feedback_grounding_exhaustive`, the programme plan is itself a
recruitment output — the planner LLM recruits programme-shape
capabilities (role, duration, constraint envelope) from an affordance
catalog. Programme authorship is grounded recruitment at the show
scale, not a pre-written script. The plan can be wrong; it re-plans.

### 4.2 Operator live influence — at runtime only

The operator's influence on programme flow happens through runtime
impingements, never through pre-stream authorship:

- **Side-chat** — operator writes to the sidechat file; emits as
  high-salience impingement; director can recruit "cut to a new
  programme" capability in response
- **Stream Deck cues** — per task #140, operator buttons emit
  impingement-level cues the pipeline recruits against
- **Voice** — STT → impingement → pipeline recruitment
- **Presence shifts** — operator leaves the room, fatigue increases,
  etc., produce perceptual impingements the planner re-reads on the
  next boundary check

Operator-triggered programme transitions (e.g. "switch to
wind-down now") are valid runtime commands, emitted as impingements,
executed at the next programme boundary. They are NOT programme
authorship — they are programme-level cues the pipeline acts on.

### 4.3 Vault integration — read-only

The vault at `~/Documents/Personal/` is a perception source, not a
write target. Programme generation reads:

- Goal notes (`type: goal`) — what the operator has flagged as
  long-horizon work
- Sprint measures — research sprint context
- Daily notes — recent narrative context + today's operator state
- Person notes — relationship context for any non-operator-identified
  content
- Project frontmatter — active project shape

These feed the programme LLM's context. The operator writes vault
notes as part of personal executive-function work; Hapax reads them
as perception. There is **no** `~/Documents/Personal/20-projects/
hapax-research/programmes/` folder, no `type: programme` frontmatter,
no template ingestion. That path, proposed in the earlier drafts, is
retired.

### 4.4 Failure mode + recovery

When the programme plan is structurally wrong (e.g. Hapax authored a
listening programme while the operator is actively speaking to
collaborators), the abort predicate at §6 fires and the planner
re-plans forward. There is no operator forcing function at the
authorship layer — abort + re-plan is the only correction path.
Post-show, the planner's Thompson posteriors update against observed
outcomes so the next run's prior is better-informed.

---

## §5. How programmes bound the director-loop search space

This is the integration point with the existing stack. The pattern
is identical across consumers: each consumer reads the active
programme's `constraints` envelope and applies it as a filter or
override on its existing logic. No consumer changes its core
algorithm. Five concrete integrations:

### 5.1 Affordance pipeline filter

`AffordancePipeline.select()` already accepts contextual biasing
(SEEKING-stance threshold halving). Extend with a programme-filter
step that runs *before* scoring:

```
def select(impingement, ...):
    candidates = retrieve_top_k(impingement.embedding)
    if programme := active_programme():
        candidates = [c for c in candidates
                      if c.name not in programme.constraints.forbidden_capabilities
                      and (not programme.constraints.required_capabilities
                           or c.name in programme.constraints.required_capabilities)]
    candidates = apply_governance_veto(candidates)
    candidates = score(candidates, programme=programme)  # programme can also bias scoring
    ...
```

The `forbidden_capabilities` set is enumerated by the programme
constraint envelope (e.g. listening programme forbids
`cam.hero.operator-brio.conversing` for its duration). The
`required_capabilities` set is rare — used for ritual programmes that
*must* surface a specific signature artefact.

### 5.2 Structural director

`StructuralDirector.tick_once()` keeps its 90 s LLM call but its
output is now constrained by the programme:

- `scene_mode` choices restricted to those compatible with the
  programme role (a `listening` programme rejects `desk-work`
  scene_mode).
- `preset_family_hint` chosen from `programme.constraints.preset_
  family_priors` if non-empty, else from the full set.
- `homage_rotation_mode` chosen from
  `programme.constraints.homage_rotation_modes` if non-empty.
- The LLM prompt receives the programme's `narrative_beat` as
  additional context — the structural director knows what programme
  it is inside and what that programme is for.

If `programme.constraints.structural_cadence_s` is set, the
structural director's tick interval is overridden for the duration
of the programme.

### 5.3 Narrative director

Two changes:

- `NarrativeStructuralIntent.ward_emphasis` is *capped* by
  `programme.constraints.ward_emphasis_cap` (current code already
  caps at 4; programme can tighten to 2 for listening programmes
  to enforce stillness).
- The director's tick interval is overridden by
  `programme.constraints.narrative_cadence_s` for the duration of
  the programme. A wind-down programme runs the narrative tier at
  120 s; a hothouse-pressure programme runs it at 20 s.

### 5.4 CPAL speech-production threshold

CPAL's `should_surface` threshold (the gate that decides whether a
candidate vocal expression actually surfaces) currently reads a
hardcoded value. It becomes programme-driven:

```
threshold = programme.constraints.surface_threshold or DEFAULT_SURFACE_THRESHOLD
```

A listening programme sets the threshold high (Hapax stays quiet
through the music); a tutorial programme sets it low (Hapax narrates
liberally). This retires gate audit finding #4 (the
speech-production short-circuit) by giving it a principled,
programme-scoped owner.

### 5.5 Reverie substrate saturation target

The Bachelard A6 substrate-saturation target (currently
`colorgrade.saturation` at runtime-default 0.45) becomes a programme-
owned palette:

```
target = programme.constraints.reverie_saturation_target or DEFAULT_SATURATION_TARGET
```

A listening programme dims the substrate (target 0.30) so the music
reads as the foreground; a hothouse-pressure programme lifts it
(target 0.70) so the substrate visibly responds to ward churn.

### 5.6 Choreographer cadence

The choreographer's `B4 phase` (steady / deliberate / rapid / burst)
is selected from `programme.constraints.homage_rotation_modes` rather
than improvised by the structural director on a free choice. The
structural director still picks the *specific* rotation mode within
the programme's allowed set on each tick — but the set is bounded.

### 5.7 Common consumer pattern

Each integration is a 3-5 line patch: read `active_programme()`,
apply the constraint, fall back to the existing default if no
programme is active. The fallback path keeps the system fully
functional with no programme layer running — critical for
incremental rollout (§7) and legacy/debug runs.

---

## §6. Programme transitions

Three transition types, all through one `ProgrammeManager` loop:

- **Planned**: `elapsed_s >= planned_duration_s` AND
  `completion_predicates` true. Manager advances PENDING → ACTIVE on
  the next programme, preceded by §6.4 choreography.
- **Operator-triggered**: Stream Deck button, side-chat command, or
  vocal cue ("hapax, next programme"). Manager hard-cuts; if a non-
  next programme is selected, plan re-orders and continues.
- **Emergent**: `abort_predicates` true. Common predicates:
  `operator_left_room_for_10min` → auto-transition to `wind_down`;
  `impingement_pressure_above_0.8_for_3min` → transition to
  hothouse-pressure (if not already in one);
  `consent_contract_expired` → transition to a consent_scope=null
  variant; `vinyl_side_a_finished` → transition out of vinyl-
  listening. Emergent transitions accept a 5 s operator-veto grace
  window.

### 6.4 Transition choreography (four beats)

1. **Exit ritual of current programme.** `ritual.exit_signature_
   artefact` rotates onto surface; `ritual.exit_ward_choreography`
   dispatched.
2. **Director-loop freeze** for `ritual.boundary_freeze_s`
   (default 4 s). Narrative director skips its tick. Surface settles.
3. **Substrate palette shift.** Reverie mixer crossfades if
   exit/entry palettes differ.
4. **Entry ritual of next programme.** Mirror of step 1.

The transition is itself legible — viewers see "we moved into a new
section" without needing literal chrome (though such chrome could
be added as an opt-in catalog capability).

---

## §7. Integration sequencing (post-live)

Programme-layer implementation is post-go-live work. The phase
breakdown follows the homage-completion-plan §2 pattern: each phase
is a discrete subagent dispatch with bounded scope, blocking
dependencies, parallel-safe siblings, success criteria, and an LOC
range. Twelve phases, organised into three families.

### Family P — Primitive + smoke test

| Phase | Scope | Deps | Parallel-safe | LOC |
|-------|-------|------|---------------|-----|
| P1: `Programme` Pydantic primitive | `shared/programme.py` (Programme + sub-models from §3) + tests | none (leaf) | P2, P3, P4 | 250-400 + 200 tests |
| P2: ProgrammeManager loop + state file | `agents/programme_manager.py`; state at `~/hapax-state/programmes/<show_id>/state.json` (atomic tmp+rename); plan at `plan.json` (read-only during show); `active_programme()` helper | P1 | P3, P4 | 350-500 |
| P3: Smoke-test programme | One concrete `vinyl-listening` programme (role=LISTENING, duration=900 s, forbids `cam.hero.operator-brio.conversing` / `cam.hero.desk-c920.coding`, requires `cam.hero.overhead.vinyl-spinning`, ward_emphasis_cap=2, surface_threshold=0.85, reverie_saturation_target=0.30, homage_rotation_modes=["paused","deliberate"], success="vinyl_side_a_finished"). Smoke harness asserts no forbidden capability recruited via Prometheus counter | P1, P2 | P4 | 100-200 + 100 |
| P4: ProgrammePlanLoader | Reads vault (`~/Documents/Personal/20-projects/hapax-research/programmes/`, frontmatter `type: programme`) + falls back to JSONL plan; supports three authorship paths by source-selection per show | P1 | P2, P3 | 300-400 |

### Family R — Consumer integrations (all parallel-safe with each other)

| Phase | Patch | Deps | LOC |
|-------|-------|------|-----|
| R1: Affordance pipeline programme filter | `AffordancePipeline.select()` reads `active_programme().constraints.{forbidden,required}_capabilities` (§5.1) | P1, P2 | 30-60 + 150 tests |
| R2: Structural director programme awareness | `StructuralDirector` applies `preset_family_priors`, `homage_rotation_modes`, optional `structural_cadence_s` (§5.2) | P1, P2 | 50-100 + 150 |
| R3: Narrative director programme caps | `DirectorLoop` caps `ward_emphasis` to `ward_emphasis_cap`; cadence override by `narrative_cadence_s` (§5.3) | P1, P2 | 50-100 + 150 |
| R4: CPAL surface-threshold programme override | CPAL `should_surface` reads `programme.constraints.surface_threshold` (§5.4); retires gate audit #4 | P1, P2 | 30-60 + 100 |
| R5: Reverie saturation programme override | Reverie mixer reads `programme.constraints.reverie_saturation_target` (§5.5) | P1, P2 | 30-60 + 100 |

### Family T — Transitions + observability

| Phase | Scope | Deps | Parallel-safe | LOC |
|-------|-------|------|---------------|-----|
| T1: Transition choreography sequencer | `agents/programme_transition.py` four-beat choreography (§6.4); hooks the existing choreographer + Reverie mixer | P1, P2 | T2, T3 | 250-400 + 250 |
| T2: Programme observability | Extend `hapax_homage_*` with `programme` label; new `hapax_programme_*` metrics (§8); JSONL outcome log | P2 | T1, T3 | 200-300 |
| T3: PerceptualField.programme block | Add `programme` field so downstream agents see active programme (mirrors `PerceptualField.homage`) | P1, P2 | T1, T2 | 50-100 + 100 |

### 7.1 Phase ordering and parallelism

```
P1 ── P2 ── P3 (smoke test, gate to ship Family R)
        │
        ├── P4 (plan loader, gate to ship hybrid path)
        │
        ├── R1, R2, R3, R4, R5 (parallel; Family R closes the
        │                       integration with the running stack)
        │
        └── T1, T2, T3 (parallel; Family T closes observability +
                        legible boundaries)
```

P1 + P2 + P3 land first as a self-contained smoke-test slice that
validates the primitive + manager + one concrete programme without
touching any consumer. Family R can then ship in parallel; the
empty-constraints fallback path means each consumer can be patched
and merged independently. Family T closes the loop with transition
choreography and observability; T1 should ship before the second
programme is added so transitions are legible from the first day.

Total estimated LOC: 1700-2700 implementation + 1500-2000 tests.

---

## §8. Post-live observability

Three layers, mirroring the homage observability landed 2026-04-19.

**Prometheus.** Extend `hapax_homage_*` metrics with a `programme`
label. New metrics: `hapax_programme_start_total{role, show_id}`,
`hapax_programme_end_total{role, show_id, reason}` (reason ∈
{planned, operator, emergent, aborted}), `hapax_programme_active
{programme_id, role}` gauge, `hapax_programme_duration_{planned,
actual}_seconds{programme_id}`, and
`hapax_programme_constraint_violation_total{programme_id, kind}`
(fires when a consumer exceeds the envelope; should be zero in
correctly-wired systems).

**JSONL outcome log** at `~/hapax-state/programmes/<show_id>/
<programme-id>.jsonl`, one line per event: `start` (full
Programme), `tactical_summary` every 60 s (wards emphasised,
impingements recruited, speech surfaced), `abort` (with predicate),
`end` (with actual_duration_s + reason). Append-only, rotates at
5 MiB / keep 3 like `director-intent.jsonl`.

**LRR research instrument coupling.** The programme is the natural
unit of comparative analysis. The Bayesian validation schedule (27
measures across 6 models) currently slices on condition_id; with a
programme layer, each programme inside a condition contributes a
separate sample (a 1-condition night with 8 programmes gives 8
samples, not 1). Programme outcomes are themselves measures (did
the listening programme stay quiet? did the hothouse-pressure
programme generate its target impingement density?). Slicing by
programme is additive to slicing by condition — both labels present.

---

## §9. Governance concerns

**Consent.** The affordance-level consent gate is unchanged: a
programme's `required_capabilities` cannot force recruitment of a
consent-required capability without an active contract; the pipeline
still rejects it. The programme layer is consent-*additive* — it can
forbid further (an `INTERLUDE-ANONYMOUS` programme forbids any
capability with `medium=visual`) but cannot permit what the affordance
gate rejects. New: programmes may declare a `consent_scope` (e.g.
`"guest-principal-a1-2026-04-19"`) which the manager checks at programme
start; if the contract is not active, the programme aborts before
starting. Mid-programme contract expiry fires an abort predicate and
the manager transitions to a consent-safe variant.

**Anti-personification.** Programme names and content directives must
pass the same CI gate that scans `axioms/**/*.md`. The role enum is
safe (functional categories). The risk is in operator-curated
`narrative_beat` strings ("Hapax wants to sit with the music tonight"
violates; "listening session for side A" passes). The CI gate
extends to scan vault programme notes and JSONL plans before
`ProgrammePlanLoader` loads them.

**Working-mode coupling.** `working_mode` biases programme
admissibility: a `research-primary` programme only fires in
`research`; an `experiment` programme requires `research` AND a
registered `parent_condition_id`; a `wind_down` programme is
admissible in both with different default envelopes (research
preserves captions even at low cadence; rnd dims them). The loader
filters the per-show plan against current working_mode and warns on
inadmissible programmes.

---

## §10. Open questions for the operator

These ten questions have answers that load-bear on the eventual
design. Each is terse on purpose; the operator's answer for each
constrains a §3-§7 detail.

1. **Authorship default.** Is hybrid (§4.3) the right default, or
   does the operator prefer Hapax-authored (§4.1) for routine
   streams and operator-curated (§4.2) only for marquee runs?
2. **Role enumeration.** Are the 12 roles in §3 complete, or are
   there roles the operator wants explicit (e.g. `repair`,
   `rehearsal`, `improvisation`)? Is any role redundant?
3. **Smallest-possible smoke programme.** Is `vinyl-listening` the
   right first programme, or should the smoke test target a
   programme the operator runs more often (e.g.
   `studio-work-block`)?
4. **Plan revision mid-show.** Should the operator be able to edit
   the JSONL plan during a running show (with the manager picking
   up changes on programme boundaries), or is the plan immutable
   for the show's duration?
5. **Programme-monitor abort threshold.** What should the default
   `min_duration_s` be (so a programme can't abort 5 s in)? §3
   suggests 60 s; the operator's tolerance for early-abort may be
   higher or lower.
6. **Director-loop freeze duration.** §6.4 defaults the boundary
   freeze to 4 s. Is that the right marker — long enough to be
   legible, short enough not to feel dead?
7. **Programme transitions on emergent abort.** Should the system
   always transition to a *named* fallback programme on abort
   (e.g. `interlude` or `wind-down`), or should it pause with no
   active programme until the operator intervenes?
8. **Vault note location.** Is `~/Documents/Personal/20-projects/
   hapax-research/programmes/` the right vault path, or is there a
   PARA placement that fits better (e.g. under `30-areas/livestream/
   programmes/`)?
9. **Hapax-authored plan latency budget.** A pre-show plan
   generation (§4.1) involves an LLM call. Is operator willing to
   wait ~15-30 s at show-start for the planner LLM to ground in
   the day's perceptual field, or should plan generation happen
   ahead of time (e.g. during the previous day's wind-down)?
10. **Programme-outcome write-back.** Should programme outcomes be
    written back into the operator-curated vault note as a Result
    appendix (closing the LRR loop into the operator's reading
    surface), or kept in JSONL only?

---

## Sources cited

[^1]: Rundown Studio, "What is a Production Rundown in Live Broadcast or Live Production". https://rundownstudio.app/blog/what-is-a-production-rundown/
[^2]: Wave.video, "Run of Show Template & Best Practices for Live Streaming". https://wave.video/blog/run-of-show-template/
[^3]: rekordbox, "DJ Set Preparation On Steroids". https://rekordbox.com/en/connect/djstudio/dj-set-preparation/
[^4]: a-rich, DJ-Tools, "Tagging Guide". https://a-rich.github.io/DJ-Tools-dev-docs/conceptual_guides/tagging_guide/
[^5]: DJ.Studio, "DJ Set Preparation: The Complete, Modern Workflow". https://dj.studio/blog/dj-set-preparation
[^6]: Stagetimer, "What is a Cue Sheet? Best Practices & Free Template". https://stagetimer.io/blog/what-is-a-cue-sheet/
[^7]: Theaterish, "Theatre Template: Master Cue Sheet". https://theaterish.com/blogs/news/theatre-template-master-cue-sheet
[^8]: Twitch Developers, "Schedule API". https://dev.twitch.tv/docs/api/schedule
