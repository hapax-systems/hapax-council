# DURF (Display Under Reflective Frame) — Design Research

**Author:** beta (synthesis from dedicated research agent)
**Date:** 2026-04-24T23:40Z
**For:** MVP implementation plan
**Precedents:** `docs/superpowers/specs/2026-04-18-homage-framework-design.md`; `docs/research/2026-04-24-grounding-capability-recruitment-synthesis.md` §2-§4; `docs/research/2026-04-24-universal-bayesian-claim-confidence.md`

**Operator directive (2026-04-24T23:10Z):**
> "New Homage Ward: Display Under Reflective Frame (DURF). First full-frame ward. I am sitting here driving a 4 session claude code session to produce this work. This is value untapped RIGHT NOW. The DURF should show these four foot frames in 'real-time' in a full-frame homage ward in the video layer like all other wards. The inclusion of this ward should be based on whether there is valuable activity to display. (Bayesian claim). However, let's not wait on the avail of the bayes capabilities. Let's get the ward displaying ASAP. It'll be your side mission. First of all: research design of ward based on value delivered and likely advantageous properties we could supply the ward given content. There will be a over indexing on visibility in the research results, remember that we have aesthetic commitments that if are undermined the project suffers immensely."

## 1. Value-delivered analysis

**Viewer (livestream audience).** The audience watches a system whose invisible labor is its whole point. Every other ward (token-pole, sierpinski, GEM, album-overlay, splattribution) is a *projection* of internal state onto domain-specific geometry. DURF is the state itself, un-projected. Value is epistemic: the viewer sees that Hapax's speech, cuts, and recruitments are not stagecraft — they are sampled from four concurrently running agents whose log-streams are visible and falsifiable on the surface. This is the *livestream-as-research-instrument* principle (memory `project_livestream_is_research`) rendered as a single ward.

**Operator.** The 4-tmux driving setup currently exists only in the operator's local viewport — never broadcast, never evidentiary. The operator pays the full cost of coordination (claim announcements, cross-cutting audits, relay-yaml maintenance) but receives no viewer-legibility dividend. DURF returns that dividend. Value is *attestational*: the operator's sustained technical labor becomes visible without requiring the operator to perform narration.

**Hapax (self-evidencing loop).** Per synthesis §9, Hapax's axiom-closure target is to drive the fetishistic-disavowal / empty-provenance rate to zero. DURF is the most direct possible grounding-provenance artifact: the broadcast shows the live record-of-work underlying every other ward's content. The ward *is* provenance for everything else on screen. This is T7 (grounding-provenance attribution) applied at the full-frame aggregate level.

**Negative-value scenarios:**
- Token leak / SSH output / private path bleeding into broadcast (`feedback_l12_equals_livestream_invariant`)
- Over-exposure collapsing the stream into a terminal-cam (if visible >15-20% of broadcast time)
- Stalled panes rendered during AFK → "no activity" reads as "failure advertisement"
- Aesthetic dilution if raw terminal output displayed without HOMAGE-native typography/palette/grammar — collapses to GEM's original failure state (`feedback_gem_aesthetic_bar`)

## 2. Advantageous properties given content

**Typography.** Mandatory: re-render in **Px437 IBM VGA 8×16** (already BitchX package-primary per `shared.homage_package.TypographyStack.primary_font_family`). Native terminal fonts violate BitchX anti-pattern `proportional-font` and the `single-weight` invariant. Capture tmux buffer as text, apply palette routing per token-class, re-rasterize via Pango through `agents/studio_compositor/text_render.py`. Eliminates anti-aliasing leak + font-cache variance.

**Palette.** Token-class → mIRC-16 role mapping via a lightweight lexer. ANSI SGR codes are *rejected* (would preserve operator-environment-specific palette, breaking HOMAGE authenticity). Semantic mapping:
- `@prompt` → `bright`
- `tool-call` → `accent_cyan`
- `error` → `accent_red`
- `success` → `accent_green`
- `meta` → `muted`

Background stays `(0.04, 0.04, 0.04, 0.90)` matching every other HOMAGE surface. Consent-safe variant collapses accents to muted (already wired).

