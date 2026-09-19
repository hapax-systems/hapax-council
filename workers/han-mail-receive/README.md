# HAN inbound mail

Task: `han-mail-receive-capability-20260919`.
AuthorityCase: `CASE-SYSTEM-INTEGRITY-20260611`.
Parent: `30-areas/hapax/frame/han-to-han/DETERMINATION-han-to-han-and-capability-io-20260919.md`, §3c.
The coordinator's 2026-09-19 storage decision replaces R2 with Workers KV.

The literal `hrl-han@hapaxresearch.com` rule invokes `worker.mjs`. It hashes and
stores at most 256 KiB of raw bytes under the SHA-256 key in `hrl-han-inbound`.
The `INBOUND` binding is the only resource binding. There is no HTTP handler,
model, forwarding, reply, or outbound email. Workers.dev, preview URLs and
Worker observability are disabled. `deployment.toml` records public resource
identifiers and the deployed source hash; it contains no account ID or token.
Those public identifiers carry the secret scanner's explicit per-line allowlist
annotation; scanning remains enabled for the whole push.
The existing `rlk@` forwarding rule and disabled catch-all are unchanged.

The Worker saves envelope sender/recipient, receipt time, size and available
SPF/DKIM/DMARC header observations as KV metadata. The public EmailMessage API
does not supply a separate trusted verdict object. Header observations remain
explicitly **unverified**, even when a header claims `pass`; absence is unknown.
No body parsing occurs in the Worker. Metadata stays under KV's 1,024-byte limit.

## Quarantine and delivery

`uv run --no-sync python -m scripts.han_mail_pull` loads the two existing
`hapax-secret` names in process: `cloudflare-api-api_token` and
`cloudflare-api-account_id`. It uses the KV REST API without a public endpoint.
Its fixed quarantine is `~/hapax-state/han-mail/quarantine/`, outside the vault
and every source repository. Directory mode is 0700; production files are 0600.
Bodies belong to the operator. Do not index this directory, expose it to an
agent, attach its contents to prompts, or run models over it.

For each message, the puller checks size and remote hash, atomically writes
`<sha256>.eml`, fsyncs the file and directory, re-hashes the local copy, and
publishes/fsyncs `<sha256>.json` with type `han.mail.foreign-data`. Only after
these steps does it delete the remote key. Raw message keys have **no TTL**.
A crash before deletion leaves KV intact; a crash after deletion leaves the
verified local raw bytes and typed metadata. Re-pulls verify the existing copy
and preserve its notification state. Hash mismatches or I/O failures retain KV.
Content-identical deliveries intentionally collapse to one local item.

The local parser receives only a bounded header block to extract the subject.
Notifications allowlist sender, subject, unverified auth observations and time;
they never include a body or MIME excerpt. `shared.notify.send_notification`
uses `technical=False` to prevent foreign subjects from triggering incident
task creation, and high priority to request desktop visibility. No enrichment
API is called. Failed notifications remain pending locally after KV deletion
and retry on later runs. A successful send followed by a crash before recording
success can produce a duplicate notification; it cannot lose the item.

The user service and timer are supplied in `systemd/units/han-mail-pull.*`.
**They have not been installed or enabled. Installation follows review.**

## Free-tier arithmetic and limits

The measured account had no Workers paid subscription and no KV namespaces
before deployment. R2 is unused. Workers Free rejects excess operations instead
of billing them. Do not upgrade this account's Workers plan for this capability.
The puller checks subscriptions before contacting KV and stops if a Workers
subscription appears. Any paid-plan requirement requires a new coordinator
decision; this implementation never buys, upgrades or falls back to paid storage.

| Operation | Ordinary maximum | Bound |
| --- | --- | --- |
| Writes | 200 admissions × (global debit + sender debit + raw value) = **600/day** | Worker counters target 200/day globally, 3/day per normalized envelope sender |
| Deletes | Normally ≤200/day; retries/backlog limited to **500/day** | Durable local reservation before each attempt, including failed attempts |
| Lists | 86,400 / 300 = **288/day** | Persistent 300-second minimum spacing plus daily cap; one page per poll |
| Reads | Normally 400 admission reads + ≤500 pull reads = **900/day** | Sender/global denials can add reads; platform Free cap remains 100,000/day |
| Stored bytes | 200 × 262,144 = **52,428,800 bytes per maximum-size intake day** | Delete after durable pull; no remote body expiry; platform Free ceiling 1 GB |

Rate keys share the namespace and expire after 48 hours. No explicit deletes
or lists are performed by the Worker. The poller excludes rate keys, carries a
pagination cursor to the next poll and reserves requests before making them.
A lock serializes poller invocations. Restarts, failed requests, delete retries,
midnight transitions and backward clock changes do not replenish spent quota.
Namespace management and the one synthetic test leave ample daily headroom.

**KV counters are eventually consistent, not atomic.** Cross-location or
concurrent arrivals can overrun the 200/day or 3/sender targets. Rejected
requests and partially completed writes also consume quota. Consequently the
600-write calculation is an ordinary-traffic budget, not a distributed hard
limit. The verified Workers **Free** platform limits are the hard boundaries:
1,000 successful writes/deletes/lists per day, 100,000 reads and 1 GB storage.
Exhaustion rejects new intake; it never silently accepts an unstored message or
deletes the last copy. This deployment does not promise availability under
abuse, a long puller outage or quota exhaustion. A paid plan would invalidate
this spend argument. Retained messages can fill free storage during an outage.

References: [KV pricing](https://developers.cloudflare.com/kv/platform/pricing/),
[KV consistency](https://developers.cloudflare.com/kv/concepts/how-kv-works/),
[KV writes and limits](https://developers.cloudflare.com/kv/api/write-key-value-pairs/),
[EmailMessage API](https://developers.cloudflare.com/email-service/api/route-emails/email-handler/).

## Validation and remaining host dependency

```sh
node --test workers/han-mail-receive/worker.test.mjs
uv run --no-sync pytest tests/test_han_mail_pull.py -q
uv run --no-sync python workers/han-mail-receive/mutation-check.py
systemd-analyze --user verify systemd/units/han-mail-pull.service systemd/units/han-mail-pull.timer
```

All fixtures are self-authored. Three mutation checks must fail their targeted
test: deleting before durable storage, notifying again on re-pull, and leaking
raw bytes into a notification. Mutation copies live in a temporary directory;
the deployed/source implementation is never mutated by the checker.

One invocation of `synthetic.mjs` exercised the exact deployed handler source
with a real KV REST adapter. It wrote a 224-byte synthetic message (three KV
writes); the puller listed, fetched, durably stored, verified and deleted only
its known hash. No SMTP delivery or operator mailbox was used, and no real
message body was read. This verifies the handler/storage/puller path, not an
SMTP event executing inside the hosted Cloudflare runtime.

The synthetic item's desktop notification remains pending: the host user bus
reported no owner for `org.freedesktop.Notifications`, and `send_notification`
returned false on both attempts. Its body and pending record remain durable.
After the operator's normal notification service is restored, this local-only
retry completes the remaining synthetic notification check (run from the repo):

```sh
uv run --no-sync python -c 'from scripts.han_mail_pull import QUARANTINE, notify_pending; from shared.notify import send_notification; print(notify_pending(QUARANTINE, send_notification))'
```

Expect one newly delivered item, then zero on a repeat. Restore the existing
desktop notification service through its own governed workflow; this row does
not install or enable host units or alter the shared notification subsystem.
