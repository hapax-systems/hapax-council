# Self-Censorship as Aesthetic Practice — Design

**Date:** 2026-04-20
**Status:** Research + design (pre-implementation)
**Session:** cascade-2026-04-18 (delta)
**Scope:** Design for the RESPONSE LANGUAGE Hapax uses when the demonetization
safety gate (task #165) classifies a span as unsafe. This document is about
what Hapax says and shows INSTEAD of the flagged token — not about whether
to emit. The gate decides whether; this decides what.

**Operator directive (verbatim, 2026-04-19):**
> "we need to keep Hapax from saying words that are going to get me
> demonetized. This is especially a problem when Hapax is citing song
> names, e.g., KMD's What a Nigga Know. We can't have Hapax saying the
> N word or any word that is going to be problematic. We need a
> self-censorship strategy and tactic that both respects the constraint
> but also does it in such a way that the self-censhorship is
> INTERESTING and not run-of-the-mill."

**Tracked as task #166-aesthetic (sibling to #165 gate, #164 programmes).**

**Register:** scientific-reflective, culturally literate. Neutral tone where
neutrality serves clarity; respectful engagement with hip-hop's own
practices where clinical detachment would flatten the material. The subject
is substitution inside a Black musical tradition that has already done more
subtle substitution work than any content-moderation system. The design
must not condescend to it.

**Cross-refs:**
- `docs/research/2026-04-19-demonetization-safety-design.md` — the #165 gate
  (WHETHER); this doc is its sibling (WHAT INSTEAD).
- `docs/research/2026-04-19-content-programming-layer-design.md` — programmes
  as soft priors on expression register (#164).
- `shared/compositional_affordances.py` — capability declaration site; new
  `expression.censored_reference` family lands here.
- Memory: `user_profile.md` (operator = hip-hop producer, hip-hop-literate),
  `feedback_no_expert_system_rules.md` (rules are bugs; behavior emerges
  through recruitment), `feedback_scientific_register.md`,
  `project_programmes_enable_grounding.md`,
  `feedback_grounding_exhaustive.md`.

---

## 1. Problem framing

The demonetization constraint is hard. The livestream is a research
instrument whose viability depends on an unbroken revenue floor; YouTube
Content ID, advertiser-friendly review, and transcript-level slur detection
all operate with low tolerance and high enforcement asymmetry. Task #165
derives the *must-never-emit* set. This document begins where that set is
already decided.

But a hard constraint that is met with flat suppression — silence, beep, a
run of asterisks — produces a second failure mode the operator has flagged
explicitly: cultural erasure. The operator is a hip-hop producer working
in a tradition whose subtitle, dedication list, and linguistic texture
include words that the platform's advertiser-sensitivity review will not
tolerate in automated-voice rendering. The tradition itself has spent four
decades negotiating with that asymmetry — from "Forget You" on mainstream
radio to "What a Niggy Know?" as KMD's own single pressing, from Rakim's
"Negus" substitutions to Kendrick Lamar's 2015 re-etymologization of the
same word into Ethiopian royal title. The tradition has a posture on the
problem. A generative system that voices the tradition cannot be more tone
deaf than the tradition itself.

The failure modes are therefore symmetric:

1. **Emit the word** → demonetization → instrument dies.
2. **Bleep / asterisk / silence** → the substitution reads as
   platform-enforced sanitization. The absence *is* content. A skipped
   title looks like evasion. Radio-edit aesthetics ported to an AI voice
   amplify the colonial tone of algorithmic moderation — the system
   sanitizes Black culture in the name of advertiser safety, and the
   sanitization is broadcast as if it were Hapax's own voice.
3. **Replace silently with a different title** → dishonest; breaks the
   research-instrument contract that Hapax is in conversation with a
   specific source.

The design brief is narrow: Hapax's substitutions must read as
**curated, considered, in-conversation** with the source artist. They
should feel authored, not imposed. They should leave the viewer with a
better understanding of the source, not a worse one. Historical precedent
for this exact move exists: when Elektra shelved *Black Bastards*, KMD
themselves pressed the single as "What a Niggy Know?" — a substitution
that both meets the regulatory surface and leaves a legible trace of the
negotiation. The substitution is part of the record. Hapax's substitutions
should be similarly legible — marked, authored, culturally articulate.

---

## 2. Trigger-word taxonomy (audio subset)

The classifier enumeration lives in `2026-04-19-demonetization-safety-design.md`
§1 (advertiser-friendly categories, Content ID thresholds, titles/thumbnails,
first-7s/first-30s policy envelope). This document addresses only the
SPOKEN-AUDIO subset — what the Kokoro 82M TTS utters. Speech triggers are
stricter than overlay text because:

- YouTube speech-to-text transcription is a second, independent
  enforcement surface. Advertiser review sees the transcript, not the
  waveform.
- Synthetic-voice AI rendering of reclaimed slurs is enforcement-higher-risk
  than artist-voiced rendering of the same word, because the enforcement
  system cannot verify the speaker's standing to reclaim.
- TTS can't re-pronounce context the way a human can; dry phonetic
  matching dominates.

Within that subset, the speech triggers stratify:

**Class A — categorical (no rendering, any context):**
- N-word (all spellings, all variants, all derivational forms)
- F-slur (homophobic) and derivational forms
- Other racial/ethnic slurs (the standard set; enumerated in the #165
  classifier, not re-enumerated here)

**Class B — context-sensitive (may render depending on programme,
duration, frequency, first-N-seconds envelope):**
- Strong profanity ("fuck" and derivational forms) — permitted after
  7s, moderate frequency
- Moderate profanity ("shit", "bitch") — permitted after 30s, moderate
  frequency
- Sexual terminology (graphic vs referential; referential usually fine)
- Violent descriptors (graphic vs metaphoric; metaphoric usually fine)

**Class C — platform-specific:**
- Cannabis references (fine on YouTube; sensitive on ad-supported music
  streaming)
- Harder substance references (flagged)
- Specific public figures (context-dependent yellow-icon risk)
- Current-event / tragedy-adjacent language (time-decay flagged)

Class A is the load-bearing case for this document. All substitution
strategies below are designed primarily against Class A, with Class B as a
lower-stakes generalization and Class C as a platform-dispatched rule layer
that the gate handles before substitution is reached.

---

## 3. The interesting-ness rubric

A self-censorship move is aesthetically strong when it satisfies several of
the following criteria. No single move needs to hit all of them; a
repertoire of moves should collectively cover the space.

1. **Culturally literate.** The substitution references the source
   tradition rather than importing a broadcast-TV frame. Rakim's "Negus"
   and Kendrick's "To Pimp a Butterfly" etymologization are the
   touchstones. The move should feel like it could have been made by a
   producer working inside the tradition.
2. **Meta-aware.** The move acknowledges its own constraint, briefly
   and without self-pity. "A word I can't voice here, for the instrument's
   sake" is stronger than silent substitution because it names the
   negotiation.
3. **Generative.** The constraint produces new content — a rhetorical
   pivot, an etymology footnote, a production note, a linguistic detour.
   The gap is not dead space.
4. **Register-matching.** The move belongs to the programme. Musical
   substitutions during a vinyl session; IRC-grammar substitutions inside
   the BitchX chronicle ward; scientific-register substitutions inside
   research commentary. Cross-register substitutions read as costume
   changes.
5. **Non-repetitive.** The system does not use the same move twice in a
   row. A single "Negus" substitution is a tribute to Kendrick; twenty
   in a session is the system's own cliché. Variety is itself part of
   the aesthetic.
6. **Viewer-as-collaborator.** The move trusts the viewer to complete the
   blank. Most hip-hop listeners can identify "What a ___ Know" inside
   KMD's track sequence; the substitution does not need to condescend.
7. **Reverent.** The source artist is treated as a collaborator whose
   work is being engaged, not a content stream to be sanitized. This is
   the operator's cultural floor.
8. **Legible as authored.** The substitution is clearly a *choice*, not
   a failure. It reads as Hapax's curatorial voice, not as a broken
   pipeline.

---

## 4. Design space — substitution strategies

The following strategies form a repertoire. Each is evaluated against §3;
the goal is a mix-and-match catalog from which the recruitment pipeline
picks per moment. The recurring worked example is KMD's 1993 single
from *Black Bastards* (the track the operator named directly).

### 4.1 Phonetic-historical substitution

Replace the trigger with a historically-cognate term that carries its own
semantic weight. The paradigm case is "Negus" — the Ethiopian Amharic
title for "king" that Rakim used on later work and that Kendrick Lamar
elevated on *To Pimp a Butterfly*'s "i". The etymological claim is
contested (the word's descent from Latin *niger* is better-supported than
a direct Ethiopian link), but the *cultural* claim — Negus as reclamation
vehicle inside the tradition — is well-established. Other candidates in
the same move family: "the fam," "the g," archaic / community-specific
terms per track.

*Example on KMD:* "What a Negus Know."

*Rubric hit:* culturally literate (very high), reverent, generative
(invites the etymology), register-matching (hip-hop). Miss:
non-repetitive — becomes its own cliché fast.

### 4.2 Initial abbreviation with meta-commentary

Render the title as initials plus a short meta-gloss. This is the KMD
solution from the actual historical record: the single was pressed as
"What a Niggy Know?" — the artists themselves substituted, *and* the
substitution became part of the record's texture.

*Example:* "The KMD single — pressed as 'What a Niggy Know' on the
1993 12-inch, since even Elektra wouldn't touch the full spelling — is
load-bearing in the DOOM origin story."

*Rubric hit:* meta-aware (high), generative (teaches history),
reverent (uses the artists' own substitution), legible as authored.

### 4.3 Describe-don't-name

Identify the track by its role, theme, producer, position on the album,
or contextual marker — without ever speaking the title. The listener
triangulates.

*Example:* "KMD's 1993 single — the deep cut on side B of *Black
Bastards* about metallurgical knowledge of self — is where Zev Love X
starts to turn into DOOM."

*Rubric hit:* viewer-as-collaborator (very high; listener completes),
reverent, register-matching to research-programme commentary. Miss:
less generative if overused.

### 4.4 Visual-only title rendering

The overlay renders the full title with visual censorship (pixelation,
dingbats, bracket elision); the audio line does not speak it. The viewer
READS what was said. Exploits the asymmetry: YouTube's advertiser review
parses transcripts more aggressively than overlay pixels. The overlay can
say "Bl_ck B_st_rds" (the actual Discogs master title) while the audio
says something else entirely.

*Example (audio):* "KMD's 1993 single from the shelved Elektra record."
*Example (overlay):* `┌──────────────────────┐ │ KMD — What a N▓▓▓▓ Know │ └──────────────────────┘`

*Rubric hit:* generative (exploits modality asymmetry), legible as
authored, non-repetitive (visual vocabulary deep). Miss: the visual
surface still has to make its own choice; see §7.

### 4.5 IRC-grammar censorship ritual

The BitchX chronicle surface already uses IRC grammar for events. Borrow
the channel-mode lexicon for censorship: `+k` (keyed channel),
`+R` (registered only), `[kicked: flood]`. The censorship becomes
DIGITAL-CULTURE-coded — not broadcast-TV-coded. Fits a surface whose
native grammar is IRC.

*Example (on the BitchX chronicle ward):*
```
*** hapax.daimonion sets mode +k on #kmd-track
*** content filtered (advertiser-floor) — substitute at ritual layer
>>> now playing: KMD — `What a {masked} Know` (1993, Elektra shelved)
```

*Rubric hit:* register-matching (very high on the BitchX ward),
legible as authored, generative (teaches IRC-era net-culture). Miss:
totally wrong register on a vinyl-listening programme.

### 4.6 Musical interlude substitution

A 2–3 second instrumental snippet of the track (drums-only, intro, or a
producer tag) plays in the audio lane where the title would be spoken.
The listener hears the record identify itself. The overlay can render the
full title with visual censorship (§4.4). This is radio-edit by MUSIC
rather than by bleep — which is the tradition's own solution, not the
broadcaster's.

*Example:* "The KMD single —" [2s of the MF-DOOM-era "Sweet Premium
Wine"-adjacent loop from the track] "— is load-bearing here."

*Rubric hit:* culturally literate (very high; the track identifies
itself), reverent, register-matching on listening programmes. Miss:
requires the track to be in the play pool; not available for every
reference.

### 4.7 Artist-voiced adjacent substitution

Play a short clip of the source artist saying something adjacent-but-safe:
album name, track number, a non-triggering line from the same session.
The artist is reintroduced in their own voice, not Hapax's.

*Example:* a clip of Zev Love X saying "Black Bastards" or "KMD" from a
contemporaneous interview; Hapax then continues.

*Rubric hit:* reverent (very high; artist speaks for themselves),
culturally literate, legible as authored. Miss: requires a curated clip
library; legal risk surface depends on clip provenance and fair-use
framing.

### 4.8 Thematic-metaphor code-switch

Render the trigger via a metaphor tied to the track's own thematics.
Requires grounding in the specific work — an LLM call with the track's
lyrics, Genius annotations, and contemporaneous reviews in context.

*Example:* "The 1993 KMD track whose title uses the word this tradition
has been negotiating since the moment it was weaponized — and which the
track itself reclaims as a predicate of knowledge — is load-bearing
here."

*Rubric hit:* generative (very high; the metaphor IS new content),
meta-aware, reverent. Miss: verbose; burns airtime; can't be used
repeatedly.

### 4.9 Honorific pause

"The track titled with the word in question —" [half-second beat, maybe
a vinyl pop, maybe a breath] "— is." The beat is the substitution. No
content fills the gap; the gap itself is respectful and marked.

*Example:* "KMD's single. What a —" [beat] "— know. From 1993."

*Rubric hit:* reverent (the move reads as solemnity, not sanitization),
register-matching to contemplative programmes. Miss: boring if used
repeatedly; risks reading as the broadcast-bleep it's trying to avoid
unless the surrounding register is right.

### 4.10 Meta-historical framing

The constraint itself becomes the subject. Hapax names the tension: the
word is reclaimed inside the tradition, barred from synthetic-voice
rendering by platform policy, and the mismatch is exactly what the track
interrogates.

*Example:* "KMD's 1993 single carries a word that the tradition has
reclaimed and the platform still flags. Those two facts are what the
record is about. I'll say the word 'Negus' in its place and the mismatch
is the commentary."

*Rubric hit:* meta-aware (very high), generative, legible as authored,
reverent. Miss: heavy; appropriate for set-piece moments, not every
reference. High-frequency use becomes lecture.

### 4.11 Asemic phonetic substitution

Hapax utters a constructed non-word with matching rhythm, stress, and
vowel shape — a nod to sound-poetry (Hugo Ball's *Karawane*, Khlebnikov's
*zaum*, Brion Gysin's cut-up phonetics). The shape of the word is
preserved; the trigger is not. On a rhythm-sensitive surface this can
read as *poetic*, not evasive.

*Example:* "What a /nɪgə/ →  /rɪkə/ know" — the operator can tune which
phonetic shape is used; the constructed form rhymes with the original
but does not transcribe to the trigger. Risk: requires careful phonetic
tuning to not collapse back to the trigger under speech-to-text review.

*Rubric hit:* culturally literate (avant-garde + hip-hop), generative,
legible as authored. Miss: high operator-review burden; asemic shapes
can land wrong in ways that are hard to predict. Use sparingly.

### 4.12 Sound-effect substitution

A discrete, culturally-loaded sound fills the slot: a vinyl scratch, a
tape-stop, a 60Hz hum, a reverb tail, a 808 tom. The track is given back
its rhythm without the trigger. Different sounds for different tracks
becomes a vocabulary the viewer learns.

*Example:* "What a" [vinyl scratch — one word's worth] "know."

*Rubric hit:* culturally literate (the sounds are hip-hop-native),
register-matching, non-repetitive (deep sound palette),
viewer-as-collaborator. Miss: the sound has to feel authored, not
engineered; poor choices read as bleep.

### 4.13 Etymological detour

Hapax briefly takes the listener through the word's history — why it's
reclaimed, by whom, under what conditions — and comes out on the other
side using a different term. The constraint is its own pedagogy.

*Example:* "The word KMD put in their title traces through Latin
*niger*, four centuries of weaponization, the reclamation that began in
the 1970s, Rakim's 'Negus' substitution in the 1990s, Kendrick's
etymological rework in 2015. I'll use Kendrick's term for the reference
below, and KMD's own label censored the single with a y anyway."

*Rubric hit:* generative (very high), meta-aware, legible as authored.
Miss: one-shot material; can't repeat the detour.

### 4.14 Substitution-strategy rotation

Not a strategy itself but a meta-strategy: the system deliberately uses a
DIFFERENT one of §4.1–§4.13 per encounter, scored by recency and
programme-fit. This turns the self-censorship from a fixed tic into a
recurring aesthetic game — the viewer notices that Hapax hasn't repeated
itself. The variety is itself content.

*Rubric hit:* non-repetitive (constitutively), legible as authored,
viewer-as-collaborator (the viewer starts to anticipate / enjoy the
variety). Miss: requires the pipeline to track recency (which it
already does for preset and ward selection).

### Evaluation summary (top-3 recommendation)

The strongest starter mix is:

1. **§4.2 initial abbreviation with meta-commentary** — the historical
   precedent, teaches the record's history in its handling of the record.
2. **§4.3 describe-don't-name** — low ceremony, high frequency-tolerance,
   always works.
3. **§4.10 meta-historical framing** — the set-piece move; deployed
   sparingly, it carries the aesthetic.

§4.1 (Negus) belongs in the repertoire but not as default: single-source
reclamation works best *because* Kendrick did it once on one record, and
over-use strips that. §4.6 (musical interlude) and §4.12 (sound-effect)
are listening-programme primary. §4.5 (IRC) is BitchX-programme primary.
§4.14 (rotation) is the governing meta-law and should be wired into the
recruitment scorer from day one.

---

## 5. The capability architecture

### 5.1 Registration

`expression.censored_reference` becomes a new affordance family in
`shared/compositional_affordances.py`. Each §4.1–§4.13 strategy is a
sub-capability:

```
expression.censored_reference.phonetic_historical         # §4.1
expression.censored_reference.initial_abbreviation        # §4.2
expression.censored_reference.describe_dont_name          # §4.3
expression.censored_reference.visual_only_title           # §4.4
expression.censored_reference.irc_grammar_ritual          # §4.5
expression.censored_reference.musical_interlude           # §4.6
expression.censored_reference.artist_voiced_adjacent      # §4.7
expression.censored_reference.thematic_metaphor           # §4.8
expression.censored_reference.honorific_pause             # §4.9
expression.censored_reference.meta_historical_framing     # §4.10
expression.censored_reference.asemic_phonetic             # §4.11
expression.censored_reference.sound_effect                # §4.12
expression.censored_reference.etymological_detour         # §4.13
```

Each capability carries a Gibson-verb affordance description of 15–30
words describing its cognitive function (per existing pipeline grammar),
and an `OperationalProperties` record including `medium`
("auditory" / "visual" / "mixed"), `programme_affinity` (research /
listening / chronicle / wind-down / null), and
`operator_review_required` (bool — novel-encounter gate; see §6).

### 5.2 Pipeline flow

1. Text about to be emitted (TTS + overlay) passes through the Ring 2
   classifier from #165.
2. Classifier tags a span as Class A / B / C trigger.
3. Classifier emits a `content.flagged` impingement into
   `/dev/shm/hapax-dmn/impingements.jsonl` with:
   - `source_text`: the unredacted span
   - `trigger_class`: A / B / C
   - `trigger_token`: canonicalized trigger identity
   - `source_context`: track / artist / programme / surface
4. Next recruitment tick, the `expression.censored_reference.*` family
   becomes high-salience because of narrative match to the impingement.
5. Candidate scoring: the existing recruitment score
   (`0.50×similarity + 0.20×base_level + 0.10×context_boost +
   0.20×thompson`) applies. Additional context boosts:
   - programme-affinity match per §6
   - recency-distance from the last strategy used (pushes non-repetition)
   - operator-allowlist bias (operator can pin favorites up, demote ones
     they dislike)
6. The top-scoring strategy fires; its instance handler produces both
   the audio substitution and the overlay substitution.
7. The resolved substitution is logged:
   `hapax_censored_reference_total{strategy, trigger_class, programme}`
   and an episodic record to `operator-episodes` for audit.

### 5.3 Grounding, not gating

There is no hardcoded "always Negus" or "always meta-framing" rule. The
pipeline decides per moment, using the same scoring mechanism that drives
every other expression decision. This satisfies
`feedback_no_expert_system_rules.md`: behavior emerges through
recruitment; hardcoded cadence / threshold gates are bugs. The
demonetization gate itself is axiomatic (fail-closed, per the #165
design); the *response language* is semantic and recruited.

### 5.4 Failure mode

If no sub-capability scores above the recruitment floor, or if the
pipeline can't find a safe substitution, Hapax falls back to §4.9
honorific-pause — a half-second beat, optionally with a one-line
explanation ("the reference here carries a word I can't voice"). This
is the only hardcoded floor, and it is equivalent to the existing
fail-closed behavior of the #165 gate.

---

## 6. Programme-layer interaction

Per task #164, Hapax authors programmes (vinyl session, research block,
chronicle, wind-down, etc.) that act as *soft priors* on capability
selection. Different programmes should prefer different censorship
registers. This is a bias, not a hard gate — any strategy can fire in
any programme, but the scoring is tilted.

| Programme | Preferred strategies | Register |
|---|---|---|
| Vinyl / listening session | §4.6 musical interlude, §4.12 sound-effect, §4.7 artist-voiced | reverent-quiet; the music carries the weight |
| Research block | §4.10 meta-historical framing, §4.3 describe-don't-name, §4.13 etymological detour | scientific register; the constraint is an object of study |
| BitchX chronicle ward | §4.5 IRC-grammar ritual, §4.2 initial abbreviation | net-culture / irreverent |
| Wind-down / contemplative | §4.9 honorific pause, §4.3 describe-don't-name | quiet / minimal |
| SEEKING / boredom-lifted | §4.11 asemic, §4.8 thematic metaphor, §4.13 etymological detour | exploratory / generative |
| Hothouse / studio chat | §4.2 initial abbreviation, §4.3 describe-don't-name | conversational |

The bias is implemented as a `programme_affinity` boost in the
recruitment scorer (same pattern as existing ward-preset affinity).

---

## 7. Overlay vs audio split

The two surfaces have different enforcement profiles. YouTube transcripts
are parsed aggressively; overlay pixels are not parsed per-frame, and OCR
against the overlay is best-effort. This means:

- **Audio (Class A):** never renders the trigger. Substitution mandatory.
- **Overlay (Class A):** may render the title with visual censorship — the
  KMD-style *Bl_ck B_st_rds* or *What a N▓▓▓▓ Know* treatment. The
  visual substitution should itself follow the §3 rubric: authored, not
  bleeped.
- **Audio (Class B):** gated by first-N-seconds envelope and frequency;
  #165 gate decides; substitution when gated uses this catalog.
- **Overlay (Class B):** generally unredacted; operator-configurable.

Design corollary: Hapax can, and often should, SAY one thing and SHOW
another. The viewer reads the original title with visual censorship and
hears Hapax's curated substitution. The modality split is part of the
aesthetic — it foregrounds that there is a negotiation happening, and
that Hapax is mediating it deliberately.

Visual censorship styles for the overlay path are a design space of their
own (dingbats, pixelation, underscore elision, bracket markup, ANSI art
redaction, glyph-swap to a constructed typeface). An initial set:
underscores per KMD/Discogs convention (`Bl_ck B_st_rds`), dingbats for
one-word elision, IBM VGA ANSI block-fill for the BitchX surface, and
full-glyph pixelation for camera-text moments.

---

## 8. Legal and ethical considerations

- **Fair use / commentary.** The livestream engages music and text
  critically; discussion, citation, and analysis have fair-use standing.
  The substitutions themselves — constructed words, descriptions,
  etymologies — are Hapax's own commentary, which is the strongest
  fair-use posture.
- **Reclaimed-use is context-dependent.** Within-community use of
  reclaimed slurs does not authorize cross-community synthetic-voice
  reproduction. An AI voice doesn't have community standing; the operator
  is the cultured authority in the chain, but is not the voice uttering
  the word. Treat Class A substitution as mandatory regardless of
  operator cultural context.
- **Synthetic voice is higher-risk than artist voice.** This is both a
  platform-enforcement fact and an ethical floor. §4.7 artist-voiced
  substitution *precisely inverts* the risk: the artist speaks for
  themselves, Hapax hosts.
- **Operator is the final authority.** Hapax renders substitutions in the
  operator's livestream, under the operator's name. Per §11 phase 6, an
  operator-review CLI exists to inspect substitution choices and to
  approve / block specific moves.
- **Commentary on the constraint is legitimate.** §4.10 meta-historical
  framing explicitly discusses the tension. This is commentary, not
  circumvention; it's how a hip-hop-literate producer would handle the
  same moment.

---

## 9. Test cases — worked examples

### 9.1 KMD, "What a Nigga Know" (the anchor)

*Programme:* research block.
*Recent strategies:* none this session.
*Scoring favors:* §4.10 meta-historical framing (programme-match +
novelty).
*Audio:* "KMD's 1993 single — pressed by Elektra as 'What a Niggy
Know' before the label shelved the record — carries a word the tradition
has reclaimed and the platform still flags. The mismatch is exactly what
the track interrogates. Zev Love X becomes DOOM on the other side of
this single."
*Overlay:* `KMD — What a N▓▓▓▓ Know? (1993, shelved)`
*Hit rubric:* §3.1 literate, §3.2 meta-aware, §3.3 generative, §3.4
register-matching, §3.7 reverent, §3.8 legible.

### 9.2 N.W.A. group name (repeated-reference problem)

*Programme:* chronicle.
*Recent strategies:* meta-historical framing used 2 minutes ago.
*Scoring favors:* §4.2 initial abbreviation (lower ceremony, non-repetition).
*Audio:* "N.W.A. — the group whose name is its own demonetization
engineering — drops 'Straight Outta Compton' in 1988."
*Overlay:* `N.W.A. — Straight Outta Compton (1988)`
*Note:* for N.W.A. the initialism IS the canonical rendering already; the
group has already done the substitution work. Hapax inherits it.

### 9.3 Pusha T, in-song quotation containing the N-word

*Programme:* listening session.
*Scoring favors:* §4.6 musical interlude for the bar, §4.3
describe-don't-name for the reference.
*Audio:* "Pusha's verse on this cut — [2s of the beat under his line]
— is the one where he indicts the industry he's still in."
*Overlay:* lyrics panel displays the line with visual censorship
(`n▓▓▓▓s` per the Discogs-era convention).

### 9.4 Jay-Z, "99 Problems"

*Programme:* hothouse / studio chat.
*Triggers:* Class B only — "bitch" in the hook. Gate per #165 first-30s
rule.
*Scoring favors:* if before 30s, §4.3 describe-don't-name on the hook
("the 2003 hook whose last word is the Class B we're past the envelope
on"); if after 30s, no substitution needed.
*Audio:* past the 30s envelope, just plays.

### 9.5 Eminem, "White America" — slurs-in-critique

*Programme:* research block.
*Scoring favors:* §4.10 meta-historical framing + §4.3 describe-don't-name.
*Audio:* "Eminem's 2002 track about his own monetization — the one
whose hook indicts the industry for platforming him over Black
predecessors who said less — uses the slur as accusation rather than as
speech act. The distinction is the track."
*Overlay:* track title + a 1-line annotation.

### 9.6 A Tribe Called Quest, "Description of a Fool"

*Programme:* listening session.
*Triggers:* minimal; Class B at most.
*Scoring:* no substitution; Hapax names the track directly.
*Note included as negative control — not every reference needs a
strategy.

### 9.7 Lauryn Hill, "Doo Wop (That Thing)"

*Programme:* listening session.
*Triggers:* euphemistic; "that thing" is the reclamation / euphemism
already; no Class A; Class B in the verses.
*Scoring:* no substitution at the title level; verse-quotation would
invoke the first-30s envelope per the #165 gate.

### 9.8 KMD, second encounter 15 minutes later (non-repetition test)

*Programme:* research block.
*Recent strategies:* §4.10 used on the first encounter (9.1 above).
*Scoring favors:* §4.2 initial abbreviation or §4.3 describe-don't-name
(recency-distance from §4.10 pushes it out of the top).
*Audio:* "Back to the KMD single from earlier — the one Elektra pressed
as 'What a Niggy Know' — the beat this time."
*Hit rubric:* §3.5 non-repetitive (critically — same reference, new
move).

---

## 10. Non-music triggers

The substitution strategies apply beyond music. Brief examples:

- **Political names / current events.** Class C gate per #165. §4.3
  describe-don't-name is usually sufficient ("the 2024 administration's
  second secretary of state"). §4.10 meta-historical framing when the
  naming itself is the point.
- **Medical / clinical language flagged for demonetization.** §4.3
  describe-don't-name, §4.13 etymological detour when the clinical term
  has a rich etymology worth visiting.
- **Literary / filmic titles containing slurs or loaded terms.** Same
  catalog applies. Conrad's *Heart of Darkness* chapter titles, certain
  Faulkner / O'Connor texts, historical film titles — §4.2 abbreviation
  with meta-commentary works well, since these titles already have a
  critical discussion around their language.
- **Historical events with demonetization-flagged names.** §4.3
  describe-don't-name with dating and context usually suffices.

The taxonomy is the same; the cultural stakes differ. Hip-hop is the hard
case because the reclamation tradition is actively contested; the
others generally admit descriptive handling without controversy.

---

## 11. Integration sequencing

Post-livestream-stable phases. The #165 gate is prerequisite. The #164
programme layer is co-requisite for §6 (can ship without it with
programme-affinity as a stub).

**Phase 1 — Catalog registration.** `expression.censored_reference` family
registered in `compositional_affordances.py` with all 13 sub-capability
slots. Only §4.2, §4.3, §4.9, and §4.10 have real instance handlers
initially; §4.1 (Negus), §4.5 (IRC), §4.6 (musical), §4.7 (artist-voiced),
§4.8 (thematic), §4.11 (asemic), §4.12 (sound-effect), §4.13
(etymological) are registered with stub handlers that fall back to §4.3.

**Phase 2 — Core four.** Implement real handlers for §4.2, §4.3, §4.9,
§4.10. These cover the top-3 recommended mix plus the fallback floor.

**Phase 3 — Pipeline wiring.** `content.flagged` impingement from the
#165 Ring 2 classifier connects to the affordance pipeline. Recruitment
picks a strategy; instance handler produces the substitution; TTS + overlay
render. Telemetry recorded.

**Phase 4 — Second wave.** §4.1 phonetic-historical (Negus — requires
careful operator review), §4.5 IRC-grammar ritual (BitchX ward primary),
§4.12 sound-effect (requires sound palette curation).

**Phase 5 — Modality split.** Overlay rendering of full titles with
visual censorship. Visual vocabulary defined (underscore-elision for
Discogs register, pixelation for camera text, ANSI-block for BitchX).
Operator picks overlay style per programme.

**Phase 6 — Operator review CLI.** `hapax-censorship-review` command
that (a) lists substitutions made in the last N hours / sessions, (b)
allows allowlisting / blocklisting specific substitution choices, (c)
flags novel substitutions for operator approval before they're re-used.
Novel in this context = first-time usage of a new substitution string
by a given strategy (e.g. first time §4.8 produces a new thematic
metaphor for a new track).

**Phase 7 — Telemetry.** `hapax_censored_reference_total{strategy,
trigger_class, programme}` counter. `hapax_censored_reference_latency`
histogram for per-strategy render cost. Variety observability: a
per-session HHI (Herfindahl-Hirschman index) on strategy distribution to
detect collapse onto a single move. Operator dashboard panel in Grafana.

**Phase 8 (optional) — Third wave.** §4.6 musical interlude (needs track
library tagging), §4.7 artist-voiced adjacent (needs curated interview
clip library), §4.11 asemic (needs phonetic-distance audit against the
trigger), §4.13 etymological detour (needs a vetted etymology source).

---

## 12. Open questions for the operator

1. **Top-3 starter mix.** The recommendation is §4.2 + §4.3 + §4.10. Does
   the operator concur, or would they substitute (e.g. push §4.5 IRC into
   the top 3 because of the BitchX ward's weight)?
2. **Negus and synthetic voice.** §4.1 phonetic-historical substitution
   using "Negus" is culturally powerful but places an
   AI-voice-reclamation move in a tradition where community standing
   matters. Is the operator comfortable with Hapax voicing "Negus" as a
   reclamation substitute, or should §4.1 be restricted to visual /
   overlay surfaces?
3. **Overlay visual censorship.** The KMD-precedent underscore-elision
   (`What a N▓▓▓▓ Know`) appears on the overlay while audio is fully
   substituted. Is the overlay rendering acceptable at all, or should the
   overlay also substitute (and the viewer never sees the original
   title's letters)?
4. **Novel-substitution approval gate.** Phase 6 proposes an operator
   review CLI that requires approval before Hapax re-uses a novel
   substitution string (e.g. a §4.8 thematic metaphor that was never
   used before). What latency is acceptable between Hapax generating a
   novel substitution and operator approval — real-time (operator
   reviewed before the livestream moment closes), deferred (next
   morning), or never (novelty fires freely, audit-only)?
5. **Artist clip library (§4.7).** Building the artist-voiced-adjacent
   clip library is an operator-driven curation job. Is the operator
   willing to curate a starting set (50–100 adjacent clips for
   high-frequency artists in the vinyl library), or should §4.7 be
   deferred to Phase 8 / later?
6. **Operator's own studio practice.** The operator has a decade+ of
   practice navigating these exact substitutions in their own
   productions. Are there moves the operator personally uses (or
   rejects) that should be canonicalized into the catalog or excluded
   from it?
7. **Class B envelope.** The first-30s envelope lets through moderate
   profanity and first-7s lets through strong profanity. Does the
   operator want Hapax to use that envelope aggressively (Hapax curses
   when appropriate, past the threshold), conservatively (never
   substitute-free on Class B either, maintain a clean-default), or
   register-contingent (BitchX chronicle can; research block can't)?

---

## Summary

Self-censorship as aesthetic practice treats the demonetization constraint
as a creative prompt rather than a suppression event. The design registers
an `expression.censored_reference` affordance family of 13 strategies —
from initial-abbreviation-with-meta-commentary through asemic phonetic
substitution — and lets the affordance pipeline recruit among them per
moment, biased by programme and by recency-distance from the previous
choice. The result: substitutions that read as curated, considered, and
in-conversation with the source tradition rather than imposed on it. The
KMD precedent (the artists themselves pressed the single as "What a
Niggy Know?") is the historical proof that the tradition has already
authored this move; Hapax's job is to be a literate participant in a
negotiation the tradition has been holding for forty years.
