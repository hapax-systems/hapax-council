# Phase 19 Projected Hero Design

## Purpose

The projected hero is a bounded compositor-side projection of the currently
selected hero camera snapshot into the virtual `_hero_small` tile. It gives the
operator and audience a stable orientation cue without making the hero camera a
second layout authority path.

## Contract

- The projection is derived from `compute_tile_layout()` and the virtual
  `_hero_small` rect. It does not create a GStreamer compositor pad.
- The projection reads the existing `/dev/shm/hapax-compositor/<role>.jpg`
  snapshot and fails closed to no drawing when the snapshot is missing.
- The projection uses constant alpha, a matte, and a border. It does not pulse,
  flash, blink, or change opacity based on audio/stimmung.
- The projection has a minimum dwell of 500 ms, matching the no-blink floor.
- The projection never grants layout success, face-obscuring success, runtime
  readback success, or privacy success. Those remain owned by their existing
  capture/layout/readback gates.

## Non-Goals

- No new camera source or layout mode.
- No raw-camera bypass around capture-side face obscuring.
- No preset, shader, or runtime authority claim.
- No interaction with content prep, segment artifacts, or selected-release gates.

## Acceptance

- A typed `ProjectedHeroProfile` records the projection posture in runtime state
  and refuses authority or blink regressions.
- `HeroSmallOverlay` uses the profile at draw time.
- Tests prove the profile is non-authoritative, constant-alpha, no-blink bounded,
  and that the overlay draws through `paint_with_alpha()` rather than an opaque
  raw blit.
