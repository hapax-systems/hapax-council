# CBIP Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the first two CBIP enhancement families (Palette Lineage + Poster Print) per `docs/superpowers/specs/2026-04-21-cbip-phase-1-design.md`. Land 3 new effect-graph nodes (`posterize`, `kuwahara`, `palette_extract`), the recognizability test harness, the Ring-2 pre-render gate, and the stimmung-coupled + manual-override intensity surface.

**Architecture:** Phase 1 adds three nodes to the effect-graph compiler (two WGSL, one Python/Cairo), composes them into two enhancement families under the existing `album` ward slot, and gates every enhancement output behind a recognizability harness + Ring-2 pre-render check. Operator overrides are additive — stimmung-coupled by default, manual slider wins when set. Round structure (chess/boxing) is Phase 2 and explicitly out of scope here.

**Tech Stack:** Python 3.12+ (pydantic, scikit-learn, imagehash, Tesseract via pytesseract, OpenAI CLIP embeddings, Pillow), WGSL fragment/compute shaders compiled by `agents/effect_graph/wgsl_compiler.py`, Cairo for the palette-extract overlay, pytest with golden-image comparison, Ring-2 classifier integration per alpha's #215/#218 work.

**Preserved operator constraints (from spec §1 locked decisions):**

- PR #1112 Phase 0 deterministic tint is the recognition foundation — **kept**, never regressed.
- Phase 1 ships exactly Palette Lineage + Poster Print; Families 3/4/5 are Phase 2/3 scope.
- Recognizability bar: ≥80% human ID rate on canonical 20-cover panel.
- Round structure deferred to Phase 2.
- Operator overrides: stimmung-coupled default + manual intensity slider.

**New constraint surfaced by spec §5:** all CBIP output passes Ring-2 WARD pre-render gate before reaching broadcast. Fail-closed (Phase 0 tint substitutes).

---

## Phase 1.1 — `posterize` effect-graph node

**Files:**
- Create: `agents/effect_graph/nodes/posterize.py`
- Create: `agents/reverie/shaders/posterize.wgsl`
- Modify: `agents/effect_graph/wgsl_compiler.py` (register node)
- Create: `tests/effect_graph/test_posterize_node.py`
- Create: `tests/studio_compositor/golden_images/cbip/posterize/*.png` (golden fixtures)

- [ ] **Step 1: Write failing test for node schema.**

```python
def test_posterize_node_registered():
    from agents.effect_graph.wgsl_compiler import NODE_REGISTRY
    assert "posterize" in NODE_REGISTRY

def test_posterize_node_params():
    from agents.effect_graph.nodes.posterize import PosterizeNode
    node = PosterizeNode(palette_size=8, dither_strength=0.6)
    assert node.name == "posterize"
    assert node.param_order == ("palette_size", "dither_strength")
    assert 4 <= node.palette_size <= 16
    assert 0.0 <= node.dither_strength <= 1.0
```

- [ ] **Step 2: Run, observe fail** — `PosterizeNode` doesn't exist yet.

- [ ] **Step 3: Write `posterize.py`** — Pydantic-validated node class per spec §2.1 (inputs, param ranges, WGSL dispatch).

- [ ] **Step 4: Write `posterize.wgsl`** — single-pass fragment shader:
  - 8×8 Bayer matrix constant.
  - Per-pixel: quantize to `palette_size` levels, add Bayer offset scaled by `dither_strength`.

- [ ] **Step 5: Register in compiler** — add to `NODE_REGISTRY` in `wgsl_compiler.py`.

- [ ] **Step 6: Generate golden images** — run the node against 5 canonical covers at `palette_size ∈ {4, 6, 8, 12}` and `dither_strength ∈ {0.0, 0.5, 1.0}`; commit outputs to `tests/studio_compositor/golden_images/cbip/posterize/`.

- [ ] **Step 7: Run tests, observe pass.**

- [ ] **Step 8: Commit.**

