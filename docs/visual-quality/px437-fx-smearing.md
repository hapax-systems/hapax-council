# Px437 edge smearing in the live FX chain

Closes the documentation half of cc-task
`visual-quality-px437-live-snapshot-fixture`. The companion artifact
is the deterministic Px437 probe at `scripts/probe-px437-snapshot.py`,
which captures clean glyph-grid edges *upstream* of the FX chain. The
HLS-extracted frame from
`closed/visual-quality-tier-b-live-verification.md` showed
visibly smeared edges *downstream*; this doc names the stages that
introduce the smear.

## Pipeline path the cairooverlay text traverses

The text-bearing surfaces (`AlbumOverlay`, `OverlayZones`,
`StreamOverlay`, etc.) draw onto a `cairooverlay` element wired into
the FX chain in `agents/studio_compositor/fx_chain.py:438-577`. After
the cairooverlay, every text glyph passes through:

1. `glupload` — host RAM → GPU texture.
2. `glcolorconvert` — pixel format conversion to whatever the
   downstream `glvideomixer` and shader effects expect.
3. `glvideomixer` — alpha-compositing the base, flash, and PiP planes.
4. The `SlotPipeline` shader chain (Reverie colorgrade + any active
   live effects).
5. `glcolorconvert` again to the output format.
6. `gldownload` — GPU texture → host RAM.
7. `videoconvert` to the output codec's expected pixel format.

Then a tee splits to:

- The output / V4L2 `/dev/video42` writer (consumed by OBS).
- The CPU JPEG snapshot path
  (`agents/studio_compositor/snapshots.py:184-205`):
  `videoconvert` → `videoscale` (1280x720) → `jpegenc` (quality=85)
  → `appsink`.
- The HLS muxer (the source of the visibly-smeared frame in the
  Tier-B verification).

## Smearing contributions, by stage

| Stage | Smearing mechanism | Settable mitigation |
| --- | --- | --- |
| `glupload` + `glcolorconvert` | Sub-pixel resampling when the GPU sampler defaults to GL_LINEAR. | Force GL_NEAREST on the cairo plane's sampler — not currently exposed via the FX chain element-set. |
| `glvideomixer` | Bilinear filtering during alpha-composite and any plane scaling. | `glvideomixer` does not surface a sample-method property in GStreamer 1.24; the cleanest mitigation is to keep every text-bearing plane at output resolution so no scaling occurs (already true for the base + flash planes). PiP plane is the residual hazard. |
| `SlotPipeline` shaders | Reverie colorgrade, any live `differential blur + tint` shader, and the `glshader` effect chain documented at `fx_chain.py:133-135`. The colorgrade pass is permanent. | The colorgrade WGSL pass is the dominant smear contributor for any frame where `colorgrade.brightness` ≠ 1.0 or `colorgrade.saturation` ≠ 1.0 — the saturation matrix mixes neighboring pixel chroma. A future clean-text mode would gate text-bearing planes around the colorgrade pass. |
| `videoscale` (snapshot path, `snapshots.py:189`) | Default scaling method is Lanczos / 4-tap, which trades sharpness for ringing-free downscaling. At Px437's integer pixel grid this manifests as soft edges with overshoot halos. | Set `videoscale.method=0` (nearest) **only** for the snapshot tee — production HLS muxer needs the Lanczos for non-text content. Best surfaced as a "snapshot-clean-text" toggle. |
| `jpegenc` quality=85 (`snapshots.py:204`) | DCT quantizes high-frequency edge components — exactly what Px437 glyph edges are. At quality=85 this is subtle but visible at integer-grid scrutiny. | Increase to quality=95 in the snapshot path, or switch the snapshot tee to PNG for text-bearing diagnostic captures. |
| HLS path | The HLS muxer consumes the same output as the V4L2 writer; smearing is dominated by the `glvideomixer`/colorgrade chain plus whatever encoder bitrate the muxer was configured at. The Tier-B HLS frame was a direct extract from a segment, not re-encoded — so the smearing is not from JPEG. | See colorgrade row above. |

## Where pre/post-FX evidence should live

- **Pre-FX (clean grid proof):**
  `~/.cache/hapax/verification/visual-quality-px437-live-snapshot-fixture/probe-<utc>.png`,
  produced by `scripts/probe-px437-snapshot.py`. Bypasses the entire
  GStreamer chain — directly invokes
  `agents.studio_compositor.text_render.render_text_to_surface`.
- **Post-FX (live HLS frame):** the existing artifact at
  `~/.cache/hapax/verification/visual-quality-tier-b-live-verification/hls-segment00330-frame-20260428T2346Z.jpg`.
  Captured during the Tier-B verification run; do not re-capture
  routinely — the artifact is sufficient evidence of the smear.

The diff between the two frames is the FX chain's contribution. The
table above attributes the contribution stage-by-stage so future
remediation work can target one stage at a time without conflating
sources.

## Relationship to other visual-quality work

- Tier-A (PR #1719) shipped Px437 16-multiples + Reverie 960×540 and
  closed the resolution-grid concerns.
- Tier-B livestream presentation (closed
  `visual-quality-tier-b-livestream-presentation.md`) shipped Cairo
  font hinting + RTMP preset cleanup. The `_PIXEL_FONT_MARKERS` /
  `ANTIALIAS_NONE` wiring in `agents/studio_compositor/text_render.py`
  is the upstream mitigation; this doc is about the downstream
  re-introduction.
- Tier-B live verification (closed
  `visual-quality-tier-b-live-verification.md`) captured both the
  text-free live snapshot and the text-bearing-but-smeared HLS frame.
  This task closes that loop.

A "snapshot-clean-text" mode that toggles `videoscale.method=0` and
JPEG quality=95 (or PNG) in the snapshot tee, plus a colorgrade-bypass
flag for diagnostic frames, would let the live FX chain produce a
clean Px437 frame on demand. That work is **explicitly out of scope**
for the current cc-task — the task contract was "capture the
artifact OR document the FX stage that prevents capture", and the
documented attribution above is the load-bearing deliverable.
