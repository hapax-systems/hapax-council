---
scope_amendment_schema: 1
pr: 4621
reviewed_head: 2613b4c5b78faec510e40ed096449f15c4aa2276
reviewed_blobs:
  config/quota-spend-ledger-fixtures.json: 7497affa9f8fbd21906718549f0c070d47218377
  scripts/hapax-glmcp-reviewer: 58e776d9770e55acc09cca0b154b22fc9012ab78
  scripts/hapax-quota-telemetry-writer: 8901722eb4281e595a82b35b46f12bb375602aef
  scripts/vulture_whitelist.py: af7824df31656a5f8d1fd29d475c3117cee22313
  shared/quota_spend_ledger.py: ced85952c509be105cb095d3086afeb4d6018553
  tests/docs/test_capability_consideration_completeness_contract.py: 8ec0e9f4974e70ce9470c187e7bfd13150f1f879
  tests/scripts/test_hapax_glmcp_reviewer.py: a3f70634dae2b7d6ae61ad534a8d2cb7651a7abb
  tests/scripts/test_hapax_quota_telemetry_writer.py: f71c703c39f31f0c2cf250389afc4f07219c7d5f
  tests/shared/test_platform_capability_registry.py: 94c93f797d76b3275eaa815f630c08f0d4b34683
  tests/shared/test_quota_spend_ledger.py: cf46a92b9ef2a059a94b2c81921e48838c1bba8e
task_ids:
  - receipt-resource-vector-absent-not-zero-20260902
  - compute-unit-absent-never-inferred-20260902
authority_case: CASE-CAPABILITY-ROUTING-001
parent_spec: 30-areas/hapax/frame/RESEARCH-latent-recurrent-reasoning-20260902.md
risk_tier: T1
amendment_authorized_by: operator
authority_evidence_ref: coord-escape-grant:72955cf428878def9e31ed18c34b9929
authorized_at: "2026-09-04"
source_mutation_authorized: true
runtime_mutation_authorized: false
provider_spend_authorized: false
mutation_scope_refs:
  - config/quota-spend-ledger-fixtures.json
  - docs/runbooks/pr-4621-receipt-schema-2.md
  - scripts/hapax-glmcp-reviewer
  - scripts/hapax-quota-telemetry-writer
  - scripts/vulture_whitelist.py
  - shared/quota_spend_ledger.py
  - tests/docs/test_capability_consideration_completeness_contract.py
  - tests/scripts/test_hapax_glmcp_reviewer.py
  - tests/scripts/test_hapax_quota_telemetry_writer.py
  - tests/shared/test_platform_capability_registry.py
  - tests/shared/test_quota_spend_ledger.py
---

# PR #4621 receipt-schema authority and migration runbook

This checked-in amendment supplements both task rows for PR #4621. The original
rows named only the shared ledger model and selected tests even though schema 2
also changes the checked-in fixture, the GLMCP paid-route receipt producer, the
live telemetry receipt consumer, the dynamic-call whitelist, and their tests.
The complete mutation surface is declared above; none of those files is an
incidental or silent omission.

`scripts/hapax-glmcp-reviewer` is a live provider-spend path. This amendment
authorizes its source change under the existing T1 authority case. It does not
authorize a provider call, live spend, deployment, or runtime-state mutation.
Verification uses fake local fixtures and stubs only.

## Review pin

The bounded review artifact is `reviewed_head` plus `reviewed_blobs`.
`reviewed_head` records the checkout head at review time; `reviewed_blobs`
records the exact reviewed file contents, including the uncommitted review
fixes based on that head. Each value is a Git blob hash of the file bytes
(`git hash-object -- <path>`). Every declared mutation path is pinned, including
the contract test, except this manifest document itself, which cannot carry
its own raw blob hash. Its exact front-matter schema, authority and mutation
scope remain independently asserted by the contract test.

Verification reads only those paths in the current checkout. It needs no
historical commit objects, ancestry, remote fetch or repository-wide diff;
shallow merge-queue checkouts and unrelated integration changes are valid.
Changing or deleting a reviewed path fails with: "the runbook reviewed X at Y;
path Z has changed since — re-review or re-pin" (with its reviewed blob hash).
After reviewing an intended change, record the checkout's `git rev-parse HEAD`
and regenerate the affected `reviewed_blobs` entries with `git hash-object --
<path>`, then rerun the contract test. Do not repin unreviewed changes merely
to clear the check. Keep this explanation in the body, outside the exact schema.

## Schema-1 compatibility contract

Readers accept historical `SpendReceipt` schema 1 and migrate it in memory to
schema 2 by retaining every historical field and supplying explicit absence for
the schema-2-only resource vector. Unknown receipt schemas still fail closed.
The telemetry writer likewise accepts legacy
`hapax.glmcp_payg_spend.v1` relay envelopes, validates their spend contract, and
emits schema 2. Its output therefore preserves both ledger history and relay
history before recomputing paid-route cap state.

Recheck:

```text
UV_CACHE_DIR=/tmp/wt-receipts-uv-cache uv run pytest -q tests/shared/test_quota_spend_ledger.py tests/scripts/test_hapax_quota_telemetry_writer.py tests/scripts/test_hapax_glmcp_reviewer.py tests/shared/test_platform_capability_registry.py tests/docs/test_capability_consideration_completeness_contract.py
UV_CACHE_DIR=/tmp/wt-receipts-uv-cache uv run ruff check shared/quota_spend_ledger.py scripts/hapax-quota-telemetry-writer tests/scripts/test_hapax_quota_telemetry_writer.py tests/docs/test_capability_consideration_completeness_contract.py
UV_CACHE_DIR=/tmp/wt-receipts-uv-cache uvx ruff@0.16.1 format --check shared/quota_spend_ledger.py scripts/hapax-quota-telemetry-writer tests/scripts/test_hapax_quota_telemetry_writer.py tests/docs/test_capability_consideration_completeness_contract.py
```

## Compute-unit drift recovery

`r7_compute_unit_drift` refuses different provider-reported compute-unit values
for the same `run_id`. The refusal names the run and receipt IDs and points
here; it must remain fail-closed through telemetry's live-ledger validation.

1. Preserve a copy of the current live ledger (the configured
   `HAPAX_QUOTA_SPEND_LEDGER_LIVE`, or
   `~/.cache/hapax/orchestration/quota-spend-ledger-live.json`) and the original
   relay receipts under `~/.cache/hapax/relay/receipts/` before reconciliation.
   Preserve all spend history and original relay receipts; never discard spend,
   reset the ledger to fixtures, or delete a receipt to make validation pass.
2. Recheck the preserved ledger without writing it:
   `uv run scripts/check-quota-spend-ledger --fixture <preserved-ledger.json>`.
   If the writer rejected new relay observations, the last valid ledger may
   pass this recheck; also inspect the named incoming receipts and run ID.
3. Reconcile the named receipts against provider evidence. Prepare a corrected
   ledger and relay set separately, retaining the original evidence and every
   spend ID, cost and accounting/reconciliation record. Correct a wrongly
   associated run ID or a mistranscribed provider field only with evidence;
   never derive compute units from tokens, latency or requested effort. Record
   the correction and its evidence in the governed task. If the provider
   conflict is unresolved, keep the refusal and escalate through that task.
4. Validate the reconciled copy with the same read-only checker using its path.
   Once the governed correction is applied to the ledger and relay set, rerun
   `uv run scripts/hapax-quota-telemetry-writer --base <reconciled-ledger.json>
   --json`. Supplying the preserved, reconciled base retains historical spend
   while the writer ingests the corrected receipts and recomputes budget state.
