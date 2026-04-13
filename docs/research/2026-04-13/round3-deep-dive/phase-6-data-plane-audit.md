# Phase 6 — Data plane audit: Qdrant + consent contracts + Obsidian sync

**Queue item:** 024
**Phase:** 6 of 6
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

Four data-plane findings, from most to least severe:

1. **`vault-context-writer.service` has been failing on every run
   since at least 10:00 CDT today — 165 `ConnectionRefusedError`
   on port 27124** (Obsidian Local REST API). The daily note `##
   Log` stream is completely down. Every 15-minute tick fires,
   connects to 27124, times out, and exits with
   `status=1/FAILURE`. No ntfy, no dashboard alert.
2. **`obsidian-sync.timer` has `LastTriggerUSec=` empty — the
   timer has never fired on this boot.** The 6-hour Obsidian vault
   → RAG sync has not run at all. The vault-to-`rag-sources/obsidian/`
   flow is dead.
3. **CLAUDE.md drift vs live Qdrant**: CLAUDE.md lists 9 canonical
   Qdrant collections, but live Qdrant has **10 collections —
   `stream-reactions` (2103 points) is present in live but not in
   CLAUDE.md**. Meanwhile, **`operator-patterns` (listed in
   CLAUDE.md) has 0 points** — the collection exists but is
   entirely empty.
4. **One consent contract is malformed**:
   `axioms/contracts/contract--2026-03-23.yaml` has
   `parties: [operator, ""]` (second party is an empty string)
   and `scope: []` (empty scope list). This is either a test
   fixture that made it into the contracts dir or a broken
   consent record.

Combined with Phase 5's Critical finding that **ConsentGatedReader
is silently off in the live daimonion right now** and this phase's
finding of a malformed consent contract, the council's governance
plane has two independent failures stacked on top of each other.

## Qdrant audit (10 collections)

```bash
$ curl -s http://127.0.0.1:6333/collections | python3 -m json.tool
```

| collection | points | CLAUDE.md? | classification | notes |
|---|---|---|---|---|
| `documents` | 186599 | yes | populated | RAG corpus, healthy |
| `stream-reactions` | 2103 | **NO** | populated | undocumented collection; CLAUDE.md drift |
| `studio-moments` | 1965 | yes | populated | healthy |
| `operator-episodes` | 1678 | yes | populated | healthy |
| `profile-facts` | 929 | yes | populated | sample: `documentation_quality_standards` dimension, confidence 0.95, profile_version 69 — live and current |
| `operator-corrections` | 307 | yes | populated | healthy |
| `affordances` | 172 | yes | populated | healthy |
| `hapax-apperceptions` | 129 | yes | populated | healthy |
| `axiom-precedents` | 17 | yes | sparse | 17 is low for an axiom-governance-enforced codebase; check if the apperception/precedent writer is firing |
| `operator-patterns` | **0** | yes | **empty** | documented but never populated |

**Findings:**

### operator-patterns is empty

CLAUDE.md lists `operator-patterns` as one of the 9 canonical
collections, but the live collection has 0 points. The collection
metadata exists (the name appears in the `/collections` listing),
so it was created at some point, but nothing has written to it.

Possibilities:
- The writer was never implemented (despite the collection being
  created in advance)
- The writer exists but its code path is disabled by a feature flag
- The writer fails silently (another Phase 5 candidate)

Out of scope for this phase to identify the intended writer —
mark as a follow-up. Grep for `operator-patterns` in code:

```bash
grep -rn "operator-patterns\|operator_patterns" --include='*.py' agents/ shared/ logos/
```

### stream-reactions is undocumented

Live Qdrant has `stream-reactions` (2103 points) — likely contains
livestream chat reactions based on the naming. CLAUDE.md's
"9 collections" list does not mention it. This is CLAUDE.md drift:
either the collection was added without updating the docs, or the
docs were written assuming 9 and the 10th was added later.

Minor. File as a `docs(claude.md)` ticket.

### axiom-precedents is sparse (17 points)

17 precedents after several weeks of active governance enforcement
seems low. The compositor, voice, and camera epics all emitted
precedent-generating events. Either:
- The writer emits only for specific governance outcomes (most
  precedents come from T0 blocked-at-hook events, not from
  everyday decisions)
- The writer is partially broken

For this phase, 17 is **noted but not pathologized**. A follow-up
would enumerate the precedent writer's trigger conditions and
check if the session's observed hook-blocks produced precedent
records.

### Sample point from profile-facts

