# Claude interactive subscription admission

`claude.interactive.full` uses the existing Claude subscription receipt contract:
an account-live observation produces a short-lived sanitized receipt; the
telemetry writer folds it into the route's ledger snapshot; registry projection
and the availability guarantor consume that snapshot. Local CLI, wrapper or
session presence cannot substitute for account evidence.

The source change requires independent review and coordinator release. It does
not itself observe live headroom or authorize launching work. After release,
the coordinator must obtain a genuine account-live subscription observation,
record its actual observation time, and use the installed
`hapax-claude-subscription-quota-admission --route-id claude.interactive.full`.
The scheduled account-live observer now includes this route and requires an
Opus-family serve, matching the declared interactive model family. A Haiku or
Sonnet serve cannot witness interactive admission. Passive transcripts and headless
logs do not bind requests to subscription authentication; their model names and
token usage cannot establish headroom. They can only report quota walls. Use
`--no-probe` when a live probe is not authorized; it leaves admission held even
when an unbound passive Opus serve exists. The existing active subscription probe
remains the positive observation path. Current login state cannot authenticate
an earlier passive request.

The active probe reads the existing Claude saved-login credential binding
`$CLAUDE_CONFIG_DIR/.credentials.json` (default `~/.claude/.credentials.json`).
It requires Pro/Max subscription metadata, the `user:inference` scope, and an
access token valid beyond the entire 180-second request timeout. The token is
passed only in the child's environment. Refresh tokens and saved API credentials
are never forwarded, and credentials are not copied into a temporary file or
receipt. An inherited OAuth token cannot replace this validated saved login.

The request runs in a private temporary home/configuration/working directory,
with file settings sources excluded and only PATH/locale plus the validated
OAuth binding in its environment. This prevents user, project, local and custom
config settings from restoring a gateway after environment cleanup. The probe
does not run tools or retain a session. The temporary configuration is removed
after success, failure or timeout, and exception messages expose only the type.

