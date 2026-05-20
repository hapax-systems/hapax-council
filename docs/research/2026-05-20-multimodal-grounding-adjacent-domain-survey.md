# Multimodal Grounding Adjacent Domain Survey

**Authority:** CASE-20260509-MULTIMODAL-
**Date:** 2026-05-20
**Kind:** Research packet (structured survey)

## 1. Unb-AIRy: Perceptual vs. Text-Grounded Assertions

### Interaction

The Unb-AIRy assertion plane currently treats all claims as text-grounded:
an assertion's epistemic status derives from its source text, citation chain,
and hedge calibration. Multimodal grounding introduces a second class —
perceptually-grounded assertions — where evidence comes from camera feeds,
IR sensors, or compositor output rather than text documents.

### Key distinction

Text-grounded and perceptually-grounded assertions are **not the same kind
of assertion** on the discursive plane. A text-grounded assertion carries
a citation chain that a reader can independently verify by following refs.
A perceptually-grounded assertion carries a temporal witness (timestamp,
sensor ID, freshness) that decays — it cannot be re-verified after the
perceptual window closes. This makes perceptual assertions inherently
more volatile and demands different staleness thresholds.

### Open question

Should the Unb-AIRy discursive plane maintain separate confidence tracks
for text-grounded vs. perceptually-grounded claims, or should they merge
into a unified posterior with a modality tag?

### Recommendation

**Yes — dedicated downstream request.** The assertion type system needs
a `grounding_modality` field (text/perceptual/multimodal) and the
discursive plane needs staleness-aware confidence decay for perceptual
claims.

## 2. Publication Hardening: Perception vs. Codebase as Evidence

### Interaction

The publication bus currently gates on codebase evidence: commit SHAs,
test results, PR receipts. Multimodal grounding opens a second evidence
channel — perceptual evidence (frame captures, audio witnesses, compositor
state snapshots). The question is whether perceptual evidence can serve as
publication evidence or whether it remains diagnostic-only.

### Concrete implication

A publication claim like "the compositor renders AoA panes correctly" currently
requires a PR with test results. With multimodal grounding, a 10-minute
frame capture run with no visual regressions could serve as publication
evidence — but only if the capture has provenance (camera ID, timestamp,
compositor version, effect state hash).

### Open question

What provenance metadata must a perceptual evidence artifact carry to be
accepted by the publication bus alongside codebase evidence?

### Recommendation

**No dedicated request yet.** The existing AVSDLC visual evidence contract
(`docs/methodology/avsdlc-visual-evidence-contract.md`) already defines
what visual evidence needs. Extend it with provenance fields rather than
creating a parallel system.

## 3. CHI 2027: Embodied Stigmergic Cognitive Mesh

### Interaction

The current CHI framing positions Hapax as a stigmergic cognitive mesh —
agents coordinate through shared artifacts on a filesystem-as-bus without
explicit message passing. Multimodal grounding adds embodiment: the system
perceives its physical environment (cameras, IR, audio) and its own rendered
output, closing a perception-action loop.

### Stance: Embodiment strengthens the contribution

**"Embodied stigmergic cognitive mesh" is a stronger contribution than the
current framing**, for two reasons:

1. **Novelty differentiation.** Pure stigmergic coordination (filesystem-as-bus,
   agent traces as coordination signals) has precedent in swarm intelligence
   and multi-agent systems literature. Adding embodiment — where the mesh
   perceives its own outputs and environmental state — moves the contribution
   from "distributed coordination pattern" to "situated cognition architecture,"
   which has fewer direct precedents in the HCI/CSCW literature.

2. **Empirical grounding.** The current framing is primarily architectural (how
   agents coordinate). Embodiment provides a measurable empirical dimension:
   does perceptual grounding improve claim accuracy? Does self-perception of
   compositor output reduce visual regressions? These are testable hypotheses
   that strengthen a CHI submission over a purely architectural contribution.

### Open question

Does embodiment introduce a "homunculus problem" — does a system that
perceives its own output need to distinguish self-generated signals from
environmental signals to avoid feedback loops?

### Recommendation

**Yes — update CHI framing document.** The embodiment angle should be
integrated into the research framing before submission planning.

## 4. Daimonion: Audio Grounding as Text-Mediation Bypass

### Interaction

The daimonion voice pipeline currently text-mediates all environmental
awareness: perception fusion produces text summaries, the LLM reads them,
and TTS speaks the result. Audio grounding could bypass text mediation
for certain operations.

### Specific text-mediated operation that audio grounding could bypass

**Operator presence detection.** Currently, the system reads IR person
detection → text summary → LLM interprets "person present" → adjusts
speech behavior. With audio grounding, the system could detect operator
vocalizations directly via STT activity patterns (speech onset, voice
activity detection) and adjust behavior without LLM mediation. The
relevant signal is `stt_voice_activity_detected` — a binary signal
from the STT frontend that currently triggers conversation mode but
could also serve as a low-latency presence/attention indicator.

### Open question

What is the latency budget for audio-grounded presence detection vs.
the current IR → text → LLM path? If audio grounding is faster, should
it run in parallel or replace the text-mediated path?

### Recommendation

**No dedicated request yet.** The existing voice pipeline already has
the STT activity signal; wiring it as a presence indicator is a small
integration task, not a research effort.

## 5. Compositor: Self-Perception of Rendered Output

### Interaction

The compositor renders camera feeds through a shader chain, producing
the final broadcast frame. If the system perceives this rendered output
(via the final frame classifier or a feedback camera), it closes a
self-perception loop: the system sees what it has done.

### Architecturally non-trivial consequence

**Effect drift becomes observable from within.** Currently, the drift
engine selects effects based on Stimmung, affordance scores, and timer
state — but it has no direct evidence of the visual result. If the
system perceives the rendered frame, it can evaluate whether the chosen
effects achieved the intended aesthetic. This creates a closed-loop
control system for visual expression: intent (Stimmung) → render
(shader chain) → perceive (final frame classifier) → adjust (drift
parameters). The non-trivial part is that the feedback latency (frame
capture → classification → drift adjustment) must be slower than the
drift engine's own tick rate to avoid oscillation — the system needs a
damping mechanism to prevent hunting between effect states.

### Open question

Should self-perception of compositor output feed into the temporal
bands (as a form of "visual retention") or remain a separate feedback
channel?

### Recommendation

**Yes — dedicated downstream request.** The closed-loop visual control
system has architectural implications for drift engine timing, damping,
and the relationship between Stimmung and perceived visual state.

## Cross-References

| Domain | Grounding inventory ref | Downstream request needed |
|--------|------------------------|--------------------------|
| Unb-AIRy | Perceptual assertion type | Yes |
| Publication hardening | AVSDLC visual evidence contract | No (extend existing) |
| CHI 2027 | Embodied mesh framing | Yes (update framing doc) |
| Daimonion | STT activity signal | No (small integration) |
| Compositor | Final frame classifier feedback | Yes |
