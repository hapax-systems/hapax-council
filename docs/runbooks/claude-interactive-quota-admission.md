# Claude interactive subscription admission

`claude.interactive.full` uses the existing Claude subscription receipt contract:
an account-live observation produces a short-lived sanitized receipt; the
telemetry writer folds it into the route's ledger snapshot; registry projection
and the availability guarantor consume that snapshot. Local CLI, wrapper or
session presence cannot substitute for account evidence.

The source change requires independent review and coordinator release. It does
not itself observe live headroom or authorize launching work. After release,
the coordinator must obtain a genuine account-live subscription observation,
record its actual observation time, and use the installed writer with
`--route-id claude.interactive.full`. The writer's `--help` lists the permitted
observation kinds and sanitized evidence-reference format. Preserve the default
900-second lifetime unless a governed observation specifies another allowed
bound; never refresh the timestamp of an old observation.

Then run the installed `hapax-quota-telemetry-writer --json` through its normal
governed path and re-evaluate the intended task with the existing dispatcher.
Read back the interactive snapshot's route, provider, evidence, expiry and
quota state, plus the resulting route decision and availability receipt.
Fresh platform capability/resource evidence remains separately necessary.

Expected boundaries:

- Only the route named by the positive receipt becomes quota-fresh. Headless
  and review receipts do not admit the interactive route, or vice versa.
- Missing, expired, future-dated, wrong-provider or lane-presence evidence
  keeps admission closed. Ledger provenance and expiry are required at read.
- Unexpired quota walls on the shared Claude subscription pool inhibit the
  interactive route too, using the existing wall precedence and recovery rules.
- No billing mode, model, quality floor or interactive-only task rule changes.

The deterministic end-to-end regression is
`tests/scripts/test_hapax_claude_interactive_admission.py`. Its observations and
platform receipts are synthetic and isolated under temporary directories. A
passing test demonstrates the producer/consumer contract, not live admission.