This producer currently supports unmanaged Linux personal subscriptions. A
present or unreadable `/etc/claude-code` policy directory, WSL/other operating
systems, Team/Enterprise or unknown subscription metadata, missing/malformed
credentials, and an expired token all hold admission before inference. A policy
directory appearing during the probe also prevents a positive result. Policy is
never disabled or rewritten. Restore the saved subscription login when that is
the missing prerequisite; a managed/unsupported configuration needs a governed
account observation with its own authentication proof. There is no API-key or
credential-refresh fallback. These bounds follow the documented
[authentication precedence](https://code.claude.com/docs/en/authentication),
[settings sources](https://code.claude.com/docs/en/cli-reference), and
[server-managed policy eligibility](https://code.claude.com/docs/en/server-managed-settings).
Recheck settings loaded inside the actual child process, invalid credentials,
managed configuration holds, cleanup and sanitized failures with
`tests/scripts/test_claude_probe_subscription_boundary.py`.

Recheck the probe-to-writer path with
`tests/scripts/test_claude_interactive_admission_auth_review.py::test_real_probe_result_reaches_interactive_mint`;
only its provider subprocess is simulated, while the probe, selector, writer and
receipt readback execute normally.
That admission script's `--help` lists the permitted
observation kinds and sanitized evidence-reference format. Preserve the default
900-second lifetime unless a governed observation specifies another allowed
bound; never refresh the timestamp of an old observation.

Then run the installed `hapax-quota-telemetry-writer --json` through its normal
governed path and re-evaluate the intended task with the existing dispatcher.
Read back the interactive snapshot's route, provider, evidence, expiry and
quota state, plus the resulting route decision and availability receipt.
Fresh platform capability/resource evidence remains separately necessary.
Telemetry must be regenerated after activation: older composite references
without an explicit `route_id` are untrusted at ledger read. The receipt's
filename is not route identity; the writer carries the validated route field
into the evidence reference and the ledger checks it against the snapshot.
This deliberate hold also applies to `claude.headless.full` and
`claude.review.opus`. Regenerate telemetry before checking admission for any
of the three routes. The writer can rebuild route-bound evidence from a still-valid
receipt without renewing its observation or expiry; an expired receipt requires
a new genuine account-live observation.

Expected boundaries:

- Only the route named by the positive receipt becomes quota-fresh. Headless
  and review receipts do not admit the interactive route, or vice versa.
  Recheck: `tests/scripts/test_claude_interactive_admission_review.py::test_ledger_binds_produced_evidence_to_its_route`.
- Missing, expired, future-dated, wrong-provider or lane-presence evidence
  keeps admission closed. At ledger read, a fresh Claude snapshot requires
  trusted producer/provider provenance and at least one matching route receipt
  whose parsed window satisfies `observed_at <= now < fresh_until`. The snapshot
  must also remain unexpired. A later snapshot expiry cannot extend the receipt,
  and a fresh sibling-route receipt cannot witness this route. Malformed or
  reversed receipt windows are untrusted. A second current matching receipt may
  admit the route while an earlier matching receipt has expired.
  Recheck missing/unsafe observations with
  `tests/scripts/test_hapax_claude_interactive_admission.py::test_interactive_unsafe_observation_keeps_admission_closed`;
  window, sibling and second-current-receipt cases with
  `tests/scripts/test_claude_interactive_admission_review.py::test_ledger_read_checks_receipt_window_independently_of_snapshot`;
  direct malformed/reversed/equal-window rejection with
  `tests/scripts/test_claude_interactive_admission_auth_review.py::test_admission_reference_rejects_invalid_windows`.
- Unexpired quota walls on the shared Claude subscription pool inhibit the
  interactive route too, using the existing wall precedence and recovery rules.
  Recheck: `tests/scripts/test_hapax_claude_interactive_admission.py::test_interactive_admission_respects_shared_pool_wall`.
- No billing mode, model, quality floor or interactive-only task rule changes.

Direct and dimensional interactive quota holds name the observation, receipt,
telemetry and retry steps. A missing registry capability instead requires
restoring `claude.interactive.full` in `config/platform-capability-registry.json`
and regenerating platform capability evidence before retrying; quota evidence
cannot replace that missing capability. Expired headless, review and interactive
receipts all leave the availability account-attestation predicate false, including
when a retained platform receipt copied their earlier positive evidence. The
projection removes that positive attestation when current ledger admission fails,
while retaining unrelated evidence. Recheck:
`tests/scripts/test_claude_interactive_admission_auth_review.py::test_retained_platform_receipt_drops_expired_account_attestation`.
Hold recovery is covered by the same file's
`test_interactive_hold_recovers_the_actual_missing_boundary` and
`test_dispatch_cli_degraded_registry_names_quota_recovery`.

The deterministic end-to-end regression is
`tests/scripts/test_hapax_claude_interactive_admission.py`. Its observations and
platform receipts are synthetic and isolated under temporary directories. A
passing test demonstrates the producer/consumer contract, not live admission.

Run the regression from the source checkout using its declared test environment:

```bash
uv run pytest tests/scripts/test_hapax_claude_interactive_admission.py \
  tests/scripts/test_claude_interactive_admission_review.py \
  tests/scripts/test_claude_interactive_admission_auth_review.py \
  tests/scripts/test_claude_probe_subscription_boundary.py \
  tests/shared/test_capability_availability_guarantor.py -q
```

After activation, run this read-only check from the activated release checkout
with the runtime's declared Python environment and ledger/receipt bindings:

```bash
uv run --no-sync python - <<'PY'
import json
from datetime import UTC, datetime
from shared.capability_availability_guarantor import (
    RefreshStrategyRegistry, evaluate_registry_availability,
)
from shared.platform_capability_registry import (
    _quota_spend_live_path_from_env, load_platform_capability_registry,
)
from shared.quota_spend_ledger import (
    load_quota_spend_ledger_resolved, subscription_quota_state_for_route,
)

route_id = "claude.interactive.full"
now = datetime.now(UTC)
resolved = load_quota_spend_ledger_resolved(live_path=_quota_spend_live_path_from_env())
state, refs = subscription_quota_state_for_route(resolved.ledger, route_id, now=now)
snapshots = [snapshot.model_dump(mode="json") for snapshot in resolved.ledger.quota_snapshots
             if snapshot.route_id == route_id]
registry = load_platform_capability_registry(now=now)
availability = evaluate_registry_availability(
    registry, route_ids=[route_id], now=now,
    refresh_strategies=RefreshStrategyRegistry(()),
)
print(json.dumps({"ledger_source": resolved.source, "ledger_path": str(resolved.path),
                  "ledger_error": resolved.live_error, "quota_state": state.value,
                  "quota_snapshots": snapshots,
                  "quota_evidence": refs, "availability": availability.to_dict()}, indent=2))
PY
```

Require `ledger_source: live`, `quota_state: fresh`, the bounded account-live
evidence reference, and an availability receipt with `status: available` and
`predicate.account_live_quota_attested: true`. A held or expired result remains
a refusal. This check does not launch or refresh anything.

The coordinator can then recheck the currently allocated privacy task through
the existing dispatcher (no `--launch`):

```bash
scripts/hapax-methodology-dispatch \
  --task pii-reland-post-recovery-review-repair-20260924 --lane alpha \
  --platform claude --mode interactive --profile full
```

Retain the emitted route-decision id and reasons. Its selected route must be
`claude.interactive.full`; account evidence alone does not clear unrelated task,
authority, resource or lane holds. Reconcile allocation before using this dated
task/lane example. Actual launch remains a separate coordinator action.
