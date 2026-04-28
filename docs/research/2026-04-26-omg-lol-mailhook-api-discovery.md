---
type: research-drop
date: 2026-04-26
title: omg.lol Mailhook REST API endpoint — discovery attempt
status: undiscoverable-via-public-sources
related_spec: docs/specs/2026-04-25-mail-monitor.md
cc_task_unblocks: mail-monitor-003-omg-lol-mailhook-client
---

# omg.lol Mailhook REST API — discovery report

## Verdict

**The Mailhook REST API endpoint(s) are NOT documented in any public source
this session could reach.** No community wrapper, Postman collection,
GitHub repository, dev.to article, Hacker News thread, Mastodon (incl.
social.lol) post, or stale cache surfaces an HTTP method + path for
get/set/delete. The dashboard-side configuration form at
`https://home.omg.lol/dashboard/mailhooks` exists (confirmed via 302→sign-in
redirect) but is auth-gated and was not probed live per the read-only
constraint.

**Recommended path forward (operator capture):** open
`home.omg.lol/dashboard/mailhooks` in a logged-in browser session, open
DevTools → Network panel, configure / save / delete a test mailhook, and
record the requests. Three requests captured (POST/PUT save, GET load,
DELETE) will fully specify the endpoint. Estimate: 5 minutes of operator
time. Until that capture exists, **do not attempt programmatic Mailhook
configuration** — guessing endpoint shape against a BETA surface risks
silent data loss or rate-limit penalties.

The receiver-side handler in `mail-monitor-006-webhook-receivers` and the
parallel-30-day Gmail-bridge (spec §1, §7.2) are unaffected by this gap —
they handle inbound traffic from omg.lol once a mailhook is configured.
The blocker is purely the **outbound configuration** path
(`mail-monitor-003-omg-lol-mailhook-client` / extending `OmgLolClient`).

## What we tried

### 1. Public API documentation (api.omg.lol)

**Result:** No mailhook section.

`https://api.omg.lol/` renders 15 sidebar categories: Account, Address,
DNS, Directory, Email, Now Page, OAuth, PURLs, Pastebin, Preferences,
Service, Statuslog, Theme, Web, Weblog. No "Mailhook", "Hook",
"Email-Hook", "Beta", or "Experimental" entry. The Email category
documents `GET /address/{address}/email/` and
`POST /address/{address}/email/` only (forwarding-address management) —
no mailhook coverage. Confirmed via WebFetch on
`https://api.omg.lol/` (this session).

### 2. Postman collections in the official repo

**Result:** 15 collections; no `Mailhook.postman_collection.json`.

`neatnik/omg.lol/api/docs/` — Postman 2.1 collections for each documented
category. No mailhook collection. The `Email.postman_collection.json` (read
fully via `gh api repos/neatnik/omg.lol/contents/api/docs/Email.postman_collection.json`)
contains exactly two endpoints:

- `GET https://api.omg.lol/address/{:address}/email/`
  (retrieve forwarding addresses)
- `POST https://api.omg.lol/address/{:address}/email/`
  (set forwarding addresses; body
  `{"destination": "<comma-separated-list>"}`)

No mailhook variant. Both endpoints use `Authorization: Bearer {api_key}`,
matching the existing `OmgLolClient._headers()` pattern at
`shared/omg_lol_client.py:139-144`.

### 3. Issue tracker on the official repo

**Result:** `neatnik/omg.lol#124 "Implement Mailhooks"`, **OPEN**, labels
`core, email`, assigned to `@newbold` (Adam Newbold, omg.lol founder),
created **2021-10-29**, **zero comments**, **empty body**, last touched
2022-10-18 via label change. The `info/Email/mailhooks.md` doc was last
updated **2022-10-15** ("Update mailhooks.md"). No subsequent commits to
that file (`gh api repos/neatnik/omg.lol/commits?path=info/Email/mailhooks.md`).

The Postman collection commit history
(`gh api repos/neatnik/omg.lol/commits?path=api/docs`) shows the most
recent change as a typo fix (`b22cea2f, 2024-09-13: retreive → retrieve`)
on Address, not a new collection addition. **No mailhook collection has
landed in the public repo as of 2024-09-13.**

