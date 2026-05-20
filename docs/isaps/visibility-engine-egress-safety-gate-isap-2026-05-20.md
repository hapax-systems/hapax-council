# ISAP: Visibility Engine Egress Safety Gate

**Date**: 2026-05-20
**Request**: REQ-20260510-visibility-engine
**Authority case**: CASE-VISIBILITY-ENGINE-001
**Sequence**: Work tree item 4 of 6

## Problem

The publish orchestrator fan-outs artifacts to public surfaces without
runtime safety controls. No rate limiting, no global kill switch, no
hold queue for human review before egress. Before scaling to "10s of
drops per day," these controls must exist.

## Proposed Solution

Add `EgressSafetyEnvelope` to `shared/publication_hardening/` that the
publish orchestrator checks before dispatching any artifact. Three
layers:

### 1. Kill Switch

File-based: `~/hapax-state/publish/KILL_SWITCH`. If this file exists,
all egress is halted regardless of artifact state. The orchestrator logs
the block and increments a Prometheus counter. The operator creates or
removes this file to toggle.

### 2. Rate Policy

Sliding-window rate limiter using the orchestrator's existing log
directory. Count successful dispatches (`ok` results) in the last N
hours. Default: 20 artifacts per 24h, configurable via
`HAPAX_EGRESS_RATE_LIMIT` and `HAPAX_EGRESS_RATE_WINDOW_HOURS`.
Artifacts exceeding the rate are deferred (remain in inbox for retry).

### 3. Hold Queue

New `~/hapax-state/publish/held/` directory. When the publication
hardening gate returns HOLD, artifacts move here instead of staying in
inbox for retry. Held artifacts require explicit operator action:
move back to inbox (after fixing the issue) or to `dropped/`.

## Integration Point

`PublishOrchestrator._tick()` calls `EgressSafetyEnvelope.check()`
before processing each artifact. The envelope returns one of:
`PROCEED`, `RATE_LIMITED`, `KILL_SWITCHED`, `HELD`.

## Effort: Small (1 session)
## Dependencies: none (publication_hardening and orchestrator exist)

## Evidence Requirements

- Unit tests for rate limiter, kill switch, hold queue
- Existing orchestrator tests still pass
- Prometheus counter for each block type