**Refresh cadence.** Render at **4-8 fps** (matches captions cadence). Capture-poll thread at **2 Hz** writing last-N-lines per pane to a ring buffer. Line-entry uses **250ms ease-in** per memory `feedback_no_blinking_homage_wards` (200-600ms envelope). No character-by-character typewriter — show-don't-tell: the *dance of arrival*, not the simulation of typing. Character-level 60Hz+ bursts (during diff-apply / test-runner) smoothed at the buffer layer, not rendered direct.

**Geometry — NOT equal quadrants.** Four equal 960×540 reads as "quad security-cam grid" — anti-HOMAGE. Use **non-equal tiled grammar**:
- One foreground pane (~1100×620, upper-right)
- Three background panes stacked left (~760×340 each, with stagger and overlap)

Foreground selection **rotates on 30-60s cadence** driven by per-pane activity-score (bytes-appended over window). Depth emerges from rotation without motion.

**Trade-off accepted:** replacing native ANSI typography loses per-operator aesthetic fidelity (operator's nvim colorscheme, Nerd Font ligatures) in exchange for HOMAGE-grammar coherence. DURF is a Hapax ward, not an IDE broadcast.

## 3. Aesthetic integration

### 3.1 Replace vs composite?

**Composite, never replace.** Full-frame = DURF's *content-bearing region* is the full frame, but the always-on reverie substrate underlays at ~0.12 alpha per `HomageSubstrateSource` convention. Reverie shader chain continues running; DURF composites on top at **0.88-0.94 alpha** with substrate bleeding through gaps/stagger. Preserves "substrate never dark" invariant — if DURF capture stalls, reverie remains visible. Fulfills the paired solo-source pattern (`SourceSchema.pair_role`).

### 3.2 Frame chrome

BitchX `GrammarRules.container_shape = "angle-bracket"`. Per-pane marker: single-line strip `»»» ` in `muted` + **4-char session-glyph** drawn as raster-cell positional token:
- `A-//` (alpha)
- `B-|/` (beta)
- `D-|\` (delta)
- `E-\\` (epsilon)

Glyph is a *geometric-identity* not a *name*. No "session alpha" text box. Refuses text-in-a-box + personification.

### 3.3 HARDM test

A "session" label personifies. The glyph-based identification in 3.2 passes HARDM — session identity is positional/geometric, not denoted. More importantly: DURF does *not* render agent-authored prose at character-level fidelity; it renders the *texture* of their work via token-class palette routing. Content becomes **signal-density on a grid** — the HARDM visual-twin fulfilled, not violated. **PASS.**

### 3.4 Show-don't-tell test

DURF crosses a subtle line: literal meta-communication. Resolution: DURF shows the **substrate** of coordination (log-stream), never the **narration** (no "session alpha is shipping PR #1280"). No status summaries, progress bars, derived-metric chirons. The dance of four panes updating at their own cadences **IS** the communication. Forbidden: header text saying what DURF is; strip saying what any pane is doing. Viewer either reads the logs or reads the overall motion — both pass show-don't-tell. **PASS.**

### 3.5 Depth (GEM aesthetic bar)

Multi-layer depth proposals ranked by HOMAGE-coherence:

1. **Z-stagger with atmospheric haze** — background three panes at 0.68 alpha over muted blue-black wash; foreground at 0.94 with crisp border; substrate bleeds between.
2. **Reflection layer** — bottom 40px of each pane mirrors last 2 lines with 0.20 alpha vertical gradient decay. **Literalizes the R of DURF.**
3. **Recursive frame-around-frame** — foreground pane contains miniature 4-quad inset at 1/9 scale (depth-of-depth, self-similar).
4. **Parallax on reverie substrate** — substrate UV displaced counter to foreground-pane rotation at 0.02 magnitude.

**Recommend (1) + (2) for MVP** (cheap, native to Cairo). (3) + (4) deferred. Clears Sierpinski-caliber bar: multi-layer, algorithmic, depth-capable.

### 3.6 "Reflective" metaphor

Literal: (2) reflection layer. Metaphorical: Hapax showing Hapax's coordination is **attestation** in Ricoeur's sense — the system attests its own labor. Both readings HOMAGE-legitimate; the literal reflection is the aesthetic discharge of the metaphor. The name *D.U.R.F.* is never rendered on-screen (chrome-free per 3.2).

## 4. Inclusion gate proposals

### MVP gate (ship now, non-Bayesian)

Threshold predicate over three signals:

1. `desk_active == True` (contact-mic, positive-only) in last 60s — operator physically present
2. Aggregate bytes-appended across all 4 panes > 200 in last 60s — actual typing/output
3. Not in `consent-safe` egress mode (`consent_live_egress.py` state)

All three required. Cache evaluation at 2 Hz. 30s hysteresis on exit (prevents flicker when a pane briefly idles). Captures "valuable activity" without over/under-firing.

### Bayesian-upgrade path

Once `ClaimEngine` lands, DURF's gate becomes a `Claim("valuable development-activity in progress")` with posterior from:
- `desk_active` (LR 18× from PresenceEngine)
- Keyboard cadence
- Per-pane token-delta rate
- `cc-active-task-{role}` claim-file freshness
- Git HEAD advance across worktrees
- Session-yaml relay mutations
- Completion-event stream

Threshold: posterior > 0.70 for inclusion, < 0.45 for exit (hysteresis). Fits `GroundingProfile.common_ground_predicate="asserted"` since DURF surfacing is itself a Hapax assertion of live-work.

### Off-gate (hard overrides)

- Fortress-mode deliberation → suppressed
- `consent_live_egress` flipped → suppressed (non-negotiable per `it-irreversible-broadcast`)
- Operator AFK > 5min → suppressed
- Private-content regex match on any pane's last-line (tokens, SSH paths, pass output, .envrc echoes) → affected pane shows redacted substitute; >1 redacted pane → full DURF suppression

## 5. Technical approach

### Capture source

`tmux capture-pane -pt <target>` over a 4-target list from `config/durf-panes.yaml`. **Text-only MANDATORY** — Wayland pixel-capture (hyprshot / grim / wl-copy) broadcasts the whole desktop, inviting L-12 bleed. Text capture is VT-escape-safe: `-e` off, sanitize with 20-line allow-regex filter pre-Pango, redaction regex per line (token patterns, absolute paths under operator-home, `AWS_`/`ANTHROPIC_API_KEY`/bearer prefixes).

### Source architecture

New `DURFCairoSource(HomageTransitionalSource)` at `agents/studio_compositor/durf_source.py`:
- Registered as `DURFCairoSource` in `cairo_sources/__init__.py`
- Natural size 1920×1080
- `update_cadence="rate"`, `rate_hz=6.0`
- Background thread polls tmux every 500ms, writes ring-buffer of classified-token lines per pane
- Render method composes from snapshot — never blocks on subprocess
- Falls back to last-good buffer on capture failure (degraded-hold already in `CairoSourceRunner`)

### Layout slot

Additive change to `config/compositor-layouts/default.json`:
- Surface `durf-fullframe`: `{kind: "rect", x: 0, y: 0, w: 1920, h: 1080}`, `z_order: 5`, `blend_mode: "over"`
- Assignment: `{source: "durf", surface: "durf-fullframe", opacity: 0.92, render_stage: "post_fx"}`
- No new `SurfaceKind` needed — large `rect` suffices
- Gate writes `visible=false` via `ward_properties` → source renders transparent → substrate + other wards show through

### Envelope / fallback

- **Enter**: 400ms ease-in alpha ramp (0 → 0.92)
- **Exit**: 600ms ease-out (0.92 → 0)
- **Capture disconnect**: hold last-good 3s, fade to substrate over 600ms
- **Pane rotation**: 400ms crossfade between old/new foreground (no-blink compliant)

Reverie remains GPU-owned; DURF is Cairo-CPU. Co-exist via post_fx composition (pattern used by every chrome ward).

### Observability

- `FreshnessGauge` auto-registered by `CairoSourceRunner`
- Gate decisions to `director_observability.emit_homage_render_cadence`
- Per-pane bytes-appended counter exposed for Bayesian-gate consumption later

## 6. Over-indexing guardrails

**Visibility ceiling: 15% of broadcast wall-clock per 60-minute rolling window.** When hit, force-exit + suppress re-entry for 10 minutes.

**Forbidden chrome:**
- No text labels ("DURF", "SESSION ALPHA", "CURRENTLY SHIPPING")
- No progress bars, activity meters, header strips, frame titles
- Ward is chrome-free; 3.2 glyph-marker is per-pane single-char positional-not-labeled

**Forbidden animations:**
- No flicker, zoom-on-update, pulse-on-pane-activity
- No attention-summoning effects of any kind

**Co-existence with other wards:** When DURF active, suppress chrome wards **except** token-pole + stance-indicator (directorial-structural, not content-competing). Album-overlay, GEM, captions, chronicle-ticker: gated off — their content would fight DURF for attention; absence is aesthetically honest (the system is showing its work, not its output).

## 7. MVP implementation plan (ship ASAP)

Per operator directive "let's not wait on the avail of the bayes capabilities":

### Files to create
- `agents/studio_compositor/durf_source.py` (~300 LOC) — `DURFCairoSource`
- `config/durf-panes.yaml` (~20 lines) — tmux target list + redaction regex config
- `tests/studio_compositor/test_durf_source.py` (~200 LOC) — unit tests

### Files to modify
- `config/compositor-layouts/default.json` — add surface + assignment
- `agents/studio_compositor/cairo_sources/__init__.py` — register class
- `shared/compositor_model.py` — if needed (likely not; existing rect surface suffices)

### Scope for first PR (minimum viable)
- Text capture + redaction
- Non-equal quadrant geometry (3.5 option 1: z-stagger)
- Px437 typography + mIRC-16 palette routing
- MVP gate (desk_active + bytes-appended + consent-safe check)
- Enter/exit envelope
- Unit tests for redaction regex + gate logic

### Scope for Phase 2 (follow-up PR)
- Reflection layer (3.5 option 2)
- Foreground rotation on activity-score
- Per-pane ring-buffer + smooth line-entry animation
- Observability gauges

### Scope deferred
- Recursive frame-around-frame (3.5 option 3)
- Parallax on reverie substrate (3.5 option 4)
- Bayesian-gate migration (once ClaimEngine lands, Phase 2b)

### 2026-05-05 Phase 3 follow-up status

- Reflection layer: implemented live by default in
  `CodingActivityReveal._render_reflection_layer`. It mirrors the last two
  already-redacted pane lines into the bottom 30% of each pane, fades alpha
  linearly, and applies the slow 0.05 Hz horizontal warp bounded to 4 px.
- Foreground rotation: implemented by salience-ranked lane selection in
  `durf_source._select_lanes` and the foreground/stack geometry in
  `_layout_for_count`. The most salient eligible lane receives the foreground
  rectangle; lower-ranked visible lanes occupy the side stack.
- Bayesian gate migration: DURF no longer owns a DURF-specific hardcoded
  Bayesian table. The live gate feeds `ActivityRevealMixin` claim state through
  `CodingActivityReveal`, and router-side static ceiling tables were retired by
  the activity-reveal governance migration.
- Per-region pixel masking: superseded on the live public path. DURF now
  broadcasts bounded tmux text only; unsafe raw/pixel capture bypasses fail
  closed before capture, so there are no default public pixels requiring
  per-region masks.

### Claim-before-parallel

DURF is cross-lane (compositor lane belongs to delta; research+ship-ASAP was delegated to beta as side-mission). Per `feedback_claim_before_parallel_work`, beta announces the claim in the broadcast inflection and coordinates with delta to avoid conflict with delta's active compositor work (Phase 2b livestream classifiers). DURF's `SourceKind=fullframe` slot doesn't collide with Phase 2b's `frame_for_llm` split (different composition stages).

## 8. Key file references

- `agents/studio_compositor/cairo_source.py` (runner + gauge plumbing)
- `agents/studio_compositor/cairo_sources/__init__.py` (class registration)
- `agents/studio_compositor/homage/__init__.py` (active package resolution)
- `agents/studio_compositor/homage/transitional_source.py` (base class)
- `agents/studio_compositor/homage/rendering.py` (`paint_bitchx_header`, `active_package`)
- `agents/studio_compositor/album_overlay.py` (mIRC-16 palette-routing reference)
- `shared/compositor_model.py` (SourceSchema/SurfaceSchema additions)
- `config/compositor-layouts/default.json` (layout to extend)
- `agents/studio_compositor/ward_properties.py` (visibility gating)
- `agents/studio_compositor/consent_live_egress.py` (consent-safe state)
- `agents/hapax_daimonion/presence_engine.py` (`desk_active` LR 18× for Bayesian upgrade)
- `scripts/cc-claim` + `~/.cache/hapax/cc-active-task-{role}` (claim-file freshness for later Bayesian gate)
