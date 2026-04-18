# Token Pole (Vitruvian Man) HOMAGE Migration — Design

**Date:** 2026-04-18
**Task:** #125 (HOMAGE follow-on dossier)
**Source finding:** `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` § #125
**Related:** #146 (token-pole reward mechanic — separate axis; see § Relation to #146)
**Status:** Stub — provisional approval 2026-04-18

---

## Goal

Migrate the existing 300×300 `TokenPoleCairoSource` (upper-left overlay; Vitruvian Man + golden-spiral token path) from its current SVG-esque, candy-palette grammar to the BitchX homage grammar: Px437 IBM VGA raster typography, Gruvbox/mIRC-grey skeleton, bright-identity accents on limb geometry, zero-frame / ticker-scroll transitions driven by the choreographer. The refactor is already syntactically a `HomageTransitionalSource` subclass (`token_pole.py:125`); what's missing is package-grammar application inside `render_content()` — the fill strategy is still hardcoded candy colors.

## Preservation Invariants

These must pass pixel-level regression tests before and after migration:

- **Geometry.** `SPIRAL_CENTER_X=0.50`, `SPIRAL_CENTER_Y=0.52`, `SPIRAL_MAX_R=0.45`, `NUM_POINTS=250`, `PHI` and `_build_spiral()` untouched. 3 turns, exponential decay coefficient `-0.2`, starting-angle offset `0.5` preserved.
- **Navel anchor.** Spiral origin remains on the figure's navel — the same `(NATURAL_SIZE * 0.50, NATURAL_SIZE * 0.52)` pixel in local coordinates. Vitruvian PNG scale logic (`scale = NATURAL_SIZE / max(sw, sh)`) preserved.
- **Natural size.** 300×300 unchanged. Origin at (0, 0); runner does layout placement.
- **FSM semantics.** Constructor call `super().__init__(source_id="token_pole")` retained; default `entering_duration_s=0.4`, `exiting_duration_s=0.3` retained.
- **Ledger contract.** `/dev/shm/hapax-compositor/token-ledger.json` reads unchanged (`pole_position`, `total_tokens`, `active_viewers`, `explosions`).
- **Token-position easing.** 0.06 lerp, 0.5 s ledger re-read interval, particle physics (`Particle`) preserved.

## Palette Substitution

Replace every hardcoded tuple in `token_pole.py:57-80` with calls through the active `HomagePackage.palette` (acquired via `homage_runtime.current_package()`):

| Current token | BitchX palette role | Usage |
|---|---|---|
| `COLOR_SPIRAL_LINE` (violet α=0.2) | `muted` α=0.3 | Spiral guide |
| `COLOR_TRAIL` (7-color rainbow) | `[muted, terminal_default, bright, accent_cyan, accent_magenta, accent_yellow]` at graded alpha | Trail gradient |
| `COLOR_GLYPH_OUTER` (hot pink) | `accent_magenta` | Pink ring → magenta ring |
| `COLOR_GLYPH` (yellow) | `accent_yellow` | Token body |
| `COLOR_GLYPH_INNER` (cream) | `bright` | Token center |
| `COLOR_GLYPH_CHEEK` (rosy) | `accent_red` α=0.5 | Cheeks |
| `COLOR_EXPLOSION` (candy 8-color) | `[accent_cyan, accent_magenta, accent_yellow, accent_green, accent_red, bright]` | Particle palette |
| Dark backing card `(0.05, 0.04, 0.08, 0.88)` | `background` | Card fill (near-black α=0.90) |

Vitruvian PNG blit: apply a `cairo_operator.MULTIPLY` with `terminal_default` so the ink lines read as mIRC-grey rather than sepia. Rounded-corner card violates `"rounded-corners"` anti-pattern — replace with straight rectangle plus the package's `line_start_marker="»»»"` decoration along the top edge.

Eye/smile color: switch from `(0.15, 0.1, 0.0)` to `muted` so the token face reads terminal-monochrome with bright identity on the ring.

## FSM Inheritance

Already inherited via `TokenPoleCairoSource(HomageTransitionalSource)`. Remaining work:

- Call `apply_package_grammar(cr, package)` at the top of `render_content()` to normalize color state.
- Override `render_entering()` / `render_exiting()` to implement BitchX ticker-scroll: payload scrolls in from the right at `NATURAL_SIZE * (1 - progress)` x-offset during `entering`, reverse for `exiting`.
- Choreographer gates visibility via `apply_transition("ticker-scroll-in" | "ticker-scroll-out")`. Token-pole is choreographed like any ward — no self-scheduled transitions. `HAPAX_HOMAGE_ACTIVE=0` preserves legacy paint-and-hold.

