# Livestream Render Architecture Shadow Plan

**Date:** 2026-05-10
**Status:** shadow architecture contract, no production cutover
**Task:** `livestream-compositor-render-architecture-shadow-plan`
**AuthorityCase:** `CASE-LIVESTREAM-COMPOSITOR-INCIDENT-20260509`
**Contract:** `config/livestream-render-architecture-shadow-plan.yaml`
**Schema:** `schemas/livestream-render-architecture-shadow-plan.schema.json`

## Decision

The target architecture is a clock-owned render core with GStreamer retained
for camera ingest, decode, caps negotiation, egress encoding, and transport
adapters. The render core owns frame cadence, source sampling, layout truth,
degradation metadata, and target frame manifests.

This is not a production cutover. The current stream remains on the existing
studio-compositor path while the new architecture proves itself in private
shadow mode.

## Why This Rejects The Local Optimum

The current GStreamer compositor can be made much better with isolated
pipelines, queues, shmsink sidecars, and explicit preflight predicates. Those
are useful and should remain. They are still a local optimum when treated as
the whole architecture.

The incident class is shared fate plus false truth: process liveness, camera
freshness, HLS movement, and OBS source state each looked useful in isolation
while the viewer-facing output could still be stale, black, cached, or
degraded containment. A monolithic composition graph keeps too much application
truth inside media-element behavior. The global target needs one application
clock and one frame ABI that says what the frame is, what sources were fresh,
what degraded, what it cost, and which adapters received it.

## Primary Documentation Consulted

- GStreamer docs: `tee` branches should use queues so one branch does not
  block another; `appsrc`/`appsink` are application boundaries for injecting
  and extracting buffers; these support keeping GStreamer at ingest/egress
  boundaries.
- PipeWire docs: PipeWire is a low-latency graph of nodes, ports, and links.
  That is a good transport/control graph shape, not the Hapax layout and
  public-truth model by itself.
- FFmpeg docs: complex filtergraphs, split, overlay, and multi-output mapping
  are strong for deterministic transforms and egress/encoding experiments, but
  they do not provide the live ward/source-health/render-truth contract.

References:

- `https://github.com/gstreamer/gstreamer/blob/main/subprojects/gst-docs/markdown/tutorials/basic/handy-elements.md`
- `https://github.com/gstreamer/gstreamer/blob/main/subprojects/gst-docs/markdown/tutorials/basic/multithreading-and-pad-availability.md`
- `https://docs.pipewire.org/page_objects_design.html`
- `https://docs.pipewire.org/page_overview.html`
- `https://ffmpeg.org/ffmpeg-all.html`

## Alternatives

| Option | Verdict | Reason |
|---|---|---|
| Monolithic GStreamer compositor | Rejected as global maximum | Good media graph, wrong authority boundary for Hapax render truth. |
| GStreamer multi-pipeline bridge | Keep as transition and adapter pattern | Improves branch isolation but does not define one final frame ABI. |
| Rust/wgpu renderd | Selected shadow target after ABI proof | Best fit for clock ownership and target views, but not allowed to cut over before shadow evidence. |
| PipeWire graph compositor | Reject as render truth owner | Useful graph transport; still needs application render semantics. |
| OBS scene/plugin owner | Reject as truth owner | OBS is a consumer and can cache stale decoded frames. |
| FFmpeg/libavfilter compositor | Reject as dynamic compositor | Strong filter/egress tool; weak fit for live source health, wards, and manifests. |

## Local Seams

The plan deliberately uses existing repo seams instead of inventing a second
stack:

- `agents/studio_compositor/ingest_mode.py`: `IngestMode.INGEST_ONLY` already
  names the topology where GStreamer ingests while another renderer composes.
- `agents/studio_compositor/output_router.py`: `OutputRouter` already maps
  render targets to v4l2, HLS, RTMP, window, NDI, and SHM sinks.
- `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs`:
  `get_target_output_view` already exposes wgpu target texture views.
- `agents/studio_compositor/shmsink_output_pipeline.py`:
  `ShmsinkOutputPipeline` already proves the nonblocking sidecar pattern for
  v4l2 isolation.
- `shared/live_surface_truth.py`: `assess_live_surface` already separates
  healthy, degraded containment, and failed viewer-facing states.

## Clock Contract

The render core owns a 30 fps clock. It samples the latest value from every
source without waiting. Missing or stale sources degrade within 2 seconds to a
last-good frame or offline slate. No camera, ward, shader, HLS writer,
v4l2/OBS path, RTMP path, archive writer, snapshot writer, or public-output
consumer may block the render clock.

Completed frames are immutable. Egress adapters receive completed frames and
metadata through bounded queues. Adapter failure changes only that adapter's
truth state.

## Frame And Source ABI

Every source contribution carries the versioned metadata pinned in
`config/livestream-render-architecture-shadow-plan.yaml`:

- `timestamp_ns`
- `sequence`
- `width`
- `height`
- `colorspace`
- `source_class`
- `health`
- `fallback_policy`
- `render_cost_us`

This is intentionally small. It is enough to prove freshness, ordering,
dimensions, pixel interpretation, source type, degradation policy, and budget.
Future fields can be additive after the first shadow proof.

## Shadow Mode

Shadow mode starts private-only and disabled by default. The first proof uses:

- RGB cameras: `brio-operator`, `c920-desk`, `c920-overhead`
- Wards: `egress_footer`, `programme_banner`,
  `grounding_provenance_ticker`
- Shader/source input: `reverie`
- Private output:
  `/dev/shm/hapax-compositor/render-shadow/frame.rgba`

IR and additional RGB cameras are added only after the private output proves
that source and adapter failures do not stall the clock.

## Chaos And Soak

Before any cutover packet, shadow mode must inject failures for camera freeze,
ward timeout, shader frame loss, HLS writer stall, v4l2 writer stall, OBS
cached frame, and slow public consumer. Each failure has one expected result:
the source or adapter degrades, and the render frame sequence continues.

The first soak is two private hours with no public output mutation, no false
restored claim, no unbounded queue growth, and fresh final-frame proof.

## Migration

1. Merge this contract and tests with no runtime mutation.
2. Run a private renderd clock with no live sources.
3. Add the three-camera ingest subset.
4. Add selected wards and Reverie source input.
5. Add isolated private SHM, HLS, v4l2, and OBS-preview adapters.
6. Produce an S5 cutover packet with source, render, egress, consumer, layout,
   chaos, soak, and rollback evidence.
7. Only after operator acceptance, evaluate a public cutover candidate while
   the current stream remains live on the old path.

Rollback is the disable flag `HAPAX_RENDER_CORE_SHADOW=0`; it stops the
private render-shadow path without moving OBS or public output.

## Inspection Contract

This plan stays bound to audiovisual SDLC truth. Required checkpoints:

- `CP-SOURCE-TRUTH`
- `CP-RENDER-TRUTH`
- `CP-EGRESS-TRUTH`
- `CP-CONSUMER-PUBLIC-TRUTH`
- `CP-LAYOUT-VALIDITY`
- `CP-INSPECTION-EVIDENCE`
- `CP-REGRESSION-GATES`
- `CP-INCIDENT-EXIT-HOLD`

Minimum evidence commands:

```bash
scripts/compositor-inspect before incident-render-architecture
scripts/compositor-inspect after incident-render-architecture-shadow
scripts/hapax-live-surface-preflight --json
```
