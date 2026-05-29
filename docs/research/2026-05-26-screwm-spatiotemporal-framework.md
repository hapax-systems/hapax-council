# Screwm Spatiotemporal Framework

Authority: `CASE-SCREWM-QUAKE-MIGRATION-20260523`

Status: operative. This framework is not optional critique language. Spatial,
temporal, media, and later sonic decisions must either satisfy it or declare a
specific exception with witness evidence.

## Research Returns

Eight read-only research lanes were defined for the migration:

- Phenomenology: embodied being-within, body schema, affordance, orientation.
- Japanese garden: roji/stroll grammar, miegakure, ma, borrowed scenery.
- Perception: Gestalt grouping, depth cues, hierarchy, clutter, luminance, motion comfort.
- Cinematography / exhibition / game space: viewing distance, angular size,
  pause points, readable aspect ratios, wayfinding, and immersive rather than
  theatrical screen placement.
- Media theory: medium specificity, remediation, media archaeology, liveness.
- Anti-parasocial: source-role legibility, consent, non-extractive audience relation.
- Light/material/temporality: luminance hierarchy, fog, bloom, flicker, adaptation.
- Sonic/aural: soundscape, auditory scene analysis, acousmatic relation, synchresis.

The first rule that follows from all lanes is determinant relation: nothing
injected into DarkPlaces or the compositor may have an arbitrary relationship to
the room. Media, text, audio, Pango surfaces, drift fields, and Quake entities
must declare what they are, where they mount, what scale/aspect contract they
obey, what source or license risk they carry, and what perceptual purpose they
serve.

## Operative Rules

1. The room is a no-front environment. It must support walking through and around
   its contents; a front-facing theater read is a failure.
2. The default OBS review path must include stable pause stations. Motion is for
   revelation and inspection, not for demonstrating camera cleverness.
3. Ward scale starts from media legibility. Geometry scales around readable media
   rather than squeezing media into arbitrary Quake-scale frames.
4. Every injected media ward must follow the deterministic mount contract in
   `config/screwm-quake-media-mounts.json`.
5. Mounts are contracts before they are objects. Default BSP frames,
   standoffs, status spines, and decorative chrome are forbidden; visible mount
   expression must be coordinate-bound compositor/CSQC behavior attached to the
   receiver surface.
6. AoA is an object of attention, not a decoration: the sphere sits in the AoA
   volume, the AoA stands upright, and the media projection belongs to that
   object.
7. Density must be staged. Each pause view should have a foreground cue,
   middle-ground media/action, and far borrowed-view cue, with no more than
   three primary media wards competing at once.
8. Obscurity is allowed only when it creates motivated reveal. Purpose-critical
   wards must become clear from their intended inspection station.
9. Temporal change must be cued. Uncued global brightness shifts, fast flicker,
   or camera jerk are failures because they break perceptual trust.
10. Anti-parasocial presentation is structural. Camera wards are bounded
   instruments with role/freshness/consent/purpose context, not intimacy
   billboards.
11. Homage is deep but portable. The framework owns contracts and mechanisms;
    specific BitchX/ACiD/Enlightenment/other choices belong in swappable Homage
    packages with their own provenance and risk boundaries.
    The current reference pack is declared at
    `config/homage-packs/bitchx-acid-enlightenment.json`; portable mount
    contracts may reference only generic material profiles.

## Media Theory And Anti-Parasocial Rules

Media wards are not neutral rectangles. A ward must declare whether it is a
flat screen, sphere projection, ticker/text field, camera instrument, or later
audio object before it enters the room. The declared medium constrains its
geometry: aspect ratio follows source aspect for flat media, spherical
projection belongs to the AoA sphere, ticker text uses readable path-relative
bands, and camera wards are placed as instruments in the garden rather than as
central face billboards.

Anti-parasocial design is also a geometry rule:

- Camera wards must carry `role`, `freshness`, `consent_or_license`, and
  `purpose` context in the mount contract.
- No default pause view may be organized around a single face as the dominant
  object. At most one face-dominant camera ward can be primary in a pause view.
- Camera wards reveal from the path and recede into the room; they should not
  own the centerline by default.
- Viewer agency targets the space, object of attention, ward purpose, or source
  state, not simulated personal access to the operator.
- The AoA sphere is disciplined as object-of-attention media: YouTube or any
  other media on it is wrapped to the object, not presented as a fourth-wall
  player.
- Ticker/text wards must speak operationally: source state, provenance,
  drift/event pressure, timing, and system relation. They must not simulate
  intimacy, direct address, or personality theater.
- Fourth-wall surfaces, HUD layers, and unbound screen-space effects are not
  entities. If compositor supplementation is required, it must carry an
  explicit receiver, coordinate, mask, depth, or route-state contract.