## Relation to #146 (Token Pole Reward)

These are orthogonal concerns:

- **#146 reward mechanic** determines the *output* side: what counts as a token, how `pole_position` moves, how `explosions` fire. Governs `/dev/shm/hapax-compositor/token-ledger.json` writes.
- **#125 this spec** governs the *aesthetic* side: how the rendered surface looks given whatever ledger content exists.

The contract between them is the ledger file. This spec does not modify writers; #146 does not modify renderers. Both can land independently. A reward-mechanic change that adds a new ledger field (e.g. `combo_multiplier`) is a #146 concern; displaying it grammatically is a #125 follow-on.

## File-Level Plan

- `agents/studio_compositor/token_pole.py` — primary edit. Remove module-level color constants; move palette lookups into methods. Add `apply_package_grammar()` call. Override `render_entering()` / `render_exiting()`. Replace rounded-corner card with marker-decorated rect. Add `cairo_operator.MULTIPLY` blit for the PNG.
- `tests/studio_compositor/test_token_pole.py` — new regression pins: geometry invariants (spiral point #0 and #249 at expected pixels ±0.5), navel anchor, palette-vs-package assertion (color used in ring equals `package.palette.accent_magenta` when package=BITCHX_PACKAGE), transition-state gating (render while ABSENT yields transparent surface).
- `assets/vitruvian_man_overlay.png` — unchanged; PNG stays sepia and is tinted at blit time.
- `agents/studio_compositor/homage/` — no changes; package + FSM already land-ready.

## Test Strategy

- **Golden-image regression** at three FSM states (ABSENT, HOLD, entering-progress=0.5) against `BITCHX_PACKAGE`. Delta tolerance ≤1% per channel for HOLD; ABSENT must be fully transparent.
- **Navel-pixel assertion** — a dedicated test reads the rendered surface and asserts the glyph center at `pole_position=0.0` (outermost spiral turn) sits on the expected radius from `(150, 156)`; at `pole_position=1.0` it sits on the navel pixel itself.
- **Palette-substitution property test** — parametrize over all `HomagePackage` registry members (currently just BitchX; future packages automatically pass or flag a gap).
- **Anti-pattern lint** — assert `grammar.refuses_anti_patterns` triggers no violations for the rendered output (no rounded-corner detection, no AA font, no emoji).

## Open Questions

1. **Vitruvian PNG legibility under `MULTIPLY` + `terminal_default`.** Will the ink lines remain readable at 300×300 once the sepia is removed? If not, fallback is `DIFFERENCE` blend with `bright` or a pre-processed monochrome asset at `assets/vitruvian_man_mono.png`.
2. **Trail gradient.** 6-color mIRC palette vs 7-color original; dropping one hop may make the trail read too flat. Alternative: interpolate `muted→bright` with a single `accent_*` midpoint selected by `pole_position % N`.
3. **Particle shape.** Current `cr.arc()` circles read non-raster. Should explosions instead render as Px437 glyph characters (`*`, `·`, `•`) for CP437-authenticity? Defer to §5 signature-artefact review.
4. **Face glyph retention.** The token face (eyes, smile, cheeks) is the candy-persona's signature. Keep as geometric primitives or replace with a CP437 glyph face (e.g. `:)` at `bright`)? Operator call.

## Implementation Order

1. Introduce `current_package()` getter in `agents/studio_compositor/homage/` runtime (if not already present). Non-blocking if already shipped by Phase 6.
2. Replace module-level color constants with method-local palette lookups; feature-flag-gate via `HAPAX_HOMAGE_ACTIVE` so legacy palette stays under the flag=0 path.
3. Add `apply_package_grammar()` call at the top of `render_content()`.
4. Remove rounded-corner card; add `»»»` marker decoration.
5. Add `MULTIPLY`-blend Vitruvian blit.
6. Override `render_entering()` / `render_exiting()` with ticker-scroll pixel effect.
7. Regression tests; golden images captured at flag=0 and flag=1.
8. Wire through choreographer (`compositional_consumer`) so `homage.*` intent families gate the token pole like other wards.

## Related Tasks

- #121 (HARDM), #122 (DEGRADED-STREAM), #123 (chat-ambient ward), #124 (Reverie preservation) — peer HOMAGE wards sharing the `HomageTransitionalSource` base.
- #146 — token-pole reward mechanic (ledger writer side).
- HOMAGE Phase 11c — choreographer gating for transitional sources (dependency for the `homage.*` intent wire-through in step 8).

**Spec path:** `docs/superpowers/specs/2026-04-18-token-pole-homage-migration-design.md` (in the cascade worktree)
