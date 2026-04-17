# Phase 4 — Legibility Surfaces

**Spec:** §3.5, §5 Phase 4
**Goal:** The output frame visibly carries Hapax's authorship. Fix no-op `set_header`; add stance indicator, activity header, captions strip, chat-keyword legend, grounding-provenance ticker (research mode). Design-language-aligned typography.

## File manifest

- **Create:** `agents/studio_compositor/cairo_sources/stance_indicator.py`
- **Create:** `agents/studio_compositor/cairo_sources/activity_header.py`
- **Create:** `agents/studio_compositor/cairo_sources/chat_keyword_legend.py`
- **Create:** `agents/studio_compositor/cairo_sources/grounding_provenance_ticker.py`
- **Modify:** `agents/studio_compositor/sierpinski_loader.py` — `set_header()` now calls `ActivityHeaderCairoSource.update()`; add new `set_stance()` / `set_provenance()` methods.
- **Modify:** `agents/studio_compositor/captions_source.py` — add `update(text, stance)` method that feeds from director_loop's `narrative_text`.
- **Modify:** `config/compositor-layouts/default.json` — add 5 new Cairo sources + surfaces + assignments. Geometry details below.
- **Modify:** `agents/studio_compositor/director_loop.py::_act_on_intent` — on each intent, update all 5 Cairo sources.
- **Create:** `config/compositor-layouts/default-legacy.json` — snapshot of the pre-epic layout for `HAPAX_COMPOSITOR_LAYOUT=default-legacy.json` rollback flag.
- **Create:** tests for each Cairo source.

## Geometry (1920×1080 canvas, design-language aligned)

- **Activity header surface**: top-center strip, `x=560 y=16 w=800 h=56`, z=30. Renders activity label (uppercase, monospace) + single-sentence gloss in smaller weight below. Translucent background per logos-design-language §3.
- **Stance indicator**: top-right corner inside the reverie quadrant, `x=1800 y=24 w=100 h=40`, z=35. Text: `NOMINAL` / `SEEKING` / `CAUTIOUS` / `DEGRADED` / `CRITICAL` with a small colored dot (Gruvbox/Solarized accent per stance). Never posture vocabulary.
- **Captions strip**: bottom full-width, `x=0 y=960 w=1920 h=120`, z=25. Renders `narrative_text` with fade-in/out. Text auto-wraps; 2 lines max.
- **Chat keyword legend**: right-side vertical strip, `x=1760 y=400 w=160 h=400`, z=20. Lists top 8 keyword→preset-family mappings. Fades when chat is idle &gt;5 min.
- **Grounding provenance ticker**: bottom-left corner, `x=16 y=900 w=480 h=40`, z=22. Renders `▸ signal_name · signal_name · ...` — the most recent `grounding_provenance` list. Research mode only (`context.working_mode == "research"`).

## Tasks

- [ ] **4.1** — Snapshot current `default.json` to `default-legacy.json`. Commit: `chore(compositor): snapshot pre-epic layout as default-legacy.json for rollback`.
- [ ] **4.2** — Add env-flag layout selection to compositor startup: `os.environ.get("HAPAX_COMPOSITOR_LAYOUT", "default.json")`. Test that legacy flag selects the old layout.
- [ ] **4.3** — Implement `StanceIndicatorCairoSource` as a subclass of `CairoSource`. Natural size 100×40. `update(stance: Stance)` stores the new value; `render(ctx, w, h)` draws.
  - Use design-language palette: NOMINAL=fg-primary, SEEKING=accent-curious, CAUTIOUS=accent-warning, DEGRADED=accent-warning, CRITICAL=accent-error.
  - Font: sans, 18px. Dot: 8px radius circle.
  - Test: given stance NOMINAL, `render` produces non-zero pixel coverage in the text region.
