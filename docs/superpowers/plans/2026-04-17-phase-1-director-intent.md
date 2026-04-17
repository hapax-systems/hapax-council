# Phase 1 — Director Intent Signature + Prompt Caching

**Spec:** `2026-04-17-volitional-grounded-director-design.md` §3.1, §5 Phase 1
**Goal:** `DirectorIntent` Pydantic schema exists; director emits it internally and logs to JSONL; LiteLLM `cache_control` wraps the stable system-prompt prefix; legacy-flag rollback exists.

## File manifest

- **Create:** `shared/director_intent.py` — Pydantic models: `CompositionalImpingement`, `DirectorIntent`, `IntentFamily` Literal, `ACTIVITY_VOCABULARY` Literal (HSEA Phase 2 13-activity).
- **Create:** `tests/shared/test_director_intent.py` — schema validation, roundtrip JSON.
- **Modify:** `agents/studio_compositor/director_loop.py`:
  - `_build_unified_prompt` emits a system-prompt prefix flagged cacheable via LiteLLM extra_body.
  - `_call_activity_llm` requests structured output (JSON mode or tool-call) matching `DirectorIntent` schema.
  - `_act_on_intent(intent: DirectorIntent)` — new dispatcher; existing `set_header` + `_speak_activity` + `_active_slot` advancement invoked by this method.
  - `HAPAX_DIRECTOR_MODEL_LEGACY` env flag restores pre-epic `{activity, react}` path.
  - Emits `DirectorIntent` to `~/hapax-state/stream-experiment/director-intent.jsonl` (append-only, atomic tmp+rename batched per-tick).
- **Modify:** `tests/studio_compositor/test_director_loop.py` — new tests for intent emission + legacy flag + cache_control insertion.

## Tasks

- [ ] **1.1** — Write Pydantic models in `shared/director_intent.py`:
  - `ActivityVocabulary` = Literal[13 HSEA Phase 2 values].
  - `IntentFamily` = Literal["camera.hero", "preset.bias", "overlay.emphasis", "youtube.direction", "attention.winner", "stream_mode.transition"].
  - `CompositionalImpingement` with fields per spec §3.1.
  - `DirectorIntent` with fields: grounding_provenance, activity, stance (from shared.stimmung.Stance — import, don't redefine), narrative_text, compositional_impingements.
  - No business logic in the module.
- [ ] **1.2** — Write failing tests in `tests/shared/test_director_intent.py`: valid construction, JSON roundtrip, stance-enum acceptance, activity-vocabulary validation (13-label), rejection of unknown activities, empty provenance allowed, empty impingements allowed.
- [ ] **1.3** — Run tests, verify they fail with "module not found" or similar. Implement models. Run tests, verify pass.
- [ ] **1.4** — Commit: `feat(director): add DirectorIntent + CompositionalImpingement Pydantic models`.
- [ ] **1.5** — Add `HAPAX_DIRECTOR_MODEL_LEGACY` env flag to director_loop.py top-of-file constants. Default False. When True, `_act_on_intent` skips all new logic and calls the pre-epic path (save a copy of the pre-epic `_act_on_activity` method as `_act_on_activity_legacy`).
- [ ] **1.6** — Modify `_call_activity_llm` to pass `extra_body={"cache_control": {"type": "ephemeral"}}` on the system message (Anthropic-style); for Command R via LiteLLM this is a no-op on the upstream but exercise the path. For OpenAI-style the flag goes via `extra_headers`. Document both paths in a comment.
- [ ] **1.7** — Write director-side intent emission: parse LLM JSON response into `DirectorIntent`; fallback to legacy path on parse error with a warning log. Tests: happy path, malformed JSON fallback, stance-out-of-enum rejection.
- [ ] **1.8** — Write `~/hapax-state/stream-experiment/director-intent.jsonl` on each emitted intent. Atomic writes via the existing `shared/atomic_write.py` (or inline if not present). Test: intent persisted across simulated restart (use tmp_path).
- [ ] **1.8b** — Write `/dev/shm/hapax-director/narrative-state.json` on each emitted intent, atomic tmp+rename. Payload: `{"stance": str, "activity": str, "last_tick_ts": float, "condition_id": str}`. Consumer: Phase 5 `TwitchDirector` reads this before each twitch tick to apply stance-gate.
- [ ] **1.9** — Run the full studio_compositor test suite: `uv run pytest tests/studio_compositor/ tests/shared/test_director_intent.py -q`. All pass.
- [ ] **1.10** — Run ruff + pyright. Fix any issues.
- [ ] **1.11** — Commit: `feat(director): emit DirectorIntent with grounding_provenance + legacy flag + prompt-cache hint`.
- [ ] **1.12** — Restart studio-compositor.service. Tail journal for 60 s. Verify: no ERRORs; at least one "DirectorIntent emitted" log line; `~/hapax-state/stream-experiment/director-intent.jsonl` has entries.
- [ ] **1.13** — Capture 1920×1080 frame from `/dev/video42`; visual check: nothing regressed (still shows old 4 PiPs, activity header still dark — legibility is Phase 4).
- [ ] **1.14** — Mark this phase ✓ in `master-plan.md` Changelog.

## Acceptance criteria

- New file `shared/director_intent.py` exists and is imported cleanly.
- Legacy flag works: `HAPAX_DIRECTOR_MODEL_LEGACY=1` → director emits only `{activity, react}` (old behavior).
- Without legacy flag: director emits `DirectorIntent` with ≥1 `grounding_provenance` entry (even if empty string; populated properly in Phase 2).
- JSONL file has one line per director tick, each parsing back to a valid `DirectorIntent`.
- `uv run pytest tests/ -q` passes with zero regressions.
- Compositor restarts cleanly; stream output unchanged visually (Phase 1 is plumbing only).

## Test strategy

Unit tests cover schema + serialization + parse-failure paths. No integration test yet; Phase 2's perceptual field is needed to populate `grounding_provenance` meaningfully.

## Rollback

`HAPAX_DIRECTOR_MODEL_LEGACY=1` in `~/.config/systemd/user/studio-compositor.service.d/legacy-director.conf`, daemon-reload, restart service. Reverts to pre-epic output.