### 4. GitHub code search across known omg.lol API wrappers

**Repos surveyed, all returned zero mailhook paths:**

- `rknightuk/omglolcli` — Bash CLI
- `supleed2/omg-api` (Rust)
- `wayneyaoo/Omg.Lol.Net` (.NET SDK)
- `litdevs/node-omglol` (Node.js / TypeScript)
- `ejstreet/terraform-provider-omglol` (Terraform)
- `~gpo/omglolrs` (Rust, on sourcehut) — has `email.rs` for forwarding only,
  no mailhook (verified via `git.sr.ht/~gpo/omglolrs/tree/main/item/src`
  directory listing; only `email.rs` matches)

Tree-recursive listing via `gh api repos/{repo}/git/trees/main?recursive=1`
filtered for `mailhook` / `mail-hook` paths returned empty for every
wrapper.

Broad code search:

- `gh search code "mailhook" --owner neatnik` → only `info/Email/mailhooks.md`
- `gh search code "Mailhook" language:python` → only third-party repos
  (Make.com, Mailhook OSS, etc.) unrelated to omg.lol
- `gh search code "/address/" "mailhook"` → only this council repo's
  spec / research drops
- `gh search code "api.omg.lol" "mailhook"` → only this council repo's
  spec / research drops
- `gh search code "newbold" "mailhook"` → no results
- `gh search code "mailhook" "Bearer"` → unrelated services (Make.com,
  Webhook.site, Mailhook OSS / VHMailHook). None reference api.omg.lol.

### 5. Dev.to / blog articles

`brennanbrown/omg.lol` (config repo) — no `hook` files; no mailhook
references. `https://dev.to/brennan/version-controlled-omglol-auto-syncing-your-indieweb-with-github-actions-22eh`
(WebFetch) explicitly states: "omg.lol has a well-documented API that
covers nearly everything you can do in the web UI." Article touches
`/web`, `/now`, `/weblog/configuration`, `/weblog/template/{name}`,
`/pastebin/`, `/statuses/bio`. **No mailhook reference.**

`blakewatson.com/journal/omg-lol-an-oasis-on-the-internet/` — discovered
via search but covers user-experience, not API surface. Did not WebFetch
because content not API-relevant per surrounding excerpts.

### 6. Hacker News + Mastodon

- `hn.algolia.com/api/v1/search?query=mailhook+omg` → 4 hits, none about
  omg.lol's mailhook (results: 19th-century postal "mail hooks", a "Show
  HN" unrelated, etc.).
- `mastodon.social/api/v2/search?q=omg.lol+mailhook&type=statuses` → 0
  statuses.
- `social.lol/api/v2/search?q=mailhook&type=statuses` (omg.lol's own
  Mastodon instance) → 0 statuses.

### 7. Dashboard URL probe (read-only)

`HEAD https://home.omg.lol/dashboard/mailhooks` → 302 redirect to
`https://home.omg.lol/sign-in?from=aG9tZS5vbWcubG9sL2Rhc2hib2FyZC9tYWlsaG9va3M=`
(base64-decoded: `home.omg.lol/dashboard/mailhooks`). Confirms the
dashboard route exists and is auth-gated. Did NOT issue any authenticated
request per the read-only research constraint.

## What we know about the feature (operator-side)

From `https://github.com/neatnik/omg.lol/blob/main/info/Email/mailhooks.md`
(canonical doc, last edit 2022-10-15) and `https://home.omg.lol/info/mailhooks`:

- **Mailhook fields** (dashboard form):
  - `Method` — required, one of `GET | POST | PUT | PATCH | DELETE`
  - `URL` — required, destination URL
  - `Headers` — optional, one per line; `{{content-length}}` template
    variable supported in conjunction with `Content-Length` header
  - `Content` — optional, body template; supports `{{from}}`,
    `{{envelope-from}}`, `{{body}}`, and any `{{<header-name-lowercased>}}`
  - **Discard vs forward** — boolean choice: discard the message after
    POST OR also forward to the existing forwarding address(es).

