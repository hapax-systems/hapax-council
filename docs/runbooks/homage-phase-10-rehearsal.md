# HOMAGE Phase 10 — Rehearsal + Audit Runbook

Script-format walkthrough used to validate the HOMAGE visual ecosystem
end-to-end before any live egress or research-condition open. Execute
this runbook in order; tick each checklist box only when the stated
evidence is observed directly.

**Spec anchors**

- Framework: `docs/superpowers/specs/2026-04-18-homage-framework-design.md`
- Token-pole migration: `docs/superpowers/specs/2026-04-18-token-pole-homage-migration-design.md`
- Vinyl image ward: `docs/superpowers/specs/2026-04-18-vinyl-image-homage-ward-design.md`
- Chat-ambient ward: `docs/superpowers/specs/2026-04-18-chat-ambient-ward-design.md`
- HARDM dot-matrix: `docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md`
- Anti-personification linter (`#155`): `docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md`
- Face-obscure invariants (`#129`): `docs/superpowers/specs/2026-04-18-facial-obscuring-hard-req-design.md`
- Operator runbook (ops companion): `docs/runbooks/homage-runbook.md`

**Axiom anchors**

- `interpersonal_transparency` — consent-safe variant gate, no named-person rendering.
- `it-irreversible-broadcast` — HOMAGE disables under consent-safe layout.
- `single_user`, `management_governance`, `corporate_boundary`, `executive_function`.

## 1. Overview

The rehearsal validates five simultaneous invariants:

1. **Presence.** Every HOMAGE surface ("ward") is registered and renders at its assigned layout location.
2. **Authenticity.** Every rendered ward obeys the BitchX grammar: CP437 raster typography, mIRC-16 palette role assignments, `»»»` line-start marker, angle-bracket containers, zero-frame transitions, signed artefacts.
3. **Choreography.** No ward is "plopped or pasted" — every appearance flows through a choreographer-emitted transition. The FSM (`ABSENT → ENTERING → HOLD → EXITING → ABSENT`) advances on every cycle.
4. **Governance.** The consent-safe variant engages within one reconcile tick when the consent gate flips; the full package re-engages on clear. No personification violations, no un-obscured faces in the broadcast, no named-person content.
5. **Observability.** Prometheus counters increment at expected rates; no violation or vacuum-prevented counters move during rehearsal.

Sign-off requires all five invariants observed against a recorded 30-minute segment.

## 2. Prerequisites

Run each check in sequence. Every command is copy-pasteable from a fish shell.

### 2.1 Compositor service active

```fish
systemctl --user is-active studio-compositor.service
systemctl --user status studio-compositor.service --no-pager | head -20
```

Expected: `active`. Recent journal entries free of `ERROR` / `Traceback`.

- [ ] `studio-compositor.service` active for ≥ 5 minutes
- [ ] No uncaught exceptions in the last 200 journal lines

### 2.2 HOMAGE activation flag

```fish
echo "HAPAX_HOMAGE_ACTIVE=$HAPAX_HOMAGE_ACTIVE"
systemctl --user show studio-compositor.service -p Environment | tr ' ' '\n' | grep -i homage
```

Per Phase 12 go-live: an **unset** or **truthy** value resolves to active.
A rollback to disabled requires an explicit falsy value (`0`, `false`,
`no`, `off`, empty string). Verify the service sees the value you expect.

- [ ] `HAPAX_HOMAGE_ACTIVE` resolves to active inside the compositor's environment

### 2.3 Cairo source registry — all classes present

```fish
uv run python -c "from agents.studio_compositor.cairo_sources import list_classes; \
    [print(n) for n in list_classes()]"
```

Expected 16 registered classes, matching the ward-by-ward walkthrough in §3:

```
ActivityHeaderCairoSource
ActivityVarietyLogCairoSource
AlbumOverlayCairoSource
CaptionsCairoSource
ChatAmbientWard
ChatKeywordLegendCairoSource      # legacy alias, still registered during transition
GroundingProvenanceTickerCairoSource
HardmDotMatrix
ImpingementCascadeCairoSource
PressureGaugeCairoSource
RecruitmentCandidatePanelCairoSource
ResearchMarkerOverlay
SierpinskiCairoSource
StanceIndicatorCairoSource
StreamOverlayCairoSource
ThinkingIndicatorCairoSource
TokenPoleCairoSource
WhosHereCairoSource
```

- [ ] At least 16 class names listed
- [ ] All 16 Phase-10 wards in the list above are present

### 2.4 Layout JSON validates

