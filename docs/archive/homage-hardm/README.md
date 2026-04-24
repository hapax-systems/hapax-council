# HOMAGE HARDM archive

**Status:** retired 2026-04-23. Superseded by **GEAL** (Grounding Expression Anchoring Layer).

HARDM (Hapax Avatar Representational Dot-Matrix) was a 16×16 CP437 signal-coloured grid, shipped as HOMAGE follow-on #121, that tried to be Hapax's non-anthropomorphic avatar surface on the livestream. Its design rationale, implementation trajectory, and failure mode are preserved here as historical record.

## Why retired

Distilled from operator feedback 2026-04-23 and the rehab retrospective in `2026-04-20-hardm-aesthetic-rehab.md`:

> A grid of signal-coloured cells never cohered into an avatar because the legible-at-a-glance geometry a viewer needs to anchor on is precisely the bilateral/symmetric/figure geometry the anti-anthropomorphization mandate forbids — the grid was too abstract to function as an anchor and too structured to be innocuous.

Three compounded failures documented in the rehab retro: dead data layer (14 of 16 signals rendered null), structural degeneracy (row-bar binding reduced 256 cells to 16 horizontal bars), blink-as-last-resort (per-cell exponential-decay + recruitment ripples produced a 500 ms sine blink — retired in PR #1245).

## Where the work went

The anti-anthropomorphization mandate, the signal-semantic (not affect-semantic) colour rule, the salience-driven rendering, and the "Hapax has chosen not to have a face" governance posture all carry forward to GEAL. HARDM's invariants survive; only the dot-matrix primitive is retired.

See `docs/superpowers/specs/2026-04-23-geal-spec.md` for the replacement design.

## Contents

- `2026-04-18-hardm-dot-matrix-design.md` — original HARDM design spec
- `2026-04-20-hardm-aesthetic-rehab.md` — failure-mode retrospective
- `hardm-map.yaml` — per-cell signal bindings (historical)

The HARDM source code (`hardm_source.py`, `hardm-publish-signals.py`) lives at `agents/studio_compositor/_retired/` with the same retired-but-preserved status.
