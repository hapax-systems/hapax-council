# Vinyl Image HOMAGE Ward — Design Spec

**Date:** 2026-04-18
**Task:** #159 (CVS #20)
**Research:** `/tmp/cvs-research-159.md`
**Related:** #127 SPLATTRIBUTION, #125 token pole HOMAGE migration, #157 non-destructive overlay, #142 vinyl rate-aware processing, #124 reverie preservation

---

## 1. Goal

Two deliverables under one ward:

- **Capture enhancement** — raise the vinyl cover from IR-monochrome + hardcoded duotone to true-colour art (cover-DB) with palette-quantized BitchX-authentic rendering.
- **HOMAGE effects** — replace the five-random-PiP-FX dict with a single package-palette-sourced Cairo effect, Px437 typography, scanline/dither grammar, and FSM-choreographed entry/exit gated on `vinyl_playing`.

Operator framing: *clearer image + more interesting effects.*

---

## 2. Current State (verified 2026-04-18)

**Three-stage capture chain:**

1. **Pi-6 edge** (`pi-edge/hapax_ir_edge.py`, `192.168.68.74:8090`) — `rpicam-still` 1920×1080 IR → `/frame.jpg` (raw) + `/album.jpg` (perspective-warped 640² via `ir_album.py::extract_album_crop`) + `/album.json` (rotation/bbox/confidence).
2. **Workstation identifier** (`scripts/album-identifier.py`, `hapax-album-identifier.service`) — currently fetches `/frame.jpg`, center-crops 15% margin, rotates 90°, downscales to 512² Lanczos, applies random 1-of-8 duotone via `ImageOps.colorize`, writes PNG to `/dev/shm/hapax-compositor/album-cover.png`.
3. **Compositor ward** (`agents/studio_compositor/album_overlay.py::AlbumOverlayCairoSource`) — already inherits `HomageTransitionalSource` (Phase 3 shipped); FSM **dormant** behind `HAPAX_HOMAGE_ACTIVE=0`. Renders at 300² inside 300×450 canvas @ `ALPHA=0.85`, picks one of five local PiP effects per album change (`_pip_fx_vintage/cold/neon/film_print/phosphor`). Attribution text above, cover below, JetBrains Mono Bold 10.

**Fidelity loss today:** IR monochrome → center-square crop → random duotone → 1.7× Cairo downscale. Five-PiP-FX dict violates BitchX grammar (per-effect tints instead of package palette).

---

## 3. Source Strategy — Cover-DB PRIMARY, IR FALLBACK

**Operator call (2026-04-18):** cover-DB lookup is the primary image source; IR capture becomes the fallback path.

**Rationale:** true-color authored art > IR-derived duotone for both fidelity and "interesting". IR remains the fallback for deep-catalog vinyl the DB doesn't know.

### 3.1 Cover-DB client (new module)

`scripts/cover_db.py` — new client, called from `album-identifier.py` after artist/title resolution.

- **Lookup order:** MusicBrainz (`/ws/2/release/?query=...`) → Cover Art Archive (`coverartarchive.org/release/{mbid}/front`) → Discogs (`/database/search?type=release&artist=...&track=...`) as secondary.
- **Cache key:** `(artist, title)` tuple, normalized (lowercase, strip punctuation, collapse whitespace).
- **Cache location:** `~/.cache/hapax/cover-db/{sha256(artist|title)}.{jpg,png}` + sidecar `.json` with `{source, fetched_at, mbid, url}`.
- **Budget:** cold-miss network fetch one-off at album change (rate ≈ once per 5–120 s). >1 s acceptable. Warm cache hit ≈ disk read <10 ms.
- **Gating:** lookup proceeds when `album-identifier` confidence ≥ 0.7 AND `(artist, title)` non-empty. On miss (offline / unidentified / rare press), fall through to IR fallback.
- **Offline posture:** no network blocking — if the first call times out (default 2 s), fall through immediately; never delay the PNG write past 500 ms past vision-ID completion.

### 3.2 IR fallback path (retained, simplified)

When cover-DB misses, the IR path takes over, but **consumes Pi-side pre-warped `/album.jpg`** rather than re-cropping `/frame.jpg` (see §4). Duotone colorize is replaced by palette-quantize to the active HomagePackage palette (§5).

---

## 4. Pi-Side Pre-Warp Adoption