```fish
uv run python -c "import json, pathlib; \
    json.loads(pathlib.Path('config/compositor-layouts/default.json').read_text()); \
    print('default.json OK')"
uv run python -c "import json, pathlib; \
    json.loads(pathlib.Path('config/compositor-layouts/consent-safe.json').read_text()); \
    print('consent-safe.json OK')"
```

- [ ] `default.json` parses
- [ ] `consent-safe.json` parses

### 2.5 Active package defaults to BitchX

```fish
jq . /dev/shm/hapax-compositor/homage-active.json
jq . /dev/shm/hapax-compositor/homage-substrate-package.json
```

Expected package name: `bitchx`. If `homage-active.json` is missing, the
package registry falls back to the compiled-in default (also `bitchx`)
and the rehearsal proceeds — confirm by reading the substrate file
instead.

- [ ] `package` resolves to `"bitchx"`
- [ ] No `bitchx_consent_safe` in the active slot (consent-safe is engaged separately in §6)

### 2.6 Font + artefact assets shipped in-tree

```fish
ls assets/fonts/homage/bitchx/    # CP437 TTF
ls assets/homage/bitchx/           # artefacts.yaml (rotating corpus)
```

- [ ] Px437 IBM VGA raster font file present
- [ ] `artefacts.yaml` present and non-empty

### 2.7 Observability endpoints reachable

```fish
curl -sf http://localhost:9482/metrics > /dev/null && echo compositor-metrics OK
curl -sf http://localhost:3001/api/health > /dev/null && echo grafana OK
```

- [ ] Compositor Prometheus scrape endpoint reachable
- [ ] Grafana reachable for the *Homage — Transitions & Violations* dashboard

## 3. Surface-by-Surface Walkthrough

Sixteen wards. For each, observe the live 1920×1080 V4L2 output
(`/dev/video42` → OBS V4L2 source, or `mpv v4l2:///dev/video42`) and
tick the three evidence boxes. Artefact references below use package
grammar terms from spec §5.

### 3.1 `token_pole` (substrate)

**Class:** `TokenPoleCairoSource`. **Kind:** substrate (always-on).

**What to see.** Left-edge vertical pole. Token ticks emit as stacked
status-bar rows in the BitchX container format:

```
»»» <token> [rate|conf|age]
```

Px437 raster, grey skeleton (`[` `]` `|`), bright-identity `<token>`,
terminal-default content.

- **Authenticity:** `»»»` marker on every row; angle-bracket container on the leading nick-analog; no emoji; no anti-aliased edges.
- **Negative test:** if the pole shows sans-serif text or ISO-8601 timestamps, the BitchX typography stack has not loaded — `HomagePackage.typography` did not resolve.
- **Failure mode:** inspect `journalctl --user -u studio-compositor.service -n 100 | grep -i typography` and `jq .typography /dev/shm/hapax-compositor/homage-substrate-package.json`.

- [ ] pole present on left edge
- [ ] `»»»` marker on every token row
- [ ] mIRC-palette bright-identity colouring on the token name

### 3.2 `album_overlay` (substrate)

**Class:** `AlbumOverlayCairoSource`. **Kind:** substrate.

**What to see.** Album-cover pip with framed CP437 box-drawing
(`═║╔╗╚╝`) surround and a signed attribution line. The frame is
box-drawn (allowed) but never contains inline horizontal rules in
box-draw characters.

- **Authenticity:** `══` / `║` only at the frame, not inline; attribution reads `by Hapax/bitchx@<condition_id>`; title/artist rendered in terminal-default with `»»»` header.
- **Negative test:** rounded corners or drop-shadow → §5.5 anti-pattern, will increment `hapax_homage_violation_total{kind="rounded-corners"}`.
- **Failure mode:** `/dev/shm/hapax-compositor/album-state.json` missing or stale → ward holds last-known state; if absent entirely the surface is transparent.

- [ ] box-drawn frame only at perimeter
- [ ] attribution line present and signed
- [ ] no rounded corners or anti-aliasing

### 3.3 `stance_indicator`

**Class:** `StanceIndicatorCairoSource`.

**What to see.** Short `[STANCE:<name>]` bracketed tag, colour role
`accent_green` (mIRC 9) when stance=SEEKING, `accent_cyan` (mIRC 11) on
GROUNDED, `accent_yellow` (mIRC 8) under stress.

