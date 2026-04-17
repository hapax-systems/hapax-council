# Volitional Director Epic 2 — Hothouse Execution Plan

**Context:** Epic 1 (PRs #1017 + #1018) shipped DirectorIntent + PerceptualField + compositional catalog + legibility surfaces + multi-rate hierarchy + observability + DEVIATION-037. Three audit agents identified real gaps, and operator 2026-04-17 flagged critical experiential gaps:

> no evidence of director / no variety or changes /
> evidence of directorial/host nature and presence should be unavoidable /
> even if there is no YouTube audience *I* am here /
> there should be evidence of ALL recruitment potential and impingement pressure /
> the livestream should be a hot house of engaging pressure that forces Hapax into impetus and action /
> symbols and text and proximity are fodder for grounding and raw interpretive material

**Goal of Epic 2:** close every gap between Epic 1's logic layer and the operator's lived experience of the stream. The hot-house principle: the stream must be a legible, continuously-engaging interpretive field that exerts pressure back on Hapax, not a calm reactive render path.

**Branch:** `vd-epic-2-hothouse`

---

## Phase A — P0 axiom hygiene (prerequisite)

A1. **Posture leak fixed** — `structural_director.py::SceneMode` renamed `research-foregrounded` → `research-primary`. (DONE pre-plan.)

A2. **Consent live-egress fail-closed.**
- `consent_live_egress.should_egress_compose_safe`: change `getattr(…, None)` to attribute access that raises if the field is missing (uses Pydantic model access).
- `models.OverlayData.persistence_allowed` default `True → None`; `_read_perception_state` stale-flag wired into the predicate (stale → compose-safe).
- `test_all_fields_none_is_safe` reversed: missing state fails *closed*, broadcasts stop.
- `HAPAX_CONSENT_EGRESS_GATE=0` env actually implemented (disable flag mentioned in runbook but unbound).

A3. **Dead code / broken imports.**
- `compositional_consumer.dispatch_attention_winner` imports `agents.attention_bids.dispatcher.dispatch_recruited_winner` which doesn't exist — define it or remove the call.
- `shared/compositional_affordances.py` comments reference `preset_family_selector.py` which doesn't exist — create it (simple weighted-random selector within a family) OR drop the reference.
- Remove `research/registry.jsonl` mention from spec (canonical registry lives elsewhere).

A4. **Parse-failure metric wiring.** `emit_parse_failure` defined but never called. Hook into `_parse_intent_from_llm` so rollback criterion "≥5 parse failures per 10 min" is measurable.

A5. **Legacy flag decouple.** `HAPAX_DIRECTOR_MODEL_LEGACY=1` currently skips ALL emissions (JSONL + narrative-state + Prometheus + DMN impingements), contradicting master-plan claim. Decouple: keep intent parsing + narrative-state writes; skip only the compositional impingement emission + prompt enrichment. Observability must survive rollback.

A6. **Prometheus cardinality whitelist.** `grounding_signal_used_total.signal_name` is LLM-free-text. Whitelist against known `PerceptualField` paths at emit time; anything else is bucketed as `signal_name="unrecognized"`.

A7. **Posture-hygiene regression test.** Automated: walk every LLM-prompt string in `director_loop.py` + `structural_director.py` and assert no posture-vocabulary tokens appear. Pin against `axioms/persona/posture-vocabulary.md` parsed at test time.

A8. **Default-legacy layout.** Create `config/compositor-layouts/default-legacy.json` as a frozen snapshot of the pre-epic layout so `HAPAX_COMPOSITOR_LAYOUT=default-legacy.json` rollback works.

## Phase B — Close the closed loop

B1. **Pipeline consumer for compositor-origin impingements.** In daimonion's `run_loops_aux.impingement_consumer_loop` (or a sibling), add a branch that routes `impingement.source == "studio_compositor.director.compositional"` to `compositional_consumer.dispatch`. Scoring + Thompson + consent gate from the pipeline still apply.

B2. **Compositor-layer SHM consumers.** Five writer-only files need readers:
- `hero-camera-override.json` → compositor reads on layout tick, swaps main-slot camera source.
- `overlay-alpha-overrides.json` → `CairoSourceRunner` or the compositor's assignment applier reads per-source alpha overrides and applies over baseline.
- `youtube-direction.json` → `_reload_slot_from_playlist` + a new `_honor_youtube_direction` check the file and act (`cut-to`, `advance-queue`, `cut-away`).
- `stream-mode-intent.json` → `shared.stream_transition_gate` reads and evaluates.
- `recent-recruitment.json` → `random_mode.run` reads `recent_recruitment_age_s("preset.bias")` and skips uniform-random pick when a family was recruited recently.

B3. **End-to-end integration test.** Synthesize a PerceptualField fixture where operator is at turntable + MIDI playing + album identified; feed the director; assert cam.hero recruitment + overlay foreground + preset bias all fire.

B4. **Consent-aware dispatch.** Consumer reads `consent-safe-active.json` before dispatching `cam.hero.*` or `stream_mode.*`; rejects those families in compose-safe state.

## Phase C — Make directorial presence unavoidable (hothouse)

This is the operator's "evidence of all recruitment potential and impingement" directive.

C1. **ImpingementCascadeCairoSource.** New Cairo surface, right side or bottom of canvas. Live readout of the top N active perceptual signals + their values + which affordance families they'd most likely recruit. Updates at 2fps. Two visual modes:
- **Compact** — 5 lines, "signal → likely recruitment family." Used when not interesting to look at.
- **Expanded** — 10-15 lines, with cosine scores against top-3 candidate affordances. When the director loop is mid-tick, expanded mode shows what's being considered in real time.

C2. **RecruitmentCandidatePanelCairoSource.** Small panel: the last 3 recruited capabilities + scores. "cam.hero.overhead.vinyl-spinning @ 0.87" etc. Updates on recruitment event.

C3. **ThinkingIndicatorCairoSource.** Small animated indicator: dot that pulses while an LLM tick is in flight (narrative OR structural). Lights up from the moment `_call_activity_llm` starts until it returns. Makes the cognitive work visible.

C4. **PressureGaugeCairoSource.** Shows the current "impingement pressure": how many signals are active above threshold, how saturated the perceptual field is. Operator sees the field filling up over time (pressure rising) then discharging when a move fires.

C5. **Activity variety log.** Bottom-left ribbon: last N narrative/structural/twitch activities, fading out. So even when current activity is `silence`, viewers see the recent dance of moves.

C6. **LLM call latency + model indicator.** Next to thinking indicator: "Command R · 14.2s" during a call; vanishes when idle. Legibility of the substrate.

## Phase D — Operator-as-audience framing

D1. **Dual-audience acknowledgement.** `PerceptualField.context.audience` becomes a structured field: `{"operator_present": bool, "external_viewers": int, "effective_stream_mode": str}`. The predicate "operator is here" is ALWAYS `True` when `presence.state == "PRESENT"`.

D2. **Private-mode legibility retention.** When `stream_mode == "private"`, all legibility surfaces still render to operator-only outputs (v4l2 loopback + imagination frame). RTMP + HLS are gated but the OPERATOR sees everything. Verify and make explicit.

D3. **"Who's here" indicator.** Small Cairo surface: "♦ operator (always) · ● 3 external (YouTube)" or "♦ operator (solo)". Small, top-right under stance indicator. Makes the dual-audience reality legible.

D4. **Operator-directed moves.** Director prompt gets an additional context block: "the operator is always present; even when external_viewers=0 your moves are seen." Removes the subtle "nobody's watching" implicit assumption.

## Phase E — Cadence + pressure increase

E1. **Narrative cadence 20s → 12s.** Watch Command R latency under the hood — 12s cadence means LLM calls must fit in <8s to leave buffer. Spec said 15-30s range; 12s is on edge but fits the hothouse directive.

E2. **TwitchDirector rule expansion.**
- Idle → emit `overlay.emphasis` moves every 10-15s (gentle variation).
- Pressure → if >N signals active, emit compositional impingement with high salience to force narrative director's hand.
- Beat-sync for ALL overlays on music activity (not just album).
- Hand-zone cycling — as operator moves between zones, emit one impingement per zone change with camera.hero bias.
- Chat-arrival pulse — on new chat message, emit `overlay.foreground.captions` pulse regardless of other state.

E3. **Structural cadence 150s → 90s.** More frequent long-horizon moves.

E4. **PressureAccumulator.** New module. Tracks how many ticks since last meaningful composition change. If exceeded, force a move at narrative's next tick (bias the prompt: "the stream has been static for 2 minutes; pick a move.").

E5. **Non-operator-triggered moves.** Most current moves are reactive to operator signals. Add PROACTIVE moves: every ~30-45s do *something* visual regardless of state (aesthetic variation pulse). Not random — guided by structural intent.

## Phase F — Aesthetic polish + layer relationships

F1. **Typography systematization.**
- Headers (activity): IBM Plex Mono Bold — machine register
- Captions: IBM Plex Sans — body register
- Stance + ticker: IBM Plex Mono Regular — telemetric
- Legend: IBM Plex Sans Medium — discoverable
Install fonts if not present; fall back gracefully.

F2. **Color resonance.** When album cover dominates warm tones (reds/oranges), chrome shifts slightly warmer. When cool, cooler. A 5s-smoothed palette pull from the album-cover PNG + chrome color overrides. One new module `agents/studio_compositor/color_resonance.py`.

F3. **Proximity grouping.** Move captions near album art (bottom-left cluster instead of full-width bottom). Activity header pairs with stance. Grounding ticker goes under the activity cluster. Spatial hierarchy expresses semantic hierarchy.

F4. **Animation.** Fade in on activity change (200ms). Stance dot pulses gently. Thinking indicator breathes. Captions slide in from right. Not flashy — a felt sense of liveness.

F5. **Symbol reinforcement.** Vitruvian man's ratios echoed in Sierpinski geometry params. Album color passed into reverie uniforms as a bias. A light "signature field" — when Hapax is author-foregrounded, the surface gently signs itself.

F6. **Per-stream-mode visual distinction.** `private`/`public`/`public_research`/`fortress` each get a distinct chrome color + border treatment. Legibility that the current mode is visually clear.

F7. **Operator-facing dashboard surface.** A private-only Cairo source (conditional on stream_mode=="private") that shows a richer diagnostic panel on the v4l2 loopback. External viewers never see it; operator can when working alone.

## Phase G — Audit-remainder fixes

G1. Create `config/compositor-layouts/default-legacy.json` (snapshot of pre-epic shape). Rollback flag.

G2. Prometheus label whitelist on `grounding_signal_used_total` — map LLM-emitted signal name to a controlled vocabulary before incrementing.

G3. Grafana dashboard JSON for palette coverage + grounding-signal distribution.

G4. File rotation for JSONL streams (rotate when >5 MB, keep last 3).

G5. `_parse_intent_from_llm` cleanly propagates validation errors with `emit_parse_failure` + optional debug dump of the bad response for later diagnosis.

## Phase H — Integration + deploy + capture

H1. End-to-end test harness: fixture sequence of 5 minutes of synthetic PerceptualField states covering turntable / coding / chat / away / conversation. Assert expected cascade of director intents + recruitments + compositor mutations + visible frame deltas.

H2. Restart services; capture 30-second clip; visual audit.

H3. PR + merge.

---

## Execution protocol

Each phase lands as a commit on `vd-epic-2-hothouse`. Phases can ship independently but order matters: A before all, B before C/D wire-up, F can run parallel with E.

Tests first where sensible. Commit granularity: ~one logical component per commit, commit messages with the axiomatic/epic rationale.

Rollback flags preserved: every new behavior additive behind a clear env toggle where the surface is non-trivial.

## Self-audit checklist (run before Phase A executes)

1. Every operator directive from 2026-04-17 has a target phase.
2. Every audit finding (consistency / robustness / axiom agents) has a target fix.
3. No plan step requires infrastructure that doesn't exist.
4. Rollback paths preserved.
5. P0 axiom findings are ALL in Phase A.
6. Phase C directly addresses "evidence of recruitment potential and impingement pressure."
7. Phase D addresses "I'm always here even when YT isn't."
8. Phase F addresses "more polish, interesting relationships, proximity as interpretive material."
