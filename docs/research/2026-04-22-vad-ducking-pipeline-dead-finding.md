---
title: VAD-ducking pipeline is dead — Bundle 1 audit framing needs revision
date: 2026-04-22
status: research finding; no code change in this PR
related:
  - docs/superpowers/audits/2026-04-20-3h-work-audit-remediation.md (Bundle 1)
  - docs/superpowers/specs/2026-04-18-audio-pathways-audit-design.md
  - agents/hapax_daimonion/vad_state_publisher.py
  - agents/hapax_daimonion/voice_gate.py
  - agents/hapax_daimonion/conversation_pipeline.py
  - agents/hapax_daimonion/cpal/perception_stream.py
  - agents/studio_compositor/vad_ducking.py
---

## Question

Audit Bundle 1 ("Phantom-VAD completion (alpha)") frames a 5-line fix:
"Wire `voice_gate.evaluate_and_emit()` into
`agents/hapax_daimonion/vad_state_publisher.py:59` before
`publish_vad_state(True)`." This investigation set out to apply the fix.

## What was already in code

`vad_state_publisher.py::VadStatePublisher` already wires the gate
correctly. Lines 86-114 invoke `voice_gate.evaluate_and_emit` on
`UserStartedSpeakingFrame`, falling open when no
`embedding_match_provider` is supplied. Lines 116-135 emit the
appropriate `publish_vad_state(True/False)` calls based on the
gate decision. The gate-wiring work was completed in a prior PR.

So the audit's literal text is already done.

## What is actually broken

`VadStatePublisher` is dead code in production. Tracing every live
call site:

| Symbol | Defined | Called from |
|---|---|---|
| `VadStatePublisher` class | `vad_state_publisher.py:60` | only `pipeline.py:198` |
| `pipeline.build_pipeline_task()` | `pipeline.py:142` | nowhere |
| `publish_vad_state(True)` | `vad_ducking.py:60` | only `vad_state_publisher.py:126` |

The active conversation pipeline is `ConversationPipeline`
(`conversation_pipeline.py:64`), constructed in
`pipeline_start.start_conversation_pipeline` and started via
`pipeline_lifecycle.start_pipeline`. `ConversationPipeline.start()`
opens audio output, prewarms the LLM, and creates a frustration
detector. **It does not instantiate `VadStatePublisher`. It does not
hook any pipecat `FrameProcessor` chain.** The `pipecat.frames`
imports in `vad_state_publisher.py` are vestigial — the pipecat
processor architecture was retired in favor of CPAL.

CPAL's perception path lives in
`cpal/perception_stream.py::PerceptionStream`. It reads
`self._buffer.speech_active` from `ConversationBuffer` and emits a
`PerceptionSignals` snapshot consumed by `cpal/evaluator.py`. It
**never calls `publish_vad_state`** and **never invokes
`voice_gate`**.

## Live system state

`/dev/shm/hapax-compositor/voice-state.json` is `{"operator_speech_active": false}`
with mtime ~5 hours stale at the time of investigation
(2026-04-22 02:00 UTC; mtime 2026-04-21 20:58 local). The file
exists because of FINDING-F's startup baseline write
(`run_inner.py:284-289`), but nothing has ever flipped it to `true`.

`vad_ducking.DuckController` polls this file. Because it never
transitions to `true`, the duck **never fires** in either direction:

- not on operator speech (so YT crossfeed is not ducked when the
  operator talks),
- not on YT crossfeed (because the gate-on-Started branch is
  unreachable).

The audit's premise — "phantom-VAD ducks fire on YT crossfeed and
need to be suppressed" — is the opposite of what the code does
right now. The duck doesn't fire at all. The operator's pain
("hapax vox still coming into l12 from pc super hot") routes
through `lssh-012` (HAPAX_TTS_TARGET bypass), not phantom-VAD.

## Implications for the audit

Bundle 1's fix as written would touch only dead code. The actual
remediation must do one of:

**Option A — wire publish_vad_state from CPAL's PerceptionStream.**
`PerceptionStream.update()` already knows `speech_active`. Add a
call to `publish_vad_state(speech_active)` on transition (only on
edge to avoid 30 ms write storms) and gate the True edge through
`voice_gate.evaluate_and_emit` with a `SpeakerIdentifier`-backed
provider supplied by `VoiceDaemon._speaker_identifier`. ~25 lines
plus tests.

**Option B — leave the path dead.** If the operator's broadcast
audio is solved by `lssh-012` (HAPAX_TTS_TARGET bypass) and there
is no demonstrated phantom-VAD ducking issue, the cheapest fix is
to delete `vad_state_publisher.py`, `pipeline.py::build_pipeline_task`,
and the unused `voice_gate.evaluate_and_emit` callsite. Reduces
dead-code surface that misleads future audits.

**Option C — revive pipecat as a parallel architecture.** Out of
scope for any current livestream-shepherd task. Listing for
completeness only.

The blocking question for the operator is whether the duck-on-
operator-speech behavior is desired at all. The current audio
topology (Evil Pet + S-4 broadcast routing, phase A complete) may
have made the duck obsolete. If so, Option B is the right answer
and Bundle 1 closes as "remediated by deletion".

## Recommendation

Mark audit Bundle 1 as **needs-redesign** rather than ready-to-ship.
The 5-line framing was wrong because the audit was written against
the pre-CPAL code and didn't notice the path went dead. Pick
between Option A and Option B based on the operator's product call
on whether the duck-on-operator-speech behavior is still wanted.

## Non-goals for this PR

- No code change. The vad_state_publisher / voice_gate modules stay
  in place pending the operator's product call.
- No deletion. Option B requires confirmation before removing
  modules.
- No CPAL wiring. Option A requires a separate PR with tests for
  the edge-detection logic and the gate provider.