```bash
git add agents/effect_graph/nodes/posterize.py agents/reverie/shaders/posterize.wgsl \
        agents/effect_graph/wgsl_compiler.py tests/effect_graph/test_posterize_node.py \
        tests/studio_compositor/golden_images/cbip/posterize/
git commit -m "feat(effect-graph): posterize node (CBIP Phase 1.1)

Bayer-dithered palette collapse; params palette_size (4-16) and
dither_strength (0-1). Single-pass fragment shader. Recognizability
risk low at palette_size>=6 && dither_strength>=0.5 per spec §2.1.
Golden images pinned at 15 (palette,strength) combinations for
regression detection."
```

---

## Phase 1.2 — `kuwahara` effect-graph node

**Files:**
- Create: `agents/effect_graph/nodes/kuwahara.py`
- Create: `agents/reverie/shaders/kuwahara.wgsl`
- Modify: `agents/effect_graph/wgsl_compiler.py`
- Create: `tests/effect_graph/test_kuwahara_node.py`
- Create: `tests/studio_compositor/golden_images/cbip/kuwahara/*.png`

- [ ] **Step 1: Write failing test** — node registered, params validated, edge-IoU ≥0.65 invariant.

```python
def test_kuwahara_preserves_edges():
    from agents.effect_graph.nodes.kuwahara import KuwaharaNode
    from tests.studio_compositor.cbip.recognizability_harness import edge_iou

    src = load_fixture("liquid_swords.png")
    out = KuwaharaNode(radius=5).render(src)
    iou = edge_iou(src, out)
    assert iou >= 0.65, f"Kuwahara eroded edges too much: IoU={iou:.2f}"
```

- [ ] **Step 2: Run, observe fail.**

- [ ] **Step 3: Write `kuwahara.py`** + WGSL compute shader per spec §2.2:
  - radius ≤ 5 → single-pass fragment shader
  - radius > 5 → multi-pass compute (4 passes over quadrants, reduce)

- [ ] **Step 4: Register + golden images** (radius ∈ {3, 4, 5}).

- [ ] **Step 5: Tests pass.**

- [ ] **Step 6: Commit.**

---

## Phase 1.3 — `palette_extract` effect-graph node

**Files:**
- Create: `agents/effect_graph/nodes/palette_extract.py` (Python + Cairo, not WGSL)
- Modify: `agents/effect_graph/wgsl_compiler.py` (register as CPU-passthrough node)
- Create: `tests/effect_graph/test_palette_extract_node.py`

Unlike §1.1/§1.2, this is CPU-only: K-means on CIELAB pixels via scikit-learn + Cairo swatch overlay. No WGSL.

- [ ] **Step 1: Write failing test** — K-means returns top-K distinct colors; swatch overlay doesn't modify underlying region.

```python
def test_palette_extract_returns_k_colors():
    from agents.effect_graph.nodes.palette_extract import PaletteExtractNode
    src = load_fixture("liquid_swords.png")
    result = PaletteExtractNode(k=8, grid_layout="grid").render(src)
    # Extract the non-original region; expect 8 distinct LAB-space clusters
    swatches = extract_swatch_colors(result)
    assert len(swatches) == 8
    # Palette delta-E vs canonical K-means reference: ≤5
    assert palette_delta_e(swatches, canonical_liquid_swords_palette()) <= 5
```

- [ ] **Step 2: Run, observe fail.**

- [ ] **Step 3: Write node** — `scikit-learn` KMeans in LAB space (skimage color conv); frequency-weighted swatch size; Cairo blit in grid/row/column layout per `grid_layout` param.

- [ ] **Step 4: Register node + tests pass.**

- [ ] **Step 5: Commit.**

---

## Phase 1.4 — Recognizability test harness + canonical 20-cover fixture

