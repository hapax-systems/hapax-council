**Target path:** `docs/methodology/avsdlc-visual-evidence-contract.md`

---

## Visual Evidence Contract

### Purpose

This contract defines what constitutes sufficient visual evidence for quality
review. It applies to all work items classified as having visual impact under
Gate 1 of the authority case, with particular emphasis on interview-specific
visual composition.

### Measurable Visual Quality Dimensions

#### 1. Design Language Compliance

The normative authority is `docs/logos-design-language.md`. Compliance is
non-negotiable for governed surfaces (section 11.1).

| Dimension | Standard | Target | Measurement method | Failure predicate |
|---|---|---|---|---|
| Color token usage | Hapax-native (governed) | Zero hardcoded hex values in components (except section 8.2 exemptions) | ESLint custom rule + CI | Any non-exempt hardcoded hex in a governed surface component |
| Palette coherence | Hapax-native (governed) | All semantic colors resolve through current mode palette | Runtime ThemeProvider warning (dev mode) | Raw hex rendered outside palette system |
| Mode switch completeness | Hapax-native (governed) | All governed surfaces switch palette simultaneously on mode change | Manual verification: switch mode, inspect all surfaces | Any surface remains on previous palette after mode switch |
| Proportional system | Hapax-native (governed) | All spacing derives from 2px base unit | Visual inspection of computed styles | Spacing values that are not integer multiples of 2px |
| Typography | Hapax-native (governed) | JetBrains Mono exclusively on all governed surfaces | Visual inspection + font-family audit | Any non-JetBrains-Mono font on a governed surface |

#### 2. Text Readability

| Dimension | Standard | Target | Measurement method | Failure predicate |
|---|---|---|---|---|
| Minimum stream text size | Hapax-native (governed, section 12.1) | >= 12px for all stream-visible text | ESLint custom rule | Sub-12px text on stream-visible surface outside `<RedactWhenLive>` |
| Contrast ratio (body text) | WCAG 2.1 AA | >= 4.5:1 against background | Contrast checker tool on screenshot | Ratio < 4.5:1 |
| Contrast ratio (large text) | WCAG 2.1 AA | >= 3:1 against background | Contrast checker tool on screenshot | Ratio < 3:1 |
| Ward text legibility | Hapax-native | Ward content readable at 1080p stream capture resolution | Screenshot at stream resolution, reading test | Any ward text unreadable at target resolution |
| Signal label legibility | Hapax-native (governed, section 5) | Signal pip labels and severity indicators distinguishable at stream resolution | Screenshot review | Signal states indistinguishable |

#### 3. Camera Framing Quality

Hapax operates 6 RGB cameras (3 BRIO + 3 C920) composited by
`studio_compositor.py` via GStreamer/cudacompositor.

| Dimension | Standard | Target | Measurement method | Failure predicate |
|---|---|---|---|---|
| Subject positioning | Adapted: cinematographic convention | Operator positioned within center-third of frame in primary camera tile | Frame capture review | Operator consistently outside center-third (accounting for fixed camera position) |
| Headroom | Adapted: cinematographic convention | Operator head not cropped, adequate space above | Frame capture review | Head cropped or touching top edge of tile |
| Multi-camera coherence | Hapax-native | All active camera tiles show meaningful content (no black frames, no frozen frames, no duplicate angles providing no additional information) | Multi-frame capture comparison | Camera tile shows black, frozen, or redundant content |
| Layout mode suitability | Hapax-native (governed) | Active layout mode (balanced/packed/sierpinski) matches current content programme requirements | Visual inspection against programme layout intent | Layout mode contradicts programme requirements |
| Obscuring compliance | Hapax-native (invariant) | Compositing effects always obscure camera content sufficiently for privacy | Frame capture review | Camera content identifiable through compositor effects where obscuring is required |

#### 4. Compositor and Shader Quality

| Dimension | Standard | Target | Measurement method | Failure predicate |
|---|---|---|---|---|
| Effect graph coherence | Hapax-native | Active effect graph produces visually coherent output (no artifacting, no z-fighting, no obvious rendering errors) | Frame capture during active effects | Visual artifacts, z-fighting, render errors |
| Preset transition smoothness | Hapax-native (governed, section 6.2) | Transitions between presets complete in 200-300ms with ease-out easing | Visual observation during transition | Jarring transitions, visible state jumps, wrong duration |
| Breathing animation stream-safety | Hapax-native (governed, section 12.3) | Opacity animations on stream-visible surfaces satisfy at least one of: delta >= 0.5, position delta >= 2px, or color boundary crossing | Frame-diff analysis on stream capture | Animation appears as flat frames punctuated by keyframe jumps |
| Stimmung border rendering | Hapax-native (governed, section 3.4) | Stimmung borders use CSS custom properties, opacity matches stance table | Inspection of rendered border colors against section 3.4 | Hardcoded rgba values, wrong opacity for stance |
| Broadcast color envelope | Hapax-native (governed, section 12.2) | High-luminance high-saturation colors muted 15% chroma on stream surfaces | Color measurement on stream capture | Unmuted saturated colors on stream-visible surface |

