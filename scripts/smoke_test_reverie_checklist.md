# Reverie Smoke Test — Visual Checklist

Run `uv run python scripts/smoke_test_reverie.py`, then inspect `output/reverie-smoke-test/`.

## Stage 0: Baseline
- `00-baseline-procedural.jpg` — Procedural field only (gradient/noise). No text. Should look like ambient generative art.

## Stage 1: Materialization
- `01-materialization-0.1.jpg` — Barely visible. Only brightest noise peaks show text.
- `01-materialization-0.3.jpg` — Partial crystallization. Text emerging from noise.
- `01-materialization-0.5.jpg` — Half visible. Noise gates still active.
- `01-materialization-0.7.jpg` — Mostly visible. Most of the text materialized.
- `01-materialization-1.0.jpg` — Fully materialized. Text clearly visible over procedural field.

## Stage 2: Materials
- `02-material-water.jpg` — Blue-tinted, dissolving edges, slight downward flow.
- `02-material-fire.jpg` — Warm boost, radial burn from center.
- `02-material-earth.jpg` — Slightly desaturated, dense, no UV distortion.
- `02-material-air.jpg` — Lightened, upward drift, dispersed.
- `02-material-void.jpg` — Darkened. Text subtracts luminance.

## Stage 3: Dwelling Trace
- `03-dwelling-before.jpg` — Full salience, text bright and clear.
- `03-dwelling-fadeout.jpg` — Salience just dropped. Luminance BOOSTED (trace effect) — should be slightly brighter than expected for low salience.
- `03-dwelling-trace.jpg` — 2 seconds later. Ghost of where text was should persist in feedback buffer.

## Stage 4: Multi-slot
- `04-multi-slot.jpg` — 4 text labels visible simultaneously, decreasing salience (SLOT-0 brightest, SLOT-3 dimmest). All screen-blended over procedural field.

## Stage 5: Cleanup
- `05-cleanup.jpg` — Everything faded. Should look like baseline again (possibly with faint trace from feedback).

## Pass Criteria
- All 13 screenshots generated
- Materialization shows progressive reveal (not instant appear)
- At least 3 of 5 materials look distinct from each other
- Dwelling trace shows brightness boost during fadeout
- Multi-slot shows 4 distinct content layers