**Files:**
- Create: `tests/studio_compositor/cbip/recognizability_harness.py`
- Create: `tests/studio_compositor/cbip/test_recognizability_invariants.py`
- Create: `tests/fixtures/cbip-canonical-covers/*.png` (20 covers)
- Create: `tests/fixtures/cbip-canonical-covers/MANIFEST.yaml` (cover → typography/abstract/figurative/monochrome/color-field class)
- Create: `docs/runbooks/cbip-human-id-panel.md` (operator-facing panel procedure)

Per spec §4 the harness exposes six metrics; INVARIANT metrics block PR merge, QUALITY metrics warn only.

- [ ] **Step 1: Curate the canonical 20-cover panel.** Spec §4 lists candidates: Madvillainy, The Low End Theory, Loveless, Selected Ambient Works, Liquid Swords, Marquee Moon, Unknown Pleasures, Black on Black. Add 12 more to fill the coverage matrix. MANIFEST.yaml tags each with `class: typography|abstract|figurative|monochrome|color-field` and `text_density: low|medium|high`.

- [ ] **Step 2: Write harness primitives.**

```python
# recognizability_harness.py
def ocr_title_accuracy(original: Image, enhanced: Image) -> float:
    """Tesseract on title region; Levenshtein-based char accuracy."""
def perceptual_hash_distance(a: Image, b: Image) -> int:
    """imagehash 64-bit Hamming."""
def palette_delta_e(a: Image, b: Image) -> float:
    """K-means K=8, mean CIE2000 per color."""
def edge_iou(a: Image, b: Image) -> float:
    """Sobel σ=1, Jaccard."""
def clip_similarity(a: Image, b: Image) -> float:
    """OpenAI CLIP cosine."""
```

- [ ] **Step 3: Write INVARIANT invariant test.**

```python
# test_recognizability_invariants.py
INVARIANT_METRICS = {
    "ocr_accuracy":       (ocr_title_accuracy,       0.90, ">="),
    "perceptual_hamming": (perceptual_hash_distance, 8,    "<="),
}
# human_id_rate is operator-run offline; tracked via vault annotation

def test_family_passes_invariants(family, cover_panel):
    for cover in cover_panel:
        original = load(cover)
        enhanced = family.render(original)
        for name, (fn, bound, op) in INVARIANT_METRICS.items():
            value = fn(original, enhanced)
            if op == ">=": assert value >= bound, ...
            elif op == "<=": assert value <= bound, ...
```

- [ ] **Step 4: Write human-ID panel runbook** — `docs/runbooks/cbip-human-id-panel.md` with the operator procedure: show 20 enhanced covers at 3 intensities, record per-cover recognition, compute rate. Target ≥80%. Re-run on threshold change.

- [ ] **Step 5: Tests pass (synthetic identity Family for baseline).**

- [ ] **Step 6: Commit.**

---

## Phase 1.5 — Family 1: Palette Lineage

**Files:**
- Create: `agents/studio_compositor/cbip/family_palette_lineage.py`
- Create: `tests/studio_compositor/cbip/test_palette_lineage_acceptance.py`

- [ ] **Step 1: Write acceptance test** — spec §3.1: original cover ≥99% pixel-identical, swatch grid present with K=8, attribution text rendered (if metadata available).

- [ ] **Step 2: Compose** — `palette_extract(k=8, layout="grid")` over the album cover; overlay attribution text (producer/artist) from album metadata when present.

- [ ] **Step 3: Acceptance test passes.**

- [ ] **Step 4: Recognizability harness runs** against Palette Lineage. All INVARIANT metrics pass trivially (original preserved).

- [ ] **Step 5: Commit.**

---

## Phase 1.6 — Family 2: Poster Print

**Files:**
- Create: `agents/studio_compositor/cbip/family_poster_print.py`
- Create: `tests/studio_compositor/cbip/test_poster_print_acceptance.py`

- [ ] **Step 1: Write acceptance test** — spec §3.2: edge IoU ≥0.65 (geometric covers), OCR ≥90%, palette delta-E ≤40.

- [ ] **Step 2: Compose** — `kuwahara(radius=5)` → `posterize(palette_size=8, dither_strength=0.6)`.

