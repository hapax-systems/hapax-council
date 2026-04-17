# Phase 5 — Multi-Rate Directorial Hierarchy

**Spec:** §3.4, §5 Phase 5
**Goal:** Three directorial rates running in parallel — twitch (4 s deterministic Python), narrative (20 s grounded LLM; slowed from 8 s), structural (150 s grounded LLM). Twitch is code-outsourced-by-a-grounding-move per the grounding-exhaustive axiom; narrative + structural are LLM-grounded.

## File manifest

- **Create:** `agents/studio_compositor/twitch_director.py` — deterministic, no LLM.
- **Create:** `agents/studio_compositor/structural_director.py` — LLM-backed, 150 s cadence.
- **Create:** `shared/structural_intent.py` — `StructuralIntent` Pydantic (coarser than DirectorIntent: scene_mode, preset_family_hint, long_horizon_direction).
- **Modify:** `agents/studio_compositor/director_loop.py::PERCEPTION_INTERVAL` 8.0 → 20.0.
- **Modify:** `agents/studio_compositor/sierpinski_loader.py::_start_director` — spawn all three director threads.
- **Create:** `tests/studio_compositor/test_twitch_director.py` + `test_structural_director.py`.

## TwitchDirector behavior (code-only, no LLM)

Reads `PerceptualField` (same as narrative). Emits small `CompositionalImpingement`s with constrained `intent_family` values (only `overlay.emphasis`, `preset.bias` subtle param nudges). Does NOT emit `camera.hero.*` or `stream_mode.transition` — those are narrative/structural.

Rules (deterministic code):
- If `audio.midi.transport_state == PLAYING` and `audio.midi.beat_position` just incremented: pulse `overlay.foreground.album` by bump-down-then-up alpha (≤ 200 ms transient).
- If `audio.contact_mic.desk_activity == "drumming"` and desk_energy is high: emit `preset.bias` favoring `fx.family.audio-reactive` with a 10 s dwell bias.
- If `visual.detected_action == "away"` for &gt;30 s: emit `overlay.dim.all-chrome`.
- If `ir.ir_hand_zone == "turntable"`: emit brief `overlay.foreground.album` pulse.
- If `stream_health.dropped_frames_pct &gt; 0.05`: emit `overlay.dim.all-chrome` plus a diagnostic flash to the provenance ticker.

Narrative director's stance acts as a gate. TwitchDirector:
- Reads the latest narrative stance from the narrative director's state file.
- In `CAUTIOUS` or `CRITICAL` stance: disabled (no twitch emissions).
- In `SEEKING`: enabled at higher rate (3 s cadence).
- Default `NOMINAL`: 4 s cadence.

## StructuralDirector behavior

LLM-backed, Command R via LiteLLM, 150 s cadence. Shorter prompt than narrative director — only context + stimmung overall + active objectives + recent stance/activity history.

Output: `StructuralIntent`:
- `scene_mode` ∈ `{"desk-work", "hardware-play", "conversation", "idle-ambient", "mixed", "research-foregrounded"}` (distinct from stance; longer-horizon).
- `preset_family_hint` ∈ `{"audio-reactive", "calm-textural", "glitch-dense", "warm-minimal"}` — hint to narrative/twitch.
- `long_horizon_direction` (str) — free-form 1-2 sentence direction the narrative director reads as context on its next tick.

Structural director emits its `StructuralIntent` as a *context enrichment* for the narrative director (via a shared state file), not as impingements directly. This keeps structural moves slow and coherent across multiple narrative ticks.

## Tasks

- [ ] **5.1** — Implement `twitch_director.py`. Single-thread loop with sleep(interval). Reads narrative's stance state file before each tick. Writes impingements directly to `/dev/shm/hapax-dmn/impingements.jsonl` with `intent_family ∈ {overlay.emphasis, preset.bias}`.
- [ ] **5.2** — Write tests: (a) beat-synced overlay pulse happens on beat_position increment; (b) CAUTIOUS stance disables twitch; (c) turntable hand zone triggers album pulse; (d) no camera.hero emissions ever.
- [ ] **5.3** — Implement `structural_intent.py` Pydantic.
- [ ] **5.4** — Implement `structural_director.py`. LLM call via LiteLLM `local-fast`, prompt has `PerceptualField` SLOW-tier-equivalent summary plus active objectives. Same prompt-cache_control. Same observability (appends to `~/hapax-state/stream-experiment/structural-intent.jsonl`).
- [ ] **5.5** — Write state-file consumer in `director_loop.py`: read latest structural intent from `/dev/shm/hapax-structural/intent.json` before each narrative tick; surface it as a context block in the narrative director's prompt ("Current structural direction: {long_horizon_direction}").
- [ ] **5.6** — Change `PERCEPTION_INTERVAL = 8.0` → `20.0` in `director_loop.py`.
- [ ] **5.7** — Modify `sierpinski_loader.py::_start_director` to spawn TwitchDirector and StructuralDirector threads (daemon=True).
- [ ] **5.8** — End-to-end test: simulate a full 5-minute cycle (fixture PerceptualField evolving), assert twitch fires ≥50 times, narrative ≥12 times, structural ≥1-2 times, and structural intent's `long_horizon_direction` appears in narrative's next prompt.
- [ ] **5.9** — Commit in 3 commits:
  - `feat(director): TwitchDirector — deterministic beat-synced + stance-gated modulations`
  - `feat(director): StructuralDirector — 150s cadence LLM for long-horizon moves`
  - `refactor(director): narrative cadence 8s→20s; structural context in prompt`
- [ ] **5.10** — Restart compositor. Tail journal 5 min. Verify all three rates ticking. Capture a 2-minute clip for visual pace audit.
- [ ] **5.11** — Mark Phase 5 ✓.

## Acceptance criteria

- Three directors run concurrently without contention.
- Twitch moves visible at 3-5 s cadence on the output frame (overlay pulses, preset param shifts).
- Narrative moves at 20 s; LLM calls complete within 30 s budget (Phase 4/Phase 6 monitoring).
- Structural moves at 150 s; long-horizon direction observable in subsequent narrative prompt.
- No twitch emissions during CAUTIOUS/CRITICAL stance.

## Risks

- **LLM contention**: structural + narrative may collide at TabbyAPI. Mitigation: structural fires at offset (e.g., 20 s into the 150 s cycle, so it's not coincident with a narrative tick edge).
- **Impingement rate spike**: 50+ twitch emissions in 5 min could flood the pipeline. Mitigation: twitch impingements carry low salience (0.2) so they're recruited only when no higher-salience impingement competes.
- **Pipeline recruitment oscillation**: adjacent twitch moves could flap an overlay. Mitigation: per-capability minimum dwell (1 s) enforced by `CompositionalConsumer` (Phase 3).

## Rollback

Stop `twitch_director` and `structural_director` threads (or don't spawn them via env flag). Narrative director falls back to 20 s cadence; revert to 8 s via `HAPAX_DIRECTOR_CADENCE_S=8` env.
