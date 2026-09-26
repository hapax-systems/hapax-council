# DataCite Phase 2B operational wiring reconcile (2026-05-01)

**cc-task:** `datacite-phase-2b-operational-wiring` (P3, WSJF 4.4)
**Author:** epsilon
**Predecessor:** PR #1726 (DataCite graph publisher Phase 2 — mint
+ version), merged 2026-04-29 onto main as commit `157a298e5`
**Parent task:** `pub-bus-datacite-graphql-mirror`

**2026-09-24 source correction:** PR #4722 changes the first-mint and
recovery contract under `pub-bus-eddy-composition-rework-20260922`. The
historical wiring and credential observations below remain dated evidence.
The current source behavior is described under "First-mint and reconciliation
contract"; it is not proof of installation, a public DOI, or release authority.

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

Missing credentials cause `self_citation_graph_doi.py` to skip with a
message and zero exit. Credential arrival alone does not guarantee first mint:
publisher admission, a durable attempt fence and consistent local state must
also permit the operation. An unresolved attempt holds future ticks for
reconciliation; see the current source contract below.

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

## First-mint and reconciliation contract

**Historical observation, 2026-05-01:** first mint was credential-blocked;
cred-watch reported `zenodo/api-token` missing. The former `pass` provisioning
instructions and promise of minting on the next tick are not current operational
instructions. Resolve credentials through the declared secret binding. Credential
arrival, a running timer and an `ok` counter do not establish public delivery.

**Current source, PR #4722 (2026-09-24; release held):**

1. `self_citation_graph_doi --commit` enters `GraphPublisher.publish` admission.
   The graph creator comes from the existing formal-name binding
   `HAPAX_OPERATOR_NAME`; there is no placeholder, inferred name or coauthor
   fallback. Missing, control-bearing or conflicting identity returns an
   actionable refusal before creating a fence or making a remote call. The
   value is sent only in formal creator metadata, not printed or saved in local
   graph state. This binding is an input to authorized publication, not release
   authority. With credentials, a valid creator and an admitted target, the
   publisher creates the intended state directory chain and exclusively creates
   `mint-attempt.json`. The fence,
   graph directory and every ancestor are synced before remote calls. Directory,
   fence or sync failure permits no remote mint.
2. The publisher checks the existing checkpoint against the latest history row.
   Both stored DOIs must pass the same bounded syntax check as remote DOIs.
   A consistent unchanged fingerprint clears the fence and returns a skip; it
   does not create a DOI. Incomplete, inconsistent or malformed legacy state
   remains held without rewriting history or making a remote call.
3. First mint creates and publishes a deposit; later changes use the verified
   new-version draft. Published deposit identity and bare concept/version DOI
   syntax must validate before success or checkpoint persistence. Syntax alone
   does not prove resolution or public content identity.
4. On success, the publisher durably appends `version-doi-history.jsonl`, writes
   the concept DOI and deposit ID, writes the fingerprint last, and syncs the
   directory before clearing the attempt fence. A failure after remote creation
   is not reported as successful publication. The failure detail includes the
   validated deposit ID when known, without echoing response bodies or tokens.

A surviving `mint-attempt.json` (including an empty or torn file) blocks another
remote attempt. No age, missing history file or second invocation clears it.
After an ambiguous remote response, interruption or persistence failure, inspect
that fence, the failure detail and the four state files. Under separate recovery
authority, reconcile the identified deposit and its public version against the
intended snapshot/fingerprint, repair and durably verify the checkpoint/history,
and only then clear the fence. If non-emission is independently established,
recovery may instead establish a safe fresh attempt. Unknown remote outcome stays
held; do not delete the fence merely to retry. A process interruption may leave
no known deposit ID, so this source does not promise automatic reconciliation.

Independent remote readback is required to confirm the intended public DOI and
version. The local files and counters are bounded local evidence. No real deposit,
installation or runtime release is authorized by this source correction.

### Read-only rechecks

From the reviewed checkout, select the graph directory from the caller's
declared `--graph-dir` binding (the default below is only the historical local
binding). This reads state without invoking `--commit`, creating an attempt,
rewriting a checkpoint or printing the creator binding:

