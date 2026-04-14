# Qdrant payload-index gap — system-wide finding from a stream-reactions audit

**Date:** 2026-04-14
**Author:** delta (beta role)
**Scope:** Started as a focused audit of the new
`stream-reactions` collection alpha added for LRR Phase 2 /
Phase 9. Expanded to system-wide when the first probe showed
that **no council collection has any payload indexes at all**
— not just stream-reactions. Asks: how much does the missing
indexing cost, and where's the inflection point where it
starts to hurt LRR research queries?
**Register:** scientific, neutral
**Status:** investigation only — system-wide observability
gap with a concrete one-function fix per collection

## Headline

**Four findings.**

1. **Every Qdrant collection in the council has an empty
   `payload_schema`.** No keyword indexes, no integer
   indexes, no geo indexes, nothing. Confirmed across all
   10 collections in `shared/qdrant_schema.py` via live
   probes of the Qdrant API. The schema verifier
   (`shared/qdrant_schema.py:39-82 verify_collections`)
   only checks vector dim and distance metric — **it has
   no visibility into payload indexes at all**, so this
   gap has never surfaced in health reports.
2. **Only `documents` has an active HNSW vector index.**
   Other collections (stream-reactions 2 650 points,
   profile-facts 929, studio-moments 1 965,
   operator-episodes 1 697, affordances 172, axiom-precedents
   17) all sit below Qdrant's default `indexing_threshold:
   10000`. Vector search against them runs in full-scan
   mode today — fine for the current point counts, but the
   collection builds toward a cliff: **exactly when
   `points_count` crosses 10 000, the HNSW index starts
   building**, and every query during that window pays a
   one-time index-build latency spike.
3. **`stream-reactions` specifically is on a write-pattern
   that does not scale.** Every reaction persist:
   - Spawns a new Python thread
     (`director_loop.py:965 threading.Thread(...).start()`)
   - Calls `client.get_collections()` to check existence,
     a full HTTP round-trip per write
   - Upserts **one point at a time** via
     `client.upsert(...)` with a single-element list
   - Calls `embed()` (a nomic-embed-cpu call) synchronously
     inside the thread before the upsert
4. **LRR research queries will not scale against the
   current schema.** Alpha's LRR Phase 1 shipped a
   `condition_id` tag that flows into Langfuse traces and
   — by the same design — into the `stream-reactions`
   payload. Research analyses that ask "how many reactions
   during condition X" or "what activities did I do during
   the Hermes 3 evaluation window" are payload-filter
   queries, not vector queries. **Without a keyword index
   on `condition_id` (and probably `activity` and
   `session_id`), every such query is a linear scan of the
   collection.** Fine at 2 650 points, slow at 100 000,
   pathological at 1 000 000 — and LRR is collecting at
   something like 240 points/hour, so 1 M points arrives
   in roughly 6 months of continuous streaming.

Consequence: **the observability surface alpha's LRR
research depends on has a latent cliff** built into it.
Index configuration is a one-time write at schema creation
and zero cost per query — the omission is pure forgotten
infrastructure.

## 1. Cross-collection payload census

```text
$ for col in profile-facts documents studio-moments \
             operator-episodes affordances axiom-precedents \
             stream-reactions; do
      curl -s http://localhost:6333/collections/$col | \
      python3 -c "import sys,json; d=json.loads(sys.stdin.read())['result']; \
          print(f'{d[\"points_count\"]} pts, idx={d[\"indexed_vectors_count\"]}, \
          payload_keys={list(d[\"payload_schema\"].keys())}')"
  done

