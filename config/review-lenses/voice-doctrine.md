---
lens_id: voice-doctrine
version: 1
title: Voice Doctrine
---

# Voice Doctrine

## Checklist

- [ ] never-cut-music: No path introduced that stops or ducks music outside the governed ducking engine.
- [ ] witness-discipline: Voice events emit their required witnesses; chosen silence is classified as abstention, never silently dropped.
- [ ] destination-gates: TTS/audio destinations stay behind their gates; no new direct sink targeting.
- [ ] consent-egress: Anything leaving the machine respects consent gating, fail-closed. AUDIO/VOICE egress to air (TTS, recordings, HLS/stream, captured mic) must stay behind the broadcast consent gates. DATA/LLM egress on the shared LiteLLM gateway that matches the established eval-plane pattern the deliberative council already uses — e.g. coherence/composability classification on the `balanced` route, gateway-config-gated, on the operator's own content — is consent-gated and PASSES; raise a finding only for a NEW unreviewed external sink, an ungated/fail-open egress of sensitive or third-party data, or PII/legal-name leakage.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
