# Antigrav (agy) gate witness - retired archive

**Original capture:** 2026-06-01T01:02:26Z, lane `delta`, task
`reform-fix-antigrav-activation-20260531`, authority
`CASE-CROSS-RUNTIME-COMMS-001`.

This file is retained only as a historical witness that the former Antigrav/agy
hook path once loaded a Hapax governance gate. It is no longer an operational
runbook or live recheck surface.

Current state:

- `scripts/hapax-antigrav` is a retired compatibility stub.
- It must not provision worktrees, wire hooks, claim tasks, spawn `agy`, or
  launch Antigravity.
- Any future agy capability must re-enter as measured supply leaves with
  route/resource/governance receipts.

Current recheck commands:

```bash
uv run pytest tests/hooks/test_antigrav_gate_enforcement.py \
  tests/hooks/test_antigrav_hook_adapter.py \
  tests/scripts/test_hapax_antigrav_launcher.py -q

./scripts/hapax-antigrav
```

Expected launcher result: non-zero refusal text naming Antigrav/agy retirement
before hooks, claims, worktrees, tmux, IDE launch, or `agy` execution.

Historical note: the 2026-06-01 capture used the then-live adapter command chain
to prove that an agy PreToolUse mutation payload reached `cc-task-gate.sh` and
failed closed without a claimed task. That historical fact does not authorize or
describe any current live Antigrav worker path.