- **BETA caveat** — verbatim: "Mailhooks are brand new around here, and
  so we welcome your testing. We'd strongly advise against incorporating
  them into any production workflows at this time, since there will
  inevitably be bugs and changes to the setup as we get things rolling."
  Bug reports route to `bugs@omg.lol`.

- **Templating** — variable substitution into the request body
  (`{{from}}`, `{{body}}`, etc.) happens server-side; the daemon only
  needs to receive the substituted POST.

## Bearer-auth confirmation

The mailhook configuration endpoint, **assuming it lives under
`api.omg.lol`**, will use the same `Authorization: Bearer {api_key}`
pattern as every other `/address/{address}/...` endpoint, established
at `shared/omg_lol_client.py:139-144`:

```python
def _headers(self) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {self._api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
```

This is uniform across all 15 documented categories and all surveyed
wrappers. The api-key load via `pass show omg-lol/api-key` is already
wired (`shared/omg_lol_client.py:79-101`).

## Plausible endpoint shapes (UNVERIFIED — DO NOT IMPLEMENT BLIND)

Following the existing omg.lol REST conventions (every resource is
address-scoped under `/address/{address}/...`, uses
JSON-bodied POST for write, GET for read, DELETE for delete), the
**most likely** shape is:

```
GET    https://api.omg.lol/address/{address}/mailhook
POST   https://api.omg.lol/address/{address}/mailhook
DELETE https://api.omg.lol/address/{address}/mailhook
```

with a JSON body roughly mirroring the dashboard form:

```jsonc
{
  "method": "POST",                                // required, one of GET|POST|PUT|PATCH|DELETE
  "url": "https://logos.tail<...>.ts.net:8051/api/awareness/inbound/omg-lol",
  "headers": "X-Hapax-Mailhook-Signature: ...\nContent-Type: application/json",
  "content": "{{body}}",                           // template, server-substituted
  "discard": true                                  // bool — discard after POST vs also forward
}
```

**This is a guess based on house style, not a citation.** Possible
variants the operator capture must disambiguate:

- Plural vs singular: `/mailhook` vs `/mailhooks` (precedent: omg.lol uses
  `/dns` plural-list + `/dns/{id}` singular-record; `/purls` plural-list
  + `/purl` / `/purl/{purl}` singular; `/statuses` plural-list +
  `/statuses/{id}` singular). Implies `/address/{addr}/mailhooks` for
  list, `/address/{addr}/mailhook` or `/address/{addr}/mailhook/{id}`
  for single record. **Capture must disambiguate** because the BETA may
  only support a single-mailhook-per-address model.
- Field name variants: `discard` vs `forward` vs `disposition`; `headers`
  as a string-blob (matches the dashboard's "one per line" UI) vs an
  array of `{key, value}` objects vs a JSON object.
- Whether multiple mailhooks per address are supported. The doc speaks of
  "a mailhook" (singular) consistently — possibly a 1:1 address↔hook
  relationship in the BETA, in which case there is no `{id}` path
  segment and POST is the upsert.

## Caveats specific to BETA status

The BETA banner is significant:

1. **The endpoint shape can change** without deprecation cycles. Any
   client we ship today may break silently on a server-side rewrite.
   Mitigation: keep the mailhook-write path behind a config flag
   (`HAPAX_OMG_LOL_MAILHOOK_WRITE_ENABLED=0` by default after capture)
   and treat 404/410 as "feature gone, fall back to operator-physical
   reconfigure."
2. **Receiver-side spec is fine to build now.** §1 / §7.2 / §8.2 of the
   mail-monitor spec
   (`docs/specs/2026-04-25-mail-monitor.md`) describe the inbound webhook
   handler at `/api/awareness/inbound/omg-lol` with HMAC-SHA256
   verification. The omg.lol SERVER's outbound HTTP shape (what fields it
   POSTs) is observable once one mailhook is configured manually — so
   the receiver can be implemented and tested without the configuration
   path. This is the lowest-risk first move.
