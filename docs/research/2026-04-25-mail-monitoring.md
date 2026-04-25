---
type: research-drop
date: 2026-04-25
title: Daemon-Driven Email Monitoring (Gmail + omg.lol) for Hapax Flows
agent_id: ad0cc9271f6700e01
status: shaping-in-progress
---

# Daemon-Driven Email Monitoring (Gmail + omg.lol) for Hapax Flows

## Verdict

Tractable. Highest-leverage opening move:

1. **omg.lol via Mailhooks** — `POST` from the omg.lol Mailhook into Hapax's awareness API at
   `/api/awareness/inbound/omg-lol`. Bypasses Gmail entirely for `hapax@omg.lol` and `oudepode@omg.lol`.
2. **Gmail via `gmail.modify`-scoped daemon**, `users.watch()`'d on Pub/Sub with
   `labelIds=[Hapax/*]` INCLUDE filter — so the daemon literally cannot pull non-Hapax mail.

The existing `agents/gmail_sync.py` (739 lines, `gmail.readonly` RAG indexer) is the **wrong substrate to
extend**. It is a body-content RAG harvester; the email-monitor is a category-routing daemon with mailbox
write permission. Build a new `agents/mail_monitor/` peer; do not graft.

## Constitutional fit

This drop is, for full-automation purposes, **plumbing**. The daemon does not surface mail content to the
operator. It does not summarise. It does not score sentiment. It produces:

- Awareness counters (3 numeric fields)
- One refusal-feedback log tail (raw entries)
- Side effects on `.zenodo.json`, `contact-suppression-list.yaml`, GitHub PR auto-merge state, TLS cert
  alarm acks

Anything outside that list is REFUSED — see §Anti-patterns.

The refusal stance is structural: an "inbox panel" or "mail digest" surface, even read-only, manufactures
HITL pressure ("you have 4 unread"). Categories A, B, F resolve silently; C, D, E feed counters / refusal-
brief / orientation operational column.

## Access-path matrix

| Path | Daemon-tractable | Min OAuth scope | 2026 status |
|---|---|---|---|
| Gmail API + `users.watch` + Pub/Sub | YES — push, label-filtered | `gmail.modify` (restricted) | CASA Tier 2 not required for self-hosted single-user; in-house use exempt from app verification |
| Gmail API polling (`history.list`) | YES — fallback only | `gmail.readonly` or `gmail.modify` | Wastes quota; use only when Pub/Sub down |
| IMAP + app-password (personal) | YES, FRAGILE | n/a | Personal accounts with 2SV still allowed; Workspace blocked since 2025-05-01 |
| IMAP + OAuth XOAUTH2 | YES | `https://mail.google.com/` (restricted) | Coarser than gmail.modify |
| Postmaster Tools API | NO | n/a | v1 retired 2025-09-30; v2 deliverability-only |
| Service account + Domain-Wide Delegation | Workspace-only | DWD | Personal Gmail does NOT support DWD |

**Decision:** `gmail.modify` over Pub/Sub, `watch()`-filtered to `Hapax/*` labelIds.

`gmail.modify` (instead of `gmail.readonly`) is required so the daemon can `addLabelIds` /
`removeLabelIds` / `INBOX` removal during dispatch. It is mailbox-wide in principle; the privacy /
scope-control story (below) compensates with filter-side gating + audit log.

## omg.lol Mailhooks (the killer move)

The omg.lol API has no inbox-read endpoint, but **Mailhooks** exist (currently BETA). Inbound mail to
`<addr>@omg.lol` triggers an HTTP POST with substitution variables (`{{from}}`, `{{subject}}`, `{{body}}`,
header variables). Choose-to-forward-or-discard semantics.

**Configuration:** point the mailhook at Hapax's Tailscale-internal awareness API:

```
POST https://logos.tail<...>.ts.net:8051/api/awareness/inbound/omg-lol
Headers: X-Hapax-Mailhook-Signature: <HMAC-SHA256 over body>
```

After processing, `discard: true` in mailhook config — mail does not retain in omg.lol.

**Caveat:** the omg.lol docs say BETA — "strongly advise against incorporating them into any production
workflows." Mitigation: run mailhook + a Gmail-forwarding fallback (`<addr>@omg.lol` → forward → operator's
Gmail with `+omg-lol-bridge` plus-tag → caught by the Gmail daemon's filter A) **in parallel for the first
30 days**. Mailhook payload + forwarded-Gmail-message land in the same logical bus; dedup is trivial via
`Message-ID`.

## Per-purpose flow design (6 categories A-F)