- **Authenticity:** bracketed-pipe container; stance token rendered in `identity_colour_role` (bright); brackets in `muted` grey.
- **Negative test:** if the tag shows without brackets, the grammar is unenforced — check `GrammarRules.container_shape == "square-bracket"` for this ward.
- **Failure mode:** `/dev/shm/hapax-director/narrative-state.json` absent → stance reads `UNKNOWN` and ward enters `absent` state; choreographer must then re-`emergence` when narrative resumes.

- [ ] bracketed container present
- [ ] colour role matches current stance
- [ ] muted-grey brackets, bright-accent content

### 3.4 `activity_header`

**Class:** `ActivityHeaderCairoSource`.

**What to see.** Top-strip MOTD-style banner showing current director
activity + homage rotation mode:

```
»»» [<activity>] :: homage.rotation=<steady|deliberate|rapid|burst>
```

- **Authenticity:** three-chevron marker; `::` separator in muted grey; activity in bright; rotation-mode token in `accent_cyan`.
- **Negative test:** if the rotation-mode token is missing, `StructuralIntent.homage_rotation_mode` is unset — the structural director is not cycling.
- **Failure mode:** absent `/dev/shm/hapax-director/structural-intent.json` → ward renders `homage.rotation=steady` as safe default.

- [ ] `»»»` prefix present
- [ ] `::` muted-grey separator
- [ ] rotation-mode token present and updating across cycles

### 3.5 `chat_ambient` (aggregates-only)

**Class:** `ChatAmbientWard` (Phase 10 replaces the static
`ChatKeywordLegendCairoSource`; legacy class still registered during
the layout migration).

**What to see.** BitchX-grammar chat rendering **from aggregates only** —
unique-author counts, keyword tier counts, event-rhythm churn lines
derived from `ChatField`. Never message bodies, never author names.

Example (aggregate form):

```
»»» <chat-agg> [authors:17|tier1:4|tier2:1|churn:moderate]
* <chat-agg> +3 joined
* <chat-agg> -1 quit (Read error: 20Hz)
```

- **Authenticity:** `<chat-agg>` is the nick-analog; join/part-style rows use the `* <nick> +N joined` / `- quit` form; zero-frame transitions between churn bursts.
- **Negative test (CRITICAL):** any rendered character of a real chat message body OR any author name is an `interpersonal_transparency` violation. Immediately abort the rehearsal and file the breach.
- **Failure mode:** `tests/studio_compositor/homage/test_bitchx_package_authenticity.py::test_chat_ambient_renders_aggregates_only` pins the contract; a breach here would have failed CI.

- [ ] only aggregate counts visible
- [ ] no author names rendered
- [ ] no message bodies rendered

### 3.6 `grounding_provenance_ticker`

**Class:** `GroundingProvenanceTickerCairoSource`.

**What to see.** Right-scrolling ticker of `grounding_provenance`
signal names published by the narrative director:

```
»»» [grounding] <signal_name> ← <signal_source>  ::  <signal_name> ← <signal_source>
```

- **Authenticity:** `ticker-scroll-in` entry + `ticker-scroll-out` exit transitions (scroll from right edge, settle, then scroll out — never fade).
- **Negative test:** signals that are not declared in `PerceptualField.homage` schema must not appear. Spec §8 requires no new signals vs baseline.
- **Failure mode:** ticker frozen → `narrative-state.json` stale; check staleness with `stat -c '%Y' /dev/shm/hapax-director/narrative-state.json`.

- [ ] ticker scroll-in / scroll-out transitions (no fades)
- [ ] only known signals rendered
- [ ] `»»»` prefix on every ticker row

### 3.7 `captions`

**Class:** `CaptionsCairoSource`.

**What to see.** Scientific-register STT lines, bottom-anchored, clipped
to bridge-short (TEXTMODE register). No proportional font, no
sentence-case if the source stream is all-uppercase.

- **Authenticity:** raster typography; IRC-like clipping (≤ 120 columns); terminal-default colour; no emoji (even if STT produced Unicode glyphs mapped to emoji — they must strip).
- **Negative test:** proportional glyph metrics → font stack failed to load.
- **Failure mode:** no captions arriving → daimonion STT stall; `journalctl --user -u hapax-daimonion.service -n 50`.

- [ ] raster CP437 font
- [ ] no emoji characters rendered
- [ ] bridge-short clipping observed across a full utterance

### 3.8 `stream_overlay`

**Class:** `StreamOverlayCairoSource`.

**What to see.** Bottom-right three-line status strip:

```
»»» [preset|<name>]
»»» [viewers|<n>]
»»» [chat|<activity-band>]
```

