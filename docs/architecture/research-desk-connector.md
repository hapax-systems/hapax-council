# The research desk connector

**Status:** implemented, **not yet activated on any host**. The server, the units, the queue
contract and the ledger are in this repo and tested.

**Five acts remain, in this order.** An earlier draft of this page said "two acts remain, and both
are the operator's", counting only the Perplexity-side ones; an operator following that would have
registered a connector against a hostname with no live origin behind it. The full list:

| # | act | command | who |
|---|---|---|---|
| 1 | merge this PR so the release tree carries the server | — | review/merge |
| 2 | install the unit files | `systemd/scripts/install-units.sh` **from `~/projects/hapax-council`** (the primary worktree, on `main` — never from a temporary one, or every unit symlink re-points at a directory about to be deleted) | operator |
| 3 | author the tunnel's ingress config | `cp docs/architecture/research-desk-tunnel.example.yml ~/.cloudflared/research-desk.yml` and fill in the tunnel id | operator |
| 4 | enable and start both units | `systemctl --user enable --now hapax-research-desk-mcp.service hapax-research-desk-tunnel.service` | operator |
| 5 | register the connector, then create one scheduled task | see **The operator's two acts** below | operator |

**Recheck after each of 2–4, and again after 5:** `uv run scripts/hapax-research-desk-probe`.
It exits non-zero and names the next action for whatever is not yet true.

The ledger and lock root needs no act: `CacheDirectory=` in the unit makes systemd create it.

**Task row:** `perplexity-research-desk-connector-20260916` ·
**Capability shape:** `perplexity.computer.desk` in `config/platform-capability-registry.json`

---

## The inversion

Perplexity's terms (§5.2(d)/(i)) bar our agents from driving its consumer UI. Perplexity ships
the inverse as a product feature, and that is what this is built on:

- **Custom remote connectors** (help centre 13915507): a Pro/Max account registers an HTTPS MCP
  server URL with auth `None` / **API Key** / OAuth 2.0.
- **Scheduled Tasks in Computer** (help centre 11521526): a recurring run, at most hourly, gives a
  **fresh isolated agent** each time, with "the same tools, connectors, and sub-agents", spending
  Computer credits (Max: 10,000/month).

So nothing here drives Perplexity. **The subscription's agent is the client and this estate is
the server.** If a future change to this system requires automating Perplexity's interface, it is
the wrong change — stop and re-derive.

## Delete-the-estate statement

> A queue of typed research requests; a server that lets an external, subscription-funded agent
> list, fetch and answer them over an authenticated tool protocol; every answer delivered to the
> place the coordinator already reads, with a receipt.

The vault, the lanebus, cloudflared and Perplexity are **bindings**. Swap the row store for any
keyed document store and the drop directory for any append-only inbox and nothing in
`shared/research_desk.py` changes shape. The two things that are *not* bindings are the
**producer** (typed requests someone actually wants answered) and **delivery at a dominator**
(the answer lands where the reader already looks). Those are the estate's claim; the rest is
plumbing.

## Shape

```
Perplexity Computer — scheduled task, fresh agent per run
   │  MCP over Streamable HTTP, Authorization: Bearer <key>
   ▼
https://desk.hapaxrnd.com/mcp          Cloudflare edge (proxied CNAME)
   │  cloudflared tunnel fcbd6235-417e-48e1-96d7-4177e46e290b
   ▼
http://127.0.0.1:8790/mcp              hapax-research-desk-mcp.service (loopback ONLY)
   │
   ├── reads   ~/Documents/Personal/20-projects/hapax-cc-tasks/active/*.md
   │             where kind: research_request and route_family: perplexity-desk
   ├── writes  ~/Documents/Personal/30-areas/hapax/lanebus/cx-blue/<ts>-perplexity-desk-<id>.md
   ├── stamps  the request row: status → delivered, plus the receipt fields
   └── appends ~/.cache/hapax/research-desk/ledger.jsonl        (one row per call)
```

