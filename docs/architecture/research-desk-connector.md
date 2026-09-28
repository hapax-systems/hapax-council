# Perplexity research desk connector (tailnet-only)

**Status:** implemented and tested; **not activated on any host**. Activation is an operator
act after merge and release-tree installation. This slice deliberately has no cloudflared unit,
public DNS or scheduled Computer task: a normal-thread operator trigger uses the connector in the
desktop app's Local mode.

## Operator runbook (activation is not performed by this PR)

1. Merge the PR so the release tree carries the server.
2. Link the one unit from the canonical activated release tree:
   `systemctl --user link ~/.cache/hapax/source-activation/worktree/systemd/units/hapax-research-desk-mcp.service`.
3. Determine the tailnet DNS name and set `HAPAX_RESEARCH_DESK_TAILNET_HOST` in a user-unit
   drop-in before starting the service. The MCP Host allowlist defaults to localhost; without
   this value a tailnet call is rejected with HTTP 421. Example drop-in for
   `systemctl --user edit hapax-research-desk-mcp.service`:

   ```ini
   [Service]
   Environment=HAPAX_RESEARCH_DESK_TAILNET_HOST=machine.tailnet.ts.net
   ```

   Expose the loopback origin to the tailnet only, using the host's approved tailnet HTTPS/Serve
   binding. Local mode needs an HTTPS remote URL in the desktop connector UI; plain HTTP is kept
   for localhost tests. Example operator act (not run here):
   `tailscale serve --https=443 http://127.0.0.1:8790`.
4. Enable the one unit:
   `systemctl --user enable --now hapax-research-desk-mcp.service`.
5. In a normal thread, add the connector in Local mode at the tailnet HTTPS URL and use the
   trigger phrase: **"research desk: take the next open request"**. The thread's agent calls
   `list_open_research_requests`, `fetch_request`, then `deliver_result` once.

Recheck the loopback origin with `uv run scripts/hapax-research-desk-probe`; once the
tailnet HTTPS/Serve name is known, recheck that endpoint with
`uv run scripts/hapax-research-desk-probe --tailnet-host machine.tailnet.ts.net`.
The probe refuses public DNS names before reading the key and names the next repair.
No unit activation, connector registration or host runtime mutation is performed here.

## Boundaries and prior art

The subscription agent is the MCP client; this estate serves the authenticated tool surface. The
connector is support-only and never an acceptor. Requests are typed cc-task rows with
`kind: research_request` and `route_family: perplexity-desk`; answers land in the existing
lanebus dominator with an untrusted-content label and a durable per-call receipt.

PR #4674 (`gamma/research-desk-connector-20260916`, head `2dad1471`) is prior art. This re-land
keeps its three tools, request-row queue, delivery stamping, per-call ledger, capability entry,
unit and tests, and extends them onto current main's MCP policy/ingest/manifest and capability
baseline contracts. It drops the cloudflared tunnel/example and scheduled-task clause under the
2026-09-28 rescope: tailnet-only exposure and a normal-thread trigger.

The two review findings fixed here are load-bearing:

* the server reads the connector key only through the login account's fixed
  `.local/bin/hapax-secret` path; `HOME` and `HAPAX_SECRET` cannot select an alternate binary;
* `uv run` gets `UV_CACHE_DIR=%h/.cache/hapax/research-desk/` under `CacheDirectory=`, while
  the ledger is under `StateDirectory=`, so `ProtectHome=read-only` does not create EROFS and a
  cache purge cannot erase call evidence.

## Shape

```
normal-thread operator trigger / Local-mode connector
  -> tailnet HTTPS/Serve (tailnet only; no public DNS)
  -> http://127.0.0.1:8790/mcp
  -> three authenticated MCP tools
  -> active research-request rows + cx-blue lanebus drop + StateDirectory ledger
```

The server refuses non-loopback binds. Tailnet HTTPS/Serve is an operator binding, not a public
cloud tunnel. The API key is compared in constant time and is never logged, echoed or written to
the ledger. `GET /healthz` is unauthenticated and contains no secret.

## Tool contract

* `list_open_research_requests(limit)` — positive-list statuses only (`offered`, `open`, `queued`).
* `fetch_request(request_id)` — strict filename-safe id, full capped brief, read-only.
* `deliver_result(request_id, markdown, citations, model_notes)` — writes one labelled lanebus
  drop, stamps the row, appends one ledger record, and is idempotent by request id.

Delivered markdown is length/control-character screened; citations accept only `http`/`https`;
images and unsafe links are neutralised; the drop says `content_trust: untrusted_external`.
A ledger write failure fails the call rather than returning an unbacked receipt.

## Capability and evidence

The declared shape is `perplexity.computer.desk` in
`config/platform-capability-registry.json`; its resource semantics are tailnet-only exposure and
loopback origin, and its failure class is `operator_trigger_absent`, not scheduled-task absent.
The live HTTP test `test_live_end_to_end_over_streamable_http` performs list, fetch and deliver
against a scratch request without printing the key. Unit and probe tests pin the sandbox, auth,
ledger, queue and delivery contracts.