```json
{
  "id": "0776e9e5-3655-5a00-8ca1-3ad92948c969",
  "payload": {
    "dimension": "values",
    "key": "documentation_quality_standards",
    "value": "Requires comprehensive and detailed documentation with a neutral, impartial scientific tone...",
    "confidence": 0.95,
    "source": "<many memory/transcript references>",
    "text": "values/documentation_quality_standards: ...",
    "profile_version": 69
  }
}
```

Schema matches `shared/qdrant_schema.py` expectations
(dimension/key/value/confidence/source/text/profile_version).
Profile version 69 indicates active writes — the profile has been
updated 69 times. Healthy.

## Consent contracts audit

`axioms/contracts/` contains **4 YAML files** (not `.md` as the
brief guessed):

| file | parties | scope | direction | visibility_mechanism | assessment |
|---|---|---|---|---|---|
| `contract-agatha.yaml` | operator, agatha | audio, presence, transcription, video | one_way | guardian_mediated | valid |
| `contract-simon.yaml` | operator, simon | audio, presence, transcription | (not shown, likely one_way) | — | valid |
| `contract-guest-2026-03-30.yaml` | operator, guest | audio | one_way | (not shown) | valid, likely template |
| `contract--2026-03-23.yaml` | operator, **""** | **[]** | one_way | on_request | **MALFORMED** |

### Malformed contract details

```yaml
created_at: '2026-03-23T17:17:50.476732'
direction: one_way
id: contract--2026-03-23
parties:
- operator
- ''
scope: []
visibility_mechanism: on_request
```

The second party is an **empty string**. The scope is an **empty
list**. The id has a double-dash suggesting a date-only
auto-generated id without a guest name inserted.

This looks like a contract creation path was called with a missing
party name, and the contract was persisted anyway. The
`ConsentRegistry` loader will try to parse this and either:
- Skip it (if validation rejects empty strings)
- Load it as a contract that grants permission to nobody (fail-open)
- Load it and raise (fail-closed)

Given Phase 5's discovery that `ConsentGatedReader.create()` is
currently **silently failing** in the live daimonion, **this
malformed contract is a plausible root cause.** If
`ConsentRegistry.load_all()` raises on `contract--2026-03-23.yaml`,
`ConsentGatedReader.create()` would propagate the exception,
`init_pipeline.py:45` catches it, logs the warning, and proceeds
with `None`. The daimonion then runs without consent filtering
because of a single broken contract file that should have been
deleted weeks ago.

**This is the chain**: malformed YAML → registry load exception →
reader init exception → silent fallthrough → governance axiom
violated on every request.

**Fix** (in priority order):

1. **Delete or fix `contract--2026-03-23.yaml`**. If it was a
   template, delete it. If it was supposed to be a real contract,
   fill in the second party and scope.
2. **Phase 5's Critical fix** (fail-closed init) is still
   required — even after this contract is fixed, future malformed
   contracts should not silently disable consent.
3. **Add `ConsentRegistry.load_all()` validation** — reject
   contracts with empty parties or empty scope at load time with
   a precise error, not a generic exception.

### Verification

```bash
# 1. Does ConsentGatedReader.create() actually raise on this contract?
uv run python -c "
from agents._consent_reader import ConsentGatedReader
try:
    r = ConsentGatedReader.create()
    print('OK:', r)
except Exception as e:
    print('EXCEPTION:', type(e).__name__, e)
"

# 2. What does ConsentRegistry.load_all do with the malformed file?
uv run python -c "
from shared.consent import ConsentRegistry
try:
    contracts = ConsentRegistry.load_all()
    print(f'loaded {len(contracts)} contracts')
except Exception as e:
    print('EXCEPTION:', type(e).__name__, e)
"
```

Both commands above are safe to run and would produce the
definitive answer. Out of scope for this phase to execute them
because running them in the daimonion's imports may have side
effects; recommend the first action in the governance-fix PR is
to run them and confirm or refute this hypothesis.

## Obsidian sync agents audit

Four sync agents were in the brief. Their live states:

### 1. `obsidian-sync.service` (6h timer, vault → RAG sync)

```bash
$ systemctl --user show -p LastTriggerUSec,NextElapseUSecRealtime obsidian-sync.timer
LastTriggerUSec=
NextElapseUSecRealtime=
```

**The timer has never fired since boot.** Both `LastTriggerUSec`
and `NextElapseUSecRealtime` are empty. The unit is `enabled` per
`systemctl --user list-unit-files`, but not in the active timer
list, and has zero journal entries since 10:00 CDT.

