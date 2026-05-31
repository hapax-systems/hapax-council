# screwm Cairo/Pango → GPU Port — Deployable Implementation Spec

**Date:** 2026-05-30
**Status:** Design ratified — supersedes Lane K ("keep Cairo on CPU") of `2026-05-30-screwm-gpu-pixel-fullport-design.md` per operator directive.
**Owner:** alpha (lead architect); single-lane direct implementation (no subagent-written persistent code per global git-safety mandate).
**Operator directive (verbatim):** "if cairo is the blocker, fully port over to a non-cpu-bound solution."
**Continues:** the GPU pixel-path effort — drift port (#3759, `screwm_media_drift`) already shipped and proven on the 5060 Ti.

---

## 0. Executive decision (read this first)

We build a **standalone Rust wgpu headless daemon, `screwm_ward_atlas`**, a sibling of the already-shipped `screwm_media_drift` binary. It:

- renders the full 2048×2304 ward-atlas (and the three 1344×176 tickers) on the **5060 Ti (GPU1)**;
- uses **hand-written WGSL pipelines + a startup CPU glyph-atlas bake** for text — **NOT vello, NOT glyphon**;
- stays **in-tree on `wgpu = "24"` / `naga = "24"`** (no crate-wide version bump, no separate-process-version escape needed — but the separate *process* boundary is still used, see §2.4);
- writes the **byte-identical BGRA shm contract** (`18,874,368` bytes atlas / `946,176` bytes ticker, atomic `tmp+rename`) that DarkPlaces already reads;
- **folds the NumPy drift pass into a WGSL fragment pass in-process** (reusing the `screwm_media_drift` shader), reclaiming the largest single CPU cost;
- ships **dormant**, cuts over **per-mount via env flag**, and keeps the **Python Cairo producers byte-for-byte intact as instant rollback**.

The decision is driven by the adversarial verdicts, not the research enthusiasm. The two things the prior spec called fatal — wgpu-version conflict and "no clean wgpu text path" — were both **conditionalized, not confirmed fatal**, but the *specific* engine choices the research strands championed (vello; glyphon) each carry a refuted or conditionalized sub-claim that disqualifies them as the primary text path. The custom-WGSL + glyph-atlas approach is the only path that survives **all six** verdicts simultaneously. §2 and §7 carry the full reasoning.

---

## 1. Context — why Cairo is the blocker, and why we override the prior verdict

### 1.1 The ~69% measurement (live, verified)

The ward-atlas producer `scripts/quake-live-ward-atlas-source.py` (live PID 122168, args `2048x2304 @0.5fps --drift on --drift-intensity 1.6`) is measured at **70.3–70.6% of a CPU core** — the single heaviest screwm CPU producer. At 0.5 fps this is **per-frame work, not cadence**: each tick costs ~1.4 s of CPU time. The cost decomposes (verified by benchmark in Claim 4) as:

1. **Full-frame NumPy drift pass** (`quake_media_drift.apply_frame_drift`) over the whole 18.9 MB BGRA buffer — chroma-split `np.roll`, temporal-feedback blend against history, Sobel-ish edge, up to 18 RNG block displacements, full-array Gaussian noise, scanlines, pulse tint. Benchmarked conservative subset = **~627 ms/frame** = ~31% of a core alone. This is the **dominant** cost and it is currently **fully CPU-bound** (the Rust drift twin exists but is not deployed against this producer).
2. **36 synchronous `tick_once()` Cairo source renders + 36 scaled blits**, with **zero atlas-level dirty-tracking** — every ward re-renders unconditionally every tick (cost driver #1 in the map).
3. **GEM** specifically: 4-step NumPy Gray-Scott RD + 3 graffiti layers × `render_text_to_surface`, each doing `PangoCairo.show_layout` **9× (8 outline offsets + 1 fg)** ≈ **27 Pango shapes/frame** + 3 surface blits.
4. **Per-glyph toy-font `show_text` + per-glyph `RadialGradient` halos** across legibility + hothouse wards (`emissive_base.py::paint_emissive_glyph`) — the heaviest *text-shaping* load because Cairo's toy API re-shapes every call.
5. Two full-buffer `blake2s` hashes (~33 ms each) + stride-repack readback.

**Adversarial correction folded in (Claim 4, holds @0.84):** the map's hedge that "`CairoSourceRunner` background threads run at per-ward `rate_hz` independently" was **disconfirmed** — the producer calls `construct_backend(...)` but **never calls `.start()`**; `tick_once()` is a synchronous inline `_render_one_frame()`. Therefore **100% of the ~70% is in the synchronous per-frame path the GPU port targets.** There is no un-portable background-thread residual. This *strengthens* the case for the port.

**Adversarial correction folded in (Claims 1/3/4/5/6):** the map repeatedly asserts `Px437 IBM VGA 8x16` is **not installed**; on this host it **is** installed (`fc-match 'Px437 IBM VGA 8x16'` → `Px437_IBM_VGA_8x16.ttf`, system-wide and in the user fonts dir). The map's "fontconfig fallback cost" (cost driver #4) is therefore **overstated** — it is not a meaningful slice of the 70%. Conversely, `JetBrains Mono Bold` does **not** resolve cleanly (`fc-match 'JetBrains Mono:bold'` → Noto Sans; only the Nerd Font variant is installed), so the **current Cairo baseline is already falling back for that face** — a GPU port that bundles the real TTF is parity-or-better, not a regression. **We bundle both faces.**

### 1.2 What the prior spec said about Cairo — and why we override it

`2026-05-30-screwm-gpu-pixel-fullport-design.md` Lane K ("keep-CPU, decided") explicitly declined the port, verbatim:

> "**Decision: keep all Cairo/Pango on CPU.**" … "Text shaping has no cheap wgpu path; glyphon/cosmic-text would reimplement Pango layout for marginal raster saving. Not worth it." … "[ward-atlas] cost is **36 `tick_once()` source backends + 36 scaled blits**, not the raster primitive … its vector content … has no clean GPU text/vector path. A glyphon+quad-compositor port (~2 days) helps only if it ever profiles hot; do not pre-emptively port."

**This spec overrides Lane K on the operator's explicit directive.** The override is justified on the prior spec's *own* terms:

- It "profiles hot" — 70% of a core, the named #1 CPU producer. The "only if it ever profiles hot" condition is **met**.
- The prior spec's framing that "the cost is orchestration, not the raster primitive" is **correct and is exactly why this design works**: we attack the orchestration (36-cell recomposite → one render pass with 36 scissor rects, no per-ward surface alloc), the drift pass (NumPy → WGSL fragment pass), GEM's RD (NumPy → compute shader) and the 27-Pango-shapes (→ one instanced quad batch), **not** raster throughput. We do not justify the port on raster Mpx/s.
- The "no clean wgpu text path" objection is dissolved by **not using a general 2D text engine**. The ward content is monospace/Latin/CP437, no bidi, no complex shaping, emoji explicitly refused — so a baked glyph atlas + nearest-neighbor quads is *more* faithful (pixel-exact, no-AA) than any AA shaper, and the layout layer is bounded arithmetic.

### 1.3 The parity bar (from the visual-invariant MAP)

The GPU output is the act that moves the wgpu visual surface **from "excluded" → "governed"** under the Logos design language (`docs/logos-design-language.md:568`). It must therefore meet the full bar:

1. **Semantic color from palette tokens, zero hardcoded hex** (3 exemptions only); dual-palette mode-aware (`HomagePackage` roles: `background/muted/terminal_default/bright/accent_cyan/magenta/green/yellow/red/blue`).
2. **On-stream text ≥12px** or `<RedactWhenLive>`; broadcast chroma ceiling on red/yellow-400 (luminance >0.7 ∧ saturation >0.85 → 15% chroma mute via oklch mix).
3. **No-blink / no-global-flash:** zero pulses in **3–55 Hz** for >0.5 s (`hapax_ward_risky_frequency_violations_total` must read **0**); no luminance change >40% faster than 500 ms; all transitions ≥200 ms with the three-phase **anticipate(80–200ms) → commit(60–120ms) → settle(400–900ms)** envelope (`|dv/dt| < 1/0.2 s`); **no global flash/dim/pulse at all** (no global luminance multiplier exists in the pipeline).
4. **Anti-face (HARDM-carry-forward):** no bilateral eye-pair, no synchronized mouth-line, no flesh tones (`R>G>B ∧ R/B>1.3 ∧ G/B>1.1`), columnar/geometric activation only; pronoun test (≥2/3 say "thing"); GEAL geometric fundamentals preserved.
5. **GEM:** flat CP437 raster, **no AA**, hard `zero-cut`/`overstrike` transitions (never fade), `MIN_FRAME_HOLD_MS=400` enforced, idle `fill` never blank.
6. **Scrim fail-closed:** stale/missing source → quiet posture (`neutral_hold`/`minimum_density`), never auto-public.
7. **Governance:** golden-PNG operator sign-off, anti-personification linter clean, PR cites which invariant the output does not violate; touching `shared/governance/` or `CLAUDE.md` requires `@ryanklee` review.

---

## 2. Engine decision — custom wgpu-24 WGSL + baked glyph atlas

### 2.1 The candidates and their disqualifiers

| Engine | wgpu-24? | Disqualifier (from verdicts) |
|---|---|---|
| **vello (latest 0.9.0)** | No (wgpu 29) | 5-major bump; **Claim 5 REFUTES maturity** — self-declared alpha, conflation artifacts (hairline seams in dense CP437 box-draw — exactly GEM/ascii/tufte content), unfinished GPU-mem allocation (RSS risk over multi-day), quarterly wgpu-major churn. |
| **vello 0.5.0** | **Yes** (`wgpu ^24.0.3`) | wgpu-compat survives (Claim 2), but **Claim 1 REFUTES it for text** — no per-draw AA-off toggle, fights the load-bearing no-AA CP437 bar; conflation seams. Usable for vector only, not text. |
| **glyphon 0.8.0** | **Yes** (`wgpu ^24`, `cosmic-text ^0.12`, no naga) | Viable text path, but **shapes nothing of the Pango layer** (markup/ellipsize hand-rolled regardless), **rasterizes glyphs on CPU via swash** (Claim 2/4 caveat — only the atlas/composite moves to GPU), and forces `=0.8.0` pin forever (0.9→wgpu25). Heavier dep tree for *less* control over the no-AA pixel grid than we get from baking the atlas ourselves. |
| **femtovg 0.25** | No (wgpu 28/29) | No dashing, separable-blend uncertain, weak no-AA CP437 story, no wgpu-24 release. |
| **skia-safe (Ganesh/Vulkan)** | wgpu-independent | Full parity, wgpu-decoupled — **the strongest correctness bet**. Disqualified on *operational* grounds: heavy C++ vendored dep, likely from-source Vulkan build (20–40 min, GN/ninja/clang), Graphite not released. Kept as the **documented fallback** if the custom path fails golden-PNG sign-off (§7). |
| **tiny-skia / vello_cpu** | CPU-only | **Violate the non-CPU mandate.** Rejected. |
| **custom wgpu-24 WGSL + baked glyph atlas** | **Yes (in-tree)** | **Survives all six verdicts.** Chosen. |

### 2.2 Why the custom path wins (verdict-by-verdict)

- **Claim 1 (parity, conditional 0.72):** holds *only* under "text uses glyphon-0.8 OR a custom baked glyph atlas — NOT vello-for-text" and "real Px437 TTF bundled" and "parity = golden-PNG perceptual, not pixel-exact." The custom atlas satisfies the first condition more directly than glyphon (we own the rasterization → guaranteed nearest-neighbor no-AA on CP437, alpha-threshold for the pixel grid). We bundle the TTF. We adopt golden-PNG sign-off (§4).
- **Claim 2 (version-compat, holds 0.9):** the custom path pulls **zero new GPU crates** — it lives in-tree on `wgpu 24.0.5 / naga 24.0.0`, no glyphon/vello/cosmic-text major to reconcile, no second naga in the tree (which would break the deliberate naga-major==wgpu-major static-validator coupling). The separate *process* boundary is retained for fault isolation (a panic can't take down `hapax-logos`), but no *version* escape is needed.
- **Claim 3 (text-shaping parity, conditional 0.72):** the hard sub-claim is the **no-AA integer-pixel-grid reproduction**. We own this end-to-end: bake Px437 to an `R8Unorm` atlas at startup with a CPU rasterizer, **threshold coverage to 0/255**, place glyphs on the exact integer grid (matching `HINT_METRICS_ON`). swash/glyphon would force us to coax this out of an AA shaper. END-ellipsize and markup-span parsing are hand-rolled in `build_scene` (bounded — see §3.3); the verdict confirms the live markup surface is *effectively plain text* (album_overlay escapes all markup; the only other markup site is the dead GStreamer path).
- **Claim 4 (CPU saving real, holds 0.84):** the win is load-bearing on "drift moves too." We **fold drift in-process** (default `--inline-drift`). The synchronous-path concentration (no background threads) means the entire 70% is reclaimable.
- **Claim 5 (maturity, conditional 0.82):** holds for "glyphon-0.8 + WGSL" and is **refuted for vello**. The custom path is *strictly more stable* than the glyphon variant — fewer moving crates, all in-tree, riding the already-proven `screwm_media_drift` skeleton (which the verdict empirically ran headless on the 5060 Ti, producing a varied non-passthrough BGRA frame).
- **Claim 6 (VRAM/perf, conditional 0.78):** the footprint is <200 MiB, trivially under the 14 GiB NO-GO. The real risk the verdict names is **text-shaping parity, not VRAM** — addressed by §3.3 + §4 + §7, not by resource headroom.

### 2.3 The load-bearing wgpu-version decision (explicit)

**Decision: stay in-tree on wgpu 24 / naga 24, in a new binary inside the `hapax-visual` crate, hand-written WGSL only. Do NOT bump hapax-visual's wgpu. Do NOT pull vello/glyphon. Do NOT spin a separate-version crate.**

Rationale, ranked against the three options the brief names:

1. **Bump `hapax-visual` to wgpu 29 (rejected):** 5-major churn (24→25→26→27→28→29) across `dynamic_pipeline.rs`, every reverie/screwm WGSL node, and the naga static validator (`media_drift.rs:317`), with regression risk across *all* visual surfaces, to gain features the wards don't need. High blast radius, low payoff.
2. **Separate crate/process with its own wgpu version (partially adopted):** we **adopt the separate-process boundary** (the shm BGRA file is the entire ABI, zero GPU-object handoff — exactly how `screwm_media_drift` already runs in production). We do **not** need a *different wgpu version* in it, because the custom WGSL path is wgpu-24-native. So we get the fault-isolation benefit of a sibling binary without the cost of a second wgpu version resident on GPU1.
3. **vello_hybrid (rejected):** `0.0.x`, no API stability, no feature parity, no wgpu-24 release.

This is the verdict-driven choice: Claim 2 establishes the version risk is *manageable on two independent legs*; we take the leg (in-tree wgpu-24) that adds the fewest crates and zero version war, and reinforce it with the process boundary for safety.

### 2.4 Engine summary

- **Service skeleton:** verbatim copy of `screwm_media_drift.rs` — `Instance::new(Backends::VULKAN)` → `enumerate_adapters(VULKAN)` → substring-match env `HAPAX_WARD_ATLAS_GPU` (default `"5060"`) → `request_device(Features::empty(), Limits::default())`. Vulkan-only, 5060-Ti-pinned.
- **Text:** hand-written glyph-atlas quad renderer; CPU glyph bake at startup via **`fontdue = "0.9"`** (pure-Rust rasterizer, no wgpu/naga dep) — or `ab_glyph = "0.2"` as an equivalent; either is fine, `fontdue` chosen for its simple coverage-bitmap API that we threshold. Atlas stored as `R8Unorm` GPU texture.
- **Vector:** ~4 hand-written WGSL pipelines (instanced rects, instanced radial-falloff quads for arcs/dots/halos, polyline ribbon, image blit + Bayer-dither). No vello.
- **GEM RD:** WGSL compute shader (Gray-Scott 5-point Laplacian → 3×3 stencil), `Rg32Float` ping-pong, resident frame-to-frame.
- **Drift:** reuse the existing `screwm_media_drift` WGSL fragment pass, inline by default.
- **Output:** render to `Bgra8Unorm` → readback bytes already B,G,R,A → **no R/B swap anywhere in the wgpu path** (the single most important integration detail vs vello, which forces `Rgba8Unorm` + swizzle).

---

## 3. Port architecture — the `screwm_ward_atlas` service

Mirrors `screwm_media_drift` for lifecycle; the only genuinely new subsystem is text → glyph quads.

### 3.1 Binary + slot model

**Binary:** `hapax-logos/crates/hapax-visual/src/bin/screwm_ward_atlas.rs` (sibling of `screwm_media_drift.rs`).

Slot-spec driven, exactly like the drift binary's `HAPAX_SCREWM_DRIFT_SLOTS`:

```
HAPAX_WARD_ATLAS_SLOTS=ward-atlas:2048x2304@2,ticker-grounding:1344x176@8,ticker-precedent:1344x176@8,ticker-chronicle:1344x176@8
```

Each slot is a `SlotGpu { target_tex, scene_builder, dirty_state }`. The ward-atlas slot runs the full 36-cell pipeline; ticker slots run the scroll-text subset (§3.5). One device, one instance, built once; per-slot loop at the slot's fps.

### 3.2 Per-frame pipeline (replaces Cairo recomposite + NumPy drift)

```
build_scene(shm_inputs) -> WardScene IR        [CPU, cheap, dirty-gated, §3.3]
  if no cell dirty AND no animation active: SKIP frame entirely (no pass, no readback, no write)
  else:
    one RenderPass into atlas_tex (Bgra8Unorm 2048x2304):
       1. clear to bg scrim (0.015,0.020,0.030), load=Clear
       2. for cell in 0..36:
            set_scissor_rect(cell.x, cell.y, 512, 256)   # storage-only cells, NO borders/chrome
            draw glyph-quad batch (instanced)             # text wards
            draw vector batch (instanced rects/arcs/lines)# m8, token_pole, emissive
            sample RD substrate tex (GEM)                 # compute -> sampled bilinear
            apply emphasis alpha-group if set             # push_layer + alpha (border/glow are no-ops)
    if --inline-drift: drift fragment pass atlas_tex -> atlas_tex_out   [§3.6, reused WGSL]
    256-aligned copy_texture_to_buffer -> staging
    map_async(Read) + poll(Wait)  (batched across slots, §6)
    de-pad (2048*4=8192 already 256-aligned -> straight copy of 18,874,368 bytes)
    atomic tmp+rename -> /dev/shm/hapax-compositor/quake-live-ward-atlas.bgra
```

Two textures ping-pong: `atlas_tex` (scene) → drift → `atlas_tex_out`. Drift-off mounts render straight into the readback-source texture.

The 36 cells render in **one pass** via `set_scissor_rect` per cell (each cell at `(col*512, row*256)`, 4 cols × 9 rows). This eliminates the 36 separate Cairo surfaces + 36 `set_source_surface`+`paint` blits that are the dominant orchestration cost.

### 3.3 Scene construction — `build_scene` (the data-driven draw-command builder)

The Python producer was an *aggregator* — it re-ran each ward's `CairoSource.render()`. We do **not** re-run Python. The ward content is already published to `/dev/shm` by upstream data daemons; `build_scene` reads the **same shm sources** the Python producer read and emits GPU geometry. Pure CPU but cheap: JSON parse + glyph layout, **no rasterization, no NumPy**.

**Ward Scene IR (per-frame):**

```rust
struct WardScene { cells: [WardCell; 36] }
struct WardCell {
    index: u8, rect: [f32; 4],                  // cell scissor in atlas space
    state: CellState,                           // Present | Stale | Missing -> fail-closed flat-bg
    bg_role: PaletteRole,                        // resolved, NEVER hex
    kind: WardKind,                              // TextGrid | EmissiveGlyphs | Waveform | RDSubstrate | ImageBlit | VectorField
    layers: Vec<DrawLayer>,
    emphasis: Option<Emphasis>,                  // from ward_properties.json (alpha-group only)
    drift: DriftSpec,                            // sine | circle | static
    content_hash: u64,                           // over IR inputs, NOT pixels (cheaper than blake2s)
}
enum DrawLayer {
    GlyphRun  { font_id: FontId, px: f32, glyphs: Vec<GlyphInstance>, fg_role: PaletteRole, outline: OutlineSpec },
    Quads     { rects: Vec<RectInstance>, role: PaletteRole, op: BlendOp },
    Polyline  { pts: Vec<[f32;2]>, width: f32, role: PaletteRole },   // m8, ticker baselines
    Arc       { center: [f32;2], r: f32, role: PaletteRole, fill: bool }, // bullets, token_pole points
    Substrate { rd_ref: RdStateRef },             // GEM Gray-Scott
    Image     { tex_id: ImgId, fit_rect: [f32;4], dither: Option<MircPalette> }, // album, cbip IR
}
struct GlyphInstance { atlas_uv: [f32;4], dest_xy: [f32;2], fg_role: PaletteRole, style: u8 }
```

**Color is always a `PaletteRole`, never hex.** A startup-resolved `HomagePackage` palette table is uploaded as a small storage buffer; shaders index it by role id. Mode-switch (Gruvbox↔Solarized) re-uploads the table only — honors "no hardcoded hex" and dual-palette mode-awareness. **Broadcast chroma ceiling** (red/yellow-400) is applied at table-build time (oklch 85/15 mix), so it cannot be bypassed downstream.

**Shm input inventory** (identical files Python read):

| Ward group | shm source | → IR |
|---|---|---|
| legibility (activity/stance/grounding) | `/dev/shm/hapax-director/narrative-state.json` + director-intent JSONL | GlyphRun + EmissiveGlyphs |
| tickers | `hapax-state/stream-experiment/director-intent.jsonl` (tail) | scrolling GlyphRun |
| GEM | graffiti text source + RD state | 3 GlyphRun layers; RD on GPU |
| album | PNG cover in shm | decode once (turbojpeg/png — already `hapax-visual` deps) → Image + dither |
| programme/lore/research wards | their JSON/state shm | TextGrid GlyphRun |
| m8_oscilloscope | waveform shm | Polyline |
| cbip_dual_ir/signal_density | IR displacement shm images | Image + chroma-diff shader |
| universal emphasis | `ward_properties.json` (200ms-cached) | Emphasis (glow/border are **no-ops** per directive — alpha-group only) |

**Text → glyph quads (the only new subsystem):**

- **Glyph atlas baked once at startup.** Bundle the real `Px437 IBM VGA 8x16` TTF + `JetBrains Mono Bold` TTF in the binary (or load from a pinned asset path under `hapax-logos/assets/fonts/`). Rasterize the needed glyph sets — printable ASCII, **CP437 box-draw/block** (`░▒▓█─│┌┐└┘╔═╗║»«╱╲`), **braille U+2800–28FF** — into an `R8Unorm` atlas with `fontdue`. **Pixel face → threshold coverage to 0/255, nearest-neighbor sample (no AA)** matching `ANTIALIAS_NONE` + `HINT_STYLE_FULL` + `HINT_METRICS_ON`. **Proportional face (JetBrains Mono Bold) → keep grayscale coverage in the alpha channel** matching `ANTIALIAS_GRAY`.
- **Layout** is an advance walk in `build_scene`: CP437 wards are fixed-advance (pure arithmetic); the few proportional wards measure via fontdue metrics. Implement the bounded Pango subset: `set_width` (px wrap bound), `set_wrap` (WORD/CHAR/WORD_CHAR), `set_line_spacing`, **END-ellipsize** (measure runs, cut, append `…` — hand-rolled, load-bearing for the 3 tickers), and the `MAX_PANGO_TEXT_CHARS=8000` truncation guard (Cairo 32767px surface-cap dodge).
- **Markup** (`set_markup` — album/gem/stream_overlay): per-span `fg_role`/style flags carried on each `GlyphInstance`. Verdict-confirmed the live markup surface is effectively plain text (album escapes everything; other site is dead), so a minimal italic/color span parser suffices; we still implement it for correctness.
- **Outline passes** (album 4-offset, GEM 8-offset `OUTLINE_OFFSETS_8`): **instance multiplication** — emit outline glyphs at offset positions in `outline_role`, then fg glyphs. GEM's "27 Pango layouts/frame" collapses to **one instanced quad batch** (9× instances).
- **Emissive glyphs** (legibility/hothouse, `paint_emissive_glyph`): glyph quad + a radial-falloff halo quad behind it (`1 - smoothstep(r)` fragment), both instanced. Per-glyph `RadialGradient` → fragment falloff; no per-glyph gradient object.
- **Emoji refused** to match the GEM `_EMOJI_RE` gate — we never feed emoji codepoints to the atlas; strip upstream in `build_scene`.

### 3.4 Vector / substrate / image layers

- **Polyline** (m8 oscilloscope, ticker baselines, speech-wave if revived): expand to a triangle-strip ribbon; **amplitude-driven width/alpha preserved** (operator's tight-reactivity invariant). One draw.
- **Arc/dot** (bullets, token_pole 11 points): instanced quads + radial-falloff fragment.
- **GEM RD substrate:** WGSL compute shader, 4 Gray-Scott steps/render on a 230×30 `Rg32Float` ping-pong texture (5-point Laplacian → 3×3 stencil), brightness-clamped 0.35, bilinear-upscaled when sampled into the 1840×240 cell region. Resident frame-to-frame. Far cheaper than NumPy.
- **Image** (album cover, cbip IR): upload decoded RGBA once, re-upload only on shm-mtime change; fit-scale in the vertex stage. **mIRC-16 ordered-dither** PIL quantize → fragment Bayer-dither against the 16-role palette table (the "fragment-shader dither" the map suggests).
- **Gradients (Linear/Radial) NOT ported:** the only consumer was the reverie proxy, and reverie renders **nothing** in the atlas (`DIRECT_TEXTURE_WARDS`, dead path). The richest vector path is **out of scope** — confirmed dead by the map.

### 3.5 Tickers (same binary, scroll-text subset)

Each ticker slot runs GlyphRun-only: header color-lerp cyan→magenta on `(now*0.18)%1` phase (a *tonal* cycle, not a luminance flash — §3.6 compliant), bullet `Arc`+fill dots, scroll via animating `TextArea.left`-equivalent = `x = 42 - (now*42)%span` in the vertex offset, clipped by the cell scissor. The glyph atlas is built once; the scroll is a per-frame vertex offset — far cheaper than Pango re-shaping per tile. 236K px each, trivially cheap.

### 3.6 Animation — drift-gated, no-blink, dirty-tracked

**Frame pacing** (copied from `screwm_media_drift::run`): fixed-cadence loop, `period = 1/fps`. **Atlas = 2 fps** (engine dedups on mtime; no benefit beyond 2). **Tickers = 8 fps.** Engine consumes at its own 60 fps render-thread rate, re-uploading only on mtime/size change.

**Dirty-tracking (the GPU-cost killer):**
- `content_hash` per cell over the *deserialized IR inputs* (not pixels — cheaper than the map's two full-buffer `blake2s`).
- A cell is **dirty** if its source shm mtime changed OR it has live animation (GEM RD, drift motion, ticker scroll, oscilloscope).
- **Zero dirty + no animation → skip the whole frame** (no pass, no readback, no write). Engine keeps blitting the last atlas. This is the dominant win over the Python producer's unconditional 36-ward re-render.
- If any cell is animated, the full one-pass render runs (2 fps, trivially cheap on GPU); **readback+write is skipped if the readback content is unchanged**. Animated cells almost always change the buffer, so this mostly saves on all-static frames.

**No-blink / no-global-flash enforcement (baked into shaders + envelope):**
- **Per-ward drift** = vertex-stage position offset (`drift_sine` hz=0.1 amp=3px default, `drift_circle`, `static`). Spatial, not luminance. Satisfies "prefer drift over flashing."
- **No global luminance multiplier exists** anywhere in the pipeline. Reactivity is spatial/tonal/cyclic only.
- All state transitions use the three-phase **anticipate(80–200ms)→commit(60–120ms)→settle(400–900ms)** curve — port `shared/geal_curves.py` to a **WGSL easing LUT** (uploaded once). Hard guarantees: `|dv/dt| < 1/0.2 s`; no luminance change >40%/500 ms; **zero pulses 3–55 Hz**.
- **GEM transitions stay hard `zero-cut`/`overstrike`** (instant glyph swap = content change, not luminance flash), `MIN_FRAME_HOLD_MS=400` enforced in `build_scene`.
- **Emphasis** is alpha-group composite only (glow/border no-ops) — `push_layer` render-to-temp + `paint_with_alpha`, matching the Cairo `push_group`/`pop_group_to_source` path.

### 3.7 Data-flow summary (one line)

`live ward-content shm (JSON/JSONL/PNG/waveform) → build_scene() → WardScene IR (palette-role colored, glyph-laid) → GPU upload (glyph atlas resident, RD compute resident) → single 36-scissor render pass into Bgra8Unorm 2048×2304 → [inline drift WGSL] → 256-aligned copy_texture_to_buffer → map_async readback (BGRA, no swap) → atomic tmp+rename → /dev/shm/hapax-compositor/quake-live-ward-atlas.bgra → DarkPlaces R_UpdateTexture slot 8 @ 60fps mtime-dedup.`

---

## 4. Visual parity strategy + the AVSDLC witness

Parity is **perceptual/aesthetic (golden-PNG operator sign-off + photosensitivity gate), NOT pixel-exact** — Claim 1's condition (4). AA-blended proportional faces and hinting metrics will differ; the bar is the §1.3 invariant set, not a pixel diff. This aligns with the project AVSDLC contract at `docs/methodology/avsdlc-visual-evidence-contract.md` (duration-bound OBS-frame motion metric, never engine `frame=N`, never a single screenshot).

### 4.1 The witness harness (`tests/witness/ward_atlas_parity/`)

Two complementary witnesses, both run in CI and pre-cutover:

**(A) Static golden-frame diff (per-ward, per-state).** For a fixed set of synthetic shm fixtures (one per ward kind × key state: present/stale/missing, emphasis on/off, GEM idle/active, ticker short/scrolling), capture both:
- the **Cairo baseline** BGRA (run the Python producer once against the fixture, write to a fixture path), and
- the **GPU** BGRA (`screwm_ward_atlas` shadow output against the same fixture).

Compare with a **perceptual metric** (SSIM per cell, plus a CP437-grid structural check), NOT byte-equality. Emit a side-by-side PNG montage per ward for **operator golden sign-off**. Threshold: SSIM ≥ 0.92 per cell OR explicit operator override (the bar is the operator's eye — the operator signs golden PNGs once, not every PR, per `feedback_operator_never_reviews`).

**(B) Duration-bound OBS-frame motion metric (the AVSDLC temporal witness).** Capture **N seconds** (default 10 s) of consecutive output frames from both producers at their native cadence and assert, on the *temporal* signal:
- **No luminance swing >40% within any 500 ms window** (per-pixel and per-cell-mean).
- **No periodicity in the 3–55 Hz band** with sustained amplitude >0.5 s (FFT the per-cell mean-luminance time series; `hapax_ward_risky_frequency_violations_total` must read **0**).
- **All transitions ≥200 ms** (`|dΔluminance/dt|` bounded; no step faster than 200 ms).
- **Stream-stability lower bound simultaneously holds:** each on-stream animation satisfies ≥1 of {opacity Δ≥0.5, position/scale Δ≥2px, color crossing a semantic boundary} so it survives lossy H.264 — held *with* the no-blink cap via slow smooth envelopes.

This is the AVSDLC ("animated visual SDLC") witness: a duration-bound OBS-frame motion metric that proves the no-blink/no-flash invariants on the *actual rendered output*, plus the side-by-side-vs-Cairo static parity. **Both must pass before cutover.**

### 4.2 Governance gates (must pass to merge)

- **Anti-personification linter** (`shared/anti_personification_linter.py`) clean over any GEAL-adjacent geometry; PR cites which anti-anthropomorphization invariant the output does not violate.
- **Pronoun test:** ≥2/3 naïve viewers say "thing" not "visual" on a captured GEAL/GEM segment.
- **No-hex audit:** static check that the WGSL/scene path resolves all color via the palette role table (the only literals permitted are the §8 exemptions).
- Touching `shared/governance/scrim_invariants/` or `CLAUDE.md` → `@ryanklee` review (CODEOWNERS).

---

## 5. Migration + rollback — dormant-then-cutover, per-mount, instant rollback

Mirrors the drift port's pattern. The Python Cairo producers stay **byte-for-byte intact** as instant rollback — they are never edited.

### 5.1 Phase 0 — build dormant

Land the `screwm_ward_atlas` binary + systemd unit `hapax-ward-atlas-gpu.service`, **installed but disabled**. It writes to a **shadow path** `/dev/shm/hapax-compositor/quake-live-ward-atlas.gpu.bgra` (NOT the engine-read path), plus `quake-live-ticker-*.gpu.bgra`. Validate offline against the Python `.bgra` via the §4 witness.

### 5.2 Phase 1 — per-mount cutover flag

Cutover is **per slot via env, not all-or-nothing**:
- GPU service env `HAPAX_WARD_ATLAS_ACTIVE_SLOTS=ward-atlas` makes it write the *real* engine path for **only** the listed slots (others stay shadow).
- The Python producer's systemd unit for a given mount is **stopped** when the GPU service owns that slot's real path; otherwise Python keeps writing.

Both write the **identical filename + byte-exact size** (`18,874,368` / `946,176`), and the engine dedups on mtime — so the engine is oblivious to which producer owns the file. Handoff: `systemctl --user stop hapax-quake-live-<slot>` → add slot to `HAPAX_WARD_ATLAS_ACTIVE_SLOTS` → `systemctl --user reload-or-restart hapax-ward-atlas-gpu`. Sub-second gap; engine blits last frame across it. **Note:** this handoff is *exporter-class* (Python→shm→engine re-reads each frame, no engine restart, no CSQC/fteqcc recompile) — it deploys LIVE, unlike CSQC/shader changes which need the witnessed broadcast-restart window.

**Cutover order (lowest → highest risk):** tickers first (3 trivial mounts) → then the ward-atlas (the big one). Each is one slot flip.

### 5.3 Rollback (instant)

Remove the slot from `HAPAX_WARD_ATLAS_ACTIVE_SLOTS` (GPU service drops back to shadow for it) and `systemctl --user start hapax-quake-live-<slot>`. The Python code never changed → rollback is restarting a known-good unit. No rebuild, no data migration. Satisfies "never stall — revert acceptable" and "Python Cairo producer as instant rollback."

### 5.4 Drift interaction

Default **`--inline-drift`**: the ward service folds drift in-process (reusing the media-drift WGSL) and writes the final `.bgra` directly — one process, one readback, lower latency. Fallback **two-process chain**: ward service writes `quake-live-ward-atlas.raw.bgra`; the existing `screwm_media_drift` service produces the final `.bgra` (the established `.raw.bgra`→`.bgra` convention). Chosen per-mount by the flag.

---

## 6. Perf / VRAM guardrails + NO-GO thresholds

**Target: 5060 Ti (GPU1)**, alongside drift + (intended) STT + imagination. Honors the prior spec's guardrails.

- **5060 Ti free ≈ 9.4 GiB** after STT warm (live measured 13.9 GiB free *today* because STT currently allocates on GPU0 — see verdict note below); **soft ceiling 14.0 GiB**. **NO-GO if `memory.used(GPU1) > 14000 MiB`.**
- **Footprint of this service (< 200 MiB):** atlas `Bgra8Unorm` 2048×2304 ×2 ≈ 36 MiB; 4 ticker targets ×2 ≈ 30 MiB; `R8` glyph atlas (a few 2K×2K) ≈ 16 MiB; GEM RD ping-pong (230×30 `Rg32F`) negligible; album/IR images a few MiB; staging buffers ≈ 36 MiB. Trivial against headroom.
- **0 bytes on the 5090 (GPU0):** Vulkan adapter substring-pinned to `"5060"`. **Pre-deploy assert `memory.used(GPU0) ≤ 27500 MiB`** (hard ceiling 30.5 GiB). NVENC sessions unchanged (port adds 0).
- **CPUAffinity / AllowedCPUs excludes audio-reserved cores** on the systemd unit — the entire point is to *reclaim* the ~70% core the Python producer pegs; that core returns to audio/cognition. (Claim 4: the reclaimed work genuinely leaves the CPU only if drift is folded in — it is, by default.)
- **1080p60 always.** The engine runs its 60 fps GL render thread on GPU0; this service is decoupled by the shm file ABI and adds 0 bytes to GPU0, so 1080p60 is structurally untouched. **NO-GO:** engine `R_RenderView` frame interval > 16.6 ms sustained (< 58 fps), OR any slot's effective output cadence < its producer fps for >2 s, OR TTS latency +15%.
- **Throughput fix (the one inherited bug):** `screwm_media_drift` does serialized per-slot `map_async` + `Maintain::Wait` (the P1 multi-slot throughput killer). With 4+ slots, **batch: submit all slot encoders, then drain all `map_async` callbacks in one `device.poll(Wait)`.** At 2/8 fps this is not yet limiting, but implement it from the start since this service carries 4 slots day one.
- **Appendix offload: rejected for the hot path** (engine reads local `/dev/shm`; 2048×2304 BGRA round-trip over the network double-hops at ~4 Gbit/s). If GPU1 ever approaches 14 GiB, **move imagination off, not the ward pixels.**

**Verdict-driven framing correction (Claim 6):** the stated co-tenancy ("alongside drift + STT + imagination on the 5060 Ti") is the *intended* dual-rig state, not the *measured present* — today no Rust drift service runs (drift is on CPU in the Python producer), and STT currently allocates on GPU0. The budget fits comfortably under either accounting; monitor `memory.used(GPU1)` against 14000 MiB as STT/imagination converge onto GPU1.

---

## 7. Honest risks + open questions (verdicts folded in)

The verdicts conditionalized or refuted several research claims. The plan reflects each:

1. **Parity is unvalidated empirically (Claim 1, conditional 0.72).** No golden frames exist yet; feasibility is established in *capability* terms only. **The §4 witness is a hard gate, not a formality.** If the PoC golden-PNG fails operator sign-off, we do not ship — we fall back to **skia-safe/Ganesh-Vulkan** (full parity, wgpu-decoupled, the documented correctness fallback) at the cost of a heavy C++ build. This is the explicit escape if the custom path can't hit the aesthetic bar.

2. **No-AA integer-pixel-grid reproduction is the hardest, most-likely-regression item (Claim 3, conditional 0.72).** Px437 is an **outline TTF, not an embedded-bitmap strike** — so the pixel-perfect bitmap path is unavailable; we must rasterize a hinted alpha mask and **threshold to 0/255** on the exact integer grid. Smudged glyph edges or sub-pixel-shifted box-draw seams in dense CP437 grids (GEM/ascii/tufte) are the real failure mode. **Mitigation:** owning the rasterizer (fontdue) gives us full threshold + grid-snap control (more than swash/glyphon would), and the §4(A) CP437-grid structural check is a dedicated golden item. **Open question:** does fontdue's hinted coverage at 8×16 + threshold reproduce the Cairo `HINT_METRICS_ON` baseline within the SSIM bar? Resolved by the PoC, not assumed.

3. **Text shaping does NOT all leave the CPU under a glyphon path (Claim 2/4 caveat).** glyphon rasterizes glyphs on CPU via swash; only atlas/composite is GPU. **Our custom path moots this** — glyph rasterization happens **once at startup** (the bake), not per-frame; per-frame text is a pure layout-arithmetic + instanced-quad submit. So the CPU residual is genuinely small (200ms-cached JSON reads + monospace advance walk + IR build + atomic write), not a hidden per-frame shaping cost.

4. **wgpu-version-compat is NOT fatal but the engine choice is forced (Claims 1/2).** The custom WGSL path commits to **in-tree wgpu 24** with the separate-*process* escape for fault isolation only. We do **not** rely on vello (refuted for text by AA + maturity) or glyphon (forces `=0.8.0` forever + CPU swash raster). If a future coordinated wgpu-major bump happens for other reasons, **vello 0.9 + parley becomes the superior single-engine target** — documented as the long-horizon migration, not this port's scope.

5. **Maturity holds only for the chosen stack (Claim 5, conditional 0.82).** The verdict **refutes** vello's maturity for a 24/7 daemon (alpha, conflation seams, unfinished GPU-mem allocation, quarterly wgpu churn). The custom path is *strictly more stable* (zero new GPU crates, all in-tree, rides the empirically-proven `screwm_media_drift` skeleton). **Standing risk:** the daemon is **not yet deployed** — this spec overrides a standing verdict and rests on unbuilt code; the dormant-then-cutover phasing (§5) is precisely to de-risk that.

6. **The CPU-saving magnitude is "large" specifically at the ward-atlas (Claim 4).** The 3 tickers are individually trivial (236K px); "large" applies to the 2048×2304 atlas. The drift fold-in is **load-bearing** — a naive port that left NumPy drift on CPU would retain ~31% of a core. We fold it in by default.

7. **Open questions for the PoC to settle (none assumed):**
   - Does the §4(A) SSIM bar pass for GEM's RD-substrate + 8-offset graffiti overlap? (RD is a compute port; visual-equivalence of the upscaled substrate vs NumPy bilinear is unverified.)
   - Does the album mIRC-16 fragment Bayer-dither match the PIL ordered-dither perceptually?
   - Does the cyan→magenta ticker header lerp register as *tonal cycle*, not a 3–55 Hz violation, under the §4(B) FFT? (It is sub-Hz by construction, but verify.)
   - Confirm fontdue glyph metrics for CP437 box-draw align to the Cairo advance grid (else box-draw seams).

8. **Scrim/governance fail-closed (parity bar 6):** stale/missing shm source → cell renders flat-bg `Missing` state (quiet posture), never auto-public. Implemented in `build_scene` `CellState` resolution.

---

## 8. Build sequence

Slots relative to the other pixel-port lanes: this **supersedes Lane K** of `2026-05-30-screwm-gpu-pixel-fullport-design.md`. It runs **after** the drift port (#3759, shipped) and **reuses** its service skeleton; it is **independent** of the remaining decode/perception lanes (the P1 batched-readback throughput fix is shared — implement once here, backport to drift). It does **not** touch the engine-side `.bgra` contract, filenames, sizes, or the DarkPlaces 12-slot live-texture patch — so it is **exporter-class** and deploys LIVE (no CSQC/fteqcc recompile, no `hapax-darkplaces-v4l2` restart).

| # | Step | Artifact | Binary/Config | Gate |
|---|---|---|---|---|
| 0 | Bundle fonts | `Px437 IBM VGA 8x16` + `JetBrains Mono Bold` TTFs in `hapax-logos/assets/fonts/` | config/asset | fonts load via fontdue |
| 1 | **PoC parity render** — single ward (GEM) + one ticker, offline, against a fixed fixture | `screwm_ward_atlas` (PoC mode) | binary | §4(A) SSIM ≥0.92 on GEM cell + operator golden sign-off; **GO/NO-GO for the whole port** |
| 2 | Glyph-atlas + text subsystem (layout arithmetic, wrap/ellipsize/markup, outline instancing, emissive halo) | text module | binary | all text-ward fixtures pass §4(A) |
| 3 | Vector + RD + image layers (polyline, arc, RD compute, Bayer-dither) | WGSL pipelines | binary | m8/token_pole/album/cbip fixtures pass §4(A) |
| 4 | Full 36-cell scene builder + dirty-tracking + inline-drift fold-in + batched readback (P1 fix) | `build_scene` + service loop | binary | full-atlas fixture passes §4(A); skip-frame verified |
| 5 | **AVSDLC temporal witness** over 10 s live-fixture capture | witness harness | `tests/witness/` | §4(B): zero 3–55 Hz, no >40%/500ms swing, transitions ≥200 ms; `hapax_ward_risky_frequency_violations_total == 0` |
| 6 | systemd unit (dormant), shadow-path output, CPUAffinity excludes audio cores, GPU1 pin | `hapax-ward-atlas-gpu.service` | config | unit installed+disabled; shadow output validated vs live Python |
| 7 | Governance gates | anti-personification linter, pronoun test, no-hex audit | — | clean; PR cites invariants; `@ryanklee` review if `shared/governance/` touched |
| 8 | **Cutover: tickers first** (`HAPAX_WARD_ATLAS_ACTIVE_SLOTS=ticker-grounding,...`), stop Python ticker units | config flip | config | live OBS frame check; instant-rollback drill verified |
| 9 | **Cutover: ward-atlas** (`...,ward-atlas`), stop Python ward-atlas unit | config flip | config | live OBS frame check; CPU of reclaimed core confirmed dropped; instant-rollback drill verified |
| 10 | Retire Python producers to dormant (kept on disk for rollback, never deleted) | — | systemd | 48 h soak clean, NO-GO thresholds never tripped |

**Binary vs config:** the entire renderer is **one binary** (`screwm_ward_atlas`) plus the bundled font assets. All cutover/rollback levers are **config** (env on the systemd unit + start/stop of Python units). No engine rebuild, no DarkPlaces patch change, no shared-library change to `hapax-visual`'s lib (it is a new `bin/` target — the lib is untouched).

**GO/NO-GO checkpoint at Step 1:** if the GEM PoC cannot hit the aesthetic bar with the custom path, **stop and fall back to skia-safe/Ganesh-Vulkan** (§7 risk 1) before investing in steps 2–4.

---

## Appendix — referenced files (repo-relative to the council worktree)

- Service template + drift WGSL: `hapax-logos/crates/hapax-visual/src/bin/screwm_media_drift.rs`
- wgpu/naga pin: `hapax-logos/crates/hapax-visual/Cargo.toml` (`wgpu = "24"`, `naga = "24"`)
- New binary (this spec): `hapax-logos/crates/hapax-visual/src/bin/screwm_ward_atlas.rs`
- Python producers (kept as rollback): `scripts/quake-live-ward-atlas-source.py`, `scripts/quake-live-ticker-source.py`, `scripts/quake_media_drift.py`, `scripts/screwm-speech-wave-producer.py`
- Text/emissive/RD semantics to reproduce: `agents/studio_compositor/text_render.py`, `agents/studio_compositor/homage/emissive_base.py`, `agents/studio_compositor/gem_source.py`, `agents/studio_compositor/gem_substrate.py`
- Universal wrappers: `agents/studio_compositor/ward_properties.py`, `agents/studio_compositor/homage/transitional_source.py`
- Per-ward dims/backends: `config/compositor-layouts/default.json`
- Atlas mount contract: `config/screwm-quake-media-mounts.json`
- Envelope LUT source: `shared/geal_curves.py`
- AVSDLC evidence contract: `docs/methodology/avsdlc-visual-evidence-contract.md`
- Visual invariants: `docs/logos-design-language.md`, `docs/superpowers/specs/2026-04-23-geal-spec.md`, `docs/research/2026-04-19-gem-ward-design.md`, `docs/superpowers/specs/2026-04-29-scrim-state-envelope-design.md`, `docs/research/2026-04-20-dynamic-livestream-audit-catalog.md` (§15.2 photosensitive)
- Governance: `shared/governance/scrim_invariants/`, `shared/anti_personification_linter.py`, `.github/CODEOWNERS`
- Prior spec (overridden Lane K, honored guardrails): `docs/superpowers/specs/2026-05-30-screwm-gpu-pixel-fullport-design.md`
- New systemd unit (this spec): `systemd/units/hapax-ward-atlas-gpu.service`
- New witness harness (this spec): `tests/witness/ward_atlas_parity/`
