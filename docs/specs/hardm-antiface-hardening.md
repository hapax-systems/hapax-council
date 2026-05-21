---
title: "HARDM anti-face hardening requirements and test cases"
date: 2026-05-21
author: epsilon
status: draft
cc_task: 202605181733-hardm-ward-redesi-p1-antiface-spec
authority_case: CASE-202605181733-HARDM-W
audit: docs/research/2026-05-21-hardm-ward-audit-synthesis.md
---

# HARDM Anti-Face Hardening Requirements and Test Cases

## 1. Invariants and mitigations

10 design-locked invariants from the redesign spec. Each has a testable
acceptance criterion below.

### I1: No stable clusters

**Requirement**: Cell values must prevent Euclidean clustering into face-like
geometry (2 bright regions at eye-distance apart).

**Mitigation**: Signal map distributes semantically unrelated signals across
adjacent cells — speech row 0 neighbors speech row 1, not perception or
eigenform.

**Test**: Given a synthetic HARDM frame with all 256 cells at their maximum
values, run k-means (k=2..5) on the bright-cell coordinates. Assert no cluster
pair has centroid separation within [0.2, 0.4] of frame height (face
proportions).

### I2: Pearson correlation < 0.6

**Requirement**: No cell pair should have Pearson r > 0.6 over a sustained
window.

**Mitigation**: Each cell maps to an independent signal source. Correlated
sources (e.g., speech RMS bands) are in the same row, not at face-feature
positions.

**Test**: Record 60s of cell values from a representative session. Compute
pairwise Pearson r for all 256×256 pairs. Assert max(r) < 0.6 for any pair
where the two cells are at bilateral-symmetric positions (mirrored across
the vertical axis).

### I3: Symmetry prevention

**Requirement**: X-axis asymmetry enforced — no bilateral reflection patterns.

**Mitigation**: Signal families are laid out by row, not by symmetric column
groups. Left and right halves of each row carry different signals.

**Test**: For each row, compute the cross-correlation between left 8 cells and
right 8 cells (reversed). Assert correlation < 0.5.

### I4: Dynamic glow-through

**Requirement**: Reaction-diffusion maintains perpetual internal motion.

**Mitigation**: Gray-Scott underlay runs independently of cell signal values.

**Test**: Render 10 consecutive HARDM frames with identical cell values. Assert
pixel-level difference between frames > 0 (underlay is animated even when
signals are static).

### I5: Cell count immutable

**Requirement**: Exactly 256 cells, no collapse to fewer active regions.

**Test**: Assert `len(SIGNAL_MAP) == 256` and
`len(set(s.cell_index for s in SIGNAL_MAP)) == 256`.

### I6: No face-like brightness gradient

**Requirement**: Prevent radial brightness patterns resembling face lighting.

**Test**: Render a HARDM frame with all cells at maximum. Compute radial
brightness profile from center. Assert the profile is not monotonically
decreasing (face-like top-lighting would produce bright center, dark edges).

### I7: Temporal decay

**Requirement**: Individual cell activation must decay to baseline.

**Test**: Set one cell to maximum, advance 30 frames with zero input. Assert
the cell value has decayed below 0.1× max.

### I8: Chromatic variance

**Requirement**: No single dominant color.

**Test**: Render a frame and compute the histogram of hue values. Assert
entropy > 2.0 bits (diverse hues, not monochromatic).

### I9: Ripple geometry

**Requirement**: Recruitment-event ripples scatter across all regions.

**Test**: Trigger a recruitment event and capture 5 frames. Assert the ripple
touches cells in at least 4 of the 8 signal families (not confined to one
region).

### I10: Scrim opacity

**Requirement**: HARDM always partially transparent through Reverie.

**Test**: Render HARDM over a known Reverie background. Assert the composite
image differs from HARDM-only rendering (Reverie shows through).

## 2. Known attack vectors and test cases

### AV1: Correlated speech RMS bands

**Vector**: Speech bands 0-3 rise together during speech, creating bilateral
bright patches at rows 0-3.

**Test**: Inject a speech-active signal (all 64 speech cells high). Assert
the resulting pattern does not produce bilateral symmetry (I3 test passes).

### AV2: Eigenform steady-state grouping

**Vector**: Eigenform cells (row 14) correlate under stable operator state,
forming a persistent bright bar.

**Test**: Set all 16 eigenform cells to 0.9 for 60 frames. Assert temporal
decay (I7) reduces them below 0.5 within 30 frames.

### AV3: Low-frequency stimmung history

**Vector**: Stimmung history cells (row 5, 0.5 Hz update) maintain persistent
values, creating stable bright regions.

**Test**: Record 120s of stimmung history cell values. Assert the standard
deviation over time > 0.1 for each cell (values do change, not frozen).

## 3. Implementation priority

| Test | Invariant | Can be automated? | Priority |
|------|-----------|-------------------|----------|
| I5 cell count | Immutable | Yes (unit test) | P0 — already exists in signal map validation |
| I2 correlation | < 0.6 | Yes (statistical, needs recorded data) | P1 |
| I3 symmetry | Bilateral | Yes (unit test on signal map) | P1 |
| I1 clustering | No face clusters | Yes (synthetic frame + k-means) | P2 |
| I4-I10 | Rendering | Requires runtime frame capture | P2 — deferred to integration testing |
| AV1-3 | Attack vectors | Needs representative session data | P2 |
