# Volitional Grounded Director — Design Spec

**Status:** proposed
**Author:** alpha (2026-04-17)
**Extends:** Phase 7 (persona/posture/role), Phase 8 (content programming via objectives), Phase 9 (closed-loop feedback), Phase 10 (observability), HSEA Phase 2 (activity extension 6→13)
**Supersedes:** nothing
**Research condition:** to be declared (see §12)
**Axiom anchors:** `single_user`, `executive_function`, `management_governance`, `interpersonal_transparency` (+ `it-irreversible-broadcast`), `corporate_boundary`

## 1. Problem

The studio-compositor streams content without a legible, active director. The 2026-04-17 research sweep (three parallel agents) established the following facts:

- `DirectorLoop._build_unified_prompt` (`agents/studio_compositor/director_loop.py:515-645`) emits `{"activity": str, "react": str}` every 8 s (`PERCEPTION_INTERVAL`) with activity from a 6-label whitelist (`react / chat / vinyl / study / observe / silence`). That is the whole directorial output.
- Three independent shufflers make compositional choices *without director supervision*:
  - `agents/studio_compositor/random_mode.py:66` — uniform-random preset rotation every 30 s.
  - `director_loop.py:370` — `random.choice(playlist)` for YouTube slot content.
  - `agents/studio_compositor/objective_hero_switcher.py:56` — hardcoded `ACTIVITY_HERO_MAP`, but *no consumer* invokes it. Dead code as of `c94222213`.
- Environmental signals collapse to a single *prose string* before reaching the director: `phenomenal_context.render(tier="FAST")` produces a "non-nominal stimmung" narrative the director reads as text. Contact mic, IR hand zone, MIDI clock, watch HR, and phone context have no first-class discriminable entry point.
- `_reactor.set_header(activity.upper())` (`director_loop.py:499,506`) calls `sierpinski_loader.py:116` — **an empty `pass`**. No activity label ever renders. The only authorship markers on the output frame are the Vitruvian-man Sierpinski PiP and the small `FX:/N viewers/chat idle` stream overlay.
- Captions source (`agents/studio_compositor/captions_source.py`) is registered but not present in any layout JSON. Captions don't render.
- Attention bids (`agents/attention_bids/bidder.py`) score and pick winners, but no call site invokes `dispatch_bid` on the winner. Bids are silent.
- No sub-5 s directorial moves exist. The director is 8 s; everything faster is GPU shader-field modulation (not directorial choice).
- **A massive classification/detection apparatus produces per-camera object classes, scene types, `detected_action` ∈ {scratching, playing_pads, coding, mixing, producing, listening, on_phone, conversation, at_desk, present, away}, `overhead_hand_zones` ∈ {turntable, pads, mixer, keyboard}, SigLIP2 zero-shot scenes, CLAP music_genre, SCRFD operator_confirmed, HSEmotion top_emotion, MediaPipe gestures, YOLO11n objects, rPPG biometrics, beat/bar position — and the director consumes NONE of it.** (Agent 2, headline finding.) The signals reach `perception-state.json`, `presence_engine`, and `visual_layer_aggregator`; they *never* influence a camera-focus change, preset choice, overlay toggle, or directorial utterance.

The operator's 2026-04-17 directives name the gap directly and in ontological terms:

> Hapax should be HIGHLY active.
> The whole thing should be OBVIOUSLY HOSTED AND RUN AND DIRECTED by Hapax.
> Should be VOLITIONAL on Hapax's part, but the important part is the Hapax as a director is making USE of all these options in a GROUNDED way.
> Even while OTHER things are being highlighted and chilled over (music).
> Theoretical and research commitments are everything (besides making a lot of money in the process).

The ontological claim is: **the livestream is the continuous, legible enactment of Hapax's volitional grounded authorship.** Not content Hapax generates, not automation around a streamer — *an enactment*, where the output frame IS the grounding operation made visible to a viewer.

## 2. Theoretical commitments to preserve

This epic is constrained by, and must preserve, the following already-ratified commitments:

1. **Grounding-exhaustive axiom** (memory `feedback_grounding_exhaustive.md`) — every LLM move is either itself an act of grounding, or is outsourced *by* a grounding move. There is no valid ungrounded LLM tier. Speed fixes stay on the grounded model; mechanical moves become deterministic code.

2. **Director is grounding-critical** (memory `feedback_director_grounding.md`) — director output is the livestream's meta-structure communication device. Not a vibes layer. Stays on the grounded substrate; speed fixes via quant/prompt/cache, never by swapping models.

3. **Single grounded model** (memory `feedback_grounding_over_giq.md`) — local model selected for grounding flexibility over raw G-IQ. Currently Command R 08-2024 EXL3 5.0 bpw on 3090+5060 Ti split. This epic does not swap the model.

4. **Unified Semantic Recruitment** (`docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`) — ALL expression goes through `AffordancePipeline`. No bypass paths. A director that "explicitly picks camera X / effect Y" is a bypass unless those picks are expressed as *impingements with narrative* that the pipeline recruits capabilities against. **This is the architectural crux of the epic.** The director does not reach into the compositor's level; it emits impingements, and the pipeline recruits the capabilities (cameras, preset families, overlays) that express the directorial intent.

