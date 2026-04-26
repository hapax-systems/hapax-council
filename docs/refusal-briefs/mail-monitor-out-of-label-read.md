# Refusal Brief: Mail-Monitor Out-of-Label Reads

**Slug:** `mail-monitor-refused-out-of-label-read`
**Axiom tag:** `interpersonal_transparency`, `single_user`, `feedback_full_automation_or_no_engagement`
**Refusal classification:** Anti-pattern #6 (mail-monitoring research) — most load-bearing of mail-monitor refusals
**Status:** REFUSED — daemon never reads mail outside `Hapax/*` labels.
**Date:** 2026-04-26
**Related cc-task:** `mail-monitor-refused-out-of-label-read`
**CI guard:** `tests/test_mail_monitor_label_scoped_reads.py`
**Sibling refusal-briefs:**
  - `mail-monitor-aggregation-digest.md`
  - `mail-monitor-auto-reply.md`
  - `mail-monitor-inbox-panel.md`

## What was refused

- Any `users.messages.list(q=...)` call where `q` does NOT include
  `label:Hapax/*`
- Any `users.messages.get(id=...)` call for a `messageId` whose
  labels don't include any `Hapax/*` label
- Any `users.threads.list` / `users.threads.get` call ever (threads
  cross labels by design — there is no thread-level scope-restriction)
- Any `users.history.list` call without a `labelId=<Hapax-label>`
  argument

## Why this is refused

### Privacy substrate (most load-bearing refusal)

The OAuth scope `gmail.modify` does not natively scope-restrict to
labels. The Gmail API permits the daemon to read **any** message in
the operator's mailbox via the granted token. The constitutional
discipline is the **sole** guarantee that operator's non-Hapax mail
(personal correspondence, family, medical, financial, etc.) stays
unread.

Per `interpersonal_transparency` axiom (weight 88): no persistent
state about non-operator persons without active consent contract.
Mail bodies and headers contain extensive non-operator-person data
— senders, recipients, body content. Reading any of that without
label-scope is a constitutional violation of the consent gate.

### Single-operator axiom

The operator's gmail is single-tenant by design (operator owns the
account). The daemon's authority within that account is delegated;
the delegation is conditional on label-scope discipline. Without
that discipline, the daemon's access is undelegated and unscoped —
which the single-operator axiom forbids.

### Scope-control mechanism #3 of 5

Per the mail-monitor research §Privacy / scope-control: this is
the third of five scope-control mechanisms (filters + watch INCLUDE
+ static-check + audit-log + revocation drill).

The other four:
1. **Server-side Gmail filters** route mail into `Hapax/*` labels
2. **Watch API INCLUDE list** scopes Pub/Sub events to specific
   labels
3. **This guard:** static-check forbids out-of-label API calls
4. **Audit-log:** `mail-monitor-012` weekly digest scans
   `api-calls.jsonl` for any out-of-label entry
5. **Revocation drill:** quarterly operator-physical drill
   verifies token-revocation works

Each mechanism is an independent layer; this brief covers layer 3
(static-check / CI guard).

## CI guard (Phase 1: regex-based static check)

`tests/test_mail_monitor_label_scoped_reads.py` regex-scans
`agents/mail_monitor/` for:

1. `messages().list(...)` calls — must include `label:Hapax` in
   the `q=` parameter
2. `threads().list()` / `threads().get()` — never permitted
   (threads cross labels)
3. `history().list(...)` — must include `labelId=` argument

Phase 2 will replace the regex scan with AST-based depth checking
(handles edge cases like multi-line calls, alternate Gmail API
client builders) plus a mocked-Gmail-API integration test.

The runtime tripwire (CI guard #3 per cc-task spec) lives in
`mail-monitor-012-audit-log-and-revocation-test` (alpha's lane).

## Refused implementation

- NO `users.messages.list(q="...")` without `label:Hapax/*` in `q`
- NO `users.messages.get(id=X)` without verifying X carries a
  `Hapax/*` label
- NO `users.threads.*` calls anywhere in mail_monitor
- NO `users.history.list` without `labelId=` argument

## Refusal-as-data: out-of-label reads surface immediately

Per the cc-task acceptance: "Out-of-label read events, if they ever
occur, must surface to refusal-brief IMMEDIATELY (not a digest
item)." This is unlike the aggregation-digest refusal (which
prevents aggregation of refusal events) — out-of-label reads are
themselves immediate-grade refusal events because they're privacy-
substrate violations.

The `mail-monitor-012-audit-log` weekly digest scanner is the
auto-detection mechanism; any detection appends a non-aggregated
entry to the refusal-brief log immediately.

## Lift conditions

This is a constitutional refusal grounded in three directives. Lift
requires retirement of any of:

- `interpersonal_transparency` axiom (constitutional; not currently
  planned — this is the consent-gate axiom)
- `single_user` axiom (constitutional)
- `feedback_full_automation_or_no_engagement`

Lift is structurally implausible — the refusal is constitutive of
the mail-monitor surface's existence (without label-scope, the
surface couldn't be deployed at all).

## Cross-references

- cc-task vault note: `mail-monitor-refused-out-of-label-read.md`
- CI guard: `tests/test_mail_monitor_label_scoped_reads.py`
- Sibling refusals: see header
- Runtime tripwire: `mail-monitor-012-audit-log-and-revocation-test`
- Source research: `docs/research/2026-04-25-mail-monitoring.md`
  §Anti-patterns #6 + §Privacy / scope-control
- Constitutional anchor: `interpersonal_transparency` axiom in
  `axioms/registry.yaml`
