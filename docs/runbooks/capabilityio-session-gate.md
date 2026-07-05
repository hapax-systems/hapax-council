# CapabilityIO SESSION Gate — governed relay-send boundary

Task: `cc-task-capabilityio-session-gate-send-20260705` (AuthorityCase CASE-CAPACITY-ROUTING-001;
parent spec `30-areas/hapax/reins-capabilityio-wiring-sequencing-2026-07-05.md`). Prerequisite:
PR #4432 (adapter admit/launch wiring).

## What it is

`SendCapableAdapter.send()` in `shared/capability_adapter_protocol.py` is the authority-checked
SESSION egress boundary for relay sends to live worker harnesses. One call does, in order:

1. **Authority FIRST** — `_require_launch_authority(decision, op="send")`: a non-`LAUNCH`
   decision (or `launch_allowed=False`) raises `AuthorityViolation` before ANY side effect
   (no relay execution, no receipt).
2. **Wiring guards** — the decision's platform must match the adapter's `PLATFORM`
   (`ValueError` on mismatch); the platform must have a canonical relay row; the wrapper must
   exist on disk (`FileNotFoundError` otherwise — fail closed, never substitute a path).
3. **Canonical relay** — executes `scripts/hapax-<platform>-send --session <lane> -- <message>`
   (the already-governed tmux transports). The platform→wrapper table
   `_SESSION_SEND_RELAYS` is the ONLY per-platform variation point.
4. **Receipt** — appends one `SessionSendReceipt` JSON line to the evidence bus.

## Capability is type-level

Send-capable: `ClaudeAdapter`, `CodexAdapter`, `VibeAdapter` (mix in `SendCapableAdapter`).
Not send-capable: `AgyAdapter`, `BudgetAuthorityAdapter` (api), `ReviewSeatAdapter` (glmcp),
`RetiredAntigravFailureClassifier` — `send` is absent from their MRO. There is deliberately no
`supports_send` runtime flag anywhere, and `send` cannot be overridden in a subclass
(`__init_subclass__` guard) — both are test-pinned in `tests/test_capability_adapter_protocol.py`.

## The evidence bus

- Path: `~/.cache/hapax/sdlc-routing/session-send-receipts.jsonl`
  (env override `HAPAX_SESSION_SEND_RECEIPTS`; persistent NVMe, NOT tmpfs — same
  tmpfs-swap-trap rationale as `shared/gate_log.py`).
- One JSON line per governed egress: route/decision/task/lane identifiers, the authority result
  (`authority_action`, `authority_launch_allowed`), the relay wrapper, exit code, and outcome
  (`sent` / `failed`).
- **Privacy:** the receipt NEVER carries the message body — only `message_sha256` +
  `message_chars` (the send route is privacy/secret-sensitive).

## The Reins consumer (built-ahead, honest-dark)

`reins/internal/model/sendgate.go` reads the bus and lights the send-gate ONLY on a receipt with
`receipt_schema=1`, `op=session_send`, `outcome=sent`. Missing file, corrupt lines, failed
relays, and unknown schemas all render the honest-dark `NOT WIRED` footer. Test-pinned in
`sendgate_test.go` (`TestSendGateLightsOnlyOnSessionGateReceipt`) and
`injection_test.go` (`TestComposerSessionGateFooterLightsOnlyOnEvidence`); reins-side commit
`7c30e2c` on `reins-cockpit-overhaul-20260627`.

## Scoped exceptions (recorded per spec §7, with re-arm plan)

1. **Reins-originated egress handoff is not yet bound.** The reins confirm still stages the
   compose locally; the LIVE footer/status truthfully reports the council-side boundary, not a
   reins-side provider send. Re-arm: the CapabilityIOEnvelope KIND-body slice (sequenced after
   R1/R4 + Phase-1 call-kind per the parent spec §2) binds the reins confirm to `adapter.send`.
2. **Legacy direct wrapper callers remain.** `scripts/cc-pr-review-dispatch.py` and
   `agents/coordination_tui/data.py` still invoke `hapax-*-send` directly; they predate the gate
   and are outside this task's mutation scope. Re-arm: reroute them through platform adapters in
   a follow-on slice so every Python-side relay send mints a SESSION receipt.

## Operational checks

- Latest evidence: `tail -n 3 ~/.cache/hapax/sdlc-routing/session-send-receipts.jsonl`
- Regression pins: `uv run pytest tests/test_capability_adapter_protocol.py -q`
- Reins pins: `go test ./internal/model/ ./internal/grammar/` in the reins clone.
