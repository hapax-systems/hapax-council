# Spectacle Architecture Contract - Design Spec

**Status:** contract seed for `spectacle-architecture-contract`  
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/spectacle-architecture-contract.md`  
**Date:** 2026-04-30  
**Scope:** composition roles, surface modes, programme/director affordances,
viewer-facing truth policy, family-specific contracts, and child implementation
split for existing spectacle systems.  
**Non-scope:** compositor rewrites, shader implementation, YouTube writes,
public fanout implementation, new camera hardware, Re-Splay hardware install,
or replacement of HOMAGE, Reverie, scrim, captions, metadata, or mobile
substream owners.

## Purpose

The livestream is a research vehicle suitcase. Its visual system cannot be a
pile of panels that happen to render at the same time. HOMAGE, scrim, Reverie,
parallax, ward choreography, GEM, multi-camera, Re-Splay, captions, overlay
zones, metadata, status, and mobile variants need one composition contract so
the stream can become larger, stranger, and more controllable without making
false public claims.

This contract consumes the existing substrate, lane, director, scrim, and
public-event contracts. It does not create a second source of truth. It defines
how evidence-bearing lanes become viewer-facing spectacle.

## Inputs Consumed

- `/home/hapax/Documents/Personal/20-projects/hapax-research/specs/2026-04-28-livestream-research-vehicle-suitcase-parent-spec.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/plans/2026-04-28-livestream-suitcase-wsjf-workload.md`
- `docs/superpowers/specs/2026-04-28-livestream-substrate-registry-design.md`
- `docs/superpowers/specs/2026-04-28-spectacle-control-plane-design.md`
- `docs/superpowers/specs/2026-04-28-research-vehicle-public-event-contract-design.md`
- `docs/superpowers/specs/2026-04-29-director-substrate-control-plane-design.md`
- `/home/hapax/Documents/Personal/20-projects/hapax-research/specs/2026-04-29-scrim-programme-director-behavior-contract.md`
- `docs/superpowers/specs/2026-04-29-scrim-state-envelope-design.md`
- `docs/superpowers/specs/2026-04-23-video-container-parallax-homage-spec.md`
- `docs/superpowers/specs/2026-04-20-homage-ward-umbrella-design.md`
- `docs/research/2026-04-19-gem-ward-design.md`
- Active/closed task anchors named in this packet, especially
  `homage-live-rehearsal-signoff-reconcile`,
  `m8-re-splay-operator-install-and-smoke`,
  `re-splay-polyend-downstream-design`,
  `re-splay-steam-deck-downstream-gate`, and
  `mobile-livestream-substream-implementation`.

## Thesis

Spectacle is not garnish after safety. The truth spine exists so the spectacle
spine can carry more aesthetic force.

The corrected architecture is:

1. `ContentSubstrate` states what carriers exist and what they may claim.
2. `SpectacleLaneState` states which carriers can be composed as lanes.
3. `DirectorControlMove` states what was attempted, applied, blocked, or held.
4. `ScrimStateEnvelope` states how the constant viewing medium may express the
   programme/director/WCS posture.
5. This contract states how surfaces compose into a viewer-facing read.

The visual output may be intense, quiet, imbricated, multi-spectacle, and
dynamic. It may not imply unavailable producers, missing hardware, private
controls, unsafe audio, unverified public egress, uncleared rights, or absent
public-event evidence.

## Composition Roles

Every viewer-facing surface must declare one or more roles. "Visible" is not a
role.

| Role | Contract |
|---|---|
| `ground` | The default visual field that gives the stream continuity. Reverie is the normative ground. |
| `medium` | The substance through which other surfaces appear. Scrim is the constant medium and WCS expression surface. |
| `focus_object` | The primary object of attention for a bounded programme moment. Cameras, HOMAGE wards, GEM, Re-Splay, research cards, and archive frames can become focus objects when evidence permits. |
| `ward` | A named HOMAGE/GEM/status surface with recognizability invariants, acceptance tests, and choreographic state. |
| `instrument` | A hardware or software source treated as a live instrument, such as Re-Splay M8, Polyend, Steam Deck, or music provenance surfaces. |
| `translation` | A surface that translates programme state into public or archive form, such as captions, metadata, cuepoints, chapters, or status posts. |
| `annotation` | A viewer-facing explanation layer, such as research markers, overlay zones, status chrome, blocked reasons, or criteria surfaces. |
| `witness` | A camera, archive frame, health row, or public-event reference that proves what happened. |
| `variant` | A deliberate aspect, device, or aperture variant, such as mobile 9:16 composition. |

One surface may have several roles, but only one primary role in a given
programme envelope. A caption strip, for example, is normally `translation`;
during a caption-quality audit it may become `focus_object`.

## Surface Modes

Programme and director control must express surface posture through bounded
modes, not ad hoc visual intensity.

| Mode | Meaning | Minimum evidence |
|---|---|---|
| `foregrounded` | Surface is the primary read. | Mounted lane, fresh renderability evidence, safe claim policy for the current public/private mode. |
| `backgrounded` | Surface remains present but subordinate. | Known lane or substrate plus fallback. |
| `held` | Current posture intentionally persists for a TTL and reason. | Target lane/substrate, `DirectorControlMove`, and hold reason. |
| `transitional` | Surface bridges from one known state/role to another. | From/to refs or dry-run fallback reason. |
| `intense` | Salience, density, motion, symbolic weight, or texture increases. | Mounted safe target plus health bounds; no blocked/degraded public intensification. |
| `quiet` | Salience, density, motion, speech, or churn decreases without disappearing. | Target and reason; valid for listening, evidence reading, correction, or recovery. |
| `suppressed` | Output is removed, muted, neutralized, or withheld. | Risk/programme reason and audit record. Suppression must not hide blockers. |
| `stabilized` | Churn, refraction, parallax, text turnover, or lane switching is reduced. | Always preferred for uncertain or recovering mounted surfaces. |
| `dry_run` | Surface can be rehearsed, described, or shown privately without public claim. | Explicit unavailable/dry-run reason. |
| `blocked` | Surface cannot be used in the requested role. | Blocking ref and safe fallback. |

Missing evidence defaults to `dry_run`, `blocked`, `suppressed`, or
`stabilized`. It never defaults to `foregrounded` or `intense`.

## Directorial Affordance Matrix

This matrix is the minimum vocabulary exposed to director/programme adapters.
Runtime adapters may filter verbs further by lifecycle state, evidence,
freshness, risk, and public/private mode.

| Family | Primary roles | Director affordances | Fallback when unavailable |
|---|---|---|---|
| HOMAGE ward system | `ward`, `focus_object`, `annotation` | `foreground`, `background`, `hold`, `suppress`, `transition`, `crossfade`, `intensify`, `stabilize`, `route_attention`, `mark_boundary` | Degraded/dry-run badge tied to rehearsal, contrast, recognizability, or OQ-02 evidence. |
| Scrim | `medium`, `annotation` | `hold`, `transition`, `crossfade`, `intensify`, `stabilize`, `route_attention`, `mark_boundary`; `foreground` only for focus regions, not the scrim itself | `neutral_hold` or `minimum_density`; public claim false. |
| Reverie substrate | `ground`, `ward`, `focus_object` | `background`, `hold`, `suppress` as dampen, `transition`, `intensify`, `stabilize`, `route_attention` | Keep ground quiet, or fallback to last safe visual ground. |
| Parallax/depth | `medium`, `attention`, `transition` | `transition`, `crossfade`, `intensify`, `stabilize`, `route_attention`, `mark_boundary` | Zero or low-amplitude stabilized depth. |
| Ward choreography | `ward`, `transition`, `attention` | All ten control-plane verbs, filtered by ward state and lane evidence | No-op with target/reason, or mass-stabilize when safety requires. |
| GEM mural | `ward`, `focus_object`, `annotation` | `foreground`, `background`, `hold`, `suppress`, `transition`, `intensify`, `stabilize`, `mark_boundary` | Decay to ambient fill; never substitute captions or status. |
| Multi-camera | `witness`, `focus_object`, `ground` | `foreground`, `background`, `hold`, `suppress`, `transition`, `crossfade`, `stabilize`, `route_attention` | Suppress degraded feed, hold last safe scene, or switch to neutral ground. |
| Re-Splay devices | `instrument`, `focus_object`, `translation` | `foreground`, `background`, `hold`, `suppress`, `route_attention`, `mark_boundary` only after smoke; blocked/no-op before smoke | Explicit blocked/no-op reason tied to hardware/capture/audio policy. |
| Captions | `translation`, `annotation` | `foreground` for caption audits, `background`, `hold`, `suppress`, `stabilize`, `mark_boundary` | Suppress or dry-run when freshness/redaction/egress evidence is stale. |
| Overlay zones and research markers | `annotation`, `focus_object`, `translation` | `foreground`, `background`, `hold`, `suppress`, `transition`, `stabilize`, `mark_boundary` | Hide or hold with event/provenance missing reason. |
| Metadata and status lanes | `translation`, `annotation`, `witness` | `foreground` when status is the content, `background`, `hold`, `suppress`, `stabilize`, `mark_boundary` | Report private/dry-run/degraded/blocked/archive-only status explicitly. |
| Mobile/aspect variants | `variant`, `witness`, `translation` | `foreground`, `background`, `hold`, `suppress`, `transition`, `stabilize`, `route_attention` within the target aspect | Fall back to desktop-safe read or unavailable companion/page reason. |

## Family Contracts

### HOMAGE Ward System

Primary roles: `ward`, `focus_object`, `annotation`.

HOMAGE carries the symbolic and status grammar of the stream. Its wards are
allowed to be visually assertive, but every enhancement remains bound to ward
recognizability, OQ-02, anti-anthropomorphization, and live rehearsal evidence.

Composition obligations:

- `homage_ward_system` and `ward_contrast` remain degraded until rehearsal,
  contrast, and legibility evidence are explicit.
- HOMAGE wards foreground only as named lanes with role, reason, and TTL.
- A ward may render telemetry only when the telemetry itself is the intended
  spectacle and the ward keeps its label, scale, and acceptance test.
- Broad HOMAGE umbrellas stay closed. Follow-up work must be focused adapters
  or smoke tasks, not a new all-HOMAGE rewrite.

### Scrim

Primary roles: `medium`, `annotation`, `witness` for posture only.

The scrim is always present and acts as a WCS expression surface. It can make
programme posture, director movement, blocked reasons, refusal, correction, and
conversion cues visually legible. It cannot grant truth, safety, monetization,
rights, consent, or public-live status.

Composition obligations:

- Scrim gestures derive from `ScrimStateEnvelope`, `DirectorControlMove`,
  programme boundaries, WCS snapshot refs, and health refs.
- Stale or missing scrim state falls closed to `neutral_hold` or
  `minimum_density`.
- Audio may modulate atmosphere, but no FFT bars, waveform register, or
  beat-synced iconography may appear.
- Scrim public posture cannot imply private controls, unavailable Re-Splay
  devices, dormant captions, or platform writes.

### Reverie Substrate

Primary roles: `ground`, `ward` when explicitly framed, `focus_object` during
visual-system programmes.

Reverie is the normative visual ground. It can be dampened, stabilized,
foregrounded, or intensified, but the always-running generative substrate is not
the same thing as a public claim.

Composition obligations:

- `reverie_substrate` stays present as ground unless a kill switch or explicit
  scene contract says otherwise.
- `suppress` means dampen/quiet the ground under a stronger lane, not stop the
  generative process.
- Public use of local visual pool or CDN assets still requires rights and
  provenance truth.
- Reverie may become a named HOMAGE ward only through the existing ward/pair
  contracts; do not hard-code a special panel path.

### Parallax And Depth

Primary roles: `medium`, `attention`, `transition`.

Parallax is an attention and depth grammar. It is not an audio visualizer and
not proof of live control.

Composition obligations:

- Parallax changes must come from audio-reactivity bounds, programme posture,
  or audited director intent.
- Depth can route attention to a ward, camera, or research object, but cannot
  make a candidate lane appear mounted.
- High parallax is an `intense` mode and needs OQ-02, no-drift, and legibility
  bounds.
- Stabilization lowers parallax first when evidence is stale or the viewer read
  is overloaded.

### Ward Choreography

Primary roles: `ward`, `transition`, `attention`.

Ward choreography is the conductor for surface appearances, not a source of
claim truth.

Composition obligations:

- Every entrance, exit, hold, foreground, and suppression has a target ward or
  lane plus a reason.
- Silence and stillness are valid only as targeted `hold`, `quiet`, or
  `stabilized` moves.
- Choreography must respect kill switches, consent/privacy blockers,
  rights/provenance blockers, public-event policy, and scrim health.

### GEM Mural

Primary roles: `ward`, `focus_object`, `annotation`.

GEM is Hapax-authored expression in CP437/BitchX-constrained mural form. It is
not a transcript, not an avatar, not a chat log, and not a status indicator.

Composition obligations:

- GEM may emphasize fragments, ideas, refusal/correction moments, or abstract
  programme state.
- GEM cannot substitute for captions or transcript evidence.
- GEM composition must preserve anti-face, anti-emoji, anti-transcription, and
  BitchX grammar constraints.
- GEM can carry ordinary content formats when it renders criteria, fragments,
  blockers, or boundaries as authored mural material.

### Multi-Camera

Primary roles: `witness`, `focus_object`, `ground`.

Camera surfaces prove and frame studio reality. They are not equivalent to
public-live state.

Composition obligations:

- Public camera use requires compositor/camera health, face-obscure posture,
  egress truth, and fallback.
- A camera can be foregrounded as witness only with fresh device evidence and a
  known privacy floor.
- Degraded cameras become `stabilized`, `backgrounded`, `suppressed`, or
  unavailable with reason.
- Camera crop, mobile crop, and parallax should serve the same programme read,
  not become unrelated parallel shows.

### Re-Splay Devices

Primary roles: `instrument`, `focus_object`, `translation` for device state.

Re-Splay makes external devices spectacle only after hardware, capture, audio,
and public/private policy are proven.

Composition obligations:

- M8 stays blocked until operator install and plugged-hardware smoke land.
- Polyend and Steam Deck stay blocked behind the M8 baseline and their own
  capture/safety design gates.
- Director/programme may name Re-Splay as dry-run or blocked, but cannot imply
  a mounted device.
- When mounted, Re-Splay must expose capture evidence, audio route policy,
  fallback, and public-claim posture before foregrounding.

### Captions

Primary roles: `translation`, `annotation`, `focus_object` only during caption
programmes.

Captions translate speech or programme boundaries. They are not raw private
transcription and not evidence by themselves.

Composition obligations:

- Captions require freshness, redaction/privacy, egress, and public-event
  policy.
- Dormant captions may be shown only as dry-run/private/unavailable with reason.
- Caption suppression is valid when source freshness or redaction evidence is
  stale.
- GEM may replace caption-strip visual territory, but not caption obligations.

### Overlay Zones And Research Markers

Primary roles: `annotation`, `focus_object`, `translation`.

Overlay zones and markers explain the research state. They must not become raw
internal telemetry by accident.

Composition obligations:

- Overlays render from producer state and event/provenance refs, not from
  layout implication.
- Research markers require condition, programme, or public-event evidence.
- If an overlay is the spectacle, label it as a research marker, criteria
  surface, refusal artifact, correction artifact, or health/status lane.
- Stale overlays become held, suppressed, or degraded with reason.

### Metadata And Status Lanes

Primary roles: `translation`, `annotation`, `witness`.

Metadata/status surfaces translate evidence into public, archive, or operator
reads. They do not scrape arbitrary internal files.

Composition obligations:

- Metadata, cuepoints, chapters, statuslog, weblog, Are.na, Shorts, and fanout
  consume `ResearchVehiclePublicEvent` and surface policy.
- Status can be viewer-facing spectacle only when status is the intended
  content and the source evidence is fresh.
- Health/status lanes report egress/audio/substrate/programme/archive truth;
  they never invent liveness.

### Mobile And Aspect Variants

Primary roles: `variant`, `witness`, `translation`.

Mobile 9:16 is a deliberate composition variant, not a crop afterthought.

Composition obligations:

- The portrait stream uses the mobile producer, salience routing, face-obscure
  wrapping, and legibility evidence from its implementation task.
- Mobile companion/page claims remain unavailable until their producer and
  public aperture evidence exist.
- A surface may have different role priority in 16:9 and 9:16, but both
  variants inherit the same truth and claim policy.

## Programme Envelope Examples

Programme chooses envelopes over roles and modes. Director accepts, reshapes,
or no-ops them through audited moves.

| Programme shape | Primary composition | Guardrail |
|---|---|---|
| `listening` | Quiet Reverie ground, warm scrim, held music provenance/CBIP/HOMAGE, autonomous speech suppressed, metadata/fanout off except boundaries. | No lyric, album, or audio claim without provenance and audio safety. |
| `evidence_audit` | Scrim in clarity posture, research markers foregrounded, cameras or archive frames as witnesses, status lanes as annotation. | Evidence refs must remain visible/auditable; raw logs need translation. |
| `tier_list` or `ranking` | Criteria surface foregrounded, GEM/HOMAGE can emphasize choices, scrim marks uncertainty and decisions. | No expert-system confidence theater; rankings carry scope and evidence limits. |
| `watch_along` or `review` | Cameras/Reverie/HOMAGE frame commentary, rights-blocked media is suppressed or metadata-first. | Third-party media cannot be laundered through spectacle. |
| `failure_autopsy` | Blocked reasons, health/status, refusal/correction artifacts, and scrim stabilization become the spectacle. | Failure is content only when it is explicit and policy-safe. |
| `hothouse_pressure` | HOMAGE, GEM, and scrim can intensify while Reverie remains ground. | Intensity cannot hide studio semantics, blockers, or public/private posture. |
| `ritual_boundary` | Scrim boundary gesture, metadata/chapter candidate, HOMAGE transition, optional GEM fragment. | Public boundary requires programme/public-event evidence; otherwise dry-run/archive-only. |
| `studio_work` | Cameras and private terminal/status lanes may foreground internally; public view uses redacted witness or neutral ground. | Private controls and terminal data do not become public spectacle by default. |

## Anti-Telemetry-Collapse Rules

Viewer-facing surfaces may show raw telemetry only when raw telemetry is the
explicit subject of the programme. Otherwise telemetry must be translated into a
role-bound visual form.

Rules:

1. A health row can be a `witness` or `annotation`; it cannot become an
   unexplained wall of internal metrics.
2. A research marker must cite condition/programme/event refs.
3. A status lane must say whether it is private, dry-run, degraded, blocked,
   archive-only, or public-live.
4. A blocked surface should show the blocker as a successful visual state when
   policy permits, not disappear silently.
5. Aesthetic intensity is never evidence. Glow, motion, clarity, parallax, and
   density cannot imply truth, safety, confidence, rights, or monetization.

## Composition Conflict Policy

When several surfaces compete:

1. Kill switches, safety, consent/privacy, rights/provenance, and public-event
   blockers win over spectacle.
2. Scrim and Reverie keep continuity unless explicitly suppressed by a safe
   envelope.
3. One foreground read is preferred. Other safe reads become backgrounded,
   held, transitional, or quiet.
4. If the foreground read is status/health/failure, make that a deliberate
   programme role.
5. If too many surfaces are safe but competing, stabilize parallax and scrim
   first, then suppress or background low-priority annotations.
6. If a requested lane is missing, emit no-op/dry-run/fallback evidence rather
   than pretending the lane did not exist.

## Child Implementation Split

Do not create one spectacle implementation umbrella. Split adapters where
existing systems already own behavior.

| Child task id | Relationship | Write scope guidance |
|---|---|---|
| `homage-spectacle-architecture-adapter` | Child of this contract and `homage-live-rehearsal-signoff-reconcile`. | Map HOMAGE rehearsal, ward contrast, recognizability, and OQ-02 evidence into composition roles/modes. Do not rewrite HOMAGE rendering. |
| `scrim-spectacle-architecture-adapter` | Child of scrim state envelope and director scrim gesture work. | Consume `ScrimStateEnvelope` as medium/posture evidence and expose composition roles without granting public claims. |
| `reverie-ground-spectacle-adapter` | Child of Reverie/source-registry work. | Expose ground dampen/stabilize/intensify evidence and rights/provenance posture for visual pool/CDN assets. |
| `parallax-depth-director-adapter` | Child of video-container parallax HOMAGE and director-control work. | Convert programme/director moves into bounded depth/parallax intent; no audio-visualizer register. |
| `gem-mural-spectacle-adapter` | Child of GEM/GEAL expression surface work. | Treat GEM as authored mural expression, not captions or status. Preserve anti-face and BitchX constraints. |
| `camera-witness-spectacle-adapter` | Child of compositor/camera health and egress truth. | Map camera freshness, face-obscure, degradation, crop, and fallback into witness/focus roles. |
| `re-splay-spectacle-architecture-adapter` | Blocked child of M8 install/smoke and downstream Polyend/Steam Deck gates. | Keep devices blocked/no-op until hardware, capture, audio, and policy evidence exist. |
| `captions-spectacle-architecture-adapter` | Child of caption bridge and YouTube production wiring. | Map caption freshness/redaction/egress/public-event policy into translation roles and suppress/fallback behavior. |
| `overlay-marker-spectacle-adapter` | Child of overlay zones/research marker producer work. | Convert producer and condition/event provenance into annotation/focus roles. |
| `metadata-status-spectacle-adapter` | Child of public-event, programme-boundary, YouTube, and cross-surface event contracts. | Render metadata/status as translation/witness lanes; no platform writes here. |
| `mobile-variant-spectacle-adapter` | Child of mobile substream implementation and future companion/page work. | Bind 9:16 salience and legibility evidence to the same role/mode policy as desktop. |
| `health-telemetry-spectacle-policy` | Child of `livestream-health-group`. | Define when raw health/status is the intended spectacle and how to translate it otherwise. |

## Acceptance Pins

This contract is accepted when downstream work can use it to verify that:

- every spectacle family has composition roles and directorial affordances;
- surfaces can be foregrounded, backgrounded, held, transitional, intense,
  quiet, suppressed, stabilized, dry-run, or blocked under programme control;
- viewer-facing surfaces do not collapse into raw telemetry unless raw
  telemetry is the intended spectacle;
- child tasks adapt existing HOMAGE, scrim, Reverie, parallax, ward, GEM,
  camera, Re-Splay, caption, overlay, metadata, and mobile systems instead of
  replacing them;
- multi-spectacle, multi-faceted, imbricated, dynamic behavior is a first-class
  design requirement;
- the scrim is treated as a WCS expression surface and constant medium, not a
  decorative overlay; and
- aesthetic force never expands truth, public-live, rights, privacy, audio,
  consent, or monetization claims beyond upstream evidence.