#### 5. Interview-Specific Visual Composition

Interview segments require specific visual affordances per the interview stress
test spec (2026-05-06).

| Dimension | Standard | Target | Measurement method | Failure predicate |
|---|---|---|---|---|
| Question card visibility | Adapted: interview methodology (layout responsibility) | Active question card visible and readable throughout question-answer cycle | Frame capture during interview segment | Question card absent, obscured, or unreadable during active question |
| Source card presence | Adapted: interview methodology (source consequence) | Source references visible alongside question when source-pressure justifies the question | Frame capture during sourced question | Source card absent for question with declared source pressure |
| Answer/transcript card | Adapted: interview methodology (turn receipt) | Operator answer state (confirmed, refused, skipped, pending) visible after each question | Frame capture during answer phase | No visual indication of answer state |
| Readback card | Adapted: interview methodology (public artifact readback) | Summary of what changed / did not change visible during readback phase | Frame capture during readback | Readback phase has no visual representation |
| Visual separation from non-interview | Hapax-native | Interview visual state clearly distinct from non-interview content programming | Layout comparison | Interview-mode layout indistinguishable from default content programming layout |
| Consent/privacy indicators | Hapax-native (governed, section 3.8 + interview stress test) | Off-record, private, skip states visually indicated when active | Frame capture during boundary utterance | Boundary state with no visual indicator |

### Evidence Collection Protocol

For any work item with visual impact:

1. **Pre-change screenshots:** capture affected surfaces using `scripts/compositor-frame-capture.sh` across all affected states
2. **Post-change screenshots:** capture same surfaces after implementation
3. **Before/after comparison:** include both in PR for review (per CLAUDE.md: "Visual PRs MUST include before/after screenshots")
4. **Mode verification:** if the change affects themed surfaces, capture in both Gruvbox (R&D) and Solarized (Research) modes
5. **Stream resolution check:** if the change affects stream-visible surfaces, verify readability at 1080p capture resolution

For interview-specific work:

6. **Interview layout walkthrough:** capture each interview visual state (question shown, answer pending, answer received, readback, boundary)
7. **Card readability test:** verify question card text, source card text, and answer card text at stream resolution
8. **Consent indicator test:** verify boundary state indicators are visible and distinct

### Live Broadcast Witness Tactics (OBS-captured surfaces)

For surfaces whose ground truth is the broadcast-facing OBS frame — the
DarkPlaces/Screwm live-texture renderer, or the studio compositor as OBS sees it,
not a dev render or the in-engine view — evidence is collected through the
broadcast path itself. Validated 2026-05-29 against the Screwm renderer
(`scripts/screwm-effect-drift-matrix-witness.py`); for live surfaces these tactics
supersede a single dev-resolution screenshot.

1. **Capture from OBS, not the engine.** Use obs-websocket `SaveSourceScreenshot`
   to capture the exact frame OBS is encoding (read the obs-websocket password from
   the OBS plugin config and never log it; fall back to an X11 grab only when
   obs-websocket is unreachable). A dev render or in-engine view can diverge from
   what the audience sees (broadcast color envelope, scaling, source routing).

2. **Tactical POV sweep — never trust one angle.** No single camera position shows
   the whole surface. Sweep a small set of fixed, named stations that together
   cover the failure modes that matter: a room/overview station (is the space
   filled — no black void, expected element count), wall/receiver stations (are the
   ward islands lit, distinct, legible), and a center station (is the focal element
   — AoA sphere / Sierpinski substrate — crisp). Resolve stations from the surface's
   own spatial layout (e.g. Screwm `GARDEN_CAMERA_STATIONS`) so coverage tracks the
   geometry, not arbitrary viewpoints. Settle each station briefly before capturing
   so the camera transition does not pollute the frame.