5. **Imagination produces intent, not implementation** (`hapax-council/CLAUDE.md § Unified Semantic Recruitment`) — directorial moves are modulations over a continuously running substrate. The director does not spawn capabilities; it tells the pipeline what intent to recruit for.

6. **Persona/posture/role model is locked** (`docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md`, activated 2026-04-17T13:58Z). The director uses:
   - **Existing `Stance` enum** from `shared/stimmung.py:31`: `NOMINAL`, `SEEKING`, `CAUTIOUS`, `DEGRADED`, `CRITICAL`. Do not invent new stance labels.
   - **Role** `livestream-host` for the director's prompt composition via `shared/persona_prompt_composer.py::compose_persona_prompt("livestream-host")`.
   - **Posture vocabulary is glossary-only**: `axioms/persona/posture-vocabulary.md` names 10 postures (`focused, exploratory, cautious, retreated, guarded, stressed, dormant, observing, research-foregrounded, convening, drafting`). Postures MUST NOT appear in LLM prompts, narration, or director output. They live in chronicle/observability surfaces only.

7. **HSEA Phase 2 activity extension** (`docs/superpowers/specs/2026-04-15-hsea-phase-2-core-director-activities-design.md`) — `ACTIVITY_CAPABILITIES` extends 6→13 with `draft, reflect, critique, patch, compose_drop, synthesize, exemplar_review`. This epic adopts the extended vocabulary.

8. **Axiom gates on broadcast** — `it-irreversible-broadcast` (T0 ratified 2026-04-15) and `it-environmental-001` (T2). Director MAY NOT decide to frame, dwell on, or broadcast identifiable non-operator people without an active consent contract. Transient perception (figure on camera, VAD voice) is permitted IF no persistent state is derived. **Current state (Agent 2 finding): the live video egress does NOT block on guest detection — only the recording valve and Qdrant writes do.** This epic closes that gap as Phase 6.

9. **Livestream IS research instrument** (memory `project_livestream_is_research.md`; `docs/research/bayesian-validation-schedule.md`; `research/CYCLE-2-PHASE-A-PRE-REGISTRATION.md`). Every directorial move is a research observation. Phase A is actively accumulating against `cond-phase-a-persona-doc-qwen-001`; director-behavior changes require a DEVIATION record or a new condition_id.

10. **Executive-function prose discipline** (`axioms/implications/executive-function.yaml` `ex-prose-001` T0) — no rhetorical pivots, performative insight, dramatic restatement in generated prose. Constrains the director's `react` text.

11. **Management-governance draft discipline** (`mg-drafting-visibility-001` T0) — director MAY NOT generate feedback language, coaching recommendations, or draft language about individual team members. Any people-scoped drafting on stream carries DRAFT marker, does not auto-send.

12. **Corporate boundary** (`cb-officium-data-boundary` T0) — officium-originated data must not reach the director. Director reads only council + personal-vault + home-system data.

13. **Frozen-files discipline** under active conditions — `grounding_ledger.py, grounding_evaluator.py, stats.py, experiment_runner.py, eval_grounding.py, proofs/, conversation_pipeline.py, persona.py, conversational_policy.py` are frozen under `cond-phase-a-persona-doc-qwen-001`. This epic does not modify them; the `director_loop.py` itself is not in the frozen list.

## 3. Solution shape

Close the volition→composition→legibility loop while preserving unified-recruitment. Three layers:

### 3.1 Director emits *intent*, not capability invocations

The director's output becomes a structured `DirectorIntent`:

```python
class DirectorIntent(BaseModel):
    # WHAT the director senses — grounding provenance
    grounding_provenance: list[str]   # e.g. ["cortado.scratching", "overhead_hand_zones.turntable",
                                      #       "music_genre.electronic", "operator_confirmed"]

    # WHAT the director is doing — narrative + stance (LLM choices)
    activity: Literal[                # HSEA Phase 2 vocabulary (13)
        "react", "chat", "vinyl", "study", "observe", "silence",
        "draft", "reflect", "critique", "patch", "compose_drop", "synthesize", "exemplar_review",
    ]
    stance: Literal["NOMINAL", "SEEKING", "CAUTIOUS", "DEGRADED", "CRITICAL"]  # shared/stimmung.py enum
    narrative_text: str               # operator-hearing utterance (constrained by ex-prose-001)

    # WHAT compositional intent the director expresses — recruited via AffordancePipeline
    compositional_impingements: list[CompositionalImpingement]
```