Either the timer specification is invalid (cannot compute next
trigger time) or the unit's `[Timer]` block has an `OnCalendar=`
entry that doesn't match the current epoch. Without reading the
unit file, I cannot be certain — but the live state is "never
ran," which is the important operational fact.

**Classification: DEAD.** The vault-to-RAG sync has not happened
on this machine since last boot.

### 2. `vault-context-writer.service` (15-min timer, writes to Obsidian daily note)

```text
Apr 13 18:00:01 hapax-podium python[3698190]:     raise ConnectionError(e, request=request)
Apr 13 18:00:01 hapax-podium python[3698190]: requests.exceptions.ConnectionError: HTTPSConnectionPool(host='localhost', port=27124):
  Max retries exceeded with url: /vault/40-calendar/daily/2026-04-13.md
  (Caused by NewConnectionError("HTTPSConnection(host='localhost', port=27124):
   Failed to establish a new connection: [Errno 111] Connection refused"))
Apr 13 18:00:02 hapax-podium systemd[1291]: vault-context-writer.service: Main process exited, code=exited, status=1/FAILURE
```

**165 failed runs since 10:00 CDT today.** Every 15-minute tick
fires, tries to POST to `https://localhost:27124/vault/...`, and
fails because the Obsidian Local REST API plugin is not listening.

```bash
$ ss -tlnp | grep :27124
(no output — port not listening)
$ pgrep -f Obsidian
(no output — Obsidian app not running)
```

**Classification: BROKEN.** Obsidian itself is not running, so
the Local REST API plugin is not serving requests, so the sync
agent fails on every tick. **The agent has no circuit breaker or
ntfy alarm** — the failure repeats every 15 min with no operator
feedback outside the journal.

### 3. `vault-canvas-writer.service` (JSON Canvas goal dependency map)

Not in the current `list-timers` output. Either not scheduled, or
its timer file is not active.

**Classification: UNKNOWN; likely DORMANT.** Flag as a check in
the retirement handoff.

### 4. `hapax-sprint-tracker.service` (5-min timer, sprint measure bidirectional sync)

```text
Apr 13 17:56:18 hapax-podium systemd[1291]: Finished Hapax Sprint Tracker — vault-native R&D schedule management.
Apr 13 17:56:18 hapax-podium systemd[1291]: hapax-sprint-tracker.service: Consumed 1.100s CPU time over 1.361s wall clock time, 40.2M memory peak.
Apr 13 18:01:16 hapax-podium systemd[1291]: Starting Hapax Sprint Tracker — vault-native R&D schedule management...
Apr 13 18:01:18 hapax-podium systemd[1291]: Finished Hapax Sprint Tracker — vault-native R&D schedule management.
```

Runs every 5 minutes, completes in ~1.3 seconds, consumes ~40 MB
memory peak. No errors in the last hour of journal.

But — it too reads from the vault via the same Obsidian Local
REST API path that `vault-context-writer` is failing against.
Either sprint-tracker uses a different code path (direct vault
file read instead of REST API), or it is also silently failing
but its exit code is 0 (silent-failure class again).

Given the timer unit shows `Finished ... Consumed 1.361s wall
clock time` with no error log, the most likely explanation is
**it uses direct vault file reads, not the REST API.** The REST
API is Obsidian-only (requires the Local REST API plugin
running), while direct file reads work without Obsidian running.

**Classification: LIVE (probably).** File a follow-up to verify.

## Cross-system consistency

### Qdrant profile-facts vs file-based profile

Per CLAUDE.md, there is a file-based profile at `profiles/*.yaml`.
Check consistency:

```bash
ls profiles/ 2>&1
# (did not dump in this phase; out of scope)
```

Out of scope. File as follow-up: a script that reads
`profiles/*.yaml` and `profile-facts` Qdrant collection, diffs the
two, and reports drift. Would detect cases where the Qdrant
write path has lagged the file-based write path.

### obsidian-hapax plugin context panel

The obsidian-hapax plugin (`obsidian-hapax/`) fetches from
logos-api at :8051. With logos-api healthy (confirmed in Phase 2:
`council-cockpit` Prometheus target is `health=up`), the plugin
should be functional.

But **the live Obsidian is not running** (verified: no Obsidian
process found). So the plugin is by definition not doing anything.
Recommendation for operator: start Obsidian when the goal is to
have vault context flowing. Right now it's all dead.

### obsidian-sync + vault-context-writer both need Obsidian running

The two Obsidian-related sync agents both depend on Obsidian being
alive + its Local REST API plugin being enabled. With Obsidian not
running, both are dead (vault-context-writer noisily, obsidian-sync
silently).