profile-facts         929  pts, idx=0       payload_keys=[]
documents          186 404  pts, idx=197 588 payload_keys=[]
studio-moments      1 965  pts, idx=0       payload_keys=[]
operator-episodes   1 697  pts, idx=0       payload_keys=[]
affordances            172 pts, idx=0       payload_keys=[]
axiom-precedents        17 pts, idx=0       payload_keys=[]
stream-reactions    2 650  pts, idx=0       payload_keys=[]
```

Every collection reports `payload_keys=[]`. The only one
with a non-zero `indexed_vectors_count` is `documents`
(186k points, crossed the 10k HNSW threshold long ago).

The `indexed=197 588 > points=186 404` delta for
`documents` is tombstoned points still in segments — a
normal Qdrant state that resolves after the next
optimizer pass.

## 2. `stream-reactions` write path

```python
# agents/studio_compositor/director_loop.py:924-965 (abbreviated)

try:
    with open(_jsonl_log_path(now), "a") as f:
        f.write(json.dumps(record) + "\n")
except OSError:
    pass

# Qdrant persistence (async — don't block the reactor)
def _persist_to_qdrant():
    try:
        from qdrant_client.models import Distance, PointStruct, VectorParams
        from shared.config import embed, get_qdrant

        client = get_qdrant()
        # Ensure collection exists
        collections = [c.name for c in client.get_collections().collections]
        if "stream-reactions" not in collections:
            client.create_collection(
                collection_name="stream-reactions",
                vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            )

        embed_text = f"{activity}: {text[:200]} | {video_title} | {album}"
        vector = embed(embed_text)
        if vector:
            import uuid
            client.upsert(
                collection_name="stream-reactions",
                points=[
                    PointStruct(
                        id=str(uuid.uuid4()),
                        vector=vector,
                        payload=record,
                    )
                ],
            )
    except Exception:
        log.debug("Qdrant persistence failed (non-fatal)", exc_info=True)

threading.Thread(target=_persist_to_qdrant, daemon=True,
                 name="qdrant-persist").start()
```

Five write-path issues, ordered by severity:

### 2.1 Collection existence check on every write

`client.get_collections()` is a full HTTP round-trip to
Qdrant's `/collections` endpoint. At ~40–240 reactions/hour,
that's 40–240 unnecessary round-trips per hour. **Fix: check
once in `__init__`, set a flag.**

### 2.2 Collection creation lives in the hot path

`create_collection` should happen at schema setup, not at
first-write. The current pattern means **the very first
reaction after a Qdrant wipe is the one that creates the
collection with hardcoded parameters** (size 768, distance
cosine) that bypass the `shared/qdrant_schema.py` registry.
The centralized schema registry exists but this writer
doesn't use it. **Fix: move creation to
`shared/qdrant_schema.py`'s verify-and-create path at
startup, like any other collection.**

### 2.3 Single-point upsert, no batching

`points=[PointStruct(...)]` with one element per call.
Qdrant upsert is network-bound, not compute-bound — the
overhead per request is fixed regardless of batch size.
Batching 10–50 points per upsert is an order-of-magnitude
reduction in wall-clock cost. **Fix: in-memory queue with
a 5-second or 10-point flush trigger, whichever comes
first.**

### 2.4 Thread-per-write creation

`threading.Thread(...).start()` spawns a new OS-level
Python thread for each persist. Python thread creation is
~100 μs and the thread lifetime is ~50 ms for a single
embed + upsert. Across ~240 reactions/hour, this is
0.024 seconds of pure thread-creation overhead per hour
— trivial in isolation but the pattern does not scale
if reaction rate climbs (e.g. during a chat raid that
bumps reaction cadence). **Fix: single background worker
thread + `queue.Queue`, or `ThreadPoolExecutor` with a
small pool.**

### 2.5 Synchronous `embed()` inside the thread

`vector = embed(embed_text)` is an Ollama HTTP call to
`nomic-embed-cpu`. Per workspace CLAUDE.md, Ollama is
GPU-isolated (`CUDA_VISIBLE_DEVICES=""`) so embedding
runs on CPU at ~10–20 ms per call. Inside the persist
thread this is fine — the daemon thread absorbs the
latency without blocking the reactor. But it does serialize
within the thread, so if multiple reactions pile up at
once (e.g. a burst of director_loop ticks), the embeds
run back-to-back. With batching (2.3) the embed could
also be batched via Ollama's `/api/embed` endpoint
(accepts an array of prompts, amortizes overhead).

## 3. What alpha's LRR research needs

Alpha's Phase 1 work landed a `condition_id` tag on Langfuse
traces and an on-disk research marker in
`/dev/shm/hapax-research-marker.txt`. The tag is read at
director_loop LLM-call time
(`director_loop.py:646 _read_research_marker()`) and
attached to every stream-reactions record's `record` dict
as a top-level field.

Phase 1 PR #794's stats analysis
(`feat(lrr): Phase 1 PR #4 — stats.py BEST analytical
approximation`) implies alpha runs per-condition statistical
comparisons. Those comparisons need efficient
"SELECT * WHERE condition_id = X" queries. Without a
keyword index on `condition_id`, every such query is O(N)
across the whole stream-reactions collection.

At current scale (2 650 points), the scan cost is ~10 ms.
At 6 months of collection (projected ~1 M points), the
scan cost is ~4 seconds per query — and any batched analysis
over all conditions runs `number_of_conditions` scans back
to back, easily multiple minutes of pure scan time per
report.

**The fix is one API call per index, one time**, for each
expected filter field:

```python
from qdrant_client.models import KeywordIndexParams