Every value below is asserted **and rechecked**. A table of operational values with no way to
re-derive them is how a drifted port or hostname reads as fact indefinitely — which is exactly the
failure mode that produced the 421 recorded further down. `scripts/hapax-research-desk-probe`
checks the whole table in one command; the per-row commands are for when it fails.

| element | value | recheck |
|---|---|---|
| public URL | `https://desk.hapaxrnd.com/mcp` | `curl -sS https://desk.hapaxrnd.com/healthz` |
| transport | MCP Streamable HTTP, **stateless** (each request independent — the client is a fresh agent every run) | `probe` (`initialize` must return `serverInfo`) |
| origin bind | `127.0.0.1:8790`; a non-loopback bind is refused outright | `ss -ltnp \| grep 8790` |
| health | `GET /healthz` → `{"ok": true, "service": "hapax-research-desk"}`, unauthenticated, no secrets | `curl -sS http://127.0.0.1:8790/healthz` |
| Host allowlist | loopback plus `desk.hapaxrnd.com` bare **and** `:443` (`HAPAX_RESEARCH_DESK_PUBLIC_HOST`). DNS-rebinding protection stays **on** | `probe` — a 421 on the authenticated check means the published Host is not allowlisted |
| auth | `Authorization: Bearer <key>` **or** `X-API-Key: <key>`, constant-time compared | `probe` checks both spellings and both refusals |
| key | FileStore name `research-desk-connector-key`; **the FileStore is the only source** | `hapax-secret --where research-desk-connector-key` |
| tunnel credentials | FileStore name `cloudflared-research-desk-tunnel-credentials`, materialised 0600 into `$XDG_RUNTIME_DIR/cloudflared/research-desk.json` at unit start and removed on stop | `systemctl --user show -p ExecStartPre hapax-research-desk-tunnel.service` |
| units loaded + active | both | `systemctl --user is-active hapax-research-desk-{mcp,tunnel}.service` |
| ledger | `~/.cache/hapax/research-desk/ledger.jsonl` | `uv run scripts/hapax-research-desk-mcp --check` |

Cloudflare Access is **not** enabled on the account. Application-layer API-key auth is the gate,
and it would remain mandatory even if Access were switched on.

## The request contract

A research request is an ordinary cc-task row under
`20-projects/hapax-cc-tasks/active/<request_id>.md` carrying:

```yaml
---
type: cc-task
task_id: <must equal the filename stem>
title: "One line, shown in the queue listing"
kind: research_request                # required — this is what makes it the desk's
route_family: perplexity-desk         # required — and this
status: offered                       # offered | open | queued are the OPEN statuses
priority: p1                          # p0..p3; sorts the queue
question: "The single question to answer."     # required, non-empty
constraints:                          # optional
  - cite primary sources
deadline: 2026-09-20                  # optional
created_at: 2026-09-16T02:00:00Z      # optional
---

The body is the full brief. `fetch_request` returns it verbatim (capped at 128 KiB).
```

`OPEN_STATUSES` is a **positive** list. A row whose status this module has never heard of is not
listed — the alternative (serve anything not on a terminal list) spends subscription credits on
rows somebody deliberately took out of the queue with a spelling we do not know. A desk row that
is malformed is *not* silently skipped: `list_open_research_requests` returns it in a `malformed`
array with a reason code, so a broken row is visible rather than absent.

## The tools

### `list_open_research_requests(limit: int = 10) -> json`

```json
{ "ok": true, "count": 1,
  "requests": [{ "request_id": "...", "title": "...", "question": "...",
                 "constraints": ["..."], "deadline": "...", "priority": "p1",
                 "status": "offered" }],
  "malformed": [{ "request_id": "...", "reason_code": "question_absent", "detail": "..." }] }
```

`limit` is 1–50; anything else is a typed refusal.

### `fetch_request(request_id: str) -> json`

The summary plus `created_at` and `brief` (the row body). Read-only, works on any desk row
whatever its status. Unknown id → `request_not_found`.

### `deliver_result(request_id, markdown, citations?, model_notes?) -> json`

