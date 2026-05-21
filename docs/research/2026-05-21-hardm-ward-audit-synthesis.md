---
title: "HARDM ward audit: current implementation and research synthesis"
date: 2026-05-21
author: epsilon
status: confirmed
cc_task: 202605181733-hardm-ward-redesi-p0-research-audit
authority_case: CASE-202605181733-HARDM-W
---

# HARDM ward audit: current implementation and research synthesis

## 1. Current implementation

**File**: `shared/hardm_signal_map.py`

256-cell signal map (16x16 grid, each cell 16x16 pixels). All 256 cells carry
unique signal bindings — no duplication. Eight signal families organized by row:

| Rows | Family | Cell count | Example signals |
|------|--------|------------|-----------------|
| 0–3 | Speech/voice | 64 | RMS bands, pitch bins, formants, VAD, MFCC, Mel |
| 4–5 | Stimmung | 32 | 11 dimensions + stance + components + history |
| 6–7 | Audio health | 32 | LUFS, crest, xrun, topology drift, broadcast safety |
| 8–9 | Perception | 32 | Presence, gaze, hands, face, body, heart rate, HRV |
| 10–11 | Density field | 32 | Per-source density + aggregate/temporal/trend |
| 12–13 | MIDI/music | 32 | 12 pitch classes, velocity, BPM, onset, 16 CCs |
| 14 | Eigenform | 16 | State vector: presence, flow, stress, curiosity... |
| 15 | System | 16 | GPU, CPU, memory, Docker, network, service health |

Update frequencies range from 0.5 Hz (history cells) to 30 Hz (speech RMS).
All cells normalized to [0.0, 1.0].

**Retired implementation**: `_retired/hardm_source.py` (969 lines) — the
previous 16-signal row-based design where all 16 columns duplicated the same
signal (16 independent cells, 240 zero-information). Used CP437 block
characters and Gray-Scott reaction-diffusion underlay.

## 2. Research artifacts located

| Document | Location | Key contribution |
|----------|----------|-----------------|
| HARDM redesign spec | `docs/research/2026-04-19-hardm-redesign.md` (427 lines) | 6 placement candidates, signal expansion, 6-phase plan |
| Homage ward umbrella | `docs/research/2026-04-20-homage-ward-umbrella-research.md` (400+ lines) | 15+ ward inventory, recognizability invariant |
| Communicative anchoring | `docs/research/hardm-communicative-anchoring.md` (400+ lines) | Salience bias, unskippable threshold, attentional anchor |

## 3. Ward layout baseline

- **Total cells**: 256 (16x16)
- **Active cells carrying non-zero signal**: 256 (all cells are independently mapped)
- **Zero-information cells**: 0 (retired design had 240; current has none)
- **Encoding scheme**: `CellSignal` dataclass with `row`, `col`, `family`,
  `source_key`, `label`, `min_val`, `max_val`, `update_hz`
- **Core lookups**: `SIGNAL_MAP` (list), `SIGNAL_BY_KEY` (dict), `SIGNAL_BY_INDEX` (dict)

## 4. Gaps between existing research and complete redesign spec

| Gap | Current state | What's missing |
|-----|---------------|----------------|
| Placement decision | 6 candidates researched, P3 (ticker band) recommended | No final operator decision; still rendering at P1 (corner badge) |
| Signal density validation | 256 cells defined | No empirical validation that all 256 carry perceptually distinguishable information |
| Reverie coupling | Option C recommended in research | Integration wiring not implemented — HARDM renders independently |
| Behavior modes | 5 modes specified (IDLE → IMPINGEMENT_SPIKE) | Mode rendering not implemented in current compositor |
| Anti-face runtime check | 10 invariants specified | No runtime enforcement — invariants are design constraints, not code checks |

## 5. Anti-face attack surface

Ten design-locked invariants (I1–I10) from the redesign spec:

1. **No stable clusters**: Cell values must prevent Euclidean clustering into face geometry
2. **Pearson < 0.6**: No high-correlation cell pairs suggesting eyes/mouth
3. **Symmetry prevention**: X-axis asymmetry enforced, no bilateral reflection
4. **Dynamic glow-through**: Reaction-diffusion maintains perpetual internal motion
5. **Cell count immutable**: Exactly 256 cells, no collapse to fewer active regions
6. **No face-like brightness gradient**: Prevent radial brightness resembling face lighting
7. **Temporal decay**: Cell activation decays to baseline, no fixed gaze effects
8. **Chromatic variance**: HOMAGE palette ensures no single dominant color
9. **Ripple geometry**: Recruitment ripples scatter, never coalesce at face zones
10. **Scrim opacity**: HARDM always partially transparent through Reverie

**Known attack vectors** (not yet hardened in code):
- Correlated signal sources (e.g., speech RMS bands 0–3 rising together) could
  create bilateral bright patches resembling eyes
- Eigenform state vector has semantically grouped cells (row 14) that could
  correlate under steady-state conditions
- Stimmung history cells (row 5) update at 0.5 Hz — low-frequency stability
  could form persistent bright regions
