# Phase 2 — Structured PerceptualField

**Spec:** §3.2, §6 inventory, §5 Phase 2
**Goal:** Director's prompt environmental block is the JSON of a typed `PerceptualField` built from all existing classifiers/detectors. Stimmung prose collapse is retired.

## File manifest

- **Create:** `shared/perceptual_field.py` — Pydantic models + `build_perceptual_field()` reader function.
- **Create:** `tests/shared/test_perceptual_field.py` — fixture-based tests with synthetic perception-state.json.
- **Modify:** `agents/studio_compositor/director_loop.py::_build_unified_prompt` — replace the stimmung-prose block with `build_perceptual_field().model_dump_json(indent=2, exclude_none=True)`.
- **Modify:** `agents/studio_compositor/phenomenal_context.py` (or wherever FAST-tier rendering lives) — leave the renderer in place for other consumers; do not delete.

## Tasks

- [ ] **2.1** — Design `PerceptualField` Pydantic hierarchy per spec §3.2 field-table: AudioField, VisualField, IrField, AlbumField, ChatField, ContextField, StimmungField, PresenceField, StreamHealthField. All fields Optional; absence handled gracefully.
  - AudioField carries: `contact_mic: ContactMicState` (desk_activity, desk_energy, desk_onset_rate, desk_spectral_centroid, desk_tap_gesture, fused_activity), `midi: MidiState` (beat_position, bar_position, tempo, transport_state), `studio_ingestion: StudioIngestionState` (music_genre, production_activity, flow_state_score), `vad: VadState` (operator_speech_active).
  - VisualField carries: per_camera_scenes (dict[str, str]), detected_action (str), overhead_hand_zones (list[str] or dict[zone,bool]), operator_confirmed (bool), top_emotion (str), hand_gesture (str), gaze_direction (str), posture (str), ambient_brightness (float), color_temperature (float), per_camera_person_count (dict[role, int]).
  - IrField carries: ir_hand_activity (float), ir_hand_zone (str), ir_gaze_zone (str), ir_posture (str), ir_heart_rate_bpm (int), ir_heart_rate_confidence (float), ir_brightness (float), ir_person_count (int), ir_screen_looking (bool), ir_drowsiness_score (float).
  - AlbumField: artist, title, current_track, year, confidence.
  - ChatField: tier_counts (dict[tier_name, int] for 7 tiers), recent_message_count (int), unique_authors (int). No message bodies or author names.
  - ContextField: working_mode (Literal["research","rnd"]), stream_mode (Literal["off","private","public","public_research","fortress"]), active_objective_ids (list[str]), time_of_day (str), recent_reactions (list[str] — last 8 activity labels), active_consent_contract_ids (list[str]).
  - StimmungField: 12 dimensions as dict[str, float]; plus `overall_stance` (Stance enum).
  - PresenceField: state (Literal PRESENT/UNCERTAIN/AWAY), probability (float).
  - StreamHealthField: bitrate, dropped_frames_pct, encoding_lag_ms.
- [ ] **2.2** — Implement `build_perceptual_field()`:
  - Read `~/.cache/hapax-daimonion/perception-state.json` (main source of vision + audio + ir classifications).
  - Read `/dev/shm/hapax-stimmung/state.json` for StimmungField.
  - Read `/dev/shm/hapax-compositor/album-state.json` for AlbumField.
  - Read `/dev/shm/hapax-compositor/chat-state.json` + `chat-recent.json` for ChatField (aggregate only — no message content or author names).
  - Read `~/.cache/hapax/working-mode` for ContextField.working_mode.
  - Read `/dev/shm/hapax-compositor/stream-live` + stream_mode file for ContextField.stream_mode.
  - Read `axioms/contracts/*.yaml` for active contract ids.
  - Read obsidian-objective files for active_objective_ids.
  - Read `/dev/shm/hapax-daimonion/presence-state.json` for PresenceField.
  - Read OBS websocket cache file (or fall back to None) for StreamHealthField.
  - Each read wrapped in try/except → None; absent-file → missing sub-field, not error.
- [ ] **2.3** — Write failing tests in `tests/shared/test_perceptual_field.py`:
  - `test_empty_state_gives_all_none`: with no files present, all sub-fields are None, no exception.
  - `test_full_state_populates_all_fields`: fixture with one of each file, all fields populated.
  - `test_stale_file_treated_as_fresh_since_no_ttl`: loader doesn't age-check (that's consumer's job).
  - `test_chat_field_excludes_author_names`: inject a chat-state.json with author info; assert no author string appears in output.
  - `test_stimmung_overall_stance_is_enum`: from stimmung state file, verify overall_stance parses to Stance enum.
  - `test_ir_field_zero_when_no_pi_data`: with no pi-noir files, ir_person_count is None or 0.
  - `test_model_dump_json_roundtrip`: dump to JSON string, reload via Pydantic, verify equality.
- [ ] **2.4** — Run tests, verify fail. Implement models + reader. Verify pass.
- [ ] **2.5** — Run ruff + pyright.
- [ ] **2.6** — Commit: `feat(director): add PerceptualField reader from existing classifier outputs`.
- [ ] **2.7** — Modify `_build_unified_prompt`:
  - Replace the existing stimmung-prose block with `"<perceptual_field>\n" + build_perceptual_field().model_dump_json(indent=2, exclude_none=True) + "\n</perceptual_field>"`.
  - Keep the `<system_state>` (ContextAssembler TOON) and `<reactor_context>` blocks.
  - Add a clear delineation: "Read the perceptual field JSON above; ground your choices in those signals."
- [ ] **2.8** — Update `tests/studio_compositor/test_director_loop.py` with a synthetic `PerceptualField` fixture; assert the serialized JSON appears in the prompt at the expected place.
- [ ] **2.9** — Verify no regression in existing director tests.
- [ ] **2.10** — Commit: `feat(director): replace stimmung-prose with structured PerceptualField in prompt`.
- [ ] **2.11** — Restart studio-compositor. Tail journal 60 s. Verify director prompt now includes `<perceptual_field>` block with populated visual/ir/audio fields. Capture a frame for regression.
- [ ] **2.12** — Mark Phase 2 ✓.

## Acceptance criteria

- `PerceptualField.model_dump_json(exclude_none=True)` output is structured and readable in the director's prompt.
- Full inventory of Agent 2's report is representable in the field (no classifier unaccounted for).
- Chat field contains NO author names or message bodies (axiom `interpersonal_transparency` compliance).
- Consent contracts + stream mode reachable.
- Tests: ≥7 tests passing; all existing director tests green.
- Visual regression: compositor output unchanged in pixels.

## Test strategy

Unit tests with tmp_path fixtures isolate each reader path. Integration at Phase 3 end (once director acts on the field).

## Rollback

Revert the commits; director reverts to stimmung-prose block.
