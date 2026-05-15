---

## Authority Case: CASE-AVSDLC-STANDARDS-20260515

### Purpose

This authority case establishes the formal review methodology for aesthetic,
visual, audio, and audiovisual work within the Hapax SDLC. It answers the
question: against what standards is aesthetic work evaluated, and where do those
standards come from?

This is a Tier-2 interview prerequisite. Interviews are the highest-stakes
aesthetic and ethical surface Hapax operates. The operator appears live, voice
synthesis carries the system's side of a broadcast conversation, and visual
composition communicates the system's research character. Without formal review
methodology, interview quality defaults to unaudited taste.

### Governing Principle

From REQ-20260508190834:

> The controlling object is a justified quality claim with evidence, critique,
> failure predicates, and revision history.

This means:
- No aesthetic work ships on "it looks/sounds good."
- No metric-only pass substitutes for perceptual or theoretical judgment.
- No external standard is borrowed without an explicit fit statement.
- No Hapax-native standard is invoked without a formation record.

### Standards Classification

Every standard applied to aesthetic work carries one of four provenance labels:

| Provenance | Definition | Required artifacts |
|---|---|---|
| **Established external** | Published professional or academic standard used as-is | Citation, version, scope statement |
| **Adapted external** | Published standard modified for Hapax context | Citation, fit statement, non-isomorphism risk, adaptation rationale |
| **Hapax-native** | Standard developed within this project with no direct external equivalent | Formation record (see REQ-AVSDLC-004A below) |
| **Experimental candidate** | Proposed standard not yet validated | Hypothesis, validation plan, expiry date, provisional scope |

### Standards Provenance by Modality

#### Audio Standards

| Standard | Provenance | Source | Scope within Hapax |
|---|---|---|---|
| EBU R128 / ITU-R BS.1770 integrated loudness | Established external | European Broadcasting Union R128 (2020); ITU-R BS.1770-5 | Broadcast master loudness target: integrated LUFS in [-16, -12], peak TP <= -0.5 dBTP. Applied at `hapax-broadcast-normalized`. Measured by `scripts/audio-measure.sh`. SSOT: `shared/audio_loudness.py`. |
| EBU R128 short-term loudness (LUFS-S) | Established external | EBU R128 s1 (2020) | Panic-cap threshold at -6 LUFS-S sustained >300ms. Implemented in `lufs_panic_cap.py`. |
| PipeWire/ALSA routing verification | Established external | PipeWire project conventions | Golden chain verification: `scripts/hapax-audio-routing-check`. Every audio change verified before/after. |
| TTS intelligibility (word error rate) | Adapted external | Speech intelligibility research (PESQ, STOI families); adapted because Hapax TTS is synthetic, not human speech | WER on representative utterances <= 5% under nominal stream conditions. Non-isomorphism: PESQ/STOI were designed for telephony/human-to-human; synthetic speech has different failure modes (phoneme dropping, prosodic collapse). |
| TTS prosodic quality | Adapted external | Phonetics/prosody research (F0 contour analysis, duration modeling); adapted for synthetic voice evaluation | Pitch range, pause distribution, and speaking rate consistency evaluated per-utterance. Non-isomorphism: human prosodic "naturalness" is not the target; non-anthropomorphic prosodic coherence is. |
| Non-anthropomorphic voice personage | Hapax-native | Derived from non-anthropomorphic segment prep framework (2026-05-06 spec) and HARDM anti-anthropomorphization principle | Voice must not simulate human empathy, rapport, warmth, concern, or personality. Formation record below. |
| Audio self-perception loop fidelity | Hapax-native | AVSDLC-002 S5 ISAP; no external equivalent for a system monitoring its own broadcast audio | System captures its own broadcast output at the normalized egress path and feeds bounded dimensions into stimmung. Formation record below. |
| Broadcast chain integrity | Adapted external | Broadcast engineering practice (signal flow verification, headroom management) | The golden chain (TTS -> voice-fx -> loudnorm -> MPC -> L-12 -> USB return -> livestream-tap -> broadcast-master -> broadcast-normalized -> OBS) must be verified end-to-end. Adapted: the chain includes non-standard elements (analog mixer, effects pedal). |