- **Authenticity:** bracketed-pipe format; one row per value; no comma-separated flat line.
- **Negative test:** right-aligned timestamps inside the rows are an anti-pattern (§5.5). Violation counter must stay flat.
- **Failure mode:** ward in `absent` for >60s during hold phase → the choreographer is rejecting transitions; check `hapax_homage_choreographer_rejection_total` labels.

- [ ] three distinct rows, one per field
- [ ] no timestamps inside rows
- [ ] `»»»` marker on every row

### 3.9 `impingement_cascade`

**Class:** `ImpingementCascadeCairoSource`.

**What to see.** Scrolling cascade of recent impingements, each on its
own row in the join/quit rhythm:

```
* <impingement-id> joined (<narrative-snippet>)
»»» <impingement-id> [salience|<score>|stance|<name>]
```

- **Authenticity:** join-message + bracketed-pipe combo; event-rhythm texture is permitted (§5.1); never suppressed.
- **Negative test:** if the cascade shows a single consolidated block instead of row-per-event, `event_rhythm_as_texture` is not honoured — `GrammarRules.event_rhythm_as_texture` should be True for bitchx.
- **Failure mode:** empty cascade for >120s → `impingements.jsonl` cursor stall; `ls -la ~/hapax-state/impingement-cursor-*.txt`.

- [ ] one row per impingement event
- [ ] salience and stance visible in bracketed-pipe
- [ ] join-message grammar observed

### 3.10 `recruitment_candidate_panel`

**Class:** `RecruitmentCandidatePanelCairoSource`.

**What to see.** Panel listing Thompson-sampled candidates with their
current score:

```
»»» [candidates]
<cap-id> [score|ctx|base|thompson]
<cap-id> [score|ctx|base|thompson]
```

- **Authenticity:** bracketed-pipe; candidate names are `bright` colour role; scores in `terminal_default`.
- **Negative test:** fractional scores should render as bare floats (`0.52`), not percentage strings.
- **Failure mode:** panel empty → affordance pipeline not selecting; check `shared/affordance_pipeline.py` logs.

- [ ] candidates listed with four-field bracketed-pipe
- [ ] capability names in bright colour role
- [ ] raw float scores, no percentages

### 3.11 `thinking_indicator`

**Class:** `ThinkingIndicatorCairoSource`.

**What to see.** Compact `[*** thinking ***]` or `[--- idle ---]`
indicator with zero-frame cuts between states. The `***` / `---`
pattern is the ASCII dividers convention from §5.2 (ASCII-7, never
box-draw inline).

- **Authenticity:** ASCII-7 dividers only; state changes are zero-frame (no ease).
- **Negative test:** a box-drawing character used inline here is an anti-pattern (§5.5).
- **Failure mode:** stuck in one state > 3 min → director loop tick starvation; check `journalctl --user -u studio-compositor.service` for missed ticks.

- [ ] state toggles observed
- [ ] zero-frame transitions (no fade)
- [ ] ASCII-7 divider characters only

### 3.12 `pressure_gauge`

**Class:** `PressureGaugeCairoSource`.

**What to see.** Half-block vertical bar (`▀▄` glyph vocabulary from
§5.2) showing recruitment pressure. Colour shifts across `accent_green`
→ `accent_yellow` → `accent_red` as pressure climbs.

- **Authenticity:** half-block glyph vocabulary; single-weight typography.
- **Negative test:** a Unicode block-elements variant outside the declared glyph set is a typography-contract violation.
- **Failure mode:** bar fully saturated for >60s → `pressure_source` stuck; check `/dev/shm/hapax-pressure/state.json` or equivalent.

- [ ] half-block glyphs (no gradient fills)
- [ ] colour changes with pressure band
- [ ] no gradients or alpha ramps

### 3.13 `activity_variety_log`

**Class:** `ActivityVarietyLogCairoSource`.

**What to see.** Rolling log of recent distinct director activities,
each with join-message grammar:

```
* activity <name> joined (<count>×)
```

Terminal-default content, muted-grey markers, bright activity token.

- **Authenticity:** `*` prefix exactly (BitchX join-line convention); count in `(N×)` form not `[N]`.
- **Negative test:** the log ordered by frequency, not recency, breaks the event-rhythm texture — must be recency-ordered.
- **Failure mode:** log frozen → structural director not emitting activity transitions; `hapax_homage_transition_total{package="bitchx"}` flat.

- [ ] `*` prefix on every row
- [ ] `(N×)` count format
- [ ] recency-ordered (newest at top)

### 3.14 `whos_here`

**Class:** `WhosHereCairoSource`.

