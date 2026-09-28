# Public inbox coverage

The check and watcher are source prepared. Runtime activation and outbound test
messages require a separate governed seat act; this task's current row has
`runtime_mutation_authorized: false` and `release_authorized: false`.

## Inventory observed 2026-09-28 20:00 UTC

`scripts/public_inbox_monitor.py check` read Cloudflare Email Routing for all
four zones, crawled the live `hapaxresearch.com` site, and read the public
GitHub organization profile and `hapax-constitution` README, SUPPORT and
SECURITY files. It reported four enabled literal routes and no missing route.
Forward destinations were deliberately omitted.

| Zone | Address | Enabled action | Public evidence |
| --- | --- | --- | --- |
| hapaxresearch.com | `hrl-han@hapaxresearch.com` | worker | live site pages and footers |
| hapaxresearch.com | `contact@hapaxresearch.com` | forward | intended GitHub Support reply address; seat added route at 19:37 UTC |
| hapaxresearch.com | `rlk@hapaxresearch.com` | forward | Cloudflare route inventory |
| hapaxromanum.com | `contact@hapaxromanum.com` | forward | Cloudflare route inventory |
| hapaxrad.com | none | none | routing unconfigured; zone inspected |
| hapaxrnd.com | none | none | routing unconfigured; zone inspected |

The live `hapaxresearch.com` crawl found only `hrl-han@` published. The other
three zone apex names had no DNS address at this observation; the checker will
begin crawling one if it acquires live DNS. The GitHub
organization profile and constitution contact files contained no address in
these four domains. The check covers these public surfaces on each run and also
requires all four currently routed addresses, so losing the `contact@` route
fails even before a page publishes it. An unavailable surface, incomplete zone
list, enabled rule in an unready zone, unsupported catch-all or unexpected
worker target fails the check.

## Delivery design

`hrl-han@` stays on `han-mail-receive` and `han_mail_pull`. The pull service is
host-pinned to `hapax-appendix`; the podium instance must stop draining the
shared KV namespace after deployment. The existing appendix quarantine and
`hapax-han-mail` ntfy path stay the intake and alert path. Before activation,
both host timers were active against one KV namespace; appendix had six
quarantine metadata files and podium had zero at the latest read-only census.
Earlier items on either host must be preserved; no quarantine is migrated or
deleted by this change.

The podium `public-inbox-watch.timer` polls Gmail history every five minutes
for enabled forward routes from Cloudflare. It requests only message header
metadata (`To`, `Cc`, `X-Original-To`, `X-Forwarded-To`) and a partial response
that excludes snippet and body. Its private durable state contains only Gmail
message IDs and a history cursor. It persists pending IDs before advancing
the cursor, retries unaccepted ntfy sends, and sends only the matching public
address to the same `hapax-han-mail` topic. It does not use the six-hour
`gmail-sync.timer` or the currently inactive Pub/Sub mail-monitor timers.
`public-inbox-routes.timer` checks public route coverage hourly on appendix.
The podium unit declares `NTFY_BASE_URL` through the appendix tailnet DNS
name. A read-only `/v1/health` request from podium returned HTTP 200; the
watcher fails closed if this binding is absent or ntfy rejects a notice.
The existing podium gmail-sync metadata state held 33 messages addressed to
`contact@hapaxromanum.com` and zero to the two research.com forward aliases
at the 20:04 UTC census. This supports header-recipient matching for Romanum
only; the research aliases still need the governed end-to-end test.

An HTTP 2xx from ntfy is server acceptance only. It does not prove an
operator subscription or device delivery. Current subscription observation is
**unobserved**; the seat/operator must confirm receipt on the actual device.
The source and unit tests are not substitutes for that observation.

## Activation and acceptance readback

After independent review, merge and governed runtime authorization:

1. Confirm activation installed the new units on both hosts. On appendix,
   enable/start `public-inbox-routes.timer`; keep `han-mail-pull.timer` active.
   On podium, disable `han-mail-pull.timer` and enable/start
   `public-inbox-watch.timer`. The `ConditionHost=hapax-appendix` in the pull
   service also prevents a podium drain if its timer is accidentally left on.
2. Check each unit's actual `FragmentPath`, `ActiveState`, latest result and
   journal count output. Confirm the watcher state directory is mode 0700.
3. The operator confirms a subscription to `hapax-han-mail` on the actual
   device, then observes an alert there. Server acceptance alone is insufficient.
4. With the seat's outbound authority, send a distinct test mail to each of the
   four addresses. For each, confirm route receipt and the operator-visible
   alert within one relevant poll interval. Inspect only message metadata;
   leave foreign bodies to the operator. Preserve the resulting quarantine
   items and Gmail state.

Keep `contact@` forwarded for now. Moving it to the worker would require a
governed worker allowlist/redeploy, zero-spend precheck and a public routing
change. The new metadata watcher supplies the requested durable alert without
that migration. Reconsider only with delivery evidence and seat authority.