**Formation record: Non-anthropomorphic voice personage**

- Motivating artifact class: TTS voice output in livestream interview segments.
- Positive examples: Hapax states factual observations, uses operational vocabulary ("the segment states," "source pressure changes the claim"), maintains consistent synthesized voice identity.
- Negative examples: TTS output that says "I understand how you feel," "thank you for sharing," "that sounds hard," uses therapeutic paraphrase, simulates human conversational warmth, or adopts personality-coded intonation patterns.
- Adjacent-domain borrowings: broadcast announcer register (neutral, clear, paced); automated system voice conventions (informational clarity over personality). Fit: both prioritize clarity over personality simulation.
- Rejected borrowings: companion-agent voice design (ELIZA, Replika — designed for simulated relationship); human-host interview voice (built on empathy simulation); Jungian persona/archetype voice (imports human interiority).
- Claim scope: the voice should be identifiably Hapax's, not identifiably human-like. This is a character constraint, not a quality metric.
- Known limits: "non-anthropomorphic" is easier to define by exclusion than by positive specification. The boundary between "clear operational tone" and "cold/robotic" needs ongoing calibration.
- Revision triggers: operator feedback on voice character; new TTS engine evaluation (see `docs/research/tts-alternatives-evaluation-2026-05-14.md`); personage lint coverage changes.

**Formation record: Audio self-perception loop fidelity**

- Motivating artifact class: Hapax's ability to detect and respond to its own broadcast audio state (signal presence, spectral characteristics, content mix).
- Positive examples: system detects silence on broadcast master and degrades stimmung stance; system detects spectral shift indicating music vs. voice and adjusts content programming.
- Negative examples: system claims to "hear" or "listen to" its own voice in human-experiential terms; system uses audio self-perception to override infrastructure health signals.
- Adjacent-domain borrowings: audio monitoring in broadcast engineering (confidence monitoring, return feeds). Fit: functional monitoring of signal presence and quality.
- Rejected borrowings: auditory perception psychology (implies conscious hearing); AI "self-awareness" literature (overclaims on what a signal processing loop constitutes).
- Claim scope: the loop measures signal properties at a defined capture point. It does not constitute hearing, listening, or auditory perception in any experiential sense.
- Known limits: first implementation (AVSDLC-002 S5) establishes only signal presence and spectral features. It does not prove that these dimensions improve segment quality or viewer engagement.
- Revision triggers: S7 live witness results; stimmung destabilization from audio dimensions; capture path changes.

#### Visual Standards