- [ ] **4.4** — Implement `ActivityHeaderCairoSource`. Natural size 800×56. Fields: `activity` (str), `gloss` (str). `update(activity, gloss)` stores; render draws activity uppercase 28px + gloss 14px below.
- [ ] **4.5** — Implement `ChatKeywordLegendCairoSource`. Reads from chat-reactor's keyword index (or hardcoded for now: 8 keywords → preset families). Fades at chat-idle &gt;5 min.
- [ ] **4.6** — Implement `GroundingProvenanceTickerCairoSource`. Reads from `~/hapax-state/stream-experiment/director-intent.jsonl` (tail last entry). Parses `grounding_provenance`. Renders comma-joined with arrow.
- [ ] **4.7** — Modify `captions_source.py` to accept `narrative_text` updates directly (not via file poll); update method called by director `_act_on_intent`.
- [ ] **4.8** — Fix `sierpinski_loader.py::set_header` — replace `pass` with call into `ActivityHeaderCairoSource.update()`. Pipe the director's chosen activity + gloss (gloss is derived from `CompositionalImpingement.narrative` of highest-salience intent).
- [ ] **4.9** — Wire: `director_loop._act_on_intent(intent)` calls:
  - `self._activity_header.update(intent.activity, self._derive_gloss(intent))`
  - `self._stance_indicator.update(intent.stance)`
  - `self._captions.update(intent.narrative_text)`
  - `self._provenance_ticker.update(intent.grounding_provenance)`
  - (`_derive_gloss` picks the highest-salience compositional impingement's narrative, truncated to 40 chars.)
- [ ] **4.10** — Update `default.json` — add 5 new source entries + 5 new surfaces + 5 new assignments. Ensure z-order doesn't collide with existing PiPs.
- [ ] **4.11** — Write 5 unit tests (one per source). Each: construct, call update, assert render produces expected pixel signatures (or content verified via cairo pattern).
- [ ] **4.12** — Write 1 integration test: spin up compositor with test layout, feed a synthetic DirectorIntent, assert the Cairo sources' render outputs are non-empty.
- [ ] **4.13** — Run ruff + pyright + tests.
- [ ] **4.14** — Commit in 4-5 commits, grouped by surface:
  - `feat(compositor): StanceIndicator Cairo source (design-language-aligned)`
  - `feat(compositor): ActivityHeader Cairo source (fixes set_header no-op)`
  - `feat(compositor): ChatKeywordLegend + GroundingProvenanceTicker Cairo sources`
  - `feat(compositor): wire captions_source into default.json layout`
  - `feat(compositor): director pushes intent to all 5 legibility surfaces`
- [ ] **4.15** — Restart studio-compositor + rebuild-logos if layout includes reverie delta. Capture frame at 1920×1080. Visual audit:
  - Activity header visible, reads current activity.
  - Stance indicator visible top-right.
  - Captions appear when director narrates, fade after.
  - Chat legend visible (may be quiet if chat idle).
  - Provenance ticker visible (research mode).
  - No overlap/collision with existing PiPs.
- [ ] **4.16** — Mark Phase 4 ✓.

## Acceptance criteria

- 5 new Cairo sources register with the compositor.
- `set_header` is no longer a no-op; visible on frame.
- Captions source reaches the layout; narrations appear as captions.
- Stance indicator text matches `Stance` enum values (not posture names).
- `HAPAX_COMPOSITOR_LAYOUT=default-legacy.json` reverts to pre-epic layout.
- Frame capture manually verifies every surface present + non-colliding.

## Test strategy

- Unit: each Cairo source standalone render.
- Integration: compositor+director feed → frame pixels show expected text.
- Visual smoke after commit.

## Rollback

`HAPAX_COMPOSITOR_LAYOUT=default-legacy.json` env in systemd drop-in. Reverts layout without code changes.

## Design-language note

Every text surface uses CSS-custom-property-equivalents (loaded as Python constants from the same source of truth used by the Logos UI). No hardcoded hex. Palette switches on working-mode change (research=Solarized, rnd=Gruvbox).