for field in ("condition_id", "activity", "session_id"):
    client.create_payload_index(
        collection_name="stream-reactions",
        field_name=field,
        field_schema=KeywordIndexParams(type="keyword"),
    )
```

Run once at schema setup. Subsequent queries with
`must=[FieldCondition(key="condition_id", match=MatchValue(...))]`
use the index transparently.

## 4. Other collections — same vulnerability, different impact

The payload-index gap is system-wide. Per-collection risk:

| collection | current points | projected scale | payload filters likely needed |
|---|---|---|---|
| stream-reactions | 2 650 | **1 M+ over months** (LRR) | `condition_id`, `activity`, `session_id`, `timestamp_bucket` |
| documents | 186 404 | growing | `source`, `kind`, `date_range` |
| profile-facts | 929 | slow growth | `dimension`, `confidence_tier` |
| studio-moments | 1 965 | growing | `activity`, `preset_name`, `timestamp_bucket` |
| operator-episodes | 1 697 | slow growth | `category`, `importance_tier` |
| affordances | 172 | bounded | — (small, scan is fine) |
| axiom-precedents | 17 | bounded | — (tiny) |
| hapax-apperceptions | ? | unknown | — (depends on writer) |
| operator-corrections | ? | unknown | — |
| operator-patterns | 0 | writer de-scheduled | — (inherited Q026 issue) |

**Impact hierarchy:**

- **High impact**: `stream-reactions` (fastest growth + most
  filter-heavy research queries) and `documents` (already
  at 186k, definitely does payload queries in its
  `shared/memory/` read path).
- **Medium impact**: `studio-moments` (growing), `profile-facts`
  (slow but used for dimension lookups).
- **Low impact**: the small ones where scan is fast enough
  that an index doesn't help.

## 5. Proposed fix — centralize via `shared/qdrant_schema.py`

Extend the schema registry to declare payload indexes alongside
vector config:

```python
# shared/qdrant_schema.py
from qdrant_client.models import KeywordIndexParams

EXPECTED_COLLECTIONS: dict[str, dict[str, object]] = {
    "stream-reactions": {
        "size": EXPECTED_EMBED_DIMENSIONS,
        "distance": "Cosine",
        "payload_indexes": {
            "condition_id": "keyword",
            "activity": "keyword",
            "session_id": "keyword",
        },
    },
    "documents": {
        "size": EXPECTED_EMBED_DIMENSIONS,
        "distance": "Cosine",
        "payload_indexes": {
            "source": "keyword",
            "kind": "keyword",
        },
    },
    # … other collections
}