**Operator call (2026-04-18):** switch the workstation daemon to consume Pi-side `/album.jpg`.

**Change in `album-identifier.py`:**
- Swap `IR_FRAME_URL = f"http://{PI6_IP}:8090/frame.jpg"` → `/album.jpg`.
- Also fetch `/album.json` for rotation/confidence (honor Pi-side perspective warp instead of re-doing it).
- **Delete:** `rotate(-90, expand=True)`, hardcoded 15% margin center-square crop, Lanczos downscale (Pi already emits 640² q90).
- **Retain:** hash-debounce (hamming < 8), vision-model artist/title resolution (Gemini Flash).

**Savings:** ~8 MB/s network (1080p → 640²), ~30 ms CPU per album change (no Python-side warp), eliminates the hardcoded-rotation assumption (captured by Pi's adaptive quad detection).

**Invalidation:** when `vinyl_playing → False`, clear hash cache so next side re-triggers identification (per §8 below).

---

## 5. BitchX Treatment — Palette Quantize + Single Package-Palette PiP

Replace the five-random-PiP-FX dict with a **single** palette-conformant effect parametrized by the active `HomagePackage`.

### 5.1 Palette quantization

After image arrives (cover-DB bytes OR IR fallback), quantize to mIRC-16 via `Image.quantize(palette=_bitchx_palette_image, dither=Image.Dither.ORDERED)` with a **Bayer 4×4** ordered dither matrix. CP437-authentic compressed-palette read; composes cleanly regardless of upstream source.

### 5.2 Single Cairo PiP effect

New `_pip_fx_package(cr, image, package)` consuming `package.palette.{bg, fg_muted, fg_bright, accent}` + `package.grammar.raster_cell_required`:
- Horizontal scanlines at raster-cell cadence (2 px dark stripes per 4 px row, `fg_muted` over quantized image).
- Ordered-dither shadow under `accent`.
- No rounded corners, no fade, no anti-aliased edges (per `refuses_anti_patterns`).

**Delete** `_pip_fx_vintage`, `_pip_fx_cold`, `_pip_fx_neon`, `_pip_fx_film_print`, `_pip_fx_phosphor` and the per-album-change random selection.

### 5.3 Px437 splattribution

`_draw_attrib()` switches from JetBrains Mono Bold 10 → `Px437 IBM VGA 8x16` (per `_BITCHX_TYPOGRAPHY.primary_font_family`). Line-start marker `»»»` per `_BITCHX_GRAMMAR.line_start_marker`. Colour from `package.resolve_colour(package.grammar.identity_colour_role)`.

---

## 6. HOMAGE Integration

Consume the active `HomagePackage` via `apply_package_grammar(cr, package)` at the top of `render_content()`. Respect:

- **#157 non-destructive tag** — ward is post-shader Cairo (`cairooverlay` tail), outside WGSL gate, but its visual treatment must still pass the `refuses_anti_patterns` lint (no rounded rects, no fades, no flat-UI chrome, no anti-aliased text). Add assertion in `album_overlay` tests.
- **Coupling slot** — consume `uniforms.custom[4]` per `_BITCHX_COUPLING.custom_slot_index=4` for director-aligned intensity.
- **Package palette precedence** — duotone IR fallback uses `(package.palette.fg_muted, package.palette.fg_bright)` as the two-tone pair, not the hardcoded 8-entry tint list (delete that list).

---

## 7. Ward State Transitions

FSM wakes when `HAPAX_HOMAGE_ACTIVE=1`. Gate all paint + resonance emission on `vinyl_playing` (#127):

- **Entry:** on track change (hash changes + `vinyl_playing=True`) → `ticker-scroll-in` over `entering_duration_s=0.4 s`. Scroll the 300×(SIZE+TEXT_BUFFER) column from off-canvas right.
- **Content:** steady paint with §5 treatment.
- **Exit:** on `vinyl_playing=False` → `ticker-scroll-out` symmetric to entry → ABSENT. Clear hash cache (see §4). `color_resonance.py` also gates: emit neutral warmth only (no palette mean read).
- **Track change while playing:** zero-cut-in (swap-in next cover without full scroll) per package grammar.

---

## 8. Budget

- **Per-album-change** (≤ 0.2 Hz, identifier process, off-GPU): cover-DB cold-miss HTTP ≤ 500 ms (soft budget); warm-cache + palette quantize + CLAHE + sharpen ≈ **80–120 ms**. IR fallback adds ~40 ms denoise.
- **Per-frame Cairo paint** (10 fps, compositor): `paint_with_alpha` + scanline loop + dither + Px437 text ≈ **1–3 ms** (within `budget.py` allocation for `album_overlay` source; validated by `publish_costs`).
- **No GPU load** — Cairo post-shader. No reverie budget impact. No TabbyAPI VRAM interference.
- **Network** — worst case one ~200 KB cover fetch per album change. Negligible.

---

## 9. Files

**New:**
- `scripts/cover_db.py` — MusicBrainz/CAA/Discogs client + on-disk cache.
- `agents/studio_compositor/tests/test_album_overlay_homage.py` — package-grammar + non-destructive lint.
- `scripts/tests/test_cover_db.py` — lookup, cache hit/miss, fallback.
- `assets/fonts/homage/bitchx/Px437_IBM_VGA_8x16.ttf` — verify install (may already be present).

**Modified:**
- `scripts/album-identifier.py` — consume `/album.jpg` (not `/frame.jpg`), call `cover_db.fetch`, fall back to IR path + palette-quantize, delete hardcoded rotate/crop, invalidate hash on `vinyl_playing=False`.
- `agents/studio_compositor/album_overlay.py` — delete 5-PiP-FX dict, add `_pip_fx_package`, switch typography to Px437, wire `render_entering`/`render_exiting`/`render_absent`, gate on `vinyl_playing`, apply `apply_package_grammar`.
- `agents/studio_compositor/color_resonance.py` — add explicit `vinyl_playing` gate (currently decays via missing-file).

---

## 10. Test Strategy

- **Cover-DB client:** mock MB/CAA/Discogs responses; assert lookup order; cache hit/miss paths; cold-fetch timeout (2 s) falls through.
- **Palette quantize:** known-input image → mIRC-16 output; Bayer-4 dither matrix applied; no colors outside `_BITCHX_PALETTE` set.
- **IR fallback:** cover-DB miss → IR path activates → palette quantize against package palette (not hardcoded tints).
- **Pi-side consumption:** `/album.jpg` served → identifier consumes without rotate/crop; hash-debounce still triggers.
- **Px437 rendering:** Cairo select font; verify glyph metrics (fallback warns loudly if font missing).
- **FSM transitions:** `vinyl_playing=True` → entering → content → `vinyl_playing=False` → exiting → absent; hash cleared.
- **Non-destructive lint:** assert no rounded-rect Cairo calls, no fade ops, no anti-aliased text in the ward.
- **Budget:** time `render_content()` 100× at 10 fps; assert p95 < 3 ms.

---

## 11. Open Questions

1. **Broadcast rights posture for cover art.** MusicBrainz/CAA is CC0/public; Discogs art licensing is less clear. If broadcast raises concerns for a given label, does the ward degrade to palette-quantized IR automatically, or block per-release? (Recommend: auto-degrade, no per-release block.)
2. **Px437 font install verification.** Is `Px437 IBM VGA 8x16` present on the workstation and inside any compositor container? `assets/fonts/homage/bitchx/README.md` flags as "follow-on." Confirm before Phase wire-up.
3. **Grace period on `vinyl_playing=False`.** #127 SPLATTRIBUTION picks snap-clear vs slow outro; album image should match whatever text policy wins (joint ship).
4. **Rate-aware processing (#142).** At 33⅓ vs 45 vs 78 RPM, does anything in the ward change (paint rate, effect cadence)? Probably no; the ward is album-change-driven, not rate-driven. Confirm against #142 when that spec lands.

---

## 12. Related

- **#127 SPLATTRIBUTION** (`2026-04-18-splattribution-design.md`) — ratifies `vinyl_playing` gate consumed here.
- **#125 token pole HOMAGE migration** — parallel pattern (class inheritance + package palette + coupling slot).
- **#157 non-destructive overlay** — enforcement layer; ward must pass `refuses_anti_patterns` lint.
- **#142 vinyl rate-aware processing** — rate coupling (likely no-op for this ward; confirm).
- **#124 reverie preservation** — vinyl ward is not substrate; full FSM applies, no exemption.

---

**Echo:** `docs/superpowers/specs/2026-04-18-vinyl-image-homage-ward-design.md`