- [ ] **Step 3: Acceptance test passes.**

- [ ] **Step 4: Full recognizability harness** runs; any INVARIANT failure blocks ship — adjust radius/palette_size/dither_strength per cover class in `MANIFEST.yaml` until the panel passes.

- [ ] **Step 5: Commit.**

---

## Phase 1.7 — Ring-2 WARD pre-render gate

**Files:**
- Create: `agents/studio_compositor/cbip/ring2_gate.py`
- Create: `tests/studio_compositor/cbip/test_ring2_gate.py`
- Modify: `agents/studio_compositor/album_overlay.py` (wire gate between family render and compositor blit)

- [ ] **Step 1: Write failing test.**

```python
def test_ring2_gate_blocks_on_content_id_match():
    gate = Ring2PreRenderGate()
    rendered = render_poster_print(cover_with_copyright_match)
    result = gate.evaluate(rendered, album_metadata=copyrighted_metadata)
    assert result.verdict == "BLOCK"
    assert result.substitute_with == "phase_0_tint"

def test_ring2_gate_allows_clean_audio():
    gate = Ring2PreRenderGate()
    rendered = render_poster_print(cover_with_clean_audio_fingerprint)
    result = gate.evaluate(rendered, album_metadata=clean_metadata)
    assert result.verdict == "PASS"
```

- [ ] **Step 2: Implement `Ring2PreRenderGate`** per spec §5: three gates (Content-ID matchability, copyright freshness 90-day cache, demonetization risk score ≤0.4). Integrate alpha's Ring-2 classifier from #215/#218.

- [ ] **Step 3: Wire into `album_overlay.py`** — every family render passes through `gate.evaluate()`; on `BLOCK`, substitute Phase 0 deterministic-tint output.

- [ ] **Step 4: Tests pass.**

- [ ] **Step 5: Commit.**

---

## Phase 1.8 — Stimmung intensity router

**Files:**
- Create: `agents/studio_compositor/cbip/intensity_router.py`
- Create: `tests/studio_compositor/cbip/test_intensity_router.py`

- [ ] **Step 1: Write failing tests.**

```python
def test_intensity_maps_stimmung_to_families():
    r = IntensityRouter()
    # High energy
    assert r.select(stimmung_intensity=0.8) == ("family_poster_print", 1.0)
    # Mid energy
    assert r.select(stimmung_intensity=0.55) == ("family_palette_lineage", 0.5)
    # Low energy
    assert r.select(stimmung_intensity=0.2) == (None, 0.0)  # Phase 0 tint only

def test_low_coherence_forces_phase_0():
    r = IntensityRouter()
    assert r.select(stimmung_intensity=1.0, stimmung_coherence=0.2) == (None, 0.0)
```

- [ ] **Step 2: Implement per spec §6.1.**

- [ ] **Step 3: Tests pass.**

- [ ] **Step 4: Commit.**

---

## Phase 1.9 — Manual override slider (alpha-owned)

**Files:**
- Create: `hapax-logos/src/components/sidebar/CbipIntensityOverride.tsx`
- Create: `hapax-logos/src-tauri/src/commands/cbip.rs`
- Modify: `logos/api/routes/studio.py` (expose `cbip.intensity_override` endpoint)
- Create: `tests/studio_compositor/cbip/test_intensity_override.py`

Alpha owns this phase per spec §7 table. Delta yields — Logos UI context is alpha's surface.

- [ ] **Step 1: Alpha implements** the Logos right-sidebar slider + IPC plumbing + `~/.cache/hapax/cbip/intensity-override.json` atomic-write contract per spec §6.2.

- [ ] **Step 2: Delta writes the consumer test** that confirms `intensity_router` reads the override file and overrides §6.1 stimmung-coupled behavior when non-auto.

- [ ] **Step 3: Commit.**

---

## Phase 1.10 — E2E smoke + ship

