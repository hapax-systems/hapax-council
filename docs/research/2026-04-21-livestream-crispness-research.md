# Crisp Intentional Livestream Surface — Research

**Author:** delta
**Date:** 2026-04-21
**Audience:** operator, alpha (for implementation); delta (follow-up specs)
**Trigger:** operator directive 2026-04-21 after ward-z-plane + stimmung modulator activation (#1147, #1163). "For the z-plane work to actually work we're going to have to fix the effect and nebulous scrim clarity/softness/muddiness. We need things to be crisp."
**Scope:** end-to-end clarity chain from compositor render → YouTube viewer. What erodes crispness, what preserves it, what to change.
**Out of scope:** new shader authoring, preset redesign, ward layout changes.

## 1. The clarity chain as it stands

Pixel flow from generation to viewer, with format conversions called out:

| # | stage | format / resolution | location in code |
|---|---|---|---|
| 1 | USB cameras | NV12 1280×720 MJPEG → decoded → NV12 | `camera_pipeline.py:176` |
| 2 | Interpipesink → interpipesrc hot-swap | NV12 | `fx_chain.py` input-selector |
| 3 | BASE cairooverlay (Sierpinski + Pango zones) | BGRA over NV12 | `overlay.py::on_draw` |
| 4 | glupload + glcolorconvert (GPU residency) | GL RGBA | `fx_chain.py:423` |
| 5 | glvideomixer + 12× glfeedback shader slots | GL RGBA | `fx_chain.py:436, 470`; `agents/effect_graph/*` |
| 6 | gldownload → videoconvert → pip-overlay (POST-FX cairooverlay — ward chrome) | NV12 (?) / BGRA blits | `fx_chain.py:472-540` |
| 7 | output tee → v4l2loopback `/dev/video42` + RTMP branch | NV12 → YUY2 (v4l2 default) | `fx_chain.py` output tee |
| 8 | RTMP branch: `x264enc`/NVENC → H.264 high-profile | H.264 6000 kbps | `rtmp_output.py:~`; NVENC preset p5 ULL |
| 9 | MediaMTX relay → RTMP to YouTube ingest | — | `127.0.0.1:1935` |
| 10 | OBS reads `/dev/video42` via V4L2 source + audio from PA | YUYV422 / NV12 | OBS |
| 11 | OBS re-encodes to H.264 → YouTube RTMP | H.264 at OBS-chosen bitrate | OBS settings |
| 12 | YouTube server-side transcode to VP9/AV1 at multiple resolutions | VP9/AV1 per viewer quality | YT |
| 13 | Viewer playback (browser/mobile/TV) | decoded | viewer |

**Canvas is 1280×720**, set in `config.py:27-43` (A+ Stage 2 cut from 1920×1080 for SM headroom). `HAPAX_COMPOSITOR_OUTPUT_WIDTH`/`_HEIGHT` environment overrides. Not bound by the camera-720p commitment (which is about CAMERA input, not canvas).

**Cairo blit filter** is `FILTER_BILINEAR` (`fx_chain.py`). Applies to every ward + post-FX blit on scale.

**Double encode path**: compositor NVENC → v4l2loopback → OBS NVENC → YouTube. Every encoder is lossy; concatenating two loses high-frequency detail (text edges, halftone patterns, tight color transitions).

## 2. Where softness enters

Softness is introduced at each stage where information is discarded. Mapped to the chain above:

| stage | softness source | effect |
|---|---|---|
| 1 | USB cameras at 720p | native ceiling: no more spatial detail than 720p carries. |
| 4 | NV12 → RGBA via videoconvert | no loss (NV12 → RGBA is expansion). |
| 5 | 12-slot glfeedback shader chain | by design — halftone, chromatic banding, glitch streaks are **intentional output**. Floor of softness-like texture. **Aesthetic**, not technical. |
| 6 | gldownload + videoconvert back to NV12 for output | **4:2:0 chroma subsampling** halves horizontal+vertical color resolution. Hurts red/green shader transitions (visible as chromatic fringe smearing — see operator screenshot). |
| 6 | FILTER_BILINEAR in ward blits | soft scale. Fine for non-integer scales; blurs slightly even at integer scales. |
| 7 | v4l2loopback NV12 / YUY2 handoff | format-dependent; 4:2:0 again if NV12. |
| 8 | NVENC compositor encode at 6000 kbps (preset p5) | quantises DCT blocks. Halftone + fine text edges lose contrast. Preset p5 is balanced; p7 sharper, p4 faster. |
| 10 | OBS re-decodes from v4l2 | full decode, no extra loss here. |
| 11 | OBS re-encodes | **second quantisation pass**. Compound loss — tiny shader features that survived compositor encode get smeared in OBS encode. This is the dominant technical softness source. |
| 12 | YouTube transcode | third encode. YouTube recommends 1080p60 at 9 Mbps, 720p60 at 4.5 Mbps. At 6 Mbps input 720p, YT re-encodes to VP9 and will quantise the shader's halftone texture further. |

## 3. Softness taxonomy

Two distinct problems, often conflated:

- **Technical softness.** Pixel-level blur from scaling, chroma subsampling, encoder quantisation. Fixable with resolution / bitrate / format / codec choices.
- **Aesthetic density.** The shader's halftone + chromatic-streak output is visually busy. Even when technically sharp, the eye reads it as "muddy" when it competes with ward chrome. Not a crispness problem per se; it's a visual-hierarchy problem.

Operator's screenshot shows a largely technically-sharp image (text edges crisp) with high aesthetic density (shader streaks dominate the centre, chromatic fringes on the red/green bands). The "muddy" feeling is predominantly §3.b, not §3.a — but §3.a compounds at the YouTube side because viewers' decoders further compress the already-busy shader output.

## 4. Crispness levers — per stage, ranked by impact×cost

**Tier A — high impact, low cost, no architectural change**

1. **Raise compositor NVENC preset p5 → p7** (`rtmp_output.py`). p7 is NVENC's slowest/sharpest preset; on a 3090 the 720p@30 load is negligible. Expected effect: noticeably sharper text, less ringing on shader edges. No latency impact at 720p.
2. **Raise compositor bitrate 6000 → 9000 kbps** matching YouTube's 720p60 ingest recommendation. More bits retain shader halftone detail that currently gets quantised. Low cost.
3. **Keyframe interval 2s** (verify — GOP 60 at 30fps). Matches YouTube live-spec; helps reset quality after motion.
4. **Cairo blit filter BILINEAR → BEST for chrome wards** at integer scales (`cairo.FILTER_BEST`). Small CPU cost; crisp edges on text-heavy wards. Phase 1 would flag per-ward whether BEST or BILINEAR; default stays BILINEAR.

**Tier B — medium impact, medium cost, non-architectural**

5. **Canvas 1280×720 → 1920×1080**. The A+ Stage 2 cut was for SM headroom; if SM isn't currently the bottleneck, reverting doubles pixel area. Benefits: (a) viewers on 1080p quality get native-rendered frames instead of a 720p→1080p upscale; (b) every ward's natural-size render doesn't need upscale; (c) Pango font rendering at 1080p has 2.25× more glyph-pixel budget — text is dramatically crisper. Cost: +100% encoder load on compositor NVENC (still trivial on 3090), +100% encoder load on OBS NVENC (also trivial), +YT needs 9-12 Mbps for clean 1080p. Risk: regression of the original SM issue A+ Stage 2 was fixing; validate before committing.
6. **Single-encode path: compositor → RTMP → MediaMTX → OBS (via MediaMTX re-pull) OR compositor → SRT direct to OBS**. Eliminates one of the two encoder passes. SRT is OBS's recommended low-latency ingest; MediaMTX can rebroadcast the compositor's RTMP to OBS as SRT. Cost: reconfiguration. Benefit: ~30-50% less quantisation loss on shader fine detail. Open technical question: does OBS v4l2loopback ingest use the NV12 raw path, bypassing a decode stage? If so, the "double encode" mental model is wrong. Needs verification.
7. **OBS NVENC settings audit**. Verify OBS uses high-profile, CRF or CBR at 9-12 Mbps, p7/p6 preset, B-frames off for live. Operator setting, not repo-deployable.

**Tier C — high impact, high cost, architectural**

8. **Pango font hinting + ANTIALIAS_GRAY vs ANTIALIAS_SUBPIXEL** audit across ward Cairo sources. Subpixel anti-aliasing is sharper at the cost of a specific subpixel pattern — can actually hurt after encoder quantisation. Per-ward choice; default should stay GRAY.
9. **4:4:4 chroma path for shader output**. NV12's 4:2:0 chroma subsampling is the single biggest source of the chromatic fringe smearing visible on red/green shader bands. A 4:4:4 intermediate (AYUV or RGB) would preserve those transitions; but NVENC H.264 doesn't support 4:4:4 in its consumer builds, and YouTube re-encodes to VP9 which carries 4:2:0 anyway. So the chromatic fringe will re-enter at stage 12 regardless. Net: not worth the engineering cost.
10. **Shader output band-limiting**. Apply a subtle low-pass filter on the shader's high-frequency output before encode. Reduces halftone noise that the encoder quantises anyway, freeing bits for text edges. Requires shader-side change.

**Tier D — not about crispness, but adjacent**

11. **Aesthetic density**: shader intensity clamp (already shipped in PR #1138 as `shader_intensity_bounds.json`). Lowering `spatial_coverage_max_pct` for certain shaders (pixel_sort et al.) so they don't fill the frame with busy texture. This is what operator's directive is actually closest to when they say "crisp intentional" — the image feels intentional when shader density is bounded to NOT compete with ward chrome. Candidate for a Phase 2 intensity-cap bump: lower `max_strength` on halftone + chromatic-banding families by another 10-20%.
12. **Ward contrast**: per the 2026-04-21 per-ward opacity audit (PR #1161), chrome wards on small surfaces (stance_indicator 4000 px², thinking_indicator 7480 px²) lose to bright shader output. A `z_plane=chrome` elevation on those raises them above the shader visually — same "crisp intentional" feel without touching the encoder path.

## 5. Recommended sequence

Phase-gated so operator can stop at any point:

1. **Immediate (Tier A)**: bump NVENC preset p5 → p7 + bitrate 6 → 9 Mbps in `rtmp_output.py`. One-file PR. Test live — should produce visible crispness improvement on text + shader edges with zero architectural disruption.
2. **Next (Tier A continuation)**: Cairo `FILTER_BEST` for chrome wards (identify via layout JSON). Small PR.
3. **Next (Tier D-11)**: tighten shader intensity cap — another 10-20% `max_strength` reduction on halftone + chromatic families. Operator's aesthetic call.
4. **Next (Tier D-12)**: raise `z_plane=chrome` on the 4 smallest wards (from PR #1161 data).
5. **Experiment (Tier B-5)**: reinstate 1920×1080 canvas behind a feature flag (env var already present — `HAPAX_COMPOSITOR_OUTPUT_WIDTH=1920 HAPAX_COMPOSITOR_OUTPUT_HEIGHT=1080`). Run for a rehearsal; measure SM load; if acceptable, commit.
6. **Research (Tier B-6)**: investigate whether OBS → RTMP/SRT single-encode path is viable; write separate research note if so.

## 6. Measurement — how to know crispness improved

Operator cannot subjectively A/B against the same livestream (memory colours the judgement). Measurement options:

- **Recorded frame grabs**: save OBS output and YT-downloaded playback snapshots pre/post. Diff zoomed-in crops of text + shader edges. Imagemagick `ssim` + `psnr` comparisons.
- **Bitrate occupancy**: Prometheus scrape of `rtmp_output` reports output bitrate actual. Sustained pinning at the 9 Mbps ceiling = encoder has enough to represent the surface without quantising noise. Dipping well below 6 Mbps average = encoder is quantising too aggressively.
- **Viewer-side sample**: download the YouTube VOD post-stream, sample frames, run same zoom+diff. This is the authoritative "did the viewer get crispness" measurement.

## 7. Open questions (not answered in this note)

- Does OBS's V4L2 ingest use raw NV12 pass-through or does it decode+re-encode? If pass-through, the "double encode" mental model is only partly right.
- What is the current OBS NVENC preset/bitrate? (operator setting, not in repo.)
- Is there measurable SM headroom today for a 1080p canvas revert?
- Does the MediaMTX RTMP branch produce the same stream quality as the v4l2loopback branch, or is there meaningful divergence?
- What is the effective YouTube viewer-side resolution most viewers land on (720p vs 1080p)? Determines whether canvas revert actually helps most viewers.

## 8. Closing summary

The technical chain has 2-3 encode passes and 4:2:0 chroma subsampling. Those are structural; eliminating them is a big project. But the **Tier A** adjustments (NVENC p5→p7, 6→9 Mbps, Cairo FILTER_BEST for chrome) are single-file, low-risk, and directly address "text+shader edges losing detail through encode." Combined with the **aesthetic density** adjustments (tighter intensity cap, chrome z_plane elevation), the operator's "crisp intentional" target is reachable without architectural churn — the z-plane stratification work (#1147/#1163) then has a sharp substrate to layer against.

Recommend shipping Tier A as a single PR with the three changes. Further tiers gated on operator's appetite post-stream-test.
