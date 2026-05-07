# Cairo Ward HOMAGE Palette Compliance Audit

**Date:** 2026-05-07
**Auditor:** delta session
**Scope:** All 41 distinct CairoSource subclasses registered in `agents/studio_compositor/cairo_sources/__init__.py`

## Method

Traced every `register()` call in `_register_builtins()` to its backing class. For each class, checked whether the render path resolves palette colors through the HOMAGE package system — either via `get_active_package()` directly from `agents.studio_compositor.homage`, or indirectly via `active_package()` / `paint_bitchx_header()` / `select_bitchx_font_pango()` / emissive-base helpers from `agents.studio_compositor.homage.rendering` and `agents.studio_compositor.homage.emissive_base`.

A ward is **compliant** if every `set_source_rgb` / `set_source_rgba` call in its render path derives colors from the active `HomagePackage`. A ward is **non-compliant** if it uses hardcoded float RGBA tuples or its own color constants without consulting the package.

Note: 43 `register()` calls exist, but `DURFCairoSource` is an alias for `CodingActivityReveal`, and `ChatKeywordLegendCairoSource` is a legacy alias still registered for layout-JSON backward compat. 41 distinct classes.

## Compliant Wards (24)

These wards call `get_active_package()` or `active_package()` (from `homage.rendering`) and derive their palette from the returned `HomagePackage`.

| # | Class | File | Mechanism |
|---|-------|------|-----------|
| 1 | `TokenPoleCairoSource` | `token_pole.py:339` | Direct `get_active_package()` + `select_bitchx_font_pango` + `emissive_base` |
| 2 | `AlbumOverlayCairoSource` | `album_overlay.py:305` | `rendering.active_package()` + `paint_bitchx_header` |
| 3 | `CBIPSignalDensityCairoSource` | `cbip_signal_density.py:98` | `rendering.active_package()` |
| 4 | `ActivityHeaderCairoSource` | `legibility_sources.py:401` | Direct `get_active_package()` + `emissive_base` |
| 5 | `StanceIndicatorCairoSource` | `legibility_sources.py:536` | Direct `get_active_package()` + `emissive_base` |
| 6 | `ChatKeywordLegendCairoSource` | `legibility_sources.py:646` | Direct `get_active_package()` + `emissive_base` |
| 7 | `GroundingProvenanceTickerCairoSource` | `legibility_sources.py:741` | Direct `get_active_package()` + `emissive_base` |
| 8 | `ChatAmbientWard` | `chat_ambient_ward.py:3` | Direct `get_active_package()` |
| 9 | `StreamOverlayCairoSource` | `stream_overlay.py:104` | `rendering.active_package()` + `emissive_base` |
| 10 | `ImpingementCascadeCairoSource` | `hothouse_sources.py:295` | `rendering` helpers + `emissive_base` |
| 11 | `RecruitmentCandidatePanelCairoSource` | `hothouse_sources.py:507` | `rendering` helpers + `emissive_base` |
| 12 | `ThinkingIndicatorCairoSource` | `hothouse_sources.py:648` | `rendering` helpers + `emissive_base` |
| 13 | `PressureGaugeCairoSource` | `hothouse_sources.py:747` | `rendering` helpers + `emissive_base` |
| 14 | `ActivityVarietyLogCairoSource` | `hothouse_sources.py:871` | `rendering` helpers + `emissive_base` |
| 15 | `WhosHereCairoSource` | `hothouse_sources.py:1002` | `rendering` helpers + `emissive_base` |
| 16 | `VinylPlatterCairoSource` | `vinyl_platter.py:177` | Direct `get_active_package()` |
| 17 | `GemCairoSource` | `gem_source.py:227` | `rendering.active_package()` |
| 18 | `ChronicleTickerCairoSource` | `chronicle_ticker.py:227` | Direct `get_active_package()` |
| 19 | `ProgrammeStateCairoSource` | `programme_state_ward.py:161` | Direct `get_active_package()` |
| 20 | `ProgrammeHistoryCairoSource` | `programme_history_ward.py:188` | Direct `get_active_package()` + `get_package()` |
| 21 | `PrecedentTickerCairoSource` | `precedent_ticker_ward.py:237` | Direct `get_active_package()` |
| 22 | `InteractiveLoreQueryWard` | `interactive_lore_query_ward.py` | Direct `get_active_package()` |
| 23 | `ResearchInstrumentDashboardCairoSource` | `research_instrument_dashboard_ward.py:272` | Direct `get_active_package()` |
| 24 | `EgressFooterCairoSource` | `egress_footer_source.py:79` | Direct `get_active_package()` |

