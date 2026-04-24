# HARDM (Hapax Avatar Representational Dot-Matrix) — Spec Stub

**Date:** 2026-04-18
**Source research:** `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` § "#121 HARDM"
**Status:** provisional — spec stub (first pass)
**Depends on:** HOMAGE Phase 6 (ward ↔ shader coupling custom[4] slot), task #136 (follow-mode signals)
**Task ID:** HOMAGE follow-on #121

---

## 1. Goal

A new 256×256 px compositor source rendering a 16×16 grid of 32 px cells, each cell bound to a single real-time system signal. Cells colour-code their signal state using the **active HOMAGE package's palette** (BitchX mIRC-16 by default), giving the viewer an avatar-like at-a-glance readout of Hapax's internal state. The bottom row doubles as a 16-band TTS waveform when the operator is speaking.

Design axioms this satisfies:
- BitchX-authentic: grey idle skeleton, bright identity colouring, mIRC-16 accent on activity, no gradient fills, no rounded corners.
- First-class HOMAGE participant: inherits `HomageTransitionalSource`, exits via `homage.rotation` / `homage.emergence` intents.
- Package-invariant geometry, package-sourced colour. Grid dimensions never change; palette swaps with `set_active_package()`.

---

## 2. Cell Layout Geometry

| Property | Value |
|---|---|
| Total surface | 256 × 256 px |
| Cell size | 32 × 32 px |
| Grid | 16 rows × 16 cols = 256 cells |
| Origin (top-left) | x = 1600, y = 20 (upper-right quadrant of 1920×1080 output) |
| Cell spacing / gutter | 0 px (CP437 raster contract — `raster_cell_required=True`) |
| Cell indexing | row-major: cell_0 = top-left, cell_15 = top-right, cell_240 = bottom-left, cell_255 = bottom-right |

No sub-pixel positioning. No anti-aliasing. No rounded corners. A 1 px muted-grey gridline between cells is permitted (CP437-thin rule, package `muted` role).

---

## 3. Signal Inventory (Primary — cells 0–15, top row)

| Cell | Signal key | Source | Mapping |
|---|---|---|---|
| 0 | `midi_active` | OXI One clock | boolean |
| 1 | `vad_speech` | Silero VAD | boolean |
| 2 | `room_occupancy` | YOLO aggregate | count → 3-level intensity |
| 3 | `ir_person_detected` | Pi NoIR (overhead/desk/room union) | boolean |
| 4 | `watch_hr` | Pixel Watch HR | bucketed (rest / moderate / elevated) |
| 5 | `bt_phone_connected` | BlueZ | boolean |
| 6 | `kde_connect_active` | KDE Connect | boolean |
| 7 | `ambient_sound` | AmbientAudioBackend | 3-level (silent / ambient / loud) |
| 8 | `screen_focus` | Hyprland desktop focus | boolean |
| 9 | `director_stance` | narrative-state.json | stance role (nominal/seeking/cautious/critical) |
| 10 | `consent_gate_state` | `shared/consent.py` | pass / cached / blocked |
| 11 | `stimmung_energy` | stimmung axis aggregate | 4-level |
| 12 | `shader_energy` | `uniforms.custom[4].shader_feedback_key` | 4-level |
| 13 | `reverie_pass_active` | pipeline pass index | pass number 0–7 |
| 14 | `degraded_stream_state` | `/dev/shm/hapax-compositor/degraded.flag` | boolean |
| 15 | `homage_package` | `get_active_package().name` | categorical (cycles accent colour per package) |

Cells 16–239 are reserved for scene-signal / aux-signal expansion from task #150 (image classification) and downstream perception work. They render in `muted` until bound.

Cells 240–255 are the TTS waveform band (see §7).

---

## 4. Cell-to-Signal Mapping Config

Externalised (per dossier recommendation 1):

**File:** `config/hardm-map.yaml`

```yaml
# Schema:
#   cells:
#     "<cell_index>":
#       signal: <signal_key>               # from signal registry
#       family: <family_tag>               # drives colour-role selection
#       mapper: <mapper_name>              # bool | level3 | level4 | bucketed | role | categorical
#       params: {...}                      # mapper-specific params

cells:
  "0":  { signal: midi_active,            family: timing,     mapper: bool }
  "1":  { signal: vad_speech,             family: operator,   mapper: bool }
  # ...
  "15": { signal: homage_package,         family: identity,   mapper: categorical }
```

Reload semantics: inotify-watched; hot-reload without restart. Schema validated via pydantic model `HardmCellMap`. Missing cell index → rendered as idle. Unknown signal key → rendered as `stress` with a warning log once per startup.

---

## 5. Colour Mapping (Package-Sourced)

All colours resolve via `HomagePackage.resolve_colour(role)` — **no hardcoded hex**. Role mapping follows BitchX grammar §5.1.