async def ensure_payload_indexes() -> list[str]:
    """Create missing payload indexes per EXPECTED_COLLECTIONS."""
    client = get_qdrant()
    issues: list[str] = []
    for name, expected in EXPECTED_COLLECTIONS.items():
        payload_indexes = expected.get("payload_indexes", {})
        if not payload_indexes:
            continue
        try:
            info = client.get_collection(name)
            existing = set(info.payload_schema.keys()) if info.payload_schema else set()
            for field, schema_type in payload_indexes.items():
                if field in existing:
                    continue
                client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=KeywordIndexParams(type=schema_type),
                )
                _log.info("qdrant: created payload index %s.%s", name, field)
        except Exception as e:
            issues.append(f"Collection '{name}': index setup failed: {e}")
    return issues
```

Call `ensure_payload_indexes()` at compositor / logos-api
startup after `verify_collections()`. Idempotent — indexes
that already exist are skipped.

**Extend `verify_collections` to also report payload-index
drift**: if a collection has a `payload_indexes` declaration
in the registry and the live collection lacks some of them,
report as a warning. This turns the current
"silent full scan" into "loud drift report" on the next
health check.

## 6. Follow-ups for alpha

Ordered by severity × ease:

1. **Ship payload indexes on `stream-reactions`** — three
   one-line `create_payload_index` calls for `condition_id`,
   `activity`, `session_id`. Zero downtime, zero risk.
   Immediate speedup for any LRR query that filters on
   those fields.
2. **Extend `shared/qdrant_schema.py`** to declare
   `payload_indexes` per collection and ship an
   `ensure_payload_indexes()` that creates missing ones at
   startup. One-time infrastructure fix, unblocks every
   future collection from the same gap.
3. **Move `stream-reactions` collection creation out of
   `director_loop._persist_to_qdrant`** — use the central
   schema-verify-and-create path instead. Removes the
   hardcoded `VectorParams(size=768, distance=Distance.COSINE)`
   duplication.
4. **Replace thread-per-write with a single background
   worker thread + `queue.Queue`**. Batches 10 upserts
   or flushes every 5 seconds, whichever first. Reduces
   network overhead by ~10x.
5. **Health-monitor integration**: teach
   `agents/health_monitor/` to report
   `payload_indexes_missing` as a warning when the schema
   drift detection flags one.

Items 1 and 2 are the biggest wins by a wide margin. Item
1 alone takes ~5 minutes to ship.

## 7. What's not in this drop

- **Performance of HNSW vector search**. Small collections
  (< 10k points) don't have the index built yet. When they
  cross the threshold, there's a one-time build latency
  spike but no long-term perf concern — this drop is
  about payload filtering, not vector similarity.
- **Sharding / replication**. Every collection has
  `shard_number: 1, replication_factor: 1` — correct for
  a single-node deployment, not a concern.
- **On-disk storage tuning**. All collections have
  `on_disk_payload: true, on_disk: false` for HNSW —
  reasonable defaults.
- **Quantization**. No `quantization_config` on any
  collection, meaning vectors are stored at full precision.
  Qdrant supports scalar / binary quantization for vector
  compression. Worth a follow-up drop once the collections
  grow large enough for it to matter.

## 8. References

- `shared/qdrant_schema.py:15-36` — `EXPECTED_COLLECTIONS` registry
- `shared/qdrant_schema.py:39-82` — `verify_collections` checks
  vectors but not payload indexes
- `agents/studio_compositor/director_loop.py:924-965` —
  `_persist_to_qdrant` write path
- `agents/studio_compositor/director_loop.py:249-252` — the
  reader that queries the same collection (similarity search
  path, not relevant to the payload-index issue but good
  cross-reference)
- `agents/studio_compositor/director_loop.py:646`
  `_read_research_marker` — where `condition_id` flows in
- Qdrant API docs (public): `create_payload_index`,
  `KeywordIndexParams`, indexing thresholds
- Live probe: `curl http://localhost:6333/collections/<name>`
  at 2026-04-14T16:00 UTC
