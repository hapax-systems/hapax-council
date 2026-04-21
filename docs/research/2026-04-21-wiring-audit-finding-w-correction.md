---
date: 2026-04-21
author: alpha
audience: delta, operator
register: scientific, neutral
status: correction note
supersedes: docs/research/2026-04-21-comprehensive-wiring-audit-alpha.md FINDING-W (architectural claim)
related:
  - agents/studio_compositor/fx_chain.py:99 (pip_draw_from_layout)
  - agents/studio_compositor/fx_chain.py:386-396 (post-FX cairooverlay wiring)
  - agents/studio_compositor/overlay.py:18 (base on_draw)
---

# Audit correction — FINDING-W is incorrect; wards already composite post-FX

The 2026-04-21 wiring audit's FINDING-W asserts that the 16 HOMAGE
wards "composite BEFORE the shader chain" and recommends moving them
to a post-FX cairooverlay. Direct reading of `agents/studio_compositor/
fx_chain.py` shows this is not how the pipeline is wired today — wards
already composite post-FX.

## What the pipeline actually does

`fx_chain.py::build_inline_fx_chain` constructs the pipeline as:

```
input-selector → queue → cairooverlay (BASE)
              → glupload → glcolorconvert → glvideomixer (camera + flash)
              → [shader slots × N]
              → glcolorconvert
              → gldownload
              → fx_convert
              → cairooverlay (POST-FX, "pip-overlay")    ← wards land here
              → output_tee
```

* **BASE cairooverlay** (line 274) draws ONLY two things:
  - Sierpinski triangle (intentionally pre-FX so it sits in the
    substrate and is modulated by shaders)
  - Pango overlay zones (markdown / ANSI from Obsidian)
  Both per `agents/studio_compositor/overlay.py::on_draw`.

* **POST-FX cairooverlay** (line 392) draws via
  `_pip_draw → pip_draw_from_layout(cr, layout_state, source_registry)`.

`pip_draw_from_layout` (`fx_chain.py:99`) iterates EVERY assignment in
`layout.assignments` — token_pole, album, stream_overlay, gem,
hardm_dot_matrix, hothouse panels, all of them — sorts by z_order, and
calls `blit_scaled` per assignment. Every ward declared in
`config/compositor-layouts/default.json` reaches this loop, and every
one of them composites AFTER the shader chain because the overlay
element is on the post-`gldownload` segment.

The audit's "wards visually absent" symptom (FINDING-R, 9/16 wards
absent) therefore cannot be explained by composition order. The actual
root causes are likely:

1. **Per-ward render output** — `source_registry.get_current_surface()`
   returns `None` when the ward's `CairoSourceRunner.tick()` produced
   a transparent frame (no input data, source HOLD-state at startup,
   subclass `render_content` short-circuited).
2. **Surface geometry off-canvas / zero-area** — `blit_scaled` receives
   a rect outside `(0, 0, canvas_w, canvas_h)` and silently composites
   nothing visible.
3. **Opacity clamp** — `apply_nondestructive_clamp` (line 140) drives
   the assignment alpha to ~0 when `non_destructive=True` and the
   source's blast-radius score is high.
4. **z_order collision** — two assignments at the same z_order overlap
   and the second covers the first.
5. **Specific input deprivation** — covered separately by FINDING-V
   (already partially addressed).

## Recommendation

Drop FINDING-W from the priority-fix list. The "Move 16 wards to
post-FX cairooverlay (4-6 hours)" line item in the audit's Top 5 is a
no-op — they're already there.

Reallocate that effort budget to:

* Live-verify each of the 9 missing wards individually via
  `curl :9482/metrics | grep 'studio_compositor_source_render_duration_ms_count' | grep <ward_id>`
  to see whether the runner is even producing frames.
* For wards whose runner IS producing, instrument `blit_scaled` (or
  `pip_draw_from_layout` itself) with per-ward DEBUG-level logging
  of the rect, opacity, and source-surface size — five minutes of
  log capture under live load identifies which ward is dropping the
  blit and why.
* Cross-check with the freshness analysis in
  `docs/research/2026-04-20-ward-full-audit-alpha.md` per-ward
  sections, which already document each ward's expected SHM input.

Alpha will not pursue these next-step diagnostics in this session;
recording the correction so the audit doesn't drive a misallocated
architectural refactor downstream.
