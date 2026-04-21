# FINDING-W Reframe — Post Ward-Z-Plane Stratification

**Author:** delta
**Date:** 2026-04-21
**Status:** research note — reframes the 2026-04-20 audit's FINDING-W after reading the code that's actually on main today
**References:**

- Original audit: `docs/research/2026-04-20-wiring-audit-findings.md` §FINDING-W (lines 759-817)
- Post-audit shipping:
  - PR #1145 — ward z-plane stratification Phase 1 (schema + blit_with_depth)
  - PR #1147 — ward stimmung modulator Phase 2 (~5 Hz dim → ward depth)
- Pipeline under inspection: `agents/studio_compositor/fx_chain.py:386-539`,
  `agents/studio_compositor/fx_chain.py:131-212` (pip_draw_from_layout)
- BASE cairooverlay draw callback: `agents/studio_compositor/overlay.py:18-40`

## 1. Audit's premise is stale

The 2026-04-20 audit's FINDING-W says: "16 wards on BASE cairooverlay run BEFORE
12-slot glfeedback shader chain → shader OVERWRITES wards. Only YouTube PiP is
post-FX." The audit's fix-path 1 proposes "Move chrome/info wards to the
post-FX cairooverlay."

Reading `fx_chain.py` as it stands on main today, this premise does not match
the code. There are indeed two cairooverlays:

- **BASE overlay** (`fx_chain.py:418`, draw callback
  `agents/studio_compositor/overlay.py::on_draw`): runs BEFORE the glfeedback
  chain. Its draw callback renders only the Sierpinski triangle and the Pango
  `_overlay_zone_manager` content. **Not 16 wards** — two specific surfaces
  that are intentionally pre-FX so the shader aesthetic operates on them.
- **POST-FX overlay** (`fx_chain.py:536`, draw callback
  `_pip_draw`→`pip_draw_from_layout`): runs AFTER gldownload, BEFORE
  output_tee. Walks `layout.assignments` by z_order and blits any rect-kind
  surface. **All wards routed through the layout system land here**, not just
  YouTube PiP.

The audit's symptom (9/16 wards visually absent) is real. The audit's
mechanism-claim (wards are on BASE being shader-overwritten) is not the
current code.

## 2. Candidate root causes (empirical)

With the real pipeline in mind, the remaining explanations for visual absence
are:

### 2.1 FINDING-V overlap — `source_surface_none`

`pip_draw_from_layout` emits `_emit_blit_skip(..., "source_surface_none")` when
`source_registry.get_current_surface(assignment.source)` returns None. FINDING-V
identified 5 wards whose publishers are missing (closed today by PR #1144's
spec+plan); their source surfaces are therefore empty, and `pip_draw_from_layout`
skips them. Once FINDING-V Phase 1 implements the publishers, the affected
wards start painting.

### 2.2 Non-destructive clamp (`apply_nondestructive_clamp`)

`fx_chain.py:182` applies a non-destructive alpha clamp per assignment. Wards
flagged `non_destructive=True` have their opacity capped so they cannot
obscure the camera content they sit over. Stacking this cap with the z-plane
attenuation in `blit_with_depth` may yield a practical alpha <= 0.3 on "deep"
or "non-destructive" wards — plausibly the visual-absence threshold against a
bright shader output. This was not an issue at the audit time because the
z-plane attenuation did not yet exist; it is now stacked on top of the
non-destructive clamp.

### 2.3 Blend mode assigned in the surface schema

`blit_with_depth(cr, src, geom, opacity, blend_mode=…)` honors the
`surface_schema.blend_mode`. Any surface with a non-`OVER` blend mode
(`MULTIPLY`, `SCREEN`, etc.) composites differently against the bright
shader output. Some legibility surfaces may have been given aesthetic blend
modes that become unreadable against a dense multi-color shader output.

### 2.4 Z-plane default applies ~4% attenuation

`z_plane=on-scrim`, `z_index_float=0.5` yields a ~0.96 multiplier on opacity
(per the PR #1145 description). Ward defaults therefore lose ~4% of their
opacity relative to pre-z-plane behavior. This is a visually imperceptible
change on its own, but stacks with 2.2 and 2.3 to explain the delta between
pre- and post-PR-1145 visual outcomes on low-contrast wards.

## 3. What this means for FINDING-W's fix path 1

Fix path 1 ("move chrome wards to post-FX cairooverlay") is a **no-op under
the current code** — they're already there. Pursuing that path would only
make sense as "make sure EVERY ward routes through the layout system rather
than the BASE `on_draw` path," but `on_draw` renders Sierpinski + Pango zones
only, and those are deliberately pre-FX for aesthetic reasons.

## 4. Recommended direction

Do not ship an architectural move. Treat FINDING-W as dissolved into:

- **FINDING-V** for the `source_surface_none` skip cluster (already research +
  spec + plan'd, implementation queued).
- **Per-ward opacity audit**: measure `effective_alpha` values emitted from
  `pip_draw_from_layout` against specific ward IDs, per the
  `WARD_BLIT_SKIPPED_TOTAL{reason="alpha_clamped_to_zero"}` and the new
  `WARD_SOURCE_SURFACE_PIXELS` gauge from the FINDING-R deepening already on
  main. Identify wards whose effective opacity pairs poorly with a bright
  shader output, then either raise their `z_plane`/`z_index_float`, unset
  their `non_destructive` flag, or change the default blend mode on the
  surface schema.
- **Blend-mode audit**: enumerate `surface_schema.blend_mode` values across
  `config/compositor-layouts/default.json` and any overrides. Any
  non-`OVER` blend mode on a legibility surface is a candidate for fix.

These are cheap data-gathering tasks, not architectural churn. Operator
reviews the data and picks specific wards to adjust.

## 5. Scope boundary for this research note

This note does not produce a spec or plan. Its deliverable is the reframe:
the audit's architectural-fix recommendation is not the right fix today. The
follow-up data-gathering recommendations (§4) are small delta-shape items
that can be picked up opportunistically; they do not require a separate
research cycle.

## 6. Explicit close-out for FINDING-W

Recommended action for the audit document:

- Mark FINDING-W **RECLASSIFIED** — root cause "wards on BASE cairooverlay"
  does not match current code. Visible-absence symptom persists but is
  attributable to FINDING-V + opacity-stacking, both of which have
  independent remediation paths.
- No architectural migration is in flight; any follow-up belongs to
  per-ward opacity/blend-mode tuning (a tactical UX task, not an
  architectural one).
