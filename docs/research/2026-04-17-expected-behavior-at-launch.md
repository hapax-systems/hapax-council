# Expected Hapax Behavior at Livestream Launch — and Is It Good Enough?

**Date:** 2026-04-17
**Authority:** alpha session, post-LRR closure, post-daimonion restart
**Operator prompt:** "How should we expect Hapax to act right out of the
gate; is that good enough?"
**Framing:** this is the research question that determines what
"finish everything conceivable + polish assiduously" actually has to
finish before the livestream can begin. The answer is a falsifiable
prediction plus a criterion for "sufficient to start".

---

## 1. What's deployed as of 2026-04-17

Ten LRR phases + the first Continuous-Loop item (stimmung 12th dim)
shipped and live. The production surface includes:

**Cognition / persona:**
- Document-driven persona composer active (no `HAPAX_PERSONA_LEGACY`).
  ~4957-char prompt: description-of-being + role declaration +
  voice-mode + partner block + tools.
- 31 tools registered with Gibson-verb affordances.
- `ToolRecruitmentGate` operational; tools degrade on critical/degraded
  stimmung, missing backends, missing consent.
- AffordancePipeline gates ALL expression per USR Phases 1–3.
- Thompson + Hebbian learning persisting every 5 min + on shutdown.
- Consent gate fail-closed on `consent_required=True` capabilities.

**Perception / signals:**
- Stimmung with 12 dimensions now (6 infra + 3 cognitive + 3 biometric).
  `audience_engagement` reading uninhabited (collector-call wiring is
  a follow-up).
- Chat structural analyzer publishing `/dev/shm/hapax-chat-signals.json`
  every 120 s when chat-monitor has a video id.
- IR perception from Pi-6 overhead (Pi-1 + Pi-2 pending flash).
- Contact mic (Cortado MKIII) wired through stimmung, VLA, vision fusion.
- VAD + STT running on utterance boundaries.

**Output:**
- Compositor rendering 1920×1080 HLS to v4l2loopback; OBS source.
- 6 cameras at 720p MJPEG, hero-mode switching wired.
- 16+ Cairo sources registered (Sierpinski, album overlay, stream
  overlay, token pole, research marker, overlay zones, objectives
  overlay, captions, environmental salience recommender output).
- Reverie visual surface (wgpu, 7-pass pipeline) available but not
  composited into stream by default.
- Voice FX chain installable; voice-over-YouTube ducker shipped (sc4m
  LADSPA required).

**Governance:**
- Stream-mode axis with 4 states (private / public / public_research /
  fortress).
- 78 privacy-regression tests green (redaction + transition matrix).
- 3 active consent contracts (`agatha`, `guest`, `simon`).
- Mid-stream revocation cascade tested at e2e level.

**Observability:**
- Per-condition Prometheus slicing active.
- Stimmung Grafana dashboard live.
- 18-item stability matrix instrumented.
- Six operational drills run once, result docs written.

**Research instrument:**
- Research registry active (`cond-phase-a-persona-doc-qwen-001`
  open).
- Frozen-files hook enforces condition-scoped edits.
- OSF pre-reg filed (LRR Phase 4).

---

## 2. Predicted launch-day behavior

Given the above, what does the first livestream session look like?

### 2.1 Persona + voice

Hapax speaks in the scientific-cognitive-substrate register the
description-of-being document prescribes. There is no Hermes charm,
no persona as mask. Utterances frame themselves in terms of what the
substrate is doing — "I notice the audio-input buffer has shifted",
"The perception layer is foregrounding the turntable" — rather than
as if by a character. The composed prompt is ~4957 chars, so context
budget is meaningful but not pathological.

**Specific testable prediction:** operator asks three open-ended
questions in the first 15 minutes. At least two of Hapax's responses
explicitly reference a substrate or system component by name (not
just generic cognitive verbs). If fewer than two, the persona is not
being absorbed by the substrate LLM.

### 2.2 Activity selection

The director-loop chooses `activity ∈ {react, chat, study, vinyl,
observe, silence}` on a PERCEPTION_INTERVAL cadence (currently the
default — needs to check the config). Selection is pure-LLM today:
`activity_scoring.score_activity` runs as telemetry only (per
Continuous-Loop §3.2 which is not yet shipped). So the stimmung
term exists in the log but cannot override the LLM.

**Predicted distribution:** `react` dominant (LLM has the most
context for reacting to what just happened). `chat` at moderate rate
if viewers post keyword hits. `silence` when nothing is happening.
`study`, `vinyl`, `observe` are *possible* but unlikely because the
LLM has weak priors for them without environmental cues.

