# mid-stream-consent-revocation drill — 2026-04-17

**Description:** Re-verify that revoking a contract mid-stream immediately closes downstream person-mention surfaces (re-run of Phase 6 §7 drill).

**Mode:** dry-run
**Started at:** 2026-04-17T13:07:08.159340+00:00

## Pre-checks

- ❌ revoke_contract() importable

## Steps executed

- Start a mock public stream
- Confirm a person-mention surface is visible
- Invoke revoke_contract() on the covering contract
- Watch the surface close within the registry cache TTL

## Post-checks

- ✅ surface closed after revocation — operator verifies the 403 / empty response manually

## Outcome

**Passed:** no

## Operator notes

Live run (by alpha, 2026-04-17T13:07Z):

- **Drill-harness finding (same as pre-stream-consent):** import probe on `shared.consent.revoke_contract` is stale. Real location is `shared.governance.consent.revoke_contract` (line 214). The pre-check reported ❌ for this reason — not because the function is missing.
- Test-suite stand-in: since no mock public stream was up, I ran the e2e revocation tests that substitute for the drill's core invariant: `tests/test_consent_scenario_e2e.py::TestConsentScenarioE2E::test_step6_revocation_cascades` + `test_step7_consent_reoffered_after_revocation` — **both passed** in 1.38s.
- Next live run during an actual stream: operator invokes `revoke_contract()` on a covering contract mid-stream, watches the person-mention surface 403 within the registry cache TTL (~60s) per Phase 6 §7. This is the canonical drill — the e2e tests verify the same contract at unit level.