## Compliant via `rendering.active_package()` (7 additional)

These wards use the `active_package()` convenience wrapper from `homage.rendering` (which internally calls `get_active_package()`) rather than importing `get_active_package` directly.

| # | Class | File | Mechanism |
|---|-------|------|-----------|
| 25 | `CodingActivityReveal` | `coding_activity_reveal.py` | `rendering.active_package()` (3 call sites) |
| 26 | `PolyendInstrumentReveal` | `polyend_instrument_reveal.py` | `rendering.active_package()` |
| 27 | `ResearchMarkerOverlay` | `research_marker_overlay.py` | `rendering.active_package()` + `emissive_base` |
| 28 | `SegmentContentWard` | `segment_content_ward.py` | `rendering.active_package()` |
| 29 | `ConstructivistResearchPosterWard` | `constructivist_research_poster_ward.py:54` | Direct `get_active_package()` |
| 30 | `TufteDensityWard` | `tufte_density_ward.py:53` | Direct `get_active_package()` |
| 31 | `ASCIISchematicWard` | `ascii_schematic_ward.py:83` | Direct `get_active_package()` |

**Total compliant: 31 / 41** (76%)

## Non-Compliant Wards (10)

These wards use hardcoded RGBA float tuples in their render paths without consulting the HOMAGE package system.

| # | Class | File | Hardcoded colors | HOMAGE heritage |
|---|-------|------|-----------------|-----------------|
| 1 | `SierpinskiCairoSource` | `sierpinski_renderer.py:160` | Synthwave palette (7+ tuples) | None — predates HOMAGE |
| 2 | `CaptionsCairoSource` | `captions_source.py:144` | Delegates to `text_render` | `HomageTransitionalSource` (FSM only) |
| 3 | `ProgrammeBannerWard` | `programme_banner_ward.py:109` | 4 RGBA tuples | None |
| 4 | `PackedCamerasCairoSource` | `packed_cameras_source.py:149` | 1 cyan border | None |
| 5 | `CBIPDualIrDisplacementCairoSource` | `cbip_dual_ir_displacement.py:250` | 8+ RGBA tuples | None |
| 6 | `MobileActivityHeaderCairoSource` | `mobile_cairo_sources.py:152` | 2 RGBA tuples | None |
| 7 | `MobileStanceIndicatorCairoSource` | `mobile_cairo_sources.py:172` | Hardcoded | None |
| 8 | `MobileImpingementCascadeCairoSource` | `mobile_cairo_sources.py:195` | Hardcoded | None |
| 9 | `MobileTokenPoleCairoSource` | `mobile_cairo_sources.py:218` | Hardcoded | None |
| 10 | `MobileCaptionsCairoSource` | `mobile_cairo_sources.py:245` | Hardcoded | None |

### Detail: `SierpinskiCairoSource`

Uses a hardcoded `COLORS` synthwave palette (neon pink, cyan, purple) and `set_source_rgba(0.0, 0.9, 1.0, 0.9)` cyan glow. No `get_active_package` or `active_package` import. The synthwave aesthetic is intentionally distinct from HOMAGE — this is the oldest visual ward and predates the HOMAGE system. **Migration risk: high** (the Sierpinski triangle is the visual signature of the stream).

### Detail: `CaptionsCairoSource`

Extends `HomageTransitionalSource` (gets FSM transition handling) but has zero `get_active_package` / `active_package` / `set_source_rgb` calls in its render body. Typography was migrated to Px437 IBM (Phase A4) but palette was not. **Migration risk: low** (retired from default layout at GEM cutover, kept for rollback layouts only).

### Detail: `ProgrammeBannerWard`

Hardcoded colors: `(0.078, 0.078, 0.078, 0.78)` dark bg, `(0.831, 0.706, 0.255, 0.95)` warm gold title, `(0.95, 0.95, 0.95, 1.0)` white body, `(0.78, 0.78, 0.78, 1.0)` grey elapsed. No HOMAGE import at all. **Migration risk: low**.

### Detail: `PackedCamerasCairoSource`