**Files:**
- Create: `tests/integration/test_cbip_phase_1_e2e.py`
- Modify: `docs/superpowers/plans/2026-04-18-active-work-index.md` §8.2 status → ✅

- [ ] **Step 1: E2E smoke** — feed a canonical cover + fresh album metadata through: intensity_router → family selection → family render → ring2_gate → blit. Verify final broadcast output matches golden image at each intensity level.

- [ ] **Step 2: Recognizability panel re-run** (operator) — confirm ≥80% human ID rate on all 20 canonical covers at the chosen default intensity.

- [ ] **Step 3: Update active-work-index** — §8.2 status flips to ✅ SHIPPED with PR number.

- [ ] **Step 4: Commit + ship.**

---

## Execution order

Serial per-phase until §1.4 (harness) ships, then:
- §1.5 (Palette Lineage) and §1.6 (Poster Print) can run in parallel (different files, same harness).
- §1.7 (Ring-2 gate) serial after both families land.
- §1.8 (intensity router) can parallelize with §1.7.
- §1.9 (alpha-owned slider) any time after §1.8.
- §1.10 is final integration.

**Delta owns §1.1–§1.8, §1.10.** Alpha owns §1.9.

## Testing strategy summary

| Phase | Unit | Integration | Recognizability | Ring-2 |
|-------|------|-------------|-----------------|--------|
| 1.1–1.3 | Node schema, golden images | — | single-node metrics | — |
| 1.4 | Harness primitives | — | full 6-metric suite | — |
| 1.5 | Palette-Lineage compose | family acceptance | INVARIANT pass | — |
| 1.6 | Poster-Print compose | family acceptance | full harness | — |
| 1.7 | Gate unit | album_overlay integration | — | block/pass verdicts |
| 1.8 | Router unit | stimmung-state read | — | — |
| 1.10 | — | E2E smoke | full panel + human-ID | gate in live path |

## Rollout checklist

- [ ] §1.1 `posterize` + golden images committed
- [ ] §1.2 `kuwahara` + edge-IoU test passing
- [ ] §1.3 `palette_extract` + delta-E test passing
- [ ] §1.4 harness live + 20-cover panel fixture set + human-ID runbook published
- [ ] §1.5 Palette Lineage family shipped + acceptance test passing
- [ ] §1.6 Poster Print family shipped + full harness passing on canonical panel
- [ ] §1.7 Ring-2 gate wired into `album_overlay.py` + substitution verified
- [ ] §1.8 Intensity router wired to stimmung state + operator override read path
- [ ] §1.9 Alpha ships manual slider in Logos UI
- [ ] §1.10 E2E smoke green + operator ≥80% human-ID panel confirmed + active-work-index §8.2 flipped ✅

## Post-ship operations

1. **Monitor** Ring-2 gate block rate (target <5% on operator's curated album library).
2. **Iterate** intensity thresholds in §1.8 per operator feedback; the router reads `~/.cache/hapax/cbip/intensity-override.json` so operator can tune without redeploy.
3. **Governance** monthly human-ID panel re-run on threshold change or family CC retuning.
4. **Phase 2 trigger**: once Phase 1 lands, author round-structure spec + plan (chess/boxing render cadence) per research §5.

## References

- Spec: `docs/superpowers/specs/2026-04-21-cbip-phase-1-design.md`
- Concept: `docs/research/2026-04-20-cbip-1-name-cultural-lineage.md`
- Enhancement families research: `docs/research/2026-04-20-cbip-vinyl-enhancement-research.md`
- Phase 0 foundation: commit `a9573c93b` (PR #1112)
- Delta audit: `~/.cache/hapax/relay/audit/oq3-cbip-history-delta-2026-04-21.md`

---

**Next action:** Phase 1.1 (posterize node) ready to execute. Delta picks up after PR #1115 merges + Degraded-Stream MVP ships + GEM ward activation ships + B7 HOMAGE umbrella hardening lands (per `~/.cache/hapax/relay/delta-priority-pathway-2026-04-21.md` queue position 7).
