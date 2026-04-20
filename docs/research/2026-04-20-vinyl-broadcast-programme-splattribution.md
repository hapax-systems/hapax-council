# Vinyl-Broadcast Programmes & Splattribution: Software Infrastructure Design

Status: research
Date: 2026-04-20
Operator: single hip-hop producer ("LegomenaLive" YouTube channel)
Register: engineering-design-doc; concrete code-shapes, file:line citations
Parent: `docs/research/2026-04-20-vinyl-collection-livestream-broadcast-safety.md` §7 (modes A/B/C/D)
Sibling specs: `docs/superpowers/plans/2026-04-20-programme-layer-plan.md`, `docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md`, `docs/superpowers/specs/2026-04-18-splattribution-design.md`
Relevant memories: `feedback_no_expert_system_rules`, `project_programmes_enable_grounding`, `feedback_hapax_authors_programmes`, `project_hardm_anti_anthropomorphization`, `feedback_grounding_exhaustive`

---

## §1 TL;DR

The four vinyl-broadcast routing modes from the parent doc §7 (A=Selector, B=Turntablist, C=Bed-panic-mute, D=Granular-wash) map cleanly onto the just-shipped `Programme` primitive (`shared/programme.py`) when each mode is encoded as a Hapax-authored Programme whose `ProgrammeConstraintEnvelope` holds **soft priors over capability biases** plus a **monetization opt-in set** (`monetization_opt_ins: frozenset[str]`). The opt-in set is the only field whose semantics are deny/allow rather than bias — it gates `MonetizationRiskGate.candidate_filter` (`shared/governance/monetization_safety.py:107-150`) for `medium`-risk capabilities. `high` is permanently excluded by axiom; `low`/`none` always pass; `medium` requires per-capability opt-in. This single bit is the legal hinge of the whole design.

The splattribution data flow today is: `scripts/album-identifier.py` → writes `/dev/shm/hapax-compositor/album-state.json` + `album-cover.png` + `music-attribution.txt` → `agents/studio_compositor/album_overlay.py::AlbumOverlayCairoSource` reads on every render tick (10 fps, unconditionally as of commit `ca0e955cc`) → composited via Pango/Cairo into the lower-left PiP. The proposed extensions add: (1) per-track license metadata sourced from a vault YAML registry + MusicBrainz/Discogs lookup, (2) Bandcamp/purchase link rendered on the overlay AND injected into the YouTube live chat description, (3) Programme-mode badge in the corner of the splattribution panel, (4) `monetization_risk` displayed as a small color-coded dot for operator-side awareness only (never rendered to broadcast).

