# privacy-regression-suite drill — 2026-04-17

**Description:** Run the redaction + consent test suite under simulated production load.

**Mode:** dry-run
**Started at:** 2026-04-17T13:07:08.471152+00:00

## Pre-checks

- ✅ privacy tests present

## Steps executed

- uv run pytest tests/logos_api/test_stream_redaction.py tests/logos_api/test_stream_mode_transition_matrix.py -q
- Record pass / fail counts
- Record any test marked xfail that now passes or vice versa

## Post-checks

- ✅ all privacy tests green — operator confirms by running the pytest command

## Outcome

**Passed:** yes

## Operator notes

Live run (by alpha, 2026-04-17T13:07Z):

- `uv run pytest tests/logos_api/test_stream_redaction.py tests/logos_api/test_stream_mode_transition_matrix.py -q` → **56 passed, 0 failed** in 3.04s.
- Extended sweep: `uv run pytest tests/logos_api/ -q -k "redaction or stream_mode or firewall"` → **78 passed, 0 failed** in 2.74s. Includes `test_stream_redaction_person_aware.py` (Phase 6 §4.A batch-2) and `test_stream_redaction_routes.py`.
- No xfail transitions, no new skips.
- No load-simulation harness yet — current run is nominal unit-load only. Follow-up: wire a repeat-N harness at 5 concurrent pytest workers to exercise the redaction under contention, and re-run at the next 2-hour compositor stability drill window (Phase 10 §3.11) so privacy + stability drills share load.
