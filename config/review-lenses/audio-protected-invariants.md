---
lens_id: audio-protected-invariants
version: 1
title: Audio PROTECTED INVARIANTS
---

# Audio PROTECTED INVARIANTS

Reference: docs/audio-topology-reference.md (single source of truth).

## Checklist

- [ ] golden-chain-intact: The golden chain (TTS → voice-fx → loudnorm → MPC → L-12 → livestream-tap → broadcast) is untouched, or the change to it carries recorded approval.
- [ ] no-mpc-l12-bypass: No path bypasses MPC/L-12.
- [ ] no-unauthorized-tap: Nothing new targets hapax-livestream-tap playback from unauthorized sources.
- [ ] pipewire-confd-frozen: ~/.config/pipewire/pipewire.conf.d/ is untouched, or the change carries recorded approval.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
