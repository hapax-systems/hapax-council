# omg.lol publication hash sidecar lifecycle (2026-05-01)

**cc-task:** `omg-lol-hash-sidecar-lifecycle` (P3, WSJF 4.1)
**Author:** epsilon
**Predecessor work:** `wsjf-007` (publish-orchestrator same-slug correction
republish behavior); `omg-weblog-rss-public-event-adapter` (PR #1968,
public-claim rules for the four-stage chain)
**Source audit:** `~/Documents/Personal/20-projects/hapax-research/audits/2026-04-28-cross-surface-reality-reconcile.md`

## Premise

The 2026-04-28 cross-surface reality reconcile audit identified two
distinct idempotency owners in the omg.lol publication chain. They
have routinely been conflated in task notes, leaving the operator
without a clear answer to "what evicts when?" This doc is the
canonical reference for both lifecycles, the explicit decision to
keep them separate, and the test coverage that pins each owner's
behavior.

## The two owners

### Owner A — Awareness fanout sidecar

**Path:** `/dev/shm/hapax-awareness/omg-lol-last-hash.txt`
**Owner module:** `agents/operator_awareness/omg_lol_fanout.py`
(`_read_last_hash` / `_write_last_hash` / `fanout`)
**Surface:** hourly omg.lol status post (Bearer-token API to
`https://api.omg.lol/address/{address}/statuses`)
**What it stores:** a single SHA-256 hex digest of the most recently
posted status text.
**Schema lifecycle:** unchanged since the awareness fanout shipped
(`agents.operator_awareness.omg_lol_fanout`'s `_content_hash`).
**Cardinality:** 1 file, contents = current hash, atomically replaced
on every successful POST.

**Lifecycle:**

- **Write:** when the awareness fanout receives a 2xx from omg.lol
  for a status post, it overwrites the sidecar with the new content
  hash. Failed posts (HTTP error, network error) deliberately do
  *not* update the sidecar so the next tick retries the same payload.
- **Read:** at the start of every fanout call; if the candidate
  payload hashes to the same digest, the call returns `skipped`
  without an HTTP request (avoiding burning omg.lol API calls on
  unchanged content).
- **Evict:** **automatic on reboot** (lives in `/dev/shm` tmpfs).
  No persistent retention; the post-reboot first tick will always
  re-post (which is correct: the audience has had no posts during
  downtime, so re-establishing the latest state is the right
  behavior).
- **Manual evict:** `rm /dev/shm/hapax-awareness/omg-lol-last-hash.txt`
  forces the next tick to re-post regardless of unchanged payload.

**Retention policy:** none (tmpfs). The file's existence-window is
exactly one boot session.

### Owner B — Publish-orchestrator artifact fingerprint

**Path:** `~/hapax-state/publish/log/<slug>.<surface>.json` (one file
per `<slug, surface>` pair). The fingerprint lives at the JSON's
`artifact_fingerprint` key.
**Owner module:** `agents/publish_orchestrator/orchestrator.py`
(`_artifact_fingerprint` computation; `_record_public_event`,
`_move_to_published`, terminal-result re-run dedup loop)
**Surface:** every publication-bus surface (Zenodo, omg-lol-weblog,
Bluesky, OSF, IA, Crossref, etc.) the orchestrator dispatches to.
**What it stores:** a hash of the artifact fields that define a
distinct publication attempt — `slug`, `title`, `body_md`, `abstract`,
`co_authors`, `surfaces_targeted`, `doi`, `attribution_block`. Approval
timestamps are deliberately excluded so a re-queue with no content
change reuses the prior terminal result.
**Cardinality:** N files (`number-of-slugs × number-of-surfaces`),
each carrying one fingerprint per dispatch attempt.

**Lifecycle:**

- **Write:** every time the orchestrator processes an artifact for a
  surface, the resulting log file records the fingerprint that was
  in effect at dispatch time. Both deferred and terminal results
  carry their fingerprint.
- **Read:** at the start of every dispatch attempt. If a prior log
  exists for this `<slug, surface>` and its `artifact_fingerprint`
  matches the current artifact's fingerprint AND its `result` is in
  `_TERMINAL_RESULTS`, the orchestrator preserves the prior result
  rather than re-dispatching. If the fingerprint differs (operator
  authored a correction with different `body_md`), the prior result
  is overwritten and a fresh dispatch fires.
- **Evict:** **never automatically.** The log file persists for the
  life of the `~/hapax-state/publish/log/` tree. It is overwritten
  in-place on each new dispatch for the same `<slug, surface>` —
  so the cardinality stays bounded by `slugs × surfaces`, not by
  attempt count.
- **Manual evict:** `rm ~/hapax-state/publish/log/<slug>.<surface>.json`
  forces a re-dispatch regardless of prior result.

**Retention policy:** indefinite. Per-`<slug, surface>` cardinality
is naturally bounded by the universe of slugs the operator has
published. The log doubles as audit trail (which surfaces dispatched
each artifact, which deferred, which terminally failed), so eviction
would erase audit history. No background sweep.

## Decision: keep owners separate

The two owners serve different concerns:

- **Owner A** (awareness sidecar) is a same-payload skip-gate for an
  hourly status fanout where the cost of duplicate posting is
  audience-visible (status feed pollution). It needs to be cheap to
  read, cheap to write, and ephemeral — tmpfs is the right substrate.
  The post-reboot re-post is correct behavior, not a bug.

- **Owner B** (orchestrator fingerprint) is a content-derived
  audit-and-dedup log for one-off `PreprintArtifact` dispatches where
  the cost of duplicate posting is downstream surface duplication
  (a second Zenodo deposit, a second OSF prereg, a second Bluesky
  post). It needs to persist across reboots and serve as audit
  trail for which surfaces dispatched what content when.

A merger would either weaken Owner A (forcing it to persist tmpfs
state across reboots, against its design) or weaken Owner B
(forcing it to live in tmpfs and lose audit history). **Decision:
no merger; two-owner separation is the design.**

The audit's "one documented owner" rule applies *per surface*,
not across all surfaces. Each surface has exactly one owner: the
hourly status fanout uses Owner A; every PreprintArtifact dispatch
uses Owner B.

## Coordination with `omg-statuslog-public-event-adapter`

The omg.statuslog surface (separate cc-task
`omg-statuslog-public-event-adapter`) has its own historical
publisher at `agents/omg_statuslog_poster/poster.py` with a third
sidecar at `~/.cache/hapax/hapax-omg-statuslog/state.json`. The
2026-04-28 audit notes that the statuslog poster is currently
credential-blocked (`no_creds`) and not actively running.

When the statuslog adapter task progresses, the recommended pattern
is **adopt Owner A's substrate** — write the per-status hash to a
file in `/dev/shm/hapax-awareness/` alongside the existing
`omg-lol-last-hash.txt`, *not* invent a third sidecar at
`~/.cache/hapax/hapax-omg-statuslog/`. Sharing the awareness sidecar
namespace means:

- One eviction primitive for both surfaces (boot).
- One observability surface (`/dev/shm/hapax-awareness/` is the
  canonical awareness-fanout state spine).
- No new persistent state introduced.

The current `~/.cache/hapax/hapax-omg-statuslog/state.json` should
be migrated or retired when the statuslog adapter ships. Filed as
follow-up scope for that cc-task.

## Test coverage (verified, not adding new tests)

The existing test suite already pins all three scenarios the
cc-task acceptance lists:

| Scenario | Owner A (awareness) | Owner B (orchestrator) |
|---|---|---|
| Same-slug correction (content changed → re-post fires) | `tests/operator_awareness/test_omg_lol_fanout.py::TestFanout::test_changed_payload_reposts` | `tests/publish_orchestrator/test_orchestrator.py::test_correction_republish_after_terminal_result` (asserts `first_log["artifact_fingerprint"] != second_log["artifact_fingerprint"]`) |
| Stale sidecar (HTTP error → sidecar NOT updated → next tick retries) | `tests/operator_awareness/test_omg_lol_fanout.py::TestFanout::test_http_error_returns_label_does_not_update_sidecar` | covered structurally: orchestrator only writes `_TERMINAL_RESULTS` outcomes; `deferred` results don't lock out re-dispatch |
| No-op unchanged republish (sidecar matches → skip) | `tests/operator_awareness/test_omg_lol_fanout.py::TestFanout::test_unchanged_payload_skips` | covered by terminal-result re-run dedup loop in `_run_once`; same fingerprint + `_TERMINAL_RESULTS` membership → preserve prior result |

The orchestrator's no-op skip path is covered by the same loop that
implements the same-slug correction skip — there is exactly one
predicate (`record.get("artifact_fingerprint") == artifact_fingerprint and result in _TERMINAL_RESULTS`) and both branches (match → skip, mismatch → re-dispatch) ride on it. Adding a fresh
no-op test would duplicate coverage.

## Acceptance criteria

- [x] Locate current omg.lol hash/fingerprint state files and
  document their lifecycle → §"The two owners" above.
- [x] Add explicit retention/eviction behavior or record why the
  current publish-orchestrator artifact fingerprint supersedes
  separate sidecars → §"Decision: keep owners separate" above
  (decision: no supersession; two-owner separation is the design).
- [x] Add tests or smoke evidence for same-slug correction, stale
  sidecar, and no-op unchanged republish cases → existing test
  matrix covers all three for both owners; documented in
  §"Test coverage" above.
- [x] Coordinate with `omg-statuslog-public-event-adapter` so
  statuslog duplicate suppression has one documented owner → see
  §"Coordination with omg-statuslog-public-event-adapter" above;
  recommended pattern is adopt Owner A's substrate, retire the
  legacy `~/.cache/hapax/hapax-omg-statuslog/` sidecar.

## Pointers

- Owner A code: `agents/operator_awareness/omg_lol_fanout.py:55–183`
- Owner A tests: `tests/operator_awareness/test_omg_lol_fanout.py`
- Owner B code: `agents/publish_orchestrator/orchestrator.py` (search
  `_artifact_fingerprint`, `_TERMINAL_RESULTS`)
- Owner B tests: `tests/publish_orchestrator/test_orchestrator.py`
  (search `artifact_fingerprint`)
- Source audit: `~/Documents/Personal/20-projects/hapax-research/audits/2026-04-28-cross-surface-reality-reconcile.md`
- omg-weblog reconcile (companion artifact, PR #1968):
  `docs/research/2026-05-01-omg-weblog-rss-public-event-adapter-reconcile.md`