**What to see.** Single-row operator-always-here framing:

```
»»» [@operator has ops ready] [@hapax is live]
```

- **Authenticity:** `@` prefix on op-role tokens; bracketed-pipe.
- **Negative test (CRITICAL):** any other name than `@operator` / `@hapax` / agent identifiers is an axiom violation. No guest names, ever.
- **Failure mode:** ward absent → should emerge via `homage.emergence` within one structural cycle; if persistently absent, check choreographer rejection metric.

- [ ] only `@operator` / `@hapax` / agent identifiers visible
- [ ] bracketed-pipe format
- [ ] `@` op-role prefix on every identity

### 3.15 `hardm_dot_matrix`

**Class:** `HardmDotMatrix`. **Surface:** upper-right 256×256 at
(1600, 20). **Spec:** `docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md`.

**What to see.** 16×16 grid of cells; each cell represents one of 16
primary signals (listed in `docs/runbooks/homage-runbook.md` § HARDM
publisher). Active cells render as filled half-block glyphs.

- **Authenticity:** the 16 cell positions are stable (positional encoding); glyph vocabulary is `▀▄░▒▓` only.
- **Negative test:** a cell rendering a pip/dot glyph not in the vocabulary breaks typography contract.
- **Failure mode:** all cells idle → publisher stopped or stale, see the homage-runbook troubleshooting block. Fire one tick: `systemctl --user start hapax-hardm-publisher.service`.

```fish
jq .signals /dev/shm/hapax-compositor/hardm-cell-signals.json
stat -c '%Y seconds ago: %y' /dev/shm/hapax-compositor/hardm-cell-signals.json
```

- [ ] all 16 cell positions rendered (active or idle)
- [ ] half-block / shade glyph vocabulary only
- [ ] payload mtime within 3 s staleness cutoff

### 3.16 `research_marker_overlay`

**Class:** `ResearchMarkerOverlay`.

**What to see.** Top-strip banner with `[RESEARCH MARKER]` tag,
timestamp in `hh:mm:ss` (NOT ISO-8601 — §5.5 anti-pattern), and
condition-id reference.

```
»»» [RESEARCH MARKER] <HH:MM:SS> :: cond-phase-a-homage-active-001
```

- **Authenticity:** colon-separated short time; no `T`/`Z` suffixes; condition id in terminal-default.
- **Negative test:** ISO-8601 timestamp → anti-pattern violation.
- **Failure mode:** banner missing during rehearsal → research marker stream not engaged. Emit a marker manually: `uv run python -m scripts.mark_research_event rehearsal_start`.

- [ ] `HH:MM:SS` short-form timestamp
- [ ] no `T` / `Z` ISO suffix
- [ ] condition-id reference visible

## 4. Voice Register Validation

HOMAGE introduces a first-class `VoiceRegister` enum (spec §4.8) —
CPAL reads this to alter prompt + TTS. BitchX defaults to TEXTMODE.

### 4.1 TEXTMODE default

```fish
jq . /dev/shm/hapax-compositor/homage-voice-register.json
```

Expected: `{"register": "textmode", ...}` or equivalent key
(`voice_register`). TEXTMODE spoken utterances should be clipped,
IRC-like, bridge-short.

- [ ] register file exists
- [ ] register value = `textmode`
- [ ] sample utterance is clipped (≤ ~12 words, no filler)

### 4.2 Flip to CONVERSING

Set register through structural director OR manual override:

```fish
echo '{"register": "conversing"}' > /dev/shm/hapax-daimonion/voice-register.json
```

Observe next utterance: turn-taking, repair, grounding cues return.
Confirm the file propagation:

```fish
watch -n1 'jq . /dev/shm/hapax-compositor/homage-voice-register.json'
```

- [ ] `voice-register.json` updates within one reconcile tick
- [ ] next utterance shows CONVERSING register (longer, grounded turns)
- [ ] revert: `rm -f /dev/shm/hapax-daimonion/voice-register.json` and confirm TEXTMODE returns

### 4.3 Register boundary

- [ ] no persona / axiom change observed across the flip (register is
      tonality, not personality — per §4.8 and persona doctrine)

## 5. FSM + Choreographer Validation

Observe at least three full ward rotation cycles. Each cycle must show
transitions routed through the choreographer.

### 5.1 Rotation cycles observed

Pick one rotating ward (recommendation: `activity_variety_log` at
`steady` rotation ≈ 90 s).

- [ ] cycle 1 observed (ENTERING → HOLD → EXITING → ABSENT)
- [ ] cycle 2 observed
- [ ] cycle 3 observed