```json
{ "ok": true, "receipt_id": "rd-20260916T040506Z-1a2b3c4d5e6f",
  "request_id": "...", "delivered_at": "2026-09-16T04:05:06Z",
  "delivery_drop": "30-areas/hapax/lanebus/cx-blue/20260916T040506Z-perplexity-desk-<id>.md",
  "duplicate": false, "bytes_written": 1234 }
```

`citations` accepts bare URL strings **or** `{"url": …, "title": …}` objects; the union is in the
tool's type annotation, not only in the parser, because FastMCP derives the published JSON schema
from the annotation and would otherwise reject at the transport a shape the code accepts.

**Idempotent on `request_id`.** A second delivery returns the first receipt, `duplicate: true`,
and files nothing new. The authority is the request row's own `delivery_receipt` field, read
inside a per-request `flock` held on a HOME-local inode (`~/.cache/hapax/research-desk/locks/`) —
local because `flock` is only reliable on a local filesystem and the vault is NFS. This makes a
client retry after any failure safe, which is what lets every other failure path be a hard error
instead of a guess.

### Refusals

Every refusal is `{"ok": false, "reason_code": …, "next_action": …, "detail": …}`. The codes:
`request_id_invalid`, `request_not_found`, `request_malformed`, `request_not_open`,
`request_already_delivered`, `limit_invalid`, `limit_out_of_range`, `requests_dir_absent`,
`markdown_empty`, `payload_too_large`, `payload_control_characters`, `citations_invalid`,
`citation_scheme_refused`, `row_stamp_would_corrupt`, `delivery_lane_invalid`.

Caps: markdown 256 KiB, model notes 8 KiB, 64 citations, citation URL 2048 chars, brief 128 KiB.

## What the delivered content is, and is not

The markdown an external agent delivers is written into the operator's vault. It is treated as
hostile input at three points:

1. **Length and bytes.** Capped, and screened for control characters (tab/newline/CR excepted).
2. **Citations.** `http`/`https` only — a `file:` or `javascript:` "citation" is a hazard, not a
   source, and it would be a live link in a vault reader. Refused typed.
3. **The body, by the same allowlist.** One URI-scheme allowlist applies to every URI the desk
   writes, wherever it appears. An earlier draft applied it to the citations array only, leaving
   the body — the largest untrusted surface — screened for size and control characters and nothing
   else. Two rules now run over the delivered markdown and the model notes:

   * **Every image becomes a link.** An image target auto-loads when the drop is opened, which
     turns any URL the external agent picks into a read receipt on the operator's vault — no click
     required. This applies whatever the scheme, because the hazard is the auto-load, not the
     protocol. Raw `<img …>` is backticked.
   * **Every link whose scheme is not http/https becomes inert text**, with the original shown in
     backticks so nothing is hidden from the reader.

   Both rules only ever **remove** capability from the content, which is why they can be total:
   there is no input for which neutralising is unsafe, so there is no failure branch. Nothing is
   refused over a stray `mailto:` — refusing a whole answer would cost a research run and teach the
   agent nothing.

   **What survives is counted**, not silently dropped: the drop's frontmatter carries
   `withheld_images:` and `withheld_links:`, and a banner appears in the body when either is
   non-zero.

   **Residual, stated rather than implied:** raw HTML other than `<img>` is left alone (Obsidian
   sanitises scripts, and escaping every `<` would corrupt code blocks in a research answer), and a
   bare http(s) URL written as plain text may be auto-linked by a reader. Neither auto-loads.
4. **Labelling.** The drop's frontmatter is estate-authored and carries
   `content_trust: untrusted_external` and `source: perplexity-computer`; the body opens with an
   explicit banner. A `---` rule inside the delivered markdown **cannot** forge the drop's
   frontmatter, because the canonical parser stops at the first closing marker, which is ours.
   That is pinned by a test.

A note on how the scheme screen was hardened: the parametrised defang test, not inspection, found
that CommonMark permits whitespace between `(` and a link destination — and a target pattern that
did not skip it read the destination as empty, scored it "no scheme", and passed
`[x]( javascript:… )` straight through as a live link. The same test found double-counting on
angle-bracket destinations. Both are pinned.