- True temporal history effects such as trails, echo, stutter, slitscan, and
  feedback belong in the Hapax compositor/glfeedback route. DarkPlaces GLSL may
  provide bounded no-history field effects, but it cannot substitute for those
  stateful drift families.

The machine-readable contract is `config/screwm-spatiotemporal-framework.json`.
The map generator validates current room scale, garden stations, mount contracts,
and target runtime basics against that file before emitting maps.

## Failure Predicates

Release blocks when any of these are true:

- OBS or Xvfb witnesses are missing, black, stale, or taken from the wrong surface.
- AoA is tilted, inverted, or the sphere is outside the AoA interior volume.
- A ward cannot be identified by its purpose from the intended inspection station.
- A media ward has arbitrary aspect ratio, arbitrary texture scale, or unknown source role.
- The default review path produces disorientation, jerk, or a front-wall theater read.
- A fourth-wall surface or screen-space effect is treated as a final ward.
- BSP frames, standoffs, status spines, or decorative mount chrome are emitted
  by default instead of receiver-bound compositor/CSQC mount expression.
- More than three primary media wards compete in a single pause view.
- Lighting pulses globally by more than 10 percent every 4-8 seconds without an explicit state/audio cue.
- The recurrent path is faster than 300 seconds or uses instantaneous speed
  changes instead of station-bound dwell/selection changes.
- The portable framework contains a specific homage's license/risk-bearing assets or personal aesthetic choices.

## Source Threads

Research intake was source-backed through governed Tavily search on
2026-05-26. The framework currently draws on:

- Embodied perception and affordance: Merleau-Ponty/Gibson threads via
  [Merleau-Ponty for Architects](https://nottingham-repository.worktribe.com/preview/971262/Merleau-Ponty%20for%20Architects_Finalproof_2016.pdf)
  and [Springer embodied architecture research](https://link.springer.com/chapter/10.1007/978-3-031-26074-2_15).
- Japanese garden pathing: roji, stroll garden, miegakure, ma, and shakkei via
  [Seattle Japanese Garden stroll-garden notes](https://arboretumfoundation.org/wp-content/uploads/2020/07/kennedy_stroll-garden-style.pdf)
  and [Analysis of Movement in Sequential Space](https://oulurepo.oulu.fi/bitstream/10024/34668/1/isbn951-42-7653-1.pdf).
- Perceptual legibility: depth cues, Gestalt figure-ground, and VR depth
  distortion via
  [Nature Index depth perception in virtual environments](https://www.nature.com/nature-index/topics/l4/depth-perception-in-virtual-environments)
  and [Scholarpedia figure-ground perception](http://www.scholarpedia.org/article/Figure-ground_perception).
- Cinematography / exhibition / game space: media height, viewing distance,
  glare, type-size, and inspection station practice via
  [Ingenium Accessibility Standards for Exhibitions](https://accessibilitycanada.ca/wp-content/uploads/2019/07/Accessibility-Standards-for-Exhibitions.pdf)
  and [Smithsonian accessible exhibition design](https://www.sifacilities.si.edu/sites/default/files/Files/Accessibility/accessible-exhibition-design1.pdf).
- Media theory: remediation, immediacy/hypermediacy, and live media as a
  hybrid cultural/technical network via
  [Bolter and Grusin, Remediation](https://monoskop.org/images/a/ae/Bolter_Jay_David_Grusin_Richard_Remediation_Understanding_New_Media_low_quality.pdf).
- Anti-parasocial design: facecam/addressing as parasocial triggers and
  livestream responsiveness as risk via
  [UMSU on facecam parasocial construction](https://umsu.unimelb.edu.au/news/article/7797/Why-the-Face-The-Role-of-the-Face-Cam-in-Constructing-Parasocial-Relationships)
  and [parasocial livestreaming research](https://www.ajpor.org/article/123169-parasocial-relationships-with-live-streamers-evidence-from-south-korea-and-the-united-states).
- Light/material/temporality: luminance maps, adaptation, glare, and local
  task luminance via
  [Defining the visual adaptation field for mesopic photometry](https://pmc.ncbi.nlm.nih.gov/articles/PMC11231917/)
  and [luminance-based lighting design](https://www.mdpi.com/2071-1050/15/5/4369).
- Sonic/aural staging: soundscape, auditory scene analysis, masking,
  direction/distance/depth, and spatial audio immersion via
  [spatial auditory scene assessment](https://repository.bilkent.edu.tr/bitstreams/86734641-e671-4f87-8aa2-b4983d33ca11/download)
  and [spatial audio for soundscape design](https://scispace.com/pdf/spatial-audio-for-soundscape-design-recording-and-4uh8nlg0e2.pdf).
