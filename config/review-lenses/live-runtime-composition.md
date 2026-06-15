---
lens_id: live-runtime-composition
version: 1
title: Composition with the LIVE Runtime
---

# Composition with the LIVE Runtime

## Checklist

- [ ] live-daemon-compose: The change composes with LIVE running daemons — restart ordering, socket/SHM contract continuity.
- [ ] event-loop-blocking: No blocking I/O or CPU burst added on an async/event-loop or GStreamer callback path.
- [ ] backpressure: Queues/buffers added have bounded size and a documented overflow policy.
- [ ] restart-storm: Unit/service changes cannot create restart loops (Restart=, StartLimit, watchdog interactions).
- [ ] runtime-witness: Composition claims carry a live-runtime witness (journal/probe output), not just unit-test greens.

## Verdict contract

Address every checklist item explicitly as pass / finding / NA in your review output.
