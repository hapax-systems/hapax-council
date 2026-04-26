# Refusal Brief: ntfy Notifications with Action Buttons

**Slug:** `awareness-refused-ntfy-action-buttons`
**Axiom tag:** `feedback_full_automation_or_no_engagement`
**Refusal classification:** Anti-pattern #2 (drop-6 §10) — tap-to-act creates operator-physical decision points
**Status:** REFUSED — no `X-Actions` headers, no `actions[]` arrays in any ntfy POST.
**Date:** 2026-04-26
**Related cc-task:** `awareness-refused-ntfy-action-buttons`
**CI guard:** `tests/test_forbidden_ntfy_action_buttons.py`
**Sibling refusal-briefs:**
  - `awareness-acknowledge-affordances.md`
  - `awareness-additional-affordances.md`
  - `awareness-aggregation-api.md`
  - `awareness-public-marketing-dashboards.md`
  - `awareness-email-digest-with-links.md`

## What was refused

- ntfy POST with `X-Actions` HTTP header (e.g.,
  `X-Actions: view, View, https://example.com`)
- ntfy POST with JSON `actions[]` array in body (the v2 action-array
  shape: `{"actions": [{"action": "view", ...}]}`)
- Any "tap to acknowledge" / "tap to retry" / "tap to dismiss" buttons
  in ntfy notifications

## Why this is refused

### Tap-to-act creates operator-physical decision points

ntfy action buttons are in-loop by construction. Every button is an
action point: the operator must look at the phone, read the
notification, decide which button to tap, and tap. That sequence is
operator-physical and breaks the constitutional posture.

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T16:55Z): action buttons require
operator decisions at the surface; the daemon should be deciding
instead.

### Latency-dependent decisions

Tap-driven action paths fail when the operator is asleep, driving,
in a social context, or otherwise non-tap-able — but the underlying
action still needs to happen. If the daemon is already deciding
correctly when buttons aren't tapped (the failure case), then the
buttons are decoration, not function. If the daemon is NOT deciding
correctly without taps, then the system depends on operator-physical
attention, which violates full-automation.

Either way, action buttons are wrong.

### Plain ntfy is permitted

ntfy notifications without action buttons remain permitted. Existing
use cases:
- Disk-full alerts (operator decides separately whether to act;
  ntfy is the ambient signal)
- Hard-fail publication notifications (failure-as-data; daemon has
  already decided to log + retry)
- Heartbeat alerts (presence/absence-of-signal; no action implied)

These work because they're informational, not interactive. The
operator may choose to act based on context, but the notification
itself doesn't demand action.

## Daemon-tractable boundary

Authorized ntfy use:
- **Plain text body** (`requests.post("https://ntfy.sh/{topic}", data=message)`)
- **Title + Priority headers** (`X-Title`, `X-Priority`) — informational
  framing, not action affordances
- **Tags** (`X-Tags`) — categorical metadata, not interactive

Refused ntfy use:
- **Actions header** (`X-Actions`)
- **Action-array body** (`{"actions": [...]}`)
- **HTTP-action callbacks** (anything that creates a tap-triggered
  HTTP request)

## CI guard

`tests/test_forbidden_ntfy_action_buttons.py` scans `agents/`,
`shared/`, `scripts/`, `logos/` for any Python source line that:

1. References ntfy in the file (avoids false-positives from unrelated
   `actions: [...]` configurations elsewhere)
2. AND contains either:
   - String key `"X-Actions"` / `'X-Actions'` followed by `:` or `=`
   - JSON key `"actions": [` / `'actions': [`

CI fails on any match. Self-tests verify both clean (codebase passes)
and planted-pattern (positive detection) cases, plus negative cases
(unrelated `actions[]` config, plain ntfy notifications).

## Refused implementation

- NO `X-Actions` header in any ntfy POST
- NO `actions[]` array in any ntfy POST body
- NO `agents/operator_awareness/ntfy_action_dispatcher/`
- NO scheduled job that sends action-button-bearing ntfy notifications
- License-request / refusal-event / publication-result notifications
  remain plain-text only

## Lift conditions

This is a constitutional refusal. Lift requires retirement of
`feedback_full_automation_or_no_engagement`.

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check the probe per its cadence policy.

## Cross-references

- cc-task vault note: `awareness-refused-ntfy-action-buttons.md`
- CI guard: `tests/test_forbidden_ntfy_action_buttons.py`
- Sibling refusals: see header
- Source research: drop-6 §10 anti-pattern #2