3. **Duration-bound observation — single frames lie.** For any criterion about
   change-over-time (liveness, no-blink / no-global-flash per WCAG 2.3.1, preset
   transition smoothness, breathing stream-safety), capture a hold sequence (N
   frames over a few seconds at a fixed POV) and compute temporal metrics
   (consecutive luma delta + consecutive motion). This is the authoritative test for
   two things a single frame — or an engine frame-counter — cannot decide:
   - **Live vs frozen.** A CPU-bound renderer can sit at its normal ~90% CPU with an
     unreliable internal frame counter; `mean_consecutive_motion > 0` over a hold is
     the reliable proof the broadcast is advancing. (2026-05-29: a "frozen" reading
     from the engine frame-counter was a false alarm; the motion metric correctly
     showed the render live, preventing an unnecessary revert.)
   - **No-blink / no-global-flash.** A global flash or hard blink shows up as a large
     whole-frame luma delta between consecutive hold frames; the duration metrics
     make the violation measurable instead of relying on a lucky single capture.

4. **Perf is part of the visual evidence.** For live render surfaces under a
   frame-budget invariant (Screwm: 1080p60), pair every visual capture with a
   GPU-utilization + VRAM + renderer-CPU sample, so a change that quietly broke the
   frame budget is caught with the frame, not hours later. Headless fps is not
   directly measurable on this renderer — treat GPU headroom plus the duration
   motion metric (advancing, not stalled) as the proxy, and bound any new per-frame
   cost (e.g. a drift-gated dlight set) with a live-tunable knob so the budget can be
   dialed without a rebuild.

### Failure Modes This Contract Prevents

1. A visual change passes CI but makes wards unreadable on stream.
2. A compositor effect change introduces artifacts nobody notices until live.
3. Interview layout ships with no visual state for answer receipts or boundary utterances.
4. A mode switch leaves an interview card on the wrong palette.
5. Camera framing changes shift the operator out of frame and nobody checks.
6. A shader effect change passes code review but looks wrong (REQ-AVSDLC-010: metric-only pass insufficient for perceptual work).
7. Stream-visible text ships at 10px and nobody catches it because it looked fine in development at 4K.
8. A live render is declared frozen — or declared live — on the basis of an unreliable engine frame-counter or a single screenshot, when liveness is a temporal property only a duration-bound motion metric read from the broadcast frame can decide (2026-05-29 Screwm false alarm).

---

## Cross-Document Dependencies

```
REQ-20260508190834 (parent request)
  |
  +-- CASE-AVSDLC-STANDARDS-20260515 (this authority case)
  |     |
  |     +-- Audio Evidence Contract (AVSDLC-002 scope)
  |     |     +-- references: audio-architecture-handoff.md
  |     |     +-- references: tts-alternatives-evaluation-2026-05-14.md
  |     |     +-- references: AVSDLC-002 S5 ISAP
  |     |     +-- references: non-anthropomorphic segment prep framework
  |     |     +-- references: interview stress test spec
  |     |
  |     +-- Visual Evidence Contract
  |           +-- references: logos-design-language.md (normative)
  |           +-- references: logos-ui-reference.md (normative)
  |           +-- references: interview stress test spec
  |           +-- references: compositor source registry spec
  |
  +-- Existing relay artifacts:
        +-- S2 plan draft v0 (2026-05-08)
        +-- S3 review synthesis (2026-05-08)
        +-- S4 plan acceptance synthesis (2026-05-09)
        +-- AVSDLC-002 S5 ISAP (2026-05-09)
        +-- AVSDLC-005 S7/S8/S9 receipts (2026-05-09)
        +-- Profile gap resolution (2026-05-09)
        +-- S4 amendment reconciliation (2026-05-09)
```

## Open Questions for Operator Review

1. **Camera framing standard precision:** The adapted cinematographic
   conventions (rule of thirds, headroom) are approximate given fixed-position
   cameras. Should the visual evidence contract specify tighter positioning
   targets, or is "center-third with headroom" sufficient?

2. **Pacing measurement tools:** The audio evidence contract calls for pause
   distribution and speaking rate measurement. These require tooling that may
   not exist yet. Should the contract note which measurements are
   aspirational vs. immediately testable?

3. **Aesthetic unity operationalization:** The audiovisual standard for
   "aesthetic unity across modalities" is the hardest to operationalize. The
   formation record acknowledges this. Is "no obvious cross-modal
   contradiction" a sufficient initial gate, or does the operator want more
   specific criteria?

4. **TTS engine change gate:** The audio evidence contract requires full
   re-evaluation on TTS engine change. Given the TTS alternatives evaluation
   identified Chatterbox-Turbo and Qwen3-TTS as candidates, should the
   evidence contract specify which dimensions are most critical for A/B
   comparison?
