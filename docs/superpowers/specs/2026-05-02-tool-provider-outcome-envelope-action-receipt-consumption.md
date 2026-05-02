# Tool Provider Outcome Envelope: Action Receipt Consumption Note

Status: implementation note for `tool-provider-outcome-envelope`

This slice adds a contract only. It does not wire the bridge governor, CPAL,
destination routing, or live action-receipt construction.

## Contract

`shared.tool_provider_outcome.ToolProviderOutcomeEnvelope` records one
tool/model/provider call result with:

- route identity: `provider_id`, `provider_kind`, `model_id`, `tool_id`,
  `route_id`, `route_ref`
- result state: `success`, `blocked`, `error`, or `unsupported_claim`
- source mode: acquired sources, supplied evidence, no acquisition, or failed
  acquisition
- evidence refs: acquired source refs, source-acquisition witness refs,
  supplied-evidence refs, redaction refs, and error refs
- public/privacy state: redacted/private/blocked outputs cannot support public
  claims
- authority ceiling: no claim, internal only, speculative, evidence-bound,
  posterior-bound, or public-gate-required

Every fixture pins `witnessed_world_truth=false`. A provider result can support
an action receipt as evidence that a route acquired sources or reasoned over
supplied evidence, but it cannot by itself prove that the intended world effect
occurred.

## Action Receipt Consumption

Future `action-receipt-outcome-grounding-contract` work can consume these
envelopes by requiring:

1. `result_status == "success"`
2. either `can_support_fresh_source_claim()` or
   `can_support_supplied_evidence_claim()`
3. `action_receipt_consumption_refs()` is non-empty
4. public receipts require `can_support_public_claim()` and a later public gate
5. blocked, error, and unsupported-claim rows are recorded as failed or held
   attempts, not success

The action receipt should preserve the upstream ceiling. A supplied-evidence
result remains supplied-evidence-only unless another route independently
acquires sources and provides acquisition evidence.
