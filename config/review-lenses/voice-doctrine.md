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
- [ ] consent-egress: AUDIO/VOICE egress to air (TTS output, recordings, HLS/stream, captured mic audio) respects consent gating, fail-closed. SCOPE: this is the voice/broadcast egress surface ONLY — general data egress, LLM/eval-gateway calls (e.g. the coherence + composability eval plane on the LiteLLM `balanced` route, which the deliberative council already uses under the gateway's own config), and publication surfaces are out of scope here and are governed by the security, consent-provenance, and trust-boundary lenses; mark NA for non-audio egress.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