The four Programme YAML files proposed in §11 are ready to ship. They live under a new `config/programmes/vinyl-broadcast/` directory and are loaded by a Hapax-authored programme planner (post-#164 Phase 5 — wiring stub today).

---

## §2 Programme schemas for Modes A/B/C/D

### §2.1 Where the Programme primitive sits today

`shared/programme.py` exports `Programme`, `ProgrammeConstraintEnvelope`, `ProgrammeContent`, `ProgrammeRitual`, `ProgrammeSuccessCriteria`, plus the closed-set enums `ProgrammeRole` (12 roles), `ProgrammeStatus`, `ProgrammeDisplayDensity`, and the type aliases `ProgrammePresetFamilyHint`, `ProgrammeHomageRotationMode`. The constraint envelope expresses **soft priors only** — `capability_bias_negative` keys multiply scores in `(0.0, 1.0]`, `capability_bias_positive` keys multiply scores `>= 1.0`, and zero is rejected by the field validator (`shared/programme.py:115-125`). This is the architectural axiom of the primitive: **a Programme cannot create a hard capability gate**.

The single exception — and the only place a Programme behaves like a deny/allow decision — is `monetization_opt_ins`. The `MonetizationRiskGate` reads it via `getattr(programme, "monetization_opt_ins", None)` (`shared/governance/monetization_safety.py:128-134`). `Programme` does **not** yet declare this field; demonet plan Phase 5 wires it in. For now, every Phase-1 caller passes `programme=None` (`shared/affordance_pipeline.py:432-434`), which means medium-risk capabilities are blocked unconditionally. The four Programme files in §11 declare the field anticipatorily so Phase 5 wiring is a one-line enable.

### §2.2 The shared envelope shape for vinyl broadcast

All four vinyl-broadcast Programmes share these fields (concrete examples in §11):

```python
from shared.programme import (
    Programme,
    ProgrammeConstraintEnvelope,
    ProgrammeContent,
    ProgrammeRitual,
    ProgrammeRole,
    ProgrammeSuccessCriteria,
)
from shared.affordance import MonetizationRisk

# Sketch of the not-yet-merged Phase-5 Programme.monetization_opt_ins extension.
# When demonet plan Phase 5 lands, this lifts to the Pydantic model directly.
class VinylBroadcastProgramme(Programme):
    monetization_opt_ins: frozenset[str] = frozenset()  # capability_name set
    mode_label: str = ""  # "A" | "B" | "C" | "D" — surfaced on overlay
    max_dwell_in_dry_signal_s: float | None = None  # Mode-A time-cap
```

**Capability namespace** (referenced by the Programme bias dicts and the opt-in set): the audit-friendly convention is `vinyl.<source>.<surface>.<risk-tier>`. Examples used below:

- `vinyl.crate.dry.<artist-id>` — direct vinyl playback, dry signal dominant; **per-track risk**
- `vinyl.crate.transformed.<artist-id>` — vinyl through Evil Pet + S-4 + ≥6% pitch/time VST; risk **down-graded** by transformation per parent §5
- `vinyl.bed.cc-by` — royalty-free / CC-BY bed library tracks; **none**
- `vinyl.bed.youtube-audio-library` — YT Audio Library; **none** (covered by YouTube's own license)
- `audio.fx.granular.evil-pet` — Endorphin.es Evil Pet granular processor send; bias surface, no monetization risk on its own
- `audio.fx.sampler.torso-s4` — Torso S-4 sampler/FX send; same
- `overlay.splattribution.attribution-text` — Pango render of artist/title/year/label
- `overlay.splattribution.purchase-cta` — Bandcamp/Discogs link rendering

The `monetization_risk` for each capability is declared at registration time on the `OperationalProperties` (`shared/affordance.py:33-34`). For per-track vinyl capabilities, that risk MUST come from the per-track license metadata catalog (§4) — never from an LLM classification. The catalog is the source of truth; the affordance registration is a passive read.

### §2.3 Programme schemas, mode-by-mode

#### Mode A — Selector (legally riskiest; minimum-modification playback)

Operator intent: minimally-modified vinyl playback (light reverb only, no granular, faithful to source). Per parent §7.1 and §5.1, this is the LEGALLY RISKY mode on YouTube. Programme defensibility comes from: (1) very short dwell (< 60 s per track in Mode A), (2) heavy attribution overlay at maximum opacity, (3) auto-transition to Mode B at the dwell cap, (4) explicit operator awareness of the mode posture.

```yaml
# config/programmes/vinyl-broadcast/mode-a-selector.yaml
programme_id: vinyl-broadcast-mode-a-selector
role: showcase
status: pending
planned_duration_s: 600  # 10 minutes target window for the whole programme
parent_show_id: $SHOW_ID  # injected by programme planner
mode_label: "A"
notes: |
  Selector mode — minimum-modification playback. Per parent §7.1, this mode
  is HIGH risk on YouTube; Programme guarantees < 60s per track in dry signal,
  splattribution at maximum opacity, and forced transition to Mode B at cap.

monetization_opt_ins:
  # Mode A opts in `low`-risk vinyl crate plays + the bed library.
  # `medium` and `high` are NOT opted in — the gate filters them out
  # at recruitment, not at playback. Operator's no-play list cascades
  # into per-track risk metadata; tracks the operator has flagged
  # personally are catalogued as `medium` and therefore not opted in
  # for Mode A even if the operator bumps them onto the platter.
  - vinyl.bed.cc-by
  - vinyl.bed.youtube-audio-library
  - overlay.splattribution.attribution-text
  - overlay.splattribution.purchase-cta

max_dwell_in_dry_signal_s: 60.0  # forced transition to Mode B at cap

constraints:
  capability_bias_positive:
    overlay.splattribution.attribution-text: 4.0  # ALWAYS prefer attribution
    overlay.splattribution.purchase-cta: 3.0
  capability_bias_negative:
    audio.fx.granular.evil-pet: 0.25  # bias against, do not require off
    audio.fx.sampler.torso-s4: 0.25
  preset_family_priors:
    - calm-textural
    - warm-minimal
  homage_rotation_modes:
    - paused
  display_density: dense  # max splattribution information

content:
  invited_capabilities:
    - vinyl.bed.cc-by
    - overlay.splattribution.attribution-text
  narrative_beat: |
    Selector mode: short dry-signal exposure with full attribution.
    Defensible only as DJ-set/commentary posture, not music streaming.

ritual:
  entry_ward_choreography:
    - splattribution.fade_in_full_opacity
  entry_substrate_palette_shift: solarized-research-warm
  exit_ward_choreography:
    - splattribution.fade_to_persistent_low
  boundary_freeze_s: 2.0  # short, snap into A then snap back

success:
  completion_predicates:
    - dwell_cap_reached
  abort_predicates:
    - content_id_warning_received
    - operator_panic_pressed
  min_duration_s: 15.0
  max_duration_s: 60.0
```

**Why these biases.** `capability_bias_positive` for the splattribution capabilities at `4.0` is the strongest legitimate up-weight short of forcing recruitment. The splattribution capabilities will essentially always recruit when their similarity is non-zero. `capability_bias_negative` for granular/sampler at `0.25` strongly de-prioritizes effects in this mode without forbidding them — operator can still trigger them via direct command if the moment calls for it (per `feedback_no_expert_system_rules`). `preset_family_priors: [calm-textural, warm-minimal]` aligns the visual tier to the auditory posture.

**Why the dwell cap.** The `max_dwell_in_dry_signal_s` field is a **Programme-level time invariant** that the programme-monitor loop watches. When the cap is hit, the planner aborts Mode A (`abort_predicates: [dwell_cap_reached]`) and transitions to Mode B. This is the structural enforcement of parent §7.1's "< 60 sec per track in Mode A before forced transition" rule. Note that this is NOT a hardcoded threshold in the affordance pipeline — it lives on the Programme record, where Hapax can author different caps for different programmes.

#### Mode B — Turntablist (recommended on YouTube)

Operator intent: dry-signal at low blend, Evil Pet + S-4 active, ≥6% pitch/time VST in chain. Per parent §7.1, this is the **recommended YouTube mode** because the spectral peak constellation is shifted away from the source by the parallel transformation branches.

```yaml
# config/programmes/vinyl-broadcast/mode-b-turntablist.yaml
programme_id: vinyl-broadcast-mode-b-turntablist
role: showcase
status: pending
planned_duration_s: 1800  # 30 minutes
parent_show_id: $SHOW_ID
mode_label: "B"
notes: |
  Turntablist mode — primary YouTube posture. Dry signal subordinate to
  Evil Pet (granular) + Torso S-4 (sampler) parallel transformation branches.
  ≥6% pitch/time VST applied at host before encoder. Per parent §5.1, this is
  the empirical Content-ID-defeat working mode; per parent §7.1, the
  recommended-for-YouTube routing.

monetization_opt_ins:
  - vinyl.crate.transformed  # all `medium` per-track tracks recruitable WHEN transformed
  - vinyl.bed.cc-by
  - audio.fx.granular.evil-pet
  - audio.fx.sampler.torso-s4
  - overlay.splattribution.attribution-text
  - overlay.splattribution.purchase-cta

max_dwell_in_dry_signal_s: null  # not applicable; dry signal is subordinate

constraints:
  capability_bias_positive:
    audio.fx.granular.evil-pet: 3.5
    audio.fx.sampler.torso-s4: 3.0
    overlay.splattribution.attribution-text: 2.0
    overlay.splattribution.purchase-cta: 1.5
  capability_bias_negative:
    vinyl.crate.dry: 0.2  # strongly discourage dry-signal-dominant scoring
  preset_family_priors:
    - audio-reactive
    - glitch-dense
  homage_rotation_modes:
    - weighted_by_salience

  # Twitch director already gates these on `vinyl_playing` per
  # docs/superpowers/specs/2026-04-18-splattribution-design.md §6;
  # Programme amplifies that gate's downstream impact without overriding it.
  ward_emphasis_target_rate_per_min: 2.5
  reverie_saturation_target: 0.6

content:
  invited_capabilities:
    - audio.fx.granular.evil-pet
    - audio.fx.sampler.torso-s4
    - overlay.splattribution.attribution-text
  narrative_beat: |
    Turntablist mode: parallel transformation branches dominate spectral
    output; dry signal subordinate. Splattribution remains visible but at
    moderate opacity to admit visual tier of granular activity.

ritual:
  entry_ward_choreography:
    - fx.engage.evil-pet
    - fx.engage.torso-s4
  entry_substrate_palette_shift: gruvbox-rnd-active
  exit_ward_choreography:
    - fx.disengage.evil-pet
    - fx.disengage.torso-s4
  boundary_freeze_s: 4.0

success:
  completion_predicates:
    - planned_duration_reached
  abort_predicates:
    - content_id_warning_received
    - operator_panic_pressed
  min_duration_s: 300.0
  max_duration_s: 3600.0
```

**Why the transformation FX get strong bias.** `audio.fx.granular.evil-pet: 3.5` and `audio.fx.sampler.torso-s4: 3.0` make the parallel transformation branches the dominant recruitment winners during Mode B. This propagates structurally — the FX engagement also signals to the visual chain (`audio-reactive` preset family prior), so the visual tier becomes glitch-dense to match the auditory posture. The recruitment pipeline still scores everything against impingement similarity, but the Programme tilts the field strongly toward FX-active routing.

#### Mode C — Bed-panic-mute (always safe)

Operator intent: ambient royalty-free underneath operator talking, OR emergency mute on Content ID warning. Two distinct sub-postures sharing one Programme. The opt-in set excludes ALL vinyl crate plays — only `none`-risk bed library and pre-cleared YouTube Audio Library tracks are recruitable.

```yaml
# config/programmes/vinyl-broadcast/mode-c-bed-panic-mute.yaml
programme_id: vinyl-broadcast-mode-c-bed-panic-mute
role: ambient
status: pending
planned_duration_s: 900  # 15 minutes default; extended on panic until operator releases
parent_show_id: $SHOW_ID
mode_label: "C"
notes: |
  Bed/panic-mute mode — always safe. Two sub-postures:
    - bed: ambient royalty-free under talking/silence
    - panic-mute: emergency mute after Content ID warning (parent §8.2)
  Distinguished by `entered_via` field on the Programme transition log,
  not by separate Programmes — same envelope serves both.

monetization_opt_ins:
  # Note: NO vinyl crate capabilities. NO transformed-vinyl capabilities.
  # Bed library only.
  - vinyl.bed.cc-by
  - vinyl.bed.youtube-audio-library
  - overlay.splattribution.attribution-text  # for bed library attribution

max_dwell_in_dry_signal_s: null  # no vinyl signal at all

constraints:
  capability_bias_positive:
    vinyl.bed.cc-by: 4.0
    vinyl.bed.youtube-audio-library: 4.0
    overlay.splattribution.attribution-text: 2.0
  capability_bias_negative:
    audio.fx.granular.evil-pet: 0.1  # FX silent during bed — strongest legitimate bias-against
    audio.fx.sampler.torso-s4: 0.1
  preset_family_priors:
    - calm-textural
  homage_rotation_modes:
    - paused
  reverie_saturation_target: 0.2  # visual quiet too

content:
  invited_capabilities:
    - vinyl.bed.cc-by
    - vinyl.bed.youtube-audio-library
  narrative_beat: |
    Bed mode: ambient pre-cleared underneath. If entered via panic, hold
    until operator releases — do not auto-transition out.

ritual:
  entry_ward_choreography:
    - audio.crossfade.from_vinyl_to_bed_2s
  entry_substrate_palette_shift: solarized-research-calm
  exit_ward_choreography:
    - audio.crossfade.from_bed_to_silence_2s
  boundary_freeze_s: 2.0  # smooth, not stark

success:
  completion_predicates:
    - operator_release_pressed  # for panic entry
    - planned_duration_reached  # for ambient entry
  abort_predicates:
    - operator_emergency_stream_end  # never auto-abort, only operator can
  min_duration_s: 30.0
  max_duration_s: 7200.0  # 2-hour ceiling (could be entire stream tail)
```

**Why `0.1` on FX capabilities.** This is the closest legal value to "off" the validator allows. `0.0` would be a hard gate, which the architectural axiom forbids (`shared/programme.py:115-125`). At `0.1`, an FX capability scoring `0.7` similarity gets a combined bias of `0.07` after the recruitment formula's bias multiplier, putting it well below the recruitment threshold (`THRESHOLD = 0.05` at `shared/affordance_pipeline.py:29`) but not strictly excluded. If the operator manually triggers an FX engagement during Mode C (deliberate soft override), it CAN still recruit — but won't on its own.

**Panic-mute mechanics** (the daemon side, not the Programme side):
The Programme transition is triggered by a panic event handler. Detection of YouTube live Content ID warnings is a **separate concern from Programme authorship** — the warning detection daemon polls the YouTube Live API (or scrapes the studio dashboard if the API is rate-limited; per parent §3.5 there is no first-party stream-event firehose for this) and emits a `panic.content_id_warning` impingement. The programme planner's response to that impingement is to call `Programme.status = ABORTED` on the active Mode A/B/D Programme and instantiate a Mode C Programme with `entered_via=panic`. The audio crossfade ritual (`audio.crossfade.from_vinyl_to_bed_2s`) is an entry choreography step that the studio compositor's audio side executes via PipeWire filter-chain crossfade.

#### Mode D — Granular-wash (deepest defeat; texture-mode)

Operator intent: deepest Content ID defeat. Vinyl source feeds Evil Pet only, dry channel muted, grain size ≤ 30ms, jitter ≥ 60%. Source recognition reduced to texture; per parent §5.3 this is the strongest spectral re-synthesis mode.

```yaml
# config/programmes/vinyl-broadcast/mode-d-granular-wash.yaml
programme_id: vinyl-broadcast-mode-d-granular-wash
role: experiment
status: pending
planned_duration_s: 1200  # 20 minutes
parent_show_id: $SHOW_ID
mode_label: "D"
notes: |
  Granular-wash mode — deepest Content ID defeat. Per parent §5.3, source
  recognition reduced to texture. Even `medium`-risk-when-dry tracks become
  effectively unidentifiable through the granular re-synthesis. Per
  parent §5.5, this is the empirical-floor defeat mode — can carry
  some `high`-when-dry-only tracks WITH the asterisk that runtime
  validation (Ring 2 of demonet plan) gates the actual pre-render,
  not the Programme.

monetization_opt_ins:
  - vinyl.crate.transformed  # all `medium`-when-transformed tracks
  - vinyl.bed.cc-by
  - audio.fx.granular.evil-pet
  - overlay.splattribution.attribution-text  # ambient label only, low opacity
  # NOTE: no overlay.splattribution.purchase-cta — granular-wash mode
  # texturalizes the source; CTA-style attribution would feel dishonest
  # since the listener can't recognize what they'd buy.

max_dwell_in_dry_signal_s: 0.0  # dry signal MUST be muted

constraints:
  capability_bias_positive:
    audio.fx.granular.evil-pet: 4.0  # primary engine
    overlay.splattribution.attribution-text: 1.5  # ambient label
  capability_bias_negative:
    audio.fx.sampler.torso-s4: 0.4  # de-emphasize, do not forbid
    vinyl.crate.dry: 0.05  # closest-to-off allowed
  preset_family_priors:
    - calm-textural
    - audio-reactive
  homage_rotation_modes:
    - random
  reverie_saturation_target: 0.7  # high — the visual tier carries the texture

content:
  invited_capabilities:
    - audio.fx.granular.evil-pet
  narrative_beat: |
    Granular-wash: source as texture. Spectral re-synthesis dominates;
    attribution remains as ambient honesty label without CTA.

ritual:
  entry_ward_choreography:
    - fx.engage.evil-pet.short-grain-high-jitter
    - audio.mute.dry-channel
  entry_substrate_palette_shift: gruvbox-rnd-textural
  exit_ward_choreography:
    - fx.disengage.evil-pet
    - audio.unmute.dry-channel  # back to normal routing on exit
  boundary_freeze_s: 6.0  # longer crossfade — granular is hard to leave abruptly

success:
  completion_predicates:
    - planned_duration_reached
  abort_predicates:
    - content_id_warning_received
    - operator_panic_pressed
  min_duration_s: 120.0
  max_duration_s: 2400.0
```

**Why `vinyl.crate.dry: 0.05` not `0.0`.** Same architectural axiom as Mode C: zero is forbidden. `0.05` is below `THRESHOLD = 0.05` so the dry signal will never recruit from the affordance pipeline alone, but the operator can still toggle dry on by manual MIDI Dispatch press. The `audio.mute.dry-channel` entry ritual handles the audio-tier muting deterministically; the Programme bias handles the recruitment-tier de-emphasis. **Both gates must be alive** — the audio tier is the legal hinge, the recruitment tier is the system-coherence hinge.

### §2.4 What the Programme primitive does NOT encode (intentional)

- **Audio routing topology.** The Programme expresses BIASES on capabilities; it does NOT directly drive PipeWire/JACK routing. Audio-side routing is owned by `agents/studio_compositor/` and the PipeWire filter-chain configs in `config/pipewire/` (council CLAUDE.md § Voice FX Chain). Programme entry/exit rituals (`ProgrammeRitual.entry_ward_choreography`) name the choreography steps; the audio-side daemons execute them.
- **Per-track license metadata.** Programmes opt IN to capability *classes*. Per-track risk classification lives in the catalog (§4). The capability `vinyl.crate.transformed.<artist-id>` is registered with `monetization_risk` set from the catalog, and the Programme's `monetization_opt_ins` admits the whole class.
- **Operator UX.** Programme transition triggers (Stream Deck press, voice command, MIDI Dispatch macro) live in the command registry (`hapax-logos/src/lib/commands/`) and the streamdeck adapter (`config/streamdeck.yaml`). The Programme is the artifact the operator triggers; the UX surface is decoupled.

---

## §3 Splattribution overlay — current state + proposed extensions

### §3.1 Current rendering chain (audited 2026-04-20)

The splattribution overlay is currently the lower-left PiP on the studio compositor, rendered by `AlbumOverlayCairoSource` (`agents/studio_compositor/album_overlay.py:236-417`). The render flow:

1. `scripts/album-identifier.py:735-815` polls the Pi-6 IR overhead camera at 5-sec intervals, hashes a downscaled grayscale, and on hash distance ≥ 8 calls `identify_album_and_track()` (`scripts/album-identifier.py:393-514`) which sends both the IR album cover AND a 12-second audio capture (speed-corrected per `shared.vinyl_rate.rate_to_restore_factor` to compensate for Handytrax 33⅓-on-45 playback) to Gemini Flash via LiteLLM `model: balanced`.
2. `write_state(album, track)` (`scripts/album-identifier.py:652-696`) writes three files atomically:
   - `/dev/shm/hapax-compositor/album-cover.png` — duotone-tinted PNG
   - `/dev/shm/hapax-compositor/music-attribution.txt` — Pango-markup text:
     ```
     SPLATTRIBUTION
     {model} says: "{artist} — {title}"
     Track: "{track}"
     Confidence: {pct}% (LOL)
     ```
   - `/dev/shm/hapax-compositor/album-state.json` — structured state including `artist`, `title`, `year`, `label`, `model`, `confidence`, `current_track`, `timestamp`
3. `AlbumOverlayCairoSource.render_content()` (`album_overlay.py:252-303`) is invoked at 10 fps. It calls `_refresh_cover()` and `_refresh_attribution()` (mtime-cached), then draws via Pango through `text_render.render_text()` and `paint_bitchx_header()` (`album_overlay.py:371-417`).
4. Per the **2026-04-20 fix at `album_overlay.py:264-274`**, the cover refresh + attribution draw are **NO LONGER gated on `vinyl_playing`** — they render unconditionally whenever the data files exist. The `vinyl_playing` signal still gates the twitch director's narrative framing (`agents/studio_compositor/twitch_director.py:150,244`) and the Mode A→B auto-transition (proposed below) but does not dim the panel itself.

### §3.2 Currently-rendered fields vs proposed additions

Currently rendered on the splattribution overlay (`scripts/album-identifier.py:660-674`):

- Header: `SPLATTRIBUTION` (literal string, BitchX-style)
- Model: `{model} says: "{artist} — {title}"`
- Track: `Track: "{current_track}"` (if known)
- Confidence: `Confidence: {pct}% (LOL)` — the `(LOL)` is deliberate operator commentary on dumb-LLM-confidence per the inline comment at `album-identifier.py:668-672`

Proposed additions (cataloged here; concrete render-field plumbing in §3.3):

| Field | Source | Render | When |
|---|---|---|---|
| Year | `album-state.json:year` | `(2021)` after title | Always when known |
| Label | `album-state.json:label` | `[Stones Throw]` after year | Always when known |
| Bandcamp link | License catalog `bandcamp_url` (§4) | small clickable line | Always when in catalog |
| Discogs link | License catalog `discogs_url` (§4) | small clickable line | Always when in catalog |
| Programme mode badge | Active Programme `mode_label` | small corner badge `[A]`/`[B]`/`[C]`/`[D]` | Always when in vinyl-broadcast Programme |
| No-play-list flag | License catalog `no_play_list: bool` (§4) | red corner dot, operator-side only | Suppressed from broadcast |
| Monetization risk dot | Capability `monetization_risk` | small color-coded dot, **operator-side only** | Operator-side overlay only; never broadcast |
| ISRC | Catalog `isrc` lookup | hidden; logged for forensics | Never rendered |

The Programme mode badge is the most operator-facing addition: it tells viewers (and the operator) which routing mode is active. Per anti-anthropomorphization (§9), the badge text is just the letter — no `Hapax is feeling turntable-y`.

### §3.3 Concrete extension to `AlbumOverlayCairoSource`

The Pango render at `album_overlay.py:391-400` builds a single `TextStyle` from the raw attribution text. To add the Bandcamp CTA + mode badge as additional render layers, extend the `_draw_attrib` method:

```python
def _draw_attrib(self, cr: cairo.Context) -> None:
    from .text_render import OUTLINE_OFFSETS_4, TextStyle, measure_text, render_text

    # Existing splattribution block (unchanged) — see album_overlay.py:381-403
    escaped = self._attrib_text.replace("&", "&amp;").replace("<", "&lt;")
    ...
    render_text(cr, style, x=0, y=-h - 5)

    # NEW: Bandcamp / Discogs CTA line, sourced from license catalog
    # (read from album-state.json + license-catalog/<artist-id>.yaml).
    # Only renders if the license catalog has the link AND the active
    # Programme has opted in `overlay.splattribution.purchase-cta`.
    cta = self._read_purchase_cta_text()
    if cta:
        cta_style = TextStyle(
            text=cta,
            font_description=f"{font_family} 10",
            color_rgba=(0.7, 0.9, 1.0, 0.95),
            outline_color_rgba=(0.0, 0.0, 0.0, 0.85),
            outline_offsets=OUTLINE_OFFSETS_4,
            max_width_px=SIZE,
            wrap="word_char",
            markup_mode=False,
        )
        render_text(cr, cta_style, x=0, y=-h - 5 + 18)

    # NEW: Programme mode badge in upper-right corner of the PiP region.
    badge = self._read_active_programme_mode_badge()
    if badge:
        badge_style = TextStyle(
            text=f"[{badge}]",
            font_description=f"{font_family} 12",
            color_rgba=self._badge_color_for_mode(badge),
            outline_color_rgba=(0.0, 0.0, 0.0, 0.85),
            outline_offsets=OUTLINE_OFFSETS_4,
            markup_mode=False,
        )
        render_text(cr, badge_style, x=SIZE - 30, y=-h + 3)
```

Where:
- `_read_purchase_cta_text()` reads `/dev/shm/hapax-compositor/album-license.json` (a sibling to `album-state.json`, written by a new `agents/license_resolver.py` daemon — see §4) and emits `Buy on Bandcamp` or `Buy on Discogs` formatted text. The actual hyperlink semantic depends on §3.4.
- `_read_active_programme_mode_badge()` reads `/dev/shm/hapax-programme/active.json` (a new path the programme planner writes) and returns the active vinyl-broadcast Programme's `mode_label` (`A`/`B`/`C`/`D`) or empty string if no vinyl-broadcast Programme is active.
- `_badge_color_for_mode()` returns mode-specific RGBA: A=warm-amber `(0.95, 0.7, 0.4, 1.0)`, B=glitch-magenta `(0.95, 0.4, 0.95, 1.0)`, C=calm-cyan `(0.4, 0.85, 1.0, 1.0)`, D=textural-violet `(0.7, 0.5, 0.95, 1.0)`. These align with Logos design language (`docs/logos-design-language.md` §3) without hard-coding hex into the overlay.

The operator-side monetization risk dot is rendered to a SEPARATE surface (`/dev/video43`, the operator-facing monitor mirror, not `/dev/video42` which feeds OBS/YouTube). This is the same kind of split as the existing operator-side mute indicator in waybar — viewer never sees it.

### §3.4 Bandcamp / Discogs link rendering on YouTube live

Per WebSearch on YouTube Live external link policy (`support.google.com/youtube/answer/9054257`), external clickable URLs require channel monetization eligibility (10,000 view threshold). The operator's channel posture (per parent §6.3) is already on a monetized DJ-stream path, so the eligibility threshold is achievable. The mechanics of how the link is presented:

- **Always-on description-block injection.** The license catalog's Bandcamp/Discogs URL for the active album is also written into the YouTube Live stream description via `agents/studio_compositor/youtube_description_syncer.py` (verified to exist). The operator authors a "Tracks playing tonight" header section in the description; the syncer appends per-track license metadata as the album rotates. Description URLs are clickable for viewers per standard YouTube Live UX.
- **On-overlay text only (not clickable).** YouTube Live overlay images / browser sources are NOT clickable on the player surface — viewer sees the URL as text but cannot click it. The overlay rendering above is therefore plain text (operator can also render a QR code variant via the `playground` skill if conversion-rate matters; deferred).
- **Chat pinned message at programme transition.** When the Programme transitions to a new vinyl track, the programme planner triggers a chat-bot post (via existing `agents/studio_compositor/youtube_turn_taking.py` infrastructure) pinning the Bandcamp link for the next 60 seconds. This is the highest-conversion link surface per parent §6.2.

Per `single_user` axiom, the splattribution overlay carries NO viewer data — no chat-author names, no viewer counts, no donor handles. Only operator-side state derived from operator-controlled sources is on the panel. This is enforced by the existing chat-reactor consent guardrail (`agents/studio_compositor/chat_reactor.py` per CLAUDE.md § Studio Compositor: "no per-author state, no persistence, no author in logs").

---

## §4 License / credit infrastructure

### §4.1 Where the per-track license metadata lives

Three candidate sources of truth, ordered by operator authority and reliability:

1. **Vault YAML registry** (`~/Documents/Personal/30-areas/legomena-live/license-catalog/<artist-slug>.yaml`) — operator-authored, operator-curated, source of truth for `monetization_risk` per track and the no-play list. Synced into RAG via `agents/obsidian_sync.py` (council CLAUDE.md § Obsidian Integration).
2. **MusicBrainz / Discogs / Spotify ISRC lookup** — populated automatically into the catalog the first time a new album is identified, then operator-confirmed before promotion to "active" status.
3. **The album-identifier daemon** (`scripts/album-identifier.py`) — populates `album-state.json` opportunistically; never authoritative for licensing.

The vault catalog format:

```yaml
# ~/Documents/Personal/30-areas/legomena-live/license-catalog/madlib.yaml
artist: Madlib
artist_id: madlib  # slug used in capability namespace
musicbrainz_artist_id: bd2cb87e-789c-4e36-9fd1-4d4a51f7f57d  # for cross-check
no_play_list: false  # whole-artist flag

# Default risk for any album by this artist not specifically listed below.
default_monetization_risk: medium
default_risk_reason: "Stones Throw catalog — strongly fingerprinted on YouTube"

# Default attribution links for the artist.
bandcamp_url: https://madlib.bandcamp.com
patreon_url: null

albums:
  - title: Madvillainy
    year: 2004
    label: Stones Throw
    musicbrainz_release_id: ...
    discogs_release_id: 25395
    monetization_risk: high  # operator's per-album override
    risk_reason: "Operator decision: artist publicly objected to sample-pack distribution"
    no_play_list: true  # honor IllMuzik-thread artist objection per parent §6.3
    purchase_url: https://madlib.bandcamp.com/album/madvillainy

  - title: Sound Ancestors
    year: 2021
    label: Madlib Invazion
    musicbrainz_release_id: ...
    discogs_release_id: 17256231
    monetization_risk: medium
    risk_reason: "Released through artist's own label; transformation-mode safe"
    no_play_list: false
    purchase_url: https://madlibinvazion.bandcamp.com/album/sound-ancestors

  - title: Beat Konducta Vol 1-2
    year: 2006
    label: Stones Throw
    discogs_release_id: 829340
    monetization_risk: medium
    no_play_list: false
    purchase_url: https://stonesthrow.com/store/madlib/beat-konducta
```

**Why YAML-in-vault, not JSON-in-/dev/shm.** The catalog is operator-curated, must persist across reboots, and must be reviewable in markdown form (the operator already reviews vault content as part of the daily/weekly cadence per `~/Documents/Personal/` PARA structure). Obsidian's frontmatter rendering makes the YAML readable. The vault sync agent (`agents/obsidian_sync.py`, 6h timer) propagates changes into RAG. The license-resolver daemon (new, §4.2) reads the YAML directly as cache, with an inotify watcher for hot-reload — the operator changing a `monetization_risk` value during a stream takes effect within seconds without daemon restart.

### §4.2 The license-resolver daemon

A new daemon, `agents/license_resolver.py`, sits between `album-identifier.py` and the studio compositor:

```
scripts/album-identifier.py
  → writes /dev/shm/hapax-compositor/album-state.json
       │
       ▼
NEW: agents/license_resolver/__main__.py
  - inotify watch on album-state.json
  - on change: read artist+title, look up in vault YAML catalog
  - if not in catalog: query MusicBrainz (ISRC + recording) to populate scaffold
  - write /dev/shm/hapax-compositor/album-license.json with:
      {
        "artist_id": "madlib",
        "monetization_risk": "high",
        "risk_reason": "...",
        "no_play_list": true,
        "bandcamp_url": "...",
        "discogs_url": "...",
        "needs_operator_review": false,
        "catalog_source": "vault" | "musicbrainz_scaffold" | "unknown"
      }
  - emits panic.album_no_play impingement if no_play_list==true (the
    operator already mounted a bad record; programme planner should
    respond by transitioning to Mode C or unmuting the bed).
       │
       ▼
agents/studio_compositor/album_overlay.py
  - reads album-license.json on mtime change
  - renders Bandcamp/Discogs CTA per §3.3
  - renders mode badge
```

The daemon's MusicBrainz scaffold-lookup is rate-limit-conscious: MusicBrainz allows 1 request/sec without authentication, plenty for an album-change cadence measured in minutes. Discogs requires OAuth-authenticated `60 req/min`; the daemon uses operator's personal Discogs token (stored via `pass`). Bandcamp does NOT have a public API as of 2026 (per WebSearch; Bandcamp shut down their public API and don't plan to reopen) — the catalog `bandcamp_url` MUST be hand-populated by the operator or generated heuristically (the daemon can construct `https://{artist-slug}.bandcamp.com` as a probe and verify it returns 200, but the operator must confirm before the URL is promoted to `catalog_source: vault`).

### §4.3 The no-play list

Per parent §6.4 and operator memory `feedback_hapax_authors_programmes` (the operator does NOT pre-author programme content but DOES author governance like the no-play list), the no-play list is operator-maintained at the per-album OR per-artist level via the YAML registry's `no_play_list: true` flag. The license-resolver daemon checks this on every album state change.

When `no_play_list: true` is detected:
1. Daemon writes `album-license.json` with `no_play_list: true`.
2. Daemon emits a `panic.album_no_play` impingement with `priority_floor: true` (so it bypasses normal recruitment scoring per `affordance_pipeline.py:453-458`).
3. Programme planner's response: trigger transition to Mode C (panic-mute crossfade); show operator-side notification via ntfy ("`{artist} — {title}` is on the no-play list — Mode C engaged").
4. The splattribution overlay shows the no-play indicator (operator-side monitor only) so the operator knows why the system swapped to bed.

### §4.4 Royalty-free / pre-cleared bed library for Mode C

Per parent §4 (Licensing options table) and the WebSearch on FMA, the candidate sources for the Mode C bed library:

| Source | License | Suitability for Mode C bed |
|---|---|---|
| Free Music Archive (CC-BY tagged) | Mostly CC-BY | Primary candidate; per-track attribution required (TASL: Title/Author/Source/License) |
| dig.ccmixter | CC-BY / CC-BY-SA | Good for ambient/electronic textures |
| YouTube Audio Library | Per-track YouTube-blanket | Cleanest legal posture — already pre-cleared by YouTube |
| Pixabay Music | Pixabay Content License (effectively CC0) | No attribution required, but quality varies |
| Bandcamp (CC-licensed releases) | Per-release CC | Operator-curated; must verify license per release |
| Internet Archive (Free Music Archive subset) | Various CC | Same as FMA |

**Storage and ingestion.** Bed library files live at `~/Music/legomena-bed/` (already-existing or to-be-created), with a sidecar `bed-catalog.yaml`:

```yaml
# ~/Music/legomena-bed/bed-catalog.yaml
sources:
  - file: fma/kosta-t/under-the-dome.mp3
    title: Under the Dome
    artist: Kosta T
    license: CC-BY-4.0
    source_url: https://freemusicarchive.org/music/Kosta_T/...
    attribution_text: "Kosta T — Under the Dome (CC-BY-4.0, FMA)"
    duration_s: 384
    bpm: null  # ambient
    energy_class: low

  - file: pixabay/lexin-music/calm.mp3
    title: Calm
    artist: Lexin Music
    license: pixabay-content-license
    attribution_text: "Lexin Music — Calm (Pixabay)"
    duration_s: 211
    energy_class: low
```

The `vinyl.bed.cc-by` capability is the umbrella registration; per-track instances are recruited based on the active Programme's energy + duration needs.

**Attribution emission for bed library tracks**: the splattribution overlay renders `attribution_text` verbatim while a bed track plays — which means the FMA TASL convention (Title/Author/Source/License) IS on screen as required for CC-BY compliance. The CTA line shows `Source: freemusicarchive.org/music/Kosta_T` to satisfy the "link back to source" CC-BY recommended practice (per WebSearch on Creative Commons Wiki).

---

## §5 Mode A deep dive

### §5.1 What makes Mode A defensible

Mode A is the **highest legal exposure** mode (parent §7.1). The legal floor for defensibility is documented in parent §6.3 and is a posture, not a technical defense. Programme-level enforcement of that posture:

| Defensibility prong | Implementation |
|---|---|
| Short duration (< 60s per track) | `max_dwell_in_dry_signal_s: 60.0` Programme field; `dwell_cap_reached` predicate in `success.abort_predicates` |
| Heavy attribution overlay | `capability_bias_positive: { overlay.splattribution.attribution-text: 4.0 }` |
| No monetization | Mode A is engaged during operator's consciously-non-monetized segments; operator handles monetization toggle separately via Stream Deck |
| Immediate transition-out | `success.abort_predicates: [dwell_cap_reached, content_id_warning_received, operator_panic_pressed]` |
| Channel posture as DJ-set/commentary | Channel description posture per parent §7.3 — static text on operator's About page, not a Programme concern |

### §5.2 The 60-second dwell cap

The cap is enforced by the **programme-monitor loop** (a new agent, `agents/programme_monitor.py`, ships in #164 plan Phase 4). The monitor polls every 10 seconds; each tick it computes:

```python
def check_mode_a_dwell_cap(prog: VinylBroadcastProgramme) -> bool:
    """Returns True if Mode A dry-signal dwell cap exceeded.

    Reads /dev/shm/hapax-compositor/album-state.json for the current
    track's start_timestamp. If the same track has been the active dry-
    signal source for > prog.max_dwell_in_dry_signal_s, the cap is hit.
    """
    if prog.mode_label != "A" or prog.max_dwell_in_dry_signal_s is None:
        return False
    state_file = Path("/dev/shm/hapax-compositor/album-state.json")
    if not state_file.exists():
        return False
    state = json.loads(state_file.read_text())
    track_start = state.get("track_start_timestamp", state.get("timestamp"))
    if track_start is None:
        return False
    elapsed = time.time() - track_start
    return elapsed > prog.max_dwell_in_dry_signal_s
```

When the predicate fires, the monitor writes `prog.status = ABORTED` and emits a `programme.transition_required` impingement with `next_programme_id: vinyl-broadcast-mode-b-turntablist`. The programme planner sequences the transition, including the entry/exit ritual choreography from §2.3.

### §5.3 Operator UX — Mode A awareness

Mode A's elevated risk demands operator awareness without distracting the operator mid-set. The operator-side affordances:

- **Splattribution mode badge** turns warm-amber (per §3.3 `_badge_color_for_mode("A")`).
- **Stream Deck key 7** (currently `studio.activity.override args: { activity: vinyl }` per `config/streamdeck.yaml:46-49`) gets a co-press behavior: pressing `key 7` while in Mode B/C/D programmes triggers `programme.transition: { to: vinyl-broadcast-mode-a-selector }`. The operator's mental model: "I want to play this next track minimally for the next minute, then go back."
- **Countdown ticker** in the operator-side waybar (NOT on broadcast) shows remaining dwell time when Mode A is active. A new waybar custom module reads `/dev/shm/hapax-programme/active.json` and shows `MODE A: 47s left` in warm-amber. (Adding this requires the timeout-wrap pattern per memory `project_zram_evicts_idle_guis` — never an unguarded external binary call from a waybar custom module.)
- **Auto-transition notification** via ntfy when Mode A times out: `MODE A → MODE B (dwell cap)`. Operator gets the notification on phone too via existing ntfy infrastructure.

### §5.4 Mode A and the recruitment threshold

A subtle interaction: the affordance pipeline applies `THRESHOLD = 0.05` (post-suppression) to filter survivors at `affordance_pipeline.py:466-467`. In SEEKING stance the threshold halves to 0.025. Mode A's strong negative biases on FX capabilities (`audio.fx.granular.evil-pet: 0.25`) push their combined scores below threshold UNLESS the impingement is very strongly aligned with FX-engagement. This is the desired behavior — the FX capabilities are not strictly excluded, but they require an unusually strong contextual reason to recruit during Mode A. If they DO recruit (e.g., the operator stomps a kill-switch macro during a particular passage), the Programme accommodates it without ABORT — that's the soft-prior axiom doing its work.

---

## §6 Mode C deep dive

### §6.1 Two sub-postures, one Programme

Per §2.3 Mode C, the `bed` (planned ambient) and `panic-mute` (emergency) sub-postures share one Programme envelope. Distinguishing field on the **Programme transition log entry** (NOT on the Programme itself):

```jsonl
# ~/hapax-state/programmes/transition-log.jsonl
{"timestamp": 1745234567.123, "from": "vinyl-broadcast-mode-b-turntablist", "to": "vinyl-broadcast-mode-c-bed-panic-mute", "trigger": "operator_stream_deck_press", "entered_via": "bed", "context": {"reason": "operator wants to talk over bed for 5 min"}}
{"timestamp": 1745236210.456, "from": "vinyl-broadcast-mode-b-turntablist", "to": "vinyl-broadcast-mode-c-bed-panic-mute", "trigger": "panic.content_id_warning", "entered_via": "panic", "context": {"warning_track": "DJ Krush — Final Home", "warning_received_at": 1745236208.901}}
```

The `entered_via` field drives the auto-release behavior: `bed` entries can auto-transition out at planned duration; `panic` entries require explicit operator release (no auto-resume to risky modes).

### §6.2 Bed library selection

When Mode C activates, the Mode C programme's `content.invited_capabilities` includes `vinyl.bed.cc-by` and `vinyl.bed.youtube-audio-library`. The recruitment pipeline scores the per-track instances against the impingement context. For a planned bed entry (operator wants to talk over ambient for 5 min), the impingement carries `energy_class: low` context, so the recruiter prefers low-energy tracks. For a panic entry, the impingement carries `panic: true` and `transition_speed: fast`, which up-weights tracks with shorter intros.

The bed track's playback engine is a **dedicated PipeWire sink** (`hapax-bed-sink`) that lives in `~/.config/pipewire/pipewire.conf.d/hapax-bed.conf`. The crossfade choreography at programme entry (`audio.crossfade.from_vinyl_to_bed_2s`) is implemented as a 2-second linear fade of the vinyl sink to -∞ dB combined with a 2-second fade-up of the bed sink from -∞ to operator's bed-target level (default -12 dBFS).

### §6.3 Panic-mute mechanics

The trigger surface for panic-mute:

1. **YouTube live Content ID warning detection.** Per parent §3.2, YouTube live-stream Content ID has graduated enforcement: warning → static-image replacement → stream termination. The warning surface is in YouTube Studio's live dashboard but is NOT exposed via a webhook or push API. Detection options:
   - **Polling**: a daemon polls the YouTube Live Streaming API's `liveBroadcasts` resource (1 req/sec budget) for status changes; this catches `liveStreamHealthStatus` transitions. NOT documented to surface Content ID warnings explicitly, but rate-of-issue reports (parent §9 open question 6) suggest there's a `liveStreamingDetails.boundStreamId` health field that goes degraded during enforcement actions.
   - **DOM-scraping the studio dashboard**: more reliable but fragile; uses Playwright in headless mode against `studio.youtube.com`. Operator-grade but fragile.
   - **Operator manual press**: the most reliable trigger surface — Stream Deck key dedicated to panic press (proposed: `key 12` since `key 11` is already `attention_bid.dismiss`). The operator sees the warning visually before the system can detect it via API.
   
   **Recommendation**: ship operator-press first (zero false-negative on operator-recognized warnings), add API polling as redundancy after operator press is in steady state. DOM-scraping deferred unless the API polling proves insufficient.

2. **`vinyl.crate.<artist>` `monetization_risk: high` recruitment attempt.** The MonetizationRiskGate (`shared/governance/monetization_safety.py:121-128`) blocks `high` capabilities unconditionally. But if the operator manually mounts a no-play-listed record, the album-identifier daemon's `panic.album_no_play` impingement (§4.3) triggers a panic-mute as a defensive move BEFORE the operator can hit the panic key.

3. **Operator panic press** via Stream Deck or MIDI Dispatch macro — single-button transition to Mode C with `entered_via: operator_panic`.

The panic-mute response sequence:

```
T+0    panic event (any source above) detected
T+0.1  programme planner: emit "programme.transition_required" impingement
T+0.2  programme planner: write Mode C programme to /dev/shm/hapax-programme/active.json
T+0.3  studio compositor: read active.json, observe transition
T+0.3  audio side: trigger audio.crossfade.from_vinyl_to_bed_2s
T+0.5  visual side: bed-mode entry choreography starts (substrate palette shift)
T+1.0  splattribution overlay updates: mode badge → calm-cyan [C]
T+2.0  audio crossfade complete; bed track playing at operator bed-target level
T+2.0  ntfy: "MODE C engaged (panic). Source: {trigger}"
T+2.0  optional: cut compositor to a pre-rendered "back in 30 seconds" video
       card (operator preference; defaults to false)
```

The "back in 30 seconds" card is an additional GStreamer element switching in via `interpipesrc.listen-to` (per CLAUDE.md § Studio Compositor's camera 24/7 epic — same hot-swap mechanism). The card is at `~/.local/share/legomena/back-in-30s.mp4`, pre-rendered by the operator.

### §6.4 Mode C exit

For `bed` entry: auto-transition at `planned_duration_s` (default 15 min). The programme planner schedules the next programme based on the show plan.

For `panic` entry: NO auto-transition. The exit ritual (`audio.crossfade.from_bed_to_silence_2s`) only fires when the operator explicitly presses the `programme.release_panic` Stream Deck key. The next Programme defaults to a Mode B re-entry (per parent §8.2: "Resume in MODE B (Turntablist) or MODE D (Granular wash), never back to MODE A"). Programme transitions FROM Mode C panic ALWAYS skip Mode A in the candidate set — encoded in the transition rules at the planner level, not in the Programme primitive itself.

---

## §7 MonetizationRiskGate integration + telemetry

### §7.1 Where the gate sits in the pipeline

`AffordancePipeline.select()` (`shared/affordance_pipeline.py:369-499`) runs filters in this order at present:

1. Interrupt-token short-circuit (`affordance_pipeline.py:375-401`)
2. Inhibition check (`affordance_pipeline.py:402-403`)
3. Embedding + retrieval (`affordance_pipeline.py:404-420`)
4. **Consent gate** (`affordance_pipeline.py:425`)
5. **Monetization-risk gate** (`affordance_pipeline.py:432-434`) — currently passes `programme=None` (Phase 1)
6. Score composition (`affordance_pipeline.py:438-452`)
7. Priority-floor split, suppression, threshold (`affordance_pipeline.py:453-468`)
8. Exploration noise (`affordance_pipeline.py:481-498`)

Phase 5 of demonet plan adds `programme: VinylBroadcastProgramme | None` parameter plumbing through to the gate call. This is a minimum-surface change — `select()` accepts an optional programme argument (default `None`), the call site in the recruitment loop reads the active programme from `/dev/shm/hapax-programme/active.json`, and the gate's existing implementation (`monetization_safety.py:107-150`) consumes the field unchanged.

The gate decision for a `medium`-risk capability with the active programme that has opted it in:

```python
# shared/governance/monetization_safety.py:128-145
if risk == "medium":
    opted_in = False
    if programme is not None:
        opt_ins = getattr(programme, "monetization_opt_ins", None)
        if opt_ins is not None and name in opt_ins:
            opted_in = True
    if not opted_in:
        return RiskAssessment(
            allowed=False,
            risk=risk,
            reason=f"{name}: medium-risk capability requires programme opt-in".rstrip(),
        )
    return RiskAssessment(
        allowed=True,
        risk=risk,
        reason=f"{name}: medium-risk capability opted in by active programme",
    )
```

### §7.2 Mode-Programme-mismatch detection

If the operator triggers Mode A but the recruitment system is otherwise about to recruit a `medium`-risk track, the gate filters it. The user-facing surface:

- The recruitment pipeline returns no candidates for that impingement (gate filtered all `medium`+).
- The album-identifier daemon's most-recent identification still shows on the splattribution panel — but the actual audio source switches. If the operator has the bed library on standby, recruitment falls through to `vinyl.bed.cc-by` (which Mode A opts in).
- Operator-side ntfy fires: `Track-X not available in Mode A (medium risk). Bed engaged.`
- Splattribution overlay shows the bed track's attribution, NOT the vinyl that was on the platter. This is the correct behavior — the broadcast attribution must always match what the broadcast is hearing.

The mismatch is NOT a panic — it's a graceful degradation. The operator can then either: (a) pull the record off and continue with bed, (b) press the Stream Deck Mode B key to switch to Turntablist, where the same track DOES recruit (`vinyl.crate.transformed` opts in `medium`).

### §7.3 Telemetry — Prometheus counters

New Prometheus metrics on `127.0.0.1:9482` (the existing studio compositor metrics server per CLAUDE.md § Studio Compositor):

```python
# Per-mode dwell time
hapax_programme_mode_seconds_total{mode="A|B|C|D"}

# Programme transition events
hapax_programme_transitions_total{from_mode, to_mode, trigger}

# Gate filter events
hapax_monetization_gate_filtered_total{risk, capability_name, programme_mode}
hapax_monetization_gate_passed_total{risk, capability_name, programme_mode}

# Attribution display events
hapax_splattribution_displayed_total{artist_id, license_source}

# Panic events
hapax_programme_panic_total{trigger, source_track_artist_id}
```

These metrics feed an existing Grafana dashboard pattern (CLAUDE.md § Bayesian Presence Detection mentions `localhost:3001/d/reverie-predictions/`). New panel proposals:

- **Current Mode** panel: large status indicator showing active mode A/B/C/D with mode-color background.
- **Time-in-current-mode** panel: countdown for time-capped modes (Mode A primarily).
- **Monetization-risk distribution** panel: stacked bar chart over time showing distribution of `monetization_gate_passed` events by risk level. Useful for retrospective: "how much of last night's stream was `low` risk vs `medium` opt-in?"
- **Panic event log** panel: tabular view of panic transitions with timestamps, trigger source, source track.
- **Bandcamp click-through** panel: requires YouTube Live API integration to pull description-link click data; deferred until basic flow is stable.

### §7.4 Post-stream forensics

A new agent, `agents/post_stream_forensics.py` (timer-based, 1h after stream end), aggregates the JSONL audit logs:

- `~/hapax-state/programmes/transition-log.jsonl` — every Programme transition
- `~/hapax-state/programmes/egress-audit/<date>/<hour>.jsonl` — per-render egress decisions (demonet plan Phase 6 wires this)
- `~/hapax-state/programmes/gate-decisions/<date>.jsonl` — per-recruitment gate decisions

Output: a markdown report at `~/Documents/Personal/30-areas/legomena-live/post-stream/<stream-date>.md` with:

- Time-in-mode breakdown
- Tracks played per mode
- Tracks BLOCKED by gate (with risk class + reason)
- Panic events: trigger, response time, recovery
- License-catalog gaps: tracks identified during stream that have no catalog entry yet (operator action item: review and populate)

Per `single_user` axiom, this report is operator-only — no viewer data, no chat content.

---

## §8 Operator UX — mode switching

### §8.1 Mode-switch trigger surfaces

The four mode-switch triggers, in order of immediate availability:

1. **Stream Deck press** — primary surface. New keys appended to `config/streamdeck.yaml`:
   ```yaml
   - key: 12
     command: programme.transition
     args: { to: vinyl-broadcast-mode-a-selector }
     label: Mode A
   - key: 13
     command: programme.transition
     args: { to: vinyl-broadcast-mode-b-turntablist }
     label: Mode B
   - key: 14
     command: programme.transition
     args: { to: vinyl-broadcast-mode-c-bed-panic-mute }
     label: Mode C / Panic
   - key: 15
     command: programme.transition
     args: { to: vinyl-broadcast-mode-d-granular-wash }
     label: Mode D
   ```
   The `programme.transition` command is a new entry in the command registry (`hapax-logos/src/lib/commands/`, probably extending an existing `studio.ts` or a new `programme.ts`). The Tauri WebSocket relay (`hapax-logos/src-tauri/src/commands/relay.rs`) already routes commands to the daemon side via `ws://127.0.0.1:8052/ws/commands`.

2. **MIDI Dispatch macro** — operator's Erica Synths MIDI Dispatch (per parent §7) already runs the audio routing macros for Modes A/B/C/D. Wiring the macros to ALSO emit a `programme.transition` impingement requires adding a MIDI listener on the daimonion side that translates specific MIDI Dispatch CC values to command-registry calls. The daimonion already has MIDI infrastructure (`agents/hapax_daimonion/backends/midi_clock.py` per the splattribution spec), so adding CC handlers is a small extension.

3. **Voice command** — `hey hapax, mode b`. The voice command path goes: STT → CPAL → impingement → AffordancePipeline.select → `programme.transition` capability recruitment. The capability registration includes a `voice_intent: ["mode a", "mode b", "switch to selector", ...]` field that the impingement matcher consults. Per `feedback_no_expert_system_rules`, this is NOT a hardcoded keyword router — the matching is via embedding similarity, with the voice intent strings serving as additional similarity-pull descriptions. Latency target: < 800ms from utterance end to mode change visible on splattribution.

4. **Time-based auto-transition** — driven by the programme planner per `success.completion_predicates`. This is the only NON-operator-initiated transition surface. The planner is Hapax-authored per `feedback_hapax_authors_programmes`.

### §8.2 On-screen mode indicator

The splattribution panel already carries the mode badge (§3.3). One on-broadcast indicator. No additional viewer-facing UI for mode awareness — the badge serves both audiences (operator-side: small, glanceable; viewer-side: same badge, present without distraction).

Operator-side ONLY (mirror monitor `/dev/video43`): the mode countdown ticker (Mode A only, §5.3) and the operator-side risk dot (§3.2).

### §8.3 Programme stacking (open question)

The Programme primitive permits multiple Programmes to be active simultaneously (multiple `parent_show_id` parents per `programme.py:266`). For vinyl-broadcast, **only one vinyl-broadcast-mode Programme is active at a time** — the planner enforces this invariant. But other Programmes (e.g., a `studio-work-block` programme parented to the same show) CAN coexist with a vinyl-broadcast-mode programme. The two compose:

- `studio-work-block` provides studio-tier biases (camera focus on workstation, ward cap=4, etc.).
- `vinyl-broadcast-mode-b` provides audio-tier biases (FX engagement, mode badge).

The bias multipliers from both Programmes multiply when scoring a capability that appears in both envelopes (`Programme.bias_multiplier(name)` in `programme.py:302-304`). This is the soft-prior composition the architectural axiom guarantees.

---

## §9 Anti-anthropomorphization invariants for this surface

Per memory `project_hardm_anti_anthropomorphization` and CLAUDE.md `management_governance` axiom:

1. **Splattribution renders factual data**, not LLM narration. The current Pango text at `scripts/album-identifier.py:660-674` is already correct: `{model} says: "{artist} — {title}"` — model attribution is to the LLM, not to "Hapax". The `(LOL)` parenthetical is operator-authored commentary on dumb-LLM-confidence; per `feedback_hapax_authors_programmes`, this is an operator authoring choice, not a Hapax persona artifact.

2. **Mode badge is a label, not an emotion**. `[A]` not `Hapax is in selector mode`, `[B]` not `Hapax is feeling turntable-y`. The mode-color is design-language (Logos design language §3) not affective signal. Same architectural pattern as HARDM grid persona (memory `project_hardm_anti_anthropomorphization`).

3. **Programme-transition ntfy notifications are factual**: `MODE A → MODE B (dwell cap)`, `MODE C engaged (panic)`. Not `Hapax decided to transition` or `Hapax is feeling the need for granular`.

4. **Mode-A countdown ticker** says `MODE A: 47s left`, not `Hapax wants to leave Mode A in 47s`.

5. **Post-stream forensics report** uses scientific register per memory `feedback_scientific_register`. Tables, counters, transition logs — no narrative reconstruction. The operator can author narrative reflection in the vault separately.

6. **License-catalog YAML** uses neutral fields: `monetization_risk: medium` not `risky_for_hapax`, `risk_reason` is a factual statement not an explanation in the model's voice.

7. **No-play-list ntfy** says `{artist} — {title} is on the no-play list. Mode C engaged.` — factual statement of the rule and the resulting action; no apology, no anthropomorphic framing.

These are all enforceable structural choices, not stylistic preferences. The factory pattern for splattribution text (the f-string template at `album-identifier.py:660-674`) is the structural enforcement — there is no LLM-generation step for the on-screen text. The mode badge color is a CSS-custom-property lookup (per Logos design language §3 governance), not a per-tick LLM emit.

---

## §10 Open questions + integration risks

### §10.1 Operator-input-required (blocking)

1. **Mode A dwell cap**. Default proposed: 60 seconds per parent §7.1. Operator may want shorter (30s, more conservative) or context-dependent (60s for first-listen tracks, 30s for already-played-this-stream). Specifying the cap as a Programme-level constant is the simplest model; making it dynamic is a Phase-2 extension.

2. **Programme transition during active recruitment**. Currently recruitment runs at variable cadence (per-impingement). If the operator presses Mode B during a Mode A recruitment cycle, what happens to the in-flight recruited capability? Proposal: in-flight capabilities complete their current emission; the next recruitment cycle sees the new Programme. Clean but introduces a brief mode-mismatch window (typically < 1s).

3. **Mode-A → Mode-A** retrigger. If operator presses Mode A while already in Mode A, is the dwell cap reset? Default proposal: yes, reset (treat re-press as "I want another minute on this track"). Could be argued either way.

4. **Bed-library curation cadence**. Operator must populate `~/Music/legomena-bed/bed-catalog.yaml` with at least 30 minutes of per-track CC-licensed material before Mode C is functional. Estimate: 4-6h of operator time over a weekend to curate + tag. The license-resolver daemon can scaffold the YAML from MusicBrainz lookup; operator must verify CC license per track.

5. **Discogs API token**. Operator must register a Discogs OAuth app and store the consumer key/secret via `pass`. Trivial but required for the license-resolver to populate non-Bandcamp links automatically.

### §10.2 Architectural risks

1. **`monetization_opt_ins` is the only `Programme` field with deny/allow semantics**. The architectural axiom of `Programme` is soft-priors-only; this field is a deliberate exception, justified by the demonet plan Phase 1 + Phase 5 design as governance-axiom-tier (sibling to consent). Risk: future Programme fields might creep toward similar deny/allow semantics, eroding the axiom. Mitigation: `monetization_opt_ins` lives in a separate `VinylBroadcastProgramme` subclass-or-extension rather than the base `Programme`, so future Programme authors don't accidentally pattern-match on the exception.

2. **`vinyl.crate.<artist>` capability proliferation**. Each artist with vinyl gets two capabilities (`.dry`, `.transformed`); a 200-album collection produces ~400 capabilities. The Qdrant `affordances` collection currently has ~31 capabilities (per CLAUDE.md § Unified Semantic Recruitment); 400 is well within capacity but increases recruitment-pipeline scoring cost. Mitigation: consider per-artist umbrella capabilities (`vinyl.crate.<artist>`) with track-level instance metadata (per the Rosch three-level structure — Domain → Affordance → Instance per CLAUDE.md). The umbrella registers once; the instances live in the catalog metadata.

3. **License-resolver daemon as new failure surface**. Adds an inotify-driven daemon between album-identifier and album-overlay. Failure modes: catalog file corrupt, MusicBrainz timeout, /dev/shm filling. Mitigation: fail-safe per `feedback_grounding_exhaustive`. If `album-license.json` is missing or stale, the album-overlay degrades to today's behavior (no CTA, no mode badge); the splattribution still renders. The Programme system continues to gate on per-capability `monetization_risk`, which is read at capability registration time, not from the live license-resolver state.

4. **Interaction with #143 (IR vinyl cadence)**. Mode A's dwell cap is measured per *track*, requiring track-change detection. Currently track-change is via ACRCloud-equivalent + LLM identification (`scripts/album-identifier.py:393-514`); cadence is on the order of minutes. If track-change detection lags, dwell-cap enforcement lags. Mitigation: the cap is conservative (60s) and the worst-case lag is ~15s (the longer cooldown_until window in album-identifier on identification failure at line 814). Combined worst case: 75s in dry signal. Acceptable risk; not mode-A-defeating.

5. **YouTube Live Content ID warning detection latency**. As noted in §6.3, the API does not surface explicit warning events. Operator-press is the reliable trigger but introduces operator-reaction latency (typical: 1-3s from warning visible to press). During that window, a few seconds of risky audio reaches viewers. Per parent §8.2, this is acceptable: a single warning is recoverable, the catastrophic failure is the third strike (channel termination), so single-event response latency is not the load-bearing risk.

6. **Bandcamp lacks public API**. Per WebSearch, Bandcamp shut down their public API and don't plan to reopen. The license-resolver's Bandcamp integration is heuristic (probe `https://{slug}.bandcamp.com`, check 200) plus operator-confirmation. Future-resilience: the catalog YAML is the source of truth, so even if Bandcamp's URL scheme changes, operator-curated `purchase_url` values continue to work.

### §10.3 Implementation sequencing

Recommended phase ordering (depending on demonet plan #165 phase order):

1. **Ship the four Programme YAML files** to `config/programmes/vinyl-broadcast/` (this dispatch's deliverable).
2. **Wire `Programme.monetization_opt_ins` field** as part of demonet plan Phase 5.
3. **Ship license-resolver daemon scaffold** (read vault catalog only; no MusicBrainz lookup yet).
4. **Extend album_overlay.py** with CTA + mode badge rendering (§3.3).
5. **Add Stream Deck mode keys** (`config/streamdeck.yaml`).
6. **Curate operator's vault license catalog** (operator action; rolling).
7. **Add programme-monitor loop** with Mode A dwell cap enforcement.
8. **Wire panic-mute** with Stream Deck operator-press first; add YouTube API polling later.
9. **Bed library catalog + crossfade infrastructure** for Mode C.
10. **Telemetry + Grafana dashboard panels** (§7.3).
11. **Post-stream forensics report** (§7.4).
12. **Voice command path** (§8.1 #3, lowest priority — Stream Deck covers the operator's mid-set needs).

---

## §11 Sources + citations

### Hapax codebase references

- **Programme primitive** — `shared/programme.py:1-313`. Soft-prior envelope, validators reject zero multipliers (`programme.py:115-125`), `bias_multiplier` shortcut (`programme.py:302-304`), `expands_candidate_set` self-check (`programme.py:306-308`).
- **MonetizationRiskGate** — `shared/governance/monetization_safety.py:1-185`. High blocked unconditionally (`monetization_safety.py:121-128`), medium requires opt-in (`monetization_safety.py:128-145`), low/none pass (`monetization_safety.py:146-150`). Module singleton `GATE` (`monetization_safety.py:163`).
- **Affordance primitive** — `shared/affordance.py:1-115`. `OperationalProperties.monetization_risk` field (`affordance.py:33-34`), `risk_reason` (`affordance.py:34`), `MonetizationRisk` literal (`affordance.py:12`).
- **Affordance pipeline gate integration** — `shared/affordance_pipeline.py:425` (consent gate), `shared/affordance_pipeline.py:432-434` (monet gate Phase 1 with `programme=None`), `THRESHOLD = 0.05` (`affordance_pipeline.py:29`), priority floor handling (`affordance_pipeline.py:453-458`).
- **Album identifier daemon** — `scripts/album-identifier.py:1-819`. Vision identification via Gemini through LiteLLM (`album-identifier.py:393-514`), audio capture with vinyl-rate restoration (`album-identifier.py:295-391`), state file writes (`album-identifier.py:652-696`), persistent log (`album-identifier.py:699-717`).
- **Album overlay rendering** — `agents/studio_compositor/album_overlay.py:1-423`. `AlbumOverlayCairoSource` (`album_overlay.py:236-417`), 2026-04-20 unconditional render fix (`album_overlay.py:264-274`), Pango render via `text_render` (`album_overlay.py:381-417`), `_pip_fx_package` palette quantize (`album_overlay.py:164-233`).
- **Splattribution spec (#127)** — `docs/superpowers/specs/2026-04-18-splattribution-design.md`. `vinyl_playing` derived signal (§4), consumer gating list (§6), opens downstream paths when False (§7).
- **Demonet research** — `docs/research/2026-04-19-demonetization-safety-design.md`. Three concentric rings (§4), capability-level filter (Ring 1) at `AffordancePipeline.select()`.
- **Demonet plan** — `docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md`. Operator directive (verbatim, 2026-04-19, §0), Phase 1 (capability filter, ships), Phase 5 (Programme.monetization_opt_ins field).
- **Programme research** — `docs/research/2026-04-19-content-programming-layer-design.md`. Meso-tier framing (§1.1), 2-hour example (§1.2).
- **Programme plan** — `docs/superpowers/plans/2026-04-20-programme-layer-plan.md` Phase 1 (which the just-shipped `programme.py` implements).
- **Parent broadcast-safety research** — `docs/research/2026-04-20-vinyl-collection-livestream-broadcast-safety.md`. Routing modes A/B/C/D (§7.1), pre-stream checklist (§8.1), Content ID warning response (§8.2).
- **Affordance pipeline (consent gate precedent)** — `shared/affordance_pipeline.py:313-362` `_consent_allows`. Fail-closed pattern referenced throughout demonet design.
- **Studio compositor audio chain** — `agents/studio_compositor/twitch_director.py:1-80` (vinyl_playing gate consumers), `agents/studio_compositor/album_overlay.py:305-318` (vinyl_playing probe pattern).
- **Command registry (Stream Deck wiring)** — `config/streamdeck.yaml:1-65`, `hapax-logos/src/lib/commandRegistry.ts`, `hapax-logos/src/lib/commands/{data,detection,nav,overlay,sequences,split,studio,terrain}.ts`, `hapax-logos/src-tauri/src/commands/relay.rs`. WebSocket on `ws://127.0.0.1:8052/ws/commands` per CLAUDE.md § Command Registry.
- **YouTube Live API integration** — `agents/studio_compositor/youtube_description.py`, `agents/studio_compositor/youtube_description_syncer.py`, `agents/studio_compositor/youtube_turn_taking.py`. Existing infrastructure for description-block and chat updates.
- **Studio compositor model** — `shared/compositor_model.py` Pydantic Source/Surface/Assignment/Layout. Integration site for the bed-mode video card hot-swap.
- **Vault Obsidian sync** — `agents/obsidian_sync.py` (per CLAUDE.md § Obsidian Integration); 6h timer to RAG, primary cadence for catalog YAML changes.
- **Anti-personification linter (sibling governance pattern)** — `scripts/lint_personification.py` per demonet design (§3.1, build-time gate).

### External APIs and policies

- [Discogs API documentation](https://www.discogs.com/developers) — 60 req/min authenticated, 25 req/min unauthenticated, rate-limit headers exposed; OAuth required for search endpoint as of August 15.
- [MusicBrainz API documentation](https://musicbrainz.org/doc/MusicBrainz_API) — 1 req/sec without auth, ISRC lookup endpoint supported.
- [MusicBrainz ISRC documentation](https://musicbrainz.org/doc/ISRC) — ISO 3901:2001, IFPI standard, identifies recordings (not songs).
- [MusicBrainz Recording Search](https://musicbrainz.org/doc/MusicBrainz_API/Search/RecordingSearch) — ISRCs supported as recording-search field.
- [musicbrainzngs Python library](https://python-musicbrainzngs.readthedocs.io/en/v0.5/api/) — `search_recordings_by_isrc` returns `recording-list`.
- [Bandcamp API status](https://bandcamp.com/developer) — Public API discontinued; no plans to reopen.
- [bandcamp-scraper (community alternative)](https://github.com/scriptkittie/bandcamp-api) — Wrapper around Bandcamp's internal undocumented JSON.
- [Free Music Archive License Guide](https://freemusicarchive.org/License_Guide) — Most CC licenses; per-track artist-selected.
- [Free Music Archive FAQ](https://freemusicarchive.org/faq/) — FMA does not own copyright; cannot license; artists upload + select CC license.
- [Creative Commons recommended attribution practices](https://wiki.creativecommons.org/wiki/Recommended_practices_for_attribution) — TASL: Title/Author/Source/License, link-back to source recommended.
- [YouTube external links policy](https://support.google.com/youtube/answer/9054257) — Includes URLs in overlays/images; policy applies to live streams.
- [YouTube Live monetization](https://support.google.com/youtube/answer/7385599) — Monetization eligibility required for external links; 10K-view threshold for YouTube Partner Program.
- [YouTube Live copyright issues (Content ID warning flow)](https://support.google.com/youtube/answer/3367684) — Warning → static-image → termination escalation referenced in parent §3.2.
- [YouTube counter-notification](https://support.google.com/youtube/answer/2807684) — Per parent §2.7.

### Anchoring memory references

- `feedback_no_expert_system_rules` — Behavior emerges from impingement → recruitment → role → persona. Programme primitive's strict soft-priors-only validation enforces this.
- `project_programmes_enable_grounding` — Programmes EXPAND grounding opportunities; never replace. The four mode YAMLs are biased priors, not capability-set filters (except `monetization_opt_ins`, the deliberate governance exception).
- `feedback_hapax_authors_programmes` — Operator does NOT pre-author programme content. The four mode YAMLs are envelope templates; per-stream programme INSTANCES are Hapax-authored. Operator authors the catalog (no-play list, license metadata) — governance, not content.
- `project_hardm_anti_anthropomorphization` — Mode badge is a label not a feeling; splattribution renders facts not narration; transition ntfys are statements not anthropomorphic framing.
- `feedback_grounding_exhaustive` — License-resolver fail-safe degrades to today's overlay behavior; nothing is "ungrounded" — the catalog is the grounding source for licensing decisions.
- `feedback_scientific_register` — Post-stream forensics use neutral tabular register.
- `single_user` — No viewer data on overlay; operator-side affordances are mirror-monitor only; license catalog is operator-curated.
- `interpersonal_transparency` — Splattribution attributes the LLM identifier (`{model} says: ...`), not Hapax. Programme transition log is operator-only.
- `management_governance` — License catalog and no-play list are operator-authored governance; the gate enforces, the operator decides.