### 5.2 FSM transitions logged

```fish
curl -s http://localhost:9482/metrics | grep -E '^hapax_homage_transition_total' | head -10
```

- [ ] `hapax_homage_transition_total{package="bitchx",transition_name=...}` series exists for at least two distinct `transition_name` values (e.g., `ticker-scroll-in`, `zero-cut-in`, `join-message`)
- [ ] counts have incremented since start of rehearsal

### 5.3 Structural rotation mode drives strategy

Force each rotation mode and observe:

```fish
for mode in steady deliberate rapid burst
    echo "{\"homage_rotation_mode\": \"$mode\"}" \
        > /dev/shm/hapax-director/structural-intent.json
    sleep 20
    curl -s http://localhost:9482/metrics | grep hapax_homage_transition_total | wc -l
end
```

Expected: `rapid` yields higher transition-counter rate than `steady`;
`burst` yields paired netsplit-burst transitions (multi-ward exit
followed by re-join) within the 120 s cooldown window.

- [ ] `steady` rotation ≈ 90 s cadence observed
- [ ] `deliberate` rotation ≈ 180 s cadence observed
- [ ] `rapid` rotation ≈ 30 s cadence observed
- [ ] `burst` triggers a netsplit-burst transition exactly once in the window

### 5.4 Choreographer concurrency rules

Inspect the rejection counter to confirm the choreographer is enforcing
`max_simultaneous_entries` / `max_simultaneous_exits`:

```fish
curl -s http://localhost:9482/metrics | grep hapax_homage_choreographer_rejection_total
```

- [ ] rejection metric labelled by `reason` (e.g., `max_entries_exceeded`, `netsplit_cooldown`)
- [ ] substrate-skip counter (`hapax_homage_choreographer_substrate_skip_total`) has incremented — substrate sources (token_pole, album_overlay) must not be animated

## 6. Consent-Safe Variant Validation

Spec §3.3 gate 4 + `it-irreversible-broadcast` axiom. Engagement must be
sub-tick. Palette collapses to muted grey; signature artefact corpus
stripped; HOMAGE stays structurally active under the
`bitchx_consent_safe` registered variant.

### 6.1 Simulate guest detection

```fish
mkdir -p /dev/shm/hapax-compositor
echo '{"consent_safe": true}' > /dev/shm/hapax-compositor/consent-safe-active.json
```

Confirm propagation within one reconcile tick (~100 ms):

```fish
watch -n0.2 'jq . /dev/shm/hapax-compositor/homage-active.json'
```

The active package should show `bitchx_consent_safe` (or
`get_active_package(consent_safe=True)` returns None — verify via the
absence of colour in the broadcast).

