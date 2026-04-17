# pre-stream-consent drill — 2026-04-17

**Description:** Verify every person-mention surface is covered by an active broadcast consent contract before going public.

**Mode:** dry-run
**Started at:** 2026-04-17T13:07:08.050051+00:00

## Pre-checks

- ✅ axioms/contracts/ exists
- ❌ shared.consent.ConsentRegistry importable

## Steps executed

- Read every active contract from axioms/contracts/
- Enumerate every person-mentioning surface
- Verify each surface has at least one contract holder in broadcast scope
- Record any surface without coverage as a gate failure

## Post-checks

- ✅ every person-surface has broadcast coverage — operator verifies manually and annotates

## Outcome

**Passed:** no

## Operator notes

Live run (by alpha, 2026-04-17T13:07Z):

- `axioms/contracts/` inventory: 3 active contract files (`contract-agatha.yaml`, `contract-guest-2026-03-30.yaml`, `contract-simon.yaml`).
- **Drill-harness finding:** `shared.consent.ConsentRegistry` is not the right import path — the class lives at `shared.governance.consent.ConsentRegistry` (also at `logos._governance.ConsentRegistry`). The `PreStreamConsentDrill.pre_check()` import probe is stale. Follow-up: patch `scripts/run_drill.py` to check `shared.governance.consent.ConsentRegistry` in a subsequent drill-harness PR.
- Did NOT run the step-level enumeration of person-mentioning surfaces — that sweep is what `tests/logos_api/test_stream_redaction_routes.py` already covers (78 tests green in the privacy-regression-suite drill run on the same day). Consider folding that coverage into the pre-stream-consent drill's post-check to close the loop automatically.
