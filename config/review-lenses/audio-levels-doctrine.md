---
lens_id: audio-levels-doctrine
version: 1
title: Levels-via-MIDI Doctrine
---

# Levels-via-MIDI Doctrine

## Checklist

- [ ] levels-via-midi: Level changes go through MIDI/operator trims, not node volume mutations.
- [ ] lufs-governance: Loudness targets and LUFS panic thresholds are respected.
- [ ] ducking-engine-only: Ducking changes go through the governed ducking engine, nowhere else.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
