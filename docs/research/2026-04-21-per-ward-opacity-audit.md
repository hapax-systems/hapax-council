# Per-Ward Opacity Audit — Live Prometheus Data Gathering

**Author:** delta
**Date:** 2026-04-21 (T+~1h after FINDING-X Phase 1 shipped as PR #1153)
**Scope:** tactical data-gathering per FINDING-W reframe §4 recommendation
**Related:** `docs/research/2026-04-21-finding-w-reframe-post-z-plane.md`
**Source:** live `curl http://127.0.0.1:9482/metrics` on the running compositor process

## 1. Method

Pulled the three ward-level Prometheus surfaces added by the FINDING-R
deepening in `agents/studio_compositor/fx_chain.py`:

- `studio_compositor_ward_blit_total{ward}` — successful blits since
  process start.
- `studio_compositor_ward_blit_skipped_total{ward,reason}` — blits
  skipped, labeled by reason (`surface_not_found`, `source_not_registered`,
  `source_surface_none`, `alpha_clamped_to_zero`).
- `studio_compositor_ward_source_surface_pixels{ward}` — most recent
  source-surface `width × height` (px²), gauge.

Ran once against the live compositor (PID 4076-ish, uptime ~8 min post
rebuild-services restart after PR #1153 landed).

## 2. Observation — zero skips

`studio_compositor_ward_blit_skipped_total` has **no labeled samples**.
Counter is registered but not emitted. That means, in the window since
the last compositor start:

- No ward's surface was missing from the registry
  (`source_not_registered = 0`).
- No ward's source returned `None` from `get_current_surface()`
  (`source_surface_none = 0`).
- No ward was clamped to alpha=0 by `apply_nondestructive_clamp`
  (`alpha_clamped_to_zero = 0`).
- No `surface_not_found` on layout lookup.

**Implication:** FINDING-V's `source_surface_none` symptom — the primary
hypothesis in the FINDING-W reframe for orphan-consumer wards — does
**not currently reproduce on the live graph**. Every ward in the layout
has a producer that's returning a real surface, and every ward is
blitting at 100% cadence (all 16 wards show identical blit counts:
10789 each over the uptime window, confirming uniform post-FX cadence).

The FINDING-V spec + plan (landed in PR #1144) remains correct for the
case when those producers are absent — but as of this snapshot, no
absence is observed. Investigations that assumed `source_surface_none`
was the dominant symptom should be re-scoped.

## 3. Surface-area distribution (live)

```
ward                             surface_px²   notes
─────────────────────────────────────────────────────
stance_indicator                      4,000    smallest; ~80×50
thinking_indicator                    7,480    2nd smallest; ~86×87
whos_here                            10,580
pressure_gauge                       15,600
grounding_provenance_ticker          19,200
chat_ambient                         30,720
activity_header                      44,800
recruitment_candidate_panel          48,000
activity_variety_log                 56,000
hardm_dot_matrix                     65,536    256×256
stream_overlay                       80,000
token_pole                           90,000
impingement_cascade                 172,800
album                               208,000
reverie                             230,400    480×480
gem                                 441,600    largest; activation pending
```

Every surface is non-trivial (>= 4000 px²), ruling out the "1×1
degenerate surface" hypothesis that motivated the per-ward pixel gauge
in the first place.

## 4. FINDING-W residual attribution

Taking §2 (zero skips) together with the surface-area distribution in
§3, the current "visually absent" symptom on some wards narrows to:

1. **Small surface area + shader overwrite.** Wards under ~10 k px² are
   the most likely to lose to a bright halftone/chromatic shader pass,
   because their cairo fill is a small fraction of the frame and any
   shader pattern has enough room to dominate. In order of risk:
   - `stance_indicator` (4,000 px²)
   - `thinking_indicator` (7,480 px²)
   - `whos_here` (10,580 px²)
   - `pressure_gauge` (15,600 px²)

2. **Non-destructive clamp + z-plane attenuation stacking.** The
   non-destructive alpha clamp (fx_chain.py:182) already caps
   informational wards so they don't obscure camera content. Stacked on
   top of the post-#1145 z-plane attenuation (default plane ≈ 0.96),
   informational wards could be composited at effective α ~ 0.6–0.8
   against a bright shader output — visually dominated.

3. **Blend mode on the surface schema.** Any non-`OVER` blend mode on a
   legibility surface would change how it composites against the shader
   output. This data gather did not inspect the layout JSON; that's a
   separate follow-up.

## 5. Suggested adjustments (operator / alpha pick)

Ordered by expected visible impact, smallest-ward-first:

- **`stance_indicator`** — 4 k px² is the smallest ward on the stream.
  Raise `z_plane` to `chrome` (or whatever plane yields max opacity) to
  survive the shader. Also audit whether it carries `non_destructive =
  true` in its layout assignment — if yes, consider unsetting for
  chrome/status-of-self wards (they're meant to be legible by design).
- **`thinking_indicator`** — 7.5 k px². Same advice as stance_indicator.
  Thinking-indicator is a pulsing dot per the director-loop spec; a
  pulsing dot visually destroyed by halftone dots is an identity
  collision, not just an opacity issue. Consider also whether its shape
  should be larger or have a higher-contrast outline.
- **`whos_here`** — 10.6 k px². Smallest of the info cluster.
- **`pressure_gauge`** — 15.6 k px². Bar-chart style, contrast-heavy so
  may already survive; lower priority.

Non-structural changes (no code):

- Edit `config/compositor-layouts/default.json` per-assignment
  `opacity`, `z_order`, or `non_destructive` flags.
- Edit ward render code to set `z_plane` / `z_index_float` higher
  (via `shared/ward_properties.py`).

## 6. What did NOT need to be investigated

- Producer presence — every source is registered and producing a real
  surface (§2).
- Blit cadence — uniform 10789 blits across all 16 wards in the sample
  window (§2).
- Gross layout bugs — no `surface_not_found` skips.

The remaining variable is purely the opacity / contrast / blend-mode
tuning against the shader output, which is a UX concern operator should
drive. The data in §3 gives the ranked candidate list to start from.

## 7. Re-query cadence

If operator wants to track whether skip-rate rises under different
scene states or director behavior, `curl
http://127.0.0.1:9482/metrics | grep studio_compositor_ward_blit_` is
the one-liner. The Grafana dashboard from PR #1160 covers the
director-side grounding observability; if per-ward opacity becomes a
recurring concern, the 4 `studio_compositor_ward_*` metrics merit their
own dashboard row on `studio-cameras.json` or a new `wards-visibility`
dashboard.

## 8. Close-out

No PR shipped from this gather. Spec-level recommendations in §5 are
tactical UX calls that operator / alpha should make with the live
stream in front of them. The data in §3 is the handoff.
