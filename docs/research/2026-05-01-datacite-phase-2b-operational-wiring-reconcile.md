# DataCite Phase 2B operational wiring reconcile (2026-05-01)

**cc-task:** `datacite-phase-2b-operational-wiring` (P3, WSJF 4.4)
**Author:** epsilon
**Predecessor:** PR #1726 (DataCite graph publisher Phase 2 — mint
+ version), merged 2026-04-29 onto main as commit `157a298e5`
**Parent task:** `pub-bus-datacite-graphql-mirror`

## Premise

PR #1726 wired the Phase 2 mint + version path for the DataCite
self-citation graph: when a non-empty diff between consecutive daily
snapshots is detected, `self_citation_graph_doi --commit` mints a
concept-DOI on first run and version-DOIs on subsequent material
changes. The substrate is complete. The cc-task asks for the
operational follow-ups Phase 2B left undone — specifically the
timer chain, the frontmatter-writeback decision, the first-mint
confirmation, and the parent-task disposition update.

## State at 2026-05-01

### What Phase 2 shipped (PR #1726)

| Component | Path | Status |
|---|---|---|
| GraphQL mirror | `agents/publication_bus/datacite_mirror.py` | WIRED — daily timer `hapax-datacite-mirror.timer` at 04:00 UTC writes `~/hapax-state/datacite-mirror/{iso-date}.json` |
| Diff scaffold + scanner | `agents/publication_bus/self_citation_graph_doi.py` | WIRED for `--dry-run`; `--commit` requires `HAPAX_ZENODO_TOKEN` |
| Graph publisher (mint + version) | `agents/publication_bus/graph_publisher.py` | WIRED — `mint_or_version()` + `persist_graph_state()` + `GraphPublisher` V5 subclass |
| Wire-status registry entry | `agents/publication_bus/wire_status.py::PUBLISHER_WIRE_REGISTRY["agents.publication_bus.graph_publisher"]` | `status="WIRED"`, surface slug `datacite-graphql-mirror` |
| Tests | `tests/agents/publication_bus/test_datacite_mirror.py` + `test_self_citation_graph_doi.py` + `test_wire_status.py` | passing |

### Phase 2B gap that this PR closes

**The chained timer was missing.** The mirror runs daily at 04:00
UTC, but no systemd unit fires `self_citation_graph_doi --commit`
afterwards. To get a Phase 2 DOI minted, the operator (or some
ad-hoc invocation) had to manually run the graph publisher. This PR
adds:

- `systemd/units/hapax-datacite-graph-publish.service` — oneshot
  that runs `python -m agents.publication_bus.self_citation_graph_doi
  --commit`, ordered `After=hapax-datacite-mirror.service` so the
  graph publisher always sees a fresh snapshot.