The capability's `authority_ceiling` is `support_only`. Desk output is support material. Anything
it would inform inside a governed surface still needs the row's own quality floor
(`frontier_review_required`) met by a frontier acceptor. **The desk is never an acceptor.**

## Measured on the live path, 2026-09-16

The end-to-end run through `https://desk.hapaxrnd.com/mcp` — before any connector existed —
produced one finding that no loopback test could have produced, and it is the reason the live gate
is in the task row at all:

> **`421 Misdirected Request`.** FastMCP turns DNS-rebinding protection **on** by default with an
> **empty** host allowlist, so the origin rejected `Host: desk.hapaxrnd.com` — the very hostname we
> had just published. Every unit and integration test passed against `127.0.0.1` while the public
> endpoint was unusable.

The fix is `transport_security(...)`: an allowlist naming loopback and the published host, with
protection left enabled. Pinned by
`test_transport_security_keeps_rebinding_protection_on_and_names_the_public_host` and by
`test_the_published_host_header_is_served_and_an_unknown_one_is_not`, which drives a real server
with a real `Host` header and asserts the unknown one still gets 421. Emptying the allowlist reds
three tests.

What the same run confirmed, through Cloudflare, from the public internet:

| probe | result |
|---|---|
| `GET /healthz` unauthenticated | `200 {"ok": true, "service": "hapax-research-desk"}` |
| `POST /mcp` no key | `401`, `reason_code: unauthorized`, `WWW-Authenticate: Bearer realm="hapax-research-desk"` |
| `POST /mcp` wrong key | `401`, identical body — no oracle for how the key was wrong |
| `initialize` with `X-API-Key` | `200`, `serverInfo.name = hapax-research-desk` |
| `list` → `fetch` → `deliver` with `Authorization: Bearer` | drop filed, row stamped `delivered`, receipt `rd-…` returned |
| `deliver` replayed | `duplicate: true`, same receipt, **no second drop** |
| `fetch_request("../escape")` | `request_id_invalid` with a next action |
| ledger after the run | five rows, `caller_ip` the real client address, no credential anywhere |

The probe ran against a scratch vault root, not the operator's — the real queue has no
`research_request` rows yet, and a live network probe is not a reason to write one.

## Identity and the filesystem

A `request_id` is matched against `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` and resolved only as
`active/<id>.md`. There is no path a caller can spell — `../`, absolute, or otherwise — that
leaves the queue directory. Mutating that pattern to `.*` reds nine tests.

## Row stamping

Delivery flips `status:` to `delivered` and appends `delivered_at`, `delivery_receipt`,
`delivery_drop`, `delivery_citations`. It is a **line edit**, not a YAML round-trip: re-emitting
the document would reorder and requote every field in a governance-tracked row and bury the one
real change in a whole-file diff. The rebuilt frontmatter is re-parsed and the status flip
re-checked **before** the write lands; a rewrite that would not parse is refused
(`row_stamp_would_corrupt`) rather than written. `delivered_at` is quoted because PyYAML coerces
a bare ISO-8601 scalar into a `datetime`, so an unquoted stamp reads back as a different type
than it was written as.

## The ledger

`~/.cache/hapax/research-desk/ledger.jsonl`, one row per call, appended under `flock` via
`shared.jsonl_append`:

```json
{"ledger_schema":1,"at":"2026-09-16T04:05:06Z","tool":"deliver_result","outcome":"ok",
 "request_id":"...","receipt_id":"rd-…","result_count":null,"bytes_in":812,"bytes_out":1234,
 "reason_code":null,"caller_ip":"127.0.0.1"}
```

Two properties are pinned by tests:

- **The credential has no route into a row.** `build_record` takes a fixed keyword set with no
  `**extra` and captures no request headers, so there is nothing to redact.
- **A receipt is durable or the call fails.** The ledger raises on IO failure rather than failing
  open — a receipt id handed to an external agent with no row behind it is a lie. Idempotent
  delivery is what makes that safe: the client's retry re-reports the first receipt.