| Cell state | Role | BitchX field | Rationale |
|---|---|---|---|
| Idle (signal present, value nominal/false) | `muted` | `palette.muted` (~mIRC 14 grey) | grey-punctuation skeleton is the structural rule |
| Active | family-keyed accent | see below | bright-identity colouring |
| Stress / overflow / errored signal | accent-red | `palette.accent_red` (mIRC 4) | critical signal |
| Package identity cell (cell 15) | `bright` | `palette.bright` (mIRC 15) | nick-as-identity convention |

**Family → accent role** (active-state colouring, assigned by family tag in `hardm-map.yaml`):

| Family | Role | BitchX palette field |
|---|---|---|
| timing (MIDI, clock) | `accent_cyan` | `palette.accent_cyan` (mIRC 11) |
| operator (VAD, HR, watch, BT, KDE) | `accent_green` | `palette.accent_green` (mIRC 9) |
| perception (IR, room, ambient, scene) | `accent_yellow` | `palette.accent_yellow` (mIRC 8) |
| cognition (stance, stimmung, shader) | `accent_magenta` | `palette.accent_magenta` (mIRC 6) |
| governance (consent, degraded, homage) | `bright` | `palette.bright` |

Multi-level mappers (level3 / level4 / bucketed) interpolate **by alpha**, never by hue — hue stays locked to the family role so the avatar remains legible. Alpha = 0.40 / 0.70 / 1.00 for 3-level; 0.30 / 0.55 / 0.80 / 1.00 for 4-level.

Stress overrides family colour when a mapper flags error / overflow / staleness.

---

## 6. FSM Integration

Inherits `HomageTransitionalSource` directly. Source id: `hardm_dot_matrix`.

| FSM state | HARDM behaviour |
|---|---|
| `ABSENT` | Transparent surface (matrix hidden — choreographer has evicted it) |
| `ENTERING` | Cells populate column-by-column L→R over `entering_duration_s` (ticker-scroll-in default) |
| `HOLD` | Normal per-tick render from signal-state cache |
| `EXITING` | Cells depopulate R→L over `exiting_duration_s` (ticker-scroll-out default) |

Intents:
- `homage.rotation` — choreographer can schedule HARDM entry/exit as part of package rotation.
- `homage.emergence` — stress-state promotion (e.g., consent gate blocked) can trigger an out-of-cadence entry.
- `homage.netsplit-burst` — brief zero-cut redraw honoured as a "redraw-all-cells" pulse (non-state-changing per the transitional_source FSM).

Non-state-changing `mode-change` / `topic-change` transitions are accepted and logged but do not mutate the grid — the grid is always live; only its visibility is FSM-gated.

---

## 7. TTS Waveform Capture (Cells 240–255)

When operator speech is active (CPAL TTS output), the bottom row replaces its default signal binding with a 16-band envelope of the Kokoro phoneme stream:

- Source: CPAL runner publishes per-frame envelope buckets to `/dev/shm/hapax-daimonion/tts-envelope.json` (16 float values, 0.0–1.0, updated at TTS frame rate).
- Phoneme fidelity decision: **16-band condensation** (per dossier recommendation 2) — full Kokoro phone set (60+) collapses into 16 manner-of-articulation buckets (vowel-front / vowel-back / nasal / stop / fricative / liquid / glide / ... ). Exact bucket assignment is per Kokoro's phone inventory; deferred to implementation.
- Rendering: each cell fills bottom-up to height = `envelope_value × 32 px`; fill colour = `accent_magenta` (operator-voice family).
- When TTS is idle, row 240–255 reverts to its normal signal bindings (currently: reserved / muted).

---

## 8. File-Level Plan

- `agents/studio_compositor/hardm_dot_matrix.py` — new `HARDMDotMatrixSource(HomageTransitionalSource)`. Render loop reads signal cache, applies mapper, blits cells.
- `agents/studio_compositor/hardm_signal_cache.py` — thin reader aggregating the 16 primary signals from their canonical sources (perception-state.json, narrative-state.json, consent registry, etc). Caches with 1 s staleness cutoff; cell goes `stress` if signal stale.
- `agents/studio_compositor/hardm_mappers.py` — bool / level3 / level4 / bucketed / role / categorical mappers. Pure functions: `(signal_value, package) → (role_name, alpha)`.
- `config/hardm-map.yaml` — cell-to-signal config (§4).
- `shared/hardm_map.py` — pydantic model + loader.
- `agents/studio_compositor/cairo_sources/__init__.py` — register source class.
- `agents/studio_compositor/compositor.py` — add assignment: surface `hardm_dot_matrix` at (1600, 20) 256×256.
- `tests/studio_compositor/test_hardm_dot_matrix.py` — see §9.

---

## 9. Test Strategy