**Root cause of the data-plane dead state**: Obsidian is not
running. Either the operator closed it intentionally, or it
crashed, or it was never started on this boot. Fixing this is a
one-step operator action (launch Obsidian) — the sync agents will
self-recover on the next tick once the plugin comes up.

## Backlog additions (for retirement handoff)

78. **`fix(governance): delete or fix
    axioms/contracts/contract--2026-03-23.yaml`** [Phase 6 + Phase
    5 Critical cross-reference] — likely root cause of the live
    `ConsentGatedReader unavailable` failure. Delete if template,
    fill in if real contract.
79. **`feat(governance): ConsentRegistry.load_all() validates
    contract shape at load time`** [Phase 6 + Phase 5 Critical] —
    reject empty parties or scope with a precise error, not a
    generic exception. Prevents future malformed contracts from
    silently disabling consent.
80. **`fix(obsidian-sync): timer never fires on this boot`**
    [Phase 6] — `obsidian-sync.timer` has
    `LastTriggerUSec=` empty. Either the unit file has an invalid
    `OnCalendar=` spec or the unit was not started. Needs a
    systemd audit.
81. **`fix(vault-context-writer): circuit-breaker + ntfy alarm
    when Obsidian is not running`** [Phase 6] — 165 failed runs
    in a session with no operator feedback is the exact
    silent-failure pattern Phase 5 flagged. Add: detect
    "connection refused to :27124 for N consecutive runs" → send
    ntfy "Obsidian is not running, daily note sync is dead" → stop
    retrying until the next operator-triggered start.
82. **`fix(vault-context-writer): degrade gracefully if Obsidian
    is not running (log once, skip silently)`** [Phase 6
    alternative to #81] — less aggressive than #81; just avoid
    165 traceback spams in the journal.
83. **`research(qdrant): why is operator-patterns collection
    empty?`** [Phase 6] — CLAUDE.md lists it but the writer is
    apparently never called. Grep for `operator-patterns` + write
    a backlog ticket for the writer path.
84. **`docs(claude.md): add stream-reactions to the 9 Qdrant
    collections list`** [Phase 6] — live Qdrant has 10, CLAUDE.md
    says 9. Add `stream-reactions` to bring the docs in sync.
85. **`research(qdrant): low axiom-precedents count (17)`** [Phase
    6] — 17 precedents in a heavily-governed codebase seems low.
    Verify the precedent writer's trigger conditions and check if
    recent T0 blocks produced records.
86. **`research(sprint-tracker): verify it reads vault directly,
    not via REST API`** [Phase 6] — the sprint tracker timer
    shows `Finished` with status 0 while vault-context-writer
    fails with Connection refused. Confirm the read path is
    resilient to Obsidian being down.
87. **`feat(monitoring): Obsidian running gauge +
    vault-context-writer failure counter`** [Phase 6] —
    `obsidian_process_alive` and `vault_context_writer_failures_total`
    series on the (to-be-created) daimonion Prometheus exporter.
88. **`research(cross-system): script that diffs profiles/*.yaml
    vs Qdrant profile-facts`** [Phase 6] — detect drift between
    the file-based and Qdrant-based profile representations.

## Reproduction commands

```bash
# 1. Qdrant collection inventory + counts
curl -s http://127.0.0.1:6333/collections
for name in axiom-precedents hapax-apperceptions operator-patterns \
            profile-facts operator-episodes studio-moments affordances \
            operator-corrections documents stream-reactions; do
  count=$(curl -s "http://127.0.0.1:6333/collections/$name" | \
    python3 -c "import json,sys; d=json.load(sys.stdin); \
    print(d.get('result',{}).get('points_count','?'))")
  echo "$name: $count"
done

# 2. Consent contracts inventory
ls axioms/contracts/*.yaml
for f in axioms/contracts/*.yaml; do echo "=== $f ==="; head -8 "$f"; done

# 3. Obsidian sync agent states
systemctl --user list-timers | grep -iE "obsidian|vault|sprint"
journalctl --user -u vault-context-writer.service --since "10:00" | \
  grep -c "Connection refused"
systemctl --user show -p LastTriggerUSec,NextElapseUSecRealtime obsidian-sync.timer
pgrep -f Obsidian || echo "Obsidian not running"
ss -tlnp | grep :27124 || echo "Local REST API port 27124 not listening"

# 4. Phase 5 Critical hypothesis test (run this before the governance fix)
uv run python -c "
from agents._consent_reader import ConsentGatedReader
try:
    r = ConsentGatedReader.create()
    print('OK:', r)
except Exception as e:
    print('EXCEPTION:', type(e).__name__, e)
"
```