- **Reading is total; writing is not.** `read_records` returns `LedgerRead(records,
  malformed_lines)`: an unparseable line is counted, logged at WARNING and skipped, never raised.
  The reason is the call site — `--check` is the server unit's `ExecStartPre`, so a bare
  `JSONDecodeError` on one torn line (an append interrupted by a kill, a hand edit) would wedge
  service start permanently with a stack trace carrying no next action. `--check` reports
  `ledger_malformed_lines` and a `ledger_next_action` instead, and still exits 0: a receipt ledger
  that cannot be read is a reason to say so, not a reason to refuse to serve.

`caller_ip` is the **real client address**, and the trust chain for it is exact: cloudflared
reaches the origin over loopback and forwards the caller in `X-Forwarded-For`; uvicorn runs with
`proxy_headers=True` and `forwarded_allow_ips="127.0.0.1"`, so that header is believed **only**
from a loopback peer; and the desk binds loopback, so the tunnel is the only thing that can speak.
A local process could still forge it — but a local process already has the vault, so that is not
the boundary this control is for. Both settings are pinned by a test rather than left to a library
default, because widening either is a change to what the ledger means.

## Units

| unit | what it is |
|---|---|
| `systemd/units/hapax-research-desk-mcp.service` | the server. `ExecStartPre` runs `--check`, which validates the FileStore credential and both directories — a desk that cannot authenticate never binds. `ProtectSystem=strict` with `ReadWritePaths` limited to the active-requests dir and the lanebus. |
| `systemd/units/hapax-research-desk-tunnel.service` | `cloudflared tunnel run`. `BindsTo=` the server, `ConditionPathExists=` the ingress config. |

Three details are load-bearing and each was a review finding that `systemd-analyze verify` cannot
reach, since verification checks syntax and not behaviour:

* **`CacheDirectory=hapax/research-desk`, not a `ReadWritePaths=` entry.** A `ReadWritePaths=` path
  that does not exist fails mount-namespace setup — and namespace setup runs **before**
  `ExecStartPre`, so the code's own `mkdir` could never rescue it. On a host that had never run the
  desk, the unit would have failed with a namespace error carrying no next action. `CacheDirectory=`
  makes systemd create it first. The two vault paths stay unprefixed on purpose: if the vault is
  absent the desk has no queue and no dominator, and failing loudly with the path named beats
  starting and hitting `EROFS` inside a tool call an external agent is waiting on.
* **`BindsTo=`, not `Requires=`.** `Requires=` propagates a stop only when the origin is stopped
  *explicitly*. If the desk crashes and exhausts `Restart=on-failure`, a `Requires=` tunnel keeps
  running and `desk.hapaxrnd.com` answers 502 — the state the unit comment says must not exist.
* **`Documentation=` points at the activation worktree and the repo URL**, not at
  `~/projects/hapax-council`. The one path in a unit that an operator follows during an incident
  must not be the one that dangles on a host carrying only the release tree.

A **condition-skipped tunnel is inactive, not failed** — `OnFailure=` never fires, the ledger stays
empty (indistinguishable from "no requests"), and the only symptom would be an external agent
failing where nobody in this estate looks. So the desk names it: a missing ingress config produces a
WARNING at startup and `tunnel_ingress_config_present: false` plus a `tunnel_next_action` in
`--check`, and the probe checks it directly.

Install from the primary worktree with `systemd/scripts/install-units.sh` — never from a temporary
worktree, or every unit symlink is re-pointed at a directory that is about to be deleted.

Ingress config: copy the committed template
[`research-desk-tunnel.example.yml`](research-desk-tunnel.example.yml) to
`~/.cloudflared/research-desk.yml` and fill in the tunnel id. The credentials file it names is
**not** authored by hand — the unit's `ExecStartPre` materialises it 0600 from the FileStore into
`$XDG_RUNTIME_DIR/cloudflared/` and systemd removes it on stop.

## The operator's two acts

Everything above is automatic. These are not, and they are the only two.

**1 — Register the custom connector** (Perplexity → Settings → Connectors → Add custom connector):

```json
{
  "name": "Hapax research desk",
  "server_url": "https://desk.hapaxrnd.com/mcp",
  "transport": "streamable_http",
  "authentication": {
    "type": "api_key",
    "header": "Authorization",
    "value": "Bearer <the research-desk-connector-key value>"
  }
}
```

