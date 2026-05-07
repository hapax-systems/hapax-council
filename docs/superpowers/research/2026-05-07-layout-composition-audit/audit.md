# Layout composition pass — Berger/Bachelard audit

**Spec:** `~/.cache/hapax/relay/context/2026-05-07-layout-composition-pass-spec.md`
**Lane:** epsilon (2026-05-07)
**Status:** AUDIT + PROPOSAL — code edits deferred pending screenshot-workflow resolution (operator open question #1 in PR #2829)

This is the analysis phase, not the edit phase. Per spec, "each change should be viewed in OBS before shipping" — same constraint as the broader screenshot-evidence directive. The doc identifies findings and proposes specific deltas; operator approves and either an OBS-attached lane applies the changes with before/after capture, or an offline render path lands first.

## Scope

`config/compositor-layouts/default.json` — the constellation layout. 26 surfaces sorted by z_order:

| z | surface | x,y | w×h | source | opac |
|---|---------|-----|-----|--------|------|
| 5 | durf-fullframe | 0,0 | 1920×1080 | durf | 0.96 |
| 8 | packed-cameras-fullframe | 0,0 | 1920×1080 | packed_cameras | 0.00 |
| 10 | pip-ll | 16,840 | 300×200 | album | 1.00 |
| 10 | pip-lr | 1580,52 | 160×36 | stream_overlay | 1.00 |
| 10 | pip-ul | 16,350 | 300×300 | token_pole | 1.00 |
| 10 | pip-ur | 1400,100 | 500×140 | reverie | 1.00 |
| 15 | sierpinski-center | 540,140 | 840×840 | sierpinski | 1.00 |
| 18 | gem-mural-bottom | 0,810 | 1920×240 | gem | 1.00 |
| 20 | activity-variety-log-mid | 1400,540 | 500×100 | activity_variety_log | 0.90 |
| 20 | impingement-cascade-midright | 1400,260 | 500×260 | impingement_cascade | 0.92 |
| 20 | pressure-gauge-ul | 16,560 | 240×40 | pressure_gauge | 0.92 |
| 22 | grounding-ticker-bl | 440,770 | 480×40 | grounding_provenance_ticker | 1.00 |
| 22 | lore-precedent-ticker | 16,712 | 340×110 | precedent_ticker | 0.92 |
| 22 | lore-programme-history | 16,612 | 340×90 | programme_history | 0.92 |
| 22 | lore-research-instrument-dashboard | 1400,660 | 500×180 | research_instrument_dashboard | 0.92 |
| 25 | activity-header-top | 540,8 | 840×36 | activity_header | 1.00 |
| 26 | recruitment-candidate-top | 555,720 | 810×48 | recruitment_candidate_panel | 0.92 |
| 28 | programme-banner-top | 555,40 | 810×160 | programme_banner | 1.00 |
| 30 | stance-indicator-tr | 1750,10 | 100×36 | stance_indicator | 1.00 |
| 30 | thinking-indicator-tr | 1580,10 | 160×36 | thinking_indicator | 0.92 |
| 30 | whos-here-tr | 1750,52 | 160×36 | whos_here | 0.92 |
| 60 | egress-footer-bottom | 0,1050 | 1920×30 | egress_footer | 1.00 |

(m8-display, steamdeck-display surfaces excluded — currently opacity 0.0; not contributing to composition.)

## Findings against spec's AVOID list

### 1. Naive symmetry — present, load-bearing

The constellation arrangement is mirror-symmetric around x=960:
- **Left column** (x≈16–356): pip-ul (token_pole), pressure-gauge-ul, lore-programme-history, lore-precedent-ticker, pip-ll (album)
- **Right column** (x≈1400–1900): pip-ur (reverie), impingement-cascade-midright, activity-variety-log-mid, lore-research-instrument-dashboard
- **Center** (x≈540–1380): sierpinski-center perfectly horizontally centered (540 + 840 = 1380, equidistant from 540 left and 540 right of canvas center)
- **Top row** (y≈8–60): activity-header at center, thinking/whos-here/stance bracketing right corner
- **Bottom row** (y≈810–1080): gem-mural full-width, egress-footer full-width

**Berger lens:** "The way we see things is affected by what we know or what we believe." A symmetric layout pre-conditions the viewer to see *the pipeline* rather than *the work*. Symmetric grids communicate "dashboard," not "composition."

### 2. Dashboard-style packing — present, especially right column

Right side stacks four panels at uniform x=1400, w=500:
- pip-ur 100→240 (140h)
- impingement-cascade 260→520 (260h)
- activity-variety-log 540→640 (100h)
- lore-research-instrument-dashboard 660→840 (180h)

These four panels with shared left-edge and uniform width read as a column of dashboard tiles. Total stack = 740 vertical px on a single x-line.

### 3. Equal spacing in TR cluster

`thinking-indicator-tr` (1580,10), `stance-indicator-tr` (1750,10), `whos-here-tr` (1750,52). Three small status indicators at uniform 36px height with mechanical 170px x-spacing. Reads as a status bar, not a composition.

### 4. Z-layer underutilization

Of 22 active surfaces, **15 cluster between z=10 and z=22** — the same compositional plane. Only durf (z=5), sierpinski (z=15), gem (z=18), and egress-footer (z=60) are meaningfully out-of-plane. Per Bachelard, depth = "the dialectics of inside and outside" — wards should suggest spaces *behind* and *beyond* the visible surface. Currently most surfaces sit on the same plane, projecting flatness.

### 5. Vertical empty strips read as gaps, not choice

Two consistent empty vertical strips:
- **Strip A** (x≈320–540, y≈0–810): between left column and sierpinski-center
- **Strip B** (x≈1380–1400, y≈0–810): between sierpinski-center and right column

These strips are ~120–220 px wide, running ~810 px tall. They're empty by accident (column gaps) rather than empty by composition. Per spec: "negative space as compositional element (emptiness is a choice, not a gap)." Currently it's a gap.

### 6. Predictable adjacencies

Left column adjacency sequence top-to-bottom: token_pole → pressure_gauge → programme_history → precedent_ticker → album. All "lore-ish" / status surfaces clustered. Right column: reverie → impingement → activity_variety → research_instrument. All "telemetry-ish" surfaces clustered. The adjacencies are sorted-by-category, not surprising.

Berger: "the relationship between image and context — each ward's meaning changes based on what's adjacent to it. Exploit this." Currently we don't exploit it — adjacencies are conservative.

## Findings against spec's PURSUE list

### 1. Forced novel adjacencies — absent

No instances of unexpected pairings. token_pole (slow, abstract symbol) sits next to pressure_gauge (telemetry); could be anywhere else.

### 2. Deliberate spatial tension — partial

Sierpinski's central placement is the single strong asymmetry signal — it's the visual anchor, drawing the eye through scale alone (840×840 = 705,600 px²). But the rest of the layout undoes the tension by mirroring around it.

### 3. Z-layer depth — minimal

z=5 (durf bg) → z=15 (sierpinski) → z=18 (gem) → z=20-22 (most wards) → z=60 (egress). The 38-unit gap between z=22 and z=60 is unused. No surface uses z=8, z=12, z=16, z=24, z=27, z=29, z=31-41, z=43-59. Vast unused depth resolution.

### 4. Scale contrast — present and load-bearing

sierpinski (840×840 = 705,600 px²) vs stance_indicator (100×36 = 3,600 px²) is 196:1. This is the strongest existing compositional move. Worth preserving and amplifying — but it's the ONLY scale move; everything else is medium.

### 5. Negative space as compositional choice — absent

The empty strips (Finding 5 above) are gaps not choices. To convert to compositional choice, either:
- Push something INTO the strips deliberately (a thin tall element that USES the channel)
- Widen one strip dramatically and tighten the other (asymmetric breath)

### 6. Bachelardian "rooms within frame" — partial

Sierpinski-center is a strong "room" — bounded, contained, holds attention. The pip- surfaces are room-shaped (square-ish). The lore-* surfaces are corridor-shaped (3:1 ratio). gem-mural-bottom is a "wall" along the floor. But these rooms don't NESTLE — they're tile-placed on the grid, not arranged as compositional niches.

## Proposed deltas (high-value, low-risk)

Three concrete changes ranked by ratio of compositional gain to risk. Each requires before/after OBS capture per spec; deferring application until that workflow is resolved.

### Proposal A — Asymmetric column widths (break naive symmetry)

Currently left column is 340 px wide, right column is 500 px wide — already asymmetric in width but symmetric in position (both anchored to canvas edge). Push further:

- Move left column wards 30 px right: x=16→46. Creates a thin (46 px) vertical breathing strip on the absolute left edge.
- Tighten left column width 340→300: lore-programme-history `w: 340 → 300`, lore-precedent-ticker `w: 340 → 300`. Still legible (340-px column was wide for the content).
- Result: left column is 300 px wide, right column is 500 px wide — clear weight asymmetry, sierpinski no longer perfectly centered (it sits 20 px right of canvas-center because left column is now thinner).

**Berger:** the asymmetry forces the viewer to notice the weight, not consume the dashboard. **Bachelard:** the 46-px left strip becomes a "shell" — a deliberate negative space that frames the column.

### Proposal B — Z-layer stratification (push depth)

Pull surfaces apart in z to create occlusion + parallax:

- `pip-ul` (token_pole): z=10 → z=12 (slightly forward; keeps token visible over album at z=10)
- `pip-ll` (album): z=10 → z=8 (push behind durf-bg overlap zone? careful with z=5)
- `pip-ur` (reverie): z=10 → z=14 (between durf and sierpinski plane; reverie should feel "in front of" the constellation)
- `lore-*` panels: z=22 → z=24 (one layer forward of impingement/activity)
- `gem-mural-bottom`: z=18 → z=16 (push slightly back — currently it sits "above" sierpinski's bottom edge; pulling back makes sierpinski feel further forward in the frame)

**Bachelard:** the 8-→-14 spread for pips creates "depth pockets" — each pip sits at a different distance from the viewer. Not parallax (the surfaces don't move) but perceived depth via z-layered translucency.

### Proposal C — Vertical empty-strip activation (Bachelardian shell)

Strip A (x=320–540) is currently dead. Two options:

**C.1 — Widen sierpinski left** (preserve symmetric center): increase sierpinski w from 840 → 960, x from 540 → 480. Eats into Strip A. Pro: sierpinski becomes more dominant. Con: less novelty, just bigger center.

**C.2 — Place a thin shell ward in Strip A** (force novel adjacency): a tall narrow ward (e.g. w=80, h=600, y=140) running parallel to sierpinski's left edge. Could be a new "spinal" ward — token-pole-like vertical text scroll, or a colorbar showing live stimmung dimensions. Pro: turns gap into composition. Con: requires a new ward source.

Recommend C.1 for low-risk delivery; C.2 as a Phase-2 design exercise.

### Proposal D — Break the right-column dashboard-stack

Currently 4 panels share x=1400, w=500. Stagger:

- impingement-cascade-midright: keep (1400,260), keep w=500
- activity-variety-log-mid: x=1400 → x=1340, y=540, w=500 (shifted 60 px left)
- lore-research-instrument-dashboard: x=1400 → x=1460, y=660, w=440 (shifted 60 px right, narrower)
- pip-ur (reverie): keep

Result: the 4 right-side panels alternate left-leaning and right-leaning by 60 px. Adjacencies become unexpected; the viewer's eye no longer slides down a clean vertical column.

**Berger:** the staggered column rejects the dashboard frame; viewer can't pre-categorize the panels as "the right-side telemetry block."

## Out of scope for this audit

- `config/compositor-layouts/segment-*.json` — the segment-mode layouts. Different design context (segment is content-foregrounding, not constellation). Spec includes them but they need their own audit pass.
- `agents/studio_compositor/layout.py` — the tile computation. No findings; the file computes layouts deterministically from the JSON spec, no Berger/Bachelard considerations apply.
- Ward `z_index_float` values in `ward_stimmung_modulator` — the modulator perturbs z values dynamically. Out-of-scope for static composition; would be addressed once base z-stratification (Proposal B) lands.

## What ships now (this PR)

This audit document. No code changes — every code edit needs OBS-side before/after verification per spec + the global screenshot-evidence directive.

## What ships next (deferred)

Apply Proposals A–D individually with before/after OBS capture per change. Either:
1. Operator runs each diff in turn on the live compositor, captures before/after, ships the diff.
2. An offline render path lands (operator open question #1 in PR #2829) and any lane can capture before/after locally.

The proposals are ordered by safety (A before B before C before D — each can be applied independently).