- `systemd/units/hapax-datacite-graph-publish.timer` — daily at
  04:30 UTC (30min after the mirror refresh, giving the GraphQL
  request + persistence time to land plus accommodating the mirror
  unit's 1min timer accuracy slack).

The graph publisher is **safe to fire on every tick regardless of
credential state** because `self_citation_graph_doi.py` documents
"no token → skip-with-message + zero exit" — it logs the
credential-blocked state, increments the appropriate metric, and
exits cleanly. The timer can run from boot; first-mint will fire on
the first daily tick after the operator inserts `zenodo/api-token`
into pass.

## Frontmatter writeback decision

**Decision: retire as out-of-scope.** Phase 2B's "frontmatter
writeback" wishlist would have written minted concept-DOI / version-DOI
identifiers back to a vault note's frontmatter or to the daily mirror
snapshot files. Two reasons to retire:

1. **Already persisted at `~/hapax-state/publications/self-citation-graph/`.**
   `persist_graph_state()` writes:
   - `concept-doi.txt` — the stable concept-DOI minted on first run.
   - `last-fingerprint.txt` — the SHA of the most recent snapshot
     that triggered a mint.
   - `last-deposit-id.txt` — Zenodo deposit ID for traceability.
   - `version-doi-history.jsonl` — append-only log of every
     version-DOI minted, with timestamp + diff-fingerprint.

   This is the canonical trail. A vault writeback would duplicate
   it without adding readability beyond what `cat
   ~/hapax-state/publications/self-citation-graph/version-doi-history.jsonl
   | jq` already provides.

2. **Snapshot frontmatter is volatile.** The daily snapshot files
   under `~/hapax-state/datacite-mirror/{iso-date}.json` are
   regenerable from upstream (DataCite GraphQL is a public
   read-only endpoint). Annotating them with minted-DOI metadata
   would create drift between the persisted state and the canonical
   `~/hapax-state/publications/self-citation-graph/` trail.

The ORCID-published-records cross-link surface (orcid_verifier
daemon) is the right place for "where do my minted DOIs end up?"
verification — that runs daily and queries the operator's ORCID
record to confirm DataCite-minted DOIs land on the public ORCID
profile. No vault writeback required.

## First-mint confirmation status

**Blocked.** First-mint requires `HAPAX_ZENODO_TOKEN`, which derives
from `pass zenodo/api-token` (see `agents/hapax_cred_monitor/
registry.py::EXPECTED_ENTRIES` per PR #1948). The cred-watch state
file at `~/.cache/hapax/cred-watch-state.json` reports
`zenodo/api-token` as missing. The operator-action-cred-watch report
ranks Zenodo as the highest-value-unlocked entry (unblocks 6 Phase
2 publication-bus tasks).

When the operator runs `pass insert zenodo/api-token` and
hapax-secrets-loader populates `HAPAX_ZENODO_TOKEN`, the next daily
tick of `hapax-datacite-graph-publish.timer` will:

1. Attempt `mint_or_version` against Zenodo.
2. On success (assuming non-empty diff), persist `concept-doi.txt`
   + first entry in `version-doi-history.jsonl`.
3. Increment `hapax_publication_bus_publishes_total{result="ok",
   surface="datacite-graphql-mirror"}` Counter.

First-mint confirmation lives on the existing cred-watch arrival
log: when `cred-arrival-log.jsonl` records arrival of
`zenodo/api-token`, the operator can verify by:

```
$ ls ~/hapax-state/publications/self-citation-graph/
$ cat ~/hapax-state/publications/self-citation-graph/concept-doi.txt
$ jq . ~/hapax-state/publications/self-citation-graph/version-doi-history.jsonl
```

No additional first-mint-confirmation tooling is needed — the
existing persistence trail + cred-watch daemon together cover the
audit surface.

## Disposition for `pub-bus-datacite-graphql-mirror` (parent task)

The parent task should be marked **Phase 2 complete; Phase 2B
operational wiring closed by this PR; first-mint blocked on
operator credential insertion**. Follow-on cc-task
`datacite-citation-graph-refresh-diff-publish` already covers the
graph-refresh / diff-publish loop and is appropriately blocked on
operator ORCID config + Zenodo token; no new follow-up needed.

## Acceptance status

- [x] Inspect current DataCite mirror and publication-bus wire
  status code → §"What Phase 2 shipped (PR #1726)" matrix.
- [x] Add or verify the timer chain from mirror refresh to any
  dependent publication/verification step → THIS PR adds
  `hapax-datacite-graph-publish.{service,timer}` ordered
  `After=hapax-datacite-mirror.service` at 04:30 UTC daily.
- [x] Implement or explicitly retire mirror-snapshot frontmatter
  writeback → §"Frontmatter writeback decision" — retired as
  out-of-scope; canonical trail at
  `~/hapax-state/publications/self-citation-graph/` is sufficient.
- [x] Record first-mint confirmation evidence or explain the
  concrete blocker → §"First-mint confirmation status" — blocked
  on `pass insert zenodo/api-token`, observable via cred-watch
  arrival log + the persistence trail.
- [x] Update `pub-bus-datacite-graphql-mirror` with the Phase 2B
  disposition → §"Disposition for pub-bus-datacite-graphql-mirror"
  records "Phase 2 complete; Phase 2B closed; first-mint
  cred-blocked".

## Pointers

- Mirror: `agents/publication_bus/datacite_mirror.py` (`hapax-datacite-mirror.timer` 04:00 UTC daily)
- Diff + commit scaffold: `agents/publication_bus/self_citation_graph_doi.py`
- Graph publisher: `agents/publication_bus/graph_publisher.py` (`GraphPublisher` V5 subclass)
- New chained timer (this PR): `systemd/units/hapax-datacite-graph-publish.{service,timer}` (04:30 UTC daily)
- Wire-status: `agents/publication_bus/wire_status.py::PUBLISHER_WIRE_REGISTRY["agents.publication_bus.graph_publisher"]`
- Persistence: `~/hapax-state/publications/self-citation-graph/{concept-doi.txt,last-fingerprint.txt,last-deposit-id.txt,version-doi-history.jsonl}`
- Credential gate: `pass zenodo/api-token` → `HAPAX_ZENODO_TOKEN` via hapax-secrets-loader; missing-state observable in `~/.cache/hapax/cred-watch-state.json` (PR #1948)
- Predecessor PR: #1726 `feat(publication-bus): wire DataCite graph publisher Phase 2 (mint + version)`