**Testable prediction:** across a 60-minute window, the activity
distribution is >70% `react`, <15% `chat`, <10% `silence`, <5% the
remaining three combined. If `study` or `vinyl` never fires in a
60-min window, it means the environmental-salience emphasis wasn't
wired (confirmed — §3.6 pending).

### 2.3 Chat reactivity

In default (non-research) working mode, the chat reactor fires on bare
preset names with a 30 s cooldown. In research mode, viewers must
prefix `!fx`. The reactor's keyword index covers every preset file
under the compositor's preset dir; collisions resolve longest-match-
first.

**Predicted audience experience:** within 2–3 minutes, a viewer
discovers the keyword mechanism and spams a preset name. The first
spam triggers; the next 30 s doesn't. A different preset can be
triggered in that window. No message leaks author ids anywhere visible.

**Testable prediction:** Stream Moments collector shows a measurable
reaction-count spike in the first 15 minutes tied to preset switches.
If zero audience interaction after 30 min, either the reactor is
broken (unlikely — regression tests pass) or the audience doesn't
know the vocabulary (likely — no on-screen prompt exists).

### 2.4 Closed-loop feedback — **mostly absent**

This is where the "not yet good enough" signal concentrates:

- **Chat queue:** producer pushes every message; drain side is the
  daimonion during `chat` activity, which is not yet wired. The queue
  fills to 20 and evicts. None of the holistic review behaviour the
  queue was built for happens.
- **Attention bids:** bidder scores and `select_winner` runs, but no
  call-site invokes `dispatch_bid` on the winner. Bids are silent.
- **Environmental salience emphasis:** `recommend_emphasis` exists
  but no timer calls it. The compositor's hero mode stays on whatever
  objective-hero-switcher picked from the objective activities.
- **Stimmung 12th dim:** the reading field exists but nothing calls
  `update_audience_engagement`. Stays stale.
- **Captions:** the CairoSource is registered but not in any layout
  JSON. STT output isn't written to the path the source expects.

**Testable prediction:** a 60-min session produces zero entries in
`~/hapax-state/attention-bids.jsonl`, zero "hero promoted by
environmental salience" events in the director-loop journal, and
zero caption draws on the compositor frame. If any of those three
exceed zero, something unexpected is working — investigate.

### 2.5 Visual surface

Compositor renders 1920×1080 with the default layout: main camera
surface + PiP overlays (album cover, stream overlay, token pole) +
Sierpinski triangle + floating overlay zones. Reactor header shows
activity state in caps. Research marker overlay banners the active
condition.

**Predicted watchability problems on first view:**
- Overlay zone text may collide with other PiPs (float + bounce).
  Needs visual audit at 1920×1080.
- Stream overlay colors may clash with the album cover depending on
  which album is playing.
- Research marker banner is probably fine, but it's full-width —
  competes with top-strip camera content.
- No on-screen legend for chat keyword vocabulary → viewers don't
  know how to participate.
- Activity header is caps-text; not styled per the design language
  document.

**Testable prediction:** visual audit under a real broadcast frame
(OBS preview or HLS preview) uncovers ≥ 3 issues needing polish
before go-live.

### 2.6 Audio

TTS via Kokoro 82M on CPU. Voice output routing defers to wireplumber
unless `HAPAX_TTS_TARGET=hapax-voice-fx-capture` is set and a voice-fx
preset is installed. The new voice-over-YouTube ducker (`hapax-ytube-
ducked`) is a separate sink that OBS/Chromium can target for music-
bed ducking — but not auto-enabled.

**Predicted audio behaviour:** default TTS audio goes to whatever
wireplumber routes to; music bed from YouTube-player continues at
full volume while Hapax speaks. Operator voice is not yet ducked.
No sidechain compression at mic input.

**Testable prediction:** operator's first speech with music playing
is audibly fighting the bed. If the ducker is installed and wired
by launch, this goes away.

### 2.7 Governance

Starts in `private` mode by default. Operator must explicitly switch
to `public` or `public_research` via the working-mode CLI. In private,
all person-mention surfaces render normally; in public, the redaction
surfaces engage per Phase 6 §4.