| Purpose | Trigger | Processor | Auto vs surface |
|---|---|---|---|
| A. Accept (verify-link click) | Sender ∈ allow-list AND outbound-correlation hit (±10 min) | `auto_clicker.py` 5-condition gate | AUTO if all conditions; surface otherwise |
| B. Verify (DOI/ORCID extract) | Sender ∈ {`noreply@zenodo.org`, `DoNotReply@notify.orcid.org`, `noreply@osf.io`, `support@datacite.org`} | regex DOI from body, write to `.zenodo.json`, awareness event | AUTO; never surface unless extraction fails |
| C. Suppress (cold-contact opt-out) | Body contains `SUPPRESS` line-anchored AND reply-to-Hapax-thread | append to `hapax-state/contact-suppression-list.yaml`; refusal-brief log | AUTO; counter to waybar `custom/refusals-1h` |
| D. Operational (TLS/DNS/dependabot) | Sender ∈ {`noreply@letsencrypt.org`, `noreply@github.com` + subject regex, `support@porkbun.com`} | parse, route to category-specific awareness slot | AUTO surface to operational awareness panel; never auto-action |
| E. Refusal-feedback | Reply-to-Hapax-thread AND not-SUPPRESS AND not-Verify | refusal-brief log entry; sentiment-NEUTRAL (no scoring) | LOG ONLY; never auto-reply |
| F. Anti-pattern | Sender domain ∈ marketing blocklist OR `List-Unsubscribe` header OR `noreply@(linkedin|twitter|x|mastodon)` | `gmail.modify` `removeLabelIds INBOX`, `addLabelIds Hapax/Discarded` | AUTO; nothing surfaces |

### 5-condition auto-click gate (ALL must be true)

1. Sender SMTP envelope-from ∈ `ALLOW_SENDERS` (verified via `Authentication-Results: dkim=pass spf=pass dmarc=pass`)
2. URL host ∈ `ALLOW_LINK_DOMAINS` (after at most 1 redirect)
3. URL scheme is `https`
4. Outbound-correlation: matching record in `~/.cache/mail-monitor/pending-actions.jsonl` within ±10 min,
   sender-domain matched
5. Operator working-mode is `rnd` OR action has `auto_unattended=true` flag

If any condition fails, **silently discard** the auto-click attempt and emit an awareness event. Do not
escalate to operator-surface.

## Server-side Gmail filters (install via `users.settings.filters.create`)

Idempotent bootstrap; install at first daemon start.

- **Filter A — Verify:** `from:(noreply@zenodo.org OR DoNotReply@notify.orcid.org OR noreply@osf.io OR support@datacite.org)` → `addLabelIds=[Hapax/Verify], removeLabelIds=[INBOX]`
- **Filter B — Suppress:** `subject:SUPPRESS AND (to:hapax@omg.lol OR to:oudepode@omg.lol)` → `addLabelIds=[Hapax/Suppress]`
- **Filter C — Operational:** `from:(noreply@letsencrypt.org OR noreply@github.com OR support@porkbun.com)` → `addLabelIds=[Hapax/Operational]`
- **Filter D — Discard:** marketing-domain patterns, `List-Unsubscribe` headers → `addLabelIds=[Hapax/Discard], removeLabelIds=[INBOX]`

## Architecture

Single daemon `agents/mail_monitor/runner.py`:

- systemd user unit `hapax-mail-monitor.service`, `Type=notify`, `WatchdogSec=60s`
- Pub/Sub topic `projects/<project>/topics/hapax-mail-monitor` → push subscription pointed at
  `https://logos.tail<...>.ts.net:8051/webhook/gmail`
- Push handler validates Google IAM JWT, then calls `mail_monitor.runner.process_history(historyId)`
- Cadence: push-driven; cron fallback every 15 min if no push received in 60 min (covers Pub/Sub outages)
- State: `~/.cache/mail-monitor/cursor.json`, atomic tmp+rename
- Dedup: SHA1(messageId) into a rocksdb-backed seen-set with 90d TTL
- Concurrency: `flock(/run/user/$UID/mail-monitor.lock)` — single execution at a time

## Privacy / scope-control mechanism

`gmail.modify` is mailbox-wide. Cryptographic proof of "Hapax-only" is not possible at the OAuth scope
layer. Compensate with five complementary mechanisms:

1. Server-side filter installs at bootstrap via `users.settings.filters.create` — Hapax/* labels populate
   automatically.
2. `users.watch()` filtered `labelIds=[Hapax/Verify, Hapax/Suppress, Hapax/Operational, Hapax/Discard]`,
   `labelFilterAction=INCLUDE` — Pub/Sub events arrive only for Hapax-labelled mail.
3. Daemon code never calls `messages.list` without `q:label:Hapax/*`. Enforce via static
   check (CI grep) + integration test (mock Gmail API; assert no list call lacks the label query).
4. Audit log: every `messages.get` call appended to `~/.cache/mail-monitor/api-calls.jsonl` with
   `{messageId, scope, label, timestamp}`. Operator can `cat` it any time.
5. Operator revocation: Google Account → Security → Third-party access → revoke disables all reads
   immediately; daemon detects and entered DEGRADED state.

The audit log is the operator's recourse, not a cryptographic guarantee. A weekly-digest job tails the log
and writes a refusal-brief entry if any out-of-Hapax-label `messages.get` is observed (defense in depth).

## `/api/awareness` integration

New endpoints:

- `POST /api/awareness/inbound/omg-lol` — Mailhook receiver, HMAC-signed
- `POST /webhook/gmail` — Pub/Sub push subscriber, Google IAM JWT verified
- `GET /api/awareness/mail/categories` — read aggregated category counts
- `GET /api/awareness/mail/refusal-feedback` — read refusal-brief mail entries

awareness state stream additions (in `agents/operator_awareness/state.py`, `MailBlock`):

- `awareness.mail.suppress_count_1h` → waybar `custom/refusals-1h`
- `awareness.mail.operational_alerts` → orientation panel "operational" domain
- `awareness.mail.refusal_feedback_unread` → refusal-brief sidebar

**No mail content surfaces in operator view.** Categories A, B, F silent. C, D, E feed counters and the
refusal-brief panel only.

## Anti-patterns (REFUSED candidates)

These are first-class REFUSED tasks — see `cc-tasks/active/mail-monitor-refused-*`:

1. **Hapax Inbox panel** — surfaces only counters; an inbox panel manufactures HITL pressure.
2. **Sentiment analysis on operator's correspondence** — privacy violation; no scoring or coloring of raw
   correspondence.
3. **Auto-reply** (except outbound-correlated DOI-failed-retrying with strict allowlist).
4. **Spam-classifier-loses-refusal** — false-negative on refusal-feedback is constitutional violation.
5. **Weekly mail digest** — aggregation obscures refusal-as-data; counters are atomic, not aggregated.
6. **Reading mail outside Hapax/* labels** — privacy substrate.
7. **Webhook without JWT/HMAC verification** — sender-spoofing trivial otherwise.

## Implementation file layout

```
agents/mail_monitor/
├── __init__.py, __main__.py, runner.py, oauth.py, filter_bootstrap.py,
├── label_bootstrap.py, webhook.py, classifier.py, auto_clicker.py, correlations.py
├── processors/{verify,suppress,operational,refusal_feedback,discard}.py
└── audit.py
systemd/user/{hapax-mail-monitor.service, hapax-mail-monitor-watch-renewal.timer}
logos/api/routes/{webhook_gmail.py, webhook_omg.py}
shared/omg_lol_client.py  # extend with set_mailhook() + get_mailhook()
hapax-state/contact-suppression-list.yaml
```

## cc-task seed list

(Research raw WSJF in parens; recalibrate to vault scale ÷ 3.)

```
mail-monitor-001-design-spec — Spec doc + sequence diagrams + label taxonomy + redact decisions (raw 23 → vault ~7.5)
mail-monitor-002-oauth-bootstrap — Operator-physical Google Cloud project + OAuth client + first consent (raw 20 → vault ~6.5; OPERATOR_BOOTSTRAP_THEN_AUTO)
mail-monitor-003-omg-lol-mailhook-client — Extend OmgLolClient with set_mailhook/get_mailhook (raw 18 → vault ~6.0)
mail-monitor-004-label-and-filter-bootstrap — Idempotent install of 4 labels + 4 filters via API (raw 19 → vault ~6.5)
mail-monitor-005-pubsub-watch-renewal — Topic + subscription + watch() + daily renewal timer (raw 22 → vault ~7.5)
mail-monitor-006-webhook-receivers — /webhook/gmail (JWT-verified) + /api/awareness/inbound/omg-lol (HMAC) (raw 24 → vault ~8.0)
mail-monitor-007-classifier-and-dispatch — Rule-based + LLM-fallback classifier; per-label dispatch (raw 17 → vault ~5.5)
mail-monitor-008-suppress-processor — SUPPRESS detection → contact-suppression-list.yaml + refusal-brief (raw 26 → vault ~8.5; HIGHEST — unblocks cold-contact research)
mail-monitor-009-verify-processor — DOI/ORCID/OSF extraction + .zenodo.json mutation (raw 21 → vault ~7.0)
mail-monitor-010-auto-clicker-with-correlation — 5-condition gate + pending-actions.jsonl correlation (raw 18 → vault ~6.0)
mail-monitor-011-operational-awareness-integration — Awareness category + waybar custom/operational-alerts (raw 14 → vault ~4.5)
mail-monitor-012-audit-log-and-revocation-test — api-calls.jsonl + weekly-digest + revocation-drill test (raw 16 → vault ~5.5)
```

## Cross-links

- `mail-monitor-008-suppress-processor` BLOCKS `cold-contact-suppression-list` — SUPPRESS detection is the
  load-bearing mail-side input that populates the suppression list.
- `mail-monitor-009-verify-processor` BLOCKS `pub-bus-zenodo-graph` — Zenodo's verify-DOI emails confirm
  successful mints; without verify, the deposit-builder cannot populate `manifest.zenodo.version_doi`
  beyond the API response (verify-mail is a redundant correctness signal, but operator-facing mints
  benefit from the same path).
- `mail-monitor-006-webhook-receivers` depends on `awareness-api-rest-endpoint` — the route registry must
  exist before mail-monitor adds inbound endpoints.

## Source research

This drop. No prior research-drop on this surface.
