---
scope_amendment_schema: 1
pr: 4621
reviewed_head: 50ad69b96dcc0ac10551f37585358bdadf803721
reviewed_head_note: "the head the amendment was reviewed against; the amendment covers every commit on branch feat/receipt-resource-vector-absent-20260902 from e767794bf onward, because a head pinned in a file that later commits change can never equal the final head (review finding, 2026-09-04)"
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