| Standard | Provenance | Source | Scope within Hapax |
|---|---|---|---|
| Design language color contract | Hapax-native (governed) | `docs/logos-design-language.md` sections 3.1-3.8 | All color in governed surfaces derives from semantic tokens. No hardcoded hex except detection overlays (mode-invariant by design) and compositor void (#0a0a0a). |
| Design language spatial model | Hapax-native (governed) | `docs/logos-design-language.md` section 4 | Five-region terrain, three depth states, fixed proportional system (2px base unit). |
| Design language typography | Hapax-native (governed) | `docs/logos-design-language.md` section 1.6 | JetBrains Mono exclusively. Size varies by context, family never changes. |
| Broadcast-safe type scale | Adapted external | Broadcast typography practice; adapted for dense information-display livestream | Minimum 12px for stream-visible text. Sub-12px only in off-stream surfaces or inside `<RedactWhenLive>`. Per `docs/logos-design-language.md` section 12.1. |
| Broadcast-safe color envelope | Adapted external | Broadcast color science (chroma limits for video encoding) | High-luminance, high-saturation colors muted 15% chroma on stream-visible surfaces. Per `docs/logos-design-language.md` section 12.2. |
| WCAG 2.1 AA contrast ratios | Established external | W3C WCAG 2.1 | Minimum 4.5:1 for body text, 3:1 for large text. Applied to ward/card text against surface backgrounds. |
| Camera framing | Adapted external | Cinematographic convention (rule of thirds, headroom, look room); adapted for multi-camera computational compositor | Camera tiles in compositor maintain subject positioning. Non-isomorphism: Hapax cameras are fixed-position surveillance-style, not operator-directed cinematic cameras. Framing is achieved through crop/pan in software, not physical camera movement. |
| ISA-101 "going gray" principle | Adapted external | ISA-101.01-2015 (Human Machine Interface for Process Automation Systems) | Gray is normal; color demands attention. Adapted: ISA-101 is for industrial HMI; Hapax uses it as a density/attention principle for information display. |
| Animation vocabulary | Hapax-native (governed) | `docs/logos-design-language.md` section 6 | Four animation families only (breathing, transitions, depth flash, decay + ambient). No bounce, elastic, or spring physics. |

**Formation record: Design language color contract**

- Motivating artifact class: every visual surface the operator sees — Logos app, desktop, terminal, notifications, lock screen.
- Positive examples: all semantic colors resolve through palette tokens; mode switch changes every surface simultaneously; the operator builds spatial memory of where colors mean what.
- Negative examples: a component hardcodes `#fb4934` instead of `var(--color-red-400)`; mode switch leaves a surface on the wrong palette; a new color is introduced without semantic assignment.
- Adjacent-domain borrowings: industrial HMI color standards (ISA-101); aviation cockpit color coding; Tufte information display principles. Fit: all prioritize meaning over decoration.
- Rejected borrowings: material design color system (decorative palette, not semantic); CSS framework default palettes; arbitrary "brand color" approaches.
- Claim scope: the contract governs meaning of color across all governed surfaces (section 11.1). It does not govern detection overlay perceptual colors (fixed by design) or third-party UI surfaces.
- Known limits: open design question on Solarized ACCENT_PRIMARY (section 10.1); ambient shader color warmth not yet mode-aware (section 10.2).
- Revision triggers: new governed surface added; operator decision on open design questions; palette drift detected by CI.

**Formation record: Animation vocabulary**

- Motivating artifact class: all motion in Logos app and governed desktop surfaces.
- Positive examples: severity-driven breathing animation on signal pips; 200-300ms transitions for depth changes; time-based decay for stale elements.
- Negative examples: bounce or elastic animations; spring physics; decorative motion without information content; animations that compress poorly for livestream (opacity delta < 0.5 without position/scale/color delta).
- Adjacent-domain borrowings: broadcast motion graphics timing; HMI animation standards (minimal, purposeful). Fit: both prioritize function over spectacle.
- Rejected borrowings: consumer app animation libraries (Material motion, Lottie); game UI animation (designed for entertainment); CSS animation galleries.
- Claim scope: all animation in governed surfaces must belong to one of four families. Stream-visible animations must satisfy broadcast compression criteria (section 12.3).
- Known limits: stream-safety of existing keyframes not yet verified by Phase 10 frame-diff check.
- Revision triggers: stream frame-diff testing reveals compression artifacts; new animation family needed (requires formation record amendment).

#### Audiovisual Standards

| Standard | Provenance | Source | Scope within Hapax |
|---|---|---|---|
| Synchresis (audio-visual synchronization) | Adapted external | Chion, Audio-Vision (1994); adapted for computational audiovisual surface | When a visual event and an audio event co-occur, the viewer perceives them as causally linked. Hapax must ensure that TTS output aligns with visual state changes (e.g., ward updates, card transitions) and that audio reactivity (Sierpinski waveform) is perceptually tight to audio signal. Non-isomorphism: Chion describes film editing; Hapax operates in real-time with programmatic control. |
| Pacing coherence | Adapted external | Broadcast segment pacing conventions; adapted for AI-operated interview format | Question-answer pacing in interview segments must maintain consistent rhythm without rushing or dragging. TTS delivery rate, pause duration between segments, and visual transition timing should cohere. Non-isomorphism: broadcast pacing assumes a human host with embodied timing; Hapax must achieve pacing through programmatic control. |
| Aesthetic unity across modalities | Hapax-native | Derived from the livestream's role as a research instrument (per REQ-20260508190834) | The visual aesthetic (Gruvbox/Solarized, terrain metaphor, density principle) and the audio aesthetic (non-anthropomorphic voice, broadcast loudness, signal chain integrity) must feel like aspects of the same system, not bolted-on independent concerns. |
| Said-seen-done alignment | Adapted external | Interview methodology (OHA, CDC qualitative methods); adapted for non-anthropomorphic interview | When TTS speaks a question, corresponding visual state (question card, source card, readback card) must be visible. When TTS speaks a segment transition, visual layout must reflect the transition. Non-isomorphism: human interviewers rely on embodied presence; Hapax must make alignment explicit through layout and state management. |
| Content programme temporal coherence | Hapax-native | Segment prep framework (2026-05-06 spec), content programmer architecture | A running programme's visual, audio, and textual components must maintain temporal coherence: a programme about topic X does not display cards from topic Y while speaking about X. |

**Formation record: Aesthetic unity across modalities**

- Motivating artifact class: the livestream as a whole — the unified audiovisual experience a viewer receives.
- Positive examples: Gruvbox-warm visual palette with non-anthropomorphic voice at broadcast loudness, both governed by stimmung stance; Sierpinski waveform reactivity to TTS voice in the center of the visual field; shader effects and ambient audio moving at coherent tempos.
- Negative examples: clinical/cold visual surface with warm/friendly voice tone; high-density information display with slow/relaxed audio pacing; visual effects operating at tempos unrelated to audio content.
- Adjacent-domain borrowings: Gesamtkunstwerk concept (total work of art — unity of media); broadcast design (visual-audio brand coherence). Fit: both address cross-modal aesthetic unity. Non-fit: Gesamtkunstwerk implies authorial intent toward audience experience; Hapax's unity is operational, not dramaturgical.
- Rejected borrowings: multimedia design "synergy" frameworks (often content-free); UX "consistency" heuristics (too shallow for the polysemic research surface).
- Claim scope: the standard requires that independently governed modalities (audio chain, visual surface, shader pipeline) do not contradict each other aesthetically. It does not require that they be designed as a single system — they are governed by separate specs — but they must not feel like separate systems to a viewer.
- Known limits: "feels like the same system" is difficult to operationalize beyond exclusion of obvious contradictions. This standard will need empirical refinement through operator review of recordings.
- Revision triggers: new modality added (haptic, motion); major aesthetic direction change in any single modality; operator identifies cross-modal contradiction in review.

### Review Gates

Every work item that impacts aesthetic, visual, audio, or audiovisual surfaces
must pass through the following gate structure. Gates are additive — a change
affecting both audio and visual must pass both sets of gates.

#### Gate 1: Impact Classification (REQ-AVSDLC-001)

Before implementation authorization, the authority case planner must classify
whether the work item has impact on any of these axes:

- aesthetic
- theoretical
- visual
- audio
- audiovisual
- dramaturgical
- interactional
- accessibility
- research-validity
- public-currentness
- provenance

If any axis is impacted, the remaining gates apply to that axis.

#### Gate 2: Standards Declaration (REQ-AVSDLC-002, REQ-AVSDLC-003)

For each impacted axis, the quality dossier must declare:

- Which standards apply (from the provenance tables above)
- What evidence type is required (from the evidence contracts below)
- What failure would look like (failure predicates)
- What review method will be used

#### Gate 3: Evidence Collection (REQ-AVSDLC-005, REQ-AVSDLC-006, REQ-AVSDLC-007)

Before release authorization:

- **Visual:** fresh screenshots or recordings across affected states/viewports, captured via `scripts/compositor-frame-capture.sh` or equivalent
- **Audio:** routing verification (`scripts/hapax-audio-routing-check`), loudness measurement (`scripts/audio-measure.sh`), audibility/intelligibility spot-check, clipping/noise check
- **Audiovisual:** temporal alignment witness (visual state matches audio state at key moments), pacing check, aesthetic unity check
- **Theoretical:** claim map with source/counter-source, debt register entries

#### Gate 4: Review (REQ-AVSDLC-010)

Review types by axis:

| Axis | Mechanical check | Agent/expert review | Operator review | Adversarial |
|---|---|---|---|---|
| Visual | CI color-token lint, screenshot diff | Design language compliance review | Operator perception check | "Can I read this at stream resolution?" |
| Audio | LUFS measurement, routing verification, clipping check | TTS quality evaluation | Operator listening check | "Does this sound like Hapax?" |
| Audiovisual | Sync witness, pacing measurement | Cross-modal coherence review | Operator viewing check | "Does this feel unified?" |
| Theoretical | Claim structure validation | Source adequacy review | Operator conceptual review | Counter-argument test |

#### Gate 5: Release Decision (REQ-AVSDLC-009)

Release is blocked when:

- Required evidence is missing or stale
- Mechanical checks fail
- Perceptual review identifies a contradiction the metrics did not catch
- A theoretical claim lacks adequate source support
- An external standard is cited without a fit statement
- A Hapax-native standard is invoked without a formation record

Release proceeds when:

- All applicable evidence is fresh
- Mechanical checks pass
- Perceptual review confirms no contradiction
- Theoretical claims have adequate support
- Standard provenance is documented
- The quality dossier is complete

### Theoretical Claim Evaluation (REQ-AVSDLC-008)

Aesthetic choices in Hapax often embed theoretical claims. Examples:

- The Sierpinski fractal center embeds a claim about non-anthropomorphic visual identity (HARDM principle).
- The non-anthropomorphic voice register embeds a claim about machine personage derived from Goffman's production format.
- The terrain spatial metaphor embeds a claim about geological/phenomenological organization of awareness domains.
- The stimmung system embeds a claim about system-state-as-aesthetic-parameter.

Each embedded theoretical claim must have:

1. **Claim statement:** what is being claimed and by what artifact
2. **Source lineage:** where the theoretical commitment comes from (corpus texts, operator decisions, research findings)
3. **Fit analysis:** why this theoretical framework applies to Hapax's specific case (not just "it sounds relevant")
4. **Non-fit risks:** where the borrowed framework does not map cleanly to Hapax's situation
5. **Counter-sources:** known objections or alternative frameworks that were considered and rejected (with reasons)
6. **Debt declaration:** what the claim assumes but has not yet proven
7. **Public-currentness classification:** stable background, current, speculative, or historical
8. **Revision triggers:** what evidence would require revising or abandoning the claim

These are recorded in the authority case quality dossier and maintained as
living documents. They are not decorative — they are audited during review.

### Interaction with Existing SDLC Stages

The aesthetic review gates integrate with the existing authority case SDLC:

| SDLC stage | Aesthetic gate |
|---|---|
| S1 Research | Identify impacted aesthetic axes |
| S2 Plan draft | Declare standards, evidence types, failure predicates |
| S3 Review synthesis | Review standards provenance and fit statements |
| S4 Plan acceptance | Verify formation records for native/adapted standards |
| S5 Implementation authorization | Confirm evidence collection plan |
| S6 Implementation | Collect evidence alongside implementation |
| S7 Runtime verification | Capture live perceptual evidence |
| S8 Release | All gates pass; release decision |
| S9 Post-merge | Verify no aesthetic regression in production |

---