1. **Geometry invariant** — render surface is exactly 256×256; 16×16 cells verified by introspection.
2. **Palette binding** — render under BitchX package, assert cells resolve to mIRC-16 role RGBA tuples (no hardcoded hex appears in any cell path).
3. **Signal mapping** — parametrised: each primary signal fed a representative value; expected (role, alpha) asserted via mapper unit tests.
4. **FSM contract** — `apply_transition("ticker-scroll-in")` from `ABSENT` → `ENTERING`; tick advance → `HOLD`; `apply_transition("ticker-scroll-out")` → `EXITING` → `ABSENT`. Render in `ABSENT` produces transparent surface.
5. **Stale signal → stress** — mock 2 s stale signal, assert cell renders `accent_red` (not family accent).
6. **TTS waveform replacement** — when tts-envelope present, bottom row cells have height proportional to envelope; when absent, bottom row reverts to default binding.
7. **Config hot-reload** — modify `hardm-map.yaml`, assert new binding takes effect without restart.
8. **Consent-safe layout** — `get_active_package(consent_safe=True)` returns `None`; assert HARDM renders transparent (no broadcast).
9. **No-hardcoded-colour lint** — grep gate in test: no `rgb(` / `#` / `set_source_rgb` with literal tuple in `hardm_*.py`.

---

## 10. Open Operator Questions

1. **Cell-to-signal permanence** — is the row-0 signal layout (§3) committed, or is it an operator-editable mapping that may drift? Recommendation: commit row-0 as stable avatar semantics; allow cells 16–239 to drift per `hardm-map.yaml`.
2. **Colour role assignment details** — does the family→accent mapping in §5 match the operator's intuitive reading? E.g., should `operator` map to `accent_green` (mIRC op-indicator) or `accent_magenta` (own-message distinction)? Current proposal follows BitchX own-identity convention (magenta) for *speech* and op-indicator (green) for *presence*.
3. **Phoneme fidelity** — 16-band manner-of-articulation bucketing vs 8-band simpler vowel/consonant split vs full raw-amplitude 16 equal-width FFT bins. Dossier recommends 16-band; this spec adopts that but flags the trade.
4. **Cell 15 behaviour** — does the homage-package cell cycle through accents over time (decorative), or latch to a package-specific identity colour that changes only on `set_active_package()`? Current proposal: latch.
5. **Grid visibility under DEGRADED-STREAM** — when `degraded_stream_ward` is active, should HARDM hide entirely or continue rendering as an alignment signal? Recommendation: hide (single centred ward is the whole contract under DEGRADED).

---

## 11. Implementation Order

1. `hardm_mappers.py` + unit tests (pure functions, no Cairo).
2. `shared/hardm_map.py` + `config/hardm-map.yaml` stub (pydantic loader + default mapping).
3. `hardm_signal_cache.py` — signal readers only for cells 0–15, with staleness handling.
4. `HARDMDotMatrixSource` minimal render (muted-only, no signal binding) — verifies geometry and FSM integration.
5. Wire mappers → source render; full 16-cell readout in BitchX palette.
6. TTS envelope row (depends on CPAL writing `tts-envelope.json`).
7. Compositor assignment + hot-reload.
8. Tests §9.1 – §9.9.

---

## 12. Related

- **#150 image classification** — supplies scene-signal cells (cell range 16–31 reserved for per-camera scene labels from `camera_scene_labels.yaml`).
- **#124 Reverie exemption** — because Reverie is exempt from HOMAGE FSM choreography, its substrate state goes to a dedicated HARDM cell (cell 13, `reverie_pass_active`) rather than appearing as ward presence.
- **#122 DEGRADED-STREAM** — §10 Q5 above.
- **#136 follow-mode** — operator-presence-per-camera booleans are candidates for cells 16–31 alongside scene labels.
- **#129 facial obscuring** — HARDM does not render camera frames; no face-obscure obligation, but the cell corresponding to `operator_face_detected` must still honour the per-camera obscure invariant (no per-camera identifiability leaks through cell-level flags).

---

## 13. Dependencies

- **HOMAGE Phase 6 (ward ↔ shader coupling)** — required for cell 12 (`shader_energy`) to read from the BitchX `_BITCHX_COUPLING.custom_slot_index = 4` payload. Spec: HOMAGE framework design, §4.10.
- **`HomageTransitionalSource` base** (already landed in compositor phase 4).
- **Signal producers** — already live: VAD (Silero), MIDI (OXI), YOLO room occupancy, Pi NoIR, watch HR, BT/KDE Connect, ambient audio, Hyprland focus, narrative director, consent registry, stimmung, reverie pipeline, degraded flag, homage active-package.
- **Operator TTS envelope producer** — new contract required from CPAL / Kokoro pipeline: `/dev/shm/hapax-daimonion/tts-envelope.json`.