**Testable prediction:** the first mode transition (private → public)
produces no visible flicker in the compositor surface and no leaked
person-mentions in the /api/orientation response or the captions
(which won't render anyway, per §2.4).

---

## 3. Is that good enough?

This is the judgment call. The right "good enough" bar depends on
what the first session is *for*:

### 3.1 If the goal is: "prove the research instrument works at all"

**Good enough = YES**, conditional on:
- Research condition `cond-phase-a-persona-doc-qwen-001` logs reaction
  events with correct condition_id.
- Per-condition Prometheus slicing produces time-series.
- No privacy regression (78 tests green, drill green).
- Stream stays up for the session duration.

Everything else is observational. The instrument is the thing being
validated; it doesn't have to behave interestingly.

### 3.2 If the goal is: "run a watchable research livestream"

**Good enough = NO**, because:
- Closed-loop feedback is largely silent (§2.4).
- Captions absent means audience can't hear what Hapax says unless
  they unmute.
- Attention bids silent → one-sided attention economy.
- Chat queue fills but produces no visible review behaviour.

Watchability gaps are Continuous-Loop §3.3 – §3.7 exactly. Shipping
those six items is the difference between "research instrument" and
"livestream."

### 3.3 If the goal is: "launch with the strongest possible first
impression"

**Good enough = NO** until polish pass. Specific gaps:
- No on-screen chat-keyword legend.
- Overlay zone visual collisions possible.
- Activity header typography not design-language-aligned.
- No voice-over-YouTube ducking by default.
- Persona's first-minute utterance quality unverified (the 14-day
  validation window just opened 2026-04-17T13:58Z).

---

## 4. Recommendation

**Run a rehearsal session first.** A 30-minute private-mode session with
the operator alone talking through material. Measurements:

1. Activity distribution (target §2.2 prediction ±10%).
2. Persona coherence (target §2.1 test).
3. Overlay visual audit at 1920×1080 (target §2.5 zero-collision).
4. TTS output quality on a line with music playing (target §2.6).
5. No journal stacktraces, no privacy-regression failures.

If all five pass, run a public-mode rehearsal with a known-friendly
audience member (`agatha` or `simon`, both have active broadcast
consent). Measurements add:

6. Chat reactor fires on keyword hit (target §2.3).
7. Mode transition produces no flicker (target §2.7).
8. Full 60-minute uptime with zero unhandled errors.

If both rehearsals pass, the instrument is good enough for a public
research session with the `public_research` stream mode + scientific
caption register + research marker overlay.

Before launching the public research session, ship at minimum the
**Continuous-Loop §3.3 (chat-queue drain) + §3.4 (captions surface)**
so audiences can read what Hapax says and Hapax actually reviews chat
during `chat` activity. §3.5 – §3.7 are nice-to-have; §3.3 + §3.4 are
the watchability floor.

---

## 5. Open research questions for the operator

1. **What's the minimum viable launch surface?** Captions required or
   optional? (I recommend required.)
2. **Is Hapax's "scientific-substrate register" actually watchable
   for a non-researcher audience?** Currently uncalibrated. First
   validation is the rehearsal above.
3. **Does the activity-scoring telemetry (Continuous-Loop §3.2) need
   to be promoted to actual override before launch,** or do we
   accept the LLM-only choice on launch day and tune override later?
4. **Does the operator want a "first-30-minutes playbook"** with
   pre-session checks + escalation playbook, or is the existing
   drill harness sufficient?
5. **What's the explicit abort criterion during a session?** The
   mid-stream-consent-revocation drill covers the governance abort.
   Is there a "this is not going well, end stream" signal we should
   document?
6. **Substrate question:** Phase A is running on Qwen 3.5-9B. Is the
   first public session on this substrate, or do we require the OLMo
   scenario 2 deployment first? The scoping doc defers this to the
   data-sufficiency trigger (~2026-05-10); the operator's launch
   decision may be earlier.

---

## 6. Summary in one table

| Question | Answer |
|---|---|
| Will Hapax speak in persona-document register? | Yes, with high confidence. Live since 13:58Z. |
| Will activity selection respond to stimmung? | No. Telemetry only until §3.2 ships. |
| Will chat drive visible behaviour? | Partially. Preset switches work; bids + drain do not. |
| Will captions appear? | No. Cairo source registered but layout entry missing. |
| Will ducking attenuate music under voice? | Only if operator installs the sc4m preset pre-session. |
| Will governance hold under public mode? | Yes. 78 regression tests + matrix + drill all green. |
| Is the instrument "good enough" to start research? | Yes, per §3.1. |
| Is the instrument "good enough" for a watchable public livestream? | No, per §3.2. Close the gap with CL §3.3 + §3.4 minimum. |
| Is the instrument "good enough" for a strongest-first-impression launch? | No. Needs polish pass. |

**The operator's directive sequence — close Bayesian, finish
everything conceivable, polish assiduously, then launch — aligns
exactly with §3.2's "NO" becoming a "YES" by the time the livestream
begins.** This doc names the concrete items the polish pass has to
cover.