3. **Single-mailhook-per-address risk.** If the BETA only allows one
   mailhook per address, configuring `hapax@omg.lol` → Hapax awareness
   API forecloses any future operator-physical mailhook on the same
   address (e.g. SUPPRESS-only forwarding). Mitigation: probe by reading
   list shape during capture; if list-and-get returns a single object,
   document the constraint in the spec.
4. **Operator-physical bootstrap remains acceptable.** The mail-monitor
   spec already lists OAuth bootstrap as operator-physical. Adding a
   one-time-per-address dashboard click for Mailhook configuration is
   well within budget.

## Recommendation for `mail-monitor-003`

**Defer the wrapper extension** (`OmgLolClient.set_mailhook` /
`get_mailhook` / `delete_mailhook`) until the operator captures the real
endpoint. Replace the cc-task with two leaner pieces:

1. **`mail-monitor-003a-mailhook-capture` (operator-physical, ~5 min):**
   operator opens `home.omg.lol/dashboard/mailhooks` with DevTools open,
   configures a test mailhook (POST to `https://httpbin.org/anything`,
   discard, `{{body}}` content), saves, then loads-and-deletes. Three
   requests captured cover SET/GET/DELETE. Operator pastes the
   request lines into a follow-up note at
   `docs/research/2026-04-26-omg-lol-mailhook-api-capture.md` (a stub
   sibling to this report).
2. **`mail-monitor-003b-mailhook-client` (daemon, ~30 min):** trivial
   extension of `OmgLolClient` once the capture is in hand —
   three new methods following the existing `_execute()` pattern at
   `shared/omg_lol_client.py:146-299`. Pin live-API tests behind
   `HAPAX_LIVE_OMG_LOL=1` (matches existing test gating).

Receiver-side work (`mail-monitor-006`) and the parallel-30-day
Gmail-bridge (`mail-monitor-002` / `mail-monitor-005`) are unaffected and
should proceed in parallel.

## Sources

Citations for every concrete claim above. All accessed 2026-04-26.

- `https://api.omg.lol/` — public API doc landing page; no mailhook
  section in the 15-category sidebar.
- `https://github.com/neatnik/omg.lol` (`info/Email/mailhooks.md`) —
  canonical Mailhooks user-facing doc, last edited 2022-10-15
  (`gh api repos/neatnik/omg.lol/commits?path=info/Email/mailhooks.md`).
- `https://github.com/neatnik/omg.lol/issues/124` — "Implement Mailhooks",
  OPEN, empty body, zero comments, last touched 2022-10-18, labels
  `core, email`, assignee `@newbold`.
- `https://github.com/neatnik/omg.lol/tree/main/api/docs` — 15 Postman
  collections; **no Mailhook collection**.
- `https://github.com/neatnik/omg.lol/blob/main/api/docs/Email.postman_collection.json`
  — fully read; only `GET` and `POST` to `/address/{address}/email/`
  (forwarding-address management).
- `https://github.com/rknightuk/omglolcli`,
  `https://github.com/supleed2/omg-api`,
  `https://github.com/wayneyaoo/Omg.Lol.Net`,
  `https://github.com/litdevs/node-omglol`,
  `https://github.com/ejstreet/terraform-provider-omglol`,
  `https://git.sr.ht/~gpo/omglolrs` — five wrappers surveyed via
  recursive tree listing; no mailhook references in any.
- `https://home.omg.lol/info/mailhooks` — same content as the GitHub
  doc; "API" footer link points back to `api.omg.lol` (no mailhook
  section there).
- `https://home.omg.lol/dashboard/mailhooks` — dashboard route exists
  (HEAD → 302 → sign-in); auth-gated and unprobed per read-only
  constraint.
- `https://hn.algolia.com/api/v1/search?query=mailhook+omg` — 4 hits,
  none about omg.lol's mailhook.
- `mastodon.social` and `social.lol` `/api/v2/search?q=mailhook` — 0
  statuses each.
- Existing Hapax client pattern: `shared/omg_lol_client.py` (Bearer auth,
  `_execute()` retry harness, `pass show omg-lol/api-key` bootstrap).