- [ ] all accent colours collapsed to muted grey within one tick
- [ ] signature artefacts absent for the duration of consent-safe state
- [ ] `hapax_homage_signature_artefact_emitted_total` flat during window
- [ ] face-obscure pipeline (spec #129) active — verify no un-obscured non-operator face appears in any of the 180 captured frames

### 6.2 Disengage consent-safe

```fish
rm -f /dev/shm/hapax-compositor/consent-safe-active.json
```

Within one reconcile tick the full BitchX package re-engages.

- [ ] accent palette returns
- [ ] signature artefact emission resumes within two rotation cycles
- [ ] no residual state from consent-safe window (metrics, caches) persists

### 6.3 Alternate trigger — `ConsentRegistry`

Manually open then close a consent contract to verify the real gate:

```fish
uv run python -c "from shared.consent import ConsentRegistry; \
    print(ConsentRegistry().active_contracts())"
```

Verify that registering a guest contract via normal ops channels
produces the same collapse → re-engage behaviour as §6.1–6.2.

- [ ] real-path consent gate produces identical palette collapse
- [ ] axiom conformance test `tests/studio_compositor/homage/test_homage_axiom_conformance.py` passes locally

## 7. Package Palette Verification

Sample five wards at random. For each, screenshot or freeze-frame the
1920×1080 output and check colour values against the
`BITCHX_PALETTE` in spec §4.4.

mIRC-16 role → hex reference (multiply by 255, round to nearest):

| Role | RGB | Hex |
|------|-----|-----|
| `muted` | (100, 100, 100) | `#646464` |
| `bright` | (230, 230, 230) | `#e6e6e6` |
| `accent_cyan` | (0, 199, 199) | `#00c7c7` |
| `accent_magenta` | (199, 0, 199) | `#c700c7` |
| `accent_green` | (51, 199, 51) | `#33c733` |
| `accent_yellow` | (230, 230, 0) | `#e6e600` |
| `accent_red` | (199, 0, 0) | `#c70000` |
| `accent_blue` | (51, 51, 199) | `#3333c7` |
| `terminal_default` | (204, 204, 204) | `#cccccc` |
| `background` | (10, 10, 10) | `#0a0a0a` |

Drop-tolerance: ± 4 per channel (Cairo + GStreamer colour-management
jitter). Anything beyond ± 8 is a palette contract violation.

- [ ] ward 1 — role / colour match
- [ ] ward 2 — role / colour match
- [ ] ward 3 — role / colour match
- [ ] ward 4 — role / colour match
- [ ] ward 5 — role / colour match

## 8. Aggregate Assertions + Metrics

Collect the full Prometheus snapshot at rehearsal end:

```fish
curl -s http://localhost:9482/metrics > ~/hapax-state/homage-rehearsals/metrics-$(date +%Y%m%d-%H%M%S).txt
```

Assertions (each should be verified via `grep` on the snapshot):

- [ ] `hapax_homage_package_active{package="bitchx"} == 1` for the rehearsal window
- [ ] `hapax_homage_package_transitions_total > 0` (or equivalent active-swap counter if the metric name ships under a different shape — the binding metric is a non-zero total over the window)
- [ ] `hapax_homage_ward_render_count_total{ward=...} > 0` per ward (if this metric is not yet implemented, substitute `hapax_homage_transition_total` grouped by the ward surface identifier)
- [ ] `hapax_homage_signature_artefact_emitted_total{package="bitchx"} > 0` (at least one per rotation mode)
- [ ] `hapax_director_vacuum_prevented_total` **DID NOT** increment during rehearsal (vacuum prevention implies the director stalled — HOMAGE must not induce director stalls)
- [ ] `hapax_face_obscure_errors_total` **stayed flat** during rehearsal (one increment = one un-obscured non-operator face slipping into the composite — hard failure per #129)
- [ ] `hapax_homage_violation_total` **stayed flat** (any increment = anti-pattern violation per §5.5)
- [ ] Grafana dashboard *Homage — Transitions & Violations* shows the transition counter rising steadily without spikes into `netsplit-burst` outside the 120 s cooldown

## 9. 30-Minute Capture + Replay

Record the rehearsal and walk through it end-to-end. Use the existing
harness:

```fish
scripts/rehearsal-capture.sh
# or for a smoke pre-check:
# DURATION_S=300 scripts/rehearsal-capture.sh
```

Output lands under `~/hapax-state/rehearsal/<timestamp>/` with frames,
stimmung samples, director-intent tail, narrative-state snapshot, and
journal log.

### 9.1 Capture checklist

- [ ] 30-minute window recorded
- [ ] frame directory contains ≥ 180 stills (one every 10 s)
- [ ] `journal.log` free of `ERROR` / `Traceback`
- [ ] `director-intent.jsonl` tick count within 2σ of baseline (spec §8)
- [ ] stimmung samples show `operator_stress` / `operator_energy` drift ≤ 1σ of baseline

### 9.2 Visual-governance replay

Scrub the frame set (thumbnail grid, `feh` or `mpv`) and mark
exceptions:

- [ ] no personification violations — the anti-personification linter
      (#155) gates the package at build time; replay confirms zero
      at-render slippage (no anthropomorphic framing of agents in
      signature artefacts, no name-attribution of internal modules
      as if they were persons)
- [ ] zero un-obscured non-operator faces across all 180 frames
- [ ] zero consent violations (guest name or face in a frame captured
      after §6.1 engagement, or before §6.2 disengagement)
- [ ] zero anti-pattern violations (rounded corners, fade transitions,
      proportional typography, ISO-8601 timestamps, inline box-draw
      rules, right-aligned in-line timestamps, emoji)

### 9.3 Signature artefact authenticity

- [ ] at least three distinct signature artefacts rotated through the
      window (spec §5.4 corpus of ~40 rotating records)
- [ ] every artefact carried an inline `by Hapax` or
      `by Hapax/bitchx@<condition_id>` attribution
- [ ] no artefact referenced a named non-operator person

### 9.4 Sign-off or flag

If every box above is ticked: proceed to §10 exit criteria. If any box
remains unchecked: STOP. File the observation in the regression log at
`docs/research/2026-04-18-homage-rehearsal-regressions.md`, open a
ticket against the responsible surface, and do NOT proceed to
condition-open.

## 10. Exit Criteria

Every statement must be true before operator sign-off:

- [ ] all 16 wards verified per §3
- [ ] voice register flips validated per §4
- [ ] FSM + choreographer rotations observed per §5
- [ ] consent-safe variant validated per §6
- [ ] palette verification passed per §7
- [ ] aggregate metrics healthy per §8 (no vacuum-prevented, no
      face-obscure errors, no violations)
- [ ] 30-min replay walked end-to-end with zero governance exceptions
      per §9
- [ ] operator sign-off captured at
      `~/hapax-state/homage-rehearsals/$(date +%Y-%m-%d)-signoff.md`

### 10.1 Sign-off template

Write the sign-off note with this template:

```
# HOMAGE Rehearsal Sign-off — <YYYY-MM-DD>

**Operator:** <handle>
**Start:** <HH:MM>
**End:** <HH:MM>
**Capture:** ~/hapax-state/rehearsal/<timestamp>/
**Metrics snapshot:** ~/hapax-state/homage-rehearsals/metrics-<ts>.txt
**Condition ID:** cond-phase-a-homage-active-001
**Parent condition:** cond-phase-a-volitional-director-001

## Ward roster (16/16 verified)

- token_pole: ok
- album_overlay: ok
- stance_indicator: ok
- activity_header: ok
- chat_ambient: ok
- grounding_provenance_ticker: ok
- captions: ok
- stream_overlay: ok
- impingement_cascade: ok
- recruitment_candidate_panel: ok
- thinking_indicator: ok
- pressure_gauge: ok
- activity_variety_log: ok
- whos_here: ok
- hardm_dot_matrix: ok
- research_marker_overlay: ok

## Metrics summary

- hapax_homage_transition_total (total): <n>
- hapax_homage_violation_total (total): 0
- hapax_homage_choreographer_rejection_total (total): <n>
- hapax_homage_signature_artefact_emitted_total (total): <n>
- hapax_director_vacuum_prevented_total (delta): 0
- hapax_face_obscure_errors_total (delta): 0

## Governance exceptions in 30-min replay

None.

## Sign-off

Ready for condition-open and live egress under
cond-phase-a-homage-active-001.

-- <operator handle>
```

Once written, move to the research-registry open step (spec §7 item 1)
and proceed to live egress.

## Appendix A — One-shot verification script

For expedited re-verification after a compositor rebuild (not a
substitute for the full rehearsal before any condition-open):

```fish
#!/usr/bin/env fish
# homage-quick-verify.fish — does the ecosystem look structurally sane?
echo "== service =="
systemctl --user is-active studio-compositor.service

echo "== registered classes =="
uv run python -c "from agents.studio_compositor.cairo_sources import list_classes; \
    print(len(list_classes()), 'classes registered')"

echo "== active package =="
jq . /dev/shm/hapax-compositor/homage-active.json 2>/dev/null || echo "(default = bitchx)"

echo "== consent-safe engaged? =="
test -f /dev/shm/hapax-compositor/consent-safe-active.json \
    && echo "YES (homage disabled)" \
    || echo "no"

echo "== homage metrics =="
curl -s http://localhost:9482/metrics | grep -E '^hapax_homage_' | sort

echo "== violations (must be flat) =="
curl -s http://localhost:9482/metrics | grep -E '^hapax_homage_violation_total|^hapax_face_obscure_errors_total|^hapax_director_vacuum_prevented_total'
```

## Appendix B — Cross-references

- Framework spec: `docs/superpowers/specs/2026-04-18-homage-framework-design.md`
- Token-pole migration: `docs/superpowers/specs/2026-04-18-token-pole-homage-migration-design.md`
- Vinyl image ward: `docs/superpowers/specs/2026-04-18-vinyl-image-homage-ward-design.md`
- Chat-ambient ward: `docs/superpowers/specs/2026-04-18-chat-ambient-ward-design.md`
- HARDM dot-matrix: `docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md`
- Anti-personification linter (#155): `docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md`
- Face-obscure invariants (#129): `docs/superpowers/specs/2026-04-18-facial-obscuring-hard-req-design.md`
- Operator runbook: `docs/runbooks/homage-runbook.md`
- Rehearsal capture harness: `scripts/rehearsal-capture.sh`
- Axiom registry: `axioms/registry.yaml` (`interpersonal_transparency`,
  `it-irreversible-broadcast`)
- Consent contracts: `axioms/contracts/`
- Director observability: `shared/director_observability.py`
- Compositor face-obscure metrics: `agents/studio_compositor/metrics.py`