If the form offers a bare header name and value instead of a full `Authorization` line, use
header `X-API-Key` with the key value alone — the server accepts both spellings and compares the
same secret. Read the key with `hapax-secret research-desk-connector-key`; it is never printed in
a log, a PR, or a lanebus drop.

**2 — Create one scheduled task** (Perplexity → Computer → Tasks → new, hourly):

> Use the Hapax research desk connector. Call `list_open_research_requests` with limit 5. For each
> request returned, call `fetch_request` for the full brief, research the question thoroughly with
> primary sources, then call `deliver_result` with your answer in markdown and every source you
> used in `citations`. Call `deliver_result` exactly once per request. If there are no open
> requests, stop without doing anything else.

## Exit predicate (from the task row)

A scheduled task delivers at least one result into `lanebus/cx-blue/` with citations and a
receipt; the row flips to `delivered`; the ledger shows the calls; no credential appears in any
log; the capability is scored in `route-decisions.jsonl`.

**Met by this change:** server, tools, queue contract, delivery, idempotency, ledger, units,
registry shape, and a live end-to-end over real HTTP through the auth edge with the official MCP
client (`tests/scripts/test_hapax_research_desk_mcp.py::test_live_end_to_end_over_streamable_http`).

**Demonstrable rather than retold:** `uv run scripts/hapax-research-desk-probe` re-runs every
public-path claim on demand — units loaded and active, ingress config present, origin listening,
both health endpoints, unauthenticated and wrong-key refusals *and that they are byte-identical*
(a refusal that differs between "absent" and "wrong" is a credential oracle), both key spellings
accepted, ledger readable. It is **non-mutating**: it never calls `deliver_result`, so it writes
nothing into the vault and spends no Computer credits, and that is pinned by an AST test rather
than by a grep that would match this sentence. Run it after each activation step and again after
registration.

**Not met, and cannot be from inside a PR:** the registration, the scheduled task, the first real
Computer-driven delivery, and the per-run credit cost. That is why the capability shape ships as
`measurement_pending` with `connector_registration_pending`, `scheduled_task_absent` and
`per_run_credit_cost_unmeasured` in its `blocked_reasons`, and why `demand_eligible` is `false`.

## Known residuals

- **A wiped lock directory during an in-flight delivery** loses the critical section for that one
  request. The consequence is bounded — two drop files for one request, never a corrupt row,
  because the row rewrite is atomic and verified. There is no second guard for this, deliberately:
  stacking a second mitigation on one hazard is the design smell, not the fix.
- **Cloudflare sees the plaintext request** — it terminates TLS. That is true of every Cloudflare-
  proxied hostname in the estate. Research questions and answers are not operator-private data by
  the `interpersonal_transparency` axiom's measure, but a request that *would* be must not be
  filed on this queue.
- **Per-run Computer credit cost is unmeasured**, so the capability cannot yet be scored on cost.
  The delivery ledger's call counts are the numerator that measurement will need.
- **`status: delivered` with no `delivery_receipt`** is refused rather than re-delivered
  (`request_already_delivered`). A row in that state was stamped by something other than this
  desk, and guessing would be worse than stopping.
- **Body neutralisation does not cover raw HTML other than `<img>`**, and a bare http(s) URL in
  plain text may be auto-linked by a reader. Neither auto-loads; see the untrusted-content section.
- **`route-decisions.jsonl` carries no score for this capability yet.** It cannot: scoring needs a
  measured run, and the first measured run needs the connector registered. That is why the registry
  shape ships `measurement_pending` / `demand_eligible: false` rather than asserting supply.
- **The credential has exactly one source.** An `HAPAX_RESEARCH_DESK_KEY_FOR_TESTS` env override
  that returned ahead of the FileStore read and ahead of the length floor was deleted rather than
  guarded — anything able to set the unit environment could have replaced the bearer credential of
  a publicly tunnelled server with a one-character key. Naming a variable "for tests" is not a
  machine-checkable precondition. A test asserts no env var can substitute for the FileStore.