```bash
graph_state_dir="$HOME/hapax-state/publications/self-citation-graph"
uv run --no-sync python - "$graph_state_dir" <<'PY'
import json
import sys
from pathlib import Path
from agents.publication_bus.graph_publisher import GraphPublisherError, _persisted_fingerprint

root = Path(sys.argv[1])
fence = root / "mint-attempt.json"
print("attempt_fence_present:", fence.exists())
if fence.exists():
    try:
        attempt = json.loads(fence.read_text())
        print("attempt_fingerprint:", attempt["fingerprint"])
    except (OSError, ValueError, KeyError, TypeError):
        print("attempt unreadable or malformed; HOLD remains")
try:
    print("consistent_checkpoint_fingerprint:", _persisted_fingerprint(root))
except GraphPublisherError:
    print("checkpoint invalid; reconcile remote identity and local evidence")
PY
```

A valid fingerprint does not override an existing fence. Preserve the four
checkpoint/history files and fence for authorized reconciliation. A read-only
observation can race an active publisher; it is not permission to clear state.

The focused regression selectors use fake HTTP and temporary state; they do not
make a real deposit:

```bash
uv run --no-sync pytest tests/agents/publication_bus/test_self_citation_graph_doi.py -q \
  -k 'creator or malformed_legacy or save_failure or first_version_then_version'
```

When a validated deposit ID is known, the public record can be checked without
credentials using `GET https://zenodo.org/api/records/{deposit_id}`. Verify the
returned ID, concept/version DOI, actual files and their checksums against the
intended snapshot and publication evidence. An HTTP success or syntactically
valid DOI alone does not prove artifact identity. Missing public state leaves
the outcome unresolved; draft inspection may require separately authorized
credentialed reads. No readback instruction authorizes minting or retrying.

The [Zenodo metadata contract](https://developers.zenodo.org/#representation)
requires creators and defines access rights and licensing. The source repair
does not establish rights clearance, artifact upload/identity, public resolution
or independent release acceptance. Those remain explicit publication boundaries;
credential insertion alone discharges none of them.

## Disposition for `pub-bus-datacite-graphql-mirror` (parent task)

The historical Phase 2B disposition concerned timer wiring and frontmatter
writeback. It is not current first-mint acceptance. PR #4722 remains a source
candidate with release held; current creator admission, rights clearance,
artifact/remote identity and independent review must be established before
publication. This correction does not change either historical task's status.

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
  concrete blocker → [First-mint and reconciliation contract](#first-mint-and-reconciliation-contract)
  and its read-only rechecks. No current public first-mint confirmation is
  claimed; creator/rights/artifact identity and release acceptance remain open.
- [x] Update `pub-bus-datacite-graphql-mirror` with the Phase 2B
  disposition → §"Disposition for pub-bus-datacite-graphql-mirror"
  distinguishes the historical wiring disposition from current publication
  acceptance; it does not authorize a task-state change.

## Pointers

- Mirror: `agents/publication_bus/datacite_mirror.py` (`hapax-datacite-mirror.timer` 04:00 UTC daily)
- Diff + commit scaffold: `agents/publication_bus/self_citation_graph_doi.py`
- Graph publisher: `agents/publication_bus/graph_publisher.py` (`GraphPublisher` V5 subclass)
- New chained timer (this PR): `systemd/units/hapax-datacite-graph-publish.{service,timer}` (04:30 UTC daily)
- Wire-status: `agents/publication_bus/wire_status.py::PUBLISHER_WIRE_REGISTRY["agents.publication_bus.graph_publisher"]`
- Persistence: `~/hapax-state/publications/self-citation-graph/{concept-doi.txt,last-fingerprint.txt,last-deposit-id.txt,version-doi-history.jsonl}`
- Credential binding: `hapax-secret`/FileStore → `HAPAX_ZENODO_TOKEN`; the dated cred-watch observation above does not prove current availability.
- Formal creator binding: `HAPAX_OPERATOR_NAME`, used only for the admitted graph's creator metadata; never echo it into diagnostic evidence.
- Predecessor PR: #1726 `feat(publication-bus): wire DataCite graph publisher Phase 2 (mint + version)`
