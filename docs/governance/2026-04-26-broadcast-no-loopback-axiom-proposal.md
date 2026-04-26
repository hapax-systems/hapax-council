# Axiom proposal: `broadcast_no_loopback`

**Status:** proposed (operator review required)
**Date:** 2026-04-26
**Origin:** cc-task `feedback-prevention-loop-detector`; researcher report a09d834c (L-12 broadcast feedback-loop diagnosis 2026-04-25)

## Proposed registry entry

```yaml
  - id: broadcast_no_loopback
    text: >
      Broadcast egress (RTMP / HLS / V4L2 fanout from studio_compositor) MUST
      NEVER loop back into the L-12 capture surface or any other
      pre-broadcast audio bus. This is the explicit inverse of
      feedback_l12_equals_livestream_invariant: anything entering broadcast
      must leave the broadcast tree, never re-enter it. Enforced
      structurally by the L-12 USB capture narrowing (PR #1471, post-2026-04-25
      14→4 channel binding) and at runtime by the per-channel
      feedback-loop detector (agents/studio_compositor/feedback_loop_detector.py).
    weight: 75
    type: softcoded
    created: "2026-04-26"
    status: active
    supersedes:
    scope: domain
    domain: broadcast
```

## Rationale

The constitutional axiom `feedback_l12_equals_livestream_invariant` (operator
feedback memory) covers the forward direction: anything entering the L-12
must reach broadcast. This proposal codifies the **inverse**: nothing leaving
broadcast may re-enter the L-12 (or any pre-broadcast audio bus).

Without the inverse codified as a domain axiom:

* PipeWire reconnect events that re-create the L-12 USB capture binding
  with default 14-channel layout silently re-introduce the AUX10/11 PC return
  path that PR #1471 narrowed away.
* Manual operator routing changes during a livestream can wire broadcast
  back into the L-12 with no governance flag.
* The S-4 loopback config (`hapax-s4-loopback.conf`) carries the same
  structural pattern and would need its own narrowing.

The axiom gives the runtime feedback-loop detector a constitutional surface
to refuse-as-data against; the refusal-log entry written on each trigger
references this axiom by name.

## Weight justification (75)

* Below `corporate_boundary` (90) and constitutional axioms (85-100): this
  is a domain rule, not a constitutional one.
* Above mere convenience: a broadcast feedback loop is monetization-affecting
  (ContentID flag risk, livestream listener attrition) and operator-facing
  (sustained tone is physically taxing per `feedback_no_blinking_homage_wards`
  audio analog).
* Comparable to `interpersonal_transparency` minus the constitutional
  invariant load.

## How the detector enforces

* Runtime: 14-channel parec capture → FFT analyzer → smooth-mute envelope on
  trigger.
* Refusal data: each trigger appends to `/dev/shm/hapax-refusals/log.jsonl`
  with `axiom: broadcast_no_loopback`.
* Awareness state: `feedback_risk` block on `/dev/shm/hapax-awareness/state.json`
  surfaces the trigger to operator-facing dashboards.
* Prometheus: `hapax_feedback_loop_detections_total{channel_aux}` +
  `hapax_feedback_loop_auto_mute_seconds_total`.

## Operator action required

Append the proposed registry entry to `axioms/registry.yaml`. The
`registry-guard.sh` hook blocks programmatic edits to that file by design;
this proposal is the alpha-side artifact that operator review can accept
or modify before merging.

If the operator declines, the runtime enforcement (detector + auto-mute)
still ships — only the refusal-log axiom tag would need to point to a
different identifier.
