# G12 Crow-Chat Attestation Gate

G12 dispatch enforcement is enabled with either
`HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION=1` or
`HAPAX_METHODOLOGY_REQUIRE_CROW_CHAT_ATTESTATION=1`.

When enabled, mutable dispatch must carry one of these per-dispatch proofs:

- Crow-chat attestation:
  - `HAPAX_METHODOLOGY_ORIGIN_SURFACE=crow_chat`
  - `HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF=<operator-attestation:reins:crow_chat:v1:...>`
  - The ref is an HMAC over `origin_surface`, `task_id`, `lane`, ruling, and version.
  - The dispatcher or launcher process must have the governed validation key in
    `HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY` or `HAPAX_OPERATOR_ATTESTATION_HMAC_KEY`.
- Signed breakglass:
  - `HAPAX_G12_SIGNED_BREAKGLASS_REF=<operator-breakglass:reins:g12:v1:...>`
  - `HAPAX_G12_SIGNED_BREAKGLASS_REASON=<emergency reason>`
  - The ref is an HMAC over `task_id`, `lane`, reason, ruling, and version.
  - The dispatcher or launcher process must have the governed breakglass key in
    `HAPAX_G12_BREAKGLASS_HMAC_KEY` or `HAPAX_OPERATOR_ATTESTATION_HMAC_KEY`.

The HMAC keys are validation-only process secrets. Launchers use them before
`cc-claim` and before worker spawn, then scrub them before executing Codex or
Claude. Do not put key values in task notes, PRs, command bodies, logs, or
runbook examples.

Normal recovery path:

```bash
scripts/hapax-methodology-dispatch \
  --task <cc-task-id> \
  --lane <lane> \
  --platform codex \
  --mode headless \
  --launch \
  --origin-surface crow_chat \
  --operator-attestation-ref <crow-chat-issued-ref> \
  --require-crow-chat-attestation
```

Emergency recovery path when Crow-chat attestation issuance is unavailable:

```bash
scripts/hapax-methodology-dispatch \
  --task <cc-task-id> \
  --lane <lane> \
  --platform codex \
  --mode headless \
  --launch \
  --signed-breakglass-ref <signed-breakglass-ref> \
  --signed-breakglass-reason "<reason>" \
  --require-crow-chat-attestation
```

A taskless mutable launch is refused while enforcement is on. Split relay MQ
broadcasts into one attested dispatch per lane because each ref binds exactly
one `task_id` to one lane.

Recheck commands:

```bash
uv run pytest tests/shared/test_g12_crow_chat_gate.py
uv run pytest tests/shared/test_relay_mq.py tests/scripts/test_cc_claim.py
uv run pytest tests/scripts/test_g12_crow_chat_launchers.py
uv run pytest tests/scripts/test_hapax_methodology_dispatch.py::test_g12_gate_requires_crow_chat_attestation_when_enforced tests/scripts/test_hapax_methodology_dispatch.py::test_g12_signed_breakglass_ref_reaches_dispatch_receipt_and_event
bash -n scripts/cc-claim scripts/hapax-codex scripts/hapax-codex-headless scripts/hapax-claude scripts/hapax-claude-headless scripts/hapax-methodology-dispatch
```

Those checks exercise taskless refusal, task/lane-bound refs, single-lane MQ
dispatch, launcher key scrubbing, remote payload propagation, and dispatcher
failure next-action text.