Hardcoded `set_source_rgba(0.0, 0.9, 1.0, 0.15)` cyan border glow. No HOMAGE import. **Migration risk: low** (single accent color).

### Detail: `CBIPDualIrDisplacementCairoSource`

Extensive hardcoded colors: dark teal bg `(0.015, 0.018, 0.02)`, scan lines `(0.1, 0.55, 0.62)`, red/cyan displacement indicators `(0.85, 0.12, 0.08)` / `(0.04, 0.78, 0.72)`, gold label `(0.95, 0.72, 0.18)`, etc. 8+ distinct hardcoded RGBA tuples. **Migration risk: medium** (the IR displacement aesthetic is intentionally sensor-diagnostic; may warrant exemption like Sierpinski).

### Detail: Mobile wards (5)

All 5 mobile wards extend `_MobileSourceBase(CairoSource)` — not `HomageTransitionalSource`. Hardcoded RGBA tuples throughout. Their desktop counterparts are all HOMAGE-compliant. **Migration risk: low** (mobile surfaces are small phone-context overlays).

## Also Checked: `ObjectivesOverlay` and `ScribbleStripSource`

- **`ObjectivesOverlay`** (`objectives_overlay.py:46`) — Hardcoded Gruvbox-adjacent colors (`(0.98, 0.92, 0.78)` fg1, `(0.66, 0.60, 0.52)` gray1). No HOMAGE import. However, this ward is **not** registered in `cairo_sources/__init__.py::_register_builtins()`, so it falls outside the 41-ward audit scope. Noted for completeness.

- **`ScribbleStripSource`** (`scribble_strip_source.py:81`) — Hardcoded `(0.05, 0.05, 0.07)` bg, `(0.85, 0.85, 0.90)` text. Mentions "homage" only in a comment about `feedback_no_blinking_homage_wards`. Similarly **not** in `_register_builtins()` — out of scope.

- **`GealCairoSource`** (`geal_source.py:174`) — Not registered in `_register_builtins()`, out of scope. Uses dynamic amplitude-based colors from data, not a fixed palette.

## Summary

| Category | Count | Percentage |
|----------|-------|------------|
| Compliant (direct `get_active_package()`) | 24 | 59% |
| Compliant (via `rendering.active_package()`) | 7 | 17% |
| **Total compliant** | **31** | **76%** |
| Non-compliant (hardcoded) | 10 | 24% |
| **Total** | **41** | 100% |

## Categorized Non-Compliance

### Likely intentional exemptions (2)
- **SierpinskiCairoSource** — Visual signature ward, predates HOMAGE, synthwave aesthetic is part of the stream identity.
- **CBIPDualIrDisplacementCairoSource** — Sensor-diagnostic ward, IR displacement colors encode physical meaning (red = primary cam, cyan = secondary cam).

### Straightforward migration candidates (3)
- **ProgrammeBannerWard** — 4 color constants, simple lower-third text.
- **PackedCamerasCairoSource** — 1 accent color on borders.
- **CaptionsCairoSource** — Retired from default layout, low urgency.

### Mobile surface cohort (5)
All 5 mobile wards (`MobileActivityHeaderCairoSource`, `MobileStanceIndicatorCairoSource`, `MobileImpingementCascadeCairoSource`, `MobileTokenPoleCairoSource`, `MobileCaptionsCairoSource`) extend `_MobileSourceBase(CairoSource)` rather than `HomageTransitionalSource`. Their desktop counterparts (the non-mobile versions) are all HOMAGE-compliant. The mobile surfaces are phone-context overlays with deliberately simplified palettes for small screens. Migrating them could be done by changing `_MobileSourceBase` to extend `HomageTransitionalSource` and adding `active_package()` calls, but the small-screen context may justify a distinct visual treatment.

## Recommendations

1. **Confirm exemptions** for `SierpinskiCairoSource` and `CBIPDualIrDisplacementCairoSource`. If exempt, document the exemption in each ward's module docstring.
2. **Migrate `ProgrammeBannerWard`** and **`PackedCamerasCairoSource`** — smallest surface area, lowest risk.
3. **Decide mobile-ward policy** — are phone surfaces expected to follow HOMAGE? If yes, batch-migrate the 5 mobile wards by lifting `_MobileSourceBase` to `HomageTransitionalSource`.
4. **Leave `CaptionsCairoSource`** for last — it's retired from the default layout and only exists for rollback.