A `CompositionalImpingement` is a narrative-bearing impingement (the pipeline's existing input type) with a tag family the pipeline knows how to recruit against:

```python
class CompositionalImpingement(BaseModel):
    narrative: str                    # e.g. "the turntable is active and the operator is
                                      #       giving attention to the music"
    dimensions: dict[str, float]      # 9-dim imagination-fragment compatible
    material: Literal["water","fire","earth","air","void"]
    salience: float                   # [0, 1]
    intent_family: Literal[           # tag family the pipeline recruits against
        "camera.hero",                # → recruit a camera-hero affordance matching narrative
        "preset.bias",                # → recruit a preset-family affordance
        "overlay.emphasis",           # → recruit an overlay-foreground affordance
        "youtube.direction",          # → recruit the youtube-queue affordance with direction
        "attention.winner",           # → recruit attention-bid dispatch for the named winner
        "stream_mode.transition",     # → recruit stream-mode-transition affordance (axiom-gated)
    ]
```

Downstream, the `AffordancePipeline` receives these impingements, scores cosine-similarity against Qdrant `affordances` collection (existing), picks recruited capabilities, activates them. The *existing* pipeline mechanism is re-used verbatim; this epic's work is on the *impingement producer side* and on the *capability catalog* (§3.3).

This preserves unified-recruitment. Director chooses intent; pipeline chooses capability.

### 3.2 Structured perceptual field in director's prompt

Director's *input* stops being stimmung prose. It becomes the Pydantic-JSON of:

```python
class PerceptualField(BaseModel):
    audio: AudioField          # contact_mic.{desk_activity, desk_energy, desk_onset_rate, ...},
                               # midi_clock.{beat_position, bar_position, tempo, transport_state},
                               # studio_ingestion.{music_genre, production_activity, flow_state_score},
                               # vad_state.operator_speech_active
    visual: VisualField        # vision.{per_camera_scenes, detected_action, overhead_hand_zones,
                               #         operator_confirmed, top_emotion, hand_gesture, gaze_direction,
                               #         posture, scene_type, ambient_brightness, color_temperature},
                               # studio_person_detector.per_camera_person_count
    ir: IrField                # ir_presence.{ir_hand_activity, ir_hand_zone, ir_gaze_zone, ir_posture,
                               #              ir_heart_rate_bpm, ir_brightness, ir_person_count,
                               #              ir_screen_looking, ir_drowsiness_score}
    album: AlbumField          # album-identifier.{artist, title, current_track, year, confidence}
    chat: ChatField            # chat_classifier tier counts + recent messages (persistent-state-free)
    context: ContextField      # working_mode, stream_mode, active_objectives, time_of_day,
                               # recent_reactions, active_consent_contracts
    stimmung: StimmungField    # 12 dimensions as floats (not rendered prose)
    presence: PresenceField    # presence_engine.{state, probability}
    stream_health: StreamHealthField  # bitrate, dropped_frames, encoding_lag
```

Every field is populated by an already-existing signal producer enumerated in Agent 2's inventory. Nothing new is measured. The epic's work is (a) building `PerceptualField` as a typed reader that pulls from `perception-state.json` + `/dev/shm/*` + REST, and (b) making it the director's prompt input.

### 3.3 Capabilities catalog for compositional affordances

The `AffordancePipeline` currently recruits capabilities of domains `perception, expression, recall, action, communication, regulation` (`hapax-council/CLAUDE.md §Unified Semantic Recruitment`). This epic adds a *compositional* family within the existing domains (not a new top-level domain). New capabilities, each with a Gibson-verb affordance description embedded in Qdrant `affordances`:

- **Camera hero affordances** (one per camera role × broad context class):
  - `cam.hero.synths-overhead.hardware-active` — "shows the hardware workspace when beats or vinyl claim attention"
  - `cam.hero.operator-brio.conversing` — "shows the operator when conversation is active"
  - `cam.hero.desk-c920.writing-reading` — "shows the desk when focused textual work is happening"
  - `cam.hero.room-brio.ambient` — "shows room ambience when nothing specific is foregrounded"
  - (more per camera × context; the catalog is data-driven)

- **Preset-family affordances**:
  - `fx.family.audio-reactive` — "sound-following visuals; modulate with beat, energy, and spectrum"
  - `fx.family.calm-textural` — "slow field-like visuals for chill or study contexts"
  - `fx.family.glitch-dense` — "high-entropy glitch for intense or seeking stances"
  - `fx.family.warm-minimal` — "warm minimal field for conversation backdrop"
  - Resolves to a *family* of presets; the specific pick is done by the `PresetSelector` (formerly `random_mode`, now biased-selection within the recruited family).

- **Overlay emphasis affordances**:
  - `overlay.foreground.album` — "foreground the album-cover Cairo source when music is the subject"
  - `overlay.foreground.captions` — "foreground the captions strip when narration happens"
  - `overlay.foreground.chat-legend` — "foreground the chat-keyword legend when viewers are new"
  - `overlay.dim.all-chrome` — "dim all chrome overlays for reverent moments"

- **YouTube direction affordances**:
  - `youtube.cut-to` — "cut the hero focus to the current YouTube slot"
  - `youtube.advance-queue` — "pull the next contextually relevant YouTube video"
  - `youtube.cut-away` — "shift focus away from YouTube to live content"

- **Attention winner affordances**: one per bid source in the existing `bidder.py` tie-break list — `attention.winner.code-narration`, `attention.winner.briefing`, `attention.winner.nudge`, `attention.winner.goal-advance`.

- **Stream mode transition**: `stream.mode.public-research.transition`, gated by `shared/stream_transition_gate.py`.

All capabilities register with `OperationalProperties.medium = "visual" | "auditory" | "textual"` and the existing `consent_required` flag where applicable. The `AffordancePipeline.select()` already applies the consent gate; compositional capabilities inherit this.

### 3.4 Three directorial rates

"Highly active" requires moves at three cadences:

| Rate | Cadence | Impl | LLM? |
|------|---------|------|------|
| **Twitch** | 3-5 s | `TwitchDirector` deterministic Python timer | No — reads `PerceptualField`, emits small `CompositionalImpingement`s (e.g., overlay alpha bumps tied to beat_position; effect param nudges tied to desk_energy) |
| **Narrative** | 15-30 s (up from 8 s) | current `DirectorLoop`, expanded output, grounded-model call | Yes — Command R |
| **Structural** | 2-3 min | new `StructuralDirector` | Yes — Command R |

Under the grounding-exhaustive axiom, the Twitch layer is *deterministic code outsourced by a grounding move* — the narrative director declares a stance, and the twitch layer's code modulates compositional parameters within the stance's frame. The twitch layer does not make independent grounding decisions; it implements them.

The narrative director is slowed from 8 s → 15-30 s because the grounded model at ~12-15 T/s can't complete a rich 350-token output in under 30 s reliably (the current 30 s ceiling is tight — see the director timeout pattern we hit 2026-04-17). The perceived rate of activity is compensated by the twitch layer + the narrative director's richer per-tick output.

The structural director produces long-horizon directorial moves (scene shifts, preset-family transitions, YouTube direction). One structural LLM call per ~2-3 min fits cheaply.

### 3.5 Authorship legibility on frame

New Cairo sources render the director's intent visibly:

- **`StanceIndicatorSource`** — always-visible badge (bottom-right corner area, Solarized/Gruvbox-aligned) showing current stance. Changes trigger a brief fade animation. **Uses `Stance` enum — no posture-vocabulary strings.**
- **`ActivityHeaderSource`** — replaces the no-op `set_header`. Shows current activity label + short gloss drawn from the `CompositionalImpingement.narrative` of the highest-salience compositional intent. Medium-prominence header strip.
- **`CaptionsStripSource`** — wires the existing `captions_source.py` into the `default.json` layout with a 1920×120 strip surface. Renders the director's `narrative_text` with fade, respecting the `ex-prose-001` prose constraints.
- **`ChatKeywordLegendSource`** — new Cairo source. Reads the chat-reactor's keyword→preset index and renders a small legend so viewers have participation vocabulary.
- **`GroundingProvenanceTickerSource`** — research-mode-only small diagnostic surface naming the signals that grounded the most recent narrative move (e.g., `▸ turntable · overhead · music_genre:electronic`). Legibility of the research instrument to the research subject (operator) and research-mode viewers.

Typography aligned with `docs/logos-design-language.md` §1.6; palette aligned with §3 and working-mode modulation.

### 3.6 Research observability

Every `DirectorIntent` is written to:

- `~/hapax-state/stream-experiment/director-intent.jsonl` — append-only, flushed per tick. Fields: timestamp, condition_id, activity, stance, grounding_provenance, compositional_impingements (summarized), narrative_text-hash.
- Langfuse span `stream.reaction` (existing) with metadata extended: `grounding_provenance_count`, `compositional_impingement_count`, `twitch_moves_in_tick`, `structural_active`.
- Prometheus gauges (extends Phase 10 per-condition slicing): `hapax_director_intent_total{condition_id, activity, stance}`, `hapax_director_grounding_signal_count{condition_id, signal_name}`, `hapax_director_palette_coverage{condition_id, family}`.

Downstream consumers (RIFTS, MCMC BEST, palette-coverage dashboard) read these. The epic adds the emission; consumers adapt gradually.

## 4. Non-goals

- Changing the LLM substrate (Command R stays).
- Introducing multi-user / viewer-identity tracking (`single_user` axiom).
- Building new sensors (the wrench is wiring the existing classifiers, not adding more).
- Bypassing `AffordancePipeline` for new "moves" (unified-recruitment commitment).
- Replacing imagination / reverie / stimmung — they remain substrate; the director modulates.
- Migrating off Cairo / GStreamer / wgpu.
- Shipping HSEA Phase 9 revenue drafting (that's its own spec; this epic aligns but does not advance revenue surface).
- Real-time speaker diarization, real-time music identification beyond what `album-identifier.py` already does.

## 5. Phases

Ten phases, serial execution; each lands as a commit block on `volitional-director` branch / PR #1017. Phase 0 already shipped.

### Phase 0 — Reverie RGBA→BGRA byte-order fix *(shipped, commit 2377fee66)*

Acute fix: wgpu writes `Rgba8Unorm` to `reverie.rgba`; cairo reads it as `ARGB32` (BGRA in LE). Swap R↔B in `write_side_output`. Unblocks the top-right reverie quadrant from rendering solid blue.

### Phase 1 — Director intent signature expansion + prompt caching

**Intent:** director output becomes `DirectorIntent` per §3.1 with grounding_provenance; adopts HSEA Phase 2 13-activity vocabulary; LiteLLM `cache_control` on the stable system-prompt prefix to recoup the ~$2k/mo prompt-cache gap (`docs/research/2026-04-14-director-loop-prompt-cache-gap.md`).

**Files touched:**
- Create: `shared/director_intent.py` (Pydantic models)
- Modify: `agents/studio_compositor/director_loop.py` (_build_unified_prompt, _call_activity_llm, _act_on_intent)
- Modify: prompt composer to include 13-activity vocabulary
- Create: `tests/studio_compositor/test_director_intent.py`

**No-goals for this phase:** no actual compositional impingement emission yet — that's Phase 3. Phase 1 produces the richer intent internally and logs it; downstream wiring is Phase 3.

### Phase 2 — Structured PerceptualField in director prompt

**Intent:** stop collapsing to stimmung prose. Director reads `PerceptualField` per §3.2. Agent 2's full inventory feeds structured fields.

**Files touched:**
- Create: `shared/perceptual_field.py` (Pydantic models + JSON-loader)
- Modify: `agents/studio_compositor/director_loop.py::_build_unified_prompt` to serialize `PerceptualField.model_dump_json()` as the environmental context block.
- Create: `tests/studio_compositor/test_perceptual_field_reader.py`

**No-goals:** no new sensors, no classifier changes.

### Phase 3 — Compositional recruitment via AffordancePipeline (retire the shufflers)

**Intent:** director emits `CompositionalImpingement`s per §3.1; AffordancePipeline recruits capabilities from the catalog in §3.3; the three shufflers are removed or demoted to fallbacks.

**Files touched:**
- Create: `shared/affordances/compositional/` — capability classes per §3.3 (camera.hero.*, fx.family.*, overlay.foreground.*, youtube.direction.*, attention.winner.*).
- Create: seed script to embed the capability descriptions in Qdrant `affordances` collection.
- Modify: `agents/studio_compositor/random_mode.py` — demoted: runs only when no `fx.family.*` affordance has been recruited in the last N seconds (fallback).
- Modify: `agents/studio_compositor/director_loop.py::_reload_slot_from_playlist` — routes through `youtube.direction.*` recruitment (falls back to `random.choice` if no `youtube.direction.advance-queue` recruitment).
- Retire: `agents/studio_compositor/objective_hero_switcher.py::hero_for_active_objectives` hardcoded map — replaced by `cam.hero.*` recruitment; the function remains as a pure-data helper for activity→camera affinity, but the dispatch happens through the pipeline.
- Modify: `agents/attention_bids/bidder.py` / `dispatcher.py` — wire `dispatch_bid(winner)` invocation on `attention.winner.*` recruitment.
- Create: `tests/affordances/test_compositional_recruitment.py`

**Sub-phase 3a — capability seeding.** Write embedding-ingest script; seed Qdrant; verify retrieval.
**Sub-phase 3b — director intent → impingement emission.** Director writes to `/dev/shm/hapax-dmn/impingements.jsonl` (existing stream).
**Sub-phase 3c — compositor consumer.** The pipeline's existing capability-activation path drives the compositor's layout mutations.

### Phase 4 — Legibility layer

**Intent:** the output frame visibly shows Hapax directing. Fix `set_header`, add stance indicator + captions + chat legend + grounding ticker.

**Files touched:**
- Modify: `agents/studio_compositor/sierpinski_loader.py:116` — implement `set_header` as a real call into `ActivityHeaderCairoSource.update(text)`.
- Create: `agents/studio_compositor/cairo_sources/stance_indicator.py`
- Create: `agents/studio_compositor/cairo_sources/activity_header.py`
- Create: `agents/studio_compositor/cairo_sources/chat_keyword_legend.py`
- Create: `agents/studio_compositor/cairo_sources/grounding_provenance_ticker.py`
- Modify: `agents/studio_compositor/captions_source.py` — unchanged internally; added to layout.
- Modify: `config/compositor-layouts/default.json` — adds 4 new Cairo sources + surfaces + assignments; captions strip geometry.
- Create: `tests/studio_compositor/test_cairo_sources_legibility.py`

**Typography pass:** per-source text rendering aligned with `docs/logos-design-language.md` §1.6.

### Phase 5 — Multi-rate directorial hierarchy

**Intent:** split into twitch / narrative / structural per §3.4. Narrative director slowed 8 s → 20 s; twitch layer deterministic code at 4 s; structural LLM call at 150 s.

**Files touched:**
- Create: `agents/studio_compositor/twitch_director.py` (deterministic, no LLM)
- Create: `agents/studio_compositor/structural_director.py` (LLM-backed, 150 s cadence)
- Modify: `agents/studio_compositor/director_loop.py::PERCEPTION_INTERVAL` from 8.0 → 20.0
- Modify: `agents/studio_compositor/sierpinski_loader.py::_start_director` to start all three loops
- Create: `tests/studio_compositor/test_twitch_director.py`, `test_structural_director.py`

**Twitch moves (sample):** beat-synchronized overlay alpha pulses; desk-energy-mapped effect param nudges; motion-delta-mapped ambient-camera micro-emphasis. All within the currently-declared stance frame.

### Phase 6 — Consent-gate on live-video egress

**Intent:** close the gap Agent 2 flagged — live-video egress does not currently block on guest detection. When a non-operator face is detected without an active consent contract, compose-safe fallback applies to the stream output, not only to Qdrant/RAG writes.

**Files touched:**
- Modify: `agents/studio_compositor/consent.py` — extend beyond recording valve to layout mutation (swap-in of "consent-safe" layout variant; replacement of operator/room cameras with lower-risk compositions; captions strip adds consent-state banner).
- Modify: `agents/studio_compositor/state.py::state_reader_loop` — trigger compose-safe layout on `consent_phase ∈ {guest_detected, consent_pending, consent_refused}`.
- Create: `config/compositor-layouts/consent-safe.json` — fallback layout (no camera feeds except operator-only if self-consent implied; reverie + cairo chrome only).
- Create: `tests/studio_compositor/test_consent_live_egress_gate.py`

**Axiom enforcement:** `it-irreversible-broadcast` T0 — this closes the remaining exposure surface.

### Phase 7 — Research observability

**Intent:** §3.6 — director-intent.jsonl, Langfuse span metadata, Prometheus gauges.

**Files touched:**
- Create: `shared/director_observability.py` — append-only JSONL writer, Prometheus metric emit.
- Modify: `agents/studio_compositor/director_loop.py` — call observability on each intent.
- Modify: Langfuse span metadata in `_call_activity_llm`.
- Create: `config/prometheus/alerts/director-intent.yml`
- Create: Grafana dashboard JSON for palette coverage + grounding-signal distribution.
- Create: `tests/shared/test_director_observability.py`

### Phase 8 — DEVIATION record + new condition declaration

**Intent:** this epic substantially changes director behavior mid-Phase-A. File a DEVIATION or declare `cond-phase-a-volitional-director-001` per LRR Phase 1 research-registry protocol.

**Files touched:**
- Create: `research/deviations/2026-04-17-volitional-director.md` — DEVIATION record with rationale, scope, rollback plan.
- Modify: `research/registry.jsonl` — add `cond-phase-a-volitional-director-001` condition entry.
- Update: `agents/hapax_daimonion/proofs/RESEARCH-STATE.md` — reflect new condition.

**Scope note:** this phase blocks the epic's activation until operator consents to the DEVIATION. The operator's 2026-04-17 directive ("execute without intervention, we can always adjust later") implies pre-authorization; file the DEVIATION anyway for audit trail.

### Phase 9 — Visual audit + rehearsal

**Intent:** per `docs/research/2026-04-17-expected-behavior-at-launch.md §4`, 30-minute private rehearsal before public research mode. Per-mode visual preview (private / public / public_research / fortress) sweep.

**Files touched:**
- Create: `scripts/rehearsal-capture.sh` — captures 30 min of frame-dumps + director-intent jsonl + stimmung state for post-hoc audit.
- Create: `docs/research/2026-04-17-volitional-director-rehearsal-results.md` — audit template filled post-rehearsal.

**Gate criteria (from launch doc §4):**
- Activity distribution within prediction ±10% ✓
- Persona coherence (no posture strings in prose) ✓
- Overlay visual audit at 1920×1080 (no collisions) ✓
- TTS quality over music (ducker works, no popping) ✓
- No stacktraces in the 30-min window ✓

If all pass, mode transitions to `public_research` and the public-ish rehearsal with consented peers (`agatha`, `simon`) is scheduled.

## 6. Classification / detection inventory

Complete enumeration from Agent 2's report. Each row is a signal producer; column 2 is whether Phase 2 exposes it as a first-class field in `PerceptualField`.

| Signal producer | File | Into `PerceptualField`? |
|-----------------|------|---|
| Pi NoIR YOLOv8n person + head_pose + gaze_zone + posture | `pi-edge/ir_inference.py` | `ir.persons[]` |
| Pi NoIR hand zone + activity | `pi-edge/ir_hands.py::detect_hands_nir` | `ir.hands[]` |
| Pi NoIR screen detection | `pi-edge/ir_hands.py::detect_screens_nir` | `ir.screens[]` |
| Pi-6 overhead album-cover detection (IR) | `pi-edge/ir_album.py` | `album.overhead_visible` |
| Pi NoIR rPPG biometrics | `pi-edge/ir_biometrics.py` | `ir.biometrics` |
| Studio RGB YOLOv8n per-camera person detection | `agents/studio_person_detector.py` | `visual.per_camera_person_count` |
| Vision: YOLO11n objects | `agents/hapax_daimonion/backends/vision.py` | `visual.detected_objects` |
| Vision: YOLO11m-pose → posture | same | `visual.posture` |
| Vision: SCRFD operator_confirmed | `agents/hapax_daimonion/face_detector.py` | `visual.operator_confirmed` |
| Vision: gaze direction | `vision.py::_run_gaze_estimation` | `visual.gaze_direction` |
| Vision: HSEmotion emotion class | `vision.py::_run_emotion_recognition` | `visual.top_emotion` |
| Vision: MediaPipe hand gesture | `vision.py::_run_hand_gesture` | `visual.hand_gesture` |
| Vision: MediaPipe overhead hand zones | `vision.py::_run_overhead_hand_zones` | `visual.overhead_hand_zones` |
| Vision: SigLIP2 zero-shot scene | `vision.py::_run_scene_classification` | `visual.per_camera_scenes` |
| Vision: ambient_brightness / color_temperature | `vision.py` | `visual.ambient_brightness`, `visual.color_temperature` |
| Vision: cross-modal `detected_action` | `vision.py::_infer_cross_modal_activity` | `visual.detected_action` |
| Vision: SceneInventory | `vision.py` | `visual.scene_inventory` |
| Studio CLAP music_genre + production_activity + flow_state_score | `studio_ingestion.py` | `audio.music_genre`, `audio.production_activity`, `audio.flow_state_score` |
| Contact mic desk_activity + energy + onset_rate + spectral_centroid + autocorr + tap_gesture | `contact_mic.py` | `audio.contact_mic.*` |
| Contact mic × IR fused activity | `contact_mic_ir.py` | `audio.fused_activity` |
| Silero VAD operator_speech_active | `vad_state_publisher.py` | `audio.vad_speech_active` |
| MIDI clock beat / bar / tempo / transport | `midi_clock.py` | `audio.midi.*` |
| Stream health bitrate / dropped / lag | `stream_health.py` | `stream_health.*` |
| Album identifier artist/title/track | `scripts/album-identifier.py` → `album-state.json` | `album.artist`, `album.title`, `album.current_track` |
| Chat classifier 7-tier | `agents/studio_compositor/chat_classifier.py` | `chat.tier_counts` (aggregated, no author) |
| Presence engine state + probability | `presence_engine.py` | `presence.*` |
| Stimmung 12-dim state | `/dev/shm/hapax-stimmung/state.json` | `stimmung.*` (as dict of floats, not prose) |
| Working mode | `~/.cache/hapax/working-mode` | `context.working_mode` |
| Stream mode | `shared/stream_mode.py` | `context.stream_mode` |
| Active consent contracts | `axioms/contracts/` | `context.active_consent_contracts` |
| Active research objectives | `~/Documents/Personal/30-areas/hapax-objectives/obj-*.md` | `context.active_objectives` |

Coverage: every classifier/detector produced in the system is exposed to the director. No new sensors added.

## 7. Economic / revenue alignment

Per-operator directive ("making a lot of money in the process" as a secondary concern): the epic does not advance the revenue surface directly. HSEA Phase 9 is the spec for revenue-preparation and owns it (`docs/superpowers/specs/2026-04-15-hsea-phase-9-revenue-preparation-design.md`). This epic's alignment:

- The richer director (legible host, clear stance, varied composition, grounded-in-environment) **raises the per-minute attention-value** of the stream — a prerequisite for sponsorship/grant/consulting drafting to have anything to reference.
- `grounding_provenance` logging in Phase 7 observability also produces the research-quality artifacts HSEA Phase 9 sponsor-copy and NLnet grant drafters will cite.
- No direct revenue code in scope; no monetization gates added.

The revenue direction remains "Hapax prepares, operator delivers" per `sp-hsea-mg-001` precedent. This epic preserves that.

## 8. Testing strategy

Per-phase tests are listed in §5. Cross-cutting:

- **Regression pins** — Phase 0 BGRA swap test; Phase 4 `set_header` now produces visible output; captions_source in layout; consent-gated layout switch fires on guest_detected.
- **Integration test** — end-to-end with mock signals (PerceptualField fixture), drive director through one full tick, assert DirectorIntent is emitted with expected grounding_provenance, impingements are written to dmn stream, AffordancePipeline recruits expected capabilities, compositor applies expected layout mutation.
- **Live smoke** — after each phase lands + imagination rebuilds + compositor restarts, visual capture from `/dev/video42` and manual audit.

## 9. Rollback plan

Each phase lands on `volitional-director` branch. Rollback = revert the phase's commit(s). For runtime rollback (if something breaks on live stream):
- Phase 0: revert `output.rs` swap → reverie goes back to blue quadrant (ugly but non-fatal).
- Phases 1-3: `HAPAX_DIRECTOR_MODEL_LEGACY=1` env flag short-circuits back to the pre-epic `{activity, react}` emission path (implement this flag as part of Phase 1).
- Phase 4: `HAPAX_COMPOSITOR_LAYOUT=default-legacy.json` env selects the pre-epic layout.
- Phases 5-7: stop the new systemd units (twitch/structural directors); narrative director falls back to 8 s cadence.

## 10. Dependencies and conflicts

- **HSEA Phase 2 activity extension** — adopted wholesale; Phase 1 pulls the 13-activity vocabulary in. No conflict; this is cohabitation.
- **Phase 8 content programming via objectives** — unchanged; this epic refines how objective-advancement scoring informs stance/intent, doesn't replace it.
- **Phase 9 closed-loop feedback** — audience_engagement dim stays; stimmung feed into PerceptualField.stimmung is backwards-compatible.
- **Phase 10 observability** — extended; per-condition Prometheus slicing maintained, new labels added.
- **LRR Phase 7 persona activation 14-day window** — active since 2026-04-17T13:58Z, earliest PR date for cleanup is 2026-04-30. This epic must not touch persona during that window.
- **`cond-phase-a-persona-doc-qwen-001`** — director changes mid-collection need DEVIATION (Phase 8 of this epic).
- **PR #1017** — this epic's PR. Accumulates commits per phase.

## 11. Success criteria

**Mechanical:**
- All 13 containers + host services stay healthy through a 30-min rehearsal.
- No director timeouts in the rehearsal window.
- Reverie quadrant renders operator-perceivable content (not blue).
- Captions visible.
- Stance indicator + activity header visible and updating.

**Grounding:**
- 100% of `DirectorIntent`s carry ≥1 `grounding_provenance` signal drawn from `PerceptualField`.
- ≥80% of stance/activity transitions trace to at least one concurrent signal change (grounding rate proxy).
- Turntable test: operator plays vinyl → within ≤30 s the narrative director has chosen a camera hero aligned with the `overhead_hand_zones.turntable` signal, the stance is `NOMINAL` (or `SEEKING` if desk+audio disagree), and the captions/activity header narrate the grounding.

**Legibility:**
- Blind-audit of 1-minute stream clips by operator or `agatha`/`simon`: ≥3 distinct directorial moves identifiable per minute (structural 0-1 + narrative 2-3 + twitch modulations visible).
- Consent-safe layout auto-switches within 5 s of a second face appearing without active contract.

**Research:**
- DEVIATION filed for `cond-phase-a-persona-doc-qwen-001` or new condition declared.
- All `DirectorIntent`s logged to `~/hapax-state/stream-experiment/director-intent.jsonl`.
- Palette-coverage dashboard shows ≥4 distinct affordance families recruited per 10-minute window.

## 12. Research-condition declaration

On Phase 8 land, declare **`cond-phase-a-volitional-director-001`**. Phase A data collection continues under the original condition until this declaration lands; afterwards the stream runs under the new condition. The new condition's delta-description cites this design spec and enumerates the director-behavior changes (intent structure, perceptual field input, impingement emission, multi-rate hierarchy, legibility layer). The MCMC BEST analysis may require splitting the sample by condition.

## 13. Open questions

- **Camera role taxonomy gap.** `objective_hero_switcher.py:46` maps `vinyl→hardware`, but "hardware" is not a declared camera role. Resolution in Phase 3: the `cam.hero.*` affordance catalog uses actual camera roles (`synths-brio`, `overhead`, etc.); the old activity→role map is retired.
- **HSEA Phase 2 activation sequencing.** If Phase 2 activates mid-epic, the 13-activity vocabulary landed here needs reconciliation. Expectation: HSEA Phase 2 activation waits on this epic's Phase 1 to land the Pydantic model, then HSEA Phase 2 fills in the `ReflectiveMomentScorer` + calibration window.
- **Posture vocabulary drift risk.** The posture vocabulary is glossary-only; if the director's `narrative_text` starts leaking posture names because the LLM has seen the document, we need a prompt-hygiene test. Add to Phase 1 test suite.
- **Twitch director contention.** If twitch moves emit impingements at 4 s cadence and narrative emits at 20 s, pipeline recruitment may oscillate. Phase 5 includes a debounce / minimum-dwell check per recruited family.
- **DMN impingement-stream cross-consumption.** Phase 3 emits CompositionalImpingements to `/dev/shm/hapax-dmn/impingements.jsonl`, which is ALSO read by daimonion (voice) and reverie (mixer). A CompositionalImpingement with a narrative like "the turntable is active" could plausibly be recruited by a daimonion voice affordance. This is consistent with unified-recruitment, but may produce vocal responses that weren't intended by the compositor. Mitigation: compositor-origin impingements carry `source="director-compositional"` metadata; daimonion's recruitment path filters to only voice-domain affordances and would not recruit compositional capabilities. Verify during Phase 3 integration testing.
- **TabbyAPI contention under multi-rate.** Narrative (20 s) + structural (150 s) + imagination-loop (~30 s) + daimonion voice all hit one TabbyAPI instance. Worst-case three-concurrent scenario: 3 × 25 s = 75 s per round-trip if fully queued. Mitigation: structural offset by 10 s from narrative edge; imagination unchanged. If measured p95 exceeds 30 s, escalate to either (a) batch merging, (b) reducing structural cadence, or (c) giving narrative a LiteLLM priority queue label.

## 14. Changelog

- 2026-04-17 (alpha) — initial draft, revised after 3-agent research sweep absorbed.
